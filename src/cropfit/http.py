"""Shared HTTP session (User-Agent required by NMDC/NEON) with retries and a JSON disk cache."""
from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path

import requests

from .config import CACHE

UA = "crop-fit-hackathon/0.1 (research prototype)"
session = requests.Session()
session.headers["User-Agent"] = UA


def _request(method: str, url: str, retries: int = 5, **kw) -> requests.Response:
    kw.setdefault("timeout", 120)
    for attempt in range(retries):
        try:
            r = session.request(method, url, **kw)
            if r.status_code in (429, 500, 502, 503, 504):
                raise requests.HTTPError(f"{r.status_code}", response=r)
            r.raise_for_status()
            return r
        except requests.RequestException:
            if attempt == retries - 1:
                raise
            time.sleep(min(2 ** attempt, 30))
    raise RuntimeError("unreachable")


def get(url: str, **kw) -> requests.Response:
    return _request("GET", url, **kw)


def post(url: str, **kw) -> requests.Response:
    return _request("POST", url, **kw)


def cached(namespace: str, key: str, fetch, *, as_text: bool = False):
    """Return cached JSON/text for (namespace, key); call fetch() on miss and store it."""
    d = CACHE / namespace
    d.mkdir(parents=True, exist_ok=True)
    h = hashlib.sha1(key.encode()).hexdigest()[:20]
    p: Path = d / (h + (".txt" if as_text else ".json"))
    if p.exists():
        return p.read_text() if as_text else json.loads(p.read_text())
    val = fetch()
    p.write_text(val if as_text else json.dumps(val))
    return val
