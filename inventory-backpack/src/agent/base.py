import asyncio
import json
import time
from typing import List, Dict, Any, Tuple, Optional, Callable
from dataclasses import dataclass

#----incoming
from dataclasses import dataclass

@dataclass(slots=True, frozen=True)
class Message:
    role: str
    content: str

@dataclass(slots=True, frozen=True)
class AgentConfig:
    name: str
    model: str = "default"

class BaseAgent:
    def __init__(self, config: AgentConfig):
        self.config = config

#----

# Minimal state enum to avoid Enum overhead
SUCCESS, FAILED, TIMEOUT = "success", "failed", "timeout"


@dataclass(slots=True)
class ToolResult:
    tool_name: str
    status: str
    result: Any = None
    error: str = ""
    latency_ms: float = 0.0


class MCPServer:
    """
    Inference-optimized MCP Server
    - Single entry execute()
    - Stateless, no context management overhead
    - Semaphore prevents OOM, timeout prevents hang
    """

    __slots__ = ("_tools", "_timeout", "_sem")

    def __init__(
        self,
        timeout: float = 30.0,
        max_concurrent: Optional[int] = None,
    ):
        self._tools: Dict[str, Callable] = {}
        self._timeout = timeout
        # Use dummy context when unlimited to avoid branch checks
        self._sem = asyncio.Semaphore(max_concurrent) if max_concurrent else None

    def register(self, name: str, handler: Callable) -> None:
        self._tools[name] = handler

    async def execute(
        self,
        calls: List[Dict],
        *,
        timeout: Optional[float] = None,
        ordered: bool = True,
    ) -> List[ToolResult]:
        """Single entry: execute tool list concurrently"""
        if not calls:
            return []

        t = timeout or self._timeout

        # Execute concurrently; gather handles exceptions uniformly
        results = await asyncio.gather(
            *(self._run(i, c, t) for i, c in enumerate(calls)),
            return_exceptions=True,
        )

        # Extract results; convert exceptions to failed
        out: List[Tuple[int, ToolResult]] = []
        for i, r in enumerate(results):
            if isinstance(r, Exception):
                out.append((i, ToolResult("unknown", FAILED, error=str(r))))
            else:
                out.append(r)

        if ordered:
            out.sort(key=lambda x: x[0])

        return [r for _, r in out]

    async def _run(
        self,
        idx: int,
        call: Dict,
        timeout: float,
    ) -> Tuple[int, ToolResult]:
        """Single execution, fully isolated"""

        name, args = self._parse(call)
        handler = self._tools.get(name)

        if not handler:
            return idx, ToolResult(name, FAILED, error="not found")

        # Semaphore control (prevents OOM); zero overhead when None
        ctx = self._sem or _NullCtx()

        async with ctx:
            t0 = time.perf_counter()

            try:
                coro = handler(**args)
                result = await asyncio.wait_for(coro, timeout=timeout)

                return idx, ToolResult(
                    name, SUCCESS, result=result,
                    latency_ms=(time.perf_counter() - t0) * 1000
                )

            except asyncio.TimeoutError:
                return idx, ToolResult(
                    name, TIMEOUT, error=f"timeout>{timeout}s",
                    latency_ms=(time.perf_counter() - t0) * 1000
                )

            except Exception as e:
                return idx, ToolResult(
                    name, FAILED, error=str(e),
                    latency_ms=(time.perf_counter() - t0) * 1000
                )

    @staticmethod
    def _parse(call: Dict) -> Tuple[str, Dict]:
        func = call.get("function", {})
        name = func.get("name", "unknown")
        args = func.get("arguments", "{}")
        if isinstance(args, str):
            args = json.loads(args)
        return name, args


# Zero-overhead empty context (replaces NullContext, avoids asyncio version compatibility issues)
class _NullCtx:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        pass
