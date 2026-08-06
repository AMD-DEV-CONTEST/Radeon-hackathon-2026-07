"""
Orchestrator - Self-developed planning reasoning engine v2


"""

from __future__ import annotations

import os
import time
import sys
import json
import asyncio
import logging
import weakref
from typing import (
    Optional, AsyncIterator, Callable, Awaitable,
    Literal, Any, Union,
)
from dataclasses import dataclass, field, asdict, replace as dataclasses_replace
import dataclasses
from enum import Enum, auto
from collections import OrderedDict
from contextlib import asynccontextmanager
from functools import lru_cache
from ..scheduler.sweet_spot_finder import SweetSpotFinder, SweetSpot, ContinuousSweetSpotMonitor
from ..scheduler.backpressure_controller import BackpressureController, AdaptiveRouter, PressureLevel
from ..scheduler.vllm_scheduler import VLLMDynamicScheduler, VLLMScheduleConfig

# Lazy import to avoid instantiation at import time
import httpx

logger = logging.getLogger(__name__)


# ==================== Configuration layer: zero hardcoding ====================

@dataclass(frozen=True, slots=True)
class ModelEndpoint:
    """Model endpoint - immutable config"""
    name: str
    url: str
    timeout: float = 30.0
    api_key: str = ""

    @property
    def chat_url(self) -> str:
        return f"{self.url.rstrip('/')}/chat/completions"

    @property
    def auth_headers(self) -> dict:
        if not self.api_key:
            return {}
        try:
            self.api_key.encode("ascii")
        except UnicodeEncodeError:
            return {}
        return {"Authorization": f"Bearer {self.api_key}"}


@dataclass(frozen=True, slots=True)
class OrchestratorConfig:
    """Unified config - environment-driven, no hardcoded defaults"""

    # Model endpoints
    small: ModelEndpoint = field(default_factory=lambda: ModelEndpoint(
        name=os.getenv("MODEL_SMALL_NAME", ""),
        url=os.getenv("MODEL_SMALL_URL", ""),
        timeout=float(os.getenv("MODEL_SMALL_TIMEOUT", "10.0")),
        api_key=os.getenv("HF_TOKEN", ""),
    ))
    large: ModelEndpoint = field(default_factory=lambda: ModelEndpoint(
        name=os.getenv("MODEL_LARGE_NAME", ""),
        url=os.getenv("MODEL_LARGE_URL", ""),
        timeout=float(os.getenv("MODEL_LARGE_TIMEOUT", "60.0")),
        api_key=os.getenv("HF_TOKEN", ""),
    ))
    
    # Inference parameters
    max_tokens: int = field(default_factory=lambda: int(os.getenv("MAX_TOKENS", "4096")))
    temperature: float = field(default_factory=lambda: float(os.getenv("TEMPERATURE", "0.7")))

    # Performance control
    max_concurrent: int = field(default_factory=lambda: int(os.getenv("MAX_CONCURRENT", "100")))
    cache_size: int = field(default_factory=lambda: int(os.getenv("CACHE_SIZE", "1000")))
    cache_ttl: float = field(default_factory=lambda: float(os.getenv("CACHE_TTL", "3600.0")))

    # OOM protection
    max_context_length: int = field(default_factory=lambda: int(os.getenv("MAX_CONTEXT_LENGTH", "128000")))
    enable_streaming: bool = field(default_factory=lambda: os.getenv("ENABLE_STREAMING", "true").lower() == "true")

    def validate(self) -> None:
        """Single validation point, avoids overlapping checks"""
        if not self.small.url or not self.large.url:
            raise ValueError("MODEL_SMALL_URL and MODEL_LARGE_URL must be set")
        if self.max_concurrent < 1:
            raise ValueError("max_concurrent must be >= 1")
        if self.cache_size < 0:
            raise ValueError("cache_size must be >= 0")


# ==================== Cache layer: bounded + eviction ====================

