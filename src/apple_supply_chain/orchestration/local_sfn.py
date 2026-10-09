"""A small, local interpreter for the subset of Amazon States Language this pipeline uses.

It executes ``state_machine.asl.json`` - the very definition Terraform deploys - by calling
the Lambda handlers in-process, so the orchestration logic (parallel extraction, retries,
the optional-source catch, DQ gates) is exercised on every local run and in CI.

Supported: Task (``arn:aws:states:::lambda:invoke`` with Parameters / ResultSelector /
ResultPath / OutputPath, Retry, Catch), Parallel, Choice (BooleanEquals, StringEquals,
NumericGreaterThanEquals), Pass (Result, ResultPath), Succeed, Fail. JSONPath is limited to
dotted paths (``$.a.b``), ``$`` and the context object ``$$.Execution.Name``.
This is a test harness, not a Step Functions emulator; anything else raises.
"""

from __future__ import annotations

import copy
import json
import re
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from importlib import resources
from typing import Any

LAMBDA_INVOKE = "arn:aws:states:::lambda:invoke"
_PLACEHOLDER = re.compile(r"^\$\{(\w+)\}$")


class StatesError(Exception):
    def __init__(self, error: str, cause: str = "") -> None:
        super().__init__(f"{error}: {cause}")
        self.error = error
        self.cause = cause


class ExecutionFailedError(RuntimeError):
    def __init__(self, error: str, cause: str, history: list[dict]) -> None:
        super().__init__(f"execution failed: {error} ({cause})")
        self.error = error
        self.cause = cause
        self.history = history


def load_definition() -> dict:
    ref = resources.files("apple_supply_chain.orchestration").joinpath("state_machine.asl.json")
    return json.loads(ref.read_text(encoding="utf-8"))


# ---------------------------------------------------------------- JSONPath helpers
def _get(data: Any, path: str, ctx: dict) -> Any:
    if path.startswith("$$."):
        data, path = ctx, "$." + path[3:]
    if path == "$":
        return data
    if not path.startswith("$."):
        raise StatesError("States.Runtime", f"unsupported path {path!r}")
    cur = data
    for part in path[2:].split("."):
        if not isinstance(cur, dict) or part not in cur:
            raise StatesError("States.Runtime", f"path {path!r} not found")
        cur = cur[part]
    return cur


def _set(data: Any, path: str | None, value: Any) -> Any:
    if path is None:
        return data
    if path == "$":
        return value
    out = copy.deepcopy(data) if isinstance(data, dict) else {}
    cur = out
    parts = path[2:].split(".")
    for part in parts[:-1]:
        cur = cur.setdefault(part, {})
    cur[parts[-1]] = value
    return out


def _render(template: Any, data: Any, ctx: dict) -> Any:
    if isinstance(template, dict):
        out = {}
        for k, v in template.items():
            if k.endswith(".$"):
                out[k[:-2]] = _get(data, v, ctx)
            else:
                out[k] = _render(v, data, ctx)
        return out
    if isinstance(template, list):
        return [_render(v, data, ctx) for v in template]
    return template


def _matches(errors: list[str], error: str) -> bool:
    return (
        "States.ALL" in errors
        or error in errors
        or (error != "States.Runtime" and "States.TaskFailed" in errors)
    )


