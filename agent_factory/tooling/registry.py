from __future__ import annotations

from collections.abc import Iterable
import importlib
from pathlib import Path
from typing import Any, Mapping

from langchain_core.tools import BaseTool

from agent_factory.paths import factory_artifact_path, project_root
from agent_factory.tooling.compiler import ToolCompiler
from agent_factory.tooling.entrypoints import MCPToolClient
from agent_factory.tooling.output_store import TOOL_OUTPUT_STORE_RESOURCE, ToolOutputStore
from agent_factory.tooling.providers import MCPToolCatalogClient
from agent_factory.tooling.skillhub import SKILLHUB_RUNTIME_RESOURCE, build_skillhub_runtime_resource
from agent_factory.tooling.builtins.aliases import canonical_builtin_tool_ids
from agent_factory.tooling.builtins.registry import (
    get_always_available_system_tool_ids,
    get_builtin_protected_tool_ids,
    get_builtin_tool_ids,
    get_builtin_tool_specs,
)
from agent_factory.tooling.spec import ModelToolView, ToolSpec, model_tool_view
from agent_factory.scheduler_system import scheduler_enabled_from_env


class ToolRegistry:
    def __init__(self, tools: Iterable[ToolSpec] | None = None) -> None:
        self._tools: dict[str, ToolSpec] = {}
        for tool in tools or []:
            self.register(tool)

    def register(self, tool: ToolSpec) -> None:
        if tool.id in self._tools:
            raise ValueError(f"duplicate tool id: {tool.id}")
        self._tools[tool.id] = tool

    def get(self, tool_id: str) -> ToolSpec:
        try:
            return self._tools[tool_id]
        except KeyError as exc:
            raise KeyError(f"unknown tool id: {tool_id}") from exc

    def all(self) -> list[ToolSpec]:
        return list(self._tools.values())

    def ids(self) -> list[str]:
        return list(self._tools.keys())

    def model_views(self) -> list[ModelToolView]:
        return [model_tool_view(tool) for tool in self._tools.values()]


def get_factory_tools(
    tool_ids: Iterable[str] | None = None,
    *,
    include_extensions: bool = True,
    extension_root: str | Path | None = None,
    mcp_catalog_clients: Mapping[str, MCPToolCatalogClient] | None = None,
    mcp_tool_clients: Mapping[str, MCPToolClient] | None = None,
    runtime_resources: Mapping[str, Any] | None = None,
    tool_runtime_resources: Mapping[str, Any] | None = None,
) -> list[BaseTool]:
    selected_ids = set(canonical_builtin_tool_ids(tool_ids or []))
    base_runtime_resources = dict(runtime_resources or {})
    base_tool_runtime_resources = dict(tool_runtime_resources or {})
    specs, effective_mcp_clients, discovered_runtime_resources = _collect_factory_tool_specs(
        selected_ids=selected_ids,
        include_extensions=include_extensions,
        extension_root=extension_root,
        mcp_catalog_clients=mcp_catalog_clients,
        mcp_tool_clients=mcp_tool_clients,
        runtime_resources=base_runtime_resources,
        tool_runtime_resources=base_tool_runtime_resources,
    )
    effective_runtime_resources = _merge_runtime_resources(base_runtime_resources, discovered_runtime_resources)
    factory_extension_root = (
        Path(extension_root).expanduser().resolve()
        if extension_root
        else _factory_extensions_module().default_factory_extension_root()
    )
    compiler = ToolCompiler(
        allowed_python_roots=[factory_extension_root],
        mcp_clients=effective_mcp_clients,
        resources={
            "filesystem": {
                "root": str(_default_filesystem_root()),
                "allow_external": False,
            },
            "process_runtime": {
                "root": str(_default_filesystem_root()),
                "allow_external": False,
            },
            TOOL_OUTPUT_STORE_RESOURCE: ToolOutputStore(factory_artifact_path("tool_outputs")),
            **_factory_skillhub_resource(factory_extension_root),
            **effective_runtime_resources,
            **base_tool_runtime_resources,
        }
    )
    return compiler.compile_many(specs)


def get_factory_tool_specs(
    tool_ids: Iterable[str] | None = None,
    *,
    include_extensions: bool = True,
    extension_root: str | Path | None = None,
    mcp_catalog_clients: Mapping[str, MCPToolCatalogClient] | None = None,
) -> list[ToolSpec]:
    selected_ids = set(canonical_builtin_tool_ids(tool_ids or []))
    specs, _mcp_clients, _runtime_resources = _collect_factory_tool_specs(
        selected_ids=selected_ids,
        include_extensions=include_extensions,
        extension_root=extension_root,
        mcp_catalog_clients=mcp_catalog_clients,
        mcp_tool_clients=None,
        runtime_resources={},
        tool_runtime_resources={},
    )
    return specs


def _collect_factory_tool_specs(
    *,
    selected_ids: set[str],
    include_extensions: bool,
    extension_root: str | Path | None,
    mcp_catalog_clients: Mapping[str, MCPToolCatalogClient] | None,
    mcp_tool_clients: Mapping[str, MCPToolClient] | None,
    runtime_resources: Mapping[str, Any],
    tool_runtime_resources: Mapping[str, Any],
) -> tuple[list[ToolSpec], Mapping[str, MCPToolClient], dict[str, object]]:
    specs = get_builtin_tool_specs()
    if not scheduler_enabled_from_env() or "scheduler_runtime" not in tool_runtime_resources:
        specs = [spec for spec in specs if spec.id != "scheduler"]
    if "knowledge_runtime" not in tool_runtime_resources:
        specs = [spec for spec in specs if spec.id != "knowledge"]
    effective_mcp_clients: Mapping[str, MCPToolClient] = dict(mcp_tool_clients or {})
    discovered_runtime_resources: dict[str, object] = {}
    if include_extensions:
        manager = _factory_extensions_module().FactoryExtensionManager(
            extension_root=extension_root,
            mcp_catalog_clients=mcp_catalog_clients,
            mcp_tool_clients=mcp_tool_clients,
        )
        extension_result, _report = manager.discover()
        effective_mcp_clients = manager.mcp_tool_clients()
        discovered_runtime_resources.update(extension_result.runtime_resources)
        registry = ToolRegistry(specs)
        for spec in extension_result.tool_specs:
            if selected_ids and spec.id not in selected_ids:
                continue
            registry.register(spec)
        specs = registry.all()
    always_available = get_always_available_system_tool_ids()
    return [
        tool for tool in specs if not selected_ids or tool.id in selected_ids or tool.id in always_available
    ], effective_mcp_clients, discovered_runtime_resources


def get_factory_model_tools() -> list[BaseTool]:
    return get_factory_tools()


def get_factory_base_tool_ids() -> list[str]:
    return get_builtin_tool_ids()


def get_factory_protected_tool_ids() -> list[str]:
    return get_builtin_protected_tool_ids()


def _default_filesystem_root() -> Path:
    return project_root()


def _merge_runtime_resources(
    base: Mapping[str, Any],
    discovered: Mapping[str, object],
) -> dict[str, object]:
    merged: dict[str, object] = dict(base)
    for key, value in discovered.items():
        if key in merged and merged[key] is not value and merged[key] != value:
            raise ValueError(f"conflicting factory tool runtime resource: {key}")
        merged[key] = value
    return merged


def _factory_skillhub_resource(extension_root: Path) -> dict[str, object]:
    resource = build_skillhub_runtime_resource(extension_root)
    return {SKILLHUB_RUNTIME_RESOURCE: resource} if resource is not None else {}


def _factory_extensions_module():
    return importlib.import_module("agent_factory.tooling.factory_extensions")