class BoundedLRUCache:
    """
    Bounded LRU cache - OOM protection

    Features:
    - Fixed capacity, auto-evicts least recently used
    - Optional TTL (not implemented, extensible)
    - Size-aware, prevents large object accumulation
    """
    
    def __init__(self, capacity: int, max_item_size: int = 1024 * 1024):
        self._capacity = capacity
        self._max_item_size = max_item_size
        self._cache: OrderedDict[str, Any] = OrderedDict()
        self._lock = asyncio.Lock()
        self._hits = 0
        self._misses = 0
    
    async def get(self, key: str) -> Optional[Any]:
        async with self._lock:
            if key in self._cache:
                self._cache.move_to_end(key)
                self._hits += 1
                return self._cache[key]
            self._misses += 1
            return None
    
    async def put(self, key: str, value: Any) -> None:
        """Store into cache, auto-evict"""
        # Estimate size, skip oversized objects
        try:
            size = len(json.dumps(value, default=str))
        except Exception:
            size = sys.getsizeof(value)
        
        if size > self._max_item_size:
            logger.warning(f"cache_skip_oversized: key={key[:50]}, size={size}")
            return
        
        async with self._lock:
            if key in self._cache:
                self._cache.move_to_end(key)
                self._cache[key] = value
                return
            
            # Evict least recently used
            while len(self._cache) >= self._capacity:
                self._cache.popitem(last=False)
            
            self._cache[key] = value
    
    async def clear(self) -> None:
        async with self._lock:
            self._cache.clear()
    
    @property
    def stats(self) -> dict:
        total = self._hits + self._misses
        return {
            "size": len(self._cache),
            "capacity": self._capacity,
            "hits": self._hits,
            "misses": self._misses,
            "hit_rate": self._hits / total if total > 0 else 0.0,
        }


# ==================== Connection pool: global singleton, lazy init ====================

class ConnectionPool:
    """
    Global async connection pool - lazy init, leak-proof

    Key design:
    - Created on first use
    - Closed uniformly on process exit
    - Not exposed to callers for management
    """
    
    _instance: Optional[httpx.AsyncClient] = None
    _initialized = False
    _lock = asyncio.Lock()
    
    @classmethod
    async def get(cls) -> httpx.AsyncClient:
        if cls._instance is not None and not cls._instance.is_closed:
            return cls._instance
        
        async with cls._lock:
            if cls._instance is not None and not cls._instance.is_closed:
                return cls._instance
            
            cls._instance = httpx.AsyncClient(
                timeout=httpx.Timeout(30.0, connect=5.0),
                limits=httpx.Limits(
                    max_keepalive_connections=100,
                    max_connections=200,
                ),
                http2=False,  # vLLM not supported
            )
            cls._initialized = True
            logger.debug("connection_pool_initialized")
        
        return cls._instance
    
    @classmethod
    async def close(cls) -> None:
        if cls._instance and not cls._instance.is_closed:
            await cls._instance.aclose()
            cls._instance = None
            cls._initialized = False
            logger.debug("connection_pool_closed")


# ==================== Context object: flat state, no redundancy ====================

@dataclass(slots=True)
class InferenceContext:
    """
    Inference context - single state carrier

    Design: replaces multi-layer nested state, avoids redundant copying
    """

    # Input
    query: str
    messages: list[dict] = field(default_factory=list)

    # Inference state
    task_type: Optional[str] = None
    model_endpoint: Optional[ModelEndpoint] = None

    # Execution trace (fully preserved, no truncation)
    plan_steps: list[dict] = field(default_factory=list)
    tool_calls: list[dict] = field(default_factory=list)
    observations: list[dict] = field(default_factory=list)

    # Result
    result: Optional[str] = None
    tokens_used: int = 0
    latency_ms: float = 0.0

    def to_messages(self) -> list[dict]:
        """Export to LLM message format"""
        base = list(self.messages)
        base.append({"role": "user", "content": self.query})
        return base


# ==================== Routing decision: stateless, pure function ====================

