"""One-time import from the retired collaboration task store."""

from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
from typing import Any
from uuid import uuid4

from agent_factory.collaboration_system.persistence.schema import ensure_background_task_schema
from agent_factory.contracts import BackgroundTaskType, task_request_fingerprint
from agent_factory.sqlite_runtime import sqlite_session


@dataclass(frozen=True, slots=True)
class LegacyTaskMigrationReport:
    migrated: bool
    session_count: int = 0
    task_count: int = 0
    event_count: int = 0


def migrate_legacy_background_tasks(
    legacy_path: str | Path,
    target_path: str | Path,
) -> LegacyTaskMigrationReport:
    """Build and validate a canonical store before atomically publishing it."""

    source = Path(legacy_path).expanduser().resolve()
    target = Path(target_path).expanduser().resolve()
    if target.exists() or not source.is_file():
        return LegacyTaskMigrationReport(migrated=False)
    with sqlite_session(source, timeout_ms=10000, foreign_keys=False, query_only=True) as legacy:
        raw_tasks = _read_legacy_tasks(legacy)
        if not raw_tasks:
            return LegacyTaskMigrationReport(migrated=False)
        raw_sessions = (
            [dict(row) for row in legacy.execute("select * from collaboration_sessions").fetchall()]
            if _table_exists(legacy, "collaboration_sessions")
            else []
        )
        raw_events = _read_legacy_events(legacy)

    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(f".{target.name}.migration-{uuid4().hex}.tmp")
    try:
        ensure_background_task_schema(temporary)
        report = _populate_canonical_store(
            temporary,
            raw_sessions=raw_sessions,
            raw_tasks=raw_tasks,
            raw_events=raw_events,
        )
        os.replace(temporary, target)
        return report
    finally:
        temporary.unlink(missing_ok=True)


def _populate_canonical_store(
    target: Path,
    *,
    raw_sessions: list[dict[str, Any]],
    raw_tasks: list[dict[str, Any]],
    raw_events: list[dict[str, Any]],
) -> LegacyTaskMigrationReport:
    sessions_by_id = {
        str(item.get("collaboration_id") or "").strip(): item
        for item in raw_sessions
        if str(item.get("collaboration_id") or "").strip()
    }
    task_ids = _required_unique_ids(raw_tasks, "task_id")
    session_ids = {_required_text(item, "session_id") for item in raw_tasks}
    with sqlite_session(target, timeout_ms=10000, foreign_keys=True) as conn:
        conn.execute("begin immediate")
        for session_id in sorted(session_ids):
            legacy_session = sessions_by_id.get(session_id, {})
            execution_config = _object(legacy_session.get("execution_config_json"))
            conn.execute(
                """insert into background_task_sessions(
                     session_id,title,owner_package_id,owner_runtime_session_id,workspace_root,
                     status,revision,created_at,updated_at
                   ) values(?,?,?,?,?,'active',0,?,?)""",
                (
                    session_id,
                    str(legacy_session.get("title") or "历史后台任务"),
                    _optional(legacy_session.get("main_agent_package_id")),
                    _optional(legacy_session.get("main_agent_package_session_id")),
                    _optional(execution_config.get("parent_workspace_root")),
                    str(legacy_session.get("created_at") or _oldest_timestamp(raw_tasks)),
                    str(legacy_session.get("updated_at") or _latest_timestamp(raw_tasks)),
                ),
            )

        normalized_tasks = _normalize_tasks(raw_tasks, known_task_ids=task_ids)
        for item in normalized_tasks:
            conn.execute(
                """insert into background_tasks(
                     task_id,session_id,type,status,request_id,request_fingerprint,task_text,
                     request_payload_json,parent_task_id,parent_package_id,assignee_package_id,
                     assignee_session_id,delivery_standard_json,visible_context_json,depends_on_json,
                     input_artifacts_json,artifact_refs_json,result_summary,result_payload_json,error_json,
                     lease_requeue_count,cancel_requested_at,cancel_reason,resources_released_at,
                     created_at,updated_at,started_at,completed_at,revision
                   ) values(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,0)""",
                tuple(item[key] for key in _MIGRATED_TASK_COLUMNS),
            )
        for item in normalized_tasks:
            for dependency in item["depends_on"]:
                conn.execute(
                    """insert into background_task_dependencies(
                         task_id,depends_on_task_id,created_at
                       ) values(?,?,?)""",
                    (item["task_id"], dependency, item["created_at"]),
                )

        eligible_events = [
            item
            for item in raw_events
            if (
                not _optional(item.get("task_id"))
                or str(item.get("task_id") or "").strip() in task_ids
            ) and (
                not _optional(item.get("session_id"))
                or str(item.get("session_id") or "").strip() in session_ids
            )
        ]
        for item in eligible_events:
            conn.execute(
                """insert into background_task_events(
                     event_id,event_type,request_id,task_id,session_id,payload_json,created_at
                   ) values(?,?,?,?,?,?,?)""",
                (
                    str(item.get("event_id") or f"legacy-event-{item.get('seq')}-{uuid4().hex}"),
                    str(item.get("kind") or item.get("event_type") or "legacy_task_event"),
                    _optional(item.get("request_id")),
                    _optional(item.get("task_id")),
                    _optional(item.get("session_id")),
                    _json(_object(item.get("payload_json"))),
                    str(item.get("created_at") or _latest_timestamp(raw_tasks)),
                ),
            )
        _validate_migration(
            conn,
            expected_sessions=len(session_ids),
            expected_tasks=len(normalized_tasks),
            expected_events=len(eligible_events),
        )
        conn.commit()
    return LegacyTaskMigrationReport(
        migrated=True,
        session_count=len(session_ids),
        task_count=len(normalized_tasks),
        event_count=len(eligible_events),
    )


