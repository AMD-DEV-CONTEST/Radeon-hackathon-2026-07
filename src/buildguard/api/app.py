"""FastAPI application factory."""

import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI

from buildguard.agent.graph import BuildGuardAgent
from buildguard.agent.production_tools import create_production_agent_tools
from buildguard.api.routes_agent import create_agent_router
from buildguard.api.routes_mvp import create_mvp_router
from buildguard.api.routes_rag import create_rag_router
from buildguard.api.routes_runtime import create_runtime_router
from buildguard.api.routes_upload import create_upload_router
from buildguard.config import Settings, load_settings
from buildguard.integration.realtime_slow_loop import RealtimeSlowLoop
from buildguard.integration.service import MvpWorkflow
from buildguard.llm.base import LocalLLMBackend
from buildguard.llm.mock_backend import MockLLMBackend
from buildguard.llm.openai_compatible import OpenAICompatibleLocalBackend
from buildguard.monitoring.amd_smi import AmdSmiMonitor
from buildguard.monitoring.base import CompositeMonitor
from buildguard.monitoring.dashboard import PerformanceDashboard
from buildguard.monitoring.nvidia_smi import NvidiaSmiMonitor
from buildguard.monitoring.process_monitor import ProcessMonitor
from buildguard.monitoring.rocm_smi import RocmSmiMonitor
from buildguard.rag.advanced.answer_grounding import AnswerGrounder
from buildguard.rag.advanced.corrective_retriever import (
    create_advanced_rag_pipeline,
)
from buildguard.rag.service import create_rag_service
from buildguard.realtime.camera_manager import create_camera_manager
from buildguard.realtime.schemas import QueryRecentEventsInput
from buildguard.reporting.builder import ReportBuilder
from buildguard.risk.service import RiskAssessmentService
from buildguard.runtime_mode import RuntimeModeManager
from buildguard.scheduling.gpu_scheduler import GpuScheduler
from buildguard.scheduling.runtime_gate import (
    GpuInferenceGate,
    ModelResidencyRegistry,
    MonitoredGpuResourceProvider,
)
from buildguard.storage.database import Database
from buildguard.storage.memory import LongTermMemory
from buildguard.system.environment_probe import EnvironmentProbe
from buildguard.vision.service import create_vision_service
from buildguard.workspace.manager import WorkspaceManager
from buildguard.workspace.retention import RetentionCleaner
from buildguard.workspace.retention_loop import RetentionLoop


def _under_workspace(path: Path, workspace: Path) -> Path:
    """Rebase conventional relative workspace paths when callers relocate the root."""
    if path.is_absolute():
        return path
    parts = path.parts
    if parts and parts[0] in {"workspace", workspace.name}:
        return workspace.joinpath(*parts[1:])
    return path


def _normalize_runtime_paths(settings: Settings) -> Settings:
    configured = settings.model_copy(deep=True)
    workspace = configured.app.workspace_dir.resolve()
    configured.app.workspace_dir = workspace
    configured.vision.visualization_dir = _under_workspace(
        configured.vision.visualization_dir, workspace
    )
    configured.vision.allowed_image_roots = [
        _under_workspace(path, workspace) for path in configured.vision.allowed_image_roots
    ]
    configured.vision.segmentation.output_dir = _under_workspace(
        configured.vision.segmentation.output_dir,
        workspace,
    )
    configured.realtime.event_image_dir = _under_workspace(
        configured.realtime.event_image_dir, workspace
    )
    configured.realtime.event_clip_dir = _under_workspace(
        configured.realtime.event_clip_dir, workspace
    )
    configured.realtime.allowed_video_roots = [
        _under_workspace(path, workspace) for path in configured.realtime.allowed_video_roots
    ]
    configured.reporting.output_dir = _under_workspace(configured.reporting.output_dir, workspace)
    configured.monitoring.dashboard_log_path = _under_workspace(
        configured.monitoring.dashboard_log_path,
        workspace,
    )
    configured.monitoring.export_dir = _under_workspace(
        configured.monitoring.export_dir,
        workspace,
    )
    return configured


