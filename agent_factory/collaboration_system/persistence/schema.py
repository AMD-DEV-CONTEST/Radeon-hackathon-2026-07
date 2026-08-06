"""Schema owned exclusively by the unified background-task subsystem."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
import sqlite3

from agent_factory.collaboration_system.capacity import DEFAULT_MAX_PARALLEL_SUB_AGENTS
from agent_factory.sqlite_runtime import sqlite_session


SCHEMA_VERSION = 1


def ensure_background_task_schema(path: str | Path) -> Path:
    """Create the canonical schema or verify that an existing store is canonical."""

    resolved = Path(path).expanduser().resolve()
    resolved.parent.mkdir(parents=True, exist_ok=True)
    create_new = not resolved.exists() or resolved.stat().st_size == 0
    with sqlite_session(resolved, timeout_ms=10000, foreign_keys=True) as conn:
        if create_new:
            conn.execute("begin immediate")
            _apply_schema(conn)
        else:
            _verify_schema(conn, resolved)
        version_row = conn.execute(
            "select schema_version from background_task_schema where singleton=1"
        ).fetchone()
        version = int(version_row[0]) if version_row is not None else 0
        if version != SCHEMA_VERSION:
            raise RuntimeError(
                f"unsupported background-task schema version {version}; expected {SCHEMA_VERSION}"
            )
        conn.commit()
    return resolved


def _verify_schema(conn: sqlite3.Connection, path: Path) -> None:
    required_tables = {
        "background_task_schema",
        "background_task_settings",
        "background_task_sessions",
        "background_tasks",
        "background_task_dependencies",
        "background_task_events",
        "background_task_approvals",
    }
    existing = {
        str(row[0])
        for row in conn.execute("select name from sqlite_master where type='table'").fetchall()
    }
    missing = sorted(required_tables - existing)
    if missing:
        raise RuntimeError(
            f"background-task store requires versioned migration before use: {path}; "
            "missing tables: " + ", ".join(missing)
        )
    required_columns = {
        "background_task_settings": {"max_parallel_sub_agents", "revision"},
        "background_task_sessions": {"session_id", "status", "revision"},
        "background_tasks": {
            "task_id",
            "session_id",
            "type",
            "status",
            "request_id",
            "request_fingerprint",
            "lease_owner",
            "lease_token",
            "lease_expires_at",
            "heartbeat_at",
            "resources_released_at",
            "revision",
        },
        "background_task_events": {"seq", "event_id", "task_id", "session_id"},
    }
    for table, expected in required_columns.items():
        columns = {str(row[1]) for row in conn.execute(f"pragma table_info({table})").fetchall()}
        missing_columns = sorted(expected - columns)
        if missing_columns:
            raise RuntimeError(
                f"background-task store requires versioned migration before use: {path}; "
                f"{table} is missing columns: " + ", ".join(missing_columns)
            )


def _apply_schema(conn: sqlite3.Connection) -> None:
    now = datetime.now(UTC).isoformat()
    conn.executescript(
        """
        create table if not exists background_task_schema (
          singleton integer primary key check(singleton = 1),
          schema_version integer not null,
          applied_at text not null
        );

        create table if not exists background_task_settings (
          singleton integer primary key check(singleton = 1),
          max_parallel_sub_agents integer not null check(max_parallel_sub_agents > 0),
          revision integer not null default 0 check(revision >= 0),
          updated_at text not null
        );

        create table if not exists background_task_sessions (
          session_id text primary key,
          title text not null,
          owner_package_id text,
          owner_runtime_session_id text,
          workspace_root text,
          status text not null check(status in ('active','deleting','deleted')),
          revision integer not null default 0 check(revision >= 0),
          created_at text not null,
          updated_at text not null
        );
        create index if not exists idx_background_task_sessions_owner
          on background_task_sessions(owner_runtime_session_id, updated_at desc);

        create table if not exists background_tasks (
          task_id text primary key,
          session_id text not null references background_task_sessions(session_id) on delete cascade,
          type text not null check(type in ('sub_agent','manufacture','evolve')),
          status text not null check(status in (
            'queued','claimed','running','waiting_approval','waiting_external',
            'cancelling','succeeded','failed','cancelled'
          )),
          request_id text not null,
          request_fingerprint text not null,
          task_text text not null default '',
          request_payload_json text not null default '{}',
          parent_task_id text references background_tasks(task_id) on delete set null,
          parent_package_id text,
          assignee_package_id text,
          assignee_session_id text,
          delivery_standard_json text not null default '{}',
          visible_context_json text not null default '{}',
          depends_on_json text not null default '[]',
          input_artifacts_json text not null default '[]',
          artifact_refs_json text not null default '[]',
          result_summary text not null default '',
          result_payload_json text,
          error_json text,
          pending_approval_json text,
          pending_external_json text,
          resume_payload_json text,
          lease_owner text,
          lease_token text,
          lease_expires_at text,
          heartbeat_at text,
          lease_requeue_count integer not null default 0 check(lease_requeue_count >= 0),
          cancel_requested_at text,
          cancel_reason text,
          resources_released_at text,
          revision integer not null default 0 check(revision >= 0),
          created_at text not null,
          updated_at text not null,
          started_at text,
          completed_at text,
          unique(session_id, request_id),
          check((lease_owner is null) = (lease_token is null)),
          check(lease_owner is null or resources_released_at is null)
        );
        create index if not exists idx_background_tasks_queue
          on background_tasks(status, created_at, task_id);
        create index if not exists idx_background_tasks_session
          on background_tasks(session_id, created_at, task_id);
        create index if not exists idx_background_tasks_lease
          on background_tasks(status, lease_expires_at);

        create table if not exists background_task_dependencies (
          task_id text not null references background_tasks(task_id) on delete cascade,
          depends_on_task_id text not null references background_tasks(task_id) on delete cascade,
          created_at text not null,
          primary key(task_id, depends_on_task_id),
          check(task_id != depends_on_task_id)
        );
        create index if not exists idx_background_task_dependencies_target
          on background_task_dependencies(depends_on_task_id, task_id);

        create table if not exists background_task_events (
          seq integer primary key autoincrement,
          event_id text not null unique,
          event_type text not null,
          request_id text,
          task_id text references background_tasks(task_id) on delete set null,
          session_id text references background_task_sessions(session_id) on delete set null,
          payload_json text not null default '{}',
          created_at text not null
        );
        create index if not exists idx_background_task_events_task
          on background_task_events(task_id, seq);
        create index if not exists idx_background_task_events_session
          on background_task_events(session_id, seq);

        create table if not exists background_task_approvals (
          approval_id text primary key,
          task_id text not null references background_tasks(task_id) on delete cascade,
          request_id text not null,
          status text not null check(status in ('pending','approved','denied','revised','cancelled')),
          request_payload_json text not null default '{}',
          decision_payload_json text,
          created_at text not null,
          updated_at text not null,
          unique(task_id, request_id)
        );
        create index if not exists idx_background_task_approvals_pending
          on background_task_approvals(task_id, status, created_at);
        """
    )
    conn.execute(
        """insert into background_task_schema(singleton,schema_version,applied_at)
           values(1,?,?)
           on conflict(singleton) do nothing""",
        (SCHEMA_VERSION, now),
    )
    conn.execute(
        """insert into background_task_settings(singleton,max_parallel_sub_agents,revision,updated_at)
           values(1,?,0,?)
           on conflict(singleton) do nothing""",
        (DEFAULT_MAX_PARALLEL_SUB_AGENTS, now),
    )