_MIGRATED_TASK_COLUMNS = (
    "task_id", "session_id", "type", "status", "request_id", "request_fingerprint",
    "task_text", "request_payload_json", "parent_task_id", "parent_package_id",
    "assignee_package_id", "assignee_session_id", "delivery_standard_json",
    "visible_context_json", "depends_on_json", "input_artifacts_json", "artifact_refs_json",
    "result_summary", "result_payload_json", "error_json", "lease_requeue_count",
    "cancel_requested_at", "cancel_reason", "resources_released_at", "created_at",
    "updated_at", "started_at", "completed_at",
)


def _read_legacy_tasks(conn: Any) -> list[dict[str, Any]]:
    if _table_exists(conn, "background_tasks"):
        return [dict(row) for row in conn.execute("select * from background_tasks").fetchall()]
    tasks: list[dict[str, Any]] = []
    if _table_exists(conn, "collaboration_tasks"):
        for row in conn.execute("select * from collaboration_tasks").fetchall():
            item = dict(row)
            item["session_id"] = item.get("collaboration_id")
            item["type"] = item.get("type") or "sub_agent"
            item["request_id"] = item.get("request_id") or f"legacy:sub_agent:{item.get('task_id')}"
            item["request_payload_json"] = item.get("request_payload_json") or "{}"
            item["assignee_session_id"] = item.get("assignee_session_id") or item.get(
                "assignee_conversation_id"
            )
            tasks.append(item)
    if _table_exists(conn, "collaboration_manufacturing_requests"):
        for row in conn.execute("select * from collaboration_manufacturing_requests").fetchall():
            item = dict(row)
            request_id = str(item.get("request_id") or "").strip()
            tasks.append(
                {
                    **item,
                    "task_id": request_id,
                    "session_id": item.get("collaboration_id"),
                    "type": "manufacture",
                    "request_id": f"legacy:manufacture:{request_id}",
                    "task_text": item.get("purpose") or item.get("agent_name") or "",
                    "assignee_session_id": item.get("create_agent_session_id"),
                    "delivery_standard_json": "{}",
                    "visible_context_json": "{}",
                    "depends_on_json": "[]",
                    "input_artifacts_json": "[]",
                    "artifact_refs_json": "[]",
                    "result_summary": "",
                }
            )
    if _table_exists(conn, "collaboration_evolution_requests"):
        for row in conn.execute("select * from collaboration_evolution_requests").fetchall():
            item = dict(row)
            request_id = str(item.get("request_id") or "").strip()
            payload = _object(item.get("request_payload_json"))
            tasks.append(
                {
                    **item,
                    "task_id": request_id,
                    "session_id": item.get("collaboration_id"),
                    "type": "evolve",
                    "request_id": f"legacy:evolve:{request_id}",
                    "task_text": _legacy_evolution_task_text(payload, item.get("package_id")),
                    "assignee_package_id": item.get("package_id"),
                    "assignee_session_id": item.get("evolution_session_id"),
                    "delivery_standard_json": "{}",
                    "visible_context_json": "{}",
                    "depends_on_json": "[]",
                    "input_artifacts_json": "[]",
                    "artifact_refs_json": "[]",
                    "result_summary": "",
                }
            )
    return tasks


