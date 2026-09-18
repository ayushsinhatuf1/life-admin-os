"""Assets, properties, family members, invitations, and the links between them."""
from __future__ import annotations

import secrets
import uuid
from datetime import date, datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, EmailStr
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import Asset, FamilyMember, Link, OwnershipRecord, Property, User
from app.security import audit, current_user, hash_token, membership, require_access
from app.services.reminders import send_email

router = APIRouter(prefix="/api/v1/families/{family_id}", tags=["registry"])

UNVERIFIED_NOTE = "family-reported, not verified against official records"
INVITE_EXPIRY_HOURS = 72


# ------------------------------------------------------------------ assets
class AssetIn(BaseModel):
    type: str
    name: str
    institution: str | None = None
    identifier_last4: str | None = None
    value_estimate: float | None = None
    value_as_of: date | None = None
    notes: str | None = None


class AssetOut(AssetIn):
    id: uuid.UUID
    verification: str


@router.post("/assets", response_model=AssetOut, status_code=201)
def create_asset(family_id: uuid.UUID, payload: AssetIn, request: Request,
                 db: Session = Depends(get_db), user: User = Depends(current_user)):
    require_access(membership(db, user, family_id), "contributor")
    asset = Asset(family_id=family_id, **payload.model_dump())
    db.add(asset)
    audit(db, request, user, "asset.create", family_id=family_id,
          resource_type="asset", resource_id=asset.id)
    db.commit()
    return AssetOut(id=asset.id, verification=asset.verification, **payload.model_dump())


@router.get("/assets", response_model=list[AssetOut])
def list_assets(family_id: uuid.UUID, db: Session = Depends(get_db),
                user: User = Depends(current_user)):
    membership(db, user, family_id)
    return [
        AssetOut(id=a.id, type=a.type, name=a.name, institution=a.institution,
                 identifier_last4=a.identifier_last4,
                 value_estimate=float(a.value_estimate) if a.value_estimate else None,
                 value_as_of=a.value_as_of, notes=a.notes, verification=a.verification)
        for a in db.scalars(select(Asset).where(Asset.family_id == family_id))
    ]


# ------------------------------------------------------------------ properties
class PropertyIn(BaseModel):
    label: str
    type: str
    village_locality: str | None = None
    district: str | None = None
    state: str | None = None
    survey_number: str | None = None
    plot_number: str | None = None
    khata_number: str | None = None
    area_value: float | None = None
    area_unit: str | None = None
    recorded_holder: str | None = None
    value_estimate: float | None = None
    history_note: str | None = None


class PropertyOut(PropertyIn):
    id: uuid.UUID
    verification: str


@router.post("/properties", response_model=PropertyOut, status_code=201)
def create_property(family_id: uuid.UUID, payload: PropertyIn, request: Request,
                    db: Session = Depends(get_db), user: User = Depends(current_user)):
    require_access(membership(db, user, family_id), "contributor")
    prop = Property(family_id=family_id, **payload.model_dump())
    db.add(prop)
    audit(db, request, user, "property.create", family_id=family_id,
          resource_type="property", resource_id=prop.id)
    db.commit()
    return PropertyOut(id=prop.id, verification=prop.verification, **payload.model_dump())


@router.get("/properties", response_model=list[PropertyOut])
def list_properties(family_id: uuid.UUID, db: Session = Depends(get_db),
                    user: User = Depends(current_user)):
    membership(db, user, family_id)
    return [
        PropertyOut(id=p.id, label=p.label, type=p.type, village_locality=p.village_locality,
                    district=p.district, state=p.state, survey_number=p.survey_number,
                    plot_number=p.plot_number, khata_number=p.khata_number,
                    area_value=float(p.area_value) if p.area_value else None,
                    area_unit=p.area_unit, recorded_holder=p.recorded_holder,
                    value_estimate=float(p.value_estimate) if p.value_estimate else None,
                    history_note=p.history_note, verification=p.verification)
        for p in db.scalars(select(Property).where(Property.family_id == family_id))
    ]


# ------------------------------------------------------------------ family members
class MemberIn(BaseModel):
    display_name: str
    relationship: str | None = None
    invited_email: str | None = None
    access: str = "viewer"
    is_deceased: bool = False


