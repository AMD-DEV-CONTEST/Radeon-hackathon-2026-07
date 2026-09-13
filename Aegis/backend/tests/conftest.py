"""
Shared pytest fixtures.

Uses an in-memory SQLite DB (via aiosqlite) instead of Postgres for the test
suite so `pytest` runs with zero external infra — CI-friendly. pgvector-specific
features (vector similarity search) are consequently exercised in
test_memory.py against a stub, not real SQLite, and are called out as such;
everything else runs against a real ORM-backed database.
"""
import asyncio
from typing import AsyncGenerator

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import os
os.environ.setdefault("SECRET_KEY", "test-secret-key-for-pytest-only-not-prod")
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")

from app.db.session import Base, get_db  # noqa: E402
from app.main import create_app  # noqa: E402


@pytest_asyncio.fixture
async def db_session() -> AsyncGenerator[AsyncSession, None]:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        # NOTE: pgvector's Vector column type doesn't exist in SQLite; the
        # memory_records table is excluded from the test schema and covered
        # separately by unit tests against VectorStore's SQL construction.
        tables = [t for t in Base.metadata.sorted_tables if t.name != "memory_records"]
        for table in tables:
            await conn.run_sync(table.create, checkfirst=True)

    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with session_factory() as session:
        yield session
    await engine.dispose()


@pytest_asyncio.fixture
async def client(db_session: AsyncSession) -> AsyncGenerator[AsyncClient, None]:
    app = create_app()

    async def _override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = _override_get_db

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
