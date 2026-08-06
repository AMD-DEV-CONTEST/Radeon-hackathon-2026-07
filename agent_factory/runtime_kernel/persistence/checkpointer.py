from __future__ import annotations

import atexit
from contextlib import closing
from dataclasses import dataclass
import importlib
from pathlib import Path
import sqlite3
import threading
from typing import Any, Literal

from agent_factory.sqlite_runtime import connect_sqlite, sqlite_session


LangGraphCheckpointerBackend = Literal["sqlite", "memory"]

@dataclass(frozen=True, slots=True)
class _SharedSQLiteCheckpointer:
    saver: Any
    connection: sqlite3.Connection


_CHECKPOINTER_REGISTRY_LOCK = threading.RLock()
_SQLITE_CHECKPOINTERS: dict[Path, _SharedSQLiteCheckpointer] = {}
_PERSISTENT_CHECKPOINTER_IDS: set[int] = set()


@dataclass(frozen=True, slots=True)
class LangGraphCheckpointerConfig:
    backend: LangGraphCheckpointerBackend = "sqlite"
    path: Path | None = None


@dataclass(frozen=True, slots=True)
class LangGraphCheckpointerHandle:
    saver: Any
    backend: LangGraphCheckpointerBackend
    persistent: bool
    path: Path | None = None


class LangGraphCheckpointerFactory:
    def build(self, config: LangGraphCheckpointerConfig) -> LangGraphCheckpointerHandle:
        if config.backend == "memory":
            return LangGraphCheckpointerHandle(
                saver=importlib.import_module("langgraph.checkpoint.memory").InMemorySaver(),
                backend="memory",
                persistent=False,
                path=None,
            )
        if config.path is None:
            raise ValueError("SQLite checkpointer requires a checkpoint path.")
        return self._build_sqlite(config.path)

    def _build_sqlite(self, checkpoint_path: Path) -> LangGraphCheckpointerHandle:
        try:
            sqlite_saver = importlib.import_module("langgraph.checkpoint.sqlite").SqliteSaver
        except ModuleNotFoundError as exc:
            raise RuntimeError(
                "SQLite checkpointer backend is configured, but langgraph-checkpoint-sqlite "
                "is not installed. Install the SQLite checkpointer package or select memory "
                "for a non-persistent debug run."
            ) from exc
        resolved_path = checkpoint_path.expanduser().resolve()
        resolved_path.parent.mkdir(parents=True, exist_ok=True)
        with _CHECKPOINTER_REGISTRY_LOCK:
            shared = _SQLITE_CHECKPOINTERS.get(resolved_path)
            if shared is None:
                connection = connect_sqlite(
                    resolved_path,
                    check_same_thread=False,
                )
                saver = sqlite_saver(connection)
                shared = _SharedSQLiteCheckpointer(saver=saver, connection=connection)
                _SQLITE_CHECKPOINTERS[resolved_path] = shared
                _PERSISTENT_CHECKPOINTER_IDS.add(id(saver))
        return LangGraphCheckpointerHandle(
            saver=shared.saver,
            backend="sqlite",
            persistent=True,
            path=resolved_path,
        )


def is_checkpointer_persistent(checkpointer: object | None) -> bool:
    return id(checkpointer) in _PERSISTENT_CHECKPOINTER_IDS


def delete_checkpoint_thread(checkpointer: Any, thread_id: str) -> bool:
    normalized_thread_id = str(thread_id or "").strip()
    if not normalized_thread_id:
        return False
    delete_thread = getattr(checkpointer, "delete_thread", None)
    if not callable(delete_thread):
        return False
    delete_thread(normalized_thread_id)
    return True


def delete_sqlite_checkpoint_thread(checkpoint_path: Path, thread_id: str) -> bool:
    normalized_thread_id = str(thread_id or "").strip()
    if not normalized_thread_id:
        return False
    path = checkpoint_path.expanduser().resolve()
    if not path.is_file():
        return False
    sqlite_saver = importlib.import_module("langgraph.checkpoint.sqlite").SqliteSaver
    with closing(connect_sqlite(path, check_same_thread=False)) as connection:
        saver = sqlite_saver(connection)
        return delete_checkpoint_thread(saver, normalized_thread_id)


def migrate_legacy_instance_checkpoints(checkpoint_path: Path) -> int:
    """Merge pre-package-scope checkpoint databases into one package store.

    Older runtimes created one database below ``instances/<hash>`` for each
    session bridge. The migration is additive and idempotent: source databases
    remain untouched and existing package-store rows win on key conflicts.
    """

    target = checkpoint_path.expanduser().resolve()
    legacy_root = target.parent / "instances"
    sources = sorted(
        path.resolve()
        for path in legacy_root.glob(f"*/{target.name}")
        if path.is_file() and path.resolve() != target
    )
    if not sources:
        return 0
    sqlite_saver = importlib.import_module("langgraph.checkpoint.sqlite").SqliteSaver
    target.parent.mkdir(parents=True, exist_ok=True)
    with closing(connect_sqlite(target, check_same_thread=False)) as connection:
        saver = sqlite_saver(connection)
        setup = getattr(saver, "setup", None)
        if callable(setup):
            setup()
    migrated = 0
    with sqlite_session(target, timeout_ms=30000) as conn:
        for index, source in enumerate(sources):
            alias = f"legacy_{index}"
            conn.execute(f"attach database ? as {alias}", (str(source),))
            try:
                tables = {
                    str(row[0])
                    for row in conn.execute(
                        f"select name from {alias}.sqlite_master where type = 'table'"
                    ).fetchall()
                }
                if "checkpoints" in tables:
                    before = conn.total_changes
                    conn.execute(
                        f"insert or ignore into main.checkpoints select * from {alias}.checkpoints"
                    )
                    migrated += conn.total_changes - before
                if "writes" in tables:
                    conn.execute(f"insert or ignore into main.writes select * from {alias}.writes")
                conn.commit()
            except Exception:
                conn.rollback()
                raise
            finally:
                conn.execute(f"detach database {alias}")
    return migrated


def close_shared_sqlite_checkpointers(*, under_root: Path | None = None) -> None:
    resolved_root = under_root.expanduser().resolve() if under_root is not None else None
    with _CHECKPOINTER_REGISTRY_LOCK:
        if resolved_root is None:
            selected_paths = list(_SQLITE_CHECKPOINTERS)
        else:
            selected_paths = [
                path
                for path in _SQLITE_CHECKPOINTERS
                if path == resolved_root or path.is_relative_to(resolved_root)
            ]
        shared_checkpointers = [
            _SQLITE_CHECKPOINTERS.pop(path)
            for path in selected_paths
        ]
        for shared in shared_checkpointers:
            _PERSISTENT_CHECKPOINTER_IDS.discard(id(shared.saver))
    for shared in shared_checkpointers:
        shared.connection.close()


atexit.register(close_shared_sqlite_checkpointers)
