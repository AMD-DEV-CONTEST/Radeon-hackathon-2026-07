from __future__ import annotations

from fastapi import APIRouter, Request
from pydantic import BaseModel

from app.llm.health import check_model_health


router = APIRouter(tags=["health"])


class ModelHealthResponse(BaseModel):
    reachable: bool
    detail: str
    status_code: int | None = None


class HealthResponse(BaseModel):
    status: str
    model: str
    model_service: ModelHealthResponse


@router.get("/health", response_model=HealthResponse)
async def health(request: Request) -> HealthResponse:
    model_health = await check_model_health(
        request.app.state.settings,
        transport=request.app.state.model_health_transport,
    )
    return HealthResponse(
        status="ok" if model_health.reachable else "degraded",
        model=request.app.state.settings.llm_model,
        model_service=ModelHealthResponse(
            reachable=model_health.reachable,
            detail=model_health.detail,
            status_code=model_health.status_code,
        ),
    )