# ------------------------------------------------------------------- interpreter
@dataclass
class LocalStateMachine:
    definition: dict
    functions: dict[str, Callable[[dict, Any], dict]]
    sleep: Callable[[float], None] = time.sleep
    retry_scale: float = 1.0  # tests set 0 to skip back-off waits
    history: list[dict] = field(default_factory=list)

    def _event(self, event: str, state: str, **detail: Any) -> None:
        self.history.append(
            {
                "ts": datetime.now(UTC).isoformat(timespec="milliseconds"),
                "type": event,
                "state": state,
                **detail,
            }
        )

    def _invoke(self, state: dict, payload: Any) -> Any:
        if state.get("Resource") != LAMBDA_INVOKE:
            raise StatesError("States.Runtime", f"unsupported resource {state.get('Resource')}")
        name = payload.get("FunctionName", "")
        m = _PLACEHOLDER.match(name)
        key = m.group(1) if m else name
        if key not in self.functions:
            raise StatesError("States.Runtime", f"no local function for {name!r}")
        try:
            result = self.functions[key](payload.get("Payload", {}), None)
        except StatesError:
            raise
        except Exception as exc:
            raise StatesError(type(exc).__name__, str(exc)) from exc
        return {"StatusCode": 200, "Payload": json.loads(json.dumps(result, default=str))}

    def _task(self, name: str, state: dict, data: Any, ctx: dict) -> Any:
        params = _render(state.get("Parameters", {}), data, ctx)
        attempts: dict[int, int] = {}
        while True:
            try:
                raw = self._invoke(state, params)
                break
            except StatesError as err:
                # As in AWS, only the first retrier whose ErrorEquals matches applies.
                rules = list(enumerate(state.get("Retry", [])))
                match = next(
                    ((i, r) for i, r in rules if _matches(r["ErrorEquals"], err.error)), None
                )
                if match is None or attempts.get(match[0], 0) >= match[1].get("MaxAttempts", 3):
                    raise
                i, rule = match
                n = attempts.get(i, 0)
                attempts[i] = n + 1
                self._event("TaskRetry", name, error=err.error, attempt=n + 1)
                self.sleep(
                    rule.get("IntervalSeconds", 1)
                    * rule.get("BackoffRate", 2.0) ** n
                    * self.retry_scale
                )
        result = _render(state["ResultSelector"], raw, ctx) if "ResultSelector" in state else raw
        out = _set(data, state.get("ResultPath", "$"), result)
        return _get(out, state.get("OutputPath", "$"), ctx)

    def _choice(self, state: dict, data: Any, ctx: dict) -> str:
        for rule in state["Choices"]:
            value = _get(data, rule["Variable"], ctx)
            if "BooleanEquals" in rule and value is rule["BooleanEquals"]:
                return rule["Next"]
            if "StringEquals" in rule and value == rule["StringEquals"]:
                return rule["Next"]
            if "NumericGreaterThanEquals" in rule and value >= rule["NumericGreaterThanEquals"]:
                return rule["Next"]
        if "Default" not in state:
            raise StatesError("States.NoChoiceMatched", "no choice matched")
        return state["Default"]

    def _run(self, machine: dict, data: Any, ctx: dict) -> Any:
        name = machine["StartAt"]
        while True:
            state = machine["States"][name]
            kind = state["Type"]
            self._event("StateEntered", name, state_type=kind)
            try:
                if kind == "Task":
                    data = self._task(name, state, data, ctx)
                elif kind == "Parallel":
                    results = [
                        self._run(branch, copy.deepcopy(data), ctx) for branch in state["Branches"]
                    ]
                    data = _set(data, state.get("ResultPath", "$"), results)
                elif kind == "Pass":
                    data = _set(data, state.get("ResultPath", "$"), state.get("Result", data))
                elif kind == "Choice":
                    self._event("StateExited", name)
                    name = self._choice(state, data, ctx)
                    continue
                elif kind == "Succeed":
                    self._event("StateExited", name)
                    return data
                elif kind == "Fail":
                    raise StatesError(state.get("Error", "States.Fail"), state.get("Cause", ""))
                else:
                    raise StatesError("States.Runtime", f"unsupported state type {kind}")
            except StatesError as err:
                handler = next(
                    (c for c in state.get("Catch", []) if _matches(c["ErrorEquals"], err.error)),
                    None,
                )
                if handler is None or kind == "Fail":
                    self._event("StateFailed", name, error=err.error, cause=err.cause[:500])
                    raise
                self._event("StateCaught", name, error=err.error)
                data = _set(
                    data, handler.get("ResultPath", "$"), {"Error": err.error, "Cause": err.cause}
                )
                name = handler["Next"]
                continue
            self._event("StateExited", name)
            if state.get("End"):
                return data
            name = state["Next"]

    def execute(self, execution_name: str, data: Any | None = None) -> Any:
        self.history = []
        ctx = {"Execution": {"Name": execution_name, "StartTime": datetime.now(UTC).isoformat()}}
        try:
            return self._run(self.definition, data if data is not None else {}, ctx)
        except StatesError as err:
            raise ExecutionFailedError(err.error, err.cause, self.history) from err
