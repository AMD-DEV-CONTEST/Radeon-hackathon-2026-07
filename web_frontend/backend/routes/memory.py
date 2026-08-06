from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field

from agent_factory.factory_graph.frontend_bridge.agent_package_runtime import AgentPackageRuntimeManager
from agent_factory.factory_graph.frontend_bridge.runtime_adapter_types import SYSTEM_CHAT_PACKAGE_ID
from agent_factory.memory_system.config import MemorySystemConfig
from agent_factory.memory_system.injection import MemorySystemRuntime, default_agent_runtime
from agent_factory.memory_system.scopes import MemoryScopeContext
from agent_factory.memory_system.retrieval import retrieve_memory_context
from agent_factory.memory_system.schema import MemoryContextPack
from agent_factory.memory_system.store_index import build_memory_store_index
from agent_factory.runtime_contracts.builder import runtime_build_context
from agent_factory.runtime_contracts.memory_config import memory_system_config_from_context
from agent_factory.runtime_contracts.schema import ContextContract
from agent_factory.runtime_kernel.persistence import LangGraphStoreConfig, LangGraphStoreFactory
from web_frontend.backend.runtime_bridge import RuntimeBridge


class MemoryDeleteRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    memory_id: str = Field(min_length=1)
    package_id: str | None = None
    workspace_id: str | None = None
    scope: Literal["workspace", "agent", "user"] | None = None


def create_memory_router(runtime_bridge: RuntimeBridge) -> APIRouter:
    router = APIRouter(prefix="/api/memory")

    @router.get("/query")
    def query_memory(
        query: str = Query(default=""),
        package_id: str | None = None,
        workspace_id: str | None = None,
        scope: Literal["combined", "workspace", "agent", "user"] = "combined",
        limit: int = Query(default=8, ge=1, le=32),
    ):
        resolved_package_id = _memory_package_id(package_id)
        runtime = _memory_runtime_for_scope(runtime_bridge, package_id=resolved_package_id, limit=limit)
        context = _scope_context(runtime, workspace_id=workspace_id)
        if scope == "combined":
            pack = runtime.retrieve_scoped_context(query=query, workspace_id=workspace_id)
        else:
            namespace = context.namespaces().get(scope)
            if namespace is None:
                raise HTTPException(status_code=400, detail=f"{scope} memory requires an active workspace")
            pack = retrieve_memory_context(
                store=runtime.store,
                namespace=namespace,
                query=query,
                config=runtime.config,
            )
        return _pack_response(pack, package_id=resolved_package_id)

    @router.delete("/items")
    def delete_memory_item(payload: MemoryDeleteRequest):
        resolved_package_id = _memory_package_id(payload.package_id)
        runtime = _memory_runtime_for_scope(runtime_bridge, package_id=resolved_package_id)
        scope = payload.scope or ("workspace" if payload.workspace_id else "agent")
        namespace = _scope_context(runtime, workspace_id=payload.workspace_id).namespaces().get(scope)
        if namespace is None:
            raise HTTPException(status_code=400, detail=f"{scope} memory requires an active workspace")
        store = runtime.store
        if store is None:
            raise HTTPException(status_code=400, detail="memory store is not available")
        memory_id = payload.memory_id.strip()
        if not memory_id:
            raise HTTPException(status_code=400, detail="memory_id is required")
        try:
            store.delete(namespace, memory_id)
        except Exception as exc:
            raise HTTPException(status_code=500, detail=f"{type(exc).__name__}: {exc}") from exc
        return {
            "deleted": True,
            "memory_id": memory_id,
            "package_id": resolved_package_id,
            "workspace_id": payload.workspace_id,
            "scope": scope,
            "namespace": list(namespace),
        }

    return router


def _memory_runtime_for_scope(
    runtime_bridge: RuntimeBridge,
    *,
    package_id: str,
    limit: int | None = None,
) -> MemorySystemRuntime:
    runtime = _agent_memory_runtime(runtime_bridge, package_id=package_id)
    if limit is None:
        return runtime
    scoped_config = runtime.config.model_copy(
        update={
            "ranking": runtime.config.ranking.model_copy(
                update={"max_items_total": limit}
            )
        },
        deep=True,
    )
    return runtime.model_copy(update={"config": scoped_config})


def _memory_package_id(package_id: str | None) -> str:
    return str(package_id or "").strip() or SYSTEM_CHAT_PACKAGE_ID


def _scope_context(runtime: MemorySystemRuntime, *, workspace_id: str | None) -> MemoryScopeContext:
    if not runtime.agent_id or not runtime.user_id:
        raise HTTPException(status_code=500, detail="memory scope identity is not available")
    return MemoryScopeContext(
        agent_id=runtime.agent_id,
        user_id=runtime.user_id,
        workspace_id=str(workspace_id or "").strip() or None,
    )


def _agent_memory_runtime(runtime_bridge: RuntimeBridge, *, package_id: str) -> MemorySystemRuntime:
    manager = _agent_package_runtime(runtime_bridge)
    try:
        package = manager.load_package(package_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=f"agent package not found: {package_id}") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    runtime_root = manager.runtime_root_for_package(package_id)
    config = _agent_memory_config(package=package, runtime_root=runtime_root)
    store_config = LangGraphStoreConfig(
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
    store = _build_existing_store(config=config, store_config=store_config)
    return default_agent_runtime(
        agent_id=package.assembly_spec.agent.id,
        config=config,
        store=store,
    )


def _agent_package_runtime(runtime_bridge: RuntimeBridge) -> AgentPackageRuntimeManager:
    adapter = runtime_bridge.adapter
    runtime = getattr(adapter, "agent_package_runtime", None) if adapter is not None else None
    return runtime if isinstance(runtime, AgentPackageRuntimeManager) else AgentPackageRuntimeManager()


def _build_existing_store(*, config: MemorySystemConfig, store_config: LangGraphStoreConfig):
    if not config.enabled:
        return None
    if config.store.backend == "sqlite":
        if store_config.path is None or not store_config.path.is_file():
            return None
    return LangGraphStoreFactory().build(store_config).store


def _agent_memory_config(*, package: Any, runtime_root: Path) -> MemorySystemConfig:
    payload = package.contracts.get("context")
    contract = ContextContract.model_validate(payload or {})
    context = runtime_build_context(package, runtime_root=runtime_root)
    config = memory_system_config_from_context(contract.config, context)
    return (
        config
        if contract.enabled
        else config.model_copy(update={"enabled": False}, deep=True)
    )


def _pack_response(pack: MemoryContextPack, *, package_id: str | None) -> dict[str, Any]:
    items = pack.model_dump(mode="json").get("items") or []
    items.sort(
        key=lambda item: (
            float(item.get("score") or 0.0),
            str(item.get("updated_at") or ""),
        ),
        reverse=True,
    )
    return {
        "package_id": package_id,
        "namespace": list(pack.namespace),
        "namespaces": list(pack.report.get("namespaces") or [list(pack.namespace)]),
        "query": pack.query,
        "items": items,
        "token_estimate": pack.token_estimate,
        "report": dict(pack.report or {}),
    }
