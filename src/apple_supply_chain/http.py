"""A polite HTTP client for public data sources.

* Every request carries a descriptive User-Agent (SEC requires one).
* Per-host minimum spacing between requests (SEC asks for <= 10 req/s; the UN Comtrade
  preview endpoint is rate-limited per IP), so a run never bursts.
* Retries with exponential backoff on 429/5xx and connection errors, honouring
  ``Retry-After``.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from urllib.parse import urlparse

import requests

from apple_supply_chain.logs import get_logger

log = get_logger(__name__)

RETRY_STATUS = {429, 500, 502, 503, 504}


class FetchError(RuntimeError):
    """Raised when a download fails after all retries."""


@dataclass
class HttpClient:
    user_agent: str
    min_interval_s: dict[str, float] = field(
        default_factory=lambda: {
            "data.sec.gov": 0.15,
            "www.sec.gov": 0.15,
            "comtradeapi.un.org": 3.0,
            "web.archive.org": 1.0,
        }
    )
    max_attempts: int = 5
    timeout_s: float = 60.0
    _last: dict[str, float] = field(default_factory=dict)
    _session: requests.Session = field(default_factory=requests.Session)

    def _throttle(self, host: str) -> None:
        wait = self.min_interval_s.get(host, 0.0) - (time.monotonic() - self._last.get(host, 0.0))
        if wait > 0:
            time.sleep(wait)
        self._last[host] = time.monotonic()

    def get(self, url: str, *, params: dict | None = None, headers: dict | None = None) -> bytes:
        host = urlparse(url).netloc
        hdrs = {"User-Agent": self.user_agent, "Accept-Encoding": "gzip, deflate"}
        hdrs.update(headers or {})
        last_error: str = ""
        for attempt in range(1, self.max_attempts + 1):
            self._throttle(host)
            try:
                resp = self._session.get(url, params=params, headers=hdrs, timeout=self.timeout_s)
            except requests.RequestException as exc:
                last_error = repr(exc)
            else:
                if resp.status_code == 200:
                    return resp.content
                last_error = f"HTTP {resp.status_code}: {resp.text[:200]!r}"
                if resp.status_code not in RETRY_STATUS:
                    raise FetchError(f"GET {url} failed: {last_error}")
                retry_after = resp.headers.get("Retry-After", "")
                if retry_after.isdigit():
                    time.sleep(min(int(retry_after), 60))
            if attempt == self.max_attempts:
                break
            delay = min(2**attempt, 30)
            log.warning("GET %s failed (%s); retry %d in %ss", url, last_error, attempt, delay)
            time.sleep(delay)
        raise FetchError(f"GET {url} failed: {last_error}")
