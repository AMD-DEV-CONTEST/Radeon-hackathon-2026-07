"""
LaunchKart AI 2.0 — Async Database Session Management

Provides the async SQLAlchemy engine, session factory, and request-scoped
session dependency for FastAPI.
"""

from __future__ import annotations

from typing import AsyncGenerator

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.config import get_settings

settings = get_settings()

engine_kwargs = {
    "echo": settings.is_development,
}
if not settings.database_url.startswith("sqlite"):
    engine_kwargs.update({
        "pool_size": settings.database_pool_size,
        "max_overflow": settings.database_max_overflow,
        "pool_pre_ping": True,
        "pool_recycle": 3600,
    })

engine = create_async_engine(settings.database_url, **engine_kwargs)

async_session_factory = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autocommit=False,
    autoflush=False,
)


async def init_db() -> None:
    """Initialize the database, create tables, and seed initial demo data if empty."""
    import uuid
    from sqlalchemy import select
    from app.infrastructure.database.base import Base
    from app.infrastructure.database.models.user_model import UserModel
    from app.infrastructure.database.models.product_model import ProductModel

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    # Seed demo user and product for Docker-less real data testing
    async with async_session_factory() as session:
        demo_user_id = uuid.UUID("123e4567-e89b-12d3-a456-426614174000")
        res = await session.execute(select(UserModel).where(UserModel.id == demo_user_id))
        if not res.scalar_one_or_none():
            user = UserModel(
                id=demo_user_id,
                email="demo@launchkart.ai",
                hashed_password="mock_hashed_password_for_local",
                full_name="Demo Admin",
                role="admin",
            )
            product = ProductModel(
                id=demo_user_id,  # using same UUID as mockProductId for convenience
                user_id=demo_user_id,
                name="AMD Radeon RX 7900 XTX 24GB",
                category="Graphics Cards",
                brand="AMD",
                image_path="./uploads/demo_gpu.jpg",
                status="ready",
            )
            session.add_all([user, product])
            await session.commit()

        # Seed demo memory if empty
        from app.infrastructure.database.models.memory_entry_model import MemoryEntryModel
        from app.services.memory_service import MemoryService
        mem_res = await session.execute(select(MemoryEntryModel).limit(1))
        if not mem_res.scalar_one_or_none():
            mem_service = MemoryService(session)
            await mem_service._seed_demo_memories(demo_user_id)

        # Seed demo GPU benchmarks if empty
        from app.infrastructure.database.models.gpu_benchmark_model import GPUBenchmarkModel
        bench_res = await session.execute(select(GPUBenchmarkModel).limit(1))
        if not bench_res.scalar_one_or_none():
            b1 = GPUBenchmarkModel(
                id=uuid.uuid4(),
                gpu_name="AMD Radeon RX 7900 XTX 24GB",
                rocm_version="6.1.2",
                vram_total_gb=24.0,
                vram_used_gb=13.8,
                gpu_utilization_percent=89.0,
                inference_latency_ms=132.0,
                tokens_per_second=74.2,
                model_benchmarks=[{"model_name": "llama3.1:8b (ROCm Accelerated)", "tokens_per_second": 74.2, "inference_latency_ms": 132.0, "vram_usage_gb": 13.8, "prompt_eval_rate": 320.0, "eval_rate": 74.2}]
            )
            b2 = GPUBenchmarkModel(
                id=uuid.uuid4(),
                gpu_name="AMD Radeon RX 7900 XTX 24GB",
                rocm_version="6.1.2",
                vram_total_gb=24.0,
                vram_used_gb=14.0,
                gpu_utilization_percent=91.5,
                inference_latency_ms=129.0,
                tokens_per_second=76.8,
                model_benchmarks=[{"model_name": "llama3.1:8b (ROCm Accelerated)", "tokens_per_second": 76.8, "inference_latency_ms": 129.0, "vram_usage_gb": 14.0, "prompt_eval_rate": 335.0, "eval_rate": 76.8}]
            )
            session.add_all([b1, b2])
            await session.commit()


async def get_db_session() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency that provides a request-scoped database session."""
    async with async_session_factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()
