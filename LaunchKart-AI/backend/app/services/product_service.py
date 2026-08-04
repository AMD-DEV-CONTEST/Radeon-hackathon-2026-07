"""
LaunchKart AI 2.0 — Product Service

Business logic for product management and image processing.
"""

from __future__ import annotations

import uuid
from pathlib import Path
from uuid import UUID

import aiofiles
from fastapi import UploadFile
from PIL import Image
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.products import ProductListResponse, ProductResponse
from app.config import get_settings
from app.exceptions import (
    FileTooLargeError,
    NotFoundError,
    UnsupportedFileTypeError,
)
from app.infrastructure.database.models.product_model import ProductModel


class ProductService:
    """Handles product CRUD operations and image upload processing."""

    def __init__(self, db: AsyncSession) -> None:
        self._db = db
        self._settings = get_settings()

    async def create_product(self, user_id: UUID, image: UploadFile) -> ProductResponse:
        """Upload and create a new product from an image."""
        # Validate file type
        if image.content_type not in self._settings.allowed_image_types_list:
            raise UnsupportedFileTypeError(
                file_type=image.content_type or "unknown",
                allowed_types=self._settings.allowed_image_types_list,
            )

        # Read and validate file size
        content = await image.read()
        if len(content) > self._settings.max_upload_size_bytes:
            raise FileTooLargeError(self._settings.max_upload_size_mb)

        # Generate unique filename
        file_ext = Path(image.filename or "upload.jpg").suffix.lower()
        file_id = str(uuid.uuid4())
        filename = f"{file_id}{file_ext}"
        filepath = self._settings.upload_path / filename

        # Save original image
        async with aiofiles.open(filepath, "wb") as f:
            await f.write(content)

        # Generate thumbnail
        thumbnail_filename = f"{file_id}_thumb.webp"
        thumbnail_path = self._settings.upload_path / thumbnail_filename
        self._create_thumbnail(filepath, thumbnail_path)

        # Create database record
        product = ProductModel(
            user_id=user_id,
            image_path=str(filepath),
            thumbnail_path=str(thumbnail_path),
            status="draft",
        )
        self._db.add(product)
        await self._db.flush()

        return ProductResponse.model_validate(product)

    async def list_products(self, user_id: UUID) -> ProductListResponse:
        """List all products for a user."""
        result = await self._db.execute(
            select(ProductModel)
            .where(ProductModel.user_id == user_id)
            .order_by(ProductModel.created_at.desc())
        )
        products = result.scalars().all()
        return ProductListResponse(
            products=[ProductResponse.model_validate(p) for p in products],
            total=len(products),
        )

    async def get_product(self, product_id: UUID, user_id: UUID) -> ProductResponse:
        """Get a single product by ID."""
        result = await self._db.execute(
            select(ProductModel).where(
                ProductModel.id == product_id,
                ProductModel.user_id == user_id,
            )
        )
        product = result.scalar_one_or_none()
        if not product:
            raise NotFoundError("Product", str(product_id))

        return ProductResponse.model_validate(product)

    async def delete_product(self, product_id: UUID, user_id: UUID) -> None:
        """Delete a product and its associated files."""
        result = await self._db.execute(
            select(ProductModel).where(
                ProductModel.id == product_id,
                ProductModel.user_id == user_id,
            )
        )
        product = result.scalar_one_or_none()
        if not product:
            raise NotFoundError("Product", str(product_id))

        # Clean up files
        for path_str in [product.image_path, product.thumbnail_path]:
            if path_str:
                path = Path(path_str)
                if path.exists():
                    path.unlink()

        await self._db.delete(product)

    @staticmethod
    def _create_thumbnail(source_path: Path, dest_path: Path, size: tuple[int, int] = (300, 300)) -> None:
        """Create a WebP thumbnail from the source image."""
        try:
            with Image.open(source_path) as img:
                img.thumbnail(size, Image.Resampling.LANCZOS)
                img.save(dest_path, "WEBP", quality=85)
        except Exception:
            # If thumbnail creation fails, copy original
            import shutil
            shutil.copy2(source_path, dest_path)
