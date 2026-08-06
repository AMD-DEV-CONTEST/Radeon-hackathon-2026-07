from __future__ import annotations

import asyncio
from typing import Any

import httpx

from glass_gateway.external_services.contracts import (
    CONTRACT_VERSION,
    DEFAULT_MAX_IMAGE_BYTES,
    FACE_RECOGNITION_PATH,
    MODELS_PATH,
    service_root_url,
)
from glass_gateway.external_services.media import (
    IMAGE_MEDIA_TYPES,
    authorization_headers,
    encode_media,
)


class IdentityWorkerClient:
    def __init__(
        self,
        base_url: str,
        *,
        api_key: str | None = None,
        model: str = "insightface",
        timeout_seconds: float = 15.0,
        max_media_bytes: int = DEFAULT_MAX_IMAGE_BYTES,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.model = model
        self.max_media_bytes = max_media_bytes
        self._client = httpx.AsyncClient(
            base_url=service_root_url(base_url),
            timeout=timeout_seconds,
            transport=transport,
            trust_env=False,
            headers=authorization_headers(api_key),
        )

    async def recognize(self, payload: dict[str, Any]) -> dict[str, Any]:
        local_path = payload.get("image_path")
        if not local_path:
            raise ValueError("identity payload requires internal image_path")
        media = await asyncio.to_thread(
            encode_media,
            local_path,
            max_bytes=self.max_media_bytes,
            allowed_media_types=IMAGE_MEDIA_TYPES,
        )
        declared_media_type = str(payload.get("media_type") or "")
        if declared_media_type and declared_media_type != media.media_type:
            raise ValueError("identity media type does not match file suffix")
        request_payload = {
            key: value
            for key, value in payload.items()
            if key not in {"image_path", "media_type"}
        }
        request_payload.update(
            {
                "model": self.model,
                "contract_version": CONTRACT_VERSION,
                "media": media.model_dump(),
            }
        )
        response = await self._client.post(FACE_RECOGNITION_PATH, json=request_payload)
        response.raise_for_status()
        value = response.json()
        if not isinstance(value, dict):
            raise ValueError("identity worker returned non-object JSON")
        return value

    async def models(self) -> dict[str, Any]:
        response = await self._client.get(MODELS_PATH)
        response.raise_for_status()
        value = response.json()
        if not isinstance(value, dict):
            raise ValueError("identity worker returned non-object models JSON")
        return value

    async def health(self) -> dict[str, Any]:
        response = await self._client.get("/health")
        response.raise_for_status()
        value = response.json()
        if not isinstance(value, dict):
            raise ValueError("identity worker returned non-object health JSON")
        return value

    async def close(self) -> None:
        await self._client.aclose()
