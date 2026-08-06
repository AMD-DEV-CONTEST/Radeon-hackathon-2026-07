"""Background-task session persistence and deletion fencing."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from agent_factory.contracts import ConflictError, DomainValidationError, NotFoundError
from agent_factory.sqlite_runtime import sqlite_session


class SessionRepository:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path).expanduser().resolve()

    def create(
        self,
        *,
        title: str,
        owner_package_id: str | None = None,
        owner_runtime_session_id: str | None = None,
        workspace_root: str | None = None,
        session_id: str | None = None,
    ) -> tuple[dict[str, Any], bool]:
        identifier = _required(session_id or uuid4().hex, "session_id")
        record = {
            "session_id": identifier,
            "title": str(title or "").strip() or "后台任务",
            "owner_package_id": _optional(owner_package_id),
            "owner_runtime_session_id": _optional(owner_runtime_session_id),
            "workspace_root": _optional(workspace_root),
        }
        now = _now()
        with sqlite_session(self.path, timeout_ms=10000, foreign_keys=True) as conn:
            conn.execute("begin immediate")
            existing = conn.execute(
                "select * from background_task_sessions where session_id=?",
                (identifier,),
            ).fetchone()
            if existing is not None:
                current = dict(existing)
                comparable = {key: current.get(key) for key in record}
                if comparable != record:
                    raise ConflictError(
                        "session_id 已对应另一后台任务会话。",
                        details={"session_id": identifier},
                    )
                return current, False
            conn.execute(
                """insert into background_task_sessions(
                     session_id,title,owner_package_id,owner_runtime_session_id,workspace_root,
                     status,revision,created_at,updated_at
                   ) values(?,?,?,?,?,'active',0,?,?)""",
                (
                    identifier,
                    record["title"],
                    record["owner_package_id"],
                    record["owner_runtime_session_id"],
                    record["workspace_root"],
                    now,
                    now,
                ),
            )
            row = conn.execute(
                "select * from background_task_sessions where session_id=?",
                (identifier,),
            ).fetchone()
            if row is None:
                raise RuntimeError("background-task session insert returned no row")
            return dict(row), True

    def get(self, session_id: str) -> dict[str, Any]:
        identifier = _required(session_id, "session_id")
        with sqlite_session(self.path, timeout_ms=10000, foreign_keys=True, query_only=True) as conn:
            row = conn.execute(
                "select * from background_task_sessions where session_id=?",
                (identifier,),
            ).fetchone()
            if row is None:
                raise NotFoundError("后台任务会话不存在。", details={"session_id": identifier})
            return dict(row)

    def list(
        self,
        *,
        owner_runtime_session_id: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        clauses: list[str] = ["status != 'deleted'"]
        params: list[object] = []
        if owner_runtime_session_id:
            clauses.append("owner_runtime_session_id=?")
            params.append(str(owner_runtime_session_id).strip())
        params.extend([max(1, min(int(limit), 500)), max(0, int(offset))])
        with sqlite_session(self.path, timeout_ms=10000, foreign_keys=True, query_only=True) as conn:
            rows = conn.execute(
                "select * from background_task_sessions "
                f"where {' and '.join(clauses)} order by updated_at desc,session_id limit ? offset ?",
                tuple(params),
            ).fetchall()
            return [dict(row) for row in rows]

    def mark_deleting(self, session_id: str) -> dict[str, Any]:
        identifier = _required(session_id, "session_id")
        now = _now()
        with sqlite_session(self.path, timeout_ms=10000, foreign_keys=True) as conn:
            conn.execute("begin immediate")
            cursor = conn.execute(
                """update background_task_sessions
                   set status='deleting',updated_at=?,revision=revision+1
                   where session_id=? and status='active'""",
                (now, identifier),
            )
            if cursor.rowcount == 0:
                row = conn.execute(
                    "select * from background_task_sessions where session_id=?",
                    (identifier,),
                ).fetchone()
                if row is None:
                    raise NotFoundError("后台任务会话不存在。", details={"session_id": identifier})
                if str(row["status"]) != "deleting":
                    raise ConflictError("后台任务会话当前不能删除。", details={"session_id": identifier})
                return dict(row)
            row = conn.execute(
                "select * from background_task_sessions where session_id=?",
                (identifier,),
            ).fetchone()
            return dict(row)

    def restore_active(self, session_id: str) -> dict[str, Any]:
        identifier = _required(session_id, "session_id")
        with sqlite_session(self.path, timeout_ms=10000, foreign_keys=True) as conn:
            conn.execute("begin immediate")
            conn.execute(
                """update background_task_sessions
                   set status='active',updated_at=?,revision=revision+1
                   where session_id=? and status='deleting'""",
                (_now(), identifier),
            )
        return self.get(identifier)

    def delete_reclaimed(self, session_id: str) -> dict[str, Any]:
        identifier = _required(session_id, "session_id")
        with sqlite_session(self.path, timeout_ms=10000, foreign_keys=True) as conn:
            conn.execute("begin immediate")
            session = conn.execute(
                "select * from background_task_sessions where session_id=?",
                (identifier,),
            ).fetchone()
            if session is None:
                raise NotFoundError("后台任务会话不存在。", details={"session_id": identifier})
            if str(session["status"]) != "deleting":
                raise ConflictError("后台任务会话尚未进入删除状态。", details={"session_id": identifier})
            unreclaimed = int(
                conn.execute(
                    """select count(*) from background_tasks
                       where session_id=? and (
                         status not in ('succeeded','failed','cancelled')
                         or resources_released_at is null
                         or lease_owner is not null
                       )""",
                    (identifier,),
                ).fetchone()[0]
            )
            if unreclaimed:
                raise ConflictError(
                    "后台任务会话仍有执行资源未回收。",
                    details={"session_id": identifier, "unreclaimed_tasks": unreclaimed},
                )
            snapshot = dict(session)
            conn.execute("delete from background_task_sessions where session_id=?", (identifier,))
            return snapshot


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _required(value: Any, field: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise DomainValidationError(f"{field} 不能为空。")
    return text


def _optional(value: Any) -> str | None:
    text = str(value or "").strip()
    return text or None
