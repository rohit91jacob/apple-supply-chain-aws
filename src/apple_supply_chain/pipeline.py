"""Run the Step Functions definition locally (the same ASL Terraform deploys)."""

from __future__ import annotations

import json
from datetime import UTC, datetime

from apple_supply_chain.config import Settings
from apple_supply_chain.lambdas.handlers import FUNCTIONS
from apple_supply_chain.logs import get_logger
from apple_supply_chain.orchestration.local_sfn import (
    ExecutionFailedError,
    LocalStateMachine,
    load_definition,
)

log = get_logger(__name__)

EXTRACT_KEYS = (
    "extract_sec_edgar_arn",
    "extract_apple_supplier_list_arn",
    "extract_un_comtrade_arn",
    "extract_us_census_arn",
)


def new_run_id() -> str:
    return "run-" + datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")


def run_pipeline(
    settings: Settings, *, run_id: str | None = None, skip_extract: bool = False
) -> dict:
    """Execute the state machine; returns ``{"status", "output"|"error", "history_file"}``."""
    run_id = run_id or new_run_id()
    functions = dict(FUNCTIONS)
    if skip_extract:
        for key in EXTRACT_KEYS:
            functions[key] = lambda _e, _c, k=key: {"source": k, "skipped": "--skip-extract"}
    machine = LocalStateMachine(load_definition(), functions)
    runs = settings.data_dir / "runs"
    runs.mkdir(parents=True, exist_ok=True)
    history_file = runs / f"{run_id}.json"
    try:
        output = machine.execute(run_id)
        result = {"status": "SUCCEEDED", "run_id": run_id, "output": output}
    except ExecutionFailedError as exc:
        result = {"status": "FAILED", "run_id": run_id, "error": exc.error, "cause": exc.cause}
    history_file.write_text(
        json.dumps({**result, "history": machine.history}, indent=2, default=str)
    )
    result["history_file"] = str(history_file)
    log.info("pipeline %s: %s", run_id, result["status"])
    return result
