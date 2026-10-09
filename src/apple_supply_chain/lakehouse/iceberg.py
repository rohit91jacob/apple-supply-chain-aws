"""Iceberg tables behind a Glue-style catalog.

Locally the catalog is pyiceberg's ``SqlCatalog`` on SQLite (a stand-in for the AWS Glue Data
Catalog) and the warehouse is a directory, or an ``s3://`` prefix when ``ASC_STORE=s3`` (moto or
LocalStack). With ``ASC_CATALOG=glue`` the same code uses pyiceberg's ``GlueCatalog``, which
is what Athena reads in AWS.

Writes are full-table ``overwrite`` commits: every run rebuilds a table from the raw zone, so a
re-run produces the same rows and only adds snapshots (time travel keeps the previous state).
"""

from __future__ import annotations

import os
from datetime import UTC, datetime

import pyarrow as pa
from pyiceberg.catalog import Catalog
from pyiceberg.exceptions import NoSuchTableError

from apple_supply_chain.config import Settings


def _s3_properties() -> dict[str, str]:
    props: dict[str, str] = {}
    endpoint = os.environ.get("AWS_ENDPOINT_URL")
    if endpoint:
        props["s3.endpoint"] = endpoint
        props["s3.path-style-access"] = "true"
    for env, key in (
        ("AWS_ACCESS_KEY_ID", "s3.access-key-id"),
        ("AWS_SECRET_ACCESS_KEY", "s3.secret-access-key"),
        ("AWS_SESSION_TOKEN", "s3.session-token"),
    ):
        if os.environ.get(env):
            props[key] = os.environ[env]
    region = os.environ.get("AWS_REGION") or os.environ.get("AWS_DEFAULT_REGION")
    if region:
        props["s3.region"] = region
    return props


def build_catalog(settings: Settings) -> Catalog:
    if settings.catalog == "glue":
        from pyiceberg.catalog.glue import GlueCatalog  # noqa: PLC0415

        return GlueCatalog("glue", **{"warehouse": settings.warehouse, **_s3_properties()})
    from pyiceberg.catalog.sql import SqlCatalog  # noqa: PLC0415

    settings.catalog_db.parent.mkdir(parents=True, exist_ok=True)
    props = {
        "uri": f"sqlite:///{settings.catalog_db.as_posix()}",
        "warehouse": settings.warehouse,
    }
    if settings.warehouse.startswith("s3://"):
        props.update(_s3_properties())
    return SqlCatalog("asc", **props)


def write_table(
    catalog: Catalog,
    identifier: str,
    table: pa.Table,
    *,
    run_id: str = "",
) -> dict:
    """Create-or-overwrite ``identifier`` with ``table``; returns snapshot info."""
    namespace = identifier.split(".", 1)[0]
    catalog.create_namespace_if_not_exists(namespace)
    try:
        ice = catalog.load_table(identifier)
        if [f.name for f in ice.schema().fields] != table.schema.names:
            # Schema changed (new column etc.): rebuild. Raw is the source of truth, so a
            # rebuild loses nothing; snapshots of the old layout are dropped with it.
            catalog.drop_table(identifier)
            ice = catalog.create_table(identifier, schema=table.schema)
    except NoSuchTableError:
        ice = catalog.create_table(identifier, schema=table.schema)
    props = {"asc.run-id": run_id or "manual", "asc.written-at": datetime.now(UTC).isoformat()}
    ice.overwrite(table, snapshot_properties=props)
    ice = catalog.load_table(identifier)
    snap = ice.current_snapshot()
    return {
        "table": identifier,
        "rows": table.num_rows,
        "snapshot_id": snap.snapshot_id if snap else None,
        "snapshots": len(ice.history()),
    }


def ns(settings: Settings, layer: str) -> str:
    """Catalog namespace for a layer (``silver`` locally, ``asc_silver`` in Glue)."""
    return f"{settings.namespace_prefix}{layer}"


def read_table(catalog: Catalog, identifier: str) -> pa.Table:
    return catalog.load_table(identifier).scan().to_arrow()


def list_tables(catalog: Catalog, namespace: str) -> list[str]:
    try:
        return sorted(".".join(t) for t in catalog.list_tables(namespace))
    except Exception:
        return []