def _read_legacy_events(conn: Any) -> list[dict[str, Any]]:
    if _table_exists(conn, "background_task_events"):
        return [
            dict(row)
            for row in conn.execute("select * from background_task_events order by seq").fetchall()
        ]
    if not _table_exists(conn, "collaboration_main_agent_events"):
        return []
    events: list[dict[str, Any]] = []
    for row in conn.execute(
        "select * from collaboration_main_agent_events order by created_at,event_id"
    ).fetchall():
        item = dict(row)
        payload = _object(item.get("message_metadata_json"))
        payload.update(
            {
                "user_message": str(item.get("user_message") or ""),
                "legacy_status": str(item.get("status") or ""),
                "legacy_attempts": int(item.get("attempts") or 0),
                "legacy_last_error": str(item.get("last_error") or ""),
            }
        )
        events.append(
            {
                "event_id": item.get("event_id"),
                "event_type": "legacy_parent_event",
                "request_id": item.get("event_ref"),
                "task_id": item.get("task_id"),
                "session_id": item.get("collaboration_id"),
                "payload_json": payload,
                "created_at": item.get("created_at"),
            }
        )
    return events


def _legacy_evolution_task_text(payload: dict[str, Any], package_id: Any) -> str:
    for key in ("instruction", "goal", "request", "message", "task_text"):
        value = str(payload.get(key) or "").strip()
        if value:
            return value
    package = str(package_id or "").strip()
    return f"进化 Agent {package}" if package else "进化 Agent"


def _normalize_tasks(
    raw_tasks: list[dict[str, Any]],
    *,
    known_task_ids: set[str],
) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    request_keys: set[tuple[str, str]] = set()
    for raw_task in raw_tasks:
        task = _normalized_task(raw_task, known_task_ids=known_task_ids)
        request_key = (task["session_id"], task["request_id"])
        if request_key in request_keys:
            task["request_id"] = f"{task['request_id']}:{task['task_id']}"
            request_key = (task["session_id"], task["request_id"])
        if request_key in request_keys:
            raise RuntimeError(
                "legacy background-task migration contains duplicate request identity: "
                f"session={request_key[0]}, request={request_key[1]}"
            )
        request_keys.add(request_key)
        normalized.append(task)
    return normalized


def _normalized_task(item: dict[str, Any], *, known_task_ids: set[str]) -> dict[str, Any]:
    task_id = _required_text(item, "task_id")
    session_id = _required_text(item, "session_id")
    task_type = _task_type(item.get("type"))
    task_text = str(item.get("task_text") or "").strip()
    payload = _object(item.get("request_payload_json"))
    parent_task_id = _optional(item.get("parent_task_id"))
    if parent_task_id not in known_task_ids:
        parent_task_id = None
    dependencies = [
        dependency
        for dependency in _string_list(item.get("depends_on_json"))
        if dependency in known_task_ids and dependency != task_id
    ]
    delivery_standard = _object(item.get("delivery_standard_json"))
    visible_context = _object(item.get("visible_context_json"))
    input_artifacts = _list_of_objects(item.get("input_artifacts_json"))
    status, migration_error = _task_status(item.get("status"))
    created_at = str(item.get("created_at") or item.get("updated_at") or "1970-01-01T00:00:00+00:00")
    updated_at = str(item.get("updated_at") or created_at)
    completed_at = _optional(item.get("completed_at"))
    terminal = status in {"succeeded", "failed", "cancelled"}
    request_id = str(item.get("request_id") or f"legacy:{task_id}")
    fingerprint = task_request_fingerprint(
        session_id=session_id,
        type=task_type,
        task_text=task_text,
        payload=payload,
        parent_task_id=parent_task_id,
        assignee_package_id=_optional(item.get("assignee_package_id")),
        assignee_session_id=_optional(item.get("assignee_session_id")),
        delivery_standard=delivery_standard,
        visible_context=visible_context,
        depends_on=dependencies,
        input_artifacts=input_artifacts,
    )
    return {
        "task_id": task_id,
        "session_id": session_id,
        "type": task_type,
        "status": status,
        "request_id": request_id,
        "request_fingerprint": fingerprint,
        "task_text": task_text,
        "request_payload_json": _json(payload),
        "parent_task_id": parent_task_id,
        "parent_package_id": None,
        "assignee_package_id": _optional(item.get("assignee_package_id")),
        "assignee_session_id": _optional(item.get("assignee_session_id")),
        "delivery_standard_json": _json(delivery_standard),
        "visible_context_json": _json(visible_context),
        "depends_on_json": _json(dependencies),
        "depends_on": dependencies,
        "input_artifacts_json": _json(input_artifacts),
        "artifact_refs_json": _json(_list_of_objects(item.get("artifact_refs_json"))),
        "result_summary": str(item.get("result_summary") or ""),
        "result_payload_json": _nullable_json(_object(item.get("result_payload_json"))),
        "error_json": _nullable_json(migration_error or _object(item.get("error_json"))),
        "lease_requeue_count": int(item.get("lease_requeue_count") or 0),
        "cancel_requested_at": _optional(item.get("cancel_requested_at")),
        "cancel_reason": _optional(item.get("cancel_reason")),
        "resources_released_at": (completed_at or updated_at) if terminal else None,
        "created_at": created_at,
        "updated_at": updated_at,
        "started_at": _optional(item.get("started_at")),
        "completed_at": (completed_at or updated_at) if terminal else None,
    }


