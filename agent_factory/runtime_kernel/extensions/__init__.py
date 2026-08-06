from __future__ import annotations

import importlib
from typing import Any


__all__ = [
    "AgentInstanceExtensionConfigBundle",
    "AgentInstanceExtensionConfigLoader",
    "AgentInstanceExtensionLoadReport",
    "AgentInstanceExtensionManager",
    "AgentInstanceExtensionSources",
]


def __getattr__(name: str) -> Any:
    if name == "AgentInstanceExtensionConfigLoader":
        return importlib.import_module("agent_factory.runtime_kernel.extensions.loader").AgentInstanceExtensionConfigLoader
    if name == "AgentInstanceExtensionManager":
        return importlib.import_module("agent_factory.runtime_kernel.extensions.manager").AgentInstanceExtensionManager
    if name in {
        "AgentInstanceExtensionConfigBundle",
        "AgentInstanceExtensionLoadReport",
        "AgentInstanceExtensionSources",
    }:
        return getattr(importlib.import_module("agent_factory.runtime_kernel.extensions.schema"), name)
    raise AttributeError(name)
