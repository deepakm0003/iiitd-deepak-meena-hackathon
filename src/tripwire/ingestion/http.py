"""Polite HTTP client shared by all collectors.

- Per-host token-bucket rate limits (kept below each provider's published limit).
- Retries with exponential backoff and jitter on 429, 5xx and network errors; honours Retry-After.
- Credentials travel in headers, so URLs (which may be logged) never contain secrets.
"""

import logging
import random
import threading
import time
from collections.abc import Callable
from urllib.parse import urlsplit

import httpx

log = logging.getLogger(__name__)
RETRY_STATUS = {429, 500, 502, 503, 504}


class HttpError(RuntimeError):
    def __init__(self, url: str, status: int | None, message: str) -> None:
        super().__init__(f"{message} (status={status}) for {url}")
        self.status = status


class TokenBucket:
    def __init__(
        self,
        rate_per_second: float,
        burst: int = 1,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.rate = rate_per_second
        self.capacity = float(burst)
        self.tokens = float(burst)
        self._clock = clock
        self._sleep = sleep
        self._last = clock()
        self._lock = threading.Lock()

    def acquire(self) -> None:
        with self._lock:
            while True:
                now = self._clock()
                self.tokens = min(self.capacity, self.tokens + (now - self._last) * self.rate)
                self._last = now
                if self.tokens >= 1:
                    self.tokens -= 1
                    return
                self._sleep((1 - self.tokens) / self.rate)


class HttpClient:
    def __init__(
        self,
        user_agent: str,
        limits: dict[str, TokenBucket] | None = None,
        max_retries: int = 3,
        timeout: float = 30.0,
        transport: httpx.BaseTransport | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.limits = limits or {}
        self.max_retries = max_retries
        self._sleep = sleep
        self._client = httpx.Client(
            timeout=timeout,
            follow_redirects=True,
            headers={"User-Agent": user_agent, "Accept-Encoding": "gzip, deflate"},
            transport=transport,
        )

    def get(self, url: str, *, params: dict | None = None, headers: dict | None = None) -> httpx.Response:
        host = urlsplit(url).hostname or ""
        bucket = self.limits.get(host)
        last_error = "unknown error"
        status = None
        for attempt in range(self.max_retries + 1):
            if bucket:
                bucket.acquire()
            try:
                response = self._client.get(url, params=params, headers=headers)
            except httpx.TransportError as exc:
                last_error, status = f"network error: {type(exc).__name__}", None
            else:
                if response.status_code < 400:
                    return response
                status = response.status_code
                if status not in RETRY_STATUS:
                    raise HttpError(url, status, "request failed")
                last_error = "retryable status"
                retry_after = response.headers.get("Retry-After", "")
                if retry_after.isdigit() and attempt < self.max_retries:
                    self._sleep(min(float(retry_after), 120.0))
                    continue
            if attempt < self.max_retries:
                delay = min(60.0, 2**attempt) + random.uniform(0, 0.5)
                log.warning("retrying %s in %.1fs (%s)", host, delay, last_error)
                self._sleep(delay)
        raise HttpError(url, status, f"giving up after {self.max_retries + 1} attempts: {last_error}")

    def close(self) -> None:
        self._client.close()
