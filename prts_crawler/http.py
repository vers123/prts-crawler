"""Minimal HTTP client with global rate limiting, gzip support and retries."""

from __future__ import annotations

import gzip
import json
import random
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import zlib
from typing import Any, Mapping

from .config import load_settings

RETRY_STATUS = {408, 425, 429, 500, 502, 503, 504}


class HttpError(RuntimeError):
    """Raised when a request cannot be completed after all retries."""

    def __init__(self, url: str, status: int | None, message: str) -> None:
        super().__init__(f"{message} [{status}] {url}")
        self.url = url
        self.status = status


class RateLimiter:
    """A shared token bucket so parallel workers stay polite to the wiki."""

    def __init__(self, rate: float) -> None:
        self._interval = 1.0 / rate if rate and rate > 0 else 0.0
        self._lock = threading.Lock()
        self._next_slot = 0.0

    def acquire(self) -> None:
        if not self._interval:
            return
        with self._lock:
            now = time.monotonic()
            wait = self._next_slot - now
            self._next_slot = max(now, self._next_slot) + self._interval
        if wait > 0:
            time.sleep(wait)


class HttpClient:
    def __init__(
        self,
        headers: Mapping[str, str] | None = None,
        *,
        rate: float | None = None,
        retries: int | None = None,
        timeout: float | None = None,
        verbose: bool = False,
    ) -> None:
        settings = load_settings()
        self.headers = dict(settings.headers)
        if headers:
            self.headers.update(headers)
        self.limiter = RateLimiter(settings.rate if rate is None else rate)
        self.retries = settings.retries if retries is None else retries
        self.timeout = settings.timeout if timeout is None else timeout
        self.verbose = verbose
        self.request_count = 0
        self._counter_lock = threading.Lock()

    def _log(self, message: str) -> None:
        if self.verbose:
            print(f"[http] {message}", flush=True)

    def get(
        self,
        url: str,
        params: Mapping[str, Any] | None = None,
        *,
        binary: bool = False,
    ) -> bytes | str:
        if params:
            url = f"{url}?{urllib.parse.urlencode(params)}"

        last_error: Exception | None = None
        for attempt in range(self.retries + 1):
            self.limiter.acquire()
            with self._counter_lock:
                self.request_count += 1
            try:
                request = urllib.request.Request(url, headers=self.headers)
                with urllib.request.urlopen(request, timeout=self.timeout) as response:
                    raw = response.read()
                    encoding = (response.headers.get("Content-Encoding") or "").lower()
                    if encoding == "gzip":
                        raw = gzip.decompress(raw)
                    elif encoding == "deflate":
                        raw = zlib.decompress(raw)
                    return raw if binary else raw.decode("utf-8", "replace")
            except urllib.error.HTTPError as exc:
                last_error = exc
                if exc.code not in RETRY_STATUS or attempt == self.retries:
                    raise HttpError(url, exc.code, "request failed") from exc
                delay = self._backoff(attempt, exc.headers.get("Retry-After"))
                self._log(f"{exc.code} -> retry in {delay:.1f}s ({url})")
            except (urllib.error.URLError, TimeoutError, OSError) as exc:
                last_error = exc
                if attempt == self.retries:
                    raise HttpError(url, None, f"network error: {exc}") from exc
                delay = self._backoff(attempt)
                self._log(f"network error -> retry in {delay:.1f}s ({url})")

        raise HttpError(url, None, f"exhausted retries: {last_error}")

    def get_json(self, url: str, params: Mapping[str, Any] | None = None) -> Any:
        payload = self.get(url, params)
        assert isinstance(payload, str)
        try:
            return json.loads(payload)
        except json.JSONDecodeError as exc:  # pragma: no cover - defensive
            raise HttpError(url, None, f"invalid JSON: {exc}") from exc

    @staticmethod
    def _backoff(attempt: int, retry_after: str | None = None) -> float:
        if retry_after:
            try:
                return max(1.0, float(retry_after))
            except ValueError:
                pass
        return min(30.0, (2**attempt) + random.uniform(0, 0.5))
