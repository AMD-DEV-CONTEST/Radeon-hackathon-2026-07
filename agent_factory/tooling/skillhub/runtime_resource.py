from __future__ import annotations

from pathlib import Path
from typing import Any

from agent_factory.skillhub_gateway.client import SkillHubGatewayClient
from agent_factory.skillhub_gateway.manager import configured_local_skillhub_gateway_url
from agent_factory.tooling.skillhub.service import SkillHubService
from agent_factory.tooling.skillhub.constants import SKILLHUB_RUNTIME_RESOURCE


def build_skillhub_runtime_resource(extension_root: str | Path | None) -> Any | None:
    gateway_url = configured_local_skillhub_gateway_url()
    if gateway_url:
        return SkillHubGatewayClient(base_url=gateway_url)
    if extension_root is None:
        return None
    return SkillHubService(extension_root=extension_root)
