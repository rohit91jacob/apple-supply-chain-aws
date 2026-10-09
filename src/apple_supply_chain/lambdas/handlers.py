"""AWS Lambda entry points (one container image, one handler per function).

Terraform points each function's ``image_config.command`` at one of these, e.g.
``apple_supply_chain.lambdas.handlers.extract_sec_edgar``. Locally the Step Functions runner
calls the same functions in-process. Configuration comes from environment variables
(``ASC_*``), never from the event, so an event cannot redirect writes.
"""

from __future__ import annotations

import hashlib
import os
from typing import Any

from apple_supply_chain.config import Settings
from apple_supply_chain.logs import configure_logging

# In AWS each Lambda has its own /tmp, so the DuckDB file dbt builds is handed between the
# BuildMarts, BuildGraph and CheckGold functions through the curated bucket.
WAREHOUSE_KEY = "warehouse/duckdb/asc.duckdb"


def _settings() -> Settings:
    _load_census_key_from_ssm()
    settings = Settings.from_env()
    configure_logging(settings.log_format)
    return settings


def _load_census_key_from_ssm() -> None:
    """Optional: read the Census API key from an SSM SecureString (never from plain env)."""
    param = os.environ.get("ASC_CENSUS_KEY_SSM_PARAMETER", "")
    if not param or os.environ.get("CENSUS_API_KEY"):
        return
    import boto3  # noqa: PLC0415

    value = boto3.client("ssm").get_parameter(Name=param, WithDecryption=True)["Parameter"]["Value"]
    os.environ["CENSUS_API_KEY"] = value


def _sha256(path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _push_warehouse(settings: Settings) -> None:
    if settings.store != "s3" or not settings.duckdb_path.exists():
        return
    from apple_supply_chain.storage import build_store  # noqa: PLC0415
    from apple_supply_chain.warehouse import connect  # noqa: PLC0415

    con = connect(settings)
    try:
        con.execute("checkpoint")  # flush the WAL so the file alone is complete
    finally:
        con.close()
    data = settings.duckdb_path.read_bytes()
    build_store(settings).put_bytes(
        settings.curated_bucket,
        WAREHOUSE_KEY,
        data,
        metadata={"sha256": hashlib.sha256(data).hexdigest()},
    )


def _pull_warehouse(settings: Settings) -> None:
    if settings.store != "s3":
        return
    from apple_supply_chain.storage import build_store  # noqa: PLC0415

    store = build_store(settings)
    if not store.exists(settings.curated_bucket, WAREHOUSE_KEY):
        return
    remote = store.get_bytes(settings.curated_bucket, WAREHOUSE_KEY)
    path = settings.duckdb_path
    if path.exists() and _sha256(path) == hashlib.sha256(remote).hexdigest():
        return  # same process / warm container already has this snapshot
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(remote)


def _run_id(event: dict | None) -> str:
    return str((event or {}).get("run_id") or "manual")


def _extract(name: str) -> dict:
    from apple_supply_chain.extract import run_extractor  # noqa: PLC0415

    return run_extractor(name, _settings())


def extract_sec_edgar(event: dict | None = None, context: Any = None) -> dict:
    return _extract("sec_edgar")


def extract_apple_supplier_list(event: dict | None = None, context: Any = None) -> dict:
    return _extract("apple_supplier_list")


def extract_un_comtrade(event: dict | None = None, context: Any = None) -> dict:
    return _extract("un_comtrade")


def extract_us_census(event: dict | None = None, context: Any = None) -> dict:
    return _extract("us_census")


def build_silver(event: dict | None = None, context: Any = None) -> dict:
    from apple_supply_chain.transform.silver import build_silver as run  # noqa: PLC0415

    results = run(_settings(), run_id=_run_id(event))
    return {"tables": {r["table"]: r["rows"] for r in results}}


def check_silver(event: dict | None = None, context: Any = None) -> dict:
    from apple_supply_chain.quality import run_silver_checks  # noqa: PLC0415

    return run_silver_checks(_settings())


def build_marts(event: dict | None = None, context: Any = None) -> dict:
    from apple_supply_chain.warehouse import build_marts as run  # noqa: PLC0415

    settings = _settings()
    result = run(settings, run_id=_run_id(event))
    _push_warehouse(settings)
    return result


def build_graph(event: dict | None = None, context: Any = None) -> dict:
    from apple_supply_chain.graph.build import build_graph_outputs  # noqa: PLC0415

    settings = _settings()
    _pull_warehouse(settings)
    result = build_graph_outputs(settings, run_id=_run_id(event))
    _push_warehouse(settings)
    return result


def check_gold(event: dict | None = None, context: Any = None) -> dict:
    from apple_supply_chain.quality import run_gold_checks  # noqa: PLC0415

    settings = _settings()
    _pull_warehouse(settings)
    return run_gold_checks(settings)


# Placeholder in the ASL definition -> handler. Terraform maps the same names to ARNs.
FUNCTIONS = {
    "extract_sec_edgar_arn": extract_sec_edgar,
    "extract_apple_supplier_list_arn": extract_apple_supplier_list,
    "extract_un_comtrade_arn": extract_un_comtrade,
    "extract_us_census_arn": extract_us_census,
    "build_silver_arn": build_silver,
    "check_silver_arn": check_silver,
    "build_marts_arn": build_marts,
    "build_graph_arn": build_graph,
    "check_gold_arn": check_gold,
}
