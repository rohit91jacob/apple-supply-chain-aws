"""URL fetchers. Extractors take a ``Fetcher`` so the same code runs live or offline.

``FixtureFetcher`` serves a mirrored tree of HTTP responses from ``tests/fixtures/http``:
``https://host/a/b?x=1`` maps to ``http/host/a/b`` (no query) or ``http/host/a/b@<sha1>``
(with a query; the hash is over the sorted, URL-encoded parameters). That way end-to-end
tests exercise exactly the parsing and landing code that runs against the real sources.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Protocol
from urllib.parse import urlencode, urlparse

from apple_supply_chain.config import Settings
from apple_supply_chain.http import FetchError, HttpClient


class Fetcher(Protocol):
    def get(self, url: str, params: dict | None = None) -> bytes: ...


def fixture_relpath(url: str, params: dict | None = None) -> str:
    parsed = urlparse(url)
    path = f"{parsed.netloc}{parsed.path}".rstrip("/")
    # Wayback URLs embed another URL ("/web/<ts>id_/https://..."): keep paths Windows-safe.
    path = path.replace("://", "/").replace(":", "_")
    query = dict(params or {})
    if parsed.query:
        for part in parsed.query.split("&"):
            k, _, v = part.partition("=")
            query[k] = v
    if query:
        canonical = urlencode(sorted((str(k), str(v)) for k, v in query.items()))
        path += "@" + hashlib.sha1(canonical.encode(), usedforsecurity=False).hexdigest()[:12]
    return path


class LiveFetcher:
    def __init__(self, client: HttpClient) -> None:
        self.client = client

    def get(self, url: str, params: dict | None = None) -> bytes:
        return self.client.get(url, params=params)


class FixtureFetcher:
    def __init__(self, root: Path) -> None:
        self.root = root

    def get(self, url: str, params: dict | None = None) -> bytes:
        path = self.root / fixture_relpath(url, params)
        if not path.is_file():
            raise FetchError(f"no fixture for {url} params={params} (expected {path})")
        return path.read_bytes()


def build_fetcher(settings: Settings, *, user_agent: str | None = None) -> Fetcher:
    if settings.source_mode == "fixtures":
        return FixtureFetcher(settings.fixtures_dir / "http")
    return LiveFetcher(HttpClient(user_agent=user_agent or settings.sec_user_agent))