def create_backend(settings: Settings) -> LocalLLMBackend:
    if settings.llm.mode == "mock":
        return MockLLMBackend(seed=settings.app.seed)
    return OpenAICompatibleLocalBackend(settings.llm, settings.permissions)


def _default_config_path() -> Path:
    env_path = os.environ.get("BUILDGUARD_CONFIG")
    if env_path:
        return Path(env_path)
    return Path("configs/app.yaml")


def create_app(
    settings: Settings | None = None,
    backend: LocalLLMBackend | None = None,
) -> FastAPI:
    configured = _normalize_runtime_paths(settings or load_settings(_default_config_path()))
    llm = backend or create_backend(configured)
    workspace_manager = WorkspaceManager(configured.app.workspace_dir)
    workspace_manager.initialize()
    database = Database(configured.app.database_path)
    database.initialize()
    memory = LongTermMemory(database)
    rag = create_rag_service(configured)
    advanced_rag = create_advanced_rag_pipeline(rag, llm)
    answer_grounder = AnswerGrounder(configured.rag.advanced)
    scheduler = GpuScheduler(configured.monitoring.scheduler)
    residency = ModelResidencyRegistry()
    if configured.llm.mode == "local":
        residency.register(
            f"llm:{configured.llm.model}",
            configured.llm.estimated_memory_mb,
        )
    if configured.rag.embedding_mode == "transformers":
        residency.register(
            f"embedding:{configured.rag.embedding_model_path}",
            configured.rag.embedding_estimated_memory_mb,
        )
    if configured.rag.reranker_enabled and configured.rag.reranker_mode == "transformers":
        residency.register(
            f"reranker:{configured.rag.reranker_model_path}",
            configured.rag.reranker_estimated_memory_mb,
        )
    for model in configured.vision.models:
        if model.enabled and model.backend == "local":
            residency.register(
                f"vision:{model.model_name}",
                model.estimated_memory_mb,
            )
    semantic_router = configured.vision.semantic_router
    if semantic_router.enabled and semantic_router.resident:
        residency.register(
            f"vision-router:{semantic_router.model_name}",
            semantic_router.estimated_memory_mb,
        )
    hardware_monitor = CompositeMonitor(
        [
            AmdSmiMonitor(configured.monitoring.command_timeout_seconds),
            RocmSmiMonitor(configured.monitoring.command_timeout_seconds),
            NvidiaSmiMonitor(configured.monitoring.command_timeout_seconds),
            ProcessMonitor(configured.monitoring.sample_interval_seconds),
        ],
        configured.monitoring.sample_interval_seconds,
    )

    gpu_resources = MonitoredGpuResourceProvider(
        hardware_monitor,
        cache_seconds=configured.monitoring.sample_interval_seconds,
        residency=residency,
    )
    gpu_gate = GpuInferenceGate(scheduler, gpu_resources)
    vision = create_vision_service(configured, gpu_gate=gpu_gate)
    risk = RiskAssessmentService(configured.vision.risk)
    report_config = configured.reporting.model_copy(
        update={"output_dir": configured.reporting.output_dir.resolve()}
    )
    reports = ReportBuilder(report_config, llm)
    camera_manager = create_camera_manager(
        configured,
        performance_sink=lambda operation, duration_ms, metrics: memory.record_performance(
            operation,
            duration_ms,
            metrics=metrics,
        ),
        model_registry=vision.models,
        vision_service=vision,
    )
    runtime_info = EnvironmentProbe(configured).probe()
    performance_dashboard = PerformanceDashboard(
        hardware_monitor,
        camera_manager,
        scheduler,
        log_path=configured.monitoring.dashboard_log_path,
        export_dir=configured.monitoring.export_dir,
        workspace_root=configured.app.workspace_dir,
        history_size=configured.monitoring.dashboard_history_size,
        rocm_version=runtime_info.rocm_version,
        resource_provider=gpu_resources,
    )
    runtime_modes = RuntimeModeManager(configured.runtime, configured.app.workspace_dir)
    workflow = MvpWorkflow(
        memory,
        vision,
        rag,
        risk,
        reports,
        event_provider=lambda: (
            camera_manager.query_events(QueryRecentEventsInput(limit=500)).events
        ),
        advanced_rag=advanced_rag,
    )
    realtime_slow_loop = RealtimeSlowLoop(workflow.process_realtime_event)
    retention_loop = RetentionLoop(
        RetentionCleaner(workspace_manager, configured.app.retention),
        configured.app.retention.interval_seconds,
        performance_sink=lambda operation, duration_ms, metrics: memory.record_performance(
            operation,
            duration_ms,
            metrics=metrics,
        ),
    )
    camera_manager.set_event_sink(realtime_slow_loop.submit)
    agent_tools = create_production_agent_tools(
        vision,
        rag,
        risk=risk,
        memory=memory,
        camera_manager=camera_manager,
        workflow=workflow,
        advanced_rag=advanced_rag,
        permissions=configured.permissions,
        workspace_root=configured.app.workspace_dir,
        inspection_image_max_items=(configured.app.tools.inspection_image_max_items),
        timeout_seconds=configured.app.tools.default_timeout_seconds,
    )
    # The application always exposes the complete production Agent loop even
    # when a minimal development config relies on the legacy AgentConfig defaults.
    required_loop_tools = [
        "inspect_single_image",
        "inspect_image_batch_structured",
        "inspect_video",
        "search_construction_standards",
        "assess_risk",
        "query_task_history",
        "generate_inspection_report",
        "generate_event_report",
    ]
    application_agent_config = configured.app.agent.model_copy(
        update={
            "registered_tools": list(
                dict.fromkeys(
                    [
                        *configured.app.agent.registered_tools,
                        *(name for name in required_loop_tools if name in agent_tools),
                    ]
                )
            ),
            "confirmation_tools": list(
                dict.fromkeys(
                    [
                        *configured.app.agent.confirmation_tools,
                        "inspect_video",
                        "inspect_image_batch",
                        "inspect_image_batch_structured",
                        "generate_inspection_report",
                        "generate_event_report",
                    ]
                )
            ),
        }
    )
    agent = BuildGuardAgent(
        llm,
        application_agent_config,
        agent_tools,
        memory=memory,
        answer_grounder=answer_grounder,
    )
    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        try:
            vision.start()
            if configured.app.retention.enabled:
                retention_loop.start()
            yield
        finally:
            vision.close()
            camera_manager.stop_all()
            realtime_slow_loop.close()
            retention_loop.close()

    application = FastAPI(
        title="BuildGuard-Radeon",
        version="0.1.0",
        lifespan=lifespan,
    )
    application.state.settings = configured
    application.state.backend = llm
    application.state.agent = agent
    application.state.rag = rag
    application.state.advanced_rag = advanced_rag
    application.state.answer_grounder = answer_grounder
    application.state.database = database
    application.state.memory = memory
    application.state.workflow = workflow
    application.state.realtime_slow_loop = realtime_slow_loop
    application.state.retention_loop = retention_loop
    application.state.camera_manager = camera_manager
    application.state.gpu_scheduler = scheduler
    application.state.gpu_gate = gpu_gate
    application.state.model_residency = residency
    application.state.performance_dashboard = performance_dashboard
    application.state.runtime_modes = runtime_modes
    application.include_router(create_agent_router(agent, workflow))
    application.include_router(
        create_rag_router(
            rag,
            [path.resolve() for path in configured.rag.allowed_source_roots],
            advanced_rag,
            answer_grounder,
        )
    )
    application.include_router(
        create_mvp_router(
            workflow,
            camera_manager,
            database,
            llm,
            performance_dashboard,
        )
    )
    application.include_router(
        create_upload_router(
            database,
            configured.vision.allowed_image_roots[0],
            configured.vision.upload,
            configured.vision.video_upload,
        )
    )
    application.include_router(create_runtime_router(runtime_modes))

    @application.get("/health")
    def health() -> dict[str, object]:
        return {
            "status": "ok" if llm.health_check() else "degraded",
            "llm_mode": configured.llm.mode,
            "llm_healthy": llm.health_check(),
            "database": database.check()["ok"],
            "semantic_router": vision.semantic_router_status(),
            "cameras_configured": len(configured.realtime.cameras),
            "realtime_slow_loop": realtime_slow_loop.metrics(),
        }

    return application
