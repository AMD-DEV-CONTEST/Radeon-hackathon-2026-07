"""
LaunchKart AI 2.0 — Memory API Routes

Endpoints for browsing, searching, and managing persistent AI memory.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Query
from pydantic import BaseModel
from typing import Any

from app.dependencies import DbSessionDep, SellerOrAdminDep, UserIdDep

router = APIRouter()


# ---- Response Schemas ----


class MemoryEntryResponse(BaseModel):
    id: UUID
    user_id: UUID
    memory_type: str
    namespace: str
    content: str
    metadata_json: dict | None
    relevance_score: float | None
    created_at: Any = None
    expires_at: Any = None

    model_config = {"from_attributes": True}


class MemoryListResponse(BaseModel):
    entries: list[MemoryEntryResponse]
    total: int


class MemorySearchResponse(BaseModel):
    results: list[MemoryEntryResponse]
    query: str
    total: int


# ---- Endpoints ----


@router.get("", response_model=MemoryListResponse)
async def list_memories(
    _auth: SellerOrAdminDep,
    user_id: UserIdDep,
    db: DbSessionDep,
    memory_type: str | None = Query(None, description="Filter by memory type"),
    namespace: str | None = Query(None, description="Filter by namespace"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
) -> MemoryListResponse:
    """List memory entries with optional filtering."""
    from app.services.memory_service import MemoryService

    service = MemoryService(db)
    return await service.list_memories(
        user_id=user_id,
        memory_type=memory_type,
        namespace=namespace,
        limit=limit,
        offset=offset,
    )


@router.get("/search", response_model=MemorySearchResponse)
async def search_memories(
    _auth: SellerOrAdminDep,
    user_id: UserIdDep,
    db: DbSessionDep,
    q: str = Query(..., min_length=1, description="Semantic search query"),
    limit: int = Query(10, ge=1, le=50),
) -> MemorySearchResponse:
    """Semantic search across memory entries using ChromaDB vectors."""
    from app.services.memory_service import MemoryService

    service = MemoryService(db)
    return await service.search_memories(user_id=user_id, query=q, limit=limit)


@router.delete("/{memory_id}", status_code=204)
async def delete_memory(
    memory_id: UUID,
    _auth: SellerOrAdminDep,
    user_id: UserIdDep,
    db: DbSessionDep,
) -> None:
    """Delete a specific memory entry."""
    from app.services.memory_service import MemoryService

    service = MemoryService(db)
    await service.delete_memory(memory_id=memory_id, user_id=user_id)
