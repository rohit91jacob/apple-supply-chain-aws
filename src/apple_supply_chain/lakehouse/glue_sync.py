"""Register the Iceberg tables in an AWS Glue Data Catalog (moto, LocalStack or AWS).

pyiceberg's ``GlueCatalog`` writes these entries itself when ``ASC_CATALOG=glue``. This
command mirrors a local SQLite-catalog warehouse into Glue so the catalog layout Athena would
read (``asc_silver`` / ``asc_gold`` databases, ``table_type=ICEBERG`` tables pointing at the
current metadata file) can be inspected and tested against an emulator.
"""

from __future__ import annotations

import contextlib
import os

import pyarrow as pa

from apple_supply_chain.config import Settings
from apple_supply_chain.lakehouse.iceberg import build_catalog, list_tables

_TYPES = {
    pa.string(): "string",
    pa.large_string(): "string",
    pa.float64(): "double",
    pa.int64(): "bigint",
    pa.int32(): "int",
    pa.bool_(): "boolean",
    pa.date32(): "date",
}


def glue_type(t: pa.DataType) -> str:
    if pa.types.is_decimal(t):
        return f"decimal({t.precision},{t.scale})"
    if pa.types.is_timestamp(t):
        return "timestamp"
    return _TYPES.get(t, "string")


def sync_to_glue(settings: Settings, *, database_prefix: str = "asc_", client=None) -> dict:
    if client is None:
        import boto3  # noqa: PLC0415

        client = boto3.client("glue", endpoint_url=os.environ.get("AWS_ENDPOINT_URL") or None)
    catalog = build_catalog(settings)
    registered: dict[str, list[str]] = {}
    for namespace in ("silver", "gold"):
        database = f"{database_prefix}{namespace}"
        with contextlib.suppress(client.exceptions.AlreadyExistsException):
            client.create_database(
                DatabaseInput={"Name": database, "Description": f"Iceberg {namespace} layer"}
            )
        for ident in list_tables(catalog, namespace):
            table = catalog.load_table(ident)
            schema = table.schema().as_arrow()
            name = ident.split(".", 1)[1]
            table_input = {
                "Name": name,
                "TableType": "EXTERNAL_TABLE",
                "Parameters": {
                    "table_type": "ICEBERG",
                    "metadata_location": table.metadata_location,
                },
                "StorageDescriptor": {
                    "Location": table.location(),
                    "Columns": [{"Name": f.name, "Type": glue_type(f.type)} for f in schema],
                },
            }
            try:
                client.create_table(DatabaseName=database, TableInput=table_input)
            except client.exceptions.AlreadyExistsException:
                client.update_table(DatabaseName=database, TableInput=table_input)
            registered.setdefault(database, []).append(name)
    return registered
