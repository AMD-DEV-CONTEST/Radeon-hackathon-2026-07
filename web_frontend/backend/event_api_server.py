"""
FastAPI Event/API Server - FastAgentFactory Web Runtime Service.

The module only assembles the app. Runtime lifecycle management and route groups
live in dedicated modules so frontend-facing concerns do not share one file.
"""
from __future__ import annotations

import asyncio
import logging
import sys
from pathlib import Path
from uuid import uuid4

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from agent_factory.env import load_agentfactory_dotenv
from agent_factory.benchmarking import BenchmarkService
from agent_factory.contracts import NotFoundError
from agent_factory.local_inference.runtime_manager import LocalInferenceRuntimeManager
from agent_factory.runtime_kernel.persistence import close_shared_sqlite_checkpointers
from agent_factory.create_agent.probe_jobs import probe_job_manager
from agent_factory.collaboration_system.task_client import background_task_store_path
from agent_factory.collaboration_system.persistence import migrate_legacy_background_tasks
from agent_factory.collaboration_system.task_executors import RuntimeBundle
from agent_factory.collaboration_system.task_runtime import (
    register_background_task_service,
    unregister_background_task_service,
)
from agent_factory.collaboration_system.task_service import BackgroundTaskService
from agent_factory.agent_group_system import AgentGroupService
from agent_factory.factory_graph.frontend_bridge.agent_package_runtime import AgentPackageRuntimeManager
from agent_factory.factory_graph.frontend_bridge.protocol import FactoryFrontendCommand
from agent_factory.paths import factory_artifact_path
from agent_factory.tooling.skillhub import ensure_global_skillhub_cli
from web_frontend.backend.routes.agent_packages import create_agent_package_router
from web_frontend.backend.routes.background_tasks import create_background_task_router
from web_frontend.backend.routes.agent_group import create_agent_group_router
from web_frontend.backend.routes.benchmarks import create_benchmark_router
from web_frontend.backend.routes.create_agent import create_create_agent_router
from web_frontend.backend.routes.extensions import create_extensions_router
from web_frontend.backend.routes.files import create_file_router
from web_frontend.backend.routes.knowledge import create_knowledge_router
from web_frontend.backend.routes.memory import create_memory_router
from web_frontend.backend.routes.model_pool import create_model_pool_router
from web_frontend.backend.routes.runtime import create_runtime_router
from web_frontend.backend.routes.scheduler import create_scheduler_router
from web_frontend.backend.routes.tips import create_tip_router
from web_frontend.backend.routes.storage import create_storage_router
from web_frontend.backend.routes.workspace import create_workspace_router
from web_frontend.backend.runtime_bridge import RuntimeBridge
from web_frontend.backend.event_loop_watchdog import EventLoopWatchdog
from web_frontend.backend.parent_process_watchdog import start_parent_process_watchdog
from web_frontend.backend.builtin_extensions import ensure_builtin_web_search_mcp

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)
load_agentfactory_dotenv()

app = FastAPI(title="FastAgentFactory Web Runtime Service")
runtime_bridge = RuntimeBridge()
event_loop_watchdog = EventLoopWatchdog(logger)
agent_group_service = AgentGroupService(
    logger=logger,
    runtime_factory=lambda: _agent_package_runtime(runtime_bridge),
)
background_task_scheduler: BackgroundTaskService | None = None
local_inference_runtime_manager = LocalInferenceRuntimeManager()
benchmark_service = BenchmarkService(local_inference_runtime_manager)

def _observe_agent_group_runtime_event(event_payload: dict) -> None:
    """Persist group runtime events, then dispatch the next member turn when a lane frees."""
    agent_group_service.observe_runtime_event(event_payload)
    payload = event_payload.get("payload") if isinstance(event_payload.get("payload"), dict) else {}
    group_id = str(payload.get("group_id") or "").strip()
    if not group_id or event_payload.get("event_type") not in {"run_completed", "run_failed", "run_cancelled"}:
        return
    runtime_bridge.schedule_coroutine(_dispatch_queued_agent_group_runs(group_id))


async def _dispatch_queued_agent_group_runs(group_id: str) -> None:
    try:
        runtime = _agent_package_runtime(runtime_bridge)
        commands = agent_group_service.prepare_queued_run_commands(group_id, runtime)
        for command in commands:
            await runtime_bridge.send_frontend_command(command)
    except Exception:
        logger.exception("Failed to dispatch queued agent-group runs for %s", group_id)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(create_runtime_router(runtime_bridge, logger))
app.include_router(create_agent_package_router(runtime_bridge, logger))
app.include_router(create_background_task_router())
app.include_router(create_agent_group_router(runtime_bridge, agent_group_service))
app.include_router(create_create_agent_router())
app.include_router(create_workspace_router(runtime_bridge))
app.include_router(create_file_router())
app.include_router(create_knowledge_router(runtime_bridge))
app.include_router(create_memory_router(runtime_bridge))
app.include_router(create_extensions_router(runtime_bridge))
app.include_router(create_scheduler_router(runtime_bridge))
app.include_router(create_model_pool_router(local_inference_runtime_manager))
app.include_router(create_benchmark_router(benchmark_service))
app.include_router(create_tip_router())
app.include_router(create_storage_router(runtime_bridge))


