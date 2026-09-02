"""End-to-end smoke test for the Prompt Attack Annotation Platform API.

Runs against the REAL PostgreSQL database configured in ``app.core.config``
(the app lifespan creates the database if missing, creates the tables and
seeds the default administrator). Every row the test creates is removed in
the ``finally`` block, so the test can be re-run on a live development DB.

Run from ``backend/``::

    .venv/Scripts/python.exe -m pytest tests/test_smoke_api.py -q
"""

from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient

from app.core.config import settings
from app.main import app

EXPECTED_FEATURE_KEYS = {
    "dashboard",
    "projects",
    "queues",
    "tasks",
    "roles",
    "users",
    "annotation_queues",
    "profile",
}

QUEUE_RESPONSE_FIELDS = {
    "id",
    "name",
    "project_id",
    "project_name",
    "task_name",
    "batch_name",
    "annotation_type",
    "priority",
    "sla_hours",
    "status",
    "user_status",
    "assigned_user_id",
    "assigned_user_name",
    "assigned_user_ids",
    "assigned_user_names",
    "linked_qa_queue_id",
    "source_production_queue_id",
    "total_tasks",
    "pending_tasks",
    "submitted_tasks",
    "approved_tasks",
    "rejected_tasks",
    "declined_tasks",
    "skipped_tasks",
    "returned_tasks",
    "timer_seconds",
    "created_at",
    "updated_at",
}

TASK_RESPONSE_FIELDS = {
    "id",
    "queue_id",
    "file_url",
    "file_name",
    "file_type",
    "batch_name",
    "status",
    "environment",
    "assigned_to",
    "assigned_to_name",
    "submitted_at",
    "started_at",
    "paused_at",
    "timer_seconds",
    "elapsed_seconds",
    "declined_reason",
    "qa_notes",
    "submitted_by",
    "annotation_version",
    "created_at",
    "updated_at",
}

SUMMARY_FIELDS = {
    "queue_name",
    "queue_type",
    "total_tasks",
    "completed_tasks",
    "pending_tasks",
    "submitted_to_qa",
    "assigned_user",
    "progress_percent",
    "status",
}

COUNT_FIELDS = (
    "total_tasks",
    "pending_tasks",
    "submitted_tasks",
    "approved_tasks",
    "rejected_tasks",
    "declined_tasks",
    "skipped_tasks",
    "returned_tasks",
    "timer_seconds",
    "sla_hours",
)


def _api(path: str) -> str:
    return f"{settings.API_V1_STR}{path}"


def _assert_queue_shape(payload: dict) -> None:
    missing = QUEUE_RESPONSE_FIELDS - set(payload)
    assert not missing, f"QueueResponse is missing fields: {sorted(missing)}"
    for key in COUNT_FIELDS:
        assert isinstance(payload[key], int), f"{key} should be an int"
    assert isinstance(payload["assigned_user_ids"], list)
    assert isinstance(payload["assigned_user_names"], list)


@pytest.fixture(scope="module")
def client():
    # "with" runs the lifespan: ensure_database() -> ensure_indexes() -> seed_default_admin()
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture(scope="module")
def admin(client: TestClient) -> dict:
    """Log in as the seeded default administrator; returns headers + profile."""
    response = client.post(
        _api("/auth/login"),
        json={
            "email": settings.DEFAULT_ADMIN_EMAIL.lower(),
            "password": settings.DEFAULT_ADMIN_PASSWORD,
        },
    )
    assert response.status_code == 200, response.text
    body = response.json()
    token = body["access_token"]
    assert token
    assert body["token_type"] == "bearer"
    assert body["user"]["email"] == settings.DEFAULT_ADMIN_EMAIL.lower()
    assert "queues" in body["permissions"]
    return {
        "headers": {"Authorization": "Bearer " + token},
        "id": body["user"]["id"],
        "profile": body["user"],
    }


def test_health(client: TestClient) -> None:
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_login_and_me(client: TestClient, admin: dict) -> None:
    response = client.get(_api("/auth/me"), headers=admin["headers"])
    assert response.status_code == 200, response.text
    me = response.json()
    assert me["id"] == admin["id"]
    assert me["email"] == settings.DEFAULT_ADMIN_EMAIL.lower()
    assert set(me["permissions"]) >= EXPECTED_FEATURE_KEYS


