"""Operational endpoints and headers (Phase 4)."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.core.config import settings
from app.main import app


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as test_client:
        yield test_client


def test_health_is_cheap_and_untimed(client: TestClient) -> None:
    r = client.get("/health")
    assert r.status_code == 200 and r.json() == {"status": "ok"}
    assert "x-response-time" not in r.headers  # bypasses the timing wrapper on purpose


def test_health_details_reports_worker_metrics(client: TestClient) -> None:
    r = client.get("/health/details")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "ok"
    assert body["db_ping_ms"] is not None
    assert body["pid"] > 0 and body["uptime_s"] >= 0
    assert {"requests", "in_flight", "errors_5xx", "slow_requests", "slow_queries"} <= set(body["requests"])
    assert body["db_pool"]["size"] == settings.DB_POOL_SIZE
    assert body["admission"]["limit"] >= 2
    assert body["threadpool_tokens"] >= 8
    # This very request was counted and timed.
    assert r.headers["x-response-time"].endswith("ms")
    assert r.headers["x-request-id"]


def test_request_id_is_echoed_and_timing_header_present(client: TestClient) -> None:
    r = client.post(f"{settings.API_V1_STR}/auth/login", json={"email": "nobody@example.org", "password": "x"},
                    headers={"X-Request-ID": "trace-abc-123"})
    assert r.status_code in (401, 429)
    assert r.headers["x-request-id"] == "trace-abc-123"
    assert float(r.headers["x-response-time"].rstrip("ms")) >= 0


def test_db_connection_has_guard_rails() -> None:
    from sqlalchemy import text

    from app.core.database import SessionLocal

    db = SessionLocal()
    try:
        # pg_settings.setting reports the raw value in milliseconds (SHOW pretty-prints "1min").
        stmt = db.execute(text("SELECT setting FROM pg_settings WHERE name = 'statement_timeout'")).scalar()
        lock = db.execute(text("SELECT setting FROM pg_settings WHERE name = 'lock_timeout'")).scalar()
        name = db.execute(text("SHOW application_name")).scalar()
    finally:
        db.close()
    assert int(stmt) == settings.DB_STATEMENT_TIMEOUT_MS
    assert int(lock) == settings.DB_LOCK_TIMEOUT_MS
    assert name == "promptattack-api"
