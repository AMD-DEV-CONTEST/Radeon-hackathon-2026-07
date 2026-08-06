from __future__ import annotations

from agent_factory.runtime_contracts.schema import (
    ContextContract,
    DependenciesContract,
    ModelContract,
    ResourcesContract,
    SchedulerContract,
    SchedulerSeedContract,
    ToolsContract,
)


def default_tools_contract() -> ToolsContract:
    return ToolsContract()


def default_model_contract() -> ModelContract:
    return ModelContract()


def default_context_contract() -> ContextContract:
    return ContextContract()


def default_resources_contract() -> ResourcesContract:
    return ResourcesContract()


def default_dependencies_contract() -> DependenciesContract:
    return DependenciesContract()


def default_scheduler_contract() -> SchedulerContract:
    return SchedulerContract()


def default_scheduler_seed_contract() -> SchedulerSeedContract:
    return SchedulerSeedContract()
