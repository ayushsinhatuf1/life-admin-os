"""Admin and product metrics router (P7.1, Section 34).

Exposes:
- GET /api/v1/admin/metrics - Computes product analytics (activation, TTV, accuracy, retention)
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import FamilyMember, User
from app.security import current_user
from app.services import analytics

router = APIRouter(prefix="/api/v1/admin", tags=["admin"])


@router.get("/metrics")
def get_product_metrics(
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    # Verify caller is an admin or owner of at least one family
    is_admin = db.scalar(
        select(FamilyMember).where(
            FamilyMember.user_id == user.id,
            FamilyMember.access.in_(["admin", "owner"]),
        )
    )
    if not is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin metrics require admin or owner access.",
        )

    return analytics.compute_metrics(db)
