"""Billing webhooks and manual tier assignment (Phase 3 stub)."""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.api.v1.endpoints.auth import get_current_user
from app.core.config import settings
from app.models.subscription import SubscriptionRecord
from app.models.user import User

router = APIRouter()


class ManualTierRequest(BaseModel):
    tier: str = Field(pattern="^(free|pro|creator)$")
    days: int = Field(30, ge=1, le=365)


class StripeWebhookPayload(BaseModel):
    """Minimal stub — extend when Stripe is wired."""
    type: str
    data: dict[str, Any] = Field(default_factory=dict)


@router.post("/webhook/stripe")
async def stripe_webhook(
    payload: StripeWebhookPayload,
    db: Session = Depends(get_db),
    stripe_signature: str | None = Header(default=None, alias="Stripe-Signature"),
) -> dict[str, str]:
    secret = getattr(settings, "STRIPE_WEBHOOK_SECRET", None) or ""
    if secret and not stripe_signature:
        raise HTTPException(401, "missing Stripe-Signature")

    # Stub: checkout.session.completed -> upgrade user to pro/creator
    if payload.type == "checkout.session.completed":
        obj = payload.data.get("object") or {}
        user_id = obj.get("client_reference_id") or obj.get("metadata", {}).get("user_id")
        tier = obj.get("metadata", {}).get("tier", "pro")
        if user_id:
            user = db.query(User).filter(User.id == uuid.UUID(str(user_id))).first()
            if user:
                user.subscription_tier = tier
                user.tier_expires_at = datetime.now(timezone.utc) + timedelta(days=30)
                sub = SubscriptionRecord(
                    id=uuid.uuid4(),
                    user_id=user.id,
                    provider="stripe",
                    external_id=str(obj.get("id", "")),
                    tier=tier,
                    status="active",
                    current_period_end=user.tier_expires_at,
                )
                db.add(sub)
                db.commit()
    return {"status": "ok"}


@router.post("/admin/set-tier")
async def admin_set_tier(
    body: ManualTierRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Dev/admin: assign tier without payment (for internal testing)."""
    if user.role != "admin":
        raise HTTPException(403, "admin only")
    user.subscription_tier = body.tier
    user.tier_expires_at = datetime.now(timezone.utc) + timedelta(days=body.days)
    db.commit()
    return {
        "user_id": str(user.id),
        "tier": body.tier,
        "tier_expires_at": user.tier_expires_at.isoformat(),
    }
