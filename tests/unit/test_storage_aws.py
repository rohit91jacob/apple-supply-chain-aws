"""Raw-zone landing on local disk and on S3, Glue registration and Step Functions, via moto."""

from __future__ import annotations

import json
import os

import boto3
import pytest
from moto import mock_aws

from apple_supply_chain import raw
from apple_supply_chain.config import Settings
from apple_supply_chain.orchestration.render import render_definition
from apple_supply_chain.storage import LocalObjectStore, S3ObjectStore

REGION = "eu-west-1"


@pytest.fixture
def aws_env(monkeypatch):
    for k, v in {
        "AWS_ACCESS_KEY_ID": "testing",
        "AWS_SECRET_ACCESS_KEY": "testing",
        "AWS_DEFAULT_REGION": REGION,
        "AWS_REGION": REGION,
    }.items():
        monkeypatch.setenv(k, v)
    monkeypatch.delenv("AWS_ENDPOINT_URL", raising=False)
    monkeypatch.delenv("AWS_PROFILE", raising=False)


def _land(store, bucket, payload: bytes):
    return raw.land(
        store,
        bucket,
        source="s",
        dataset="d",
        item="i",
        payload=payload,
        ext="json",
        source_url="https://example.org/x",
    )


def test_local_landing_is_idempotent(tmp_path):
    store = LocalObjectStore(tmp_path)
    first = _land(store, "raw", b'{"a": 1}')
    again = _land(store, "raw", b'{"a": 1}')
    changed = _land(store, "raw", b'{"a": 2}')
    assert (first.status, again.status, changed.status) == ("new", "unchanged", "new")
    assert again.sha256 == first.sha256 != changed.sha256
    # both versions stay addressable; the pointer moved to the new one
    keys = list(store.list_keys("raw"))
    assert len([k for k in keys if k.endswith(".json") and "_latest" not in k]) == 2
    assert raw.latest(store, "raw", "s", "d")[0]["sha256"] == changed.sha256


def test_local_store_rejects_path_traversal(tmp_path):
    with pytest.raises(ValueError, match="unsafe"):
        LocalObjectStore(tmp_path).put_bytes("raw", "../escape", b"x")


@mock_aws
def test_s3_landing_with_moto(aws_env):
    s3 = boto3.client("s3", region_name=REGION)
    s3.create_bucket(Bucket="asc-raw", CreateBucketConfiguration={"LocationConstraint": REGION})
    store = S3ObjectStore(s3)
    assert _land(store, "asc-raw", b"{}").status == "new"
    assert _land(store, "asc-raw", b"{}").status == "unchanged"
    assert not store.exists("asc-raw", "nope")
    pointer = raw.latest(store, "asc-raw", "s", "d")[0]
    assert raw.read_latest(store, "asc-raw", pointer) == b"{}"
    head = s3.head_object(Bucket="asc-raw", Key=pointer["key"])
    assert head["Metadata"]["sha256"] == pointer["sha256"]


@pytest.fixture
def moto_server(aws_env, monkeypatch):
    """A real HTTP endpoint (moto server mode): pyarrow's native S3 client cannot be
    patched in-process, so Iceberg-on-S3 is tested against moto over HTTP."""
    from moto.server import ThreadedMotoServer

    server = ThreadedMotoServer(ip_address="127.0.0.1", port=0)
    server.start()
    host, port = server.get_host_and_port()
    endpoint = f"http://{host}:{port}"
    monkeypatch.setenv("AWS_ENDPOINT_URL", endpoint)
    yield endpoint
    server.stop()


def test_iceberg_on_s3_and_glue_sync_with_moto_server(moto_server, tmp_path, monkeypatch):
    """Silver Iceberg tables written to (moto) S3, then registered in (moto) Glue."""
    import pyarrow as pa

    from apple_supply_chain.lakehouse.glue_sync import sync_to_glue
    from apple_supply_chain.lakehouse.iceberg import build_catalog, read_table, write_table

    s3 = boto3.client("s3", region_name=REGION, endpoint_url=moto_server)
    s3.create_bucket(Bucket="asc-curated", CreateBucketConfiguration={"LocationConstraint": REGION})
    monkeypatch.setenv("ASC_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("ASC_STORE", "s3")
    settings = Settings.from_env()
    assert settings.warehouse == "s3://asc-curated/warehouse"
    catalog = build_catalog(settings)
    write_table(catalog, "silver.t", pa.table({"x": [1, 2]}))
    write_table(catalog, "silver.t", pa.table({"x": [1, 2]}))  # rerun: same rows, new snapshot
    assert read_table(catalog, "silver.t").num_rows == 2
    keys = [o["Key"] for o in s3.list_objects_v2(Bucket="asc-curated")["Contents"]]
    assert any(k.endswith(".parquet") for k in keys) and any(
        k.endswith(".metadata.json") for k in keys
    )
    glue = boto3.client("glue", region_name=REGION, endpoint_url=moto_server)
    assert sync_to_glue(settings, client=glue) == {"asc_silver": ["t"]}
    table = glue.get_table(DatabaseName="asc_silver", Name="t")["Table"]
    assert table["Parameters"]["table_type"] == "ICEBERG"
    assert table["Parameters"]["metadata_location"].startswith("s3://asc-curated/")


@mock_aws
def test_state_machine_definition_accepted_by_stepfunctions(aws_env):
    iam = boto3.client("iam", region_name=REGION)
    role = iam.create_role(
        RoleName="sfn",
        AssumeRolePolicyDocument=json.dumps(
            {
                "Version": "2012-10-17",
                "Statement": [
                    {
                        "Effect": "Allow",
                        "Principal": {"Service": "states.amazonaws.com"},
                        "Action": "sts:AssumeRole",
                    }
                ],
            }
        ),
    )["Role"]["Arn"]
    sfn = boto3.client("stepfunctions", region_name=REGION)
    definition = render_definition("123456789012", REGION, "asc-dev")
    arn = sfn.create_state_machine(name="asc-dev-pipeline", definition=definition, roleArn=role)[
        "stateMachineArn"
    ]
    described = sfn.describe_state_machine(stateMachineArn=arn)
    assert json.loads(described["definition"])["StartAt"] == "Extract"


def test_no_real_aws_credentials_in_test_env():
    assert os.environ.get("AWS_ACCESS_KEY_ID") in (None, "testing")
