"""Shared fixtures: an isolated data dir and an offline fixture tree per test session."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from apple_supply_chain.config import Settings
from apple_supply_chain.fixtures import build_fixture_tree

# Tests never run on EC2: stop boto3 / pyarrow's AWS SDK from probing the instance-metadata
# endpoint for credentials or region (slow, and a source of flaky native-client start-up).
os.environ.setdefault("AWS_EC2_METADATA_DISABLED", "true")

REPO = Path(__file__).resolve().parents[1]
COMMITTED = REPO / "tests" / "fixtures"

FIXTURE_ENV = {
    "ASC_SOURCE_MODE": "fixtures",
    "ASC_TRADE_YEARS": "2022-2024",
    "ASC_STORE": "local",
    "ASC_CATALOG": "sql",
    "ASC_LOG_FORMAT": "text",
    "DBT_TARGET": "dev",
}


@pytest.fixture(scope="session")
def fixture_tree(tmp_path_factory) -> Path:
    out = tmp_path_factory.mktemp("fixtures")
    build_fixture_tree(out, COMMITTED)
    return out


@pytest.fixture
def fixture_settings(tmp_path, fixture_tree, monkeypatch) -> Settings:
    """Settings for an offline run in a fresh data directory."""
    for k in list(os.environ):
        if k.startswith("ASC_") or k in {"CENSUS_API_KEY", "AWS_ENDPOINT_URL"}:
            monkeypatch.delenv(k, raising=False)
    for k, v in FIXTURE_ENV.items():
        monkeypatch.setenv(k, v)
    monkeypatch.setenv("ASC_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("ASC_FIXTURES_DIR", str(fixture_tree))
    return Settings.from_env()
