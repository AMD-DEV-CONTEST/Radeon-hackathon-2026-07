"""
Async database engine and session management.

A single engine is created at import time (pooled, reused across requests).
`get_db` is a FastAPI dependency that yields a session and guarantees it is
closed (and rolled back on error) at the end of every request — no connection
leaks, no straddling transactions across requests.
"""
from typing import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from app.core.config import get_settings

settings = get_settings()

_is_sqlite = settings.DATABASE_URL.startswith("sqlite")

# SQLite (used only in the test suite, see tests/conftest.py) doesn't support
# pool_size/max_overflow — Postgres (production) does and benefits from them.
_engine_kwargs: dict = {"pool_pre_ping": True, "echo": False}
if not _is_sqlite:
    _engine_kwargs["pool_size"] = settings.DB_POOL_SIZE
    _engine_kwargs["max_overflow"] = settings.DB_MAX_OVERFLOW

engine: AsyncEngine = create_async_engine(settings.DATABASE_URL, **_engine_kwargs)

AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False,
)


class Base(DeclarativeBase):
    """Declarative base for all ORM models (see app/db/models/)."""
    pass


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()
