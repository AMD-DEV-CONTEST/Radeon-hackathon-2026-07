import os
import sys
import time
import asyncio
import signal
import logging
import platform
from typing import Dict, Callable, Any, Optional
from dataclasses import dataclass, field
from functools import partial
from enum import Enum, auto

_original_env = dict(os.environ)

from dotenv import load_dotenv
load_dotenv()

# Automatically set default values (if environment variables are not set)
if not os.getenv("MODEL_SMALL_URL"):
    os.environ["MODEL_SMALL_URL"] = "mock://small-model"

if not os.getenv("MODEL_LARGE_URL"):
    os.environ["MODEL_LARGE_URL"] = "mock://large-model"

# Try to import high-performance event loop
try:
    import uvloop
    if platform.system() != 'Windows':
        uvloop.install()
except ImportError:
    pass

# Added: httpx async client
import httpx

logging.basicConfig(
    level=getattr(logging, os.getenv("LOG_LEVEL", "INFO")),
    format="%(asctime)s %(levelname)s %(message)s",
)
logger = logging.getLogger(__name__)


# ==================== Added: Dynamic Routing ====================

class TaskType(Enum):
    SIMPLE = auto()
    COMPLEX = auto()


@dataclass(frozen=True, slots=True)
class ModelRoute:
    name: str
    url: str


class ModelRouter:
    """Dynamic model router"""

    def __init__(self):
        self.routes = {
            "small": ModelRoute(
                name=os.getenv("MODEL_SMALL_NAME", "Qwen/Qwen2.5-7B-Instruct"),
                url=os.getenv("MODEL_SMALL_URL", "http://localhost:8000"),
            ),
            "large": ModelRoute(
                name=os.getenv("MODEL_LARGE_NAME", "Qwen/Qwen2.5-72B-Instruct"),
                url=os.getenv("MODEL_LARGE_URL", "http://localhost:8001"),
            ),
        }

    def classify(self, query: str) -> TaskType:
        """Task classification: simple/complex"""
        query_lower = query.lower()

        # Complex task patterns
        complex_patterns = (
            "analyze", "debug", "root cause", "why", "how to",
            "分析", "诊断", "排查", "根因", "优化",
        )

        if any(p in query_lower for p in complex_patterns):
            return TaskType.COMPLEX

        return TaskType.SIMPLE

    def get_route(self, task_type: TaskType) -> ModelRoute:
        """Get routing target"""
        return self.routes["large" if task_type == TaskType.COMPLEX else "small"]


# ==================== Modified: Config Extension ====================
from src.agent.orchestrator import Orchestrator, OrchestratorConfig
@dataclass(frozen=True, slots=True)
class Config:
    mode: str = "api"
    host: str = "0.0.0.0"
    port: int = 8000
    timeout: float = 30.0
    max_concurrent: int = 100
    vllm_url: str = "http://localhost:8000"
    mcp_server: Optional[str] = None  # ← added

    @classmethod
    def from_env(cls) -> "Config":
        return cls(
            mode=os.getenv("MODE", "api"),
            host=os.getenv("HOST", "0.0.0.0"),
            port=int(os.getenv("PORT", "8000")),
            timeout=float(os.getenv("TIMEOUT", "30.0")),
            max_concurrent=int(os.getenv("MAX_CONCURRENT", "100")),
            vllm_url=os.getenv("VLLM_URL", "http://localhost:8000"),
            mcp_server=os.getenv("MCP_SERVER"),  # ← added
        )


# ==================== Added: Global Connection Pool ====================

class HTTPClientPool:
    """Global async connection pool - prevents FD exhaustion and OOM"""
    
    _client: Optional[httpx.AsyncClient] = None
    _lock = asyncio.Lock()
    
    @classmethod
    async def get_client(cls, timeout: float = 30.0) -> httpx.AsyncClient:
        if cls._client is None or cls._client.is_closed:
            async with cls._lock:
                if cls._client is None or cls._client.is_closed:
                    cls._client = httpx.AsyncClient(
                        timeout=httpx.Timeout(timeout, connect=5.0),
                        limits=httpx.Limits(
                            max_keepalive_connections=100,
                            max_connections=200,
                        ),
                        http2=False,
                    )
        return cls._client
    
    @classmethod
    async def close(cls) -> None:
        if cls._client and not cls._client.is_closed:
            await cls._client.aclose()
            cls._client = None


