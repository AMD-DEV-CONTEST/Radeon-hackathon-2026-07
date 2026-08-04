"""
LaunchKart AI 2.0 — Analytics API Routes

Endpoints for dashboard statistics and usage analytics.
"""

from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel

from app.dependencies import DbSessionDep, SellerOrAdminDep, UserIdDep

router = APIRouter()


# ---- Response Schemas ----


class DashboardStats(BaseModel):
    total_products: int
    total_launches: int
    completed_launches: int
    failed_launches: int
    active_launches: int
    total_marketplace_listings: int
    avg_launch_duration_seconds: float
    avg_confidence_score: float
    total_tokens_used: int
    gpu_hours_used: float


class LaunchAnalytics(BaseModel):
    launches_by_status: dict[str, int]
    launches_by_marketplace: dict[str, int]
    avg_agent_duration: dict[str, float]
    daily_launches: list[dict]
    top_categories: list[dict]


class GPUAnalytics(BaseModel):
    avg_utilization: float
    avg_tokens_per_second: float
    total_inference_time_hours: float
    model_usage: dict[str, int]
    daily_usage: list[dict]


# ---- Endpoints ----


@router.get("/dashboard", response_model=DashboardStats)
async def get_dashboard_stats(
    _auth: SellerOrAdminDep,
    user_id: UserIdDep,
    db: DbSessionDep,
) -> DashboardStats:
    """Get dashboard summary statistics."""
    from app.services.analytics_service import AnalyticsService

    service = AnalyticsService(db)
    return await service.get_dashboard_stats(user_id=user_id)


@router.get("/launches", response_model=LaunchAnalytics)
async def get_launch_analytics(
    _auth: SellerOrAdminDep,
    user_id: UserIdDep,
    db: DbSessionDep,
) -> LaunchAnalytics:
    """Get launch performance analytics."""
    from app.services.analytics_service import AnalyticsService

    service = AnalyticsService(db)
    return await service.get_launch_analytics(user_id=user_id)


@router.get("/gpu", response_model=GPUAnalytics)
async def get_gpu_analytics(
    _auth: SellerOrAdminDep,
    db: DbSessionDep,
) -> GPUAnalytics:
    """Get GPU usage analytics."""
    from app.services.analytics_service import AnalyticsService

    service = AnalyticsService(db)
    return await service.get_gpu_analytics()