class TaskRouter:
    """Task router - stateless, no hardcoding"""

    # Simple task features (configurable, not hardcoded)
    SIMPLE_KEYWORDS = frozenset({
        "status", "health", "ping", "ready",
        "log", "日志", "状态", "查询",
    })

    # Complex task features
    COMPLEX_KEYWORDS = frozenset({
        "analyze", "debug", "root cause", "why",
        "分析", "诊断", "排查", "根因", "优化",
    })

    def classify(self, query: str, tool_count: int = 0) -> str:
        """
        Classify task complexity - returns string to avoid enum dependency

        Rule priority:
        1. Many tools -> complex
        2. Complex keywords -> complex
        3. Simple keywords -> simple
        4. Default -> simple (cost-first)
        """
        if not query:
            return "simple"

        normalized = query.lower()

        # Rule 1: tool count
        if tool_count >= 3:
            return "complex"

        # Rule 2: complex features
        if any(kw in normalized for kw in self.COMPLEX_KEYWORDS):
            return "complex"

        # Rule 3: simple features
        if any(kw in normalized for kw in self.SIMPLE_KEYWORDS):
            return "simple"

        # Rule 4: query length heuristic
        if len(query) > 1000:
            return "complex"

        return "simple"

    def select_endpoint(self, task_type: str, config: OrchestratorConfig) -> ModelEndpoint:
        """Select endpoint - explicit mapping, no double mapping"""
        return config.large if task_type == "complex" else config.small


# ==================== Inference execution: unified entry, no duplication ====================

class InferenceEngine:
    """
    Inference engine - single responsibility, no duplicate exception handling

    Design:
    - Unified entry: infer()
    - Exception pass-through: no wrapping, let caller decide
    - Full preservation: no string truncation
    """
    
    def __init__(self, client: httpx.AsyncClient, config: OrchestratorConfig):
        self.client = client
        self.config = config
    
    async def infer(
        self,
        endpoint: ModelEndpoint,
        messages: list[dict],
        *,
        stream: bool = False,
        max_tokens: Optional[int] = None,
        temperature: Optional[float] = None,
    ) -> Union[dict, AsyncIterator[str]]:
        """
        Unified inference entry

        Args:
            endpoint: target model
            messages: full message list (no truncation)
            stream: whether to stream
            max_tokens: override default
            temperature: override default

        Returns:
            Full response JSON, or stream iterator
        """
        payload = {
            "model": endpoint.name,
            "messages": messages,
            "max_tokens": max_tokens or self.config.max_tokens,
            "temperature": temperature or self.config.temperature,
            "stream": stream,
        }
        
        if stream:
            return self._infer_stream(endpoint, payload)
        
        return await self._infer_sync(endpoint, payload)
    
    async def _infer_sync(self, endpoint: ModelEndpoint, payload: dict) -> dict:
        """Sync inference - full return"""
        response = await self.client.post(
            endpoint.chat_url,
            json=payload,
            headers={"Content-Type": "application/json", **endpoint.auth_headers},
        )
        response.raise_for_status()
        return response.json()

    async def _infer_stream(self, endpoint: ModelEndpoint, payload: dict) -> AsyncIterator[str]:
        """Streaming inference - reduce first-token latency"""
        async with self.client.stream(
            "POST",
            endpoint.chat_url,
            json=payload,
            headers={"Content-Type": "application/json", **endpoint.auth_headers},
        ) as response:
            response.raise_for_status()

            async for line in response.aiter_lines():
                if line.startswith("data: "):
                    yield line[6:]  # Strip "data: " prefix, keep full content


# ==================== Main class: unified entry, no dead code ====================

