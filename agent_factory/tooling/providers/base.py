from __future__ import annotations

from pathlib import Path
from typing import Any, Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field

from agent_factory.tooling.spec import ToolSpec


ProviderDiagnosticLevel = Literal["info", "warning", "error"]


class PromptFragment(BaseModel):
    model_config = ConfigDict(extra="forbid")

    fragment_id: str
    content: str
    source: str = ""


class ResourceRequirementHint(BaseModel):
    model_config = ConfigDict(extra="forbid")

    key: str
    description: str
    required: bool = True
    source: str = ""


class RuntimeDependency(BaseModel):
    model_config = ConfigDict(extra="forbid")

    dependency_id: str
    kind: Literal["mcp_server", "skill_runtime", "python_package", "system_package", "other"]
    required: bool = True
    details: dict[str, Any] = Field(default_factory=dict)


class ProviderDiagnostic(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provider_id: str
    level: ProviderDiagnosticLevel
    message: str
    details: dict[str, Any] = Field(default_factory=dict)


class ToolProviderContext(BaseModel):
    model_config = ConfigDict(extra="forbid", arbitrary_types_allowed=True)

    package_root: Path | None = None
    extension_root: Path | None = None
    resources: dict[str, Any] = Field(default_factory=dict)


class ToolProviderResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tool_specs: list[ToolSpec] = Field(default_factory=list)
    system_tool_ids: list[str] = Field(default_factory=list)
    prompt_fragments: list[PromptFragment] = Field(default_factory=list)
    resource_requirements: list[ResourceRequirementHint] = Field(default_factory=list)
    runtime_dependencies: list[RuntimeDependency] = Field(default_factory=list)
    runtime_resources: dict[str, Any] = Field(default_factory=dict)
    diagnostics: list[ProviderDiagnostic] = Field(default_factory=list)

    def merge(self, other: "ToolProviderResult") -> "ToolProviderResult":
        return ToolProviderResult(
            tool_specs=[*self.tool_specs, *other.tool_specs],
            system_tool_ids=_unique([*self.system_tool_ids, *other.system_tool_ids]),
            prompt_fragments=[*self.prompt_fragments, *other.prompt_fragments],
            resource_requirements=[*self.resource_requirements, *other.resource_requirements],
            runtime_dependencies=[*self.runtime_dependencies, *other.runtime_dependencies],
            runtime_resources={**self.runtime_resources, **other.runtime_resources},
            diagnostics=[*self.diagnostics, *other.diagnostics],
        )


class ToolProvider(Protocol):
    provider_id: str

    def discover(self, context: ToolProviderContext) -> ToolProviderResult:
        ...


def diagnostic(provider_id: str, level: ProviderDiagnosticLevel, message: str, **details: Any) -> ProviderDiagnostic:
    return ProviderDiagnostic(provider_id=provider_id, level=level, message=message, details=details)


def _unique(values: list[str]) -> list[str]:
    items: list[str] = []
    seen: set[str] = set()
    for value in values:
        item = str(value).strip()
        if item and item not in seen:
            items.append(item)
            seen.add(item)
    return items
