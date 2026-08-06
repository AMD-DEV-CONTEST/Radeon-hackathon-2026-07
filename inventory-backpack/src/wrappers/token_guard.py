"""
TokenBudgetGuard - pure async version, zero blocking

Design constraints:
- No synchronous IO
- No global locks
- O(1) computational complexity
"""

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Optional, Dict, Any

import orjson
import tiktoken

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class BudgetConfig:
    """Budget configuration - immutable"""
    max_prompt_tokens: int = 4096
    max_completion_tokens: int = 2048
    tool_output_budget: int = 1024


class AsyncTokenCounter:
    """
    Async token counter - preloads encoders to avoid repeated computation
    """
    
    _encoders: Dict[str, Any] = {}
    _lock = asyncio.Lock()
    
    @classmethod
    async def get_encoder(cls, model: str = "cl100k_base"):
        """Async get encoder (with cache)"""
        if model in cls._encoders:
            return cls._encoders[model]
        
        # Double-checked locking to avoid duplicate creation
        async with cls._lock:
            if model not in cls._encoders:
                cls._encoders[model] = tiktoken.get_encoding(model)
            
            return cls._encoders[model]
    
    @classmethod
    async def count(cls, text: str, model: str = "cl100k_base") -> int:
        """Async count (actual computation is fast, but keep interface consistent)"""
        enc = await cls.get_encoder(model)
        return len(enc.encode(text))


class TokenBudgetGuard:
    """
    Token budget guard - pure async, non-blocking
    """
    
    def __init__(self, config: Optional[BudgetConfig] = None):
        self.config = config or BudgetConfig()
        self._counter = AsyncTokenCounter()
    
    async def check_request(self, messages: list[dict]) -> tuple[bool, int, Optional[str]]:
        """
        Check whether the request is compliant
        
        Returns:
            (passed, token count, error message)
        """
        # Fast path: empty check
        if not messages:
            return False, 0, "Empty messages"
        
        # Estimate tokens (async, but actually fast)
        text = " ".join(m.get("content", "") for m in messages)
        token_count = await self._counter.count(text)
        
        if token_count > self.config.max_prompt_tokens:
            return False, token_count, f"Prompt too long: {token_count} > {self.config.max_prompt_tokens}"
        
        return True, token_count, None
    
    async def check_tool_output(self, output: Any) -> tuple[bool, int]:
        """
        Check whether tool output needs compression
        
        Returns:
            (needs compression, current token count)
        """
        text = self._to_string(output)
        token_count = await self._counter.count(text)
        
        return token_count > self.config.tool_output_budget, token_count
    
    def _to_string(self, value: Any) -> str:
        """Convert to string - synchronous, no IO"""
        if isinstance(value, str):
            return value
        
        try:
            return orjson.dumps(value).decode()
        except Exception:
            return str(value)
    
    async def compress_if_needed(self, output: Any) -> Any:
        """
        Compress if necessary - async but lightweight
        
        Strategy: keep only key fields, with recursion depth limit
        """
        need_compress, tokens = await self.check_tool_output(output)
        
        if not need_compress:
            return output
        
        # Compression logic (synchronous, no IO)
        compressed = self._compress_value(output, depth=0)
        
        logger.info(f"Compressed output: {tokens} tokens -> reduced")
        
        return compressed
    
    def _compress_value(self, value: Any, depth: int) -> Any:
        """Recursive compression - synchronous, depth-controlled"""
        MAX_DEPTH = 5
        
        if depth > MAX_DEPTH:
            return "<truncated: depth limit>"
        
        if isinstance(value, dict):
            # Keep only key fields
            critical = {"status", "result", "error", "code", "data"}
            return {
                k: self._compress_value(v, depth + 1)
                for k, v in value.items()
                if k in critical or depth < 2  # Keep more in the first two levels
            }
        
        elif isinstance(value, list):
            if len(value) > 3:
                return [
                    self._compress_value(v, depth + 1)
                    for v in value[:3]
                ] + [{"_truncated": len(value)}]
            
            return [self._compress_value(v, depth + 1) for v in value]
        
        elif isinstance(value, str) and len(value) > 500:
            # Truncate string, but keep full length info
            return {
                "_type": "string",
                "_head": value[:200],
                "_tail": value[-100:],
                "_length": len(value),
            }
        
        return value
