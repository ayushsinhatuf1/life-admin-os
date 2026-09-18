"""Data-subject rights and profile endpoints under DPDP Act (P6.3).

Routes:
- GET /api/v1/me - View profile and active membership
- GET /api/v1/me/consents - View versioned consent history
- POST /api/v1/me/consents/withdraw - Withdraw a specific consent (e.g. ai_processing)
- GET /api/v1/me/export - Request complete portable data export (24h signed URL)
- DELETE /api/v1/me - Request account erasure (immediate soft-delete, 30-day grace period)
"""
from __future__ import annotations

from typing import Any
import uuid

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel
from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import Consent, User
from app.security import audit, current_user
from app.services import dpdp

router = APIRouter(prefix="/api/v1/me", tags=["me", "dpdp"])


class ConsentWithdrawIn(BaseModel):
    purpose: str  # e.g. "ai_processing", "email_reminders"


class ConsentOut(BaseModel):
    id: uuid.UUID
    purpose: str
    granted: bool
    notice_version: str
    created_at: Any


class ExportOut(BaseModel):
    request_id: uuid.UUID
    status: str
    download_url: str
    expires_in_hours: int = 24


@router.get("")
def get_profile(user: User = Depends(current_user)):
    return {
        "id": user.id,
        "email": user.email,
        "full_name": user.full_name,
        "is_active": user.is_active,
    }


@router.get("/consents", response_model=list[ConsentOut])
def list_consents(db: Session = Depends(get_db), user: User = Depends(current_user)):
    consents = db.scalars(
        select(Consent).where(Consent.user_id == user.id).order_by(desc(Consent.created_at))
    ).all()
    return [
        ConsentOut(
            id=c.id,
            purpose=c.purpose,
            granted=c.granted,
            notice_version=c.notice_version,
            created_at=c.created_at,
        )
        for c in consents
    ]


@router.post("/consents/withdraw", response_model=ConsentOut)
def withdraw_consent(
    payload: ConsentWithdrawIn,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    if payload.purpose not in dpdp.DEFAULT_PURPOSES:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown purpose '{payload.purpose}'. Valid purposes: {', '.join(dpdp.DEFAULT_PURPOSES)}",
        )

    updated_consent = dpdp.withdraw_consent(db, user.id, payload.purpose)
    audit(db, request, user, "consent.withdrawn", purpose=payload.purpose)

    return ConsentOut(
        id=updated_consent.id,
        purpose=updated_consent.purpose,
        granted=updated_consent.granted,
        notice_version=updated_consent.notice_version,
        created_at=updated_consent.created_at,
    )


@router.get("/export", response_model=ExportOut)
def export_user_data(
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    req, download_url = dpdp.create_export_request(db, user.id)
    audit(db, request, user, "data_request.export", request_id=req.id)

    return ExportOut(
        request_id=req.id,
        status=req.status,
        download_url=download_url,
        expires_in_hours=24,
    )


@router.delete("")
def delete_account(
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    result = dpdp.request_erasure(db, user.id)
    audit(db, request, user, "data_request.erasure")
    return result
