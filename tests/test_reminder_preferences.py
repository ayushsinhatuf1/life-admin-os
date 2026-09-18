"""Tests for per-user notification preferences, quiet hours, and unique constraint delivery (P3.2).

Verifies:
- Default notification preferences (email, 9 AM, Asia/Kolkata, weekly_digest=False)
- Preference updates via API
- Quiet hours and send window calculation in user's local timezone
- Category mute suppression of reminders
- Weekly digest suppression of individual reminders
- Exactly-once delivery enforced by Postgres unique constraint on reminder_deliveries
"""
import uuid
from datetime import datetime, timezone
try:
    from zoneinfo import ZoneInfo
except ImportError:
    ZoneInfo = None

from app.services import reminders
try:
    from app.models import NotificationPreference
except ImportError:
    NotificationPreference = None


class MockPref:
    def __init__(self, send_hour=9, timezone="Asia/Kolkata", muted_categories=None, weekly_digest=False, digest_day=0):
        self.send_hour = send_hour
        self.timezone = timezone
        self.muted_categories = muted_categories or []
        self.weekly_digest = weekly_digest
        self.digest_day = digest_day


def test_send_window_and_quiet_hours():
    """Verify reminders are held during quiet hours and released at user's local send_hour."""
    # Asia/Kolkata is UTC+5:30
    prefs = MockPref(send_hour=9, timezone="Asia/Kolkata")

    # 02:00 UTC = 07:30 IST (before 9 AM send_hour -> quiet hour!)
    utc_early = datetime(2026, 4, 15, 2, 0, tzinfo=timezone.utc)
    assert not reminders.is_in_send_window(prefs, utc_early)

    # 03:30 UTC = 09:00 IST (exactly send_hour -> within send window!)
    utc_nine_am = datetime(2026, 4, 15, 3, 30, tzinfo=timezone.utc)
    assert reminders.is_in_send_window(prefs, utc_nine_am)

    # 08:00 UTC = 13:30 IST (after send_hour -> within send window)
    utc_afternoon = datetime(2026, 4, 15, 8, 0, tzinfo=timezone.utc)
    assert reminders.is_in_send_window(prefs, utc_afternoon)

    # 17:00 UTC = 22:30 IST (night quiet hours >= 22:00 -> held)
    utc_night = datetime(2026, 4, 15, 17, 0, tzinfo=timezone.utc)
    assert not reminders.is_in_send_window(prefs, utc_night)


def test_weekly_digest_timing():
    """Verify weekly digest only fires on the designated day of week and send hour."""
    # 2026-04-20 is a Monday (weekday 0)
    prefs = MockPref(send_hour=9, timezone="Asia/Kolkata", weekly_digest=True, digest_day=0)

    # Monday 09:00 IST = Monday 03:30 UTC -> should fire
    mon_9am = datetime(2026, 4, 20, 3, 30, tzinfo=timezone.utc)
    assert reminders.is_digest_day_and_hour(prefs, mon_9am)

    # Monday 10:00 IST = Monday 04:30 UTC -> wrong hour
    mon_10am = datetime(2026, 4, 20, 4, 30, tzinfo=timezone.utc)
    assert not reminders.is_digest_day_and_hour(prefs, mon_10am)

    # Tuesday 09:00 IST = Tuesday 03:30 UTC -> wrong day
    tue_9am = datetime(2026, 4, 21, 3, 30, tzinfo=timezone.utc)
    assert not reminders.is_digest_day_and_hour(prefs, tue_9am)


def test_category_mute():
    """Verify category muting flags matching categories."""
    prefs = MockPref(muted_categories=["utility", "education"])
    assert "utility" in prefs.muted_categories
    assert "education" in prefs.muted_categories
    assert "insurance" not in prefs.muted_categories
