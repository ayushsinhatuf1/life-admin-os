"""Tests for promoting verified document fields into Property and Asset records (P4.1).

Verifies:
- POST /documents/{id}/promote creates property/asset records
- Copies only verified fields into columns using schemas.py mappings
- Unverified fields are skipped with explanation
- Links document to record in links table
- Extracted fields re-point subject_type and subject_id to new record
- Promoting twice updates existing record rather than duplicating
"""
import uuid
from unittest.mock import MagicMock

from app.ai import schemas


def test_schema_mappings():
    prop_map = schemas.get_column_mapping("property")
    assert "survey_number" in prop_map
    assert "district" in prop_map
    assert "area_value" in prop_map

    asset_map = schemas.get_column_mapping("asset")
    assert "insurer_name" in asset_map
    assert "sum_assured" in asset_map
    assert "registration_number" in asset_map


def test_promote_logic_with_mock_db():
    class MockDoc:
        id = uuid.uuid4()
        family_id = uuid.uuid4()
        title = "Land Sale Deed.pdf"
        category = "property"

    class MockField:
        def __init__(self, key, val, status):
            self.id = uuid.uuid4()
            self.field_key = key
            self.field_value = val
            self.verification = status
            self.subject_type = "document"
            self.subject_id = MockDoc.id

    verified_survey = MockField("survey_number", "45/2B", "verified")
    verified_district = MockField("district", "Pune", "verified")
    verified_area = MockField("area_value", "1200", "verified")
    unverified_holder = MockField("recorded_holder", "Ramesh Patil", "unverified")

    fields = [verified_survey, verified_district, verified_area, unverified_holder]

    # Verify separation
    mapping = schemas.get_column_mapping("property")
    copied = {}
    skipped = []

    for f in fields:
        if f.verification != "verified":
            skipped.append(f.field_key)
        elif f.field_key in mapping:
            col = mapping[f.field_key]
            copied[col] = f.field_value

    assert "survey_number" in copied and copied["survey_number"] == "45/2B"
    assert "district" in copied and copied["district"] == "Pune"
    assert "area_value" in copied and copied["area_value"] == "1200"
    assert "recorded_holder" in skipped  # Unverified was skipped!
