"""Cross-process command client for the canonical background-task store."""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from typing import Any

from agent_factory.collaboration_system.persistence import (
    EventRepository,
    SessionRepository,
    TaskRepository,
    ensure_background_task_schema,
)
from agent_factory.contracts import BackgroundTask, BackgroundTaskType


BACKGROUND_TASK_STORE_NAME = "background_tasks.sqlite"


@dataclass(frozen=True, slots=True)
class BackgroundTaskOwner:
    package_id: str
    session_id: str
    workspace_root: Path


class BackgroundTaskClient:
    """Submit and control tasks from host or isolated tool processes."""

    def __init__(self, store_path: str | Path) -> None:
        self.store_path = ensure_background_task_schema(store_path)
        self.sessions = SessionRepository(self.store_path)
        self.tasks = TaskRepository(self.store_path)
        self.events = EventRepository(self.store_path)

    @classmethod
    def from_root(cls, root: str | Path) -> "BackgroundTaskClient":
        return cls(background_task_store_path(root))

    def ensure_owner_session(self, owner: BackgroundTaskOwner) -> dict[str, Any]:
        session, _ = self.sessions.create(
            session_id=owner.session_id,
            title=f"{owner.package_id} 后台任务",
            owner_package_id=owner.package_id,
            owner_runtime_session_id=owner.session_id,
            workspace_root=str(owner.workspace_root),
        )
        return session

    def submit(
        self,
        owner: BackgroundTaskOwner,
        *,
        type: BackgroundTaskType,
        request_id: str,
        task_text: str,
        payload: dict[str, Any] | None = None,
        parent_task_id: str | None = None,
        assignee_package_id: str | None = None,
        delivery_standard: dict[str, Any] | None = None,
        visible_context: dict[str, Any] | None = None,
        depends_on: list[str] | None = None,
        input_artifacts: list[dict[str, Any]] | None = None,
    ) -> BackgroundTask:
        self.ensure_owner_session(owner)
        task_id = task_id_for_request(owner.session_id, request_id)
        task, _ = self.tasks.create(
            task_id=task_id,
            session_id=owner.session_id,
            type=type,
            request_id=request_id,
            task_text=task_text,
            payload=payload,
            parent_task_id=parent_task_id,
            parent_package_id=owner.package_id,
            assignee_package_id=assignee_package_id,
            delivery_standard=delivery_standard,
            visible_context=visible_context,
            depends_on=depends_on,
            input_artifacts=input_artifacts,
        )
        return task

    def owned_task(self, owner_session_id: str, task_id: str) -> BackgroundTask:
        task = self.tasks.get(task_id)
        if task.session_id != str(owner_session_id or "").strip():
            raise PermissionError("后台任务不属于当前会话。")
        return task

    def list_owned(self, owner_session_id: str, *, limit: int = 100) -> list[BackgroundTask]:
        return self.tasks.list(session_id=owner_session_id, limit=limit)

    def cancel_owned(
        self,
        owner_session_id: str,
        task_id: str,
        *,
        reason: str,
    ) -> BackgroundTask:
        self.owned_task(owner_session_id, task_id)
        task, _ = self.tasks.request_cancel(task_id, reason=reason)
        return task

    def approve_owned(
        self,
        owner_session_id: str,
        task_id: str,
        *,
        decision: str,
        payload: dict[str, Any],
    ) -> BackgroundTask:
        task = self.owned_task(owner_session_id, task_id)
        pending = task.pending_approval or {}
        request_id = str(pending.get("request_id") or "").strip()
        if not request_id:
            raise ValueError("后台任务没有待处理的审批请求。")
        decision_payload = {**payload, "decision": decision}
        return self.tasks.resolve_approval_and_queue(
            task.task_id,
            request_id=request_id,
            decision=decision,
            decision_payload=decision_payload,
            resume_payload={
                "runtime_request_id": pending.get("runtime_request_id"),
                "resume": decision_payload,
            },
        )

    def resume_owned(
        self,
        owner_session_id: str,
        task_id: str,
        *,
        payload: dict[str, Any],
    ) -> BackgroundTask:
        task = self.owned_task(owner_session_id, task_id)
        pending = task.pending_external or {}
        return self.tasks.resolve_external_and_queue(
            task.task_id,
            resume_payload={
                "runtime_request_id": pending.get("runtime_request_id"),
                "resume": payload,
            },
        )

    def record_child_delivery(
        self,
        task_id: str,
        *,
        assignee_package_id: str,
        assignee_session_id: str,
        result_summary: str,
        result: dict[str, Any],
        artifact_refs: list[dict[str, Any]],
    ) -> BackgroundTask:
        return self.tasks.record_delivery(
            task_id,
            assignee_package_id=assignee_package_id,
            assignee_session_id=assignee_session_id,
            result_summary=result_summary,
            result=result,
            artifact_refs=artifact_refs,
        )


def background_task_store_path(root: str | Path) -> Path:
    resolved = Path(root).expanduser().resolve()
    if resolved == Path(resolved.anchor):
        raise ValueError("background-task root must not be a filesystem root")
    resolved.mkdir(parents=True, exist_ok=True)
    return resolved / BACKGROUND_TASK_STORE_NAME


def task_id_for_request(session_id: str, request_id: str) -> str:
    material = f"{str(session_id).strip()}\0{str(request_id).strip()}".encode("utf-8")
    return sha256(material).hexdigest()[:32]
