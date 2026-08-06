from __future__ import annotations

import argparse
from datetime import UTC, datetime
import hashlib
import json
from pathlib import Path
from collections.abc import Iterator
from typing import Any

from langgraph.store.base import BaseStore, SearchItem

from agent_factory.file_lock import exclusive_file_lock
from agent_factory.memory_system.namespace import agent_memory_namespace, workspace_memory_namespace
from agent_factory.memory_system.scopes import application_memory_store_path
from agent_factory.runtime_kernel.persistence import LangGraphStoreConfig, LangGraphStoreFactory
from agent_factory.runtime_kernel.session import AgentSessionConfig, AgentSessionManager


MIGRATION_VERSION = "workspace_memory_v1"
MIGRATION_PAGE_SIZE = 256


def migrate_legacy_agent_memory(
    *,
    source_store: BaseStore,
    target_store: BaseStore,
    agent_id: str,
    session_root: Path,
    log_path: Path,
) -> dict[str, Any]:
    lock_path = log_path.with_suffix(f"{log_path.suffix}.lock")
    with exclusive_file_lock(lock_path):
        return _migrate_legacy_agent_memory_locked(
            source_store=source_store,
            target_store=target_store,
            agent_id=agent_id,
            session_root=session_root,
            log_path=log_path,
        )


def _migrate_legacy_agent_memory_locked(
    *,
    source_store: BaseStore,
    target_store: BaseStore,
    agent_id: str,
    session_root: Path,
    log_path: Path,
) -> dict[str, Any]:
    existing_log = _read_log(log_path)
    if (
        existing_log.get("version") == MIGRATION_VERSION
        and existing_log.get("status") == "completed"
        and not existing_log.get("source_missing")
    ):
        return existing_log

    started_at = _now()
    report: dict[str, Any] = {
        "version": MIGRATION_VERSION,
        "status": "running",
        "agent_id": agent_id,
        "started_at": started_at,
        "completed_at": None,
        "scanned_count": 0,
        "copied_count": 0,
        "skipped_count": 0,
        "failed_items": [],
        "target_counts": {"agent": 0, "workspace": 0},
    }
    _write_log(log_path, report)
    sessions = AgentSessionManager(AgentSessionConfig(root=session_root))
    source_namespace = agent_memory_namespace(agent_id)
    for item in _iter_store_items(source_store, source_namespace):
        report["scanned_count"] += 1
        try:
            _copy_item(
                target_store=target_store,
                namespace=source_namespace,
                key=item.key,
                value=_migrated_value(
                    item=item,
                    scope="agent",
                    key=item.key,
                    source_namespace=source_namespace,
                ),
                report=report,
                target_scope="agent",
            )
            source = dict(item.value or {}).get("source")
            session_id = str(source.get("session_id") or "").strip() if isinstance(source, dict) else ""
            workspace_id = _workspace_id_for_source(sessions, session_id=session_id)
            if workspace_id:
                workspace_namespace = workspace_memory_namespace(workspace_id)
                workspace_key = _workspace_migration_key(
                    source_namespace=source_namespace,
                    source_key=item.key,
                    workspace_id=workspace_id,
                )
                _copy_item(
                    target_store=target_store,
                    namespace=workspace_namespace,
                    key=workspace_key,
                    value=_migrated_value(
                        item=item,
                        scope="workspace",
                        key=workspace_key,
                        source_namespace=source_namespace,
                    ),
                    report=report,
                    target_scope="workspace",
                )
        except Exception as exc:
            report["failed_items"].append(
                {
                    "namespace": list(item.namespace),
                    "key": item.key,
                    "error": f"{type(exc).__name__}: {exc}",
                }
            )
    report["status"] = "failed" if report["failed_items"] else "completed"
    report["completed_at"] = _now()
    _write_log(log_path, report)
    return report


def _workspace_id_for_source(
    sessions: AgentSessionManager,
    *,
    session_id: str,
) -> str | None:
    if not session_id:
        return None
    try:
        session = sessions.load_optional(session_id)
    except Exception:
        return None
    return str(session.workspace_id or "").strip() if session is not None else None


