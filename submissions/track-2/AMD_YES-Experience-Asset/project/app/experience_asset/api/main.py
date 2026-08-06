"""Minimal E1-A status API; durable writes stay behind application services."""

from __future__ import annotations

import os
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path

from fastapi import FastAPI
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

from app.experience_asset import __version__
from app.experience_asset.api.routes.delivery import build_delivery_router
from app.experience_asset.api.routes.m1 import build_m1_router
from app.experience_asset.api.routes.m2 import build_m2_router
from app.experience_asset.api.routes.m3 import build_m3_router
from app.experience_asset.api.routes.m4 import build_m4_router
from app.experience_asset.api.routes.m5 import build_m5_router
from app.experience_asset.api.routes.relation import build_relation_router
from app.experience_asset.application.m2 import M2CriticalMomentService
from app.experience_asset.application.m3 import M3LedgerService
from app.experience_asset.application.m4 import M4MapService
from app.experience_asset.application.m5.context_loader import M5ContextLoader
from app.experience_asset.delivery import (
    E7DeliveryRepository,
    E7DeliveryService,
    LocalArtifactStore,
    PersistedM5ApprovalAdapter,
)
from app.experience_asset.domain.enums import TerminalState
from app.experience_asset.domain.models import HealthStatusV1
from app.experience_asset.inference import LocalVLLMClient, ModelClient
from app.experience_asset.inference.client import require_loopback_base_url
from app.experience_asset.persistence.m5_store import M5Store
from app.experience_asset.persistence.repository import SQLiteAssetRepository
from app.experience_asset.policy import RuntimePolicy
from app.experience_asset.retrieval import SQLiteCurrentSourceRetrievalRepository
from app.experience_asset.tools import BoundedToolExecutor
from app.experience_asset.workflow import M1ProductionGraph, M2ProductionGraph
from app.experience_asset.workflow.m3_graph import M3ProductionGraph
from app.experience_asset.workflow.m4_graph import M4ProductionGraph
from app.experience_asset.workflow.m5_graph import M5ProductionGraph

DEFAULT_DATABASE_PATH = "/workspace/amd-track2-agent/data/experience_asset.sqlite3"
DEFAULT_WORKFLOW_DATABASE_PATH = (
    "/workspace/amd-track2-agent/data/experience_asset.workflow.sqlite3"
)
DEFAULT_MODEL_ENDPOINT = "http://127.0.0.1:8000/v1"
DEFAULT_MODEL_ID = "Qwen3.5-9B"


