from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from agent_factory.tooling.providers import (
    EnabledSkillsConfig,
    MCPServersConfig,
    ProviderDiagnostic,
)


class AgentInstanceExtensionSources(BaseModel):
    model_config = ConfigDict(extra="forbid", arbitrary_types_allowed=True)

    extension_root: Path
    extension_roots: list[Path] = Field(default_factory=list)
    mcp_servers_path: Path | None = None
    mcp_servers_paths: list[Path] = Field(default_factory=list)
    enabled_skills_path: Path | None = None
    enabled_skills_paths: list[Path] = Field(default_factory=list)


class AgentInstanceExtensionConfigBundle(BaseModel):
    model_config = ConfigDict(extra="forbid", arbitrary_types_allowed=True)

    sources: AgentInstanceExtensionSources
    mcp_servers: MCPServersConfig = Field(default_factory=MCPServersConfig)
    enabled_skills: EnabledSkillsConfig = Field(default_factory=EnabledSkillsConfig)


class AgentInstanceExtensionLoadReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: str = "agent_instance_extension_load.v0"
    extension_root: str
    extension_roots: list[str] = Field(default_factory=list)
    mcp_servers_path: str | None = None
    mcp_servers_paths: list[str] = Field(default_factory=list)
    enabled_skills_path: str | None = None
    enabled_skills_paths: list[str] = Field(default_factory=list)
    tool_ids: list[str] = Field(default_factory=list)
    system_tool_ids: list[str] = Field(default_factory=list)
    prompt_fragment_ids: list[str] = Field(default_factory=list)
    runtime_dependency_ids: list[str] = Field(default_factory=list)
    diagnostics: list[ProviderDiagnostic] = Field(default_factory=list)