def test_features_list_has_eight_keys(client: TestClient, admin: dict) -> None:
    response = client.get(_api("/features/"), headers=admin["headers"])
    assert response.status_code == 200, response.text
    features = response.json()
    keys = [f["key"] for f in features]
    assert len(keys) == 8, keys
    assert set(keys) == EXPECTED_FEATURE_KEYS
    # Sorted by the seeded order (dashboard first, profile last).
    orders = [f["order"] for f in features]
    assert orders == sorted(orders)
    assert keys[0] == "dashboard"
    assert keys[-1] == "profile"


def test_project_queue_lifecycle(client: TestClient, admin: dict) -> None:
    headers = admin["headers"]
    admin_id = admin["id"]
    suffix = uuid.uuid4().hex[:8]
    project_name = f"Smoke Project {suffix}"
    queue_name = f"Smoke Queue {suffix}"

    project_id: str | None = None
    queue_id: str | None = None

    try:
        # ---- create project -------------------------------------------------
        response = client.post(
            _api("/projects/"),
            headers=headers,
            json={
                "name": project_name,
                "description": "Created by test_smoke_api",
                "media_type": "text",
                "status": "active",
                "assigned_user_ids": [],
            },
        )
        assert response.status_code == 201, response.text
        project = response.json()
        project_id = project["id"]
        assert project["name"] == project_name
        assert project["media_type"] == "text"
        assert project["status"] == "active"

        # ---- create queue with 2 tasks --------------------------------------
        response = client.post(
            _api("/queues/"),
            headers=headers,
            json={
                "name": queue_name,
                "project_id": project_id,
                "task_name": "Smoke task",
                "annotation_type": "production",
                "priority": "medium",
                "sla_hours": 24,
                "timer_seconds": 7200,
                "tasks": [
                    {
                        "file_url": f"/uploads/smoke-{suffix}-1.txt",
                        "file_name": f"smoke-{suffix}-1.txt",
                        "file_type": "text/plain",
                    },
                    {
                        "file_url": f"/uploads/smoke-{suffix}-2.txt",
                        "file_name": f"smoke-{suffix}-2.txt",
                        "file_type": "text/plain",
                        "annotation_data": {"note": "seeded"},
                    },
                ],
            },
        )
        assert response.status_code == 201, response.text
        queue = response.json()
        queue_id = queue["id"]
        _assert_queue_shape(queue)
        assert queue["name"] == queue_name
        assert queue["project_id"] == project_id
        assert queue["project_name"] == project_name
        assert queue["annotation_type"] == "production"
        assert queue["priority"] == "medium"
        assert queue["status"] == "inactive"
        assert queue["batch_name"], "a batch name must be generated when omitted"
        assert queue["timer_seconds"] == 7200
        assert queue["total_tasks"] == 2
        assert queue["pending_tasks"] == 2
        assert queue["submitted_tasks"] == 0
        assert queue["assigned_user_ids"] == []

        # ---- get queue by id ------------------------------------------------
        response = client.get(_api(f"/queues/{queue_id}"), headers=headers)
        assert response.status_code == 200, response.text
        fetched = response.json()
        _assert_queue_shape(fetched)
        assert fetched["id"] == queue_id
        assert fetched["total_tasks"] == 2

        # ---- list queues (search narrows to ours) ---------------------------
        response = client.get(
            _api("/queues/"),
            headers=headers,
            params={"search": queue_name, "page": 1, "page_size": 10},
        )
        assert response.status_code == 200, response.text
        page = response.json()
        for key in ("items", "total", "page", "page_size"):
            assert key in page, f"Page envelope missing {key}"
        assert page["page"] == 1
        assert page["page_size"] == 10
        assert page["total"] >= 1
        listed = [q for q in page["items"] if q["id"] == queue_id]
        assert len(listed) == 1, "created queue not found in list"
        _assert_queue_shape(listed[0])
        assert listed[0]["total_tasks"] == 2
        assert listed[0]["pending_tasks"] == 2

        # ---- project now reports two queues (production + auto-created QA) --
        # SPEC2 5.1: creating a production queue also creates its linked
        # "<name> - QA" queue in the same project, in the same transaction.
        response = client.get(_api(f"/projects/{project_id}"), headers=headers)
        assert response.status_code == 200, response.text
        assert response.json()["total_queues"] == 2
        assert queue.get("linked_qa_queue_id"), "production queue must link its QA queue"

        # ---- queue tasks ----------------------------------------------------
        response = client.get(
            _api(f"/queues/{queue_id}/tasks"),
            headers=headers,
            params={"page": 1, "page_size": 10},
        )
        assert response.status_code == 200, response.text
        body = response.json()
        for key in ("queue", "summary", "tasks", "pagination"):
            assert key in body, f"QueueTasksResponse missing {key}"

        _assert_queue_shape(body["queue"])
        assert body["queue"]["id"] == queue_id

        summary = body["summary"]
        missing = SUMMARY_FIELDS - set(summary)
        assert not missing, f"summary missing {sorted(missing)}"
        assert summary["queue_name"] == queue_name
        assert summary["queue_type"] == "production"
        assert summary["total_tasks"] == 2
        assert summary["completed_tasks"] == 0
        assert summary["pending_tasks"] == 2
        assert summary["submitted_to_qa"] == 0
        assert summary["progress_percent"] == 0
        assert summary["status"] == "inactive"

        tasks = body["tasks"]
        assert len(tasks) == 2
        for task in tasks:
            missing = TASK_RESPONSE_FIELDS - set(task)
            assert not missing, f"TaskResponse missing {sorted(missing)}"
            assert task["queue_id"] == queue_id
            assert task["status"] == "pending"
            assert task["environment"] == "production"
            assert task["batch_name"] == queue["batch_name"]
            assert task["timer_seconds"] == 7200
            assert task["elapsed_seconds"] == 0
            assert task["assigned_to"] is None
        assert {t["file_name"] for t in tasks} == {
            f"smoke-{suffix}-1.txt",
            f"smoke-{suffix}-2.txt",
        }

        pagination = body["pagination"]
        assert pagination["total"] == 2
        assert pagination["page"] == 1
        assert pagination["page_size"] == 10

        # ---- set assignees -> active ----------------------------------------
        response = client.put(
            _api(f"/queues/{queue_id}/assignees"),
            headers=headers,
            json={"user_ids": [admin_id]},
        )
        assert response.status_code == 200, response.text
        assigned = response.json()
        _assert_queue_shape(assigned)
        assert assigned["status"] == "active"
        assert assigned["assigned_user_ids"] == [admin_id]
        assert assigned["assigned_user_id"] == admin_id
        assert assigned["assigned_user_name"]
        assert len(assigned["assigned_user_names"]) == 1

        # The queue now shows up in the admin's own work list with a user_status.
        response = client.get(
            _api("/queues/"),
            headers=headers,
            params={
                "assigned_user_id": admin_id,
                "search": queue_name,
                "exclude_completed": "true",
            },
        )
        assert response.status_code == 200, response.text
        mine = [q for q in response.json()["items"] if q["id"] == queue_id]
        assert len(mine) == 1
        assert mine[0]["user_status"] == "active"

        # ---- unassign -> inactive -------------------------------------------
        response = client.patch(_api(f"/queues/{queue_id}/unassign"), headers=headers)
        assert response.status_code == 200, response.text
        unassigned = response.json()
        _assert_queue_shape(unassigned)
        assert unassigned["status"] == "inactive"
        assert unassigned["assigned_user_ids"] == []
        assert unassigned["assigned_user_id"] is None

        # ---- delete queue ---------------------------------------------------
        response = client.delete(_api(f"/queues/{queue_id}"), headers=headers)
        assert response.status_code == 204, response.text
        response = client.get(_api(f"/queues/{queue_id}"), headers=headers)
        assert response.status_code == 404
        queue_id = None

        # ---- delete project -------------------------------------------------
        response = client.delete(_api(f"/projects/{project_id}"), headers=headers)
        assert response.status_code == 204, response.text
        response = client.get(_api(f"/projects/{project_id}"), headers=headers)
        assert response.status_code == 404
        project_id = None

    finally:
        # Best-effort cleanup if any assertion above failed mid-flow.
        if queue_id:
            client.delete(_api(f"/queues/{queue_id}"), headers=headers)
        if project_id:
            client.delete(_api(f"/projects/{project_id}"), headers=headers)
