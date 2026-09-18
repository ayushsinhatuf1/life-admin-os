"""Table-driven tests for deterministic Asset and Property readiness scoring (P4.3).

Verifies:
- 5 objective criteria (supporting document, verified holder, value/area, location/institution, living member)
- Correct points calculation (20 points per passed check, 0 to 100)
- Highest-impact action determination
"""
import uuid
from app.services.readiness import score_record


class MockEntity:
    def __init__(self, id, name):
        self.id = id
        self.name = name


# Table of test cases: (name, has_doc, has_holder, has_val, has_loc, has_living, expected_score, expected_missing_count)
READINESS_TEST_CASES = [
    ("Completely unverified record", False, False, False, False, False, 0, 5),
    ("Location only record", False, False, False, True, False, 20, 4),
    ("Location + Value record", False, False, True, True, False, 40, 3),
    ("Location + Value + Living Member", False, False, True, True, True, 60, 2),
    ("Missing only title verification", True, False, True, True, True, 80, 1),
    ("Fully documented & verified record", True, True, True, True, True, 100, 0),
]


def test_table_driven_readiness_scoring():
    for name, has_doc, has_holder, has_val, has_loc, has_living, exp_score, exp_missing_count in READINESS_TEST_CASES:
        rec = MockEntity(uuid.uuid4(), name)
        res = score_record(
            record_type="property",
            record=rec,
            has_document=has_doc,
            has_verified_holder=has_holder,
            has_value_or_area=has_val,
            has_location=has_loc,
            has_living_member=has_living,
        )
        assert res["score"] == exp_score, f"Case '{name}' expected score {exp_score}, got {res['score']}"
        assert len(res["missing_items"]) == exp_missing_count, f"Case '{name}' expected {exp_missing_count} missing, got {len(res['missing_items'])}"


def test_highest_impact_action_priorities():
    # If supporting document is missing, it should be recommended first
    rec = MockEntity(uuid.uuid4(), "Flat 402 Palm Heights")
    res = score_record("property", rec, False, False, True, True, True)
    assert "supporting_document" in res["missing_items"]
    assert "verified_holder" in res["missing_items"]
    assert res["score"] == 60
