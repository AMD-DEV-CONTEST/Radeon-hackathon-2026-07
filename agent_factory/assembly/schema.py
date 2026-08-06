from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from agent_factory.runtime_kernel.bindings import BindingSet
from agent_factory.runtime_kernel.harness import HarnessScenario
from agent_factory.runtime_kernel.patterns.schema import PatternNodeWrapperSpec
from agent_factory.runtime_contracts.schema import AgentIdentitySpec as AgentSpec
from agent_factory.tooling.spec import ToolSpec


OutputFormat = Literal["text", "json", "markdown"]


class RuntimeSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    pattern_id: str
    compiled_pattern_id: str | None = None
    user_config: dict[str, Any] = Field(default_factory=dict)
    agent_config: dict[str, Any] = Field(default_factory=dict)


class NodeWrapperOverride(BaseModel):
    model_config = ConfigDict(extra="forbid")

    node_id: str
    replace_existing: bool = False
    wrappers: list[PatternNodeWrapperSpec] = Field(default_factory=list)


class GraphOverrides(BaseModel):
    model_config = ConfigDict(extra="forbid")

    node_wrappers: list[NodeWrapperOverride] = Field(default_factory=list)


class OutputSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    citations_required: bool = False
    format: OutputFormat = "text"


class AgentAssemblySpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = "0.1"
    agent: AgentSpec
    runtime: RuntimeSpec
    graph_overrides: GraphOverrides = Field(default_factory=GraphOverrides)
    bindings: BindingSet = Field(default_factory=BindingSet)
    tools: list[ToolSpec] = Field(default_factory=list)
    output: OutputSpec = Field(default_factory=OutputSpec)
    harness: list[HarnessScenario] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class AssemblyRunReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    assembly_id: str
    agent_id: str
    status: Literal["passed", "failed"]
    scenario_results: list[dict[str, Any]] = Field(default_factory=list)
    errors: list[dict[str, str]] = Field(default_factory=list)
