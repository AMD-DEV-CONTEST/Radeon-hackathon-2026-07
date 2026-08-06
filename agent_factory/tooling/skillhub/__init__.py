"""SkillHUB host-side service integration."""

from __future__ import annotations

import importlib
from typing import TYPE_CHECKING, Any

from agent_factory.tooling.skillhub.constants import SKILLHUB_RUNTIME_RESOURCE

_LAZY_EXPORTS: dict[str, str] = {
    "SkillHubService": "agent_factory.tooling.skillhub.service",
    "build_skillhub_runtime_resource": "agent_factory.tooling.skillhub.runtime_resource",
    "ensure_global_skillhub_cli": "agent_factory.tooling.skillhub.service",
}


def __getattr__(name: str) -> Any:
    module_name = _LAZY_EXPORTS.get(name)
    if module_name is None:
        raise AttributeError(name)
    value = getattr(importlib.import_module(module_name), name)
    globals()[name] = value
    return value


if TYPE_CHECKING:
    from agent_factory.tooling.skillhub.runtime_resource import build_skillhub_runtime_resource
    from agent_factory.tooling.skillhub.service import SkillHubService, ensure_global_skillhub_cli


__all__ = [
    "SKILLHUB_RUNTIME_RESOURCE",
    "SkillHubService",
    "build_skillhub_runtime_resource",
    "ensure_global_skillhub_cli",
]
