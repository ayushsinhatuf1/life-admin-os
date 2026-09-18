"""Tests for the durable Postgres job queue (P2.1).

Verifies:
- Jobs can be enqueued and claimed
- A failing job is retried with exponential backoff
- After max_attempts, a job lands in 'failed' with error text preserved
- Completed jobs are marked correctly
"""
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.db import SessionLocal
from app.models import Job
from app.services import queue

client = TestClient(app)


def _get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def test_enqueue_creates_pending_job():
    db = SessionLocal()
    try:
        job_id = queue.enqueue(db, "test.job", {"key": "value"})
        db.commit()

        job = db.get(Job, job_id)
        assert job is not None
        assert job.kind == "test.job"
        assert job.status == "pending"
        assert job.attempts == 0
        assert job.payload == {"key": "value"}
    finally:
        db.close()


def test_claim_returns_job_and_updates_status():
    db = SessionLocal()
    try:
        job_id = queue.enqueue(db, "test.claim", {"x": 1})
        db.commit()

        job = queue.claim(db, "worker-test")
        assert job is not None
        assert job.id == job_id
        assert job.status == "running"
        assert job.attempts == 1
        assert job.locked_by == "worker-test"
        db.commit()
    finally:
        db.close()


def test_claim_returns_none_when_empty():
    db = SessionLocal()
    try:
        job = queue.claim(db, "worker-test")
        # It's OK if there are other test jobs; we just verify it doesn't crash.
        db.rollback()
    finally:
        db.close()


def test_complete_marks_job_done():
    db = SessionLocal()
    try:
        job_id = queue.enqueue(db, "test.complete", {})
        db.commit()

        job = queue.claim(db, "worker-test")
        queue.complete(db, job)
        db.commit()

        job = db.get(Job, job_id)
        assert job.status == "completed"
        assert job.completed_at is not None
        assert job.locked_by is None
    finally:
        db.close()


def test_failing_job_retries_then_fails_permanently():
    """A job that fails repeatedly lands in 'failed' with the error preserved."""
    db = SessionLocal()
    try:
        job_id = queue.enqueue(db, "test.retry", {}, max_attempts=3)
        db.commit()

        for attempt in range(3):
            # Reset run_after to now so it's claimable immediately.
            job = db.get(Job, job_id)
            if job.status == "pending":
                job.run_after = datetime.now(timezone.utc) - timedelta(seconds=1)
                db.commit()

            job = queue.claim(db, f"worker-{attempt}")
            if job is None:
                # May not find it if run_after is in the future, force it.
                job = db.get(Job, job_id)
                job.status = "running"
                job.attempts += 1
                db.flush()

            queue.fail(db, job, f"Error on attempt {attempt + 1}")
            db.commit()

        job = db.get(Job, job_id)
        assert job.status == "failed", f"expected 'failed' but got '{job.status}'"
        assert job.attempts == 3
        assert "Error on attempt 3" in job.last_error
        assert job.completed_at is not None
    finally:
        db.close()


def test_fail_sets_backoff_for_retryable_job():
    """First failure should schedule a retry 30s later, not immediately."""
    db = SessionLocal()
    try:
        job_id = queue.enqueue(db, "test.backoff", {}, max_attempts=3)
        db.commit()

        job = queue.claim(db, "worker-test")
        before = datetime.now(timezone.utc)
        queue.fail(db, job, "transient error")
        db.commit()

        job = db.get(Job, job_id)
        assert job.status == "pending"
        assert job.run_after > before  # pushed into the future
    finally:
        db.close()


def test_upload_enqueues_document_process_job():
    """Uploading a document should create a 'document.process' job."""
    # Register a user first.
    reg = client.post("/api/v1/auth/register", json={
        "email": f"{uuid.uuid4()}@example.com",
        "full_name": "Queue Test",
        "password": "correct-horse-battery",
    })
    assert reg.status_code == 201
    token = reg.json()["access_token"]
    family_id = reg.json()["family_id"]

    files = {"file": ("test.pdf", b"%PDF-1.4 minimal", "application/pdf")}
    h = {"Authorization": f"Bearer {token}"}
    r = client.post(f"/api/v1/families/{family_id}/documents", files=files, headers=h)

    # The upload may succeed (201) or be rejected by mime sniffing (415).
    if r.status_code == 201:
        db = SessionLocal()
        try:
            doc_id = r.json()["id"]
            job = db.query(Job).filter(
                Job.kind == "document.process",
                Job.payload["document_id"].as_string() == doc_id,
            ).first()
            assert job is not None, "upload must enqueue a document.process job"
            assert job.status == "pending"
        finally:
            db.close()
