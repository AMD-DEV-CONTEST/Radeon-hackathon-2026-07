"""
LaunchKart AI 2.0 — Launch Service

Business logic for product launch orchestration.
Delegates to the AgentOrchestrator for AI execution.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import AsyncGenerator
from uuid import UUID

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.launches import LaunchListResponse, LaunchResponse
from app.exceptions import (
    LaunchAlreadyRunningError,
    LaunchNotRetryableError,
    NotFoundError,
)
from app.infrastructure.database.models.launch_model import LaunchModel
from app.infrastructure.database.models.product_model import ProductModel

logger = structlog.get_logger(__name__)


class LaunchService:
    """Orchestrates the product launch lifecycle."""

    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    async def create_launch(
        self,
        product_id: UUID,
        user_id: UUID,
        target_marketplaces: list[str],
        preferences: dict | None,
    ) -> LaunchResponse:
        """Create a new launch and trigger agent execution."""
        # Verify product exists and belongs to user
        result = await self._db.execute(
            select(ProductModel).where(
                ProductModel.id == product_id,
                ProductModel.user_id == user_id,
            )
        )
        product = result.scalar_one_or_none()
        if not product:
            raise NotFoundError("Product", str(product_id))

        # In demo/local mode, if an active launch exists, cleanly cancel it so the user can re-launch freely without 409 errors
        active_res = await self._db.execute(
            select(LaunchModel).where(
                LaunchModel.product_id == product_id,
                LaunchModel.status.in_(["pending", "planning", "executing"]),
            )
        )
        for existing in active_res.scalars().all():
            existing.status = "cancelled"
        await self._db.flush()

        # Create launch record
        launch = LaunchModel(
            product_id=product_id,
            user_id=user_id,
            status="pending",
            total_steps=14,  # One per agent
            marketplace_listings={
                "target_marketplaces": target_marketplaces,
            },
        )
        self._db.add(launch)
        await self._db.flush()

        # Start agent orchestration in background
        asyncio.create_task(self._run_launch(launch.id, product.id, product.image_path, target_marketplaces, preferences))

        logger.info("Launch created", launch_id=str(launch.id), product_id=str(product_id))

        return LaunchResponse.model_validate(launch)

    async def list_launches(self, user_id: UUID) -> LaunchListResponse:
        """List all launches for a user."""
        result = await self._db.execute(
            select(LaunchModel)
            .where(LaunchModel.user_id == user_id)
            .order_by(LaunchModel.created_at.desc())
        )
        launches = result.scalars().all()
        return LaunchListResponse(
            launches=[LaunchResponse.model_validate(l) for l in launches],
            total=len(launches),
        )

    async def get_launch(self, launch_id: UUID, user_id: UUID) -> LaunchResponse:
        """Get launch details including all agent results."""
        result = await self._db.execute(
            select(LaunchModel).where(
                LaunchModel.id == launch_id,
                LaunchModel.user_id == user_id,
            )
        )
        launch = result.scalar_one_or_none()
        if not launch:
            raise NotFoundError("Launch", str(launch_id))

        return LaunchResponse.model_validate(launch)

    async def stream_launch_progress(
        self, launch_id: UUID, user_id: UUID
    ) -> AsyncGenerator[str, None]:
        """Stream launch progress via SSE."""
        # Verify access
        result = await self._db.execute(
            select(LaunchModel).where(
                LaunchModel.id == launch_id,
                LaunchModel.user_id == user_id,
            )
        )
        launch = result.scalar_one_or_none()
        if not launch:
            raise NotFoundError("Launch", str(launch_id))

        while True:
            # Re-fetch launch state
            await self._db.refresh(launch)

            yield f"data: {{'status': '{launch.status}', 'progress': {launch.progress_percent}, 'completed_steps': {launch.completed_steps}, 'total_steps': {launch.total_steps}}}\n\n"

            if launch.status in ("completed", "failed"):
                yield f"data: {{'status': '{launch.status}', 'final': true}}\n\n"
                break

            await asyncio.sleep(1)

    async def retry_launch(self, launch_id: UUID, user_id: UUID) -> LaunchResponse:
        """Retry a failed launch."""
        result = await self._db.execute(
            select(LaunchModel).where(
                LaunchModel.id == launch_id,
                LaunchModel.user_id == user_id,
            )
        )
        launch = result.scalar_one_or_none()
        if not launch:
            raise NotFoundError("Launch", str(launch_id))

        if launch.status != "failed":
            raise LaunchNotRetryableError(str(launch_id), launch.status)

        launch.status = "pending"
        launch.progress_percent = 0.0
        launch.completed_steps = 0
        await self._db.flush()

        # Restart orchestration
        product = await self._db.get(ProductModel, launch.product_id)
        if product:
            target_marketplaces = (launch.marketplace_listings or {}).get("target_marketplaces", ["amazon"])
            asyncio.create_task(self._run_launch(launch.id, product.id, product.image_path, target_marketplaces, None))

        return LaunchResponse.model_validate(launch)

    async def delete_launch(self, launch_id: UUID, user_id: UUID) -> None:
        """Delete or cancel a launch."""
        result = await self._db.execute(
            select(LaunchModel).where(
                LaunchModel.id == launch_id,
                LaunchModel.user_id == user_id,
            )
        )
        launch = result.scalar_one_or_none()
        if not launch:
            raise NotFoundError("Launch", str(launch_id))

        await self._db.delete(launch)

    async def _run_launch(
        self,
        launch_id: UUID,
        product_id: UUID,
        image_path: str,
        target_marketplaces: list[str],
        preferences: dict | None,
    ) -> None:
        """Background task that runs the agent orchestration pipeline."""
        logger.info("Starting launch execution", launch_id=str(launch_id))
        
        from app.services.agent_orchestrator import AgentOrchestrator
        from app.infrastructure.callbacks.websocket_callback import DashboardWebSocketCallbackHandler
        from app.infrastructure.database.session import async_session_factory
        
        # Use a dedicated session for the background task (request session is already closed)
        async with async_session_factory() as db:
            try:
                # 1. Update Launch status
                result = await db.execute(select(LaunchModel).where(LaunchModel.id == launch_id))
                launch = result.scalar_one_or_none()
                if launch:
                    launch.status = "executing"
                    await db.commit()
                    
                # 2. Build Initial State
                initial_state = {
                    "launch_id": str(launch_id),
                    "product_id": str(product_id),
                    "product_image_path": image_path,
                    "target_marketplaces": target_marketplaces,
                    "preferences": preferences,
                }
                
                # 3. Initialize orchestrator, services, and callbacks
                orchestrator = AgentOrchestrator()
                graph = orchestrator.build_graph()
                
                from app.services.gpu_monitor_service import GPUMonitorService
                gpu_service = GPUMonitorService()
                
                # Start the GPU Telemetry stream
                import asyncio
                telemetry_task = asyncio.create_task(gpu_service.stream_metrics(str(launch_id)))

                # Optionally add the callback handler for LLM internal streams
                callbacks = [DashboardWebSocketCallbackHandler(launch_id)]
                
                # 4. Execute the pipeline
                try:
                    final_state = await graph.ainvoke(initial_state, config={"callbacks": callbacks})
                    
                    # 5. Save results and mark complete
                    result = await db.execute(select(LaunchModel).where(LaunchModel.id == launch_id))
                    launch = result.scalar_one_or_none()
                    if launch:
                        launch.status = "completed"
                        launch.progress_percent = 100
                        launch.completed_steps = launch.total_steps
                        await db.commit()
                        
                    logger.info("Launch completed successfully", launch_id=str(launch_id))
                    
                except Exception as e:
                    logger.error("Launch failed during execution", error=str(e), launch_id=str(launch_id))
                    result = await db.execute(select(LaunchModel).where(LaunchModel.id == launch_id))
                    launch = result.scalar_one_or_none()
                    if launch:
                        launch.status = "failed"
                        await db.commit()
                finally:
                    # Stop the telemetry stream gracefully
                    telemetry_task.cancel()
                    try:
                        await telemetry_task
                    except asyncio.CancelledError:
                        pass
            except Exception as e:
                logger.error("Background launch task failed", error=str(e), launch_id=str(launch_id))

