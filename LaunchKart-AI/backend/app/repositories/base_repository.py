"""
LaunchKart AI 2.0 — Base Repository

Provides generic CRUD operations for SQLAlchemy models.
"""

from __future__ import annotations

from typing import Any, Generic, Sequence, TypeVar
from uuid import UUID

from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.database.base import Base

ModelType = TypeVar("ModelType", bound=Base)


class BaseRepository(Generic[ModelType]):
    """Generic repository providing basic CRUD operations."""

    def __init__(self, model: type[ModelType], db: AsyncSession):
        self.model = model
        self.db = db

    async def get_by_id(self, id: UUID) -> ModelType | None:
        """Get a single record by its UUID."""
        result = await self.db.execute(select(self.model).where(self.model.id == id))
        return result.scalar_one_or_none()

    async def get_all(self, skip: int = 0, limit: int = 100) -> Sequence[ModelType]:
        """Get a list of records with pagination."""
        result = await self.db.execute(select(self.model).offset(skip).limit(limit))
        return result.scalars().all()

    async def create(self, **kwargs: Any) -> ModelType:
        """Create a new record."""
        db_obj = self.model(**kwargs)
        self.db.add(db_obj)
        await self.db.flush()
        return db_obj

    async def update(self, id: UUID, **kwargs: Any) -> ModelType | None:
        """Update an existing record."""
        await self.db.execute(
            update(self.model)
            .where(self.model.id == id)
            .values(**kwargs)
        )
        return await self.get_by_id(id)

    async def delete(self, id: UUID) -> bool:
        """Delete a record by its UUID."""
        result = await self.db.execute(delete(self.model).where(self.model.id == id))
        return result.rowcount > 0
