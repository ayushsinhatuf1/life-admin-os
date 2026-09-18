"""Worker process that polls the Postgres job queue and dispatches handlers.

Run: python -m worker

The worker polls every few seconds, claims one job at a time using
SELECT ... FOR UPDATE SKIP LOCKED, runs the handler, and commits or
rolls back. If the worker crashes mid-job, the row lock releases and
the job becomes available to the next poller.
"""
from __future__ import annotations

import logging
import os
import signal
import time
import uuid

from app.ai import pipeline
from app.db import SessionLocal
from app.services import queue

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("worker")

POLL_INTERVAL = 2  # seconds between polls when idle
WORKER_ID = f"worker-{os.getpid()}-{uuid.uuid4().hex[:8]}"

_shutdown = False


def _handle_signal(sig, frame):
    global _shutdown
    _shutdown = True
    log.info("Shutdown signal received — finishing current job then exiting.")


signal.signal(signal.SIGINT, _handle_signal)
signal.signal(signal.SIGTERM, _handle_signal)


# ------------------------------------------------------------------ handlers
# Register handlers by job kind. Each receives (db, payload) and should
# raise on failure.

HANDLERS = {}


def handler(kind: str):
    """Decorator to register a job handler."""
    def decorator(fn):
        HANDLERS[kind] = fn
        return fn
    return decorator


@handler("document.process")
def handle_document_process(db, payload: dict) -> None:
    """Run the AI pipeline on an uploaded document."""
    document_id = uuid.UUID(payload["document_id"])
    pipeline.process_document(db, document_id)


# ------------------------------------------------------------------ main loop

def run_once() -> bool:
    """Claim and run one job. Returns True if a job was processed."""
    db = SessionLocal()
    try:
        job = queue.claim(db, WORKER_ID)
        if job is None:
            db.rollback()
            return False

        log.info("Claimed job %s [%s] (attempt %d/%d)",
                 job.id, job.kind, job.attempts, job.max_attempts)

        handler_fn = HANDLERS.get(job.kind)
        if handler_fn is None:
            queue.fail(db, job, f"No handler registered for job kind '{job.kind}'")
            db.commit()
            return True

        try:
            handler_fn(db, job.payload)
            queue.complete(db, job)
            db.commit()
            log.info("Job %s completed successfully.", job.id)
        except Exception as exc:
            db.rollback()
            # Re-open a fresh session to record the failure — the old one
            # may be in a broken state.
            db = SessionLocal()
            job = db.get(queue.Job, job.id)
            if job:
                queue.fail(db, job, str(exc)[:2000])
                db.commit()
            log.exception("Job %s failed: %s", job.id if job else "?", exc)

        return True
    finally:
        db.close()


def main():
    log.info("Worker %s starting. Polling every %ds.", WORKER_ID, POLL_INTERVAL)
    while not _shutdown:
        had_work = run_once()
        if not had_work:
            time.sleep(POLL_INTERVAL)
    log.info("Worker %s shut down.", WORKER_ID)


if __name__ == "__main__":
    main()
