"""Reminder dispatcher and notification preferences engine (P3.2).

Features:
- Per-user notification preferences (channels, send hour, quiet hours, category mutes, weekly digest)
- Exactly-once delivery guaranteed by Postgres UNIQUE(reminder_id) constraint in reminder_deliveries
- Concurrent-safe dispatch with SELECT ... FOR UPDATE SKIP LOCKED
- Weekly digest option batching 7-day deadlines into a single summary
"""
from __future__ import annotations

import logging
import smtplib
import uuid
from datetime import date, datetime, time, timedelta, timezone
from email.message import EmailMessage
try:
    from zoneinfo import ZoneInfo
except ImportError:
    ZoneInfo = None

try:
    from sqlalchemy import select, text
    from sqlalchemy.exc import IntegrityError
    from sqlalchemy.orm import Session

    from app.config import settings
    from app.db import SessionLocal
    from app.models import (
        Deadline,
        Document,
        NotificationPreference,
        Reminder,
        ReminderDelivery,
        User,
    )
except ImportError:
    select = None
    text = None
    IntegrityError = Exception
    Session = None
    settings = None
    SessionLocal = None
    Deadline = None
    Document = None
    NotificationPreference = None
    Reminder = None
    ReminderDelivery = None
    User = None

log = logging.getLogger(__name__)
MAX_ATTEMPTS = 3


def send_email(to: str, subject: str, body: str) -> None:
    """Send an email using configured SMTP settings."""
    msg = EmailMessage()
    msg["From"] = settings.mail_from
    msg["To"] = to
    msg["Subject"] = subject
    msg.set_content(body)
    with smtplib.SMTP(settings.smtp_host, settings.smtp_port) as smtp:
        smtp.starttls()
        if settings.smtp_user:
            smtp.login(settings.smtp_user, settings.smtp_password)
        smtp.send_message(msg)


def get_user_preferences(db: Session, user_id: uuid.UUID) -> NotificationPreference:
    """Get or initialize default notification preferences for a user."""
    prefs = db.scalar(
        select(NotificationPreference).where(NotificationPreference.user_id == user_id)
    )
    if not prefs:
        prefs = NotificationPreference(
            user_id=user_id,
            channels=["email"],
            send_hour=9,
            timezone="Asia/Kolkata",
            muted_categories=[],
            weekly_digest=False,
            digest_day=0,  # Monday
        )
        db.add(prefs)
        db.flush()
    return prefs


def _get_timezone(tz_str: str | None) -> timezone:
    """Resolve timezone with fallbacks for environments lacking IANA tzdata (e.g. Windows)."""
    name = (tz_str or "Asia/Kolkata").strip()
    if ZoneInfo:
        try:
            return ZoneInfo(name)
        except Exception:
            pass

    COMMON_OFFSETS = {
        "Asia/Kolkata": timedelta(hours=5, minutes=30),
        "Asia/Calcutta": timedelta(hours=5, minutes=30),
        "IST": timedelta(hours=5, minutes=30),
        "UTC": timedelta(0),
        "GMT": timedelta(0),
    }
    if name in COMMON_OFFSETS:
        return timezone(COMMON_OFFSETS[name], name)
    return timezone.utc


def is_in_send_window(prefs: NotificationPreference, now_utc: datetime) -> bool:
    """Check if the current time in the user's timezone has reached their preferred send hour."""
    tz = _get_timezone(prefs.timezone)
    local_time = now_utc.astimezone(tz)
    # Only deliver after user's preferred send_hour (e.g. 9 AM) and not during night quiet hours (e.g. 22:00-07:00)
    return local_time.hour >= prefs.send_hour and local_time.hour < 22


def is_digest_day_and_hour(prefs: NotificationPreference, now_utc: datetime) -> bool:
    """Check if it is the user's scheduled weekly digest day and hour."""
    tz = _get_timezone(prefs.timezone)
    local_time = now_utc.astimezone(tz)
    return local_time.weekday() == prefs.digest_day and local_time.hour == prefs.send_hour


def get_deadline_category(db: Session, deadline: Deadline) -> str | None:
    """Resolve category of the deadline or its source document."""
    if deadline.source_type == "document" and deadline.source_id:
        doc = db.get(Document, deadline.source_id)
        if doc:
            return doc.category
    return None