class Orchestrator:
    """
    Unified scheduling entry - sole external interface

    Removed:
    - Deprecated factory functions (e.g. create_orchestrator)
    - Redundant wrapper methods (e.g. run/process/invoke)
    - Duplicate exception handling layers

    Kept:
    - execute(): sole entry
    - close(): resource cleanup
    """

    def __init__(self, config: Optional[OrchestratorConfig] = None,**kwargs):## Absorb extra params, or for extension
        self.config = config or OrchestratorConfig()
        self.config.validate()  # Single validation point

        # Lazy init, no connection created here
        self._client: Optional[httpx.AsyncClient] = None
        self._engine: Optional[InferenceEngine] = None
        # Extract optional dependencies from kwargs
        self.mcp_server = kwargs.get('mcp_server')
        self.http_client = kwargs.get('http_client') or (config.http_client if config else None)
        self._router = TaskRouter()
        self._cache: Optional[BoundedLRUCache] = None

        # Concurrency control
        self._semaphore: Optional[asyncio.Semaphore] = None
        
    
    def set_api_key(self, api_key: str):
        if not api_key:
            return
        try:
            api_key.encode("ascii")
        except UnicodeEncodeError:
            return
        self.config = dataclasses_replace(
            self.config,
            small=dataclasses_replace(self.config.small, api_key=api_key),
            large=dataclasses_replace(self.config.large, api_key=api_key),
        )

    def set_model_url(self, model_url: str):
        """Update model endpoint URL at runtime (from frontend input)."""
        if not model_url:
            return
        url = model_url.rstrip('/')
        self.config = dataclasses_replace(
            self.config,
            small=dataclasses_replace(self.config.small, url=url),
            large=dataclasses_replace(self.config.large, url=url),
        )
    
    # ==================== Lifecycle management ====================

    async def __aenter__(self) -> Orchestrator:
        """Async context - initialize resources"""
        self._client = await ConnectionPool.get()
        self._engine = InferenceEngine(self._client, self.config)
        self._cache = BoundedLRUCache(self.config.cache_size) if self.config.cache_size > 0 else None
        self._semaphore = asyncio.Semaphore(self.config.max_concurrent)
        return self

    async def __aexit__(self, *args) -> None:
        """Do not close global connection pool, only clear references"""
        self._engine = None
        self._cache = None
        self._semaphore = None

    async def close(self) -> None:
        """Explicit close - for non-context-manager scenarios"""
        await ConnectionPool.close()

    # ==================== Unified API entry ====================
    
    async def execute(
        self,
        query: str,
        *,
        context: Optional[list[dict]] = None,
        tools: Optional[list[dict]] = None,
        stream: bool = False,
    ) -> dict:
        """
        Sole execution entry - precision first

        Flow:
        1. Build context (fully preserved)
        2. Routing decision
        3. Cache check
        4. Execute inference
        5. Return full result

        Args:
            query: user query (fully preserved)
            context: conversation context (fully preserved)
            tools: tool list (for routing)
            stream: whether to stream

        Returns:
            Full result dict, no truncation
        """
        start_time = asyncio.get_event_loop().time()

        # 1. Build context
        ctx = InferenceContext(query=query)
        if context:
            ctx.messages.extend(context)

        # 2. Routing decision
        ctx.task_type = self._router.classify(query, len(tools) if tools else 0)
        ctx.model_endpoint = self._router.select_endpoint(ctx.task_type, self.config)

        logger.info(f"execute: task_type={ctx.task_type}, model={ctx.model_endpoint.name}")

        # 3. Cache check (based on full messages content)
        messages = ctx.to_messages()
        cache_key = f"{ctx.task_type}:{hash(json.dumps(messages, ensure_ascii=False)[:200])}"
        if self._cache:
            cached = await self._cache.get(cache_key)
            if cached:
                return {
                    "cached": True,
                    "task_type": ctx.task_type,
                    "model": ctx.model_endpoint.name,
                    "result": cached,
                }

        # 4. Execute inference (with concurrency control)
        if not self._semaphore or not self._engine:
            raise RuntimeError("Orchestrator not initialized. Use 'async with'.")

        async with self._semaphore:
            if stream:
                # Return stream iterator
                return {
                    "stream": self._engine.infer(
                        endpoint=ctx.model_endpoint,
                        messages=messages,
                        stream=True,
                    ),
                    "task_type": ctx.task_type,
                    "model": ctx.model_endpoint.name,
                }

            # Sync wait for full result
            raw_result = await self._engine.infer(
                endpoint=ctx.model_endpoint,
                messages=messages,
            )

        # 5. Extract result (fully preserved)
        ctx.result = self._extract_content(raw_result)
        ctx.tokens_used = raw_result.get("usage", {}).get("total_tokens", 0)
        ctx.latency_ms = (asyncio.get_event_loop().time() - start_time) * 1000

        # Cache result
        if self._cache:
            await self._cache.put(cache_key, ctx.result)

        # Return full context, no truncation
        return {
            "task_type": ctx.task_type,
            "model": ctx.model_endpoint.name,
            "result": ctx.result,
            "tokens_used": ctx.tokens_used,
            "latency_ms": ctx.latency_ms,
            "plan_steps": ctx.plan_steps,  # Fully preserved
        }
    
    # ==================== Batch execution: backpressure control ====================

    async def execute_batch(
        self,
        queries: list[str],
        *,
        max_concurrent: Optional[int] = None,
    ) -> list[dict]:
        """
        Batch execution - backpressure control prevents OOM

        Args:
            queries: query list
            max_concurrent: override default concurrency
        """
        limit = max_concurrent or self.config.max_concurrent
        sem = asyncio.Semaphore(limit)

        async def _bounded(q: str) -> dict:
            async with sem:
                return await self.execute(q)

        # Control concurrency, avoid burst
        return await asyncio.gather(*(_bounded(q) for q in queries))

    # ==================== Internal tools ====================

    def _extract_content(self, raw: dict) -> str:
        """Extract content from vLLM response - fully preserved"""
        try:
            choices = raw.get("choices", [])
            if choices:
                return choices[0].get("message", {}).get("content", "")
            return ""
        except Exception:
            # Return raw on exception, no information loss
            return str(raw)


