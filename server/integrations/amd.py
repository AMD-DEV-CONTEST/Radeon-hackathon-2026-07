"""AMD API client stub for future hardware / inference integrations."""

from __future__ import annotations

from typing import Any

from core.config import settings
from core.logger import get_logger

logger = get_logger(__name__)


class AMDClient:
    """No-op AMD API client placeholder."""

    def __init__(self, base_url: str | None = None, api_key: str | None = None) -> None:
        self.base_url = base_url or getattr(settings, "amd_api_base_url", None)
        self.api_key = api_key or getattr(settings, "amd_api_key", None)
        self.enabled = bool(getattr(settings, "amd_api_enabled", False))

    async def health(self) -> dict[str, Any]:
        return {"status": "disabled", "enabled": self.enabled}

    async def invoke(self, *, endpoint: str, payload: dict[str, Any]) -> dict[str, Any]:
        _ = (endpoint, payload)
        raise NotImplementedError("AMD API client stub — not implemented yet")


_amd_client: AMDClient | None = None


def get_amd_client() -> AMDClient:
    global _amd_client
    if _amd_client is None:
        _amd_client = AMDClient()
        if not _amd_client.enabled:
            logger.debug("AMD API integration disabled (stub client active)")
    return _amd_client
