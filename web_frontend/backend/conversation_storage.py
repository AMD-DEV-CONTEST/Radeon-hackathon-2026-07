"""Conversation storage usage and coordinated destructive cleanup."""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Any
from uuid import uuid4

from agent_factory.collaboration_system.task_runtime import background_task_service
from agent_factory.contracts import NotFoundError, ServiceUnavailableError
from agent_factory.factory_graph.frontend_bridge.protocol import FactoryFrontendCommand
from agent_factory.paths import factory_artifact_path
from agent_factory.workspace_system import WorkspaceStore
from web_frontend.backend.runtime_bridge import RuntimeBridge


logger = logging.getLogger(__name__)


class ConversationStorageService:
    def __init__(self, runtime_bridge: RuntimeBridge) -> None:
        self.runtime_bridge = runtime_bridge
        self._lock = asyncio.Lock()

    def usage(self) -> dict[str, Any]:
        snapshot = self._session_snapshot()
        bytes_used, file_count = _storage_usage(_conversation_storage_paths())
        return {
            "bytes_used": bytes_used,
            "file_count": file_count,
            "factory_session_count": len(snapshot["factory_sessions"]),
            "agent_session_count": len(snapshot["agent_sessions"]),
            "background_task_session_count": len(snapshot["background_task_sessions"]),
            "session_count": len(snapshot["factory_sessions"]) + len(snapshot["agent_sessions"]),
        }

    async def clear(self) -> dict[str, Any]:
        async with self._lock:
            before = await asyncio.to_thread(self.usage)
            snapshot = await asyncio.to_thread(self._session_snapshot)
            for session in snapshot["factory_sessions"]:
                await self.runtime_bridge.delete_session_and_wait(
                    FactoryFrontendCommand(
                        type="delete_session",
                        request_id=f"clear-conversations-{uuid4().hex}",
                        session_id=str(session["session_id"]),
                        mode=session.get("current_mode"),
                        payload={"session_id": str(session["session_id"])},
                    )
                )
            for session in snapshot["agent_sessions"]:
                await self.runtime_bridge.delete_session_and_wait(
                    FactoryFrontendCommand(
                        type="delete_agent_package_session",
                        request_id=f"clear-conversations-{uuid4().hex}",
                        session_id=str(session["session_id"]),
                        mode="agent_package",
                        payload={
                            "package_id": str(session["package_id"]),
                            "session_id": str(session["session_id"]),
                        },
                    )
                )
            await asyncio.to_thread(self._delete_remaining_background_task_sessions)
            after = await asyncio.to_thread(self.usage)
            return {
                "cleared": True,
                "before": before,
                "after": after,
                "released_bytes": max(0, int(before["bytes_used"]) - int(after["bytes_used"])),
            }

    def _session_snapshot(self) -> dict[str, list[dict[str, Any]]]:
        adapter = self.runtime_bridge.adapter
        if adapter is None:
            raise RuntimeError("Runtime service not started")
        factory_sessions = [
            record.model_dump(mode="json")
            for record in adapter.session_manager.list_sessions(include_internal=True)
        ]
        agent_sessions: list[dict[str, Any]] = []
        runtime = adapter.agent_package_runtime
        for package in runtime.list_packages():
            package_id = str(package.get("package_id") or "").strip()
            if not package_id:
                continue
            try:
                package_sessions = runtime.list_sessions(package_id, include_internal=True)
            except (FileNotFoundError, ValueError, OSError) as exc:
                logger.warning("Skipping unavailable Agent package while reading conversation usage: %s: %s", package_id, exc)
                continue
            for session in package_sessions:
                agent_sessions.append({**session, "package_id": package_id})
        try:
            background_sessions = _all_background_task_sessions()
        except ServiceUnavailableError:
            background_sessions = []
        return {
            "factory_sessions": factory_sessions,
            "agent_sessions": agent_sessions,
            "background_task_sessions": background_sessions,
        }

    @staticmethod
    def _delete_remaining_background_task_sessions() -> None:
        try:
            service = background_task_service()
        except ServiceUnavailableError:
            return
        for session in _all_background_task_sessions():
            try:
                service.delete_session(str(session["session_id"]))
            except NotFoundError:
                continue


def _all_background_task_sessions() -> list[dict[str, Any]]:
    service = background_task_service()
    sessions: list[dict[str, Any]] = []
    offset = 0
    while True:
        page = service.sessions.list(limit=500, offset=offset)
        sessions.extend(page)
        if len(page) < 500:
            return sessions
        offset += len(page)


def _conversation_storage_paths() -> list[Path]:
    paths = [
        factory_artifact_path("sessions"),
        factory_artifact_path("checkpoints"),
        factory_artifact_path("runtime_events"),
        factory_artifact_path("create_agent_workspaces"),
        factory_artifact_path("background_tasks"),
        factory_artifact_path("workspaces"),
    ]
    runtime_root = factory_artifact_path("agent_runtime")
    if runtime_root.is_dir():
        for package_root in runtime_root.iterdir():
            if not package_root.is_dir():
                continue
            paths.extend(
                package_root / name
                for name in ("sessions", "workdirs", "checkpoints", "traces", "tool_outputs")
            )
    for workspace in WorkspaceStore().list(include_archived=True):
        if workspace.root_kind != "managed":
            continue
        workdir = Path(workspace.workdir_root).expanduser().resolve()
        paths.append(workdir)
    return paths


def _storage_usage(paths: list[Path]) -> tuple[int, int]:
    bytes_used = 0
    file_count = 0
    visited_roots: set[Path] = set()
    visited_files: set[Path] = set()
    for root in paths:
        resolved = root.expanduser().resolve()
        if resolved in visited_roots or not resolved.exists():
            continue
        visited_roots.add(resolved)
        candidates = [resolved] if resolved.is_file() else resolved.rglob("*")
        for path in candidates:
            if not path.is_file() or path.is_symlink():
                continue
            try:
                resolved_file = path.resolve()
                if resolved_file in visited_files:
                    continue
                visited_files.add(resolved_file)
                bytes_used += path.stat().st_size
                file_count += 1
            except OSError:
                continue
    return bytes_used, file_count