async def _ensure_skillhub_cli() -> None:
    try:
        result = await asyncio.to_thread(ensure_global_skillhub_cli, auto_install=True)
    except Exception as exc:
        logger.warning("SkillHUB CLI initialization failed: %s: %s", type(exc).__name__, exc)
        return
    if result.get("cli_available"):
        logger.info(
            "SkillHUB CLI ready: %s %s",
            result.get("cli_path") or "skillhub",
            result.get("cli_version") or "",
        )
        return
    logger.warning(
        "%s",
        result.get("message")
        or "SkillHUB CLI is not available; install a native SkillHUB CLI distribution to enable it.",
    )


@app.on_event("startup")
async def startup_event():
    global background_task_scheduler
    start_parent_process_watchdog()
    builtin_web_search = ensure_builtin_web_search_mcp()
    logger.info("Built-in MCP is configured: %s", builtin_web_search.server_id)
    event_loop_watchdog.start(asyncio.get_running_loop())
    await runtime_bridge.start()
    adapter = runtime_bridge.adapter
    if (
        adapter is None
        or adapter.agent_package_runtime is None
        or adapter.create_agent_runtime is None
        or adapter.evolution_runtime is None
    ):
        raise RuntimeError("runtime adapter did not initialize background-task runtimes")
    runtimes = RuntimeBundle(
        agent_package_runtime=adapter.agent_package_runtime,
        create_agent_runtime=adapter.create_agent_runtime,
        evolution_runtime=adapter.evolution_runtime,
    )
    task_store_path = background_task_store_path(factory_artifact_path("background_tasks"))
    migration = migrate_legacy_background_tasks(
        factory_artifact_path("collaboration", "factory.sqlite"),
        task_store_path,
    )
    if migration.migrated:
        logger.info(
            "Migrated legacy background tasks: sessions=%s tasks=%s events=%s",
            migration.session_count,
            migration.task_count,
            migration.event_count,
        )
    background_task_scheduler = BackgroundTaskService(
        task_store_path,
        runtimes.task_executors(),
        logger=logger,
    )
    background_task_scheduler.add_event_listener(_observe_background_task_event)
    register_background_task_service(background_task_scheduler)
    background_task_scheduler.start()
    app.state.skillhub_cli_install_task = asyncio.create_task(
        _ensure_skillhub_cli(),
        name="skillhub-cli-install",
    )
    recovered_group_commits = agent_group_service.recover_workspace_transactions()
    if recovered_group_commits:
        logger.info("Recovered %s pending agent-group workspace commits", len(recovered_group_commits))
    runtime_bridge.add_event_observer(_observe_agent_group_runtime_event)
    await local_inference_runtime_manager.restore()


@app.on_event("shutdown")
async def shutdown_event():
    global background_task_scheduler
    await benchmark_service.shutdown()
    await local_inference_runtime_manager.shutdown()
    if background_task_scheduler is not None:
        background_task_scheduler.remove_event_listener(_observe_background_task_event)
        background_task_scheduler.stop()
        unregister_background_task_service(background_task_scheduler)
        background_task_scheduler = None
    agent_group_service.shutdown()
    probe_job_manager.shutdown()
    runtime_bridge.remove_event_observer(_observe_agent_group_runtime_event)
    await runtime_bridge.stop()
    close_shared_sqlite_checkpointers()
    event_loop_watchdog.stop()


def _observe_background_task_event(event_payload: dict) -> None:
    event_type = str(event_payload.get("event_type") or "")
    if event_type != "background_task_result":
        return
    task_id = str(event_payload.get("task_id") or "").strip()
    if task_id:
        runtime_bridge.schedule_coroutine(_continue_parent_after_background_task(task_id))


async def _continue_parent_after_background_task(task_id: str) -> None:
    scheduler = background_task_scheduler
    if scheduler is None:
        return
    try:
        task = scheduler.get(task_id)
        session = scheduler.sessions.get(task.session_id)
    except NotFoundError:
        return
    if session.get("status") != "active":
        return
    package_id = str(session.get("owner_package_id") or "").strip()
    session_id = str(session.get("owner_runtime_session_id") or "").strip()
    if not package_id or not session_id:
        return
    details = [
        f"后台任务主动更新：task_id={task.task_id}，type={task.type}，status={task.status}。",
    ]
    if task.result_summary:
        details.append(task.result_summary)
    if task.artifact_refs:
        details.append(f"已交付产物 {len(task.artifact_refs)} 项。")
    details.append("请处理本次主动更新并继续必要工作；其他任务会分别主动更新，无需调用 background_tasks 查询进度。")
    await runtime_bridge.send_frontend_command(
        FactoryFrontendCommand(
            type="send_agent_package_message",
            request_id=f"background-task-{task.task_id}-{uuid4().hex[:8]}",
            session_id=session_id,
            payload={
                "package_id": package_id,
                "session_id": session_id,
                "message": "\n".join(details),
                "message_metadata": {
                    "source": "background_task",
                    "visibility": "internal",
                    "task_id": task.task_id,
                    "task_type": task.type,
                },
            },
        )
    )


def _agent_package_runtime(runtime_bridge: RuntimeBridge) -> AgentPackageRuntimeManager:
    adapter = runtime_bridge.adapter
    runtime = getattr(adapter, "agent_package_runtime", None) if adapter is not None else None
    return runtime if isinstance(runtime, AgentPackageRuntimeManager) else AgentPackageRuntimeManager()


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000, log_level="info")
