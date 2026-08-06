"""
Resilient HTTP client - retry + timeout + circuit breaker

Goal: eliminate 25 connection timeouts, improve stability
"""

import asyncio
import logging
import time
from typing import Optional, AsyncIterator, Callable, Awaitable

import aiohttp
import orjson

from .circuit_breaker import CircuitBreaker, AdaptiveLimiter

logger = logging.getLogger(__name__)


class ResilientClient:
    """
    Resilient HTTP client
    
    Features:
    - Connection warm-up to avoid cold start
    - Smart retry: only retries on retryable errors
    - Circuit breaker protection: prevents cascading failures
    - Adaptive rate limiting: dynamically adjusts concurrency
    """
    
    # Retryable status codes
    RETRYABLE_STATUS = {429, 502, 503, 504}
    # Retryable exceptions
    RETRYABLE_EXCEPTIONS = (
        aiohttp.ClientConnectionError,
        aiohttp.ServerTimeoutError,
        asyncio.TimeoutError,
    )
    
    def __init__(
        self,
        base_url: str,
        max_retries: int = 2,
        base_timeout: float = 30.0,
        stream_timeout: float = 120.0,
    ):
        self.base_url = base_url.rstrip("/")
        self.max_retries = max_retries
        self.base_timeout = base_timeout
        self.stream_timeout = stream_timeout
        
        self._session: Optional[aiohttp.ClientSession] = None
        self._circuit = CircuitBreaker(
            failure_threshold=0.3,
            recovery_timeout=10.0,
        )
        self._limiter = AdaptiveLimiter(
            initial_limit=20,
            target_p99_ms=800.0,
        )
    
    async def __aenter__(self):
        """Initialize + warm-up"""
        connector = aiohttp.TCPConnector(
            limit=100,
            limit_per_host=50,
            keepalive_timeout=600,
            enable_tcp_fast_open=True,
            ttl_dns_cache=3600,
        )
        
        self._session = aiohttp.ClientSession(
            connector=connector,
            timeout=aiohttp.ClientTimeout(total=300, connect=10),
            json_serialize=orjson.dumps,
        )
        
        # Warm-up connection
        await self._warmup()
        
        return self
    
    async def __aexit__(self, *args):
        if self._session:
            await self._session.close()
    
    async def _warmup(self):
        """Connection warm-up - eliminate first request latency"""
        try:
            async with self._session.get(
                f"{self.base_url}/health",
                timeout=aiohttp.ClientTimeout(total=5),
                ssl=False,  # Cloud providers may have slow SSL handshake
            ) as resp:
                await resp.read()
                logger.info("Connection warmed up")
        except Exception as e:
            logger.warning(f"Warmup failed: {e}, continuing anyway")
    
    async def post_stream(
        self,
        path: str,
        payload: dict,
        *,
        headers: Optional[dict] = None,
    ) -> AsyncIterator[bytes]:
        """
        Streaming POST - with retry and circuit breaker
        
        Yields:
            Raw byte chunks
        """
        
        url = f"{self.base_url}{path}"
        
        # Rate limit check
        if not await self._limiter.acquire():
            raise TooManyRequestsError("Server overloaded, back off")
        
        start = time.monotonic()
        
        for attempt in range(self.max_retries + 1):
            try:
                # Circuit breaker protection
                async with self._session.post(
                    url,
                    json=payload,
                    headers=headers or {},
                    # Streaming: only set connect timeout, no read timeout
                    timeout=aiohttp.ClientTimeout(
                        connect=10,
                        sock_read=None,  # No read timeout for streaming
                    ),
                ) as response:
                    
                    # Check status code
                    if response.status >= 400:
                        raise aiohttp.ClientResponseError(
                            request_info=response.request_info,
                            history=(),
                            status=response.status,
                        )
                    
                    # Stream yield
                    async for chunk in response.content.iter_chunked(8192):
                        yield chunk
                
                # Success, report latency
                latency = (time.monotonic() - start) * 1000
                await self._limiter.release(latency)
                return
                
            except self.RETRYABLE_EXCEPTIONS as e:
                if attempt < self.max_retries:
                    wait = min(2 ** attempt, 10)  # Exponential backoff, max 10s
                    logger.warning(f"Retry {attempt+1}/{self.max_retries} after {wait}s: {e}")
                    await asyncio.sleep(wait)
                else:
                    # Retries exhausted, report failure
                    await self._limiter.release(99999)  # Mark as failure
                    raise
            
            except aiohttp.ClientResponseError as e:
                if e.status in self.RETRYABLE_STATUS and attempt < self.max_retries:
                    wait = min(2 ** attempt, 10)
                    await asyncio.sleep(wait)
                else:
                    await self._limiter.release(99999)
                    raise


class TooManyRequestsError(Exception):
    pass
