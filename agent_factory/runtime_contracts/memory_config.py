from __future__ import annotations

from agent_factory.context_system import ContextContractConfig
from agent_factory.memory_system.config import MemorySystemConfig
from agent_factory.memory_system.scopes import application_memory_store_path
from agent_factory.runtime_contracts.builder import RuntimeBuildContext
from agent_factory.runtime_contracts.paths import package_runtime_path_text


def resolve_memory_system_config(
    config: MemorySystemConfig,
    context: RuntimeBuildContext,
) -> MemorySystemConfig:
    store = config.store
    background = config.background
    return config.model_copy(
        update={
            "store": (
                store.model_copy(
                    update={
                        "path": str(application_memory_store_path())
                    }
                )
                if store.backend == "sqlite" and store.path.strip()
                else store
            ),
            "background": background.model_copy(
                update={
                    "journal_root": package_runtime_path_text(
                        context,
                        background.journal_root,
                        field_path="context.runtime.cross_session_memory.background.journal_root",
                    )
                }
            ),
        },
        deep=True,
    )


def memory_system_config_from_context(
    config: ContextContractConfig,
    context: RuntimeBuildContext,
) -> MemorySystemConfig:
    policy = config.default_policy.cross_session_memory
    defaults = MemorySystemConfig()
    return resolve_memory_system_config(
        defaults.model_copy(
            update={
                "enabled": policy.enabled,
                "write_enabled": policy.write_enabled,
                "injection_enabled": policy.injection_enabled,
                "ranking": defaults.ranking.model_copy(
                    update={
                        "max_items_total": policy.max_items,
                        "max_tokens_total": policy.max_tokens,
                        "min_score": policy.min_score,
                        "per_kind_limits": policy.per_kind_limits,
                    }
                ),
                "background": defaults.background.model_copy(
                    update={"write_interval_turns": policy.write_interval_turns}
                ),
            },
            deep=True,
        ),
        context,
    )
