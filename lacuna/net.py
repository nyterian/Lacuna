from __future__ import annotations
import hashlib
import ipaddress
import json
import socket
import sqlite3
import time
from pathlib import Path
from urllib.parse import urlsplit, urljoin
import httpx


class RequestLimit(RuntimeError):
    pass


def public_url(url: str) -> str:
    parsed = urlsplit(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError("Only HTTP/HTTPS URLs without embedded credentials are supported.")
    addresses = socket.getaddrinfo(parsed.hostname, parsed.port or (443 if parsed.scheme == "https" else 80))
    if any(not ipaddress.ip_address(a[4][0]).is_global for a in addresses):
        raise ValueError("Document requests to local or private network addresses are blocked.")
    return url


class WebClient:
    """Bounded, cached, redacted HTTP requests; partial failures stay visible."""
    def __init__(self, db: Path, budget: int = 60, cache: bool = True, transport=None):
        db.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(str(db))
        self.db.execute("CREATE TABLE IF NOT EXISTS cache (key TEXT PRIMARY KEY, created REAL, body TEXT)")
        self.db.execute("CREATE TABLE IF NOT EXISTS runs (id TEXT PRIMARY KEY, created TEXT, title TEXT, body TEXT)")
        self.http = httpx.Client(timeout=httpx.Timeout(20, connect=10), follow_redirects=False, transport=transport,
                                 headers={"User-Agent": "FieldLacuna/0.2 (open-source literature discovery)"})
        self.budget, self.use_cache, self.used = budget, cache, 0
        self.log: list[dict] = []
        self.mock = transport is not None
        self.last_request = 0.0

    def _budget(self):
        if self.used >= self.budget:
            raise RequestLimit("Request budget reached; discovery is incomplete.")
        self.used += 1
        delay = 0.35 - (time.monotonic() - self.last_request)
        if delay > 0 and not self.mock:
            time.sleep(delay)
        self.last_request = time.monotonic()

    def request(self, url: str, params=None, headers=None, source="", label="", max_bytes=12_000_000) -> bytes:
        # Credentials never enter the log. The cache key is a nonreversible hash.
        params = params or {}
        key = hashlib.sha256(json.dumps([url, params, headers or {}], sort_keys=True).encode()).hexdigest()
        entry = {"source": source, "endpoint": url.split("?")[0], "query": label,
                 "timestamp": time.time(), "cached": False, "status": "pending"}
        if self.use_cache and source != "pdf":
            row = self.db.execute("SELECT body FROM cache WHERE key=? AND created>?", (key, time.time()-86400)).fetchone()
            if row:
                entry.update(status="ok", cached=True, bytes=len(row[0].encode()))
                self.log.append(entry)
                return row[0].encode()
        try:
            current_url, current_params = url, params
            for redirect in range(6):
                if not self.mock:
                    public_url(current_url)
                response_data = None
                for attempt in range(3):
                    self._budget()
                    with self.http.stream("GET", current_url, params=current_params, headers=headers) as response:
                        if response.status_code in {429, 500, 502, 503, 504} and attempt < 2:
                            if not self.mock:
                                retry = response.headers.get("Retry-After", "1")
                                time.sleep(min(float(retry) if retry.isdigit() else 1, 3))
                            continue
                        if response.is_redirect:
                            location = response.headers.get("location")
                            if not location:
                                raise ValueError("Redirect location is missing.")
                            previous_host = urlsplit(current_url).netloc
                            current_url = urljoin(str(response.url), location)
                            current_params = {}
                            if urlsplit(current_url).netloc != previous_host:
                                headers = None
                            break
                        response.raise_for_status()
                        if int(response.headers.get("content-length", "0")) > max_bytes:
                            raise ValueError("Response size limit exceeded.")
                        chunks, size = [], 0
                        for chunk in response.iter_bytes():
                            size += len(chunk)
                            if size > max_bytes:
                                raise ValueError("Response size limit exceeded.")
                            chunks.append(chunk)
                        response_data = b"".join(chunks)
                    if response_data is not None:
                        break
                if response_data is not None:
                    entry.update(status="ok", bytes=len(response_data))
                    if self.use_cache and source != "pdf":
                        try:
                            body = response_data.decode("utf-8")
                            self.db.execute("INSERT OR REPLACE INTO cache VALUES (?, ?, ?)", (key, time.time(), body))
                            self.db.commit()
                        except UnicodeDecodeError:
                            pass
                    return response_data
            raise ValueError("Too many redirects.")
        except Exception as exc:
            # httpx error strings contain full URLs and API keys; never serialize them.
            status = getattr(getattr(exc, "response", None), "status_code", None)
            reason = f"HTTP {status}" if status else type(exc).__name__
            if isinstance(exc, (RequestLimit, ValueError)):
                reason = str(exc)
            entry.update(status="error", error=reason)
            raise RuntimeError(reason) from None
        finally:
            self.log.append(entry)

    def json(self, url, **kwargs):
        return json.loads(self.request(url, **kwargs))

    def save_run(self, result):
        self.db.execute("INSERT OR REPLACE INTO runs VALUES (?, ?, ?, ?)",
                        (result.run_id, result.started_at, result.profile.title, result.model_dump_json()))
        self.db.commit()

    def close(self):
        self.http.close()
        self.db.close()
