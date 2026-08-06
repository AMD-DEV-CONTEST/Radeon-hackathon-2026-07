from __future__ import annotations

from agent_factory.runtime_contracts.builtins.builders import (
    ArtifactContractBuilder,
    ContextContractBuilder,
    DependenciesContractBuilder,
    ModelContractBuilder,
    NodeProviderContractBuilder,
    ResourcesContractBuilder,
    SchedulerContractBuilder,
    SchedulerSeedContractBuilder,
    ToolsContractBuilder,
    TraceContractBuilder,
)
from agent_factory.runtime_contracts.builtins.defaults import (
    default_context_contract,
    default_dependencies_contract,
    default_model_contract,
    default_resources_contract,
    default_scheduler_contract,
    default_scheduler_seed_contract,
    default_tools_contract,
)
from agent_factory.runtime_contracts.registry import RuntimeContractRegistry
from agent_factory.runtime_contracts.schema import (
    ArtifactContract,
    ContextContract,
    DependenciesContract,
    ModelContract,
    NodeProviderContract,
    ResourcesContract,
    SchedulerContract,
    SchedulerSeedContract,
    ToolsContract,
    TraceContract,
)
from agent_factory.runtime_kernel.node_providers import NodeProviderRegistry, PackageNodeProviderFactory


def default_runtime_contract_registry(
    *,
    node_provider_registry: NodeProviderRegistry | None = None,
) -> RuntimeContractRegistry:
    if node_provider_registry is None:
        node_provider_registry = NodeProviderRegistry([])
    if not node_provider_registry.has_factory("builtin.package_nodes"):
        node_provider_registry.register_factory(PackageNodeProviderFactory())
    registry = RuntimeContractRegistry()
    registry.register(
        contract_type="tools",
        version="tools_contract.v0",
        model=ToolsContract,
        builder=ToolsContractBuilder(),
    )
    registry.register(
        contract_type="context",
        version="context_contract.v1",
        model=ContextContract,
        builder=ContextContractBuilder(),
    )
    registry.register(
        contract_type="trace",
        version="trace_contract.v0",
        model=TraceContract,
        builder=TraceContractBuilder(),
    )
    registry.register(
        contract_type="model",
        version="model_contract.v1",
        model=ModelContract,
        builder=ModelContractBuilder(),
    )
    registry.register(
        contract_type="node_provider",
        version="node_provider_contract.v0",
        model=NodeProviderContract,
        builder=NodeProviderContractBuilder(provider_registry=node_provider_registry),
    )
    registry.register(
        contract_type="artifact",
        version="artifact_contract.v0",
        model=ArtifactContract,
        builder=ArtifactContractBuilder(),
    )
    registry.register(
        contract_type="resources",
        version="resources_contract.v0",
        model=ResourcesContract,
        builder=ResourcesContractBuilder(),
    )
    registry.register(
        contract_type="scheduler",
        version="scheduler_contract.v0",
        model=SchedulerContract,
        builder=SchedulerContractBuilder(),
    )
    registry.register(
        contract_type="scheduler_seed",
        version="scheduler_seed_contract.v0",
        model=SchedulerSeedContract,
        builder=SchedulerSeedContractBuilder(),
    )
    registry.register(
        contract_type="dependencies",
        version="dependencies_contract.v1",
        model=DependenciesContract,
        builder=DependenciesContractBuilder(),
    )
    return registry


__all__ = [
    "default_context_contract",
    "default_dependencies_contract",
    "default_model_contract",
    "default_resources_contract",
    "default_runtime_contract_registry",
    "default_scheduler_contract",
    "default_scheduler_seed_contract",
    "default_tools_contract",
]
