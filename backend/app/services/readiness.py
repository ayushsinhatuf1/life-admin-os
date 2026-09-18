"""Deterministic Asset and Property Information Readiness Score (P4.3).

Scores each property and asset against five objective verification criteria:
1. Supporting document linked
2. Verified holder / ownership record
3. Quantified area or estimated value
4. Location or institution identifier
5. Associated living family member

Computes:
- Overall readiness percentage
- Per-record score breakdown
- Single highest-impact action the user can take
"""
from __future__ import annotations

import uuid
from typing import Any, Sequence

try:
    from sqlalchemy import select
    from sqlalchemy.orm import Session
    from app.models import Asset, FamilyMember, Link, OwnershipRecord, Property
except ImportError:
    select = None
    Session = None
    Asset = None
    FamilyMember = None
    Link = None
    OwnershipRecord = None
    Property = None


def score_record(
    record_type: str,
    record: Any,
    has_document: bool,
    has_verified_holder: bool,
    has_value_or_area: bool,
    has_location: bool,
    has_living_member: bool,
) -> dict[str, Any]:
    """Score a single property or asset record deterministically out of 100 points."""
    checks = {
        "supporting_document": has_document,
        "verified_holder": has_verified_holder,
        "quantified_value_or_area": has_value_or_area,
        "location_or_institution": has_location,
        "associated_living_member": has_living_member,
    }

    points = sum(20 for passed in checks.values() if passed)
    missing = [k for k, passed in checks.items() if not passed]

    return {
        "id": str(getattr(record, "id", "")),
        "type": record_type,
        "name": getattr(record, "label", getattr(record, "name", "Record")),
        "score": points,
        "checks": checks,
        "missing_items": missing,
    }


def compute_family_readiness(
    db: Session,
    family_id: uuid.UUID,
) -> dict[str, Any]:
    """Compute overall readiness score, per-record breakdown, and highest impact action."""
    properties = db.scalars(select(Property).where(Property.family_id == family_id)).all()
    assets = db.scalars(select(Asset).where(Asset.family_id == family_id)).all()
    links = db.scalars(select(Link).where(Link.family_id == family_id)).all()
    ownerships = db.scalars(select(OwnershipRecord).where(OwnershipRecord.family_id == family_id)).all()
    members = {m.id: m for m in db.scalars(select(FamilyMember).where(FamilyMember.family_id == family_id)).all()}

    # Sets of record IDs that have supporting documents linked
    doc_linked_record_ids = set()
    for l in links:
        if l.from_type == "document":
            doc_linked_record_ids.add(l.to_id)
        elif l.to_type == "document":
            doc_linked_record_ids.add(l.from_id)

    # Subject IDs with verified ownership and living member association
    verified_holder_subjects = set()
    living_member_subjects = set()

    for o in ownerships:
        if o.verification == "verified":
            verified_holder_subjects.add(o.subject_id)
        if o.member_id and o.member_id in members:
            member = members[o.member_id]
            if not member.is_deceased:
                living_member_subjects.add(o.subject_id)

    breakdown = []

    # Score properties
    for p in properties:
        has_doc = p.id in doc_linked_record_ids
        has_holder = p.id in verified_holder_subjects or (p.verification == "verified" and bool(p.recorded_holder))
        has_val = bool(p.area_value and p.area_value > 0) or bool(p.value_estimate and p.value_estimate > 0)
        has_loc = bool(p.village_locality or p.district or p.state)
        has_living = p.id in living_member_subjects

        breakdown.append(
            score_record(
                record_type="property",
                record=p,
                has_document=has_doc,
                has_verified_holder=has_holder,
                has_value_or_area=has_val,
                has_location=has_loc,
                has_living_member=has_living,
            )
        )

    # Score assets
    for a in assets:
        has_doc = a.id in doc_linked_record_ids
        has_holder = a.id in verified_holder_subjects or (a.verification == "verified")
        has_val = bool(a.value_estimate and a.value_estimate > 0)
        has_loc = bool(a.institution)
        has_living = a.id in living_member_subjects

        breakdown.append(
            score_record(
                record_type="asset",
                record=a,
                has_document=has_doc,
                has_verified_holder=has_holder,
                has_value_or_area=has_val,
                has_location=has_loc,
                has_living_member=has_living,
            )
        )

    if not breakdown:
        return {
            "overall_percentage": 100,
            "total_records": 0,
            "breakdown": [],
            "highest_impact_action": "Add an asset or property to the family registry to track readiness.",
        }

    total_score = sum(b["score"] for b in breakdown)
    overall_pct = round(total_score / len(breakdown))

    # Determine highest-impact missing item
    # Priority order for actions: supporting_document > verified_holder > associated_living_member > location > value
    ACTION_PRIORITY = [
        "supporting_document",
        "verified_holder",
        "associated_living_member",
        "location_or_institution",
        "quantified_value_or_area",
    ]

    highest_action = None
    for priority_key in ACTION_PRIORITY:
        for item in sorted(breakdown, key=lambda x: x["score"]):
            if priority_key in item["missing_items"]:
                if priority_key == "supporting_document":
                    highest_action = f"Upload a supporting document for {item['name']} (+20% readiness)"
                elif priority_key == "verified_holder":
                    highest_action = f"Verify title or recorded ownership for {item['name']} (+20% readiness)"
                elif priority_key == "associated_living_member":
                    highest_action = f"Link a living family member to {item['name']} (+20% readiness)"
                elif priority_key == "location_or_institution":
                    highest_action = f"Add institution or location details for {item['name']} (+20% readiness)"
                elif priority_key == "quantified_value_or_area":
                    highest_action = f"Record estimated value or area for {item['name']} (+20% readiness)"
                break
        if highest_action:
            break

    if not highest_action:
        highest_action = "All records are 100% verified and fully documented."

    return {
        "overall_percentage": overall_pct,
        "total_records": len(breakdown),
        "breakdown": breakdown,
        "highest_impact_action": highest_action,
    }