def _task_type(value: Any) -> BackgroundTaskType:
    normalized = str(value or "").strip()
    mapped = {"agent": "sub_agent"}.get(normalized, normalized)
    if mapped == "sub_agent":
        return "sub_agent"
    if mapped == "manufacture":
        return "manufacture"
    if mapped == "evolve":
        return "evolve"
    raise RuntimeError(f"unsupported legacy background-task type: {normalized or '<empty>'}")


def _task_status(value: Any) -> tuple[str, dict[str, str] | None]:
    status = str(value or "").strip()
    if status in {"assigned", "queued", "requested", "resume_requested", "revision_requested"}:
        return "queued", None
    if status in {"completed", "submitted"}:
        return "succeeded", None
    if status in {"failed", "cancelled"}:
        return status, None
    if status == "blocked":
        return "waiting_external", None
    return "failed", {
        "code": "legacy_incomplete_task",
        "message": "升级时发现未完成的旧后台任务；为避免重复执行，已明确标记为失败。",
        "legacy_status": status,
    }


def _validate_migration(conn: Any, *, expected_sessions: int, expected_tasks: int, expected_events: int) -> None:
    actual = (
        int(conn.execute("select count(*) from background_task_sessions").fetchone()[0]),
        int(conn.execute("select count(*) from background_tasks").fetchone()[0]),
        int(conn.execute("select count(*) from background_task_events").fetchone()[0]),
    )
    expected = (expected_sessions, expected_tasks, expected_events)
    if actual != expected:
        raise RuntimeError(f"background-task migration count mismatch: expected={expected}, actual={actual}")
    violations = conn.execute("pragma foreign_key_check").fetchall()
    if violations:
        raise RuntimeError(f"background-task migration foreign-key violations: {len(violations)}")


def _table_exists(conn: Any, table: str) -> bool:
    return conn.execute(
        "select 1 from sqlite_master where type='table' and name=?",
        (table,),
    ).fetchone() is not None


def _required_unique_ids(items: list[dict[str, Any]], field: str) -> set[str]:
    values: set[str] = set()
    for item in items:
        value = _required_text(item, field)
        if value in values:
            raise RuntimeError(f"duplicate legacy background-task {field}: {value}")
        values.add(value)
    return values


def _required_text(item: dict[str, Any], field: str) -> str:
    value = str(item.get(field) or "").strip()
    if not value:
        raise RuntimeError(f"legacy background-task is missing required field: {field}")
    return value


def _object(value: Any) -> dict[str, Any]:
    parsed = _parsed(value)
    return dict(parsed) if isinstance(parsed, dict) else {}


def _list_of_objects(value: Any) -> list[dict[str, Any]]:
    parsed = _parsed(value)
    return [dict(item) for item in parsed if isinstance(item, dict)] if isinstance(parsed, list) else []


def _string_list(value: Any) -> list[str]:
    parsed = _parsed(value)
    return list(dict.fromkeys(str(item).strip() for item in parsed if str(item).strip())) if isinstance(parsed, list) else []


def _parsed(value: Any) -> Any:
    if not isinstance(value, str):
        return value
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return None


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def _nullable_json(value: dict[str, Any]) -> str | None:
    return _json(value) if value else None


def _optional(value: Any) -> str | None:
    text = str(value or "").strip()
    return text or None


def _oldest_timestamp(tasks: list[dict[str, Any]]) -> str:
    values = sorted(str(item.get("created_at") or "") for item in tasks if item.get("created_at"))
    return values[0] if values else "1970-01-01T00:00:00+00:00"


def _latest_timestamp(tasks: list[dict[str, Any]]) -> str:
    values = sorted(str(item.get("updated_at") or "") for item in tasks if item.get("updated_at"))
    return values[-1] if values else _oldest_timestamp(tasks)
