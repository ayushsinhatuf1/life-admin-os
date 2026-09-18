"""Durable job queue backed by Postgres.

Uses SELECT ... FOR UPDATE SKIP LOCKED for safe concurrent polling:
- A job that's locked by a crashed worker releases its lock when the
  connection drops, so it becomes available to the next poller.
- Exponential backoff on failure: 30s, 120s, 480s before giving up.
- No Celery, no Redis — Postgres is the queue.
"""
from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.models import Job

log = logging.getLogger(__name__)

# Backoff schedule per attempt number (seconds).
BACKOFF = [30, 120, 480]


def enqueue(
    db: Session,
    kind: str,
    payload: dict | None = None,
    max_attempts: int = 3,
    run_after: datetime | None = None,
) -> uuid.UUID:
    """Add a job to the queue. Returns the job id."""
    job = Job(
        kind=kind,
        payload=payload or {},
        max_attempts=max_attempts,
        run_after=run_after or datetime.now(timezone.utc),
    )
    db.add(job)
    db.flush()  # populate id
    return job.id


def claim(db: Session, worker_id: str) -> Job | None:
    """Claim the next available job using FOR UPDATE SKIP LOCKED.

    Returns None if no jobs are ready. The caller must commit or rollback
    to release the row lock.
    """
    now = datetime.now(timezone.utc)
    # Raw SQL for the FOR UPDATE SKIP LOCKED clause, which SQLAlchemy ORM
    # doesn't support natively.
    result = db.execute(
        text("""
            SELECT id FROM jobs
            WHERE status = 'pending'
              AND run_after <= :now
            ORDER BY run_after
            LIMIT 1
            FOR UPDATE SKIP LOCKED
        """),
        {"now": now},
    )
    row = result.fetchone()
    if row is None:
        return None

    job = db.get(Job, row[0])
    job.status = "running"
    job.locked_by = worker_id
    job.locked_at = now
    job.attempts += 1
    db.flush()
    return job


def complete(db: Session, job: Job) -> None:
    """Mark a job as successfully completed."""
    job.status = "completed"
    job.completed_at = datetime.now(timezone.utc)
    job.locked_by = None
    job.locked_at = None


def fail(db: Session, job: Job, error: str) -> None:
    """Handle a failed job: retry with backoff, or mark as permanently failed."""
    job.last_error = error[:2000]
    job.locked_by = None
    job.locked_at = None

    if job.attempts >= job.max_attempts:
        job.status = "failed"
        job.completed_at = datetime.now(timezone.utc)
        log.warning("Job %s permanently failed after %d attempts: %s",
                    job.id, job.attempts, error[:200])
    else:
        # Exponential backoff.
        delay = BACKOFF[min(job.attempts - 1, len(BACKOFF) - 1)]
        job.status = "pending"
        job.run_after = datetime.now(timezone.utc) + timedelta(seconds=delay)
        log.info("Job %s will retry in %ds (attempt %d/%d)",
                 job.id, delay, job.attempts, job.max_attempts)