def create_app(
    *,
    database_path: str | Path | None = None,
    workflow_database_path: str | Path | None = None,
    model_endpoint: str | None = None,
    model_id: str | None = None,
    gpu_viability: str | None = None,
    model_client: ModelClient | None = None,
    code_commit: str | None = None,
) -> FastAPI:
    configured_database = Path(
        database_path or os.getenv("EXPERIENCE_ASSET_DB", DEFAULT_DATABASE_PATH)
    )
    if workflow_database_path is not None:
        configured_workflow_database = Path(workflow_database_path)
    elif os.getenv("EXPERIENCE_WORKFLOW_DB"):
        configured_workflow_database = Path(os.environ["EXPERIENCE_WORKFLOW_DB"])
    elif database_path is not None:
        configured_workflow_database = configured_database.with_suffix(".workflow.sqlite3")
    else:
        configured_workflow_database = Path(DEFAULT_WORKFLOW_DATABASE_PATH)
    configured_endpoint = require_loopback_base_url(
        model_endpoint or os.getenv("OPENAI_BASE_URL", DEFAULT_MODEL_ENDPOINT)
    )
    configured_model = (
        model_id or os.getenv("SERVED_MODEL_NAME") or os.getenv("MODEL_ID", DEFAULT_MODEL_ID)
    )
    configured_viability = gpu_viability or os.getenv("GPU_VIABILITY", "NOT_VERIFIED")
    configured_code_commit = code_commit or os.getenv("CODE_COMMIT", "UNCOMMITTED")
    if configured_viability not in {"VERIFIED", "NOT_VERIFIED", "BLOCKED"}:
        raise ValueError("GPU_VIABILITY must be VERIFIED, NOT_VERIFIED, or BLOCKED")
    repository = SQLiteAssetRepository(configured_database)
    m5_store = M5Store(configured_database)
    m5_context_loader = M5ContextLoader(repository)
    # E7 owns its own store and export directory: deletion removes managed
    # files as well as rows, and pointing it at the canonical asset database
    # would put irreversible file deletion next to version history.
    #
    # Built lazily. LocalArtifactStore creates its root in __init__, and every
    # other component here defers filesystem work to lifespan; constructing it
    # eagerly makes importing an app object try to mkdir the configured export
    # directory, which fails wherever that path is not writable.
    delivery_repository = E7DeliveryRepository(configured_database.with_suffix(".delivery.sqlite3"))
    delivery_holder: dict[str, E7DeliveryService] = {}

    def delivery_service() -> E7DeliveryService:
        if "service" not in delivery_holder:
            delivery_holder["service"] = E7DeliveryService(
                delivery_repository,
                LocalArtifactStore(configured_database.parent / "exports"),
                PersistedM5ApprovalAdapter(m5_context_loader, m5_store),
            )
        return delivery_holder["service"]

    configured_model_client = model_client or LocalVLLMClient(
        base_url=configured_endpoint,
        model_id=configured_model,
    )
    agent_graph = M1ProductionGraph(
        repository=repository,
        model_client=configured_model_client,
        runtime_policy=RuntimePolicy(),
        tool_executor=BoundedToolExecutor(SQLiteCurrentSourceRetrievalRepository(repository)),
        code_commit=configured_code_commit,
    )
    m2_graph = M2ProductionGraph(
        repository=repository,
        service=M2CriticalMomentService(repository),
        model_client=configured_model_client,
        code_commit=configured_code_commit,
    )
    m3_graph = M3ProductionGraph(
        repository=repository,
        service=M3LedgerService(repository),
        model_client=configured_model_client,
        runtime_policy=RuntimePolicy(),
        code_commit=configured_code_commit,
    )
    m4_graph = M4ProductionGraph(
        repository=repository,
        service=M4MapService(repository),
        model_client=configured_model_client,
        runtime_policy=RuntimePolicy(),
        code_commit=configured_code_commit,
    )
    m5_graph = M5ProductionGraph(
        context_loader=m5_context_loader,
        store=m5_store,
        draft_loader=lambda draft_id: delivery_service().repository.get_draft(draft_id),
        code_commit=configured_code_commit,
    )

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        repository.initialize()
        delivery_repository.initialize()
        # Built here, where filesystem work belongs, and published on state so
        # callers get the service rather than the provider.
        api.state.delivery_service = delivery_service()
        configured_workflow_database.parent.mkdir(parents=True, exist_ok=True)
        async with AsyncSqliteSaver.from_conn_string(
            str(configured_workflow_database)
        ) as checkpointer:
            await checkpointer.setup()
            agent_graph.compile(checkpointer)
            m2_graph.compile(checkpointer)
            m3_graph.compile(checkpointer)
            m4_graph.compile(checkpointer)
            m5_graph.compile(checkpointer)
            await agent_graph.recover_incomplete_runs()
            await m2_graph.recover_incomplete_runs()
            await m3_graph.recover_incomplete_runs()
            await m4_graph.recover_incomplete_runs()
            await m5_graph.recover_incomplete_runs()
            yield

    api = FastAPI(
        title="Experience Asset Agent API",
        version=__version__,
        description="Local-only Track 2 Agent contracts. Model output never grants permission.",
        lifespan=lifespan,
    )
    api.state.repository = repository
    api.state.agent_graph = agent_graph
    api.state.m2_graph = m2_graph
    api.state.m3_graph = m3_graph
    api.state.m4_graph = m4_graph
    api.state.m5_graph = m5_graph
    api.state.workflow_database_path = configured_workflow_database
    api.state.delivery_provider = delivery_service
    api.include_router(build_m1_router(repository, agent_graph))
    api.include_router(build_m2_router(repository, m2_graph))
    api.include_router(build_m3_router(repository, m3_graph))
    # Registered by the E5 contract freeze so that four parallel Wave-1
    # branches never edit this file. Ticket 02 owns the map handlers; the
    # acceptance and readiness handlers are ticket 03's and still raise a typed,
    # non-shippable NOT_IMPLEMENTED that ticket 10's public QA rejects at an
    # evidence head.
    api.include_router(build_m4_router(repository, m4_graph))
    api.include_router(build_m5_router(repository, delivery_service, m5_graph, m5_store))
    api.include_router(build_delivery_router(delivery_service, m5_context_loader, m5_store))
    api.include_router(build_relation_router(repository, configured_model_client))

    @api.get("/api/v1/health", response_model=HealthStatusV1, tags=["system"])
    async def health() -> HealthStatusV1:
        database_status = "ok" if repository.ping() else "unavailable"
        return HealthStatusV1(
            status="ok" if database_status == "ok" else "degraded",
            app_version=__version__,
            database=database_status,
            model_endpoint=configured_endpoint,
            model_profile=configured_model,
            gpu_viability=configured_viability,
            checked_at=datetime.now(UTC),
        )

    @api.get("/api/v1/contracts/terminal-states", tags=["contracts"])
    async def terminal_states() -> dict[str, list[str] | str]:
        return {
            "schema_version": "1.0.0",
            "values": [state.value for state in TerminalState],
        }

    return api


app = create_app()
