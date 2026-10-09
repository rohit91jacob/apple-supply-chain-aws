"""Silver Iceberg -> DuckDB -> dbt marts -> gold Iceberg.

Locally, dbt runs on DuckDB (the stand-in for Athena). Each run loads the *current* Iceberg
snapshot of every silver table into the DuckDB schema ``silver`` (the same names the Athena
target reads from the Glue database ``asc_silver``), runs ``dbt build`` (models + tests), and
writes the marts back to Iceberg (namespace ``gold``) so downstream consumers read one format.
"""

from __future__ import annotations

import os
from pathlib import Path

import duckdb

from apple_supply_chain.config import Settings
from apple_supply_chain.lakehouse.iceberg import (
    build_catalog,
    list_tables,
    ns,
    read_table,
    write_table,
)
from apple_supply_chain.logs import get_logger

log = get_logger(__name__)

MART_SCHEMA = "marts"


def dbt_dir() -> Path:
    env = os.environ.get("ASC_DBT_DIR")
    if env:
        return Path(env).resolve()
    return Path(__file__).resolve().parents[2] / "dbt"


def connect(settings: Settings, *, read_only: bool = False) -> duckdb.DuckDBPyConnection:
    settings.duckdb_path.parent.mkdir(parents=True, exist_ok=True)
    return duckdb.connect(str(settings.duckdb_path), read_only=read_only)


def load_silver(settings: Settings) -> dict[str, int]:
    catalog = build_catalog(settings)
    counts: dict[str, int] = {}
    con = connect(settings)
    try:
        con.execute("create schema if not exists silver")
        for ident in list_tables(catalog, ns(settings, "silver")):
            name = ident.split(".", 1)[1]
            arrow = read_table(catalog, ident)
            con.execute(f'create or replace table silver."{name}" as select * from arrow')
            counts[name] = arrow.num_rows
    finally:
        con.close()
    return counts


def _release_dbt_duckdb() -> None:
    """Close the DuckDB handle dbt-duckdb keeps open after an in-process ``dbtRunner`` call.

    dbt-duckdb caches its environment (and the open database file) at class level, so the file
    stays locked after ``invoke`` returns. On Windows that lock makes the next reader of the
    file (``_push_warehouse`` copying it to S3) fail with PermissionError; on Linux it only
    delays the release. There is no public API for this, hence the private attribute.
    """
    try:
        from dbt.adapters.duckdb.connections import DuckDBConnectionManager  # noqa: PLC0415
    except ImportError:  # pragma: no cover - dbt-duckdb is a runtime dependency
        return
    with DuckDBConnectionManager._LOCK:
        env = DuckDBConnectionManager._ENV
        DuckDBConnectionManager._ENV = None
    if env is not None:
        env.close()


def run_dbt(settings: Settings, args: list[str]) -> None:
    from dbt.cli.main import dbtRunner  # noqa: PLC0415 - dbt import is slow

    project = dbt_dir()
    env_backup = os.environ.get("ASC_DUCKDB_PATH")
    os.environ["ASC_DUCKDB_PATH"] = settings.duckdb_path.as_posix()
    try:
        result = dbtRunner().invoke(
            [
                *args,
                "--project-dir",
                str(project),
                "--profiles-dir",
                str(project),
                "--target",
                os.environ.get("DBT_TARGET", "dev"),
            ]
        )
    finally:
        _release_dbt_duckdb()
        if env_backup is None:
            os.environ.pop("ASC_DUCKDB_PATH", None)
        else:
            os.environ["ASC_DUCKDB_PATH"] = env_backup
    if not result.success:
        raise DbtFailedError(f"dbt {' '.join(args)} failed: {result.exception or 'see dbt log'}")


class DbtFailedError(RuntimeError):
    pass


def export_marts(settings: Settings, *, run_id: str = "") -> list[dict]:
    catalog = build_catalog(settings)
    # Same (read-write) configuration as dbt-duckdb's connection, which stays open in-process.
    con = connect(settings)
    try:
        names = [
            r[0]
            for r in con.execute(
                "select table_name from information_schema.tables "
                "where table_schema = ? and table_type = 'BASE TABLE' order by 1",
                [MART_SCHEMA],
            ).fetchall()
        ]
        tables = {n: con.execute(f'select * from {MART_SCHEMA}."{n}"').arrow() for n in names}
    finally:
        con.close()
    out = []
    for name, table in tables.items():
        if hasattr(table, "read_all"):
            table = table.read_all()
        out.append(write_table(catalog, f"{ns(settings, 'gold')}.{name}", table, run_id=run_id))
    return out


def build_marts(settings: Settings, *, run_id: str = "") -> dict:
    loaded = load_silver(settings)
    run_dbt(settings, ["build"])
    exported = export_marts(settings, run_id=run_id)
    return {"silver_loaded": loaded, "gold_tables": [e["table"] for e in exported]}
