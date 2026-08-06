import asyncio
import json
import logging
from typing import List, Dict, Any, Tuple, Optional, Callable, Awaitable
from dataclasses import dataclass
from enum import Enum
from contextlib import nullcontext
import time


logger = logging.getLogger(__name__)


class ToolStatus(str, Enum):
    SUCCESS = "success"
    FAILED = "failed"
    TIMEOUT = "timeout"


@dataclass(slots=True, frozen=True)
class ToolResult:
    tool_name: str
    status: ToolStatus
    result: Any = None
    error: str = ""
    latency_ms: float = 0.0


class MCPServer:
    """
    MCP Server - high-performance single-task execution entry
    """
    __slots__ = ("_tools", "_timeout", "_semaphore", "_max_retries", "_closed")

    def __init__(
        self,
        timeout: float = 30.0,
        max_concurrency: Optional[int] = None,
        max_retries: int = 2,
    ):
        self._tools: Dict[str, Callable[..., Awaitable[Any]]] = {}
        self._timeout = timeout
        self._max_retries = max_retries
        self._closed = False

        self._semaphore: Optional[asyncio.Semaphore] = None
        if max_concurrency is not None:
            self._semaphore = asyncio.Semaphore(max_concurrency)

    def register(self, name: str, handler: Callable[..., Awaitable[Any]]) -> None:
        """Dynamically register a tool"""
        self._tools[name] = handler

    async def execute(
        self,
        tool_name: str,
        params: Dict[str, Any],
    ) -> List[ToolResult]:
        """Unified execution entry"""
        if self._closed:
            return [ToolResult(
                tool_name=tool_name,
                status=ToolStatus.FAILED,
                error="Server is closed",
            )]

        args = self._parse_args(params)

        handler = self._tools.get(tool_name)
        if handler is None:
            return [ToolResult(
                tool_name=tool_name,
                status=ToolStatus.FAILED,
                error=f"Tool not found: {tool_name}",
            )]

        last_error = ""
        for attempt in range(self._max_retries + 1):
            try:
                result = await self._invoke(handler, tool_name, args, self._timeout)
                return [result]

            except asyncio.TimeoutError:
                last_error = f"Timeout after {self._timeout}s (Attempt {attempt + 1})"
                if attempt < self._max_retries:
                    continue
                break

            except Exception as e:
                last_error = f"{type(e).__name__}: {str(e)}"
                break

        return [ToolResult(
            tool_name=tool_name,
            status=ToolStatus.FAILED,
            error=last_error or "Unknown execution failure",
        )]

    async def _invoke(
        self,
        handler: Callable[..., Awaitable[Any]],
        tool_name: str,
        args: Dict[str, Any],
        timeout: float
    ) -> ToolResult:
        """Low-level async execution"""
        ctx = self._semaphore if self._semaphore is not None else nullcontext()

        async with ctx:
            t0 = time.perf_counter()
            try:
                result = await asyncio.wait_for(handler(**args), timeout=timeout)
                latency_ms = (time.perf_counter() - t0) * 1000

                return ToolResult(
                    tool_name=tool_name,
                    status=ToolStatus.SUCCESS,
                    result=result,
                    latency_ms=latency_ms,
                )
            except asyncio.TimeoutError:
                raise
            except Exception as e:
                raise

    @staticmethod
    def _parse_args(params: Any) -> Dict[str, Any]:
        """Minimal argument parsing"""
        if isinstance(params, dict):
            return params
        if isinstance(params, str):
            try:
                return json.loads(params)
            except json.JSONDecodeError:
                return {"query": params}
        return {}

    # ═══════ Added: lifecycle management ═══════

    async def close(self) -> None:
        """Close the server"""
        self._closed = True
        # Clean up resources (if any)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        await self.close()
