"""Skill marketplace (Phase 3)."""
from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.api.v1.endpoints.auth import get_current_user
from app.models.skill_listing import SkillListing
from app.models.user import User
from app.services.entitlement_service import require_tier

router = APIRouter()


class CreateListingRequest(BaseModel):
    skill_id: str = Field(min_length=1)
    title: str = Field(min_length=1, max_length=200)
    description: str | None = None
    price_cents: int = Field(0, ge=0)
    currency: str = "CNY"
    license_type: str = Field("personal", pattern="^(personal|commercial)$")


class ListingResponse(BaseModel):
    id: str
    skill_id: str
    seller_id: str
    title: str
    description: str | None
    price_cents: int
    currency: str
    license_type: str
    status: str
    is_active: bool


def _serialize(row: SkillListing) -> dict[str, Any]:
    return {
        "id": str(row.id),
        "skill_id": row.skill_id,
        "seller_id": str(row.seller_id),
        "title": row.title,
        "description": row.description,
        "price_cents": row.price_cents,
        "currency": row.currency,
        "license_type": row.license_type,
        "status": row.status,
        "is_active": row.is_active,
    }


@router.get("/listings")
async def list_listings(
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
) -> dict[str, Any]:
    rows = (
        db.query(SkillListing)
        .filter(SkillListing.status == "approved", SkillListing.is_active.is_(True))
        .order_by(SkillListing.created_at.desc())
        .limit(100)
        .all()
    )
    return {"total": len(rows), "items": [_serialize(r) for r in rows]}


@router.post("/listings", status_code=201)
async def create_listing(
    body: CreateListingRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    require_tier(user, "creator", code="tier_required_creator")
    if body.price_cents > 0 and body.license_type == "commercial":
        pass  # creator tier includes commercial_license
    listing = SkillListing(
        id=uuid.uuid4(),
        skill_id=body.skill_id,
        seller_id=user.id,
        title=body.title,
        description=body.description,
        price_cents=body.price_cents,
        currency=body.currency,
        license_type=body.license_type,
        status="pending",
        is_active=True,
    )
    db.add(listing)
    db.commit()
    db.refresh(listing)
    return _serialize(listing)


@router.get("/listings/mine")
async def my_listings(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    rows = (
        db.query(SkillListing)
        .filter(SkillListing.seller_id == user.id)
        .order_by(SkillListing.created_at.desc())
        .all()
    )
    return {"total": len(rows), "items": [_serialize(r) for r in rows]}


class BatchDatasetImportRequest(BaseModel):
    paths: list[str] = Field(min_length=1, max_length=20)


class BatchTrainingRequest(BaseModel):
    jobs: list[dict[str, Any]] = Field(min_length=1, max_length=10)


@router.post("/batch/datasets")
async def batch_import_datasets(
    body: BatchDatasetImportRequest,
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    require_tier(user, "creator", code="tier_required_creator")
    return {
        "accepted": len(body.paths),
        "status": "queued",
        "message": "Batch dataset import queued (stub — wire to dataset_service)",
    }


@router.post("/batch/trainings")
async def batch_submit_trainings(
    body: BatchTrainingRequest,
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    require_tier(user, "creator", code="tier_required_creator")
    return {
        "accepted": len(body.jobs),
        "status": "queued",
        "message": "Batch training submit queued (stub — wire to trainings.create)",
    }
