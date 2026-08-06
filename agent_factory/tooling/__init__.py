"""Unified ToolSpec-based tool system.

The package root intentionally keeps imports lazy. Importing a focused
submodule such as ``agent_factory.tooling.skillhub`` must not initialize the
compiler, providers, gateways, and built-in registry at the same time.
"""

from __future__ import annotations

import importlib
from typing import TYPE_CHECKING, Any

_EXPORT_MODULES: dict[str, str] = {
    "BuiltinToolProvider": "agent_factory.tooling.providers",
    "FACTORY_EXTENSION_ROOT_ENV": "agent_factory.tooling.factory_extensions",
    "FactoryExtensionLoadReport": "agent_factory.tooling.factory_extensions",
    "FactoryExtensionManager": "agent_factory.tooling.factory_extensions",
    "MCPRuntimeClient": "agent_factory.tooling.mcp_runtime",
    "MCPRuntimeError": "agent_factory.tooling.mcp_runtime",
    "MCPRuntimeManager": "agent_factory.tooling.mcp_runtime",
    "MCPToolProvider": "agent_factory.tooling.providers",
    "ModelToolView": "agent_factory.tooling.spec",
    "PackageToolProvider": "agent_factory.tooling.providers",
    "SkillMetadata": "agent_factory.tooling.providers",
    "SkillProvider": "agent_factory.tooling.providers",
    "ToolCompiler": "agent_factory.tooling.compiler",
    "ToolEntrypointLoader": "agent_factory.tooling.entrypoint",
    "ToolEventPayload": "agent_factory.tooling.spec",
    "ToolExecutionGateway": "agent_factory.tooling.gateway",
    "ToolObservation": "agent_factory.tooling.spec",
    "ToolProviderContext": "agent_factory.tooling.providers",
    "ToolProviderResult": "agent_factory.tooling.providers",
    "ToolRegistry": "agent_factory.tooling.registry",
    "ToolRiskEvaluatorConfig": "agent_factory.tooling.spec",
    "ToolRiskResult": "agent_factory.tooling.spec",
    "ToolSpec": "agent_factory.tooling.spec",
    "compile_json_schema": "agent_factory.tooling.schema_compiler",
    "default_builtin_factory_extension_root": "agent_factory.tooling.factory_extensions",
    "default_factory_extension_root": "agent_factory.tooling.factory_extensions",
    "get_factory_base_tool_ids": "agent_factory.tooling.registry",
    "get_factory_model_tools": "agent_factory.tooling.registry",
    "get_factory_protected_tool_ids": "agent_factory.tooling.registry",
    "get_factory_tool_specs": "agent_factory.tooling.registry",
    "get_factory_tools": "agent_factory.tooling.registry",
}


def __getattr__(name: str) -> Any:
    module_name = _EXPORT_MODULES.get(name)
    if module_name is None:
        raise AttributeError(name)
    value = getattr(importlib.import_module(module_name), name)
    globals()[name] = value
    return value


if TYPE_CHECKING:
    from agent_factory.tooling.compiler import ToolCompiler
    from agent_factory.tooling.entrypoint import ToolEntrypointLoader
    from agent_factory.tooling.factory_extensions import (
        FACTORY_EXTENSION_ROOT_ENV,
        FactoryExtensionLoadReport,
        FactoryExtensionManager,
        default_builtin_factory_extension_root,
        default_factory_extension_root,
    )
    from agent_factory.tooling.gateway import ToolExecutionGateway
    from agent_factory.tooling.mcp_runtime import MCPRuntimeClient, MCPRuntimeError, MCPRuntimeManager
    from agent_factory.tooling.providers import (
        BuiltinToolProvider,
        MCPToolProvider,
        PackageToolProvider,
        SkillMetadata,
        SkillProvider,
        ToolProviderContext,
        ToolProviderResult,
    )
    from agent_factory.tooling.registry import (
        ToolRegistry,
        get_factory_base_tool_ids,
        get_factory_model_tools,
        get_factory_protected_tool_ids,
        get_factory_tool_specs,
        get_factory_tools,
    )
    from agent_factory.tooling.schema_compiler import compile_json_schema
    from agent_factory.tooling.spec import (
        ModelToolView,
        ToolEventPayload,
        ToolObservation,
        ToolRiskEvaluatorConfig,
        ToolRiskResult,
        ToolSpec,
    )


__all__ = sorted(_EXPORT_MODULES)