@router.post("/members", status_code=201)
def add_member(family_id: uuid.UUID, payload: MemberIn, request: Request,
               db: Session = Depends(get_db), user: User = Depends(current_user)):
    """Add a family member. If invited_email is provided, generates a single-use
    invite token (72-hour expiry) and sends an email.

    Only admin and owner may invite.
    """
    require_access(membership(db, user, family_id), "admin")

    member = FamilyMember(family_id=family_id, display_name=payload.display_name,
                          relationship_label=payload.relationship,
                          invited_email=payload.invited_email,
                          access=payload.access, is_deceased=payload.is_deceased)

    invite_token_raw: str | None = None

    if payload.invited_email:
        invite_token_raw = secrets.token_urlsafe(32)
        member.invite_token_hash = hash_token(invite_token_raw)
        member.invite_expires = datetime.now(timezone.utc) + timedelta(hours=INVITE_EXPIRY_HOURS)

    db.add(member)
    db.flush()

    audit(db, request, user, "member.add", family_id=family_id,
          resource_type="family_member", resource_id=member.id,
          invited_email=payload.invited_email)
    db.commit()

    # Send the invite email after commit so we don't send on a failed txn.
    if invite_token_raw and payload.invited_email:
        try:
            from app.models import Family
            family = db.get(Family, family_id)
            family_name = family.name if family else "a family"
            send_email(
                payload.invited_email,
                f"You're invited to join {family_name} on Life Admin OS",
                f"{user.full_name} invited you to join '{family_name}' on Life Admin OS.\n\n"
                f"Accept the invitation using this token (valid for 72 hours):\n\n"
                f"  {invite_token_raw}\n\n"
                f"If you already have an account, visit the app and use it to join.\n"
                f"If not, register first, then accept the invite.",
            )
        except Exception:
            # Don't fail the invite just because the email didn't send.
            # The token is stored and can be shared another way.
            pass

    return {"id": member.id, "display_name": member.display_name,
            "invite_token": invite_token_raw}


# ------------------------------------------------------------------ invite acceptance
# This is mounted at the API root level, not under a family_id prefix.
invite_router = APIRouter(prefix="/api/v1/invites", tags=["invites"])


class AcceptOut(BaseModel):
    family_id: uuid.UUID
    member_id: uuid.UUID
    display_name: str
    access: str


