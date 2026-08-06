from __future__ import annotations

from agent_factory.runtime_kernel.errors import RuntimeKernelError
from agent_factory.runtime_kernel.nodes.base import NodeImplementation


class NodeRegistry:
    def __init__(self) -> None:
        self._implementations: dict[str, NodeImplementation] = {}

    def register(self, implementation: NodeImplementation) -> None:
        if implementation.impl_id in self._implementations:
            raise RuntimeKernelError(f"Duplicate node implementation: {implementation.impl_id}")
        self._implementations[implementation.impl_id] = implementation

    def get(self, impl_id: str) -> NodeImplementation:
        if impl_id not in self._implementations:
            raise RuntimeKernelError(f"Unknown node implementation: {impl_id}")
        return self._implementations[impl_id]

    def has(self, impl_id: str) -> bool:
        return impl_id in self._implementations

    def list_impl_ids(self) -> list[str]:
        return sorted(self._implementations)
