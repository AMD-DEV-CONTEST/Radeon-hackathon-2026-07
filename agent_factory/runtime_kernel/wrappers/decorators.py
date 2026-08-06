from __future__ import annotations

from collections.abc import Callable

from pydantic import BaseModel

from agent_factory.runtime_kernel.wrappers.base import NodeWrapper, WrapperPhase
from agent_factory.runtime_kernel.wrappers.registry import register_node_wrapper


def wrap_node(
    wrapper_id: str,
    *,
    phases: set[WrapperPhase] | None = None,
    reads: set[str] | None = None,
    writes: set[str] | None = None,
    config_schema: type[BaseModel] | None = None,
    description: str | None = None,
) -> Callable[[type[NodeWrapper]], type[NodeWrapper]]:
    def decorator(wrapper_cls: type[NodeWrapper]) -> type[NodeWrapper]:
        return register_node_wrapper(
            wrapper_cls,
            wrapper_id=wrapper_id,
            phases=phases,
            reads=reads,
            writes=writes,
            config_schema=config_schema,
            description=description,
        )

    return decorator
