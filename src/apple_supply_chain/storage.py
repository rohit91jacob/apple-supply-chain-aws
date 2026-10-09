"""Object storage: one interface, two backends.

``LocalObjectStore`` lays buckets out as directories (``<data_dir>/lake/<bucket>/<key>``),
which is what runs on a laptop. ``S3ObjectStore`` uses boto3 and therefore works unchanged
against moto (unit tests), LocalStack (CI) and real S3; set ``AWS_ENDPOINT_URL`` to point it
at an emulator.
"""

from __future__ import annotations

import json
import os
from collections.abc import Iterator
from pathlib import Path
from typing import Protocol

from apple_supply_chain.config import Settings


class ObjectStore(Protocol):
    def put_bytes(
        self, bucket: str, key: str, data: bytes, *, metadata: dict[str, str] | None = None
    ) -> None: ...
    def get_bytes(self, bucket: str, key: str) -> bytes: ...
    def exists(self, bucket: str, key: str) -> bool: ...
    def list_keys(self, bucket: str, prefix: str = "") -> Iterator[str]: ...


class LocalObjectStore:
    def __init__(self, root: Path) -> None:
        self.root = root

    def _path(self, bucket: str, key: str) -> Path:
        if key.startswith("/") or ".." in key.split("/"):
            raise ValueError(f"unsafe object key: {key!r}")
        return self.root / bucket / key

    def put_bytes(
        self, bucket: str, key: str, data: bytes, *, metadata: dict[str, str] | None = None
    ) -> None:
        path = self._path(bucket, key)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_bytes(data)
        tmp.replace(path)  # atomic on the same filesystem
        if metadata:
            path.with_name(path.name + ".meta.json").write_text(json.dumps(metadata, indent=2))

    def get_bytes(self, bucket: str, key: str) -> bytes:
        return self._path(bucket, key).read_bytes()

    def exists(self, bucket: str, key: str) -> bool:
        return self._path(bucket, key).is_file()

    def list_keys(self, bucket: str, prefix: str = "") -> Iterator[str]:
        base = self.root / bucket
        if not base.exists():
            return
        for path in sorted(base.rglob("*")):
            if path.is_file() and not path.name.endswith((".meta.json", ".tmp")):
                key = path.relative_to(base).as_posix()
                if key.startswith(prefix):
                    yield key


class S3ObjectStore:
    def __init__(self, client=None) -> None:
        if client is None:
            import boto3  # noqa: PLC0415 - boto3 import is slow; only pay for it when used

            client = boto3.client("s3", endpoint_url=os.environ.get("AWS_ENDPOINT_URL") or None)
        self.client = client

    def put_bytes(
        self, bucket: str, key: str, data: bytes, *, metadata: dict[str, str] | None = None
    ) -> None:
        self.client.put_object(Bucket=bucket, Key=key, Body=data, Metadata=metadata or {})

    def get_bytes(self, bucket: str, key: str) -> bytes:
        return self.client.get_object(Bucket=bucket, Key=key)["Body"].read()

    def exists(self, bucket: str, key: str) -> bool:
        from botocore.exceptions import ClientError  # noqa: PLC0415

        try:
            self.client.head_object(Bucket=bucket, Key=key)
        except ClientError as exc:
            if exc.response.get("Error", {}).get("Code") in {"404", "NoSuchKey", "NotFound"}:
                return False
            raise
        return True

    def list_keys(self, bucket: str, prefix: str = "") -> Iterator[str]:
        paginator = self.client.get_paginator("list_objects_v2")
        for page in paginator.paginate(Bucket=bucket, Prefix=prefix):
            for obj in page.get("Contents", []):
                yield obj["Key"]


def build_store(settings: Settings) -> ObjectStore:
    if settings.store == "s3":
        return S3ObjectStore()
    return LocalObjectStore(settings.lake_dir)
