from __future__ import annotations

from agent_factory.assembly.schema import AgentAssemblySpec
from agent_factory.runtime_kernel.errors import RuntimeKernelError
from agent_factory.runtime_kernel.patterns.registry import PatternRegistry
from agent_factory.runtime_kernel.wrappers import DEFAULT_NODE_WRAPPER_REGISTRY, NodeWrapperRegistry


class AgentAssemblyValidationError(RuntimeKernelError):
    """Raised when an AgentAssemblySpec cannot be compiled safely."""


class AgentAssemblyValidator:
    def __init__(
        self,
        *,
        pattern_registry: PatternRegistry,
        wrapper_registry: NodeWrapperRegistry | None = None,
    ) -> None:
        self.pattern_registry = pattern_registry
        self.wrapper_registry = wrapper_registry or DEFAULT_NODE_WRAPPER_REGISTRY

    def validate(self, spec: AgentAssemblySpec) -> AgentAssemblySpec:
        if spec.schema_version != "0.1":
            raise AgentAssemblyValidationError(f"Unsupported assembly schema_version: {spec.schema_version}")
        if not spec.agent.id.strip():
            raise AgentAssemblyValidationError("agent.id must not be empty.")
        base_pattern = self.pattern_registry.get(spec.runtime.pattern_id)
        node_ids = {node.id for node in base_pattern.nodes}
        for override in spec.graph_overrides.node_wrappers:
            if override.node_id not in node_ids:
                raise AgentAssemblyValidationError(
                    f"graph_overrides.node_wrappers references unknown node_id: {override.node_id}"
                )
            for wrapper in override.wrappers:
                try:
                    self.wrapper_registry.validate_spec(wrapper)
                except Exception as exc:
                    raise AgentAssemblyValidationError(
                        f"Invalid wrapper {wrapper.id} on node {override.node_id}: {exc}"
                    ) from exc
        tool_ids = [tool.id for tool in spec.tools]
        if len(tool_ids) != len(set(tool_ids)):
            raise AgentAssemblyValidationError("tools[].id must be unique.")
        return spec
