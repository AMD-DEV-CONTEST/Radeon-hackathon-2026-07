"""
LaunchKart AI 2.0 — Launches API Routes

Endpoints for creating, monitoring, and managing product launches.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from typing import Any

from app.dependencies import DbSessionDep, SellerOrAdminDep, UserIdDep

router = APIRouter()


# ---- Request / Response Schemas ----


class CreateLaunchRequest(BaseModel):
    product_id: UUID
    target_marketplaces: list[str] = Field(
        default=["amazon", "shopify"],
        description="Target marketplaces for listing generation",
    )
    preferences: dict | None = Field(
        default=None, description="Custom preferences for this launch"
    )


class LaunchResponse(BaseModel):
    id: UUID
    product_id: UUID
    user_id: UUID
    status: str
    execution_plan: dict | None = None
    agent_results: dict | None = None
    seo_data: dict | None = None
    pricing_data: dict | None = None
    marketing_content: dict | None = None
    marketplace_listings: dict | None = None
    progress_percent: float
    total_steps: int
    completed_steps: int
    started_at: str | None = None
    completed_at: str | None = None
    created_at: Any = None
    updated_at: Any = None

    model_config = {"from_attributes": True}


class LaunchListResponse(BaseModel):
    launches: list[LaunchResponse]
    total: int


# ---- Endpoints ----


@router.post("", response_model=LaunchResponse, status_code=201)
async def create_launch(
    request: CreateLaunchRequest,
    _auth: SellerOrAdminDep,
    user_id: UserIdDep,
    db: DbSessionDep,
) -> LaunchResponse:
    """Create and start a new product launch."""
    from app.services.launch_service import LaunchService

    service = LaunchService(db)
    return await service.create_launch(
        product_id=request.product_id,
        user_id=user_id,
        target_marketplaces=request.target_marketplaces,
        preferences=request.preferences,
    )


@router.get("", response_model=LaunchListResponse)
async def list_launches(
    _auth: SellerOrAdminDep,
    user_id: UserIdDep,
    db: DbSessionDep,
) -> LaunchListResponse:
    """List all launches for the current user."""
    from app.services.launch_service import LaunchService

    service = LaunchService(db)
    return await service.list_launches(user_id=user_id)


@router.get("/{launch_id}", response_model=LaunchResponse)
async def get_launch(
    launch_id: UUID,
    _auth: SellerOrAdminDep,
    user_id: UserIdDep,
    db: DbSessionDep,
) -> LaunchResponse:
    """Get detailed launch results."""
    from app.services.launch_service import LaunchService

    service = LaunchService(db)
    return await service.get_launch(launch_id=launch_id, user_id=user_id)


@router.get("/{launch_id}/stream")
async def stream_launch(
    launch_id: UUID,
    _auth: SellerOrAdminDep,
    user_id: UserIdDep,
    db: DbSessionDep,
) -> StreamingResponse:
    """Stream launch progress via Server-Sent Events."""
    from app.services.launch_service import LaunchService

    service = LaunchService(db)
    event_generator = service.stream_launch_progress(
        launch_id=launch_id, user_id=user_id
    )
    return StreamingResponse(
        event_generator,
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.post("/{launch_id}/retry", response_model=LaunchResponse)
async def retry_launch(
    launch_id: UUID,
    _auth: SellerOrAdminDep,
    user_id: UserIdDep,
    db: DbSessionDep,
) -> LaunchResponse:
    """Retry a failed launch."""
    from app.services.launch_service import LaunchService

    service = LaunchService(db)
    return await service.retry_launch(launch_id=launch_id, user_id=user_id)


@router.delete("/{launch_id}", status_code=204)
async def delete_launch(
    launch_id: UUID,
    _auth: SellerOrAdminDep,
    user_id: UserIdDep,
    db: DbSessionDep,
) -> None:
    """Cancel or delete a launch."""
    from app.services.launch_service import LaunchService

    service = LaunchService(db)
    await service.delete_launch(launch_id=launch_id, user_id=user_id)
