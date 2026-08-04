"""
LaunchKart AI 2.0 — Products API Routes

Endpoints for product image upload, listing, detail, and deletion.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, File, UploadFile
from pydantic import BaseModel
from typing import Any

from app.dependencies import DbSessionDep, SellerOrAdminDep, UserIdDep

router = APIRouter()


# ---- Response Schemas ----


class ProductResponse(BaseModel):
    id: UUID
    user_id: UUID
    name: str | None
    category: str | None
    brand: str | None
    attributes: dict | None
    vision_analysis: dict | None
    image_path: str
    thumbnail_path: str | None
    status: str
    created_at: Any = None
    updated_at: Any = None

    model_config = {"from_attributes": True}


class ProductListResponse(BaseModel):
    products: list[ProductResponse]
    total: int


# ---- Endpoints ----


@router.post("", response_model=ProductResponse, status_code=201)
async def upload_product(
    _auth: SellerOrAdminDep,
    user_id: UserIdDep,
    db: DbSessionDep,
    image: UploadFile = File(..., description="Product image (JPEG, PNG, WebP, BMP)"),
) -> ProductResponse:
    """Upload a product image for AI analysis."""
    from app.services.product_service import ProductService

    service = ProductService(db)
    return await service.create_product(user_id=user_id, image=image)


@router.get("", response_model=ProductListResponse)
async def list_products(
    _auth: SellerOrAdminDep,
    user_id: UserIdDep,
    db: DbSessionDep,
) -> ProductListResponse:
    """List all products for the current user."""
    from app.services.product_service import ProductService

    service = ProductService(db)
    return await service.list_products(user_id=user_id)


@router.get("/{product_id}", response_model=ProductResponse)
async def get_product(
    product_id: UUID,
    _auth: SellerOrAdminDep,
    user_id: UserIdDep,
    db: DbSessionDep,
) -> ProductResponse:
    """Get product details by ID."""
    from app.services.product_service import ProductService

    service = ProductService(db)
    return await service.get_product(product_id=product_id, user_id=user_id)


@router.delete("/{product_id}", status_code=204)
async def delete_product(
    product_id: UUID,
    _auth: SellerOrAdminDep,
    user_id: UserIdDep,
    db: DbSessionDep,
) -> None:
    """Delete a product and its associated data."""
    from app.services.product_service import ProductService

    service = ProductService(db)
    await service.delete_product(product_id=product_id, user_id=user_id)
