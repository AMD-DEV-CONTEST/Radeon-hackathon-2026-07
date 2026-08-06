from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
import sqlite3
from pathlib import Path

from agent_factory.paths import factory_artifact_path
from agent_factory.sqlite_runtime import connect_sqlite, initialize_sqlite_store
from agent_factory.tip_system.schema import TipMessage, TipRecord, utc_now_text


SQLITE_BUSY_TIMEOUT_MS = 10000


class TipStore:
    def __init__(self, path: str | Path | None = None) -> None:
        self.path = Path(path) if path is not None else factory_artifact_path("tips", "factory.sqlite")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        initialize_sqlite_store(
            self.path,
            self._ensure_schema,
            timeout_ms=SQLITE_BUSY_TIMEOUT_MS,
            wal=True,
        )

    def create(self, tip: TipRecord) -> TipRecord:
        with self._connect() as conn:
            conn.execute(
                """
                insert into tips (
                  tip_id, scope_type, scope_id, source_message_id, source_role,
                  source_content, selected_text, selection_start, selection_end,
                  agent_package_id, model_profile_id, reasoning_intensity,
                  status, error, created_at, updated_at
                ) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    tip.tip_id,
                    tip.scope_type,
                    tip.scope_id,
                    tip.source_message_id,
                    tip.source_role,
                    tip.source_content,
                    tip.selected_text,
                    tip.selection_start,
                    tip.selection_end,
                    tip.agent_package_id,
                    tip.model_profile_id,
                    tip.reasoning_intensity,
                    tip.status,
                    tip.error,
                    tip.created_at,
                    tip.updated_at,
                ),
            )
            for message in tip.messages:
                self._insert_message(conn, tip.tip_id, message)
        return self.require(tip.tip_id)

    def require(self, tip_id: str) -> TipRecord:
        with self._connect() as conn:
            row = conn.execute("select * from tips where tip_id = ?", (tip_id,)).fetchone()
            if row is None:
                raise KeyError(f"unknown tip: {tip_id}")
            messages = conn.execute(
                "select * from tip_messages where tip_id = ? order by message_index asc",
                (tip_id,),
            ).fetchall()
        return self._record(row, messages)

    def list_scope(self, scope_type: str, scope_id: str) -> list[TipRecord]:
        with self._connect() as conn:
            rows = conn.execute(
                "select * from tips where scope_type = ? and scope_id = ? order by updated_at desc",
                (scope_type, scope_id),
            ).fetchall()
            return [
                self._record(
                    row,
                    conn.execute(
                        "select * from tip_messages where tip_id = ? order by message_index asc",
                        (row["tip_id"],),
                    ).fetchall(),
                )
                for row in rows
            ]

    def append_message(self, tip_id: str, message: TipMessage) -> TipRecord:
        with self._connect() as conn:
            self._insert_message(conn, tip_id, message)
            conn.execute(
                "update tips set updated_at = ? where tip_id = ?",
                (utc_now_text(), tip_id),
            )
        return self.require(tip_id)

    def set_status(self, tip_id: str, status: str, *, error: str | None = None) -> TipRecord:
        with self._connect() as conn:
            cursor = conn.execute(
                "update tips set status = ?, error = ?, updated_at = ? where tip_id = ?",
                (status, error, utc_now_text(), tip_id),
            )
            if cursor.rowcount == 0:
                raise KeyError(f"unknown tip: {tip_id}")
        return self.require(tip_id)

    def delete(self, tip_id: str) -> bool:
        with self._connect() as conn:
            cursor = conn.execute("delete from tips where tip_id = ?", (tip_id,))
        return cursor.rowcount > 0

    @staticmethod
    def _insert_message(conn: sqlite3.Connection, tip_id: str, message: TipMessage) -> None:
        next_index = conn.execute(
            "select coalesce(max(message_index), -1) + 1 from tip_messages where tip_id = ?",
            (tip_id,),
        ).fetchone()[0]
        conn.execute(
            """
            insert into tip_messages (message_id, tip_id, message_index, role, content, created_at)
            values (?, ?, ?, ?, ?, ?)
            """,
            (message.message_id, tip_id, next_index, message.role, message.content, message.created_at),
        )

    @staticmethod
    def _record(row: sqlite3.Row, messages: list[sqlite3.Row]) -> TipRecord:
        return TipRecord(
            tip_id=row["tip_id"],
            scope_type=row["scope_type"],
            scope_id=row["scope_id"],
            source_message_id=row["source_message_id"],
            source_role=row["source_role"],
            source_content=row["source_content"],
            selected_text=row["selected_text"],
            selection_start=row["selection_start"],
            selection_end=row["selection_end"],
            agent_package_id=row["agent_package_id"],
            model_profile_id=row["model_profile_id"],
            reasoning_intensity=row["reasoning_intensity"],
            status=row["status"],
            error=row["error"],
            messages=[
                TipMessage(
                    message_id=item["message_id"],
                    role=item["role"],
                    content=item["content"],
                    created_at=item["created_at"],
                )
                for item in messages
            ],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        conn = connect_sqlite(
            self.path,
            timeout_ms=SQLITE_BUSY_TIMEOUT_MS,
            foreign_keys=True,
        )
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def _ensure_schema(self) -> None:
        with self._connect() as conn:
            conn.executescript(
                """
                create table if not exists tips (
                  tip_id text primary key,
                  scope_type text not null,
                  scope_id text not null,
                  source_message_id text not null,
                  source_role text not null,
                  source_content text not null,
                  selected_text text not null,
                  selection_start integer,
                  selection_end integer,
                  agent_package_id text,
                  model_profile_id text,
                  reasoning_intensity integer,
                  status text not null,
                  error text,
                  created_at text not null,
                  updated_at text not null
                );
                create index if not exists idx_tips_scope on tips(scope_type, scope_id, updated_at);
                create index if not exists idx_tips_source on tips(scope_type, scope_id, source_message_id);

                create table if not exists tip_messages (
                  message_id text primary key,
                  tip_id text not null references tips(tip_id) on delete cascade,
                  message_index integer not null,
                  role text not null,
                  content text not null,
                  created_at text not null,
                  unique(tip_id, message_index)
                );
                """
            )
