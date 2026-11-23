# -*- coding: utf-8 -*-
"""A simple in-memory rate limiter (standard library only) for the public demo: enough for one backend process and a crowd of
a hundred phones; not a defence against a real attack (that needs a proxy or a service in front)."""
from __future__ import annotations

import threading
import time
from collections import deque
from typing import Optional

from fastapi import HTTPException, Request


class RateLimiter:
    """At most `calls` calls per `seconds` for each key."""

    def __init__(self, calls: int, seconds: float):
        self.calls, self.seconds = calls, seconds
        self._hits: dict[str, deque] = {}
        self._lock = threading.Lock()

    def allow(self, key: str, now: Optional[float] = None) -> bool:
        now = time.monotonic() if now is None else now
        with self._lock:
            q = self._hits.setdefault(key, deque())
            while q and q[0] <= now - self.seconds:
                q.popleft()
            if len(q) >= self.calls:
                return False
            q.append(now)
            if len(self._hits) > 20000:                      # keep the memory bounded
                for k in [k for k, v in self._hits.items() if not v or v[-1] <= now - self.seconds]:
                    del self._hits[k]
            return True


def client_ip(request: Request) -> str:
    """The client address: the first X-Forwarded-For value set by the proxy (Caddy), else the direct peer."""
    xff = request.headers.get("x-forwarded-for")
    if xff:
        return xff.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def enforce(limiter: RateLimiter, key: str) -> None:
    if not limiter.allow(key):
        raise HTTPException(status_code=429, detail="too many requests, try again in a moment")
