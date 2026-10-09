"""The raw (bronze) zone: immutable, content-addressed objects plus a ``_latest`` pointer.

Layout in the raw bucket::

    source=<source>/dataset=<dataset>/item=<item>/<sha256>.<ext>    immutable payload
    source=<source>/dataset=<dataset>/item=<item>/_latest.json      pointer + lineage

Landing the same bytes twice is a no-op (same hash, pointer unchanged), so extractors are
safe to retry and re-run: Step Functions retries, weekly refreshes and manual backfills
never duplicate data. A changed payload (e.g. a restated filing) lands as a new object and
moves the pointer; earlier versions stay addressable for audit.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from datetime import UTC, datetime

from apple_supply_chain.storage import ObjectStore


@dataclass(frozen=True)
class RawObject:
    source: str
    dataset: str
    item: str
    sha256: str
    key: str
    bytes: int
    source_url: str
    fetched_at: str
    content_type: str
    status: str  # "new" | "unchanged"


def _prefix(source: str, dataset: str, item: str) -> str:
    safe_item = item.replace("/", "_")
    return f"source={source}/dataset={dataset}/item={safe_item}"


def land(
    store: ObjectStore,
    bucket: str,
    *,
    source: str,
    dataset: str,
    item: str,
    payload: bytes,
    ext: str,
    source_url: str,
    content_type: str = "application/octet-stream",
) -> RawObject:
    """Write ``payload`` unless the current pointer already references identical bytes."""
    digest = hashlib.sha256(payload).hexdigest()
    prefix = _prefix(source, dataset, item)
    pointer_key = f"{prefix}/_latest.json"
    key = f"{prefix}/{digest}.{ext}"
    if store.exists(bucket, pointer_key):
        current = json.loads(store.get_bytes(bucket, pointer_key))
        if current.get("sha256") == digest:
            return RawObject(**{**current, "status": "unchanged"})
    if not store.exists(bucket, key):
        store.put_bytes(
            bucket,
            key,
            payload,
            metadata={"source-url": source_url[:1024], "sha256": digest},
        )
    obj = RawObject(
        source=source,
        dataset=dataset,
        item=item,
        sha256=digest,
        key=key,
        bytes=len(payload),
        source_url=source_url,
        fetched_at=datetime.now(UTC).isoformat(timespec="seconds"),
        content_type=content_type,
        status="new",
    )
    pointer = {k: v for k, v in asdict(obj).items() if k != "status"}
    store.put_bytes(bucket, pointer_key, json.dumps(pointer, indent=2).encode())
    return obj


def latest(store: ObjectStore, bucket: str, source: str, dataset: str) -> list[dict]:
    """All ``_latest`` pointers for a source/dataset, sorted by item."""
    prefix = f"source={source}/dataset={dataset}/"
    pointers = [
        json.loads(store.get_bytes(bucket, key))
        for key in store.list_keys(bucket, prefix)
        if key.endswith("/_latest.json")
    ]
    return sorted(pointers, key=lambda p: p["item"])


def read_latest(store: ObjectStore, bucket: str, pointer: dict) -> bytes:
    return store.get_bytes(bucket, pointer["key"])
