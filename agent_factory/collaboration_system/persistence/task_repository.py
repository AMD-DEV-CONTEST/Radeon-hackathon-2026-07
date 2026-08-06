"""Atomic repository for canonical background tasks."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
import json
from pathlib import Path
import sqlite3
from typing import Any, Iterable
from uuid import uuid4

from agent_factory.contracts import (
    BACKGROUND_TASK_STATUSES,
    BACKGROUND_TASK_TYPES,
    BackgroundTask,
    BackgroundTaskType,
    ConflictError,
    DomainValidationError,
    NotFoundError,
    TERMINAL_TASK_STATUSES,
    can_transition_task,
    task_request_fingerprint,
)
from agent_factory.sqlite_runtime import sqlite_session


LEASE_STATUSES = ("claimed", "running", "cancelling")

_FIELD_COLUMNS = {
    "assignee_session_id": "assignee_session_id",
    "visible_context": "visible_context_json",
    "artifact_refs": "artifact_refs_json",
    "result_summary": "result_summary",
    "result": "result_payload_json",
    "error": "error_json",
    "pending_approval": "pending_approval_json",
    "pending_external": "pending_external_json",
    "resume_payload": "resume_payload_json",
    "lease_owner": "lease_owner",
    "lease_token": "lease_token",
    "lease_expires_at": "lease_expires_at",
    "heartbeat_at": "heartbeat_at",
    "lease_requeue_count": "lease_requeue_count",
    "cancel_requested_at": "cancel_requested_at",
    "cancel_reason": "cancel_reason",
    "resources_released_at": "resources_released_at",
    "started_at": "started_at",
    "completed_at": "completed_at",
}
_JSON_COLUMNS = frozenset(
    {
        "request_payload_json",
        "delivery_standard_json",
        "visible_context_json",
        "depends_on_json",
        "input_artifacts_json",
        "artifact_refs_json",
        "result_payload_json",
        "error_json",
        "pending_approval_json",
        "pending_external_json",
        "resume_payload_json",
    }
)


class TaskRepository:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path).expanduser().resolve()

    def create(
        self,
        *,
        session_id: str,
        type: BackgroundTaskType,
        request_id: str,
        task_text: str = "",
        payload: dict[str, Any] | None = None,
        parent_task_id: str | None = None,
        parent_package_id: str | None = None,
        assignee_package_id: str | None = None,
        assignee_session_id: str | None = None,
        delivery_standard: dict[str, Any] | None = None,
        visible_context: dict[str, Any] | None = None,
        depends_on: list[str] | None = None,
        input_artifacts: list[dict[str, Any]] | None = None,
        task_id: str | None = None,
    ) -> tuple[BackgroundTask, bool]:
        clean_session_id = _required(session_id, "session_id")
        clean_request_id = _required(request_id, "request_id")
        clean_task_id = _required(task_id or uuid4().hex, "task_id")
        if type not in BACKGROUND_TASK_TYPES:
            raise DomainValidationError("后台任务类型无效。", details={"type": type})
        dependencies = _clean_ids(depends_on)
        if clean_task_id in dependencies:
            raise DomainValidationError("后台任务不能依赖自身。", details={"task_id": clean_task_id})
        fingerprint = task_request_fingerprint(
            session_id=clean_session_id,
            type=type,
            task_text=task_text,
            payload=payload,
            parent_task_id=parent_task_id,
            parent_package_id=parent_package_id,
            assignee_package_id=assignee_package_id,
            assignee_session_id=assignee_session_id,
            delivery_standard=delivery_standard,
            visible_context=visible_context,
            depends_on=dependencies,
            input_artifacts=input_artifacts,
        )
        now = utc_now_text()
        with self._connect() as conn:
            conn.execute("begin immediate")
            if conn.execute(
                "select 1 from background_task_sessions where session_id=? and status='active'",
                (clean_session_id,),
            ).fetchone() is None:
                raise NotFoundError("后台任务会话不存在或正在删除。", details={"session_id": clean_session_id})
            existing = conn.execute(
                "select * from background_tasks where session_id=? and request_id=?",
                (clean_session_id, clean_request_id),
            ).fetchone()
            if existing is not None:
                current = _task_from_row(existing)
                if current.request_fingerprint != fingerprint:
                    raise ConflictError(
                        "request_id 已用于不同的后台任务请求。",
                        details={"request_id": clean_request_id, "task_id": current.task_id},
                    )
                return current, False
            self._validate_task_reference(conn, parent_task_id, clean_session_id, "parent_task_id")
            for dependency in dependencies:
                self._validate_task_reference(conn, dependency, clean_session_id, "depends_on")
            try:
                conn.execute(
                    """insert into background_tasks(
                         task_id,session_id,type,status,request_id,request_fingerprint,task_text,
                         request_payload_json,parent_task_id,parent_package_id,assignee_package_id,
                         assignee_session_id,delivery_standard_json,visible_context_json,depends_on_json,
                         input_artifacts_json,created_at,updated_at
                       ) values(?,?,?,'queued',?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (
                        clean_task_id,
                        clean_session_id,
                        type,
                        clean_request_id,
                        fingerprint,
                        str(task_text or "").strip(),
                        _json(payload or {}),
                        _optional(parent_task_id),
                        _optional(parent_package_id),
                        _optional(assignee_package_id),
                        _optional(assignee_session_id),
                        _json(delivery_standard or {}),
                        _json(visible_context or {}),
                        _json(dependencies),
                        _json(input_artifacts or []),
                        now,
                        now,
                    ),
                )
                for dependency in dependencies:
                    conn.execute(
                        """insert into background_task_dependencies(
                             task_id,depends_on_task_id,created_at
                           ) values(?,?,?)""",
                        (clean_task_id, dependency, now),
                    )
            except sqlite3.IntegrityError as exc:
                raise ConflictError(
                    "后台任务标识已存在。",
                    details={"task_id": clean_task_id, "request_id": clean_request_id},
                ) from exc
            return self._get(conn, clean_task_id), True

    def get(self, task_id: str) -> BackgroundTask:
        with self._connect() as conn:
            return self._get(conn, _required(task_id, "task_id"))

    def get_by_request_id(self, session_id: str, request_id: str) -> BackgroundTask | None:
        with self._connect() as conn:
            row = conn.execute(
                "select * from background_tasks where session_id=? and request_id=?",
                (_required(session_id, "session_id"), _required(request_id, "request_id")),
            ).fetchone()
            return _task_from_row(row) if row is not None else None

    def request_cancel(self, task_id: str, *, reason: str) -> tuple[BackgroundTask, bool]:
        """Atomically request cancellation without racing the scheduler claim."""

        identifier = _required(task_id, "task_id")
        clean_reason = _required(reason, "reason")
        now = utc_now_text()
        with self._connect() as conn:
            conn.execute("begin immediate")
            current = self._get(conn, identifier)
            if current.status in TERMINAL_TASK_STATUSES or current.status == "cancelling":
                return current, False
            target = "cancelling" if current.lease_owner is not None else "cancelled"
            terminal = target == "cancelled"
            cursor = conn.execute(
                """update background_tasks
                   set status=?,cancel_requested_at=?,cancel_reason=?,
                       pending_approval_json=null,pending_external_json=null,resume_payload_json=null,
                       completed_at=case when ? then ? else completed_at end,
                       resources_released_at=case when ? then coalesce(resources_released_at,?) else null end,
                       updated_at=?,revision=revision+1
                   where task_id=? and status=? and revision=?""",
                (
                    target,
                    now,
                    clean_reason,
                    int(terminal),
                    now,
                    int(terminal),
                    now,
                    now,
                    identifier,
                    current.status,
                    current.revision,
                ),
            )
            if cursor.rowcount != 1:
                raise ConflictError("后台任务已被其他请求修改。", details={"task_id": identifier})
            if current.status == "waiting_approval":
                conn.execute(
                    """update background_task_approvals
                       set status='cancelled',decision_payload_json=?,updated_at=?
                       where task_id=? and status='pending'""",
                    (_json({"reason": clean_reason}), now, identifier),
                )
            return self._get(conn, identifier), True

    def list(
        self,
        *,
        session_id: str | None = None,
        type: str | None = None,
        statuses: Iterable[str] | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[BackgroundTask]:
        clauses: list[str] = []
        params: list[object] = []
        if session_id:
            clauses.append("session_id=?")
            params.append(str(session_id).strip())
        if type:
            if type not in BACKGROUND_TASK_TYPES:
                raise DomainValidationError("后台任务类型无效。", details={"type": type})
            clauses.append("type=?")
            params.append(type)
        clean_statuses = [str(value).strip() for value in statuses or [] if str(value).strip()]
        if any(value not in BACKGROUND_TASK_STATUSES for value in clean_statuses):
            raise DomainValidationError("后台任务状态无效。", details={"statuses": clean_statuses})
        if clean_statuses:
            clauses.append("status in (" + ",".join("?" for _ in clean_statuses) + ")")
            params.extend(clean_statuses)
        where = " where " + " and ".join(clauses) if clauses else ""
        params.extend([max(1, min(int(limit), 500)), max(0, int(offset))])
        with self._connect() as conn:
            rows = conn.execute(
                f"select * from background_tasks{where} order by created_at desc,task_id limit ? offset ?",
                tuple(params),
            ).fetchall()
            return [_task_from_row(row) for row in rows]

    def claim(
        self,
        *,
        owner: str,
        max_parallel: int,
        lease_seconds: int,
    ) -> tuple[list[BackgroundTask], list[BackgroundTask]]:
        clean_owner = _required(owner, "owner")
        if max_parallel <= 0:
            return [], []
        now = datetime.now(UTC)
        now_text = now.isoformat()
        expires_at = (now + timedelta(seconds=max(1, int(lease_seconds)))).isoformat()
        with self._connect() as conn:
            conn.execute("begin immediate")
            dependency_failed_ids = self._fail_tasks_with_terminal_dependencies(conn, now_text)
            dependency_failed = [self._get(conn, task_id) for task_id in dependency_failed_ids]
            active = int(
                conn.execute(
                    """select count(*) from background_tasks
                       where status in (?,?,?) and lease_owner is not null""",
                    LEASE_STATUSES,
                ).fetchone()[0]
            )
            available = max(0, int(max_parallel) - active)
            if not available:
                return [], dependency_failed
            rows = conn.execute(
                """select task.task_id
                   from background_tasks as task
                   where task.status='queued'
                     and not exists (
                       select 1
                       from background_task_dependencies as dependency
                       join background_tasks as prerequisite
                         on prerequisite.task_id=dependency.depends_on_task_id
                       where dependency.task_id=task.task_id
                         and prerequisite.status!='succeeded'
                     )
                   order by task.created_at,task.task_id
                   limit ?""",
                (available,),
            ).fetchall()
            claimed: list[BackgroundTask] = []
            for row in rows:
                task_id = str(row[0])
                token = uuid4().hex
                cursor = conn.execute(
                    """update background_tasks
                       set status='claimed',lease_owner=?,lease_token=?,lease_expires_at=?,
                           heartbeat_at=?,resources_released_at=null,updated_at=?,revision=revision+1
                       where task_id=? and status='queued' and lease_owner is null""",
                    (clean_owner, token, expires_at, now_text, now_text, task_id),
                )
                if cursor.rowcount == 1:
                    claimed.append(self._get(conn, task_id))
            return claimed, dependency_failed

    def transition(
        self,
        task_id: str,
        *,
        to_status: str,
        expected_revision: int | None = None,
        lease_owner: str | None = None,
        lease_token: str | None = None,
        fields: dict[str, Any] | None = None,
    ) -> BackgroundTask:
        identifier = _required(task_id, "task_id")
        if to_status not in BACKGROUND_TASK_STATUSES:
            raise DomainValidationError("后台任务目标状态无效。", details={"status": to_status})
        _require_fence(expected_revision, lease_owner, lease_token)
        with self._connect() as conn:
            conn.execute("begin immediate")
            current = self._get(conn, identifier)
            if not can_transition_task(current.status, to_status):
                raise ConflictError(
                    "后台任务状态转换非法。",
                    details={"task_id": identifier, "from": current.status, "to": to_status},
                )
            assignments = ["status=?", "updated_at=?", "revision=revision+1"]
            params: list[object] = [to_status, utc_now_text()]
            self._append_fields(assignments, params, fields or {})
            where, fence_params = _fence_where(
                identifier,
                current.status,
                expected_revision=expected_revision,
                lease_owner=lease_owner,
                lease_token=lease_token,
            )
            cursor = conn.execute(
                f"update background_tasks set {', '.join(assignments)} where {where}",
                tuple([*params, *fence_params]),
            )
            if cursor.rowcount != 1:
                raise ConflictError("后台任务已被其他执行者修改。", details={"task_id": identifier})
            return self._get(conn, identifier)

    def update_fields(
        self,
        task_id: str,
        *,
        fields: dict[str, Any],
        expected_revision: int | None = None,
        lease_owner: str | None = None,
        lease_token: str | None = None,
    ) -> BackgroundTask:
        identifier = _required(task_id, "task_id")
        if not fields:
            return self.get(identifier)
        _require_fence(expected_revision, lease_owner, lease_token)
        with self._connect() as conn:
            conn.execute("begin immediate")
            current = self._get(conn, identifier)
            assignments = ["updated_at=?", "revision=revision+1"]
            params: list[object] = [utc_now_text()]
            self._append_fields(assignments, params, fields)
            where, fence_params = _fence_where(
                identifier,
                current.status,
                expected_revision=expected_revision,
                lease_owner=lease_owner,
                lease_token=lease_token,
            )
            cursor = conn.execute(
                f"update background_tasks set {', '.join(assignments)} where {where}",
                tuple([*params, *fence_params]),
            )
            if cursor.rowcount != 1:
                raise ConflictError("后台任务已被其他执行者修改。", details={"task_id": identifier})
            return self._get(conn, identifier)

    def record_delivery(
        self,
        task_id: str,
        *,
        assignee_package_id: str,
        assignee_session_id: str,
        result_summary: str,
        result: dict[str, Any],
        artifact_refs: list[dict[str, Any]],
    ) -> BackgroundTask:
        """Persist an authenticated child delivery without changing execution state."""

        identifier = _required(task_id, "task_id")
        package_id = _required(assignee_package_id, "assignee_package_id")
        session_id = _required(assignee_session_id, "assignee_session_id")
        now = utc_now_text()
        with self._connect() as conn:
            conn.execute("begin immediate")
            current = self._get(conn, identifier)
            if current.assignee_package_id != package_id or current.assignee_session_id != session_id:
                raise ConflictError(
                    "子 Agent 身份与后台任务不匹配。",
                    details={"task_id": identifier},
                )
            if current.status != "running":
                raise ConflictError(
                    "只有运行中的后台任务可以交付结果。",
                    details={"task_id": identifier, "status": current.status},
                )
            existing_delivery = current.result.get("delivery") if isinstance(current.result, dict) else None
            incoming_delivery = result.get("delivery") if isinstance(result, dict) else None
            if (
                isinstance(existing_delivery, dict)
                and isinstance(incoming_delivery, dict)
                and existing_delivery.get("delivery_id") == incoming_delivery.get("delivery_id")
            ):
                return current
            merged_result = {**(current.result or {}), **result}
            merged_artifacts = _merge_artifact_refs(current.artifact_refs, artifact_refs)
            cursor = conn.execute(
                """update background_tasks
                   set result_summary=?,result_payload_json=?,artifact_refs_json=?,
                       updated_at=?,revision=revision+1
                   where task_id=? and status='running' and revision=?""",
                (
                    str(result_summary or "").strip(),
                    _json(merged_result),
                    _json(merged_artifacts),
                    now,
                    identifier,
                    current.revision,
                ),
            )
            if cursor.rowcount != 1:
                raise ConflictError("后台任务已被其他请求修改。", details={"task_id": identifier})
            return self._get(conn, identifier)

    def heartbeat(self, task_id: str, *, owner: str, token: str, lease_seconds: int) -> BackgroundTask:
        now = datetime.now(UTC)
        identifier = _required(task_id, "task_id")
        with self._connect() as conn:
            cursor = conn.execute(
                """update background_tasks
                   set heartbeat_at=?,lease_expires_at=?,updated_at=?,revision=revision+1
                   where task_id=? and lease_owner=? and lease_token=?
                     and status in (?,?,?)""",
                (
                    now.isoformat(),
                    (now + timedelta(seconds=max(1, int(lease_seconds)))).isoformat(),
                    now.isoformat(),
                    identifier,
                    _required(owner, "owner"),
                    _required(token, "token"),
                    *LEASE_STATUSES,
                ),
            )
            if cursor.rowcount != 1:
                raise ConflictError("后台任务 lease 已失效。", details={"task_id": identifier})
            return self._get(conn, identifier)

    def complete_execution(
        self,
        task_id: str,
        *,
        outcome: str,
        lease_owner: str,
        lease_token: str,
        fields: dict[str, Any] | None = None,
    ) -> BackgroundTask:
        """Atomically settle an execution, with cancellation taking precedence."""

        if outcome not in TERMINAL_TASK_STATUSES:
            raise DomainValidationError("后台任务执行结果无效。", details={"outcome": outcome})
        identifier = _required(task_id, "task_id")
        owner = _required(lease_owner, "lease_owner")
        token = _required(lease_token, "lease_token")
        now = utc_now_text()
        with self._connect() as conn:
            conn.execute("begin immediate")
            current = self._get(conn, identifier)
            if current.lease_owner != owner or current.lease_token != token:
                raise ConflictError("后台任务 lease 已失效。", details={"task_id": identifier})
            if current.status not in {"claimed", "running", "cancelling"}:
                raise ConflictError(
                    "后台任务当前不能结束执行。",
                    details={"task_id": identifier, "status": current.status},
                )
            target = "cancelled" if current.status == "cancelling" else outcome
            assignments = [
                "status=?",
                "lease_owner=null",
                "lease_token=null",
                "lease_expires_at=null",
                "heartbeat_at=null",
                "pending_approval_json=null",
                "pending_external_json=null",
                "resume_payload_json=null",
                "completed_at=?",
                "updated_at=?",
                "revision=revision+1",
            ]
            params: list[object] = [target, now, now]
            if target == outcome:
                settled_fields = dict(fields or {})
                if target == "succeeded":
                    settled_fields["artifact_refs"] = _merge_artifact_refs(
                        current.artifact_refs,
                        settled_fields.get("artifact_refs")
                        if isinstance(settled_fields.get("artifact_refs"), list)
                        else [],
                    )
                    settled_fields["result"] = {
                        **(current.result or {}),
                        **(
                            settled_fields.get("result")
                            if isinstance(settled_fields.get("result"), dict)
                            else {}
                        ),
                    }
                    if not str(settled_fields.get("result_summary") or "").strip():
                        settled_fields["result_summary"] = current.result_summary
                self._append_fields(assignments, params, settled_fields)
            cursor = conn.execute(
                f"""update background_tasks set {', '.join(assignments)}
                    where task_id=? and status=? and lease_owner=? and lease_token=?""",
                (*params, identifier, current.status, owner, token),
            )
            if cursor.rowcount != 1:
                raise ConflictError("后台任务已被其他执行者修改。", details={"task_id": identifier})
            return self._get(conn, identifier)

    def recover_expired(self, *, max_requeues: int) -> list[dict[str, str]]:
        now = utc_now_text()
        recovered: list[dict[str, str]] = []
        with self._connect() as conn:
            conn.execute("begin immediate")
            rows = conn.execute(
                """select task_id,status,lease_requeue_count
                   from background_tasks
                   where status in (?,?,?)
                     and lease_expires_at is not null and lease_expires_at < ?""",
                (*LEASE_STATUSES, now),
            ).fetchall()
            for row in rows:
                task_id = str(row["task_id"])
                source = str(row["status"])
                requeues = int(row["lease_requeue_count"] or 0)
                if source == "cancelling":
                    target = "cancelled"
                elif requeues + 1 >= max(1, int(max_requeues)):
                    target = "failed"
                else:
                    target = "queued"
                next_requeues = requeues + 1
                terminal = target in TERMINAL_TASK_STATUSES
                error = (
                    _json({"code": "lease_recovery_exhausted", "message": "后台任务执行 lease 多次过期。"})
                    if target == "failed"
                    else None
                )
                conn.execute(
                    """update background_tasks
                       set status=?,lease_owner=null,lease_token=null,lease_expires_at=null,
                           heartbeat_at=null,lease_requeue_count=?,
                           error_json=coalesce(?,error_json),
                           completed_at=case when ? then ? else completed_at end,
                           resources_released_at=?,updated_at=?,revision=revision+1
                       where task_id=?""",
                    (target, next_requeues, error, int(terminal), now, now, now, task_id),
                )
                recovered.append({"task_id": task_id, "from": source, "to": target})
        return recovered

    def mark_resources_released(self, task_id: str) -> BackgroundTask:
        identifier = _required(task_id, "task_id")
        now = utc_now_text()
        with self._connect() as conn:
            conn.execute("begin immediate")
            current = self._get(conn, identifier)
            if current.lease_owner is not None:
                raise ConflictError("后台任务仍持有 lease。", details={"task_id": identifier})
            conn.execute(
                """update background_tasks
                   set resources_released_at=coalesce(resources_released_at,?),updated_at=?,revision=revision+1
                   where task_id=? and lease_owner is null""",
                (now, now, identifier),
            )
            return self._get(conn, identifier)

    def delete_reclaimed(self, task_id: str) -> BackgroundTask:
        identifier = _required(task_id, "task_id")
        with self._connect() as conn:
            conn.execute("begin immediate")
            current = self._get(conn, identifier)
            if (
                current.status not in TERMINAL_TASK_STATUSES
                or current.resources_released_at is None
                or current.lease_owner is not None
            ):
                raise ConflictError(
                    "后台任务尚未完成资源回收，不能删除。",
                    details={"task_id": identifier, "status": current.status},
                )
            conn.execute("delete from background_tasks where task_id=?", (identifier,))
            return current

    def suspend(
        self,
        task_id: str,
        *,
        status: str,
        request_id: str,
        pending_payload: dict[str, Any],
        approval_payload: dict[str, Any] | None,
        lease_owner: str,
        lease_token: str,
        resources_released_at: str,
    ) -> BackgroundTask:
        """Release a running lease and persist its wait request atomically."""

        if status not in {"waiting_approval", "waiting_external"}:
            raise DomainValidationError("后台任务等待状态无效。", details={"status": status})
        identifier = _required(task_id, "task_id")
        clean_request_id = _required(request_id, "request_id")
        owner = _required(lease_owner, "lease_owner")
        token = _required(lease_token, "lease_token")
        now = utc_now_text()
        with self._connect() as conn:
            conn.execute("begin immediate")
            current = self._get(conn, identifier)
            if current.status != "running":
                raise ConflictError(
                    "只有运行中的后台任务可以进入等待状态。",
                    details={"task_id": identifier, "status": current.status},
                )
            if status == "waiting_approval":
                conn.execute(
                    """insert into background_task_approvals(
                         approval_id,task_id,request_id,status,request_payload_json,created_at,updated_at
                       ) values(?,?,?,'pending',?,?,?)
                       on conflict(task_id,request_id) do update set
                         request_payload_json=excluded.request_payload_json,
                         updated_at=excluded.updated_at""",
                    (
                        uuid4().hex,
                        identifier,
                        clean_request_id,
                        _json(approval_payload or {}),
                        now,
                        now,
                    ),
                )
            pending_column = (
                "pending_approval_json" if status == "waiting_approval" else "pending_external_json"
            )
            cursor = conn.execute(
                f"""update background_tasks
                    set status=?,{pending_column}=?,resume_payload_json=null,
                        lease_owner=null,lease_token=null,lease_expires_at=null,heartbeat_at=null,
                        resources_released_at=?,updated_at=?,revision=revision+1
                    where task_id=? and status='running' and lease_owner=? and lease_token=?""",
                (
                    status,
                    _json(pending_payload),
                    _required(resources_released_at, "resources_released_at"),
                    now,
                    identifier,
                    owner,
                    token,
                ),
            )
            if cursor.rowcount != 1:
                raise ConflictError("后台任务 lease 已失效。", details={"task_id": identifier})
            return self._get(conn, identifier)

    def resolve_approval_and_queue(
        self,
        task_id: str,
        *,
        request_id: str,
        decision: str,
        decision_payload: dict[str, Any],
        resume_payload: dict[str, Any] | None,
    ) -> BackgroundTask:
        """Resolve an approval and move its task in the same transaction."""

        if decision not in {"approve", "deny", "trust_tool", "revise"}:
            raise DomainValidationError("审批结果无效。", details={"decision": decision})
        identifier = _required(task_id, "task_id")
        clean_request_id = _required(request_id, "request_id")
        now = utc_now_text()
        approval_status = {
            "approve": "approved",
            "deny": "denied",
            "trust_tool": "approved",
            "revise": "revised",
        }[decision]
        target_status = "queued"
        with self._connect() as conn:
            conn.execute("begin immediate")
            current = self._get(conn, identifier)
            if current.status != "waiting_approval":
                raise ConflictError(
                    "后台任务当前不在等待批准状态。",
                    details={"task_id": identifier, "status": current.status},
                )
            approval = conn.execute(
                """update background_task_approvals
                   set status=?,decision_payload_json=?,updated_at=?
                   where task_id=? and request_id=? and status='pending'""",
                (approval_status, _json(decision_payload), now, identifier, clean_request_id),
            )
            if approval.rowcount != 1:
                raise ConflictError(
                    "审批请求不存在或已经处理。",
                    details={"task_id": identifier, "request_id": clean_request_id},
                )
            task = conn.execute(
                """update background_tasks
                   set status=?,pending_approval_json=null,resume_payload_json=?,
                       lease_owner=null,lease_token=null,lease_expires_at=null,heartbeat_at=null,
                       updated_at=?,revision=revision+1
                   where task_id=? and status='waiting_approval' and revision=?""",
                (
                    target_status,
                    _json(resume_payload) if resume_payload is not None else None,
                    now,
                    identifier,
                    current.revision,
                ),
            )
            if task.rowcount != 1:
                raise ConflictError("后台任务已被其他请求修改。", details={"task_id": identifier})
            return self._get(conn, identifier)

    def resolve_external_and_queue(
        self,
        task_id: str,
        *,
        resume_payload: dict[str, Any],
    ) -> BackgroundTask:
        identifier = _required(task_id, "task_id")
        now = utc_now_text()
        with self._connect() as conn:
            conn.execute("begin immediate")
            current = self._get(conn, identifier)
            if current.status != "waiting_external" or current.pending_external is None:
                raise ConflictError(
                    "后台任务当前不在等待外部条件状态。",
                    details={"task_id": identifier, "status": current.status},
                )
            cursor = conn.execute(
                """update background_tasks
                   set status='queued',pending_external_json=null,resume_payload_json=?,
                       updated_at=?,revision=revision+1
                   where task_id=? and status='waiting_external' and revision=?""",
                (_json(resume_payload), now, identifier, current.revision),
            )
            if cursor.rowcount != 1:
                raise ConflictError("后台任务已被其他请求修改。", details={"task_id": identifier})
            return self._get(conn, identifier)

    def pending_approval(self, task_id: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute(
                """select * from background_task_approvals
                   where task_id=? and status='pending'
                   order by created_at desc,approval_id desc limit 1""",
                (_required(task_id, "task_id"),),
            ).fetchone()
            return _approval_row(row) if row is not None else None

    def _get(self, conn: sqlite3.Connection, task_id: str) -> BackgroundTask:
        row = conn.execute("select * from background_tasks where task_id=?", (task_id,)).fetchone()
        if row is None:
            raise NotFoundError("后台任务不存在。", details={"task_id": task_id})
        return _task_from_row(row)

    @staticmethod
    def _validate_task_reference(
        conn: sqlite3.Connection,
        task_id: str | None,
        session_id: str,
        field: str,
    ) -> None:
        if not task_id:
            return
        row = conn.execute(
            "select session_id from background_tasks where task_id=?",
            (str(task_id).strip(),),
        ).fetchone()
        if row is None or str(row[0]) != session_id:
            raise DomainValidationError(
                "后台任务引用不存在或属于其他会话。",
                details={field: task_id, "session_id": session_id},
            )

    @staticmethod
    def _append_fields(assignments: list[str], params: list[object], fields: dict[str, Any]) -> None:
        for name, value in fields.items():
            column = _FIELD_COLUMNS.get(name)
            if column is None:
                raise DomainValidationError("不允许更新后台任务字段。", details={"field": name})
            assignments.append(f"{column}=?")
            params.append(_json(value) if column in _JSON_COLUMNS and value is not None else value)

    @staticmethod
    def _fail_tasks_with_terminal_dependencies(conn: sqlite3.Connection, now: str) -> list[str]:
        task_ids = [
            str(row[0])
            for row in conn.execute(
                """select distinct background_tasks.task_id
                   from background_tasks
                   join background_task_dependencies as dependency
                     on dependency.task_id=background_tasks.task_id
                   join background_tasks as prerequisite
                     on prerequisite.task_id=dependency.depends_on_task_id
                   where background_tasks.status='queued'
                     and prerequisite.status in ('failed','cancelled')"""
            ).fetchall()
        ]
        if not task_ids:
            return []
        conn.execute(
            """update background_tasks
               set status='failed',
                   error_json='{"code":"dependency_not_satisfied","message":"前置任务未成功完成。"}',
                   completed_at=?,resources_released_at=?,updated_at=?,revision=revision+1
               where status='queued' and exists (
                 select 1
                 from background_task_dependencies as dependency
                 join background_tasks as prerequisite
                   on prerequisite.task_id=dependency.depends_on_task_id
                 where dependency.task_id=background_tasks.task_id
                   and prerequisite.status in ('failed','cancelled')
               )""",
            (now, now, now),
        )
        return task_ids

    def _connect(self):
        return sqlite_session(self.path, timeout_ms=10000, foreign_keys=True)


def _task_from_row(row: sqlite3.Row) -> BackgroundTask:
    value = dict(row)
    return BackgroundTask(
        task_id=str(value["task_id"]),
        session_id=str(value["session_id"]),
        type=value["type"],
        status=value["status"],
        request_id=str(value["request_id"]),
        request_fingerprint=str(value["request_fingerprint"]),
        task_text=str(value.get("task_text") or ""),
        payload=_loads(value.get("request_payload_json"), {}),
        parent_task_id=value.get("parent_task_id"),
        parent_package_id=value.get("parent_package_id"),
        assignee_package_id=value.get("assignee_package_id"),
        assignee_session_id=value.get("assignee_session_id"),
        delivery_standard=_loads(value.get("delivery_standard_json"), {}),
        visible_context=_loads(value.get("visible_context_json"), {}),
        depends_on=_loads(value.get("depends_on_json"), []),
        input_artifacts=_loads(value.get("input_artifacts_json"), []),
        artifact_refs=_loads(value.get("artifact_refs_json"), []),
        result_summary=str(value.get("result_summary") or ""),
        result=_loads(value.get("result_payload_json"), None),
        error=_loads(value.get("error_json"), None),
        pending_approval=_loads(value.get("pending_approval_json"), None),
        pending_external=_loads(value.get("pending_external_json"), None),
        resume_payload=_loads(value.get("resume_payload_json"), None),
        lease_owner=value.get("lease_owner"),
        lease_token=value.get("lease_token"),
        lease_expires_at=value.get("lease_expires_at"),
        heartbeat_at=value.get("heartbeat_at"),
        lease_requeue_count=int(value.get("lease_requeue_count") or 0),
        cancel_requested_at=value.get("cancel_requested_at"),
        cancel_reason=value.get("cancel_reason"),
        resources_released_at=value.get("resources_released_at"),
        created_at=str(value["created_at"]),
        updated_at=str(value["updated_at"]),
        started_at=value.get("started_at"),
        completed_at=value.get("completed_at"),
        revision=int(value.get("revision") or 0),
    )


def _approval_row(row: sqlite3.Row) -> dict[str, Any]:
    value = dict(row)
    value["request_payload"] = _loads(value.pop("request_payload_json", None), {})
    value["decision_payload"] = _loads(value.pop("decision_payload_json", None), None)
    return value


def _fence_where(
    task_id: str,
    status: str,
    *,
    expected_revision: int | None,
    lease_owner: str | None,
    lease_token: str | None,
) -> tuple[str, list[object]]:
    clauses = ["task_id=?", "status=?"]
    params: list[object] = [task_id, status]
    if expected_revision is not None:
        clauses.append("revision=?")
        params.append(int(expected_revision))
    if lease_owner is not None:
        clauses.append("lease_owner=?")
        params.append(_required(lease_owner, "lease_owner"))
    if lease_token is not None:
        clauses.append("lease_token=?")
        params.append(_required(lease_token, "lease_token"))
    return " and ".join(clauses), params


def _require_fence(
    expected_revision: int | None,
    lease_owner: str | None,
    lease_token: str | None,
) -> None:
    has_lease = lease_owner is not None and lease_token is not None
    if expected_revision is None and not has_lease:
        raise DomainValidationError("后台任务更新必须提供 revision 或完整 lease fence。")
    if (lease_owner is None) != (lease_token is None):
        raise DomainValidationError("lease_owner 与 lease_token 必须同时提供。")


def _clean_ids(values: Iterable[str] | None) -> list[str]:
    return list(dict.fromkeys(str(item).strip() for item in values or [] if str(item).strip()))


def _merge_artifact_refs(
    existing: list[dict[str, Any]],
    incoming: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    merged: dict[str, dict[str, Any]] = {}
    for item in [*existing, *incoming]:
        if not isinstance(item, dict):
            continue
        key = str(item.get("path") or item.get("id") or "").strip()
        if key:
            merged[key] = dict(item)
    return list(merged.values())


def _required(value: Any, field: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise DomainValidationError(f"{field} 不能为空。")
    return text


def _optional(value: Any) -> str | None:
    text = str(value or "").strip()
    return text or None


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), default=str)


def _loads(value: Any, fallback: Any) -> Any:
    if value is None or value == "":
        return fallback
    try:
        parsed = json.loads(str(value))
    except (TypeError, ValueError):
        return fallback
    return parsed


def utc_now_text() -> str:
    return datetime.now(UTC).isoformat()
