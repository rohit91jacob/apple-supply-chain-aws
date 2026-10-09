"""Integration against LocalStack (CI job ``localstack``): S3 raw zone, Iceberg warehouse on
S3, Step Functions definition, and the fixture pipeline with ``ASC_STORE=s3``.

Needs ``AWS_ENDPOINT_URL`` pointing at LocalStack; skipped otherwise.
"""

from __future__ import annotations

import json
import os

import boto3
import pytest

from apple_supply_chain.config import Settings
from apple_supply_chain.lakehouse.glue_sync import glue_type  # noqa: F401 - import check
from apple_supply_chain.orchestration.render import render_definition
from apple_supply_chain.pipeline import run_pipeline

pytestmark = pytest.mark.localstack

ENDPOINT = os.environ.get("AWS_ENDPOINT_URL", "")
REGION = os.environ.get("AWS_DEFAULT_REGION", "eu-west-1")


@pytest.fixture
def s3_settings(fixture_settings, monkeypatch, tmp_path):
    if not ENDPOINT:
        pytest.skip("AWS_ENDPOINT_URL not set (LocalStack)")
    monkeypatch.setenv("AWS_ENDPOINT_URL", ENDPOINT)
    suffix = os.urandom(3).hex()
    raw_bucket, curated = f"asc-raw-{suffix}", f"asc-curated-{suffix}"
    s3 = boto3.client("s3", endpoint_url=ENDPOINT, region_name=REGION)
    for b in (raw_bucket, curated):
        s3.create_bucket(Bucket=b, CreateBucketConfiguration={"LocationConstraint": REGION})
    monkeypatch.setenv("ASC_STORE", "s3")
    monkeypatch.setenv("ASC_RAW_BUCKET", raw_bucket)
    monkeypatch.setenv("ASC_CURATED_BUCKET", curated)
    return Settings.from_env()


def test_fixture_pipeline_on_localstack_s3(s3_settings):
    result = run_pipeline(s3_settings, run_id="localstack-1")
    assert result["status"] == "SUCCEEDED", result
    s3 = boto3.client("s3", endpoint_url=ENDPOINT, region_name=REGION)
    raw_keys = [o["Key"] for o in s3.list_objects_v2(Bucket=s3_settings.raw_bucket)["Contents"]]
    assert any(k.endswith("_latest.json") for k in raw_keys)
    curated = [
        o["Key"]
        for o in s3.list_objects_v2(Bucket=s3_settings.curated_bucket, MaxKeys=1000)["Contents"]
    ]
    assert any(k.startswith("warehouse/silver") and k.endswith(".parquet") for k in curated)
    assert any(k.startswith("neptune/") for k in curated)
    again = run_pipeline(s3_settings, run_id="localstack-2")
    assert all(r["new"] == 0 for r in again["output"]["extract"] if r["source"] != "us_census")


def test_state_machine_on_localstack():
    if not ENDPOINT:
        pytest.skip("AWS_ENDPOINT_URL not set (LocalStack)")
    iam = boto3.client("iam", endpoint_url=ENDPOINT, region_name=REGION)
    trust = {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Effect": "Allow",
                "Principal": {"Service": "states.amazonaws.com"},
                "Action": "sts:AssumeRole",
            }
        ],
    }
    name = f"asc-sfn-{os.urandom(3).hex()}"
    role = iam.create_role(RoleName=name, AssumeRolePolicyDocument=json.dumps(trust))["Role"]["Arn"]
    sfn = boto3.client("stepfunctions", endpoint_url=ENDPOINT, region_name=REGION)
    arn = sfn.create_state_machine(
        name=name, definition=render_definition("000000000000", REGION, "asc-ci"), roleArn=role
    )["stateMachineArn"]
    assert sfn.describe_state_machine(stateMachineArn=arn)["status"] == "ACTIVE"
