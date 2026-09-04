"""QA edits an annotator's response in place (real PostgreSQL)."""

from __future__ import annotations

import uuid

import pytest

from app.core.database import SessionLocal, ensure_indexes, startup_lock
from app.crud import annotation as crud
from app.models import Task, TaskOutput

from tests.test_concurrency import _cleanup, _mk_queue, _mk_users
from tests.test_workspace_flow import ANNOTATION


@pytest.fixture(scope="module", autouse=True)
def _schema():
    with startup_lock():
        ensure_indexes()


@pytest.fixture()
def reviewed_task():
    """A task with 3 submitted responses (intentions: adversarial, adversarial, hard_to_say)."""
    suffix = uuid.uuid4().hex[:8]
    db = SessionLocal()
    annotators = _mk_users(db, 3, suffix)
    reviewer = _mk_users(db, 1, suffix + "qa")[0]
    q = _mk_queue(db, suffix, n_tasks=1, required=3)
    task_id = db.query(Task.id).filter(Task.queue_id == q.id).scalar()
    for k, u in enumerate(annotators):
        data = dict(ANNOTATION)
        if k == 2:
            data["intention"] = "hard_to_say"
        task = crud.get_task(db, str(task_id))
        assert crud.submit_annotation(db, task, u, data, 10) == []
    db.close()
    try:
        yield {"task_id": str(task_id), "queue_id": q.id, "annotators": annotators, "reviewer": reviewer}
    finally:
        _cleanup([q.id], [u["id"] for u in annotators] + [reviewer["id"]])


def test_edit_response_keeps_original_and_updates_output(reviewed_task):
    db = SessionLocal()
    try:
        task = crud.get_task(db, reviewed_task["task_id"])
        assert task.status == "submitted"
        third = crud.submitted_annotations(task)[2]
        assert third.data["intention"] == "hard_to_say"

        edited = dict(third.data)
        edited["intention"] = "adversarial"
        ann = crud.edit_qa_response(db, task, str(third.id), reviewed_task["reviewer"], edited, "", 30)

        assert ann.data["intention"] == "adversarial"
        assert ann.original_data["intention"] == "hard_to_say", "first edit keeps the annotator's original"
        assert str(ann.qa_edited_by) == reviewed_task["reviewer"]["id"]
        assert ann.qa_edited_by_name == reviewed_task["reviewer"]["full_name"]
        assert ann.status == "submitted", "the response stays a submitted response"
        out = db.query(TaskOutput).filter(TaskOutput.annotation_id == ann.id).one()
        assert out.intention == "adversarial"

        # Second edit does not overwrite the original snapshot.
        edited["severity"] = {"J": 3, "I": 4, "L": 0}
        task = crud.get_task(db, reviewed_task["task_id"])
        ann = crud.edit_qa_response(db, task, str(third.id), reviewed_task["reviewer"], edited, "", 40)
        assert ann.original_data["intention"] == "hard_to_say"
        assert ann.data["severity"]["J"] == 3

        # The reviewer's session remembers which response they were editing.
        task = crud.get_task(db, reviewed_task["task_id"])
        session = crud.qa_draft_of(task, reviewed_task["reviewer"]["id"])
        assert session and session["annotation_id"] == str(third.id)
        payload = crud.qa_task_payload(task, reviewed_task["reviewer"]["id"])
        flags = {a["id"]: a["edited"] for a in payload["annotations"]}
        assert flags[str(third.id)] is True and sum(flags.values()) == 1
    finally:
        db.close()


def test_finalize_with_edited_response_uses_majority_of_corrected_responses(reviewed_task):
    db = SessionLocal()
    try:
        task = crud.get_task(db, reviewed_task["task_id"])
        first = crud.submitted_annotations(task)[0]
        # Reviewer changes annotator 1 to hard_to_say -> now 2 of 3 say hard_to_say.
        edited = dict(first.data)
        edited["intention"] = "hard_to_say"
        errors = crud.finalize_task(db, task, reviewed_task["reviewer"], edited, "", annotation_id=str(first.id))
        assert errors == []
        task = crud.get_task(db, reviewed_task["task_id"])
        assert task.status == "approved"
        assert task.final_data["intention"] == "hard_to_say", "final = majority of the corrected responses"
        record = task.final_record
        assert record["annotator_1"]["intention"] == "hard_to_say"
        assert record["annotator_2"]["intention"] == "adversarial"
        assert record["annotator_3"]["intention"] == "hard_to_say"
        assert record["inter_annotator_agreement"]["intention"] == "majority"
        assert task.qa_owner_id is None and task.draft_data == {}
    finally:
        db.close()


def test_finalize_refuses_while_another_response_is_incomplete(reviewed_task):
    db = SessionLocal()
    try:
        task = crud.get_task(db, reviewed_task["task_id"])
        anns = crud.submitted_annotations(task)
        # Reviewer leaves annotator 2's response half-edited (no attack type at all).
        crud.edit_qa_response(db, task, str(anns[1].id), reviewed_task["reviewer"], {"data_type": "general_text"}, "", 5)
        task = crud.get_task(db, reviewed_task["task_id"])
        errors = crud.finalize_task(db, task, reviewed_task["reviewer"], dict(anns[0].data), "", annotation_id=str(anns[0].id))
        assert errors, "an invalid response blocks finalisation"
        assert any(anns[1].user_name in e for e in errors), errors
        task = crud.get_task(db, reviewed_task["task_id"])
        assert task.status == "submitted"
    finally:
        db.close()


def test_legacy_finalize_without_annotation_id_still_stores_data_as_final(reviewed_task):
    db = SessionLocal()
    try:
        task = crud.get_task(db, reviewed_task["task_id"])
        final = dict(ANNOTATION)
        final["intention"] = "benign"
        assert crud.finalize_task(db, task, reviewed_task["reviewer"], final, "") == []
        task = crud.get_task(db, reviewed_task["task_id"])
        assert task.final_data["intention"] == "benign"
    finally:
        db.close()
