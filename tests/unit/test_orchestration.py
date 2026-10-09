"""The local ASL interpreter, the shipped definition and its rendering."""

from __future__ import annotations

import json

import pytest

from apple_supply_chain.lambdas.handlers import FUNCTIONS
from apple_supply_chain.orchestration.local_sfn import (
    ExecutionFailedError,
    LocalStateMachine,
    load_definition,
)
from apple_supply_chain.orchestration.render import function_name, render_definition


def _fake_functions(**overrides):
    def ok(name):
        return lambda event, ctx: {"source": name, "new": 0}

    funcs = {k: ok(k) for k in FUNCTIONS}
    funcs["build_silver_arn"] = lambda e, c: {"tables": {"silver.x": 1}}
    funcs["check_silver_arn"] = lambda e, c: {"passed": True, "errors": 0, "warnings": 0}
    funcs["build_marts_arn"] = lambda e, c: {"gold_tables": ["gold.x"]}
    funcs["build_graph_arn"] = lambda e, c: {"tables": {"graph_x": 1}}
    funcs["check_gold_arn"] = lambda e, c: {"passed": True, "errors": 0, "warnings": 0}
    funcs.update(overrides)
    return funcs


def _machine(**overrides):
    return LocalStateMachine(load_definition(), _fake_functions(**overrides), retry_scale=0.0)


def test_every_placeholder_has_a_handler():
    text = json.dumps(load_definition())
    import re

    placeholders = set(re.findall(r"\$\{(\w+)\}", text))
    assert placeholders == set(FUNCTIONS)


def test_happy_path_runs_all_stages_and_passes_run_id():
    seen = {}

    def silver(event, ctx):
        seen.update(event)
        return {"tables": {}}

    out = _machine(build_silver_arn=silver).execute("run-1")
    assert seen["run_id"] == "run-1"
    assert out["silver_dq"]["passed"] is True and out["gold_dq"]["passed"] is True
    assert len(out["extract"]) == 4


def test_silver_gate_routes_to_fail_state():
    m = _machine(check_silver_arn=lambda e, c: {"passed": False, "errors": 2, "warnings": 0})
    with pytest.raises(ExecutionFailedError) as exc:
        m.execute("run-dq")
    assert exc.value.error == "DataQualityFailed"
    entered = [h["state"] for h in exc.value.history if h["type"] == "StateEntered"]
    assert "BuildMarts" not in entered


def test_task_failure_is_retried_then_succeeds():
    calls = {"n": 0}

    def flaky(event, ctx):
        calls["n"] += 1
        if calls["n"] < 3:
            raise ConnectionError("upstream reset")
        return {"source": "sec_edgar"}

    m = _machine(extract_sec_edgar_arn=flaky)
    m.execute("run-retry")
    assert calls["n"] == 3
    assert sum(1 for h in m.history if h["type"] == "TaskRetry") == 2


def test_retries_exhausted_fail_the_execution():
    def broken(event, ctx):
        raise RuntimeError("always")

    with pytest.raises(ExecutionFailedError) as exc:
        _machine(extract_un_comtrade_arn=broken).execute("run-broken")
    assert exc.value.error == "RuntimeError"


def test_optional_census_failure_is_caught():
    def broken(event, ctx):
        raise RuntimeError("census down")

    out = _machine(extract_us_census_arn=broken).execute("run-census")
    census = next(r for r in out["extract"] if r.get("source") == "us_census")
    assert census["skipped"].startswith("extract failed")


def test_render_definition_substitutes_concrete_arns():
    text = render_definition("123456789012", "eu-west-1", "asc-dev")
    assert "${" not in text
    doc = json.loads(text)
    branch = doc["States"]["Extract"]["Branches"][0]["States"]["ExtractSecEdgar"]
    assert branch["Parameters"]["FunctionName"] == (
        "arn:aws:lambda:eu-west-1:123456789012:function:asc-dev-extract-sec-edgar"
    )
    assert function_name("check_gold_arn", "p") == "p-check-gold"