# ==================== Modified: Lifespan ====================

class Lifespan:
    """Application lifecycle manager"""

    def __init__(self, config: Config):
        self.config = config
        self.mcp_server = None
        self.orchestrator = None
        self.http_client = None
        self.router = None  # added
        self._shutdown = asyncio.Event()

    async def __aenter__(self) -> "Lifespan":
        from src.mcp.server import MCPServer
        from src.agent.orchestrator import Orchestrator

        # Fix: reuse global connection pool
        self.http_client = await HTTPClientPool.get_client(self.config.timeout)

        # Added: initialize router
        self.router = ModelRouter()

        self.mcp_server = MCPServer()
        self.orchestrator = Orchestrator(
            mcp_server=self.mcp_server,
            vllm_url=self.config.vllm_url,
            http_client=self.http_client,  # Inject shared client
            router=self.router,              # Inject router
        )
        await self.orchestrator.__aenter__()

        self._register_tools()

        if platform.system() != "Windows":
            loop = asyncio.get_running_loop()
            for sig in (signal.SIGTERM, signal.SIGINT):
                loop.add_signal_handler(sig, self._shutdown.set)

        logger.info("lifespan_init_complete")
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        # Fix: do not close the global connection pool; handled by atexit
        if self.orchestrator:
            await self.orchestrator.close()
        if self.mcp_server:
            await self.mcp_server.close()
        # Note: http_client is globally reused, not closed here

        logger.info("lifespan_cleanup_complete")

    def _register_tools(self):
        from src.mcp.tools import search_web, get_weather, get_current_time
        from src.mcp.local_rag import local_rag_search
        from src.rag.pipeline import get_rag_pipeline

        self.mcp_server.register("search", partial(search_web, self.http_client))
        self.mcp_server.register("weather", partial(get_weather, self.http_client))
        self.mcp_server.register("time", lambda: get_current_time())
        self.mcp_server.register("research", search_web)
        self.mcp_server.register("local_rag", lambda query="": local_rag_search(query, get_rag_pipeline()))

    async def wait_shutdown(self):
        await self._shutdown.wait()


# ==================== Modified: Orchestrator Invocation ====================

async def _run_api(lifespan: Lifespan):
    import uvicorn
    from src.api.server import app
    from src.utils.config_loader import load_config

    app.state.orchestrator = lifespan.orchestrator
    app.state.router = lifespan.router
    app.state.config = load_config("config/agent.yaml")
    app.state.original_env = _original_env
    
    from src.rag.pipeline import get_rag_pipeline
    app.state.pipeline = get_rag_pipeline(app.state.config, original_env=_original_env)

    config = uvicorn.Config(
        app=app,
        host=lifespan.config.host,
        port=lifespan.config.port,
        loop="asyncio" if platform.system() == "Windows" else "uvloop",
        workers=1,
        access_log=False,
    )
    server = uvicorn.Server(config)
    task = asyncio.create_task(server.serve())

    await lifespan.wait_shutdown()
    task.cancel()
    await task


async def _run_cli(lifespan: Lifespan):
    print("Interactive mode. Enter queries (Ctrl+D to exit)")
    loop = asyncio.get_running_loop()
    
    while not lifespan._shutdown.is_set():
        try:
            query = await loop.run_in_executor(None, input, "> ")
        except EOFError:
            break
            
        if not query.strip():
            continue

        # Added: display routing decision
        task_type = lifespan.router.classify(query)
        route = lifespan.router.get_route(task_type)
        print(f"[route: {task_type.name} -> {route.name}]")

        t0 = time.perf_counter()
        result = await lifespan.orchestrator.execute(query)
        latency_ms = (time.perf_counter() - t0) * 1000
        print(f"[{latency_ms:.1f}ms] {result}")


_MODES: Dict[str, Callable] = {"api": _run_api, "cli": _run_cli}


async def main():
    config = Config.from_env()
    runner = _MODES.get(config.mode)

    if not runner:
        logger.error(f"Unknown mode: {config.mode}")
        sys.exit(1)

    async with Lifespan(config) as lifespan:
        await runner(lifespan)


# ==================== Added: Process Exit Cleanup ====================

def _cleanup():
    """Clean up connection pool on process exit"""
    loop = asyncio.new_event_loop()
    loop.run_until_complete(HTTPClientPool.close())
    loop.close()

import atexit
atexit.register(_cleanup)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Received keyboard interrupt, exiting...")