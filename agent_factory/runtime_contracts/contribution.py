from __future__ import annotations

from dataclasses import dataclass, field
import json
from typing import Any

from agent_factory.runtime_kernel.bindings import RuntimeServices


@dataclass(slots=True)
class RuntimeContribution:
    services: dict[str, Any] = field(default_factory=dict)
    system_wrappers: list[str] = field(default_factory=list)
    node_providers: list[Any] = field(default_factory=list)
    background_workers: list[Any] = field(default_factory=list)
    session_config: dict[str, Any] = field(default_factory=dict)
    resources: dict[str, Any] = field(default_factory=dict)
    tool_runtime_resources: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class RuntimeBuildResult:
    services: RuntimeServices
    system_wrappers: list[str] = field(default_factory=list)
    session_config: dict[str, Any] = field(default_factory=dict)
    background_workers: list[Any] = field(default_factory=list)
    node_providers: list[Any] = field(default_factory=list)


class RuntimeContributionMergeError(ValueError):
    pass


class RuntimeContributionMerger:
    def __init__(self, *, base_services: RuntimeServices) -> None:
        self._base_services = base_services

    def merge(self, contributions: list[RuntimeContribution]) -> RuntimeBuildResult:
        services = _service_slots(self._base_services)
        background_workers: list[Any] = []
        node_providers: list[Any] = []
        seen_node_impl_ids: set[str] = set()
        system_wrappers: list[str] = []
        seen_system_wrappers: set[str] = set()
        session_config: dict[str, Any] = {}
        resources: dict[str, Any] = {}
        tool_runtime_resources: dict[str, Any] = {}
        for contribution in contributions:
            for name, value in contribution.services.items():
                if value is None:
                    continue
                if name not in services:
                    raise RuntimeContributionMergeError(f"unknown runtime service slot: {name}")
                if services[name] is not None and services[name] is not value:
                    raise RuntimeContributionMergeError(f"duplicate runtime service contribution: {name}")
                services[name] = value
            for wrapper_id in contribution.system_wrappers:
                if wrapper_id in seen_system_wrappers:
                    raise RuntimeContributionMergeError(f"duplicate system wrapper contribution: {wrapper_id}")
                seen_system_wrappers.add(wrapper_id)
                system_wrappers.append(wrapper_id)
            for provider in contribution.node_providers:
                provider_id = str(getattr(provider, "provider_id", ""))
                for implementation in provider.implementations():
                    impl_id = str(getattr(implementation, "impl_id", ""))
                    if not impl_id:
                        raise RuntimeContributionMergeError(f"node provider {provider_id} returned implementation without impl_id")
                    if impl_id in seen_node_impl_ids:
                        raise RuntimeContributionMergeError(f"duplicate node implementation contribution: {impl_id}")
                    seen_node_impl_ids.add(impl_id)
                node_providers.append(provider)
            for key, value in contribution.session_config.items():
                if key in session_config and session_config[key] != value:
                    raise RuntimeContributionMergeError(f"conflicting session config: {key}")
                session_config[key] = value
            for key, value in contribution.resources.items():
                _assert_json_serializable_runtime_resource(key, value)
                if key in resources and resources[key] != value:
                    raise RuntimeContributionMergeError(f"conflicting runtime resource: {key}")
                resources[key] = value
            for key, value in contribution.tool_runtime_resources.items():
                if key in tool_runtime_resources and tool_runtime_resources[key] is not value:
                    raise RuntimeContributionMergeError(f"conflicting tool runtime resource: {key}")
                tool_runtime_resources[key] = value
            background_workers.extend(contribution.background_workers)
        services["runtime_resources"] = dict(resources)
        services["tool_runtime_resources"] = dict(tool_runtime_resources)
        return RuntimeBuildResult(
            services=RuntimeServices(**services),
            system_wrappers=system_wrappers,
            session_config=session_config,
            background_workers=background_workers,
            node_providers=node_providers,
        )


def _service_slots(services: RuntimeServices) -> dict[str, Any]:
    return {
        "model_service": None,
        "model_operation_service": None,
        "tool_registry": None,
        "memory_store": None,
        "memory_system": None,
        "knowledge_runtime": None,
        "context_system": None,
        "context_engine": services.context_engine,
        "observability_manager": services.observability_manager,
        "checkpointer": None,
        "harness_bridge": services.harness_bridge,
        "scheduler_store": None,
        "scheduler_runtime": None,
        "artifact_store": None,
        "report_store": None,
        "bookmark_store": services.bookmark_store,
        "trace_recorder": services.trace_recorder,
        "trace_reader": services.trace_reader,
        "trace_projector": services.trace_projector,
        "trace_diagnostics": services.trace_diagnostics,
        "runtime_resources": dict(services.runtime_resources),
        "tool_runtime_resources": dict(services.tool_runtime_resources),
    }


def _assert_json_serializable_runtime_resource(key: str, value: Any) -> None:
    try:
        json.dumps(value, ensure_ascii=False)
    except (TypeError, ValueError) as exc:
        raise RuntimeContributionMergeError(
            f"runtime resource must be JSON serializable: {key}"
        ) from exc
