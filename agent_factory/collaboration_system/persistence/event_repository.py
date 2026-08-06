"""Durable lifecycle events with a database-assigned global cursor."""

from __future__ import annotations

import json
from pathlib import Path
import sqlite3
from typing import Any
from uuid import uuid4

from agent_factory.collaboration_system.persistence.task_repository import utc_now_text
from agent_factory.contracts import EventEnvelope, NotFoundError
from agent_factory.sqlite_runtime import sqlite_session


TASK_TIMELINE_EVENT_TYPES = (
    "background_task_created",
    "background_task_status_changed",
    "background_task_progress_report",
    "background_task_approval_resolved",
    "background_task_external_resolved",
    "background_task_requeued",
    "background_task_recovered",
    "background_task_result",
)


class EventRepository:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path).expanduser().resolve()

    def append(
        self,
        *,
        event_type: str,
        task_id: str | None = None,
        session_id: str | None = None,
        request_id: str | None = None,
        payload: dict[str, Any] | None = None,
        event_id: str | None = None,
    ) -> EventEnvelope:
        identifier = str(event_id or uuid4().hex).strip() or uuid4().hex
        timestamp = utc_now_text()
        with sqlite_session(self.path, timeout_ms=10000, foreign_keys=True) as conn:
            conn.execute("begin immediate")
            existing = conn.execute(
                "select * from background_task_events where event_id=?",
                (identifier,),
            ).fetchone()
            if existing is not None:
                return _event_from_row(existing)
            try:
                cursor = conn.execute(
                    """insert into background_task_events(
                         event_id,event_type,request_id,task_id,session_id,payload_json,created_at
                       ) values(?,?,?,?,?,?,?)""",
                    (
                        identifier,
                        str(event_type or "runtime"),
                        _optional(request_id),
                        _optional(task_id),
                        _optional(session_id),
                        json.dumps(payload or {}, ensure_ascii=False, separators=(",", ":"), default=str),
                        timestamp,
                    ),
                )
            except sqlite3.IntegrityError as exc:
                raise NotFoundError(
                    "后台任务事件引用的任务或会话不存在。",
                    details={"event_id": identifier},
                ) from exc
            row = conn.execute(
                "select * from background_task_events where seq=?",
                (int(cursor.lastrowid),),
            ).fetchone()
            if row is None:
                raise RuntimeError("background-task event insert returned no row")
            return _event_from_row(row)

    def list_after(
        self,
        *,
        after_seq: int = 0,
        task_id: str | None = None,
        session_id: str | None = None,
        limit: int = 500,
    ) -> list[EventEnvelope]:
        clauses = ["seq > ?"]
        params: list[object] = [max(0, int(after_seq))]
        if task_id:
            clauses.append("task_id=?")
            params.append(str(task_id).strip())
        if session_id:
            clauses.append("session_id=?")
            params.append(str(session_id).strip())
        params.append(max(1, min(int(limit), 5000)))
        with sqlite_session(
            self.path,
            timeout_ms=10000,
            foreign_keys=True,
            query_only=True,
        ) as conn:
            rows = conn.execute(
                "select * from background_task_events "
                f"where {' and '.join(clauses)} order by seq limit ?",
                tuple(params),
            ).fetchall()
            return [_event_from_row(row) for row in rows]

    def list_task_timeline_after(
        self,
        task_id: str,
        *,
        after_seq: int = 0,
        limit: int = 500,
    ) -> list[EventEnvelope]:
        """Read the compact user-facing lifecycle, excluding transport and lease events."""

        placeholders = ",".join("?" for _ in TASK_TIMELINE_EVENT_TYPES)
        with sqlite_session(
            self.path,
            timeout_ms=10000,
            foreign_keys=True,
            query_only=True,
        ) as conn:
            rows = conn.execute(
                "select * from background_task_events "
                f"where seq>? and task_id=? and event_type in ({placeholders}) "
                "order by seq limit ?",
                (
                    max(0, int(after_seq)),
                    str(task_id).strip(),
                    *TASK_TIMELINE_EVENT_TYPES,
                    max(1, min(int(limit), 5000)),
                ),
            ).fetchall()
            return [_event_from_row(row) for row in rows]

    def latest_seq(self) -> int:
        with sqlite_session(
            self.path,
            timeout_ms=10000,
            foreign_keys=True,
            query_only=True,
        ) as conn:
            return int(conn.execute("select coalesce(max(seq),0) from background_task_events").fetchone()[0])


def _event_from_row(row: Any) -> EventEnvelope:
    value = dict(row)
    try:
        payload = json.loads(str(value.get("payload_json") or "{}"))
    except (TypeError, ValueError):
        payload = {}
    return EventEnvelope(
        seq=int(value["seq"]),
        event_id=str(value["event_id"]),
        event_type=str(value["event_type"]),
        created_at=str(value["created_at"]),
        request_id=value.get("request_id"),
        task_id=value.get("task_id"),
        session_id=value.get("session_id"),
        payload=payload if isinstance(payload, dict) else {},
    )


def _optional(value: Any) -> str | None:
    text = str(value or "").strip()
    return text or None
