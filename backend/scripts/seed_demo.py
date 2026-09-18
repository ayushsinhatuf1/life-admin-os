"""Realistic demo data generator (Section 33).

Creates:
- A family with four members across three generations (Ramesh, Rahul, Priya, Aarav)
- Realistic source documents:
  1. Health Insurance policy
  2. Vehicle Registration Certificate
  3. 1978-style Land Record / 7/12 Extract
  4. Property with unverified holder (Flat 402 Palm Heights)
- Four upcoming deadlines at varied urgencies
- One document sitting in the review queue needing human verification
- Idempotent: running twice updates/preserves without duplicating.
"""
from __future__ import annotations

import hashlib
import io
import sys
import uuid
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

# Add backend directory to sys.path
backend_dir = Path(__file__).resolve().parent.parent
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

try:
    from sqlalchemy import select
    from sqlalchemy.orm import Session
except ImportError:
    select = None
    Session = None

try:
    from app.db import engine, SessionLocal
    from app.models import (
        Asset,
        Deadline,
        Document,
        ExtractedField,
        Family,
        FamilyMember,
        Property,
        Reminder,
        User,
    )
    from app.security import hash_password
    from app.services import storage
except ImportError:
    engine = None
    SessionLocal = None
    hash_password = lambda p: f"hashed_{p}"
    class _StorageMock:
        @staticmethod
        def put(k, b, m): pass
    storage = _StorageMock()

# Deterministic UUIDs for demo idempotency
DEMO_FAMILY_ID = uuid.UUID("11111111-2222-3333-4444-555555555555")
USER_RAHUL_ID = uuid.UUID("aaaaaaaa-1111-2222-3333-444444444444")
USER_PRIYA_ID = uuid.UUID("bbbbbbbb-1111-2222-3333-444444444444")
USER_RAMESH_ID = uuid.UUID("cccccccc-1111-2222-3333-444444444444")
USER_AARAV_ID = uuid.UUID("dddddddd-1111-2222-3333-444444444444")

DOC_INSURANCE_ID = uuid.UUID("10000000-0000-0000-0000-000000000001")
DOC_VEHICLE_ID = uuid.UUID("10000000-0000-0000-0000-000000000002")
DOC_LAND_ID = uuid.UUID("10000000-0000-0000-0000-000000000003")
DOC_REVIEW_ID = uuid.UUID("10000000-0000-0000-0000-000000000004")


def generate_simple_pdf(title: str, lines: list[str]) -> bytes:
    """Generate minimal conforming PDF with text stream."""
    stream_content = "BT\n/F1 14 Tf\n50 750 Td\n"
    stream_content += f"({title}) Tj\n/F1 10 Tf\n"
    y_offset = -20
    for line in lines:
        escaped = line.replace("(", "\\(").replace(")", "\\)")
        stream_content += f"0 {y_offset} Td\n({escaped}) Tj\n"
        y_offset = -14
    stream_content += "ET"

    stream_bytes = stream_content.encode("latin1")
    stream_len = len(stream_bytes)

    pdf_parts = [
        b"%PDF-1.4\n",
        b"1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj\n",
        b"2 0 obj\n<< /Type /Pages /Kids [3 0 R] /Count 1 >>\nendobj\n",
        b"3 0 obj\n<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>\nendobj\n",
        b"4 0 obj\n<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>\nendobj\n",
        f"5 0 obj\n<< /Length {stream_len} >>\nstream\n".encode("latin1"),
        stream_bytes,
        b"\nendstream\nendobj\n",
        b"xref\n0 6\n0000000000 65535 f \n",
        b"trailer\n<< /Size 6 /Root 1 0 R >>\nstartxref\n500\n%%EOF\n",
    ]
    return b"".join(pdf_parts)


