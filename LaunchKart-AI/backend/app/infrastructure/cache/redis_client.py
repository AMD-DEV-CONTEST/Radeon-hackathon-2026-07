"""
LaunchKart AI 2.0 — Redis Client

Provides async Redis connection for caching and pub/sub event bus.
"""

from __future__ import annotations

from typing import Any

import redis.asyncio as aioredis
import structlog

from app.config import get_settings

logger = structlog.get_logger(__name__)


class InMemoryRedis:
    """Lightweight in-memory fallback when Redis server is unreachable (no Docker)."""

    def __init__(self) -> None:
        self._store: dict[str, str] = {}
        self._channels: dict[str, list[Any]] = {}

    async def get(self, key: str) -> str | None:
        return self._store.get(key)

    async def set(self, key: str, value: str, ex: int | None = None) -> bool:
        self._store[key] = str(value)
        return True

    async def delete(self, *keys: str) -> int:
        count = 0
        for key in keys:
            if key in self._store:
                del self._store[key]
                count += 1
        return count

    async def publish(self, channel: str, message: str) -> int:
        # No-op or local callback distribution for pub/sub in memory
        return 0

    async def close(self) -> None:
        self._store.clear()
        self._channels.clear()

    async def ping(self) -> bool:
        return True


_redis_client: Any | None = None


async def get_redis_client() -> Any:
    """Get or create the singleton Redis client with in-memory fallback."""
    global _redis_client
    if _redis_client is None:
        settings = get_settings()
        try:
            client = aioredis.from_url(
                settings.redis_url,
                encoding="utf-8",
                decode_responses=True,
                socket_connect_timeout=1.0,
            )
            await client.ping()
            _redis_client = client
            logger.info("Redis client connected", url=settings.redis_url)
        except Exception as e:
            logger.warning("Redis server unreachable, falling back to InMemoryRedis (Docker-less mode)", error=str(e))
            _redis_client = InMemoryRedis()
    return _redis_client


async def cache_get(key: str) -> str | None:
    """Get a value from Redis cache."""
    client = await get_redis_client()
    return await client.get(key)


async def cache_set(key: str, value: str, ttl: int | None = None) -> None:
    """Set a value in Redis cache with optional TTL."""
    client = await get_redis_client()
    settings = get_settings()
    await client.set(key, value, ex=ttl or settings.redis_cache_ttl)


async def cache_delete(key: str) -> None:
    """Delete a key from Redis cache."""
    client = await get_redis_client()
    await client.delete(key)


async def publish_event(channel: str, message: str) -> None:
    """Publish an event to a Redis pub/sub channel."""
    client = await get_redis_client()
    await client.publish(channel, message)


async def close_redis() -> None:
    """Close the Redis connection."""
    global _redis_client
    if _redis_client:
        await _redis_client.close()
        _redis_client = None
