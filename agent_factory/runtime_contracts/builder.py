from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from pydantic import BaseModel

from agent_factory.runtime_contracts.contribution import RuntimeBuildResult, RuntimeContribution, RuntimeContributionMerger
from agent_factory.runtime_contracts.loader import LoadedAgentPackage
from agent_factory.runtime_contracts.registry import RuntimeContractRegistry
from agent_factory.runtime_contracts.schema import (
    ArtifactContract,
    REQUIRED_AGENT_PACKAGE_CONTRACTS,
    TraceContract,
)
from agent_factory.runtime_kernel.bindings import RuntimeServices
from agent_factory.runtime_kernel.wrappers.system_render import RENDER_NODE_SYSTEM_WRAPPER_ID


@dataclass(frozen=True, slots=True)
class RuntimeBuildContext:
    package_root: Path
    runtime_root: Path | None
    runtime_instance_id: str | None
    instance_extension_root: Path | None
    package: LoadedAgentPackage
    resources: dict[str, object]
    tool_runtime_resources: dict[str, object]


def runtime_build_context(
    package: LoadedAgentPackage,
    *,
    runtime_root: str | Path | None = None,
    runtime_instance_id: str | None = None,
    instance_extension_root: str | Path | None = None,
    resources: dict[str, object] | None = None,
    tool_runtime_resources: dict[str, object] | None = None,
) -> RuntimeBuildContext:
    return RuntimeBuildContext(
        package_root=package.package_root,
        runtime_root=Path(runtime_root).expanduser().resolve() if runtime_root is not None else None,
        runtime_instance_id=str(runtime_instance_id).strip() if runtime_instance_id else None,
        instance_extension_root=(
            Path(instance_extension_root).expanduser().resolve()
            if instance_extension_root is not None
            else None
        ),
        package=package,
        resources={} if resources is None else dict(resources),
        tool_runtime_resources=dict(tool_runtime_resources or {}),
    )


class RuntimeBuildPlanner:
    def __init__(self, *, registry: RuntimeContractRegistry) -> None:
        self.registry = registry

    def build(
        self,
        package: LoadedAgentPackage,
        *,
        base_services: RuntimeServices,
        runtime_root: str | Path | None = None,
        runtime_instance_id: str | None = None,
        instance_extension_root: str | Path | None = None,
    ) -> RuntimeBuildResult:
        missing = sorted(REQUIRED_AGENT_PACKAGE_CONTRACTS - set(package.contracts))
        if missing:
            raise ValueError("agent package missing required runtime contracts: " + ", ".join(missing))
        context = runtime_build_context(
            package,
            runtime_root=runtime_root,
            runtime_instance_id=runtime_instance_id,
            instance_extension_root=instance_extension_root,
        )
        contracts = sorted(
            [self.registry.parse(payload) for payload in package.contracts.values()],
            key=_contract_build_priority,
        )
        contributions = [RuntimeContribution(system_wrappers=[RENDER_NODE_SYSTEM_WRAPPER_ID])]
        build_resources = dict(context.resources)
        build_tool_runtime_resources: dict[str, object] = {}
        from agent_factory.runtime_contracts.builtins.builders import (
            build_knowledge_runtime_infrastructure,
            build_session_runtime,
        )

        for contribution in (
            build_session_runtime(context),
            build_knowledge_runtime_infrastructure(context),
        ):
            build_resources.update(contribution.resources)
            build_tool_runtime_resources.update(contribution.tool_runtime_resources)
            contributions.append(contribution)
        for contract in [*_default_runtime_infrastructure_contracts(), *contracts]:
            if not bool(getattr(contract, "enabled", True)):
                continue
            contract_context = runtime_build_context(
                context.package,
                runtime_root=context.runtime_root,
                runtime_instance_id=context.runtime_instance_id,
                instance_extension_root=context.instance_extension_root,
                resources=build_resources,
                tool_runtime_resources=build_tool_runtime_resources,
            )
            contribution = self.registry.builder_for(contract).build(contract, contract_context)
            for key, value in contribution.resources.items():
                if key in build_resources and build_resources[key] != value:
                    raise ValueError(f"conflicting runtime build resource: {key}")
                build_resources[key] = value
            for key, value in contribution.tool_runtime_resources.items():
                if key in build_tool_runtime_resources and build_tool_runtime_resources[key] is not value:
                    raise ValueError(f"conflicting tool runtime build resource: {key}")
                build_tool_runtime_resources[key] = value
            contributions.append(contribution)
        return RuntimeContributionMerger(base_services=base_services).merge(contributions)


def _default_runtime_infrastructure_contracts() -> list[BaseModel]:
    return [
        TraceContract(),
        ArtifactContract(),
    ]


def _contract_build_priority(contract: BaseModel) -> tuple[int, str]:
    contract_type = str(getattr(contract, "type"))
    priority = {
        "resources": 20,
        "trace": 25,
        "artifact": 35,
        "scheduler": 40,
        "scheduler_seed": 41,
        "model": 48,
        "tools": 50,
        "node_provider": 55,
        "context": 80,
        "dependencies": 100,
    }
    return (priority.get(contract_type, 100), contract_type)
