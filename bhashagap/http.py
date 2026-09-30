"""
A small, polite HTTP client for the Wikimedia APIs.

- Sends a descriptive User-Agent (required by Wikimedia's API policy).
- Caches every successful response on disk, so re-running the pipeline is
  instant and the raw responses can be published with the dataset.
- Retries with exponential backoff on 429 / 5xx / network errors.
- Limits request rate so we never hammer the servers.
"""

import hashlib
import json
import os
import threading
import time
from pathlib import Path

import requests

DEFAULT_UA = (
    "BhashaGap/1.0 (student data project measuring Indian-language Wikipedia coverage; "
    "https://github.com/Bhoomiairen/bhashagap)"
)


class HttpClient:
    def __init__(self, cache_dir: Path | None, requests_per_second: float = 8.0, user_agent: str | None = None,
                 max_retries: int = 5, offline: bool = False):
        self.cache_dir = Path(cache_dir) if cache_dir else None
        if self.cache_dir:
            self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": user_agent or os.environ.get("BHASHAGAP_USER_AGENT", DEFAULT_UA),
            "Accept": "application/json",
        })
        self.min_interval = 1.0 / requests_per_second if requests_per_second else 0
        self.max_retries = max_retries
        self.offline = offline
        self._lock = threading.Lock()
        self._last_request = 0.0
        self.stats = {"network": 0, "cache": 0, "errors": 0}

    # ---- cache -------------------------------------------------------------
    def _key(self, method: str, url: str, params: dict | None, data: dict | None) -> str:
        blob = json.dumps([method, url, sorted((params or {}).items()), sorted((data or {}).items())], ensure_ascii=False)
        return hashlib.sha1(blob.encode("utf-8")).hexdigest()

    def _cache_path(self, key: str) -> Path | None:
        return self.cache_dir / key[:2] / f"{key}.json" if self.cache_dir else None

    def _read_cache(self, key):
        path = self._cache_path(key)
        if path and path.exists():
            with self._lock:
                self.stats["cache"] += 1
            return json.loads(path.read_text("utf-8"))["body"]
        return None

    def _write_cache(self, key, url, params, body):
        path = self._cache_path(key)
        if not path:
            return
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps({"url": url, "params": params, "fetched_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "body": body}, ensure_ascii=False), "utf-8")
        tmp.replace(path)

    # ---- requests ----------------------------------------------------------
    def _throttle(self):
        with self._lock:
            wait = self._last_request + self.min_interval - time.monotonic()
            if wait > 0:
                time.sleep(wait)
            self._last_request = time.monotonic()

    def get_json(self, url: str, params: dict | None = None, method: str = "GET", data: dict | None = None,
                 allow_404: bool = False):
        """Return parsed JSON. With allow_404, a 404 returns None (and is cached as such)."""
        key = self._key(method, url, params, data)
        cached = self._read_cache(key)
        if cached is not None:
            if isinstance(cached, dict) and cached.get("__404__"):
                return None  # we already know this page doesn't exist
            return cached
        if self.offline:
            raise RuntimeError(f"Offline mode and no cached response for {url}")

        delay = 2.0
        for attempt in range(self.max_retries + 1):
            self._throttle()
            try:
                resp = self.session.request(method, url, params=params, data=data, timeout=60)
            except requests.RequestException as exc:
                err = exc
            else:
                with self._lock:
                    self.stats["network"] += 1
                if resp.status_code == 404 and allow_404:
                    self._write_cache(key, url, params, {"__404__": True})
                    return None
                if resp.status_code == 200:
                    body = resp.json()
                    self._write_cache(key, url, params, body)
                    return body
                if resp.status_code not in (429, 500, 502, 503, 504):
                    raise RuntimeError(f"HTTP {resp.status_code} for {resp.url}: {resp.text[:300]}")
                err = RuntimeError(f"HTTP {resp.status_code}")
                retry_after = resp.headers.get("Retry-After")
                if retry_after and retry_after.isdigit():
                    delay = max(delay, float(retry_after))
            if attempt == self.max_retries:
                with self._lock:
                    self.stats["errors"] += 1
                raise RuntimeError(f"Giving up on {url} after {self.max_retries} retries: {err}")
            time.sleep(delay)
            delay = min(delay * 2, 60)
