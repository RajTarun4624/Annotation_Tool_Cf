"""In-process sliding-window rate limiter for abuse-prone endpoints (login).

Per worker process (each gunicorn worker keeps its own counters), which still
bounds a brute-force attempt to ``limit x workers`` per window and, more
importantly for throughput, stops a runaway client from monopolising the
thread pool with password hashing.
"""

from __future__ import annotations

import threading
import time
from collections import deque


class SlidingWindowLimiter:
    def __init__(self, limit: int, window_seconds: float, max_keys: int = 50_000) -> None:
        self.limit = int(limit)
        self.window = float(window_seconds)
        self._hits: dict[str, deque[float]] = {}
        self._lock = threading.Lock()
        self._max_keys = max_keys

    def allow(self, key: str) -> bool:
        """Record one hit for ``key``; False when the key exceeded the limit."""
        now = time.monotonic()
        cutoff = now - self.window
        with self._lock:
            q = self._hits.get(key)
            if q is None:
                if len(self._hits) >= self._max_keys:
                    self._hits.clear()  # pathological churn: reset rather than grow unbounded
                q = deque()
                self._hits[key] = q
            while q and q[0] < cutoff:
                q.popleft()
            if len(q) >= self.limit:
                return False
            q.append(now)
            return True

    def reset(self, key: str) -> None:
        with self._lock:
            self._hits.pop(key, None)


# 10 login attempts per minute per (client IP, email); success resets the key.
login_limiter = SlidingWindowLimiter(limit=10, window_seconds=60)
