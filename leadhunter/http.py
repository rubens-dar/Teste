from __future__ import annotations

import json
import logging
import sqlite3
import threading
import time
from typing import Any
from urllib.parse import urlsplit

import requests

from leadhunter.config import CONFIG

log = logging.getLogger("leadhunter.http")

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)

_lock = threading.Lock()
_last_hit: dict[str, float] = {}
_local = threading.local()


class Cache:
    """Cache de respostas em SQLite. Reexecucoes nao repetem chamadas de rede."""

    def __init__(self, path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        with sqlite3.connect(self.path) as conn:
            conn.execute(
                "CREATE TABLE IF NOT EXISTS resp ("
                "k TEXT PRIMARY KEY, status INT, body TEXT, ts REAL)"
            )

    def get(self, key: str, max_age: float) -> tuple[int, str] | None:
        with sqlite3.connect(self.path) as conn:
            row = conn.execute("SELECT status, body, ts FROM resp WHERE k=?", (key,)).fetchone()
        if not row:
            return None
        status, body, ts = row
        if max_age > 0 and (time.time() - ts) > max_age:
            return None
        return status, body

    def put(self, key: str, status: int, body: str) -> None:
        with sqlite3.connect(self.path) as conn:
            conn.execute(
                "INSERT OR REPLACE INTO resp (k, status, body, ts) VALUES (?,?,?,?)",
                (key, status, body, time.time()),
            )


CACHE = Cache(CONFIG.cache_path)


def _session() -> requests.Session:
    sess = getattr(_local, "sess", None)
    if sess is None:
        sess = requests.Session()
        sess.headers.update({
            "User-Agent": UA,
            "Accept-Language": "pt-BR,pt;q=0.9,en;q=0.6",
            "Accept": "text/html,application/json,application/xhtml+xml,*/*;q=0.8",
        })
        _local.sess = sess
    return sess


def _throttle(url: str) -> None:
    host = urlsplit(url).netloc
    delay = CONFIG.rate_limit
    if delay <= 0:
        return
    with _lock:
        wait = _last_hit.get(host, 0.0) + delay - time.monotonic()
        if wait > 0:
            time.sleep(wait)
        _last_hit[host] = time.monotonic()


def fetch(
    url: str,
    *,
    method: str = "GET",
    params: dict | None = None,
    headers: dict | None = None,
    json_body: Any = None,
    cache_ttl: float = 7 * 24 * 3600,
    retries: int = 3,
) -> tuple[int, str]:
    """Requisicao com cache, rate limit por host e retry exponencial."""
    key = json.dumps(
        [method, url, params or {}, json_body or {}], sort_keys=True, ensure_ascii=False
    )
    if cache_ttl:
        hit = CACHE.get(key, cache_ttl)
        if hit is not None:
            return hit

    last_error = ""
    for attempt in range(retries):
        _throttle(url)
        try:
            resp = _session().request(
                method,
                url,
                params=params,
                headers=headers,
                json=json_body,
                timeout=CONFIG.timeout,
                allow_redirects=True,
            )
        except requests.RequestException as exc:
            last_error = str(exc)
            time.sleep(2 ** attempt)
            continue

        if resp.status_code in (429, 500, 502, 503, 504):
            last_error = f"HTTP {resp.status_code}"
            time.sleep(2 ** attempt * 2)
            continue

        body = resp.text
        if cache_ttl and resp.status_code < 500:
            CACHE.put(key, resp.status_code, body)
        return resp.status_code, body

    log.debug("falha em %s: %s", url, last_error)
    return 0, ""


def fetch_json(url: str, **kwargs) -> Any | None:
    status, body = fetch(url, **kwargs)
    if status != 200 or not body:
        return None
    try:
        return json.loads(body)
    except json.JSONDecodeError:
        return None
