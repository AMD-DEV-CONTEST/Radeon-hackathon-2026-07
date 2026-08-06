from __future__ import annotations

from collections.abc import Callable
from typing import Any, Protocol

from pydantic import BaseModel, ConfigDict, Field

from agent_factory.runtime_kernel.bindings.services import RuntimeServices
from agent_factory.runtime_kernel.state import RuntimeState
from agent_factory.runtime_render import NodeRenderSpec


class NodeExecutionContext(BaseModel):
    model_config = ConfigDict(extra="forbid", arbitrary_types_allowed=True)

    node_id: str
    impl: str
    bindings: list[dict[str, Any]] = Field(default_factory=list)
    all_bindings: list[dict[str, Any]] = Field(default_factory=list)
    hook_bindings: list[dict[str, Any]] = Field(default_factory=list)
    services: RuntimeServices
    emit_event: Callable[[dict[str, Any]], None]
    render_spec: NodeRenderSpec | None = None
    graph_messages: list[Any] = Field(default_factory=list)
    graph_config: Any | None = None
    graph_runtime: Any | None = None


class NodeImplementation(Protocol):
    impl_id: str
    node_type: str
    supports_interrupt: bool
    supports_subgraph_slot: bool
    writable_sections: set[str]

    def execute(
        self,
        state: RuntimeState,
        context: NodeExecutionContext,
    ) -> dict[str, Any]:
        ...
