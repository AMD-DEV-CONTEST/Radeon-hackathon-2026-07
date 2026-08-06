from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


PatternKind = Literal["main", "subgraph"]
NodeType = Literal["reserved", "cognitive", "operational", "governance", "terminal", "sub_graph"]
StateMode = Literal["shared", "isolated"]
WrapperPhase = Literal["before", "after", "on_error"]


class PatternNodeWrapperSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    phase: WrapperPhase
    order: int = 0
    config: dict[str, Any] = Field(default_factory=dict)


class PatternNodeSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    type: NodeType
    impl: str
    pattern_ref: str | None = None
    config: dict[str, Any] = Field(default_factory=dict)
    wrappers: list[PatternNodeWrapperSpec] = Field(default_factory=list)


class PatternEdgeSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    from_: str = Field(alias="from")
    to: str
    when: str


class PatternTerminationSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    success_nodes: list[str] = Field(default_factory=list)
    failure_nodes: list[str] = Field(default_factory=list)


class PatternConstraintsSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    allowed_node_types: list[NodeType] = Field(default_factory=list)
    required_capabilities: list[str] = Field(default_factory=list)


class PatternIOContractSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    readable_sections: list[str] = Field(default_factory=list)
    writable_sections: list[str] = Field(default_factory=list)


PatternSlotType = Literal[
    "prompt",
    "tool",
    "resource",
    "state",
    "scheduler",
    "structured_output",
    "package_node",
    "artifact",
    "knowledge",
    "memory",
    "context",
]


class PatternSlotSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    slot_id: str
    slot_type: PatternSlotType
    node_id: str | None = None
    required: bool = True
    purpose: str
    expected_binding: str = ""
    output_target: str = ""
    notes: list[str] = Field(default_factory=list)


class PatternMetadataSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    summary: str = ""
    use_when: list[str] = Field(default_factory=list)
    avoid_when: list[str] = Field(default_factory=list)
    selection_notes: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)


class PatternCatalogItemSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    pattern_id: str
    kind: PatternKind
    embeddable: bool
    version: int
    name: str
    description: str
    metadata: PatternMetadataSpec = Field(default_factory=PatternMetadataSpec)


class PatternStructureNodeSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    node_id: str
    node_type: NodeType
    impl: str


class PatternStructureRouteSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    from_node: str
    to_node: str
    condition: str


class PatternStructureTerminationSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    success_nodes: list[str] = Field(default_factory=list)
    failure_nodes: list[str] = Field(default_factory=list)


class PatternStructureSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    pattern_id: str
    kind: PatternKind
    name: str
    description: str
    entry_node: str
    nodes: list[PatternStructureNodeSummary] = Field(default_factory=list)
    routes: list[PatternStructureRouteSummary] = Field(default_factory=list)
    slots: list[PatternSlotSpec] = Field(default_factory=list)
    interrupt_points: list[str] = Field(default_factory=list)
    termination: PatternStructureTerminationSummary


class GraphPatternSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    pattern_id: str
    kind: PatternKind
    embeddable: bool
    version: int
    name: str
    description: str
    metadata: PatternMetadataSpec = Field(default_factory=PatternMetadataSpec)
    entry_node: str
    nodes: list[PatternNodeSpec] = Field(default_factory=list)
    edges: list[PatternEdgeSpec] = Field(default_factory=list)
    interrupt_points: list[str] = Field(default_factory=list)
    termination: PatternTerminationSpec
    constraints: PatternConstraintsSpec = Field(default_factory=PatternConstraintsSpec)
    input_contract: PatternIOContractSpec = Field(default_factory=PatternIOContractSpec)
    output_contract: PatternIOContractSpec = Field(default_factory=PatternIOContractSpec)
    slots: list[PatternSlotSpec] = Field(default_factory=list)
    exit_routes: list[str] = Field(default_factory=list)
    state_mode: StateMode = "shared"
