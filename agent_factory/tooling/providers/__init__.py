"""Tool provider public exports.

Provider modules depend on different parts of the tooling stack. Keep this
package root lazy so importing one provider configuration model does not
initialize every provider implementation.
"""

from __future__ import annotations

import importlib
from typing import TYPE_CHECKING, Any

_EXPORT_MODULES: dict[str, str] = {
    "BuiltinToolProvider": "agent_factory.tooling.providers.builtin",
    "EnabledSkillConfig": "agent_factory.tooling.providers.skill",
    "EnabledSkillsConfig": "agent_factory.tooling.providers.skill",
    "MCPDiscoveredTool": "agent_factory.tooling.providers.mcp",
    "MCPServerConfig": "agent_factory.tooling.providers.mcp",
    "MCPServersConfig": "agent_factory.tooling.providers.mcp",
    "MCPToolCatalogClient": "agent_factory.tooling.providers.mcp",
    "MCPToolProvider": "agent_factory.tooling.providers.mcp",
    "PreparedMCPTool": "agent_factory.tooling.providers.mcp",
    "PackageToolProvider": "agent_factory.tooling.providers.package",
    "PromptFragment": "agent_factory.tooling.providers.base",
    "ProviderDiagnostic": "agent_factory.tooling.providers.base",
    "ResourceRequirementHint": "agent_factory.tooling.providers.base",
    "RuntimeDependency": "agent_factory.tooling.providers.base",
    "SkillMetadata": "agent_factory.tooling.skills",
    "SkillProvider": "agent_factory.tooling.providers.skill",
    "ToolProvider": "agent_factory.tooling.providers.base",
    "ToolProviderContext": "agent_factory.tooling.providers.base",
    "ToolProviderResult": "agent_factory.tooling.providers.base",
    "prepare_mcp_tool": "agent_factory.tooling.providers.mcp",
}


def __getattr__(name: str) -> Any:
    module_name = _EXPORT_MODULES.get(name)
    if module_name is None:
        raise AttributeError(name)
    value = getattr(importlib.import_module(module_name), name)
    globals()[name] = value
    return value


if TYPE_CHECKING:
    from agent_factory.tooling.providers.base import (
        PromptFragment,
        ProviderDiagnostic,
        ResourceRequirementHint,
        RuntimeDependency,
        ToolProvider,
        ToolProviderContext,
        ToolProviderResult,
    )
    from agent_factory.tooling.providers.builtin import BuiltinToolProvider
    from agent_factory.tooling.providers.mcp import (
        MCPDiscoveredTool,
        MCPServerConfig,
        MCPServersConfig,
        MCPToolCatalogClient,
        MCPToolProvider,
        PreparedMCPTool,
        prepare_mcp_tool,
    )
    from agent_factory.tooling.providers.package import PackageToolProvider
    from agent_factory.tooling.providers.skill import EnabledSkillConfig, EnabledSkillsConfig, SkillProvider
    from agent_factory.tooling.skills import SkillMetadata


__all__ = sorted(_EXPORT_MODULES)