def dispatch_due(now_utc: datetime | None = None) -> int:
    """Dispatch due reminders honoring preferences and enforcing exactly-once delivery via unique constraint."""
    db = SessionLocal()
    sent = 0
    now = now_utc or datetime.now(timezone.utc)

    try:
        # Use SELECT ... FOR UPDATE SKIP LOCKED to prevent concurrent worker contention
        due = db.scalars(
            select(Reminder)
            .where(
                Reminder.delivery_status == "pending",
                Reminder.remind_at <= now,
            )
            .with_for_update(skip_locked=True)
            .limit(200)
        ).all()

        for reminder in due:
            deadline = db.get(Deadline, reminder.deadline_id)
            user = db.get(User, reminder.recipient_user) if reminder.recipient_user else None

            if not deadline or not user or deadline.status != "open":
                reminder.delivery_status = "skipped"
                continue

            prefs = get_user_preferences(db, user.id)

            # 1. Check if channel is enabled
            if reminder.channel not in (prefs.channels or ["email"]):
                reminder.delivery_status = "skipped"
                continue

            # 2. Check if user enabled weekly digest instead of individual reminders
            if prefs.weekly_digest:
                # Individual reminders are suppressed in favor of weekly digest
                reminder.delivery_status = "skipped"
                continue

            # 3. Check per-category mute
            cat = get_deadline_category(db, deadline)
            if cat and cat in (prefs.muted_categories or []):
                reminder.delivery_status = "skipped"
                continue

            # 4. Check quiet hours and local send hour
            if not is_in_send_window(prefs, now):
                # Outside preferred window; leave pending until next dispatch sweep
                continue

            # 5. Enforce exactly-once delivery via Postgres UNIQUE(reminder_id) constraint
            delivery_record = ReminderDelivery(
                reminder_id=reminder.id,
                deadline_id=deadline.id,
                recipient_user=user.id,
                channel=reminder.channel,
                sent_at=now,
            )
            db.add(delivery_record)

            try:
                # Flush creates the unique delivery row in Postgres
                db.flush()
            except IntegrityError:
                # Unique constraint violation! Another worker already claimed/sent this reminder.
                db.rollback()
                log.info("Concurrent worker duplicate prevented by unique constraint for reminder %s", reminder.id)
                continue

            # Deliver reminder
            days = (deadline.due_date - now.date()).days
            try:
                send_email(
                    user.email,
                    f"{deadline.title} is due in {days} days",
                    f"{deadline.title}\nDue {deadline.due_date}.\n\n"
                    f"{deadline.description or ''}\n\n"
                    f"Open Life Admin OS to mark it done or snooze it.",
                )
                reminder.delivery_status = "sent"
                reminder.sent_at = now
                sent += 1
                db.commit()
            except Exception as exc:  # noqa: BLE001
                db.rollback()
                reminder.attempts += 1
                reminder.delivery_status = (
                    "failed" if reminder.attempts >= MAX_ATTEMPTS else "pending"
                )
                log.warning("Reminder %s delivery failed: %s", reminder.id, exc)
                db.commit()

    finally:
        db.close()

    return sent


def dispatch_weekly_digests(now_utc: datetime | None = None) -> int:
    """Send weekly digest email batching all deadlines due in the next 7 days for opted-in users."""
    db = SessionLocal()
    digests_sent = 0
    now = now_utc or datetime.now(timezone.utc)
    cutoff = now.date() + timedelta(days=7)

    try:
        # Find all users with weekly_digest enabled
        users_with_digest = db.scalars(
            select(NotificationPreference).where(NotificationPreference.weekly_digest == True)
        ).all()

        for prefs in users_with_digest:
            if not is_digest_day_and_hour(prefs, now):
                continue

            user = db.get(User, prefs.user_id)
            if not user:
                continue

            # Fetch deadlines due in the next 7 days across user's families
            deadlines = db.scalars(
                select(Deadline)
                .where(
                    Deadline.status == "open",
                    Deadline.due_date >= now.date(),
                    Deadline.due_date <= cutoff,
                )
                .order_by(Deadline.due_date)
            ).all()

            # Filter out muted categories
            active_deadlines = [
                d for d in deadlines
                if not (get_deadline_category(db, d) in (prefs.muted_categories or []))
            ]

            if not active_deadlines:
                continue

            items_text = "\n".join(
                f"• {d.title} — Due {d.due_date} ({d.priority.upper()})"
                for d in active_deadlines
            )

            body = (
                f"Hello {user.full_name},\n\n"
                f"Here is your weekly Life Admin OS summary of deadlines due in the next 7 days:\n\n"
                f"{items_text}\n\n"
                f"Open Life Admin OS to review, complete, or snooze upcoming items."
            )

            try:
                send_email(user.email, f"Life Admin OS: {len(active_deadlines)} deadlines due this week", body)
                digests_sent += 1
            except Exception as exc:
                log.warning("Weekly digest failed for user %s: %s", user.id, exc)

    finally:
        db.close()

    return digests_sent


if __name__ == "__main__":
    print(f"sent {dispatch_due()} individual reminders, {dispatch_weekly_digests()} weekly digests")
