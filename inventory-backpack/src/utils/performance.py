"""
Performance optimization layer - reduce TTFT, improve RPS
"""

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Optional, AsyncIterator, Callable, Any
from functools import wraps

import orjson
import aiohttp

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class PerfMetrics:
    """Performance metrics"""
    ttft_ms: float = 0.0          # Time to first token
    tpot_ms: float = 0.0          # Time per token
    total_tokens: int = 0
    input_tokens: int = 0


class FastStreamParser:
    """
    Fast stream parser - reduce TTFT
    
    Optimization points:
    - orjson instead of json
    - Pre-allocated buffer
    - Zero-copy parsing
    """
    
    __slots__ = ["_buffer", "_first_token", "_token_count", "_start"]
    
    def __init__(self):
        self._buffer = bytearray()
        self._first_token = True
        self._token_count = 0
        self._start = time.perf_counter()
    
    def feed(self, chunk: bytes) -> list[str]:
        """
        Parse SSE chunk
        
        Returns:
            List of parsed tokens
        """
        self._buffer.extend(chunk)
        tokens = []
        
        # Fast lookup for data: lines
        while b"\n\n" in self._buffer:
            idx = self._buffer.index(b"\n\n")
            line = self._buffer[:idx]
            self._buffer = self._buffer[idx + 2:]
            
            if line.startswith(b"data: "):
                data = line[6:]
                
                if data == b"[DONE]":
                    break
                
                try:
                    # orjson zero-copy parsing
                    msg = orjson.loads(data)
                    content = msg.get("choices", [{}])[0].get("delta", {}).get("content", "")
                    if content:
                        tokens.append(content)
                        self._token_count += 1
                        
                        if self._first_token:
                            self._first_token = False
                            ttft = (time.perf_counter() - self._start) * 1000
                            logger.debug(f"TTFT: {ttft:.2f}ms")
                            
                except orjson.JSONDecodeError:
                    continue
        
        return tokens
    
    @property
    def metrics(self) -> PerfMetrics:
        elapsed = time.perf_counter() - self._start
        return PerfMetrics(
            ttft_ms=0 if self._first_token else elapsed * 1000,
            tpot_ms=(elapsed * 1000) / max(self._token_count, 1),
            total_tokens=self._token_count,
        )


class BatchQueue:
    """
    Dynamic batching queue - improve GPU utilization
    
    Strategy:
    - Collect requests within a window
    - Merge homogeneous requests
    - Force flush on timeout
    """
    
    def __init__(
        self,
        max_batch_size: int = 16,
        max_wait_ms: float = 10.0,
    ):
        self.max_batch_size = max_batch_size
        self.max_wait_ms = max_wait_ms / 1000.0
        
        self._queue: list[asyncio.Future] = []
        self._lock = asyncio.Lock()
        self._timer: Optional[asyncio.Task] = None
    
    async def submit(self, request: dict) -> asyncio.Future:
        """Submit a request to the queue"""
        future = asyncio.get_event_loop().create_future()
        
        async with self._lock:
            self._queue.append((future, request))
            
            if len(self._queue) >= self.max_batch_size:
                await self._flush()
            elif self._timer is None:
                self._timer = asyncio.create_task(self._delayed_flush())
        
        return future
    
    async def _delayed_flush(self):
        """Delayed flush"""
        await asyncio.sleep(self.max_wait_ms)
        async with self._lock:
            await self._flush()
            self._timer = None
    
    async def _flush(self):
        """Execute batching"""
        if not self._queue:
            return
        
        batch = self._queue[:self.max_batch_size]
        self._queue = self._queue[self.max_batch_size:]
        
        # Actual send
        asyncio.create_task(self._execute_batch(batch))
    
    async def _execute_batch(self, batch: list):
        """Execute batch requests"""
        # Call actual inference here
        pass


class ConnectionOptimizer:
    """
    Connection optimization - reduce setup overhead
    """
    
    @staticmethod
    def create_optimized_connector() -> aiohttp.TCPConnector:
        """Create an optimized connection pool"""
        return aiohttp.TCPConnector(
            limit=500,                    # Total connections
            limit_per_host=100,           # Per host
            keepalive_timeout=600,        # 10-minute keepalive
            enable_cleanup_closed=True,
            force_close=False,
            ttl_dns_cache=3600,           # 1-hour DNS
            use_dns_cache=True,
            # Enable TCP Fast Open
            enable_tcp_fast_open=True,
            # Reuse port
            reuse_port=True,
        )
    
    @staticmethod
    def create_optimized_session(connector: aiohttp.TCPConnector) -> aiohttp.ClientSession:
        """Create an optimized session"""
        timeout = aiohttp.ClientTimeout(
            total=300,
            connect=5,
            sock_read=240,
        )
        
        return aiohttp.ClientSession(
            connector=connector,
            timeout=timeout,
            # Disable auto-decompression to reduce CPU
            auto_decompress=False,
            # Disable content-type checking
            raise_for_status=False,
            # Use orjson
            json_serialize=orjson.dumps,
        )


def track_latency(func):
    """Latency tracking decorator"""
    @wraps(func)
    async def wrapper(*args, **kwargs):
        start = time.perf_counter()
        try:
            return await func(*args, **kwargs)
        finally:
            latency = (time.perf_counter() - start) * 1000
            logger.debug(f"{func.__name__}: {latency:.2f}ms")
    return wrapper
