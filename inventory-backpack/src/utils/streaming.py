"""
Streaming processing - optimize FPS and latency
"""

import asyncio
import logging
from typing import AsyncIterator, Callable, Optional

import aiohttp

logger = logging.getLogger(__name__)


class TokenBuffer:
    """
    Token buffer - optimize streaming output FPS
    
    Strategy:
    - Small buffer with fast flush (low latency)
    - Large buffer with batch output (high throughput)
    """
    
    def __init__(
        self,
        flush_interval: float = 0.05,  # 50ms flush
        max_buffer_size: int = 16,      # Maximum token count
    ):
        self.flush_interval = flush_interval
        self.max_buffer_size = max_buffer_size
        self._buffer: list[str] = []
        self._last_flush = 0.0
    
    def add(self, token: str) -> Optional[str]:
        """
        Add a token, may trigger flush
        
        Returns:
            Content to output, or None
        """
        self._buffer.append(token)
        
        # Check whether to flush
        now = asyncio.get_event_loop().time()
        should_flush = (
            len(self._buffer) >= self.max_buffer_size or
            (now - self._last_flush) >= self.flush_interval
        )
        
        if should_flush:
            return self.flush()
        
        return None
    
    def flush(self) -> str:
        """Force flush the buffer"""
        if not self._buffer:
            return ""
        
        result = "".join(self._buffer)
        self._buffer.clear()
        self._last_flush = asyncio.get_event_loop().time()
        
        return result


async def stream_with_fps_control(
    response: aiohttp.ClientResponse,
    *,
    target_fps: float = 60.0,  # Target FPS
    min_chunk: int = 4,        # Minimum token count
) -> AsyncIterator[str]:
    """
    Stream read - FPS control
    
    Args:
        response: aiohttp response
        target_fps: target refresh rate
        min_chunk: minimum output token count
    
    Yields:
        Controlled output chunks
    """
    interval = 1.0 / target_fps
    buffer = TokenBuffer(flush_interval=interval)
    
    async for line in response.content:
        if not line:
            continue
        
        # SSE format parsing
        line = line.decode('utf-8').strip()
        if not line.startswith("data: "):
            continue
        
        data = line[6:]  # Strip "data: "
        
        if data == "[DONE]":
            # Flush remaining
            remaining = buffer.flush()
            if remaining:
                yield remaining
            break
        
        # Parse JSON content
        try:
            import json
            chunk = json.loads(data)
            content = chunk.get("choices", [{}])[0].get("delta", {}).get("content", "")
            
            if content:
                result = buffer.add(content)
                if result:
                    yield result
                    
        except (json.JSONDecodeError, IndexError):
            continue
    
    # Final flush
    final = buffer.flush()
    if final:
        yield final
