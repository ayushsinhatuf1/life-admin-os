"""Recurrence calculations and deadline lifecycle (P3.1).

Parses RFC 5545 RRULEs using dateutil, handles month-end rules (e.g. 31st in February),
snoozing, and daily sweep of expired deadlines with priority escalation.
"""
from __future__ import annotations

import calendar
import logging
import uuid
from datetime import date, datetime, time, timedelta, timezone
from typing import Sequence

try:
    from dateutil.rrule import rrulestr, rrule, MONTHLY, YEARLY, WEEKLY, DAILY
except ImportError:
    rrulestr = None

try:
    from sqlalchemy import select
    from sqlalchemy.orm import Session
    from app.models import Deadline, Reminder
except ImportError:
    select = None
    Session = None
    Deadline = None
    Reminder = None

log = logging.getLogger(__name__)

PRIORITY_LADDER = ["low", "medium", "high", "critical"]

# Deterministic nudge schedule by priority (days before due date).
LEAD_DAYS = {
    "critical": [30, 14, 7, 3, 1],
    "high": [30, 7, 1],
    "medium": [14, 1],
    "low": [7],
}


def raise_priority(current_priority: str) -> str:
    """Raise deadline priority by one level: low -> medium -> high -> critical."""
    try:
        idx = PRIORITY_LADDER.index(current_priority.lower())
        return PRIORITY_LADDER[min(idx + 1, len(PRIORITY_LADDER) - 1)]
    except ValueError:
        return "high"


def _is_month_end(dt: date) -> bool:
    """Return True if dt is the last day of its month."""
    _, last_day = calendar.monthrange(dt.year, dt.month)
    return dt.day == last_day


def _clamp_month_end(year: int, month: int, desired_day: int) -> date:
    """Return date in year/month clamped to the last day of the month if needed."""
    _, last_day = calendar.monthrange(year, month)
    return date(year, month, min(desired_day, last_day))


def next_occurrence(rrule_str: str, current_due_date: date) -> date | None:
    """Calculate the next due date based on an RFC 5545 RRULE string.
    
    Handles:
    - Standard RFC 5545 RRULE parsing
    - Month-end rules (e.g. 31st rolling into February clamped to 28th/29th)
    - DST-free timezone independence (computes calendar date directly)
    """
    if not rrule_str or not rrule_str.strip():
        return None

    clean_rule = rrule_str.strip()
    if clean_rule.upper().startswith("RRULE:"):
        clean_rule = clean_rule[6:]

    # Fast-path month-end rules (e.g. BYMONTHDAY=-1 or monthly with 31st)
    is_monthly = "FREQ=MONTHLY" in clean_rule.upper()
    is_month_end_rule = "BYMONTHDAY=-1" in clean_rule or (is_monthly and _is_month_end(current_due_date))

    if rrulestr is not None:
        try:
            dt_start = datetime.combine(current_due_date, time(0, 0))
            rule = rrulestr(clean_rule, dtstart=dt_start)
            nxt = rule.after(dt_start)

            if nxt is not None:
                res_date = nxt.date()
                # If this is a monthly recurrence starting on month-end (like Jan 31),
                # dateutil standard RFC 5545 skips February unless BYMONTHDAY=-1.
                # If it skipped February, check if the immediately following month was skipped:
                if is_month_end_rule:
                    target_month = current_due_date.month + 1
                    target_year = current_due_date.year
                    if target_month > 12:
                        target_month = 1
                        target_year += 1
                    expected_next_month_end = _clamp_month_end(target_year, target_month, current_due_date.day)
                    if expected_next_month_end < res_date:
                        return expected_next_month_end
                return res_date
        except Exception as exc:
            log.warning("dateutil rrulestr failed for '%s': %s", clean_rule, exc)

    # Pure Python RFC 5545 fallback
    return _fallback_next_occurrence(clean_rule, current_due_date)


def _fallback_next_occurrence(rule_str: str, current_date: date) -> date | None:
    """Deterministic fallback for common RFC 5545 rules when dateutil is unavailable."""
    parts = dict(part.split("=", 1) for part in rule_str.split(";") if "=" in part)
    freq = parts.get("FREQ", "").upper()
    interval = int(parts.get("INTERVAL", 1))

    if freq == "DAILY":
        return current_date + timedelta(days=interval)
    elif freq == "WEEKLY":
        return current_date + timedelta(weeks=interval)
    elif freq == "MONTHLY":
        target_month = current_date.month + interval
        target_year = current_date.year + (target_month - 1) // 12
        target_month = ((target_month - 1) % 12) + 1
        return _clamp_month_end(target_year, target_month, current_date.day)
    elif freq == "YEARLY":
        target_year = current_date.year + interval
        return _clamp_month_end(target_year, current_date.month, current_date.day)

    return None


def schedule_reminders(db: Session, deadline: Deadline, user_id: uuid.UUID | None = None) -> None:
    """Schedule pending reminder nudges for a deadline."""
    # Remove existing pending reminders for this deadline
    db.query(Reminder).filter(
        Reminder.deadline_id == deadline.id,
        Reminder.delivery_status == "pending",
    ).delete()

    leads = LEAD_DAYS.get(deadline.priority, [7])
    now_utc = datetime.now(timezone.utc)

    for lead in leads:
        when = datetime.combine(
            deadline.due_date - timedelta(days=lead),
            time(9, 0),
            tzinfo=timezone.utc,
        )
        if when > now_utc:
            db.add(
                Reminder(
                    deadline_id=deadline.id,
                    remind_at=when,
                    recipient_user=user_id,
                    channel="email",
                    delivery_status="pending",
                )
            )


def spawn_next_occurrence(
    db: Session,
    deadline: Deadline,
    user_id: uuid.UUID | None = None,
    raise_priority_level: bool = False,
) -> Deadline | None:
    """Create the next occurrence of a recurring deadline."""
    if not deadline.recurrence_rule:
        return None

    next_due = next_occurrence(deadline.recurrence_rule, deadline.due_date)
    if not next_due:
        return None

    next_prio = raise_priority(deadline.priority) if raise_priority_level else deadline.priority

    next_dl = Deadline(
        family_id=deadline.family_id,
        title=deadline.title,
        description=deadline.description,
        due_date=next_due,
        priority=next_prio,
        status="open",
        recurrence_rule=deadline.recurrence_rule,
        source_type=deadline.source_type,
        source_id=deadline.source_id,
    )
    db.add(next_dl)
    db.flush()
    schedule_reminders(db, next_dl, user_id)
    return next_dl


def sweep_expired_deadlines(db: Session, as_of: date | None = None) -> int:
    """Daily sweep: marks past-due open deadlines as 'expired'.
    
    For recurring deadlines, expiry raises the priority of the next occurrence by one level.
    """
    today = as_of or datetime.now(timezone.utc).date()

    expired_candidates = db.scalars(
        select(Deadline).where(
            Deadline.status == "open",
            Deadline.due_date < today,
        )
    ).all()

    count = 0
    for dl in expired_candidates:
        dl.status = "expired"
        count += 1

        # Cancel any pending reminders
        db.query(Reminder).filter(
            Reminder.deadline_id == dl.id,
            Reminder.delivery_status == "pending",
        ).update({"delivery_status": "cancelled"})

        # If recurring, raise priority one level and spawn next occurrence
        if dl.recurrence_rule:
            spawn_next_occurrence(db, dl, raise_priority_level=True)

    db.commit()
    return count