def migrate_legacy_sqlite_memory(
    *,
    source_path: Path,
    target_store: BaseStore,
    agent_id: str,
    session_root: Path,
    log_path: Path,
) -> dict[str, Any]:
    resolved_source = source_path.expanduser().resolve()
    if not resolved_source.is_file():
        with exclusive_file_lock(log_path.with_suffix(f"{log_path.suffix}.lock")):
            existing_log = _read_log(log_path)
            if existing_log.get("version") == MIGRATION_VERSION and existing_log.get("status") == "completed":
                return existing_log
            report = {
                "version": MIGRATION_VERSION,
                "status": "completed",
                "agent_id": agent_id,
                "started_at": _now(),
                "completed_at": _now(),
                "scanned_count": 0,
                "copied_count": 0,
                "skipped_count": 0,
                "failed_items": [],
                "target_counts": {"agent": 0, "workspace": 0},
                "source_missing": True,
            }
            _write_log(log_path, report)
            return report
    source_store = LangGraphStoreFactory().build(
        LangGraphStoreConfig(backend="sqlite", path=resolved_source, setup=True)
    ).store
    return migrate_legacy_agent_memory(
        source_store=source_store,
        target_store=target_store,
        agent_id=agent_id,
        session_root=session_root,
        log_path=log_path,
    )


def _iter_store_items(
    store: BaseStore,
    namespace: tuple[str, ...],
) -> Iterator[SearchItem]:
    offset = 0
    while True:
        page = store.search(
            namespace,
            query=None,
            limit=MIGRATION_PAGE_SIZE,
            offset=offset,
        )
        yield from page
        if len(page) < MIGRATION_PAGE_SIZE:
            return
        offset += len(page)


def _copy_item(
    *,
    target_store: BaseStore,
    namespace: tuple[str, ...],
    key: str,
    value: dict[str, Any],
    report: dict[str, Any],
    target_scope: str,
) -> None:
    if target_store.get(namespace, key) is not None:
        report["skipped_count"] += 1
        return
    target_store.put(namespace, key, value)
    report["copied_count"] += 1
    report["target_counts"][target_scope] += 1


def _migrated_value(
    *,
    item: SearchItem,
    scope: str,
    key: str,
    source_namespace: tuple[str, ...],
) -> dict[str, Any]:
    value = dict(item.value or {})
    metadata = dict(value.get("metadata") or {})
    metadata["migration"] = {
        "version": MIGRATION_VERSION,
        "source_namespace": list(source_namespace),
        "source_key": item.key,
    }
    return {
        **value,
        "memory_id": key,
        "scope": scope,
        "metadata": metadata,
        "updated_at": str(value.get("updated_at") or getattr(item, "updated_at", "") or _now()),
    }


def _workspace_migration_key(
    *,
    source_namespace: tuple[str, ...],
    source_key: str,
    workspace_id: str,
) -> str:
    identity = json.dumps(
        {
            "source_namespace": list(source_namespace),
            "source_key": source_key,
            "workspace_id": workspace_id,
        },
        ensure_ascii=False,
        sort_keys=True,
    )
    return hashlib.sha256(identity.encode("utf-8")).hexdigest()


def _read_log(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def _write_log(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(f"{path.suffix}.tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


def _now() -> str:
    return datetime.now(UTC).isoformat()


def main() -> None:
    parser = argparse.ArgumentParser(description="Migrate legacy Agent memory into scoped application memory.")
    parser.add_argument("--source-db", type=Path, required=True)
    parser.add_argument("--session-root", type=Path, required=True)
    parser.add_argument("--agent-id", required=True)
    parser.add_argument("--log-path", type=Path, required=True)
    parser.add_argument("--target-db", type=Path, default=application_memory_store_path())
    arguments = parser.parse_args()
    target_store = LangGraphStoreFactory().build(
        LangGraphStoreConfig(backend="sqlite", path=arguments.target_db.expanduser().resolve(), setup=True)
    ).store
    report = migrate_legacy_sqlite_memory(
        source_path=arguments.source_db,
        target_store=target_store,
        agent_id=arguments.agent_id,
        session_root=arguments.session_root,
        log_path=arguments.log_path,
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
