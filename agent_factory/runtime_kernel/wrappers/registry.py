from __future__ import annotations

from pydantic import BaseModel

from agent_factory.runtime_kernel.errors import RuntimeKernelError
from agent_factory.runtime_kernel.patterns.schema import PatternNodeWrapperSpec
from agent_factory.runtime_kernel.wrappers.base import NodeWrapper, WrapperPhase


class NodeWrapperRegistry:
    def __init__(self) -> None:
        self._wrappers: dict[str, type[NodeWrapper]] = {}

    def register(self, wrapper_cls: type[NodeWrapper]) -> None:
        wrapper_id = getattr(wrapper_cls, "wrapper_id", "")
        if not wrapper_id:
            raise RuntimeKernelError("Node wrapper must define wrapper_id.")
        self._wrappers[wrapper_id] = wrapper_cls

    def get(self, wrapper_id: str) -> type[NodeWrapper]:
        wrapper_cls = self._wrappers.get(wrapper_id)
        if wrapper_cls is None:
            raise RuntimeKernelError(f"Unknown node wrapper: {wrapper_id}")
        return wrapper_cls

    def has(self, wrapper_id: str) -> bool:
        return wrapper_id in self._wrappers

    def list_wrapper_ids(self) -> list[str]:
        return sorted(self._wrappers)

    def validate_spec(self, spec: PatternNodeWrapperSpec) -> None:
        wrapper_cls = self.get(spec.id)
        if spec.phase not in wrapper_cls.supported_phases:
            raise RuntimeKernelError(f"Node wrapper {spec.id} does not support phase: {spec.phase}")
        if wrapper_cls.config_schema is not None:
            wrapper_cls.config_schema.model_validate(spec.config)

    def create(self, spec: PatternNodeWrapperSpec) -> NodeWrapper:
        self.validate_spec(spec)
        return self.get(spec.id)()


DEFAULT_NODE_WRAPPER_REGISTRY = NodeWrapperRegistry()


def register_node_wrapper(
    wrapper_cls: type[NodeWrapper],
    *,
    wrapper_id: str,
    phases: set[WrapperPhase] | None = None,
    reads: set[str] | None = None,
    writes: set[str] | None = None,
    config_schema: type[BaseModel] | None = None,
    description: str | None = None,
) -> type[NodeWrapper]:
    wrapper_cls.wrapper_id = wrapper_id
    if phases is not None:
        wrapper_cls.supported_phases = set(phases)
    if reads is not None:
        wrapper_cls.readable_sections = set(reads)
    if writes is not None:
        wrapper_cls.writable_sections = set(writes)
    if config_schema is not None:
        wrapper_cls.config_schema = config_schema
    if description is not None:
        wrapper_cls.description = description
    DEFAULT_NODE_WRAPPER_REGISTRY.register(wrapper_cls)
    return wrapper_cls
