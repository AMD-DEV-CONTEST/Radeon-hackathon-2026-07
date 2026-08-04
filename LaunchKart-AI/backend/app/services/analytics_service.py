"""
LaunchKart AI 2.0 — Analytics Service

Dashboard statistics and usage analytics.
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.analytics import DashboardStats, GPUAnalytics, LaunchAnalytics
from app.infrastructure.database.models.agent_task_model import AgentTaskModel
from app.infrastructure.database.models.gpu_benchmark_model import GPUBenchmarkModel
from app.infrastructure.database.models.launch_model import LaunchModel
from app.infrastructure.database.models.marketplace_listing_model import MarketplaceListingModel
from app.infrastructure.database.models.product_model import ProductModel


class AnalyticsService:
    """Computes analytics and dashboard statistics."""

    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    async def get_dashboard_stats(self, user_id: UUID) -> DashboardStats:
        """Compute dashboard summary statistics."""
        # Product count
        products_result = await self._db.execute(
            select(func.count(ProductModel.id)).where(ProductModel.user_id == user_id)
        )
        total_products = products_result.scalar() or 0

        # Launch stats
        launches_result = await self._db.execute(
            select(
                func.count(LaunchModel.id),
                func.count(LaunchModel.id).filter(LaunchModel.status == "completed"),
                func.count(LaunchModel.id).filter(LaunchModel.status == "failed"),
                func.count(LaunchModel.id).filter(LaunchModel.status.in_(["pending", "planning", "executing"])),
            ).where(LaunchModel.user_id == user_id)
        )
        row = launches_result.one()
        total_launches, completed, failed, active = row

        # Marketplace listings count
        listings_result = await self._db.execute(
            select(func.count(MarketplaceListingModel.id)).join(
                LaunchModel, LaunchModel.id == MarketplaceListingModel.launch_id
            ).where(LaunchModel.user_id == user_id)
        )
        total_listings = listings_result.scalar() or 0

        # Average launch duration
        avg_duration_result = await self._db.execute(
            select(func.avg(AgentTaskModel.duration_seconds)).join(
                LaunchModel, LaunchModel.id == AgentTaskModel.launch_id
            ).where(LaunchModel.user_id == user_id)
        )
        avg_duration = avg_duration_result.scalar() or 0.0

        # Average confidence
        avg_confidence_result = await self._db.execute(
            select(func.avg(AgentTaskModel.confidence_score)).join(
                LaunchModel, LaunchModel.id == AgentTaskModel.launch_id
            ).where(
                LaunchModel.user_id == user_id,
                AgentTaskModel.confidence_score.is_not(None),
            )
        )
        avg_confidence = avg_confidence_result.scalar() or 0.0

        # Total tokens
        tokens_result = await self._db.execute(
            select(func.sum(AgentTaskModel.tokens_used)).join(
                LaunchModel, LaunchModel.id == AgentTaskModel.launch_id
            ).where(LaunchModel.user_id == user_id)
        )
        total_tokens = int(tokens_result.scalar() or 0)

        return DashboardStats(
            total_products=total_products,
            total_launches=total_launches,
            completed_launches=completed,
            failed_launches=failed,
            active_launches=active,
            total_marketplace_listings=total_listings,
            avg_launch_duration_seconds=float(avg_duration),
            avg_confidence_score=float(avg_confidence),
            total_tokens_used=total_tokens,
            gpu_hours_used=0.0,  # Phase 7
        )

    async def get_launch_analytics(self, user_id: UUID) -> LaunchAnalytics:
        """Compute launch performance analytics."""
        return LaunchAnalytics(
            launches_by_status={},
            launches_by_marketplace={},
            avg_agent_duration={},
            daily_launches=[],
            top_categories=[],
        )

    async def get_gpu_analytics(self) -> GPUAnalytics:
        """Compute GPU usage analytics."""
        return GPUAnalytics(
            avg_utilization=0.0,
            avg_tokens_per_second=0.0,
            total_inference_time_hours=0.0,
            model_usage={},
            daily_usage=[],
        )
