"""
Connection pool management - based on aiohttp, reuse existing dependencies
"""

import asyncio
import logging
from typing import Optional

import aiohttp
import aiohttp.connector

logger = logging.getLogger(__name__)


class AIOHTTPPool:
    """
    aiohttp connection pool - singleton with lazy initialization

    Features:
    - TCP connection reuse
    - DNS cache
    -  keep-alive optimization
    """

    _instance: Optional[aiohttp.ClientSession] = None
    _lock = asyncio.Lock()

    @classmethod
    async def get(cls) -> aiohttp.ClientSession:
        if cls._instance is not None and not cls._instance.closed:
            return cls._instance

        async with cls._lock:
            if cls._instance is not None and not cls._instance.closed:
                return cls._instance

            connector = aiohttp.TCPConnector(
                limit=100,                    # Total connections
                limit_per_host=20,            # Connections per host
                keepalive_timeout=300,        # 5-minute keepalive
                enable_cleanup_closed=True,   # Clean up closed connections
                force_close=False,            # Reuse connections
                ttl_dns_cache=300,            # DNS cache for 5 minutes
                use_dns_cache=True,
            )

            timeout = aiohttp.ClientTimeout(
                total=120,        # Total timeout
                connect=10,       # Connection timeout
                sock_read=90,     # Read timeout
            )

            cls._instance = aiohttp.ClientSession(
                connector=connector,
                timeout=timeout,
                raise_for_status=True,  # Auto raise exception
                json_serialize=__import__('orjson').dumps,  # Use orjson for speed
            )

            logger.info("aiohttp pool initialized")

        return cls._instance

    @classmethod
    async def close(cls) -> None:
        if cls._instance and not cls._instance.closed:
            await cls._instance.close()
            cls._instance = None
            logger.info("aiohttp pool closed")


# httpx-compatible wrapper (if you need it)
class HTTPXCompatWrapper:
    """
    Compatibility layer: let existing httpx code gradually migrate to aiohttp
    """

    def __init__(self, session: aiohttp.ClientSession):
        self._session = session

    async def post(self, url: str, **kwargs) -> 'ResponseWrapper':
        """httpx-compatible interface"""
        data = kwargs.pop('json', None)
        headers = kwargs.pop('headers', {})

        async with self._session.post(url, json=data, headers=headers) as resp:
            return ResponseWrapper(resp)


class ResponseWrapper:
    """httpx.Response-compatible"""

    def __init__(self, aiohttp_resp):
        self._resp = aiohttp_resp
        self.status_code = aiohttp_resp.status

    async def json(self):
        return await self._resp.json()

    @property
    def text(self):
        return self._resp.text()
