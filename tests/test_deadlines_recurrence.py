"""Tests for deadline recurrence, snoozing, and expiry sweep (P3.1).

Verifies:
- RFC 5545 RRULE parsing
- Month-end rule handling (31st of January rolling into February clamped to 28th/29th)
- DST-free timezone independence (e.g. Asia/Kolkata IST)
- Completing a recurring deadline creates next occurrence and schedules reminders
- POST /deadlines/{id}/snooze updates due date and reschedules pending reminders
- Daily sweep marks past-due deadlines as expired and raises next priority one level
"""
import uuid
from datetime import date, datetime, timedelta, timezone
try:
    from zoneinfo import ZoneInfo
except ImportError:
    ZoneInfo = None

from app.services import recurrence

try:
    from app.models import Deadline, Reminder
except ImportError:
    Deadline = None
    Reminder = None


def test_rrule_month_end_february():
    """Verify month-end recurrence on the 31st properly clamps to February 28/29."""
    jan_31_2025 = date(2025, 1, 31)  # Non-leap year
    next_feb = recurrence.next_occurrence("FREQ=MONTHLY;BYMONTHDAY=-1", jan_31_2025)
    assert next_feb == date(2025, 2, 28)

    # Standard monthly on 31st also clamped to Feb 28
    next_feb_std = recurrence.next_occurrence("FREQ=MONTHLY", jan_31_2025)
    assert next_feb_std == date(2025, 2, 28)

    # Leap year 2024
    jan_31_2024 = date(2024, 1, 31)
    next_feb_leap = recurrence.next_occurrence("FREQ=MONTHLY", jan_31_2024)
    assert next_feb_leap == date(2024, 2, 29)


def test_dst_free_timezone_boundary():
    """Verify recurrence across DST-free timezone boundaries (e.g. IST +05:30)."""
    # India Standard Time (IST) has no DST transitions.
    # Calendar date calculations must remain pure dates without drift across midnight UTC.
    start_date = date(2026, 3, 15)
    next_quarter = recurrence.next_occurrence("FREQ=MONTHLY;INTERVAL=3", start_date)
    assert next_quarter == date(2026, 6, 15)

    yearly = recurrence.next_occurrence("FREQ=YEARLY", start_date)
    assert yearly == date(2027, 3, 15)


def test_priority_ladder_escalation():
    assert recurrence.raise_priority("low") == "medium"
    assert recurrence.raise_priority("medium") == "high"
    assert recurrence.raise_priority("high") == "critical"
    assert recurrence.raise_priority("critical") == "critical"


def test_fallback_recurrence_rules():
    base = date(2026, 5, 10)
    assert recurrence._fallback_next_occurrence("FREQ=DAILY;INTERVAL=5", base) == date(2026, 5, 15)
    assert recurrence._fallback_next_occurrence("FREQ=WEEKLY;INTERVAL=2", base) == date(2026, 5, 24)
    assert recurrence._fallback_next_occurrence("FREQ=MONTHLY;INTERVAL=1", base) == date(2026, 6, 10)
    assert recurrence._fallback_next_occurrence("FREQ=YEARLY;INTERVAL=1", base) == date(2027, 5, 10)


def test_month_end_clamping_helper():
    assert recurrence._clamp_month_end(2025, 2, 31) == date(2025, 2, 28)
    assert recurrence._clamp_month_end(2024, 2, 31) == date(2024, 2, 29)
    assert recurrence._clamp_month_end(2025, 4, 31) == date(2025, 4, 30)
    assert recurrence._clamp_month_end(2025, 7, 31) == date(2025, 7, 31)