# ==================== Global lifecycle ====================

@asynccontextmanager
async def orchestrator_scope(config: Optional[OrchestratorConfig] = None):
    """
    Global lifecycle management - ensures connection pool is properly closed

    Usage:
        async with orchestrator_scope() as orch:
            result = await orch.execute("query")
    """
    orch = Orchestrator(config)
    try:
        await orch.__aenter__()
        yield orch
    finally:
        await ConnectionPool.close()


# ==================== Compatibility: legacy interface mapping ====================

# All deprecated factory functions removed, e.g.:
# def create_orchestrator(): ...  # removed
# class OrchestratorFactory: ...   # removed


# ==================== Tests ====================

async def _test():
    """Internal test"""
    import os

    if not os.getenv("MODEL_SMALL_URL"):
        print("Set MODEL_SMALL_URL to test")
        return

    async with orchestrator_scope() as orch:
        # Simple task
        r1 = await orch.execute("Check status")
        print(f"Simple: {r1['task_type']}, latency={r1['latency_ms']:.1f}ms")

        # Complex task
        r2 = await orch.execute("Analyze root cause of memory leak")
        print(f"Complex: {r2['task_type']}, tokens={r2['tokens_used']}")

        # Cache test
        r3 = await orch.execute("Check status")
        print(f"Cache stats: {orch._cache.stats if orch._cache else 'N/A'}")

        # Batch test
        batch = await orch.execute_batch([
            "Status?", "Debug?", "Optimize?",
        ], max_concurrent=2)
        print(f"Batch: {len(batch)} results")

