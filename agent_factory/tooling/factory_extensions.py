from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Literal, Mapping

from pydantic import BaseModel, ConfigDict, Field

from agent_factory.paths import project_root
from agent_factory.runtime_kernel.extensions.schema import (
    AgentInstanceExtensionConfigBundle,
    AgentInstanceExtensionSources,
)
from agent_factory.tooling.entrypoints import MCPToolClient
from agent_factory.tooling.extension_registry import (
    default_extension_registry_root,
    load_registered_mcp_servers,
    load_resolved_registered_skills,
    registry_mcp_path,
    registry_skills_path,
    selected_registry_configs,
)
from agent_factory.tooling.mcp_runtime import MCPRuntimeManager
from agent_factory.tooling.providers import (
    MCPToolCatalogClient,
    MCPToolProvider,
    SkillProvider,
    ToolProviderContext,
    ToolProviderResult,
)


FACTORY_EXTENSION_ROOT_ENV = "AGENTFACTORY_FACTORY_EXTENSION_ROOT"
SystemAgentExtensionOwner = Literal["factory_chat", "create_agent", "evolve_agent"]


class FactoryExtensionLoadReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: str = "factory_extension_load.v0"
    extension_root: str
    builtin_extension_root: str | None = None
    extension_roots: list[str] = Field(default_factory=list)
    mcp_servers_path: str | None = None
    mcp_servers_paths: list[str] = Field(default_factory=list)
    enabled_skills_path: str | None = None
    enabled_skills_paths: list[str] = Field(default_factory=list)
    tool_ids: list[str] = Field(default_factory=list)
    system_tool_ids: list[str] = Field(default_factory=list)
    prompt_fragment_ids: list[str] = Field(default_factory=list)
    runtime_dependency_ids: list[str] = Field(default_factory=list)
    diagnostics: list[dict[str, Any]] = Field(default_factory=list)


class FactoryExtensionManager:
    def __init__(
        self,
        *,
        extension_root: str | Path | None = None,
        include_builtin_extension_root: bool | None = None,
        mcp_catalog_clients: Mapping[str, MCPToolCatalogClient] | None = None,
        mcp_tool_clients: Mapping[str, MCPToolClient] | None = None,
    ) -> None:
        explicit_extension_root = extension_root is not None
        self.extension_root = Path(extension_root).expanduser().resolve() if extension_root else default_factory_extension_root()
        include_builtin = (not explicit_extension_root) if include_builtin_extension_root is None else include_builtin_extension_root
        self.builtin_extension_root = default_builtin_factory_extension_root() if include_builtin else None
        self.loader = FactoryExtensionConfigLoader(
            extension_root=self.extension_root,
            builtin_extension_root=self.builtin_extension_root,
        )
        self.mcp_catalog_clients = dict(mcp_catalog_clients or {})
        self._configured_mcp_tool_clients = dict(mcp_tool_clients or {})
        self._effective_mcp_tool_clients: dict[str, MCPToolClient] = dict(mcp_tool_clients or {})

    def discover(self, context: ToolProviderContext | None = None) -> tuple[ToolProviderResult, FactoryExtensionLoadReport]:
        return self._discover_bundle(self.loader.load(), context=context)

    def discover_registry(
        self,
        context: ToolProviderContext | None = None,
    ) -> tuple[ToolProviderResult, FactoryExtensionLoadReport]:
        return self._discover_bundle(self.loader.load_registry(), context=context)

    def _discover_bundle(
        self,
        bundle: AgentInstanceExtensionConfigBundle,
        *,
        context: ToolProviderContext | None,
    ) -> tuple[ToolProviderResult, FactoryExtensionLoadReport]:
        mcp_runtime = MCPRuntimeManager(bundle.mcp_servers)
        catalog_clients = self.mcp_catalog_clients or mcp_runtime.clients()
        self._effective_mcp_tool_clients = self._configured_mcp_tool_clients or mcp_runtime.clients()
        provider_context = context or ToolProviderContext(extension_root=bundle.sources.extension_root)
        if provider_context.extension_root is None:
            provider_context = provider_context.model_copy(update={"extension_root": bundle.sources.extension_root})
        result = ToolProviderResult()
        result = result.merge(
            MCPToolProvider(config=bundle.mcp_servers, clients=catalog_clients).discover(provider_context)
        )
        result = result.merge(SkillProvider(config=bundle.enabled_skills).discover(provider_context))
        report = FactoryExtensionLoadReport(
            extension_root=str(bundle.sources.extension_root),
            builtin_extension_root=str(self.builtin_extension_root) if self.builtin_extension_root else None,
            extension_roots=[
                str(path)
                for path in (self.builtin_extension_root, self.extension_root)
                if path is not None and path.exists()
            ],
            mcp_servers_path=str(bundle.sources.mcp_servers_path) if bundle.sources.mcp_servers_path else None,
            mcp_servers_paths=[str(path) for path in _existing_paths([registry_mcp_path()])],
            enabled_skills_path=str(bundle.sources.enabled_skills_path) if bundle.sources.enabled_skills_path else None,
            enabled_skills_paths=[str(path) for path in _existing_paths([registry_skills_path()])],
            tool_ids=[tool.id for tool in result.tool_specs],
            system_tool_ids=list(result.system_tool_ids),
            prompt_fragment_ids=[fragment.fragment_id for fragment in result.prompt_fragments],
            runtime_dependency_ids=[dependency.dependency_id for dependency in result.runtime_dependencies],
            diagnostics=[diagnostic.model_dump(mode="json") for diagnostic in result.diagnostics],
        )
        return result, report

    def mcp_tool_clients(self) -> dict[str, MCPToolClient]:
        return dict(self._effective_mcp_tool_clients)