def seed_demo_data(db: Session) -> dict[str, Any]:
    """Populate database with Section 33 demo family, records, and PDFs."""
    # 1. Users (Three Generations)
    users_spec = [
        (USER_RAHUL_ID, "rahul.sharma@example.in", "Rahul Sharma", "owner"),
        (USER_PRIYA_ID, "priya.sharma@example.in", "Priya Sharma", "admin"),
        (USER_RAMESH_ID, "ramesh.sharma@example.in", "Ramesh Sharma (Grandfather)", "viewer"),
        (USER_AARAV_ID, "aarav.sharma@example.in", "Aarav Sharma (Son)", "viewer"),
    ]

    for uid, email, full_name, access in users_spec:
        user = db.get(User, uid)
        if not user:
            user = User(
                id=uid,
                email=email,
                full_name=full_name,
                password_hash=hash_password("DemoPassword123!"),
                is_active=True,
            )
            db.add(user)
    db.flush()

    # 2. Family
    family = db.get(Family, DEMO_FAMILY_ID)
    if not family:
        family = Family(
            id=DEMO_FAMILY_ID,
            name="Sharma Family Vault",
            owner_user_id=USER_RAHUL_ID,
        )
        db.add(family)
        db.flush()

    # 3. Family Memberships
    relationships = {
        USER_RAHUL_ID: ("Rahul Sharma", "self", "owner"),
        USER_PRIYA_ID: ("Priya Sharma", "spouse", "admin"),
        USER_RAMESH_ID: ("Ramesh Sharma", "parent", "viewer"),
        USER_AARAV_ID: ("Aarav Sharma", "child", "viewer"),
    }
    for uid, (disp, rel, acc) in relationships.items():
        existing = db.scalar(
            select(FamilyMember).where(
                FamilyMember.family_id == DEMO_FAMILY_ID,
                FamilyMember.user_id == uid,
            )
        )
        if not existing:
            db.add(
                FamilyMember(
                    family_id=DEMO_FAMILY_ID,
                    user_id=uid,
                    display_name=disp,
                    relationship_label=rel,
                    access=acc,
                )
            )
    db.flush()

    # 4. Source Documents & PDFs
    today = date.today()

    doc_specs = [
        {
            "id": DOC_INSURANCE_ID,
            "title": "Star Health Comprehensive Insurance Policy.pdf",
            "category": "insurance",
            "status": "ready",
            "body": [
                "Insurer: Star Health and Allied Insurance Co Ltd",
                "Policy Number: POL-88776655",
                "Insured Persons: Rahul Sharma, Priya Sharma, Aarav Sharma",
                "Sum Insured: INR 10,00,000",
                f"Policy Expiry Date: {today + timedelta(days=30)}",
                "Annual Premium: INR 22,450",
            ],
            "fields": [
                ("policy_number", "Policy Number", "POL-88776655", 0.98, "verified"),
                ("sum_insured", "Sum Insured", "1000000", 0.95, "verified"),
                ("expiry_date", "Policy Expiry Date", str(today + timedelta(days=30)), 0.96, "verified"),
            ],
        },
        {
            "id": DOC_VEHICLE_ID,
            "title": "Vehicle Registration Certificate (MH12AB1234).pdf",
            "category": "vehicle",
            "status": "ready",
            "body": [
                "Form 23 - Certificate of Registration",
                "Registration No: MH12AB1234",
                "Owner: Rahul Sharma",
                "Make / Model: Honda City 1.5 i-VTEC",
                "Chassis No: MAKGM26569B123456",
                f"Registration Expiry: {today + timedelta(days=45)}",
            ],
            "fields": [
                ("registration_number", "Registration Number", "MH12AB1234", 0.99, "verified"),
                ("owner_name", "Registered Owner", "Rahul Sharma", 0.94, "verified"),
                ("expiry_date", "Fitness Expiry Date", str(today + timedelta(days=45)), 0.91, "verified"),
            ],
        },
        {
            "id": DOC_LAND_ID,
            "title": "1978 Ancestral Land Record Extract (Village Haveli).pdf",
            "category": "property",
            "status": "ready",
            "body": [
                "Village Form VII-XII (7/12 Extract) - Record of Rights",
                "District: Pune, Taluka: Haveli, Village: Wagholi",
                "Survey / Gat Number: 128/3B",
                "Total Area: 2.4 Hectares",
                "Recorded Holder: Ramesh Sharma and Ancestors",
                "Tenure: Class 1 Occupant",
            ],
            "fields": [
                ("survey_number", "Survey / Gat Number", "128/3B", 0.92, "verified"),
                ("recorded_holder", "Recorded Holder", "Ramesh Sharma", 0.88, "verified"),
                ("area", "Land Area", "2.4 Hectares", 0.89, "verified"),
            ],
        },
        {
            "id": DOC_REVIEW_ID,
            "title": "MSEDCL Electricity Bill - July 2026.pdf",
            "category": "utility",
            "status": "review_needed",  # Sitting in the review queue
            "body": [
                "Maharashtra State Electricity Distribution Co. Ltd.",
                "Consumer Number: 998877665544",
                "Billing Unit: 4501 Pune East",
                f"Bill Due Date: {today + timedelta(days=12)}",
                "Amount Payable: INR 2,840",
            ],
            "fields": [
                ("consumer_number", "Consumer Number", "998877665544", 0.82, "unverified"),
                ("due_date", "Bill Due Date", str(today + timedelta(days=12)), 0.68, "unverified"),
            ],
        },
    ]

    for dspec in doc_specs:
        doc = db.get(Document, dspec["id"])
        pdf_bytes = generate_simple_pdf(dspec["title"], dspec["body"])
        pdf_sha = hashlib.sha256(pdf_bytes).hexdigest()
        storage_key = f"documents/{DEMO_FAMILY_ID}/{dspec['id']}.pdf"

        try:
            storage.put(storage_key, pdf_bytes, "application/pdf")
        except Exception:
            pass

        if not doc:
            doc = Document(
                id=dspec["id"],
                family_id=DEMO_FAMILY_ID,
                uploaded_by=USER_RAHUL_ID,
                title=dspec["title"],
                category=dspec["category"],
                mime_type="application/pdf",
                size_bytes=len(pdf_bytes),
                sha256=pdf_sha,
                storage_key=storage_key,
                page_count=1,
                status=dspec["status"],
                ocr_text="\n".join(dspec["body"]),
            )
            db.add(doc)
            db.flush()

        # Add or update extracted fields
        for key, label, val, conf, ver in dspec["fields"]:
            existing_f = db.scalar(
                select(ExtractedField).where(
                    ExtractedField.document_id == doc.id,
                    ExtractedField.field_key == key,
                )
            )
            if not existing_f:
                db.add(
                    ExtractedField(
                        document_id=doc.id,
                        family_id=DEMO_FAMILY_ID,
                        field_key=key,
                        label=label,
                        field_value=val,
                        confidence=conf,
                        verification=ver,
                        source="ai_extracted",
                        source_page=1,
                        source_snippet=f"{label}: {val}",
                    )
                )

    # 5. Property with Unverified Holder
    unverified_prop = db.scalar(
        select(Property).where(
            Property.family_id == DEMO_FAMILY_ID,
            Property.label == "Flat 402 Palm Heights Sector 62",
        )
    )
    if not unverified_prop:
        db.add(
            Property(
                family_id=DEMO_FAMILY_ID,
                label="Flat 402 Palm Heights Sector 62",
                type="residential",
                area_value=1150,
                area_unit="sqft",
                district="Pune",
                survey_number="128/3B",
                recorded_holder="Rahul Sharma and Priya Sharma",
                verification="unverified",  # Explicitly unverified holder
            )
        )

    # 6. Four Upcoming Deadlines at Varied Urgencies
    deadlines_spec = [
        ("Star Health Policy Renewal", today + timedelta(days=30), "critical"),
        ("Honda City PUC & Insurance Check", today + timedelta(days=45), "high"),
        ("MSEDCL Electricity Bill Payment", today + timedelta(days=12), "medium"),
        ("HDFC Fixed Deposit Maturity Review", today + timedelta(days=90), "low"),
    ]

    for title, d_date, priority in deadlines_spec:
        dl = db.scalar(
            select(Deadline).where(
                Deadline.family_id == DEMO_FAMILY_ID,
                Deadline.title == title,
            )
        )
        if not dl:
            db.add(
                Deadline(
                    family_id=DEMO_FAMILY_ID,
                    title=title,
                    due_date=d_date,
                    priority=priority,
                    status="open",
                )
            )

    db.commit()

    return {
        "status": "success",
        "family_id": str(DEMO_FAMILY_ID),
        "family_name": "Sharma Family Vault",
        "members_count": len(users_spec),
        "documents_count": len(doc_specs),
        "deadlines_count": len(deadlines_spec),
        "review_queue_count": 1,
    }


def main():
    print("Seeding Section 33 Demo Family...")
    if SessionLocal:
        db = SessionLocal()
        try:
            res = seed_demo_data(db)
            print(f"Demo seeded successfully: {res}")
        finally:
            db.close()
    else:
        print("SessionLocal not available; dry-run PDF generation test:")
        pdf = generate_simple_pdf("Test Document", ["Line 1", "Line 2"])
        print(f"Generated test PDF: {len(pdf)} bytes")


if __name__ == "__main__":
    main()