class ProductionOrchestrator:
    """
    Production-grade orchestrator

    Three layers of protection:
. Sweet spot detection: find optimal concurrency config
. Adaptive rate limiting: prevent queue avalanche in real time
. Dynamic scheduling: adjust vLLM params based on load
    """

    def __init__(self, vllm_endpoint: str):
        self.vllm = VLLMDynamicScheduler(vllm_endpoint)

        # Sweet spot detection
        self._spot_finder = SweetSpotFinder(
            min_concurrency=3,
            max_concurrency=20,
            target_p99_ms=1000.0,
        )

        # Adaptive rate limiting
        self._backpressure = BackpressureController()

        # Routing
        self._router = AdaptiveRouter()

        # Current state
        self._sweet_spot: Optional[SweetSpot] = None
        self._active_requests = 0

    async def initialize(self, benchmark_func):
        """Initialize - detect sweet spot"""

        logger.info("Initializing production orchestrator...")

        # Detect sweet spot
        self._sweet_spot = await self._spot_finder.find(benchmark_func)

        logger.info(f"Sweet spot found: concurrency={self._sweet_spot.concurrency}, "
                   f"rps={self._sweet_spot.rps:.2f}, p99={self._sweet_spot.ttft_p99:.0f}ms")

        # Apply optimal config
        await self.vllm.apply_profile("balanced")

        # Start continuous monitoring
        self._monitor = ContinuousSweetSpotMonitor(self._spot_finder)

        # Launch background monitoring task
        asyncio.create_task(self._monitor.start(
            benchmark_func,
            on_spot_change=self._on_sweet_spot_change,
        ))

    async def execute(self, query: str) -> AsyncIterator[str]:
        """
        Execute request - with full protection

        Flow:
. Rate limit check
. Concurrency control
. Execute request
. Report latency
        """

        # 1. Adaptive rate limiting
        if not await self._backpressure.acquire():
            # Service overloaded, fail fast or degrade
            yield "[Server busy, please retry]"
            return

        # 2. Concurrency control (based on sweet spot)
        if self._sweet_spot and self._active_requests >= self._sweet_spot.concurrency:
            # Reached sweet spot concurrency, queue and wait
            while self._active_requests >= self._sweet_spot.concurrency:
                await asyncio.sleep(0.01)

        # 3. Execute request
        self._active_requests += 1
        start = time.monotonic()

        try:
            # Actual execution...
            async for token in self._do_execute(query):
                yield token

            # 4. Report latency
            ttft = (time.monotonic() - start) * 1000
            await self._backpressure.report_latency(ttft)

        finally:
            self._active_requests -= 1

    async def _do_execute(self, query: str) -> AsyncIterator[str]:
        """Actual execution (simplified)"""
        # Call vLLM...
        yield "result"

    async def _on_sweet_spot_change(self, new_spot: SweetSpot):
        """Sweet spot change callback"""

        logger.info(f"Sweet spot drifted: {self._sweet_spot} -> {new_spot}")

        # Update concurrency limit
        self._sweet_spot = new_spot

        # Adjust vLLM based on new sweet spot
        if new_spot.ttft_p99 > 2000:
            await self.vllm.adjust_for_pressure("high")
        elif new_spot.ttft_p99 < 500:
            await self.vllm.adjust_for_pressure("low")

    @property
    def status(self) -> dict:
        """Current state"""
        return {
            "sweet_spot": {
                "concurrency": self._sweet_spot.concurrency if self._sweet_spot else None,
                "rps": self._sweet_spot.rps if self._sweet_spot else None,
                "ttft_p99": self._sweet_spot.ttft_p99 if self._sweet_spot else None,
            },
            "backpressure": self._backpressure.current_state,
            "active_requests": self._active_requests,
        }
    """Agent orchestrator"""

# Existing imports...
from .specialists.code import CodeAgent
from .specialists.creative import CreativeAgent
from .specialists.research import ResearchAgent  # if present

# Added: import knowledge assistant
from .specialists.knowledge_assistant import KnowledgeAssistant


class AgentOrchestrator:
    def __init__(self):
        self.agents = {
            "code": CodeAgent(),
            "creative": CreativeAgent(),
            "research": ResearchAgent(),
            # Added
            "knowledge": KnowledgeAssistant(),
        }

        # Initialize knowledge assistant (optional)
        self.agents["knowledge"].initialize()

    async def route(self, query: str, context: dict = None) -> dict:
        """
        Route to the appropriate agent

        Strategy:
        - Contains keywords like "document", "knowledge", "query" -> knowledge assistant
        - Code-related questions -> code assistant
        - Creative writing -> creative assistant
        """
        query_lower = query.lower()

        # Knowledge base query detection
        knowledge_keywords = [
            "文档", "资料", "根据", "查询", "搜索", "找到",
            "knowledge", "document", "search", "find", "query",
            "pdf", "手册", "说明书", "报告", "论文"
        ]

        if any(kw in query_lower for kw in knowledge_keywords):
            return await self.agents["knowledge"].process(query)

        # Code detection
        code_keywords = ["code", "编程", "bug", "函数", "class"]
        if any(kw in query_lower for kw in code_keywords):
            return await self.agents["code"].process(query)

        # Default route
        return await self.agents["creative"].process(query)


if __name__ == "__main__":
    asyncio.run(_test())