from __future__ import annotations

from abc import ABC
from typing import Any, ClassVar, Literal

from pydantic import BaseModel, ConfigDict, Field

from agent_factory.runtime_kernel.nodes.base import NodeExecutionContext
from agent_factory.runtime_kernel.state import RuntimeState


WrapperPhase = Literal["before", "after", "on_error"]


class NodeWrapperConfig(BaseModel):
    model_config = ConfigDict(extra="allow")


class NodeWrapperResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    patch: dict[str, Any] = Field(default_factory=dict)


class NodeWrapper(ABC):
    wrapper_id: ClassVar[str]
    supported_phases: ClassVar[set[WrapperPhase]] = {"before", "after", "on_error"}
    readable_sections: ClassVar[set[str]] = set()
    writable_sections: ClassVar[set[str]] = set()
    config_schema: ClassVar[type[BaseModel] | None] = None
    description: ClassVar[str | None] = None

    def before(
        self,
        *,
        state: RuntimeState,
        context: NodeExecutionContext,
        config: dict[str, Any],
    ) -> dict[str, Any]:
        return {}

    def after(
        self,
        *,
        state: RuntimeState,
        context: NodeExecutionContext,
        config: dict[str, Any],
        node_result: dict[str, Any],
    ) -> dict[str, Any]:
        return {}

    def on_error(
        self,
        *,
        state: RuntimeState,
        context: NodeExecutionContext,
        config: dict[str, Any],
        error: Exception,
    ) -> dict[str, Any]:
        return {}
