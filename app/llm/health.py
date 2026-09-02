from __future__ import annotations

from dataclasses import dataclass

import httpx

from app.config import Settings


@dataclass(frozen=True, slots=True)
class ModelHealth:
    reachable: bool
    detail: str
    status_code: int | None = None


def model_health_url(settings: Settings) -> str:
    """Convert the OpenAI `/v1` base URL into llama-server's health endpoint."""
    base_url = str(settings.llm_base_url).rstrip("/")
    return f"{base_url[:-3]}/health"


async def check_model_health(
    settings: Settings,
    *,
    transport: httpx.AsyncBaseTransport | None = None,
) -> ModelHealth:
    try:
        async with httpx.AsyncClient(
            timeout=settings.llm_timeout_seconds,
            transport=transport,
        ) as client:
            response = await client.get(model_health_url(settings))
    except httpx.HTTPError as error:
        return ModelHealth(reachable=False, detail=f"model service unavailable: {error}")

    if response.is_success:
        return ModelHealth(reachable=True, detail="model service reachable", status_code=response.status_code)
    return ModelHealth(
        reachable=False,
        detail=f"model service returned HTTP {response.status_code}",
        status_code=response.status_code,
    )
