"""Operational visibility: request timing, slow-query log, process metrics.

- ``RequestTiming`` (pure ASGI, outermost): stamps every response with
  ``X-Request-ID`` and ``X-Response-Time`` (ms, including any admission wait),
  logs a WARNING for requests slower than ``SLOW_REQUEST_MS`` and every 5xx,
  and keeps per-process counters (requests, errors, slow, in-flight).
- ``install_slow_query_log(engine)``: logs statements slower than
  ``SLOW_QUERY_MS`` with a truncated SQL text - the app-side complement of
  Postgres' ``log_min_duration_statement``.
- ``snapshot()``: the numbers ``GET /health/details`` reports.

Everything here is per worker process (gunicorn runs several); the health
endpoint says which pid answered.
"""

from __future__ import annotations

import logging
import os
import threading
import time
import uuid
from typing import Any

from sqlalchemy import event

from app.core.config import settings

logger = logging.getLogger("uvicorn.error")
STARTED_AT = time.time()


class Counters:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.requests = 0
        self.errors_5xx = 0
        self.slow_requests = 0
        self.slow_queries = 0
        self.in_flight = 0
        self.total_ms = 0.0
        self.max_ms = 0.0

    def start(self) -> None:
        with self._lock:
            self.in_flight += 1

    def finish(self, status: int, ms: float, slow: bool) -> None:
        with self._lock:
            self.in_flight -= 1
            self.requests += 1
            self.total_ms += ms
            if ms > self.max_ms:
                self.max_ms = ms
            if status >= 500:
                self.errors_5xx += 1
            if slow:
                self.slow_requests += 1

    def slow_query(self) -> None:
        with self._lock:
            self.slow_queries += 1

    def as_dict(self) -> dict[str, Any]:
        with self._lock:
            avg = self.total_ms / self.requests if self.requests else 0.0
            return {
                "requests": self.requests,
                "in_flight": self.in_flight,
                "errors_5xx": self.errors_5xx,
                "slow_requests": self.slow_requests,
                "slow_queries": self.slow_queries,
                "avg_ms": round(avg, 1),
                "max_ms": round(self.max_ms, 1),
            }


counters = Counters()


class RequestTiming:
    """Outermost ASGI wrapper: request id, response time header, slow/5xx log."""

    def __init__(self, app) -> None:
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        path = scope.get("path") or ""
        if path == "/health":
            return await self.app(scope, receive, send)
        headers = dict(scope.get("headers") or [])
        request_id = (headers.get(b"x-request-id") or b"").decode("latin-1")[:64] or uuid.uuid4().hex[:16]
        started = time.perf_counter()
        status_holder = {"status": 0}
        counters.start()

        async def send_wrapper(message):
            if message["type"] == "http.response.start":
                status_holder["status"] = int(message.get("status", 0))
                ms = (time.perf_counter() - started) * 1000
                hdrs = list(message.get("headers") or [])
                hdrs.append((b"x-request-id", request_id.encode("latin-1")))
                hdrs.append((b"x-response-time", f"{ms:.1f}ms".encode("latin-1")))
                message = {**message, "headers": hdrs}
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        except Exception:
            status_holder["status"] = status_holder["status"] or 500
            raise
        finally:
            ms = (time.perf_counter() - started) * 1000
            status = status_holder["status"] or 500
            slow = ms >= settings.SLOW_REQUEST_MS
            counters.finish(status, ms, slow)
            if slow or status >= 500:
                method = scope.get("method", "?")
                query = (scope.get("query_string") or b"").decode("latin-1")
                logger.warning(
                    "%s request id=%s %s %s%s -> %s in %.0f ms",
                    "SLOW" if slow and status < 500 else "ERROR",
                    request_id, method, path, ("?" + query[:80]) if query else "", status, ms,
                )


def install_slow_query_log(engine) -> None:
    threshold_s = max(0.01, float(settings.SLOW_QUERY_MS) / 1000.0)

    @event.listens_for(engine, "before_cursor_execute")
    def _before(conn, cursor, statement, parameters, context, executemany):  # noqa: ANN001
        conn.info.setdefault("query_start", []).append(time.perf_counter())

    @event.listens_for(engine, "after_cursor_execute")
    def _after(conn, cursor, statement, parameters, context, executemany):  # noqa: ANN001
        starts = conn.info.get("query_start")
        if not starts:
            return
        elapsed = time.perf_counter() - starts.pop()
        if elapsed >= threshold_s:
            counters.slow_query()
            text = " ".join(str(statement).split())
            logger.warning("SLOW query %.0f ms: %s", elapsed * 1000, text[:300])


def pool_status(engine) -> dict[str, Any]:
    pool = engine.pool
    out: dict[str, Any] = {"size": settings.DB_POOL_SIZE, "max_overflow": settings.DB_MAX_OVERFLOW}
    for name in ("checkedout", "checkedin", "overflow"):
        fn = getattr(pool, name, None)
        try:
            out[name] = int(fn()) if callable(fn) else None
        except Exception:  # noqa: BLE001
            out[name] = None
    return out


def snapshot(engine, admission: dict[str, Any] | None, threadpool_tokens: int | None) -> dict[str, Any]:
    return {
        "pid": os.getpid(),
        "uptime_s": int(time.time() - STARTED_AT),
        "requests": counters.as_dict(),
        "db_pool": pool_status(engine),
        "admission": admission or {},
        "threadpool_tokens": threadpool_tokens,
        "lease_seconds": settings.CLAIM_LEASE_SECONDS,
        "thresholds": {"slow_request_ms": settings.SLOW_REQUEST_MS, "slow_query_ms": settings.SLOW_QUERY_MS},
    }
