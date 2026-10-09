"""AWS Lambda entry points (one container image, one handler per function).

Terraform points each function's ``image_config.command`` at one of these, e.g.
``apple_supply_chain.lambdas.handlers.extract_sec_edgar``. Locally the Step Functions runner
calls the same functions in-process. Configuration comes from environment variables
(``ASC_*``), never from the event, so an event cannot redirect writes.
"""

from __future__ import annotations

from typing import Any

from apple_supply_chain.config import Settings
from apple_supply_chain.logs import configure_logging


def _settings() -> Settings:
    settings = Settings.from_env()
    configure_logging(settings.log_format)
    return settings


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

    return run(_settings(), run_id=_run_id(event))


def build_graph(event: dict | None = None, context: Any = None) -> dict:
    from apple_supply_chain.graph.build import build_graph_outputs  # noqa: PLC0415

    return build_graph_outputs(_settings(), run_id=_run_id(event))


def check_gold(event: dict | None = None, context: Any = None) -> dict:
    from apple_supply_chain.quality import run_gold_checks  # noqa: PLC0415

    return run_gold_checks(_settings())


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
