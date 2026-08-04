"""
LaunchKart AI 2.0 — Marketplace API Routes

Endpoints for marketplace listing preview, management, and export.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter
from pydantic import BaseModel, Field
from typing import Any

from app.dependencies import DbSessionDep, SellerOrAdminDep

router = APIRouter()


# ---- Response Schemas ----


class MarketplaceListingResponse(BaseModel):
    id: UUID
    launch_id: UUID
    product_id: UUID
    marketplace: str
    title: str | None
    description: str | None
    bullet_points: dict | None
    keywords: dict | None
    pricing: dict | None
    images: dict | None
    compliance_check: dict | None
    export_format: str | None
    status: str
    created_at: Any = None
    updated_at: Any = None

    model_config = {"from_attributes": True}


class MarketplaceListingsResponse(BaseModel):
    listings: list[MarketplaceListingResponse]
    total: int
    product_image_url: str | None = None
    product_name: str | None = None
    vision_attributes: list[str] | None = None


class ExportRequest(BaseModel):
    marketplaces: list[str] = Field(
        default=["amazon"], description="Marketplaces to export"
    )
    format: str = Field(default="json", description="Export format (json, csv)")


class ExportResponse(BaseModel):
    exports: dict[str, str]
    message: str


# ---- Endpoints ----


@router.get("/{launch_id}/listings", response_model=MarketplaceListingsResponse)
async def get_listings(
    launch_id: UUID,
    _auth: SellerOrAdminDep,
    db: DbSessionDep,
) -> MarketplaceListingsResponse:
    """Get all marketplace listings for a launch."""
    from app.services.marketplace_service import MarketplaceService

    service = MarketplaceService(db)
    return await service.get_listings(launch_id=launch_id)


@router.get("/{launch_id}/preview/{marketplace}", response_model=MarketplaceListingResponse)
async def preview_listing(
    launch_id: UUID,
    marketplace: str,
    _auth: SellerOrAdminDep,
    db: DbSessionDep,
) -> MarketplaceListingResponse:
    """Preview a marketplace-specific listing."""
    from app.services.marketplace_service import MarketplaceService

    service = MarketplaceService(db)
    return await service.preview_listing(launch_id=launch_id, marketplace=marketplace)


@router.post("/{launch_id}/export", response_model=ExportResponse)
async def export_listings(
    launch_id: UUID,
    request: ExportRequest,
    _auth: SellerOrAdminDep,
    db: DbSessionDep,
) -> ExportResponse:
    """Export marketplace listings in specified format."""
    from app.services.marketplace_service import MarketplaceService

    service = MarketplaceService(db)
    return await service.export_listings(
        launch_id=launch_id,
        marketplaces=request.marketplaces,
        export_format=request.format,
    )
