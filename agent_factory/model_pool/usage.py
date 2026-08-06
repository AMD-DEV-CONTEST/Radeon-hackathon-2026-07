from __future__ import annotations

from collections.abc import Iterable
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Literal
from uuid import uuid4

from agent_factory.model_pool.config import default_model_usage_store_path, resolve_model_pool_store_path
from agent_factory.model_pool.schema import ModelPoolProfile
from agent_factory.model_pool.store import ModelPoolStore
from agent_factory.sqlite_runtime import connect_sqlite, initialize_sqlite_store


ModelUsageGroupBy = Literal["model", "provider", "agent"]
LEGACY_MODEL_POOL_USAGE_MIGRATION = "legacy_model_pool_usage.v1"
SQLITE_BUSY_TIMEOUT_MS = 10000


class ModelUsageStore:
    def __init__(
        self,
        path: str | Path | None = None,
        *,
        model_pool_path: str | Path | None = None,
        setup: bool = True,
    ) -> None:
        self.path = (
            Path(path).expanduser().resolve()
            if path is not None
            else default_model_usage_store_path()
        )
        self.model_pool_path = resolve_model_pool_store_path(model_pool_path)
        if setup:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            initialize_sqlite_store(
                self.path,
                self._initialize,
                timeout_ms=SQLITE_BUSY_TIMEOUT_MS,
                wal=True,
            )

    def _initialize(self) -> None:
        self._ensure_schema()
        self._migrate_legacy_usage()

    def record_frontend_event(self, event_payload: dict[str, Any]) -> bool:
        record = usage_record_from_frontend_event(event_payload, model_pool_path=self.model_pool_path)
        if record is None:
            return False
        with self._connect() as conn:
            cursor = conn.execute(
                """
                insert or ignore into model_usage_events (
                  usage_id, event_id, created_at, request_id, run_id, session_id,
                  collaboration_id, collaboration_task_id,
                  mode, graph_id, node_id, agent_id, agent_label, package_id,
                  model_role, model_profile_id, provider, provider_display_name,
                  model_name, input_tokens, output_tokens, total_tokens,
                  reasoning_tokens, cache_hit_tokens, cache_miss_tokens,
                  estimated_cost, payload_json
                ) values (
                  :usage_id, :event_id, :created_at, :request_id, :run_id, :session_id,
                  :collaboration_id, :collaboration_task_id,
                  :mode, :graph_id, :node_id, :agent_id, :agent_label, :package_id,
                  :model_role, :model_profile_id, :provider, :provider_display_name,
                  :model_name, :input_tokens, :output_tokens, :total_tokens,
                  :reasoning_tokens, :cache_hit_tokens, :cache_miss_tokens,
                  :estimated_cost, :payload_json
                )
                """,
                record,
            )
        return cursor.rowcount > 0

    def summary(self, *, group_by: ModelUsageGroupBy = "model", days: int = 14, limit: int = 12) -> dict[str, Any]:
        safe_days = min(max(int(days), 1), 365)
        safe_limit = min(max(int(limit), 1), 24)
        since = datetime.now(UTC) - timedelta(days=safe_days - 1)
        since_day = since.date().isoformat()
        with self._connect() as conn:
            rows = conn.execute(
                """
                select * from model_usage_events
                where substr(created_at, 1, 10) >= ?
                order by created_at asc
                """,
                (since_day,),
            ).fetchall()
        records = [dict(row) for row in rows]
        groups = _group_records(records, group_by=group_by)
        groups.sort(key=lambda item: int(item["totals"]["total_tokens"] or 0), reverse=True)
        visible_groups = groups[:safe_limit]
        visible_keys = {str(item["key"]) for item in visible_groups}
        return {
            "group_by": group_by,
            "since": since_day,
            "until": datetime.now(UTC).date().isoformat(),
            "totals": _totals(records),
            "groups": groups,
            "series": _series(records, group_by=group_by, visible_keys=visible_keys),
        }

    def collaboration_summary(
        self,
        collaboration_id: str,
        *,
        task_by_session_id: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        clean_id = str(collaboration_id or "").strip()
        if not clean_id:
            raise ValueError("collaboration_id is required")
        session_task_map = {
            str(session_id).strip(): str(task_id or "").strip()
            for session_id, task_id in (task_by_session_id or {}).items()
            if str(session_id).strip()
        }
        with self._connect() as conn:
            session_ids = sorted(session_task_map)
            if session_ids:
                placeholders = ", ".join("?" for _ in session_ids)
                rows = conn.execute(
                    f"""
                    select * from model_usage_events
                    where collaboration_id = ? or session_id in ({placeholders})
                    order by created_at asc, usage_id asc
                    """,
                    (clean_id, *session_ids),
                ).fetchall()
            else:
                rows = conn.execute(
                    """
                    select * from model_usage_events
                    where collaboration_id = ?
                    order by created_at asc, usage_id asc
                    """,
                    (clean_id,),
                ).fetchall()
        records = [dict(row) for row in rows]
        for record in records:
            session_id = str(record.get("session_id") or "").strip()
            if not record.get("collaboration_id") and session_id in session_task_map:
                record["collaboration_id"] = clean_id
            if not record.get("collaboration_task_id") and session_task_map.get(session_id):
                record["collaboration_task_id"] = session_task_map[session_id]
        return {
            "collaboration_id": clean_id,
            "totals": _totals(records),
            "by_agent": _group_records(records, group_by="agent"),
            "by_model": _group_records(records, group_by="model"),
            "by_task": _group_records_by_field(records, field="collaboration_task_id", unknown_key="main_agent"),
            "first_model_call_at": records[0]["created_at"] if records else None,
            "last_model_call_at": records[-1]["created_at"] if records else None,
        }

    @contextmanager
    def _connect(self):
        conn = connect_sqlite(self.path, timeout_ms=SQLITE_BUSY_TIMEOUT_MS)
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def _ensure_schema(self) -> None:
        with self._connect() as conn:
            conn.executescript(
                """
                create table if not exists model_usage_events (
                  usage_id text primary key,
                  event_id text unique,
                  created_at text not null,
                  request_id text,
                  run_id text,
                  session_id text,
                  collaboration_id text,
                  collaboration_task_id text,
                  mode text not null,
                  graph_id text,
                  node_id text,
                  agent_id text,
                  agent_label text,
                  package_id text,
                  model_role text,
                  model_profile_id text,
                  provider text,
                  provider_display_name text,
                  model_name text,
                  input_tokens integer not null default 0,
                  output_tokens integer not null default 0,
                  total_tokens integer not null default 0,
                  reasoning_tokens integer not null default 0,
                  cache_hit_tokens integer not null default 0,
                  cache_miss_tokens integer not null default 0,
                  estimated_cost real,
                  payload_json text not null
                );
                create index if not exists idx_model_usage_created_at on model_usage_events(created_at);
                create index if not exists idx_model_usage_provider on model_usage_events(provider);
                create index if not exists idx_model_usage_model on model_usage_events(model_name);
                create index if not exists idx_model_usage_agent on model_usage_events(agent_id);
                create index if not exists idx_model_usage_profile on model_usage_events(model_profile_id);
                create table if not exists model_usage_migrations (
                  migration_id text primary key,
                  completed_at text not null
                );
                """
            )
            self._ensure_column(conn, "model_usage_events", "collaboration_id", "text")
            self._ensure_column(conn, "model_usage_events", "collaboration_task_id", "text")
            conn.execute(
                "create index if not exists idx_model_usage_collaboration on model_usage_events(collaboration_id, created_at)"
            )
            conn.execute(
                "create index if not exists idx_model_usage_collaboration_task on model_usage_events(collaboration_task_id, created_at)"
            )

    @staticmethod
    def _ensure_column(conn: Any, table: str, column: str, definition: str) -> None:
        columns = {str(row["name"]) for row in conn.execute(f"pragma table_info({table})").fetchall()}
        if column not in columns:
            conn.execute(f"alter table {table} add column {column} {definition}")

    def _migrate_legacy_usage(self) -> None:
        source = self.model_pool_path.resolve()
        if source == self.path or not source.is_file():
            return
        with self._connect() as conn:
            migrated = conn.execute(
                "select 1 from model_usage_migrations where migration_id = ?",
                (LEGACY_MODEL_POOL_USAGE_MIGRATION,),
            ).fetchone()
            if migrated:
                return
            conn.execute("attach database ? as legacy_model_pool", (str(source),))
            try:
                exists = conn.execute(
                    "select 1 from legacy_model_pool.sqlite_master "
                    "where type = 'table' and name = 'model_usage_events'"
                ).fetchone()
                if exists:
                    target_columns = _table_columns(conn, "main", "model_usage_events")
                    source_columns = set(_table_columns(conn, "legacy_model_pool", "model_usage_events"))
                    shared_columns = [column for column in target_columns if column in source_columns]
                    if shared_columns:
                        projection = ", ".join(shared_columns)
                        conn.execute(
                            f"insert or ignore into main.model_usage_events ({projection}) "
                            f"select {projection} from legacy_model_pool.model_usage_events"
                        )
                conn.execute(
                    "insert or ignore into model_usage_migrations(migration_id, completed_at) values (?, ?)",
                    (LEGACY_MODEL_POOL_USAGE_MIGRATION, datetime.now(UTC).isoformat()),
                )
                conn.commit()
            except Exception:
                conn.rollback()
                raise
            finally:
                conn.execute("detach database legacy_model_pool")


def record_model_usage_frontend_event(event_payload: dict[str, Any]) -> bool:
    return ModelUsageStore().record_frontend_event(event_payload)


def usage_record_from_frontend_event(
    event_payload: dict[str, Any],
    *,
    model_pool_path: str | Path | None = None,
) -> dict[str, Any] | None:
    if str(event_payload.get("event_type") or "") != "model_cache_metrics":
        return None
    payload = event_payload.get("payload")
    if not isinstance(payload, dict):
        return None
    provider_cache = payload.get("provider_cache")
    if not isinstance(provider_cache, dict):
        return None
    input_tokens = _positive_int(provider_cache.get("input_tokens"))
    output_tokens = _positive_int(provider_cache.get("output_tokens"))
    total_tokens = _positive_int(provider_cache.get("total_tokens"))
    reasoning_tokens = _positive_int(provider_cache.get("reasoning_tokens"))
    cache_hit_tokens = _positive_int(provider_cache.get("cached_input_tokens"))
    cache_miss_tokens = _positive_int(provider_cache.get("cache_miss_tokens"))
    if cache_miss_tokens is None and input_tokens is not None and cache_hit_tokens is not None:
        cache_miss_tokens = max(0, input_tokens - cache_hit_tokens)
    if total_tokens is None:
        total_tokens = int(input_tokens or 0) + int(output_tokens or 0)
    if not any((input_tokens, output_tokens, total_tokens, reasoning_tokens, cache_hit_tokens, cache_miss_tokens)):
        return None

    profile_id = _text(payload.get("model_profile_id") or payload.get("profile_id"))
    provider = _text(payload.get("engine") or payload.get("provider") or payload.get("model_provider"))
    model_name = _text(payload.get("model") or payload.get("model_name"))
    profile = _resolve_profile(
        profile_id=profile_id,
        provider=provider,
        model_name=model_name,
        store_path=model_pool_path,
    )
    if profile is not None:
        profile_id = profile_id or profile.profile_id
        provider = provider or profile.engine
        model_name = model_name or profile.model_name
    package_id = _text(payload.get("package_id"))
    mode = _text(event_payload.get("mode")) or "unknown"
    agent_id = _agent_id(event_payload=event_payload, payload=payload, package_id=package_id, mode=mode)
    created_at = _text(event_payload.get("timestamp")) or datetime.now(UTC).isoformat()
    return {
        "usage_id": uuid4().hex,
        "event_id": _text(event_payload.get("event_id")) or uuid4().hex,
        "created_at": created_at,
        "request_id": _text(event_payload.get("request_id")),
        "run_id": _text(payload.get("run_id") or event_payload.get("run_id")),
        "session_id": _text(payload.get("session_id") or event_payload.get("session_id")),
        "collaboration_id": _text(payload.get("collaboration_id")),
        "collaboration_task_id": _text(payload.get("collaboration_task_id")),
        "mode": mode,
        "graph_id": _text(event_payload.get("graph_id")),
        "node_id": _text(payload.get("node_id") or event_payload.get("node_id")),
        "agent_id": agent_id,
        "agent_label": _agent_label(event_payload=event_payload, payload=payload, agent_id=agent_id, mode=mode),
        "package_id": package_id,
        "model_role": _text(payload.get("model_role")),
        "model_profile_id": profile_id,
        "provider": provider,
        "provider_display_name": _text(payload.get("provider_display_name")),
        "model_name": model_name,
        "input_tokens": int(input_tokens or 0),
        "output_tokens": int(output_tokens or 0),
        "total_tokens": int(total_tokens or 0),
        "reasoning_tokens": int(reasoning_tokens or 0),
        "cache_hit_tokens": int(cache_hit_tokens or 0),
        "cache_miss_tokens": int(cache_miss_tokens or 0),
        "estimated_cost": _estimated_cost(
            profile=profile,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            reasoning_tokens=reasoning_tokens,
            cache_hit_tokens=cache_hit_tokens,
        ),
        "payload_json": _json_text({"event": event_payload, "payload": payload}),
    }


def _resolve_profile(
    *,
    profile_id: str,
    provider: str,
    model_name: str,
    store_path: str | Path | None,
) -> ModelPoolProfile | None:
    try:
        store = ModelPoolStore(path=store_path)
        if profile_id:
            profile = store.get_profile(profile_id)
            if profile is not None:
                return profile
        if provider and model_name:
            for profile in store.list_profiles():
                if profile.engine == provider and profile.model_name == model_name:
                    return profile
    except Exception:
        return None
    return None


def _estimated_cost(
    *,
    profile: ModelPoolProfile | None,
    input_tokens: int | None,
    output_tokens: int | None,
    reasoning_tokens: int | None,
    cache_hit_tokens: int | None,
) -> float | None:
    del profile, input_tokens, output_tokens, reasoning_tokens, cache_hit_tokens
    return None


def _group_records(records: list[dict[str, Any]], *, group_by: ModelUsageGroupBy) -> list[dict[str, Any]]:
    buckets: dict[str, dict[str, Any]] = {}
    for record in records:
        key = _group_key(record, group_by=group_by)
        item = buckets.setdefault(
            key,
            {
                "key": key,
                "label": _group_label(record, group_by=group_by),
                "provider": record.get("provider") or "",
                "provider_display_name": record.get("provider_display_name") or "",
                "model_name": record.get("model_name") or "",
                "model_profile_id": record.get("model_profile_id") or "",
                "agent_id": record.get("agent_id") or "",
                "agent_label": record.get("agent_label") or "",
                "totals": _empty_totals(),
            },
        )
        _add_totals(item["totals"], record)
    return list(buckets.values())


def _group_records_by_field(
    records: list[dict[str, Any]],
    *,
    field: str,
    unknown_key: str,
) -> list[dict[str, Any]]:
    buckets: dict[str, dict[str, Any]] = {}
    for record in records:
        key = str(record.get(field) or unknown_key)
        item = buckets.setdefault(key, {"key": key, "totals": _empty_totals()})
        _add_totals(item["totals"], record)
    return sorted(
        buckets.values(),
        key=lambda item: int(item["totals"]["total_tokens"] or 0),
        reverse=True,
    )


def _table_columns(conn: Any, database: str, table: str) -> list[str]:
    return [
        str(row["name"])
        for row in conn.execute(f"pragma {database}.table_info({table})").fetchall()
    ]


def _series(
    records: list[dict[str, Any]],
    *,
    group_by: ModelUsageGroupBy,
    visible_keys: set[str],
) -> list[dict[str, Any]]:
    bucketed: dict[str, dict[str, dict[str, Any]]] = {}
    labels: dict[str, str] = {}
    for record in records:
        key = _group_key(record, group_by=group_by)
        if key not in visible_keys:
            continue
        labels.setdefault(key, _group_label(record, group_by=group_by))
        day = str(record.get("created_at") or "")[:10]
        if not day:
            continue
        totals = bucketed.setdefault(key, {}).setdefault(day, _empty_totals())
        _add_totals(totals, record)
    result: list[dict[str, Any]] = []
    for key, points_by_day in bucketed.items():
        result.append(
            {
                "key": key,
                "label": labels.get(key) or key,
                "points": [
                    {"bucket": day, **totals}
                    for day, totals in sorted(points_by_day.items(), key=lambda item: item[0])
                ],
            }
        )
    return result


def _totals(records: Iterable[dict[str, Any]]) -> dict[str, Any]:
    totals = _empty_totals()
    for record in records:
        _add_totals(totals, record)
    return totals


def _empty_totals() -> dict[str, Any]:
    return {
        "call_count": 0,
        "input_tokens": 0,
        "output_tokens": 0,
        "total_tokens": 0,
        "reasoning_tokens": 0,
        "cache_hit_tokens": 0,
        "cache_miss_tokens": 0,
        "cache_hit_ratio": None,
        "estimated_cost": None,
    }


def _add_totals(totals: dict[str, Any], record: dict[str, Any]) -> None:
    totals["call_count"] = int(totals["call_count"] or 0) + 1
    for key in (
        "input_tokens",
        "output_tokens",
        "total_tokens",
        "reasoning_tokens",
        "cache_hit_tokens",
        "cache_miss_tokens",
    ):
        totals[key] = int(totals[key] or 0) + int(record.get(key) or 0)
    if record.get("estimated_cost") is not None:
        totals["estimated_cost"] = round(float(totals["estimated_cost"] or 0) + float(record["estimated_cost"]), 8)
    input_tokens = int(totals["input_tokens"] or 0)
    totals["cache_hit_ratio"] = round(float(totals["cache_hit_tokens"] or 0) / float(input_tokens), 6) if input_tokens else None


def _group_key(record: dict[str, Any], *, group_by: ModelUsageGroupBy) -> str:
    if group_by == "provider":
        return str(record.get("provider") or "unknown_provider")
    if group_by == "agent":
        return str(record.get("agent_id") or "unknown_agent")
    profile = str(record.get("model_profile_id") or "").strip()
    if profile:
        return profile
    provider = str(record.get("provider") or "unknown_provider")
    model = str(record.get("model_name") or "unknown_model")
    return f"{provider}:{model}"


def _group_label(record: dict[str, Any], *, group_by: ModelUsageGroupBy) -> str:
    if group_by == "provider":
        return str(record.get("provider_display_name") or record.get("provider") or "未知厂商")
    if group_by == "agent":
        return str(record.get("agent_label") or record.get("agent_id") or "未知 Agent")
    return str(record.get("model_name") or "未知模型")


def _agent_id(*, event_payload: dict[str, Any], payload: dict[str, Any], package_id: str, mode: str) -> str:
    value = _text(payload.get("agent_id"))
    if value:
        return value
    if package_id:
        return package_id
    if mode == "chat":
        return "factory_chat"
    if mode == "create_agent":
        return "create_agent"
    if mode in {"agent_evolution", "evolve_agent"}:
        return "agent_evolution"
    return _text(event_payload.get("graph_id")) or mode or "unknown_agent"


def _agent_label(*, event_payload: dict[str, Any], payload: dict[str, Any], agent_id: str, mode: str) -> str:
    for value in (payload.get("agent_name"), payload.get("agent_label"), payload.get("package_name")):
        text = _text(value)
        if text:
            return text
    if mode == "chat":
        return "闲聊"
    if mode == "create_agent":
        return "制造 Agent"
    if mode in {"agent_evolution", "evolve_agent"}:
        return "进化 Agent"
    return agent_id or _text(event_payload.get("graph_id")) or "未知 Agent"


def _positive_int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value if value >= 0 else None
    if isinstance(value, float):
        return int(value) if value >= 0 else None
    return None


def _text(value: Any) -> str:
    return str(value or "").strip()


def _json_text(value: Any) -> str:
    import json

    return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)