class FactoryExtensionConfigLoader:
    def __init__(
        self,
        *,
        extension_root: Path,
        builtin_extension_root: Path | None = None,
    ) -> None:
        self.extension_root = extension_root
        self.builtin_extension_root = builtin_extension_root

    def load(self) -> AgentInstanceExtensionConfigBundle:
        roots = [root for root in (self.builtin_extension_root, self.extension_root) if root is not None]
        mcp_servers, enabled_skills, _bindings = selected_registry_configs(roots)
        return self._bundle(
            roots=roots,
            mcp_servers=mcp_servers,
            enabled_skills=enabled_skills,
        )

    def load_registry(self) -> AgentInstanceExtensionConfigBundle:
        roots = [root for root in (self.builtin_extension_root, self.extension_root) if root is not None]
        return self._bundle(
            roots=roots,
            mcp_servers=load_registered_mcp_servers(),
            enabled_skills=load_resolved_registered_skills(),
        )

    def _bundle(
        self,
        *,
        roots: list[Path],
        mcp_servers: Any,
        enabled_skills: Any,
    ) -> AgentInstanceExtensionConfigBundle:
        registry_root = default_extension_registry_root()
        mcp_path = registry_mcp_path()
        skills_path = registry_skills_path()
        return AgentInstanceExtensionConfigBundle(
            sources=AgentInstanceExtensionSources(
                extension_root=self.extension_root,
                extension_roots=[*roots, registry_root],
                mcp_servers_path=mcp_path if mcp_path.is_file() else None,
                mcp_servers_paths=[mcp_path] if mcp_path.is_file() else [],
                enabled_skills_path=skills_path if skills_path.is_file() else None,
                enabled_skills_paths=[skills_path] if skills_path.is_file() else [],
            ),
            mcp_servers=mcp_servers,
            enabled_skills=enabled_skills,
        )

def _existing_paths(paths: list[Path | None]) -> list[Path]:
    return [path for path in paths if path is not None and path.is_file()]


def default_builtin_factory_extension_root() -> Path:
    return project_root() / "SystemPackage" / "extensions"


def default_factory_extension_root() -> Path:
    configured = os.getenv(FACTORY_EXTENSION_ROOT_ENV)
    if configured:
        return Path(configured).expanduser().resolve()
    return project_root() / ".agentfactory" / "factory" / "extensions"


def default_system_agent_extension_root(owner: SystemAgentExtensionOwner) -> Path:
    env_name = {
        "factory_chat": "AGENTFACTORY_FACTORY_CHAT_EXTENSION_ROOT",
        "create_agent": "AGENTFACTORY_CREATE_AGENT_EXTENSION_ROOT",
        "evolve_agent": "AGENTFACTORY_EVOLVE_AGENT_EXTENSION_ROOT",
    }[owner]
    configured = os.getenv(env_name)
    if configured:
        return Path(configured).expanduser().resolve()
    return project_root() / ".agentfactory" / "factory" / owner / "extensions"
