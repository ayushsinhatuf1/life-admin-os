from __future__ import annotations

import uuid
from datetime import date, datetime, time, timedelta, timezone

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import Deadline, Reminder, User
from app.security import audit, current_user, membership, owned_or_404, require_access

from app.services import recurrence

router = APIRouter(prefix="/api/v1/families/{family_id}/deadlines", tags=["deadlines"])


class DeadlineIn(BaseModel):
    title: str
    description: str | None = None
    due_date: date
    priority: str = "medium"
    recurrence_rule: str | None = None


class DeadlineOut(DeadlineIn):
    id: uuid.UUID
    status: str
    days_left: int


class SnoozeIn(BaseModel):
    until: date


@router.post("", response_model=DeadlineOut, status_code=201)
def create(family_id: uuid.UUID, payload: DeadlineIn, request: Request,
           db: Session = Depends(get_db), user: User = Depends(current_user)):
    require_access(membership(db, user, family_id), "contributor")
    dl = Deadline(family_id=family_id, source_type="manual", **payload.model_dump())
    db.add(dl)
    db.flush()
    recurrence.schedule_reminders(db, dl, user.id)
    audit(db, request, user, "deadline.create", family_id=family_id,
          resource_type="deadline", resource_id=dl.id)
    db.commit()
    return DeadlineOut(id=dl.id, status=dl.status,
                       days_left=(dl.due_date - date.today()).days, **payload.model_dump())


@router.get("", response_model=list[DeadlineOut])
def upcoming(family_id: uuid.UUID, within_days: int = 90,
             db: Session = Depends(get_db), user: User = Depends(current_user)):
    membership(db, user, family_id)
    cutoff = date.today() + timedelta(days=within_days)
    rows = db.scalars(
        select(Deadline).where(Deadline.family_id == family_id,
                               Deadline.status == "open",
                               Deadline.due_date <= cutoff)
        .order_by(Deadline.due_date)
    )
    return [DeadlineOut(id=d.id, title=d.title, description=d.description,
                        due_date=d.due_date, priority=d.priority,
                        recurrence_rule=d.recurrence_rule, status=d.status,
                        days_left=(d.due_date - date.today()).days) for d in rows]


@router.post("/{deadline_id}/complete")
def complete(family_id: uuid.UUID, deadline_id: uuid.UUID, request: Request,
             db: Session = Depends(get_db), user: User = Depends(current_user)):
    dl = owned_or_404(db, user, Deadline, deadline_id, minimum="contributor")
    dl.status = "done"
    dl.completed_at = datetime.now(timezone.utc)

    # If recurring, spawn next occurrence and schedule its reminders
    next_occurrence_row = None
    if dl.recurrence_rule:
        next_occurrence_row = recurrence.spawn_next_occurrence(db, dl, user.id)

    audit(db, request, user, "deadline.complete", family_id=dl.family_id,
          resource_type="deadline", resource_id=dl.id,
          next_occurrence_id=str(next_occurrence_row.id) if next_occurrence_row else None)
    db.commit()
    return {
        "id": dl.id,
        "status": dl.status,
        "next_occurrence": str(next_occurrence_row.id) if next_occurrence_row else None,
    }


@router.post("/{deadline_id}/snooze", response_model=DeadlineOut)
def snooze(
    family_id: uuid.UUID,
    deadline_id: uuid.UUID,
    payload: SnoozeIn,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    dl = owned_or_404(db, user, Deadline, deadline_id, minimum="contributor")
    old_due = dl.due_date
    dl.due_date = payload.until
    if dl.status == "expired":
        dl.status = "open"

    # Reschedule pending reminders for new due date
    recurrence.schedule_reminders(db, dl, user.id)

    audit(
        db, request, user, "deadline.snooze",
        family_id=dl.family_id,
        resource_type="deadline",
        resource_id=dl.id,
        old_due_date=str(old_due),
        new_due_date=str(payload.until),
    )
    db.commit()
    return DeadlineOut(
        id=dl.id,
        title=dl.title,
        description=dl.description,
        due_date=dl.due_date,
        priority=dl.priority,
        recurrence_rule=dl.recurrence_rule,
        status=dl.status,
        days_left=(dl.due_date - date.today()).days,
    )


@router.post("/sweep")
def sweep(
    family_id: uuid.UUID,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    membership(db, user, family_id)
    expired_count = recurrence.sweep_expired_deadlines(db)
    return {"expired_count": expired_count}

