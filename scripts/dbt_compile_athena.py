"""Compile the dbt project for the Athena target without touching AWS.

dbt-athena creates boto3 clients while compiling (e.g. an STS identity lookup), so every AWS
call is pointed at an in-process moto server with dummy credentials, and the relation cache
is not populated. The compiled Trino SQL lands in dbt/target/compiled.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from moto.server import ThreadedMotoServer

DBT_DIR = Path(__file__).resolve().parents[1] / "dbt"


def main() -> int:
    server = ThreadedMotoServer(ip_address="127.0.0.1", port=0)
    server.start()
    host, port = server.get_host_and_port()
    os.environ.update(
        {
            "AWS_ENDPOINT_URL": f"http://{host}:{port}",
            "AWS_ACCESS_KEY_ID": "compile-only",
            "AWS_SECRET_ACCESS_KEY": "compile-only",
            "AWS_REGION": "eu-west-1",
            "AWS_DEFAULT_REGION": "eu-west-1",
        }
    )
    os.environ.pop("AWS_PROFILE", None)
    os.environ.pop("AWS_SESSION_TOKEN", None)
    try:
        from dbt.cli.main import dbtRunner  # noqa: PLC0415 - import after env is pointed at moto

        result = dbtRunner().invoke(
            [
                "compile",
                "--project-dir",
                str(DBT_DIR),
                "--profiles-dir",
                str(DBT_DIR),
                "--target",
                "athena",
                "--no-populate-cache",
            ]
        )
    finally:
        server.stop()
    return 0 if result.success else 1


if __name__ == "__main__":
    sys.exit(main())
