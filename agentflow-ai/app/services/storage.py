from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, UTC
import json
from pathlib import Path
import sqlite3
import threading
import uuid
from typing import Any, Iterator


ISO = "%Y-%m-%dT%H:%M:%SZ"


def utc_now() -> str:
    return datetime.now(UTC).strftime(ISO)


class SQLiteStorage:
    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        self._lock = threading.Lock()
        self._init_db()

    @contextmanager
    def connection(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def _init_db(self) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self.connection() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS conversations (
                    id TEXT PRIMARY KEY,
                    title TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS messages (
                    id TEXT PRIMARY KEY,
                    conversation_id TEXT NOT NULL,
                    role TEXT NOT NULL,
                    content TEXT NOT NULL,
                    model TEXT,
                    plan_json TEXT,
                    timeline_json TEXT,
                    citations_json TEXT,
                    tools_json TEXT,
                    benchmark_json TEXT,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY (conversation_id) REFERENCES conversations(id)
                );

                CREATE TABLE IF NOT EXISTS memories (
                    id TEXT PRIMARY KEY,
                    conversation_id TEXT,
                    kind TEXT NOT NULL,
                    content TEXT NOT NULL,
                    score REAL NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY (conversation_id) REFERENCES conversations(id)
                );

                CREATE TABLE IF NOT EXISTS documents (
                    id TEXT PRIMARY KEY,
                    filename TEXT NOT NULL,
                    path TEXT NOT NULL,
                    mime_type TEXT NOT NULL,
                    page_count INTEGER NOT NULL,
                    chunk_count INTEGER NOT NULL,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS benchmarks (
                    id TEXT PRIMARY KEY,
                    conversation_id TEXT NOT NULL,
                    model TEXT,
                    duration_ms INTEGER NOT NULL,
                    tools_used INTEGER NOT NULL,
                    citations_used INTEGER NOT NULL,
                    success INTEGER NOT NULL,
                    created_at TEXT NOT NULL,
                    metadata_json TEXT,
                    FOREIGN KEY (conversation_id) REFERENCES conversations(id)
                );
                """
            )

    def create_or_get_conversation(self, conversation_id: str | None, first_message: str) -> dict[str, Any]:
        with self._lock:
            with self.connection() as conn:
                if conversation_id:
                    row = conn.execute(
                        "SELECT * FROM conversations WHERE id = ?", (conversation_id,)
                    ).fetchone()
                    if row:
                        return dict(row)

                created_at = utc_now()
                conversation_id = conversation_id or str(uuid.uuid4())
                title = self._title_from_text(first_message)
                conn.execute(
                    "INSERT INTO conversations (id, title, created_at, updated_at) VALUES (?, ?, ?, ?)",
                    (conversation_id, title, created_at, created_at),
                )
                return {
                    "id": conversation_id,
                    "title": title,
                    "created_at": created_at,
                    "updated_at": created_at,
                }

    def add_message(
        self,
        conversation_id: str,
        role: str,
        content: str,
        *,
        model: str | None = None,
        plan: dict[str, Any] | None = None,
        timeline: list[dict[str, Any]] | None = None,
        citations: list[dict[str, Any]] | None = None,
        tools: list[dict[str, Any]] | None = None,
        benchmark: dict[str, Any] | None = None,
    ) -> str:
        message_id = str(uuid.uuid4())
        created_at = utc_now()
        with self._lock:
            with self.connection() as conn:
                conn.execute(
                    """
                    INSERT INTO messages (
                        id, conversation_id, role, content, model,
                        plan_json, timeline_json, citations_json, tools_json,
                        benchmark_json, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        message_id,
                        conversation_id,
                        role,
                        content,
                        model,
                        json.dumps(plan or {}),
                        json.dumps(timeline or []),
                        json.dumps(citations or []),
                        json.dumps(tools or []),
                        json.dumps(benchmark or {}),
                        created_at,
                    ),
                )
                conn.execute(
                    "UPDATE conversations SET updated_at = ? WHERE id = ?",
                    (created_at, conversation_id),
                )
        return message_id

    def list_conversations(self) -> list[dict[str, Any]]:
        with self.connection() as conn:
            rows = conn.execute(
                """
                SELECT c.id, c.title, c.updated_at,
                       COALESCE((
                         SELECT SUBSTR(content, 1, 120)
                         FROM messages m
                         WHERE m.conversation_id = c.id
                         ORDER BY m.created_at DESC
                         LIMIT 1
                       ), '') AS last_message_preview
                FROM conversations c
                ORDER BY c.updated_at DESC
                """
            ).fetchall()
            return [dict(row) for row in rows]

    def get_conversation(self, conversation_id: str) -> dict[str, Any] | None:
        with self.connection() as conn:
            conversation = conn.execute(
                "SELECT * FROM conversations WHERE id = ?", (conversation_id,)
            ).fetchone()
            if not conversation:
                return None
            messages = conn.execute(
                "SELECT * FROM messages WHERE conversation_id = ? ORDER BY created_at ASC",
                (conversation_id,),
            ).fetchall()
            return {
                **dict(conversation),
                "messages": [self._decode_message(row) for row in messages],
            }

    def get_recent_messages(self, conversation_id: str, limit: int = 8) -> list[dict[str, Any]]:
        with self.connection() as conn:
            rows = conn.execute(
                "SELECT * FROM messages WHERE conversation_id = ? ORDER BY created_at DESC LIMIT ?",
                (conversation_id, limit),
            ).fetchall()
            return [self._decode_message(row) for row in reversed(rows)]

    def add_memory(self, content: str, *, kind: str = "summary", conversation_id: str | None = None, score: float = 0.0) -> str:
        memory_id = str(uuid.uuid4())
        with self._lock:
            with self.connection() as conn:
                conn.execute(
                    "INSERT INTO memories (id, conversation_id, kind, content, score, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                    (memory_id, conversation_id, kind, content, score, utc_now()),
                )
        return memory_id

    def search_memories(self, query: str, limit: int = 5) -> list[dict[str, Any]]:
        keywords = [word.lower() for word in query.split() if len(word) > 2][:8]
        if not keywords:
            return []
        with self.connection() as conn:
            rows = conn.execute(
                "SELECT * FROM memories ORDER BY created_at DESC LIMIT 50"
            ).fetchall()
        scored: list[tuple[int, dict[str, Any]]] = []
        for row in rows:
            record = dict(row)
            haystack = record["content"].lower()
            score = sum(haystack.count(keyword) for keyword in keywords)
            if score:
                scored.append((score, record))
        scored.sort(key=lambda item: (-item[0], item[1]["created_at"]), reverse=False)
        return [record for _, record in scored[:limit]]

    def add_document(self, *, document_id: str, filename: str, path: str, mime_type: str, page_count: int, chunk_count: int) -> None:
        with self._lock:
            with self.connection() as conn:
                conn.execute(
                    "INSERT OR REPLACE INTO documents (id, filename, path, mime_type, page_count, chunk_count, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (document_id, filename, path, mime_type, page_count, chunk_count, utc_now()),
                )

    def list_documents(self) -> list[dict[str, Any]]:
        with self.connection() as conn:
            rows = conn.execute("SELECT * FROM documents ORDER BY created_at DESC").fetchall()
        return [dict(row) for row in rows]

    def get_document(self, document_id: str) -> dict[str, Any] | None:
        with self.connection() as conn:
            row = conn.execute("SELECT * FROM documents WHERE id = ?", (document_id,)).fetchone()
        return dict(row) if row else None

    def add_benchmark(
        self,
        *,
        conversation_id: str,
        model: str | None,
        duration_ms: int,
        tools_used: int,
        citations_used: int,
        success: bool,
        metadata: dict[str, Any],
    ) -> None:
        with self._lock:
            with self.connection() as conn:
                conn.execute(
                    "INSERT INTO benchmarks (id, conversation_id, model, duration_ms, tools_used, citations_used, success, created_at, metadata_json) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        str(uuid.uuid4()),
                        conversation_id,
                        model,
                        duration_ms,
                        tools_used,
                        citations_used,
                        1 if success else 0,
                        utc_now(),
                        json.dumps(metadata),
                    ),
                )

    def benchmark_summary(self) -> dict[str, Any]:
        with self.connection() as conn:
            total_conversations = conn.execute("SELECT COUNT(*) AS count FROM conversations").fetchone()["count"]
            total_messages = conn.execute("SELECT COUNT(*) AS count FROM messages").fetchone()["count"]
            total_documents = conn.execute("SELECT COUNT(*) AS count FROM documents").fetchone()["count"]
            aggregate = conn.execute(
                "SELECT COUNT(*) AS runs, AVG(duration_ms) AS avg_duration, AVG(success) AS success_rate, SUM(tools_used) AS tools_total, SUM(citations_used) AS citations_total FROM benchmarks"
            ).fetchone()
            recent = conn.execute(
                "SELECT * FROM benchmarks ORDER BY created_at DESC LIMIT 10"
            ).fetchall()

        tool_counts: dict[str, int] = {}
        recent_runs = []
        for row in recent:
            metadata = json.loads(row["metadata_json"] or "{}")
            for tool in metadata.get("tool_names", []):
                tool_counts[tool] = tool_counts.get(tool, 0) + 1
            recent_runs.append(
                {
                    "conversation_id": row["conversation_id"],
                    "model": row["model"],
                    "duration_ms": row["duration_ms"],
                    "success": bool(row["success"]),
                    "created_at": row["created_at"],
                }
            )

        return {
            "totals": {
                "conversations": total_conversations,
                "messages": total_messages,
                "documents": total_documents,
                "runs": aggregate["runs"] or 0,
                "avg_duration_ms": int(aggregate["avg_duration"] or 0),
                "success_rate": round(float(aggregate["success_rate"] or 0) * 100, 1),
                "tools_total": aggregate["tools_total"] or 0,
                "citations_total": aggregate["citations_total"] or 0,
            },
            "recent_runs": recent_runs,
            "tool_usage": [
                {"tool": name, "count": count}
                for name, count in sorted(tool_counts.items(), key=lambda item: item[1], reverse=True)
            ],
        }

    @staticmethod
    def _title_from_text(text: str) -> str:
        cleaned = " ".join(text.split())
        return cleaned[:60] + ("…" if len(cleaned) > 60 else "") or "New Workflow"

    @staticmethod
    def _decode_message(row: sqlite3.Row) -> dict[str, Any]:
        return {
            "id": row["id"],
            "role": row["role"],
            "content": row["content"],
            "model": row["model"],
            "plan": json.loads(row["plan_json"] or "{}"),
            "timeline": json.loads(row["timeline_json"] or "[]"),
            "citations": json.loads(row["citations_json"] or "[]"),
            "tools": json.loads(row["tools_json"] or "[]"),
            "benchmark": json.loads(row["benchmark_json"] or "{}"),
            "created_at": row["created_at"],
        }
