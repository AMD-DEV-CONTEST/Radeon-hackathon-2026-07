"""Redis client stub for future caching / pub-sub / WS fan-out."""

from __future__ import annotations

from typing import Any

from core.config import settings
from core.logger import get_logger

logger = get_logger(__name__)


class RedisClient:
    """No-op Redis facade. Replace with real redis.asyncio later."""

    def __init__(self, url: str | None = None) -> None:
        self.url = url or getattr(settings, "redis_url", None)
        self.enabled = bool(getattr(settings, "redis_enabled", False))

    async def get(self, key: str) -> str | None:
        _ = key
        return None

    async def set(self, key: str, value: str, *, ex: int | None = None) -> bool:
        _ = (key, value, ex)
        return False

    async def publish(self, channel: str, message: str) -> int:
        _ = (channel, message)
        return 0

    async def close(self) -> None:
        return None


_redis_client: RedisClient | None = None


def get_redis_client() -> RedisClient:
    global _redis_client
    if _redis_client is None:
        _redis_client = RedisClient()
        if not _redis_client.enabled:
            logger.debug("Redis integration disabled (stub client active)")
    return _redis_client
