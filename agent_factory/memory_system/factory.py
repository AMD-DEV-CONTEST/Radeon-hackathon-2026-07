from __future__ import annotations

from pathlib import Path
import os
from typing import Any

from agent_factory.paths import resolve_project_path
from agent_factory.memory_system.background import MemoryBackgroundWorker
from agent_factory.memory_system.config import (
    MemoryBackgroundConfig,
    MemoryStoreRuntimeConfig,
    MemorySystemConfig,
    memory_write_interval_turns_from_env,
    memory_semantic_index_config_from_env,
    should_enqueue_memory_write,
)
from agent_factory.memory_system.formatting import memory_context_text
from agent_factory.memory_system.injection import default_factory_runtime, inject_factory_cross_session_memory
from agent_factory.memory_system.schema import MemoryConversationSegment, MemoryWriteJob, MemoryWriteReport
from agent_factory.memory_system.store_index import build_memory_store_index
from agent_factory.runtime_kernel.background_workers import RuntimeBackgroundWorkerManager
from agent_factory.runtime_kernel.persistence import LangGraphStoreConfig, LangGraphStoreFactory


_FACTORY_MEMORY_RUNTIME = None
_FACTORY_MEMORY_WORKER: MemoryBackgroundWorker | None = None
_FACTORY_MEMORY_WORKERS = RuntimeBackgroundWorkerManager()


def inject_factory_prompt_memory(*, stage_id: str, values: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    try:
        runtime = _factory_memory_runtime()
        updated, report = inject_factory_cross_session_memory(values=values, runtime=runtime, stage_id=stage_id)
    except Exception as exc:
        return values, {"status": "failed", "error": f"{type(exc).__name__}: {exc}"}
    context_text = memory_context_text(updated.get("cross_session_memory") or {})
    if context_text:
        updated["factory_operating_context"] = (
            str(updated.get("factory_operating_context") or "")
            + "\n\n相关已知信息：\n"
            + context_text
            + "\n使用要求：只在确实相关时自然参考，不要说明这些信息的来源。"
        )
    return updated, report.model_dump(mode="json")


def factory_memory_runtime():
    return _factory_memory_runtime()


def _factory_memory_runtime():
    global _FACTORY_MEMORY_RUNTIME
    if _FACTORY_MEMORY_RUNTIME is not None:
        return _FACTORY_MEMORY_RUNTIME
    config = _factory_memory_config()
    handle = LangGraphStoreFactory().build(
        LangGraphStoreConfig(
            backend=config.store.backend,
            path=(
                Path(config.store.path)
                if config.store.backend == "sqlite" and config.store.path.strip()
                else None
            ),
            connection_uri=config.store.connection_uri,
            database_name=config.store.database_name,
            collection_name=config.store.collection_name,
            setup=config.store.setup,
            provider_options=config.store.provider_options,
            index=build_memory_store_index(config),
        )
    )
    _FACTORY_MEMORY_RUNTIME = default_factory_runtime(project_id="default", config=config, store=handle.store)
    return _FACTORY_MEMORY_RUNTIME


def enqueue_factory_memory_write(
    *,
    segment: MemoryConversationSegment,
) -> MemoryWriteReport:
    runtime = _factory_memory_runtime()
    turn_index = int(segment.end_turn)
    if not should_enqueue_memory_write(turn_index=turn_index, config=runtime.config):
        return MemoryWriteReport(
            job_id="not_due",
            status="noop",
            namespace=tuple(runtime.namespace),
            action_counts={"noop": 1},
        )
    worker = _factory_memory_worker(runtime)
    job = MemoryWriteJob(
        scope="factory",
        namespace=tuple(runtime.namespace),
        source=segment.source,
        segment=segment,
    )
    return worker.enqueue(job)


def _factory_memory_worker(runtime) -> MemoryBackgroundWorker:
    global _FACTORY_MEMORY_WORKER
    if _FACTORY_MEMORY_WORKER is not None:
        return _FACTORY_MEMORY_WORKER
    _FACTORY_MEMORY_WORKER = MemoryBackgroundWorker(store=runtime.store, config=runtime.config)
    runtime.writer = _FACTORY_MEMORY_WORKER
    _FACTORY_MEMORY_WORKERS.add(_FACTORY_MEMORY_WORKER)
    events = _FACTORY_MEMORY_WORKERS.start_all()
    failed = [event for event in events if event.status == "failed"]
    if failed:
        runtime.writer = None
        _FACTORY_MEMORY_WORKER = None
        raise RuntimeError("; ".join(event.message for event in failed if event.message) or "factory memory worker start failed")
    return _FACTORY_MEMORY_WORKER


def shutdown_factory_memory_worker() -> None:
    global _FACTORY_MEMORY_WORKER, _FACTORY_MEMORY_WORKERS
    _FACTORY_MEMORY_WORKERS.shutdown_all()
    _FACTORY_MEMORY_WORKER = None
    _FACTORY_MEMORY_WORKERS = RuntimeBackgroundWorkerManager()


def _factory_memory_config() -> MemorySystemConfig:
    backend = os.getenv("AGENTFACTORY_MEMORY_STORE_BACKEND", "sqlite").strip().lower() or "sqlite"
    path = resolve_project_path(os.getenv("AGENTFACTORY_MEMORY_STORE_PATH", ".agentfactory/memory/factory.sqlite"))
    journal_root = resolve_project_path(".agentfactory/memory/jobs")
    return MemorySystemConfig(
        store=MemoryStoreRuntimeConfig(
            backend=backend,
            path=str(path),
            connection_uri=_env_empty_as_none("AGENTFACTORY_MEMORY_STORE_CONNECTION_URI"),
            database_name=_env_empty_as_none("AGENTFACTORY_MEMORY_STORE_DATABASE_NAME"),
            collection_name=_env_empty_as_none("AGENTFACTORY_MEMORY_STORE_COLLECTION_NAME"),
            setup=_env_bool("AGENTFACTORY_MEMORY_STORE_SETUP", default=True),
        ),
        background=MemoryBackgroundConfig(
            journal_root=str(journal_root),
            write_interval_turns=memory_write_interval_turns_from_env(),
        ),
        semantic_index=memory_semantic_index_config_from_env(),
    )


def _env_empty_as_none(name: str) -> str | None:
    value = os.getenv(name)
    if value is None:
        return None
    text = value.strip()
    return text or None


def _env_bool(name: str, *, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    normalized = raw.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    return default