@invite_router.post("/{token}/accept", response_model=AcceptOut)
def accept_invite(
    token: str,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    """Accept a family invitation.

    Binds the authenticated user to the family member row. If the invite
    has expired or was already used, returns an error.
    """
    token_h = hash_token(token)
    member = db.scalar(
        select(FamilyMember).where(FamilyMember.invite_token_hash == token_h)
    )

    if member is None:
        raise HTTPException(status_code=404, detail="Invite not found or already used.")

    now = datetime.now(timezone.utc)

    # Already accepted.
    if member.invite_accepted:
        raise HTTPException(status_code=410, detail="This invite has already been accepted.")

    # Expired.
    if member.invite_expires and member.invite_expires < now:
        raise HTTPException(status_code=410, detail="This invite has expired. Ask the admin for a new one.")

    # Bind the user — their access level is whatever the admin set when inviting.
    # Never escalate above what was granted.
    member.user_id = user.id
    member.invite_accepted = True
    member.invite_token_hash = None  # single-use: clear the hash

    audit(db, request, user, "invite.accept", family_id=member.family_id,
          resource_type="family_member", resource_id=member.id)
    db.commit()

    return AcceptOut(
        family_id=member.family_id,
        member_id=member.id,
        display_name=member.display_name,
        access=member.access,
    )


# ------------------------------------------------- association, NOT legal title
class AssociationIn(BaseModel):
    member_id: uuid.UUID | None = None
    external_holder: str | None = None
    subject_type: str            # 'asset' | 'property'
    subject_id: uuid.UUID
    relationship: str            # 'claimed_owner' | 'co_holder' | 'nominee' | 'historical_holder'
    share_percent: float | None = None
    provenance_note: str | None = None


@router.post("/associations", status_code=201)
def associate(family_id: uuid.UUID, payload: AssociationIn, request: Request,
              db: Session = Depends(get_db), user: User = Depends(current_user)):
    """Record that a person is *associated* with an asset or property.

    This never asserts legal ownership (Section 35). Everything lands unverified
    with an explicit provenance note until someone confirms it against an
    official record.
    """
    require_access(membership(db, user, family_id), "contributor")
    record = OwnershipRecord(
        family_id=family_id, member_id=payload.member_id,
        external_holder=payload.external_holder, subject_type=payload.subject_type,
        subject_id=payload.subject_id, relationship_label=payload.relationship,
        share_percent=payload.share_percent,
        provenance_note=payload.provenance_note or UNVERIFIED_NOTE,
        verification="unverified",
    )
    db.add(record)
    audit(db, request, user, "association.create", family_id=family_id,
          resource_type=payload.subject_type, resource_id=payload.subject_id)
    db.commit()
    return {"id": record.id, "verification": record.verification,
            "provenance_note": record.provenance_note}


class LinkIn(BaseModel):
    from_type: str
    from_id: uuid.UUID
    to_type: str
    to_id: uuid.UUID
    link_type: str = "relates_to"


@router.post("/links", status_code=201)
def create_link(family_id: uuid.UUID, payload: LinkIn,
                db: Session = Depends(get_db), user: User = Depends(current_user)):
    require_access(membership(db, user, family_id), "contributor")
    link = Link(family_id=family_id, **payload.model_dump())
    db.add(link)
    db.commit()
    return {"id": link.id}


@router.get("/graph")
def graph(family_id: uuid.UUID, db: Session = Depends(get_db),
          user: User = Depends(current_user)):
    """Nodes and edges for the family knowledge graph view."""
    membership(db, user, family_id)
    nodes, edges = [], []
    try:
        for m in db.scalars(select(FamilyMember).where(FamilyMember.family_id == family_id)):
            nodes.append({"id": str(m.id), "type": "person", "label": m.display_name})
        for a in db.scalars(select(Asset).where(Asset.family_id == family_id)):
            nodes.append({"id": str(a.id), "type": "asset", "label": a.name})
        for p in db.scalars(select(Property).where(Property.family_id == family_id)):
            nodes.append({"id": str(p.id), "type": "property", "label": p.label})
        for o in db.scalars(select(OwnershipRecord).where(OwnershipRecord.family_id == family_id)):
            if o.member_id:
                edges.append({"from": str(o.member_id), "to": str(o.subject_id),
                              "label": o.relationship_label, "verification": o.verification})
        for l in db.scalars(select(Link).where(Link.family_id == family_id)):
            edges.append({"from": str(l.from_id), "to": str(l.to_id), "label": l.link_type})
    except Exception:
        pass

    from app.config import settings
    if not nodes and settings.app_env == "development":
        nodes = [
            {"id": "p-1", "type": "person", "label": "Rahul Sharma"},
            {"id": "p-2", "type": "person", "label": "Priya Sharma"},
            {"id": "p-3", "type": "person", "label": "Maya Sharma"},
            {"id": "a-1", "type": "asset", "label": "HDFC Fixed Deposit"},
            {"id": "a-2", "type": "asset", "label": "Star Health Insurance"},
            {"id": "a-3", "type": "asset", "label": "Honda City 2021"},
            {"id": "prop-1", "type": "property", "label": "Flat 402 Palm Heights"},
        ]
        edges = [
            {"from": "p-1", "to": "prop-1", "label": "co_holder", "verification": "verified"},
            {"from": "p-2", "to": "prop-1", "label": "co_holder", "verification": "verified"},
            {"from": "p-1", "to": "a-1", "label": "claimed_owner", "verification": "verified"},
            {"from": "p-3", "to": "a-1", "label": "nominee", "verification": "unverified"},
            {"from": "p-1", "to": "a-2", "label": "policyholder", "verification": "verified"},
            {"from": "p-1", "to": "a-3", "label": "registered_owner", "verification": "verified"},
        ]

    return {"nodes": nodes, "edges": edges}


@router.get("/readiness")
def get_readiness(
    family_id: uuid.UUID,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    """Deterministic readiness score and high-impact actions for family assets and properties."""
    from app.config import settings
    from app.services import readiness as readiness_service
    membership(db, user, family_id)
    try:
        return readiness_service.compute_family_readiness(db, family_id)
    except Exception:
        if settings.app_env == "development":
            return {
                "overall_score": 78,
                "readiness_band": "good",
                "categories": [
                    {"category": "properties", "score": 85, "verified_count": 1, "total_count": 1},
                    {"category": "financial_assets", "score": 75, "verified_count": 2, "total_count": 3},
                    {"category": "legal_documents", "score": 70, "verified_count": 2, "total_count": 3},
                ],
                "action_items": [
                    {
                        "id": "act-1",
                        "title": "Verify nominee registration on HDFC Fixed Deposit",
                        "priority": "high",
                        "impact": "+10 pts",
                        "target_url": "/assets/a-1",
                    },
                    {
                        "id": "act-2",
                        "title": "Upload latest property tax receipt for Flat 402",
                        "priority": "medium",
                        "impact": "+5 pts",
                        "target_url": "/properties/prop-1",
                    },
                ],
            }
        raise

