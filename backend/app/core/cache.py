"""Tiny in-process TTL cache (thread-safe) for hot, cheap-to-recompute reads.

Per worker process: with several gunicorn workers each keeps its own copy,
which is fine for the short TTLs used here (seconds). Never cache anything
that must be exact the instant it changes (claims, task status): the cache is
for dashboard aggregates and the per-request user/permission lookup.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from typing import Any, TypeVar

T = TypeVar("T")


class TTLCache:
    def __init__(self, max_items: int = 4096) -> None:
        self._data: dict[Any, tuple[float, Any]] = {}
        self._lock = threading.Lock()
        self._max = max_items

    def get(self, key: Any) -> Any | None:
        now = time.monotonic()
        with self._lock:
            hit = self._data.get(key)
            if hit is None:
                return None
            expires, value = hit
            if expires < now:
                self._data.pop(key, None)
                return None
            return value

    def set(self, key: Any, value: Any, ttl: float) -> None:
        now = time.monotonic()
        with self._lock:
            if len(self._data) >= self._max:
                # Cheap eviction: drop expired first, then the oldest quarter.
                expired = [k for k, (exp, _) in self._data.items() if exp < now]
                for k in expired:
                    self._data.pop(k, None)
                if len(self._data) >= self._max:
                    for k in list(self._data)[: self._max // 4]:
                        self._data.pop(k, None)
            self._data[key] = (now + ttl, value)

    def get_or_set(self, key: Any, ttl: float, producer: Callable[[], T]) -> T:
        value = self.get(key)
        if value is not None:
            return value
        value = producer()
        if value is not None:
            self.set(key, value, ttl)
        return value

    def invalidate(self, key: Any) -> None:
        with self._lock:
            self._data.pop(key, None)

    def clear(self) -> None:
        with self._lock:
            self._data.clear()


# Shared instances.
user_cache = TTLCache(max_items=8192)       # user id -> serialized profile (auth dependency)
dashboard_cache = TTLCache(max_items=64)    # dashboard aggregates
