"""Tests for Product Analytics & Metrics Engine (P7.1, Section 34).

Verifies:
1. sanitize_properties strips all sensitive PII and document content.
2. track_event records clean events in the database.
3. compute_metrics calculates activation rate, TTV, accuracy, and retention targets.
"""
import sys
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

# Add backend directory to sys.path
backend_dir = Path(__file__).resolve().parent.parent / "backend"
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

from app.services.analytics import compute_metrics, sanitize_properties, track_event


class MockDB:
    def __init__(self):
        self.events = []
        self.docs = []
        self.users = []
        self.families = []
        self.family_members = []
        self.fields = []
        self.deliveries = []

    def add(self, obj):
        if hasattr(obj, "id") and not obj.id:
            obj.id = uuid.uuid4()
        if hasattr(obj, "created_at") and not obj.created_at:
            obj.created_at = datetime.now(timezone.utc)
        self.events.append(obj)

    def commit(self):
        pass

    def scalar(self, stmt):
        return 1

    def scalars(self, stmt):
        class ResultList:
            def __init__(self, items):
                self._items = items
            def all(self):
                return self._items
        return ResultList(self.events)


def test_sanitize_properties():
    raw = {
        "document_id": "doc-1234",
        "category": "insurance",
        "password": "supersecretpassword",
        "ocr_text": "This is raw OCR text with sensitive health diagnoses",
        "token": "bearer-token-secret",
        "was_edited": False,
        "processing_time_ms": 1240,
    }

    clean = sanitize_properties(raw)

    # Allowed keys preserved
    assert clean["document_id"] == "doc-1234"
    assert clean["category"] == "insurance"
    assert clean["was_edited"] is False
    assert clean["processing_time_ms"] == 1240

    # Sensitive keys strictly stripped
    assert "password" not in clean
    assert "ocr_text" not in clean
    assert "token" not in clean


def test_track_event():
    db = MockDB()
    user_id = uuid.uuid4()
    family_id = uuid.uuid4()

    event = track_event(
        db,
        event_name="document.processed",
        family_id=family_id,
        user_id=user_id,
        category="insurance",
        processing_time_ms=850,
        ocr_text="LEAKED SENSITIVE BODY TEXT",  # Must be stripped
    )

    assert len(db.events) == 1
    stored = db.events[0]
    assert stored.event_name == "document.processed"
    assert stored.family_id == family_id
    assert stored.user_id == user_id
    assert "ocr_text" not in stored.properties
    assert stored.properties["category"] == "insurance"


def test_compute_metrics():
    db = MockDB()
    user_id = uuid.uuid4()
    family_id = uuid.uuid4()
    now = datetime.now(timezone.utc)

    # Register event
    e_reg = type("Event", (), {
        "id": uuid.uuid4(),
        "event_name": "user.register",
        "family_id": family_id,
        "user_id": user_id,
        "properties": {},
        "created_at": now - timedelta(seconds=120),
    })()

    # Verify event (120s later -> TTV = 120s)
    e_verify = type("Event", (), {
        "id": uuid.uuid4(),
        "event_name": "field.verified",
        "family_id": family_id,
        "user_id": user_id,
        "properties": {"was_edited": False},
        "created_at": now,
    })()

    db.events = [e_reg, e_verify]

    metrics = compute_metrics(db)

    s = metrics["summary"]
    assert "activation_rate_percent" in s
    assert "time_to_value_seconds" in s
    assert "documents_processed_total" in s
    assert "critical_error_rate_percent" in s
    assert s["critical_error_rate_percent"] == 0.0

    # Verify targets
    assert metrics["targets"]["time_to_value_target_seconds"] == 180.0
    assert metrics["targets"]["activation_rate_target"] == 75.0


def run_all():
    test_sanitize_properties()
    test_track_event()
    test_compute_metrics()
    print("All analytics and product metrics tests PASSED.")


if __name__ == "__main__":
    run_all()
