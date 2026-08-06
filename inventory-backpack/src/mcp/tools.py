from __future__ import annotations

import asyncio
import time
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Awaitable, Callable, Coroutine, ParamSpec, TypeVar

import httpx

@dataclass(slots=True, frozen=True)
class APIConfig:
    """Declarative API config, pure data, zero behavior"""
    method: str
    url_template: str
    params: dict[str, str] | None = None
    headers: dict[str, str] | None = None

async def _api(
    client: httpx.AsyncClient,
    config: APIConfig,
    *,
    path_params: dict[str, str] | None = None,
    query_params: dict[str, Any] | None = None,
    json_data: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    Unified HTTP execution entry.
    Exceptions are raised directly, converged into ToolResult by MCPServer.
    Latency measurement is inlined, does not affect hot path.
    """
    t0 = time.perf_counter()

    url = config.url_template.format(**(path_params or {}))

    response = await client.request(
        config.method,
        url,
        params=query_params,
        json=json_data,
        headers=config.headers,
    )
    response.raise_for_status()

    # Only log latency at DEBUG level to avoid string concatenation overhead
    # logger = logging.getLogger(__name__)
    # logger.debug(f"api_latency_ms={(time.perf_counter() - t0) * 1000:.2f}")

    return response.json()

async def search_web(
    client: httpx.AsyncClient,
    query: str,
) -> dict[str, Any]:
    """
    DuckDuckGo instant search.
    Exceptions are raised, caught by MCPServer and converted to ToolResult.
    """
    return await _api(
        client,
        APIConfig("GET", "https://api.duckduckgo.com/"),
        query_params={"q": query, "format": "json"},
    )


async def get_weather(
    client: httpx.AsyncClient,
    city: str,
) -> dict[str, Any]:
    """
    wttr.in weather query.
    """
    data = await _api(
        client,
        APIConfig("GET", "https://wttr.in/{city}"),
        path_params={"city": city},
        query_params={"format": "j1"},
    )

    current = data["current_condition"][0]

    return {
        "city": city,
        "temp_c": current["temp_C"],
        "weather_desc": current["weatherDesc"][0]["value"],
        "humidity": current["humidity"],
    }


async def get_current_time() -> dict[str, Any]:
    """
    Local system time, no external dependencies.
    Non-IO operation, no client needed.
    """
    return {
        "current_time": datetime.now().isoformat(),
    }

def create_http_client() -> httpx.AsyncClient:
    """
    Create an optimized HTTP client.
    Held by main.py Lifespan and injected into each tool.
    """
    return httpx.AsyncClient(
        timeout=httpx.Timeout(10.0, connect=2.0),
        limits=httpx.Limits(
            max_connections=100,
            max_keepalive_connections=20,
            keepalive_expiry=30.0,
        ),
        http2=True,  # Multiplexing, reduces latency
    )
