# -*- coding: utf-8 -*-
"""A small cache with a time to live (standard library only), for answers that are the same for every user and change rarely,
for example the grid layer and the risk surface of one day. One cache per worker process."""
from __future__ import annotations

import threading
import time
from collections import OrderedDict
from typing import Any, Callable, Hashable, Optional


class TtlCache:
    """At most `max_items` entries, each valid for `ttl_seconds` (the least recently used one goes first)."""

    def __init__(self, ttl_seconds: float, max_items: int = 64):
        self.ttl, self.max_items = ttl_seconds, max_items
        self._items: "OrderedDict[Hashable, tuple[float, Any]]" = OrderedDict()
        self._lock = threading.Lock()
        self._building: dict[Hashable, threading.Lock] = {}

    def get(self, key: Hashable, now: Optional[float] = None) -> Any:
        now = time.monotonic() if now is None else now
        with self._lock:
            entry = self._items.get(key)
            if entry is None:
                return None
            if entry[0] <= now:
                del self._items[key]
                return None
            self._items.move_to_end(key)
            return entry[1]

    def put(self, key: Hashable, value: Any, now: Optional[float] = None) -> None:
        now = time.monotonic() if now is None else now
        with self._lock:
            self._items[key] = (now + self.ttl, value)
            self._items.move_to_end(key)
            while len(self._items) > self.max_items:
                self._items.popitem(last=False)

    def get_or_build(self, key: Hashable, builder: Callable[[], Any]) -> Any:
        """The value for `key`; when it is missing exactly one caller builds it and the others wait for that result (without this,
        a burst of requests that all miss at the same moment builds the same answer dozens of times). A builder that returns None
        is not cached; an exception from it reaches only the caller that built."""
        value = self.get(key)
        if value is not None:
            return value
        with self._lock:
            lock = self._building.setdefault(key, threading.Lock())
        with lock:
            value = self.get(key)                              # built by another caller while this one waited
            if value is None:
                value = builder()
                if value is not None:
                    self.put(key, value)
        with self._lock:
            self._building.pop(key, None)
        return value

    def clear(self) -> None:
        with self._lock:
            self._items.clear()

    def __len__(self) -> int:
        return len(self._items)
