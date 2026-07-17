from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterator, Sequence

from .config import Settings
from .schemas import Chunk, FetchedArtifact, StrategyCard
from .utils import new_id, stable_json, utcnow


SCHEMA = """
CREATE TABLE IF NOT EXISTS sources (
    id TEXT PRIMARY KEY,
    kind TEXT NOT NULL,
    canonical_url TEXT NOT NULL UNIQUE,
    external_id TEXT NOT NULL,
    title TEXT NOT NULL,
    author TEXT,
    license_spdx TEXT NOT NULL DEFAULT 'NOASSERTION',
    metadata_json TEXT NOT NULL DEFAULT '{}',
    first_seen_at TEXT NOT NULL,
    last_seen_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS revisions (
    id TEXT PRIMARY KEY,
    source_id TEXT NOT NULL REFERENCES sources(id) ON DELETE CASCADE,
    revision_key TEXT NOT NULL,
    immutable_url TEXT NOT NULL,
    fetched_at TEXT NOT NULL,
    content_sha256 TEXT NOT NULL,
    etag TEXT,
    last_modified TEXT,
    metadata_json TEXT NOT NULL DEFAULT '{}',
    UNIQUE(source_id, revision_key)
);

CREATE TABLE IF NOT EXISTS documents (
    id TEXT PRIMARY KEY,
    revision_id TEXT NOT NULL REFERENCES revisions(id) ON DELETE CASCADE,
    path TEXT NOT NULL,
    title TEXT NOT NULL,
    content_type TEXT NOT NULL,
    source_url TEXT,
    text TEXT NOT NULL,
    content_sha256 TEXT NOT NULL,
    UNIQUE(revision_id, path)
);

CREATE TABLE IF NOT EXISTS chunks (
    id TEXT PRIMARY KEY,
    document_id TEXT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    revision_id TEXT NOT NULL REFERENCES revisions(id) ON DELETE CASCADE,
    ordinal INTEGER NOT NULL,
    start_line INTEGER NOT NULL,
    end_line INTEGER NOT NULL,
    text TEXT NOT NULL,
    content_sha256 TEXT NOT NULL,
    UNIQUE(document_id, ordinal)
);

CREATE VIRTUAL TABLE IF NOT EXISTS chunk_fts USING fts5(
    chunk_id UNINDEXED,
    title,
    text,
    tokenize='unicode61 remove_diacritics 2'
);

CREATE TABLE IF NOT EXISTS strategy_cards (
    id TEXT PRIMARY KEY,
    source_id TEXT NOT NULL REFERENCES sources(id) ON DELETE CASCADE,
    revision_id TEXT NOT NULL REFERENCES revisions(id) ON DELETE CASCADE,
    title TEXT NOT NULL,
    summary TEXT NOT NULL,
    strategy_type TEXT NOT NULL,
    markets_json TEXT NOT NULL DEFAULT '[]',
    timeframes_json TEXT NOT NULL DEFAULT '[]',
    signals_json TEXT NOT NULL DEFAULT '[]',
    license_spdx TEXT NOT NULL,
    cost_disclosure TEXT NOT NULL,
    risk_flags_json TEXT NOT NULL DEFAULT '[]',
    fingerprint TEXT NOT NULL,
    card_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE(revision_id, fingerprint)
);

CREATE TABLE IF NOT EXISTS evidence (
    id TEXT PRIMARY KEY,
    card_id TEXT NOT NULL REFERENCES strategy_cards(id) ON DELETE CASCADE,
    field_name TEXT NOT NULL,
    chunk_id TEXT NOT NULL REFERENCES chunks(id) ON DELETE CASCADE,
    quote TEXT NOT NULL,
    source_url TEXT NOT NULL,
    line_start INTEGER,
    line_end INTEGER
);

CREATE TABLE IF NOT EXISTS embeddings (
    chunk_id TEXT PRIMARY KEY REFERENCES chunks(id) ON DELETE CASCADE,
    model_id TEXT NOT NULL,
    vector_json TEXT NOT NULL,
    dimension INTEGER NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS jobs (
    id TEXT PRIMARY KEY,
    kind TEXT NOT NULL,
    state TEXT NOT NULL,
    stage TEXT NOT NULL,
    input_json TEXT NOT NULL DEFAULT '{}',
    checkpoint_json TEXT NOT NULL DEFAULT '{}',
    items_processed INTEGER NOT NULL DEFAULT 0,
    error TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    finished_at TEXT
);

CREATE TABLE IF NOT EXISTS job_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id TEXT NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
    stage TEXT NOT NULL,
    status TEXT NOT NULL,
    detail TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS watch_rules (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    kind TEXT NOT NULL,
    config_json TEXT NOT NULL,
    interval_minutes INTEGER NOT NULL,
    enabled INTEGER NOT NULL DEFAULT 1,
    next_run_at TEXT NOT NULL,
    last_run_at TEXT,
    cursor_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS notifications (
    id TEXT PRIMARY KEY,
    kind TEXT NOT NULL,
    title TEXT NOT NULL,
    body TEXT NOT NULL,
    source_id TEXT,
    read_at TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS conversations (
    session_id TEXT PRIMARY KEY,
    summary TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL REFERENCES conversations(session_id) ON DELETE CASCADE,
    role TEXT NOT NULL,
    content TEXT NOT NULL,
    citations_json TEXT NOT NULL DEFAULT '[]',
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS preferences (
    key TEXT PRIMARY KEY,
    value_json TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS audit_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_type TEXT NOT NULL,
    actor TEXT NOT NULL,
    detail_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_revisions_source ON revisions(source_id, fetched_at DESC);
CREATE INDEX IF NOT EXISTS idx_chunks_revision ON chunks(revision_id);
CREATE INDEX IF NOT EXISTS idx_cards_source ON strategy_cards(source_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_jobs_created ON jobs(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_watch_due ON watch_rules(enabled, next_run_at);
CREATE INDEX IF NOT EXISTS idx_messages_session ON messages(session_id, id);
"""


class Database:
    def __init__(self, settings: Settings | Path | str):
        if isinstance(settings, Settings):
            self.settings = settings
            self.path = settings.db_path
        else:
            path = Path(settings).expanduser().resolve()
            self.path = path
            self.settings = None

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.path, timeout=30)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA busy_timeout=30000")
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def initialize(self) -> None:
        with self.connect() as connection:
            connection.executescript(SCHEMA)

    def upsert_source(self, artifact: FetchedArtifact) -> str:
        source_id = new_id("src", artifact.canonical_url)
        now = utcnow()
        with self.connect() as connection:
            connection.execute(
                """
                INSERT INTO sources(
                    id, kind, canonical_url, external_id, title, author,
                    license_spdx, metadata_json, first_seen_at, last_seen_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(canonical_url) DO UPDATE SET
                    title=excluded.title,
                    author=COALESCE(excluded.author, sources.author),
                    license_spdx=excluded.license_spdx,
                    metadata_json=excluded.metadata_json,
                    last_seen_at=excluded.last_seen_at
                """,
                (
                    source_id,
                    artifact.kind,
                    artifact.canonical_url,
                    artifact.external_id,
                    artifact.title,
                    artifact.author,
                    artifact.license_spdx,
                    stable_json(artifact.metadata),
                    now,
                    now,
                ),
            )
            row = connection.execute(
                "SELECT id FROM sources WHERE canonical_url=?", (artifact.canonical_url,)
            ).fetchone()
        return str(row["id"])

    def create_revision(self, source_id: str, artifact: FetchedArtifact, content_sha256: str) -> tuple[str, bool]:
        revision_id = new_id("rev", f"{source_id}:{artifact.revision_key}")
        with self.connect() as connection:
            existing = connection.execute(
                "SELECT id FROM revisions WHERE source_id=? AND revision_key=?",
                (source_id, artifact.revision_key),
            ).fetchone()
            if existing:
                return str(existing["id"]), False
            connection.execute(
                """
                INSERT INTO revisions(
                    id, source_id, revision_key, immutable_url, fetched_at,
                    content_sha256, etag, last_modified, metadata_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    revision_id,
                    source_id,
                    artifact.revision_key,
                    artifact.immutable_url,
                    utcnow(),
                    content_sha256,
                    artifact.etag,
                    artifact.last_modified,
                    stable_json(artifact.metadata),
                ),
            )
        return revision_id, True

    def delete_revision(self, revision_id: str) -> bool:
        """Remove an incomplete revision and every derived record."""
        with self.connect() as connection:
            connection.execute(
                """
                DELETE FROM chunk_fts
                WHERE chunk_id IN (SELECT id FROM chunks WHERE revision_id=?)
                """,
                (revision_id,),
            )
            cursor = connection.execute("DELETE FROM revisions WHERE id=?", (revision_id,))
        return bool(cursor.rowcount)

    def store_document(
        self,
        revision_id: str,
        path: str,
        title: str,
        content_type: str,
        source_url: str | None,
        text: str,
        content_sha256: str,
    ) -> str:
        document_id = new_id("doc", f"{revision_id}:{path}")
        with self.connect() as connection:
            connection.execute(
                """
                INSERT OR IGNORE INTO documents(
                    id, revision_id, path, title, content_type, source_url, text, content_sha256
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (document_id, revision_id, path, title, content_type, source_url, text, content_sha256),
            )
            row = connection.execute(
                "SELECT id FROM documents WHERE revision_id=? AND path=?", (revision_id, path)
            ).fetchone()
        return str(row["id"])

    def store_chunks(self, title: str, chunks: Sequence[Chunk]) -> None:
        with self.connect() as connection:
            for chunk in chunks:
                cursor = connection.execute(
                    """
                    INSERT OR IGNORE INTO chunks(
                        id, document_id, revision_id, ordinal, start_line, end_line, text, content_sha256
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        chunk.id,
                        chunk.document_id,
                        chunk.revision_id,
                        chunk.ordinal,
                        chunk.start_line,
                        chunk.end_line,
                        chunk.text,
                        chunk.content_sha256,
                    ),
                )
                if cursor.rowcount:
                    connection.execute(
                        "INSERT INTO chunk_fts(chunk_id, title, text) VALUES (?, ?, ?)",
                        (chunk.id, title, chunk.text),
                    )

    def save_card(self, card: StrategyCard) -> StrategyCard:
        if not card.source_id or not card.revision_id:
            raise ValueError("card source_id and revision_id are required")
        card_id = new_id("card", f"{card.revision_id}:{card.fingerprint}")
        created_at = utcnow()
        stored = card.model_copy(update={"id": card_id, "created_at": created_at})
        with self.connect() as connection:
            connection.execute(
                """
                INSERT OR IGNORE INTO strategy_cards(
                    id, source_id, revision_id, title, summary, strategy_type,
                    markets_json, timeframes_json, signals_json, license_spdx,
                    cost_disclosure, risk_flags_json, fingerprint, card_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    card_id,
                    stored.source_id,
                    stored.revision_id,
                    stored.title,
                    stored.summary,
                    stored.strategy_type,
                    stable_json(stored.markets),
                    stable_json(stored.timeframes),
                    stable_json(stored.signals),
                    stored.license_spdx,
                    stored.cost_disclosure,
                    stable_json(stored.risk_flags),
                    stored.fingerprint,
                    stored.model_dump_json(),
                    created_at,
                ),
            )
            row = connection.execute(
                "SELECT id, card_json, created_at FROM strategy_cards WHERE revision_id=? AND fingerprint=?",
                (stored.revision_id, stored.fingerprint),
            ).fetchone()
            resolved_id = str(row["id"])
            for item in stored.evidence:
                evidence_id = new_id("ev", f"{resolved_id}:{item.field}:{item.chunk_id}:{item.quote}")
                connection.execute(
                    """
                    INSERT OR IGNORE INTO evidence(
                        id, card_id, field_name, chunk_id, quote, source_url, line_start, line_end
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        evidence_id,
                        resolved_id,
                        item.field,
                        item.chunk_id,
                        item.quote,
                        item.source_url,
                        item.line_start,
                        item.line_end,
                    ),
                )
        payload = json.loads(row["card_json"])
        payload.update({"id": resolved_id, "created_at": row["created_at"]})
        return StrategyCard.model_validate(payload)

    def save_embedding(self, chunk_id: str, model_id: str, vector: Sequence[float]) -> None:
        with self.connect() as connection:
            connection.execute(
                """
                INSERT INTO embeddings(chunk_id, model_id, vector_json, dimension, created_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(chunk_id) DO UPDATE SET
                    model_id=excluded.model_id,
                    vector_json=excluded.vector_json,
                    dimension=excluded.dimension,
                    created_at=excluded.created_at
                """,
                (chunk_id, model_id, stable_json(list(vector)), len(vector), utcnow()),
            )

    def list_embedding_rows(self, limit: int = 5000) -> list[dict[str, Any]]:
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT e.chunk_id, e.model_id, e.vector_json, c.text, c.start_line, c.end_line,
                       COALESCE(d.source_url, r.immutable_url) AS immutable_url, s.canonical_url,
                       (SELECT sc.id FROM strategy_cards sc WHERE sc.revision_id=c.revision_id LIMIT 1) AS card_id,
                       (SELECT sc.title FROM strategy_cards sc WHERE sc.revision_id=c.revision_id LIMIT 1) AS card_title
                FROM embeddings e
                JOIN chunks c ON c.id=e.chunk_id
                JOIN documents d ON d.id=c.document_id
                JOIN revisions r ON r.id=c.revision_id
                JOIN sources s ON s.id=r.source_id
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [dict(row) for row in rows]

    def search_fts(self, expression: str, limit: int = 30) -> list[dict[str, Any]]:
        if not expression:
            return []
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT f.chunk_id, f.text, c.start_line, c.end_line,
                       bm25(chunk_fts, 0.0, 1.0, 1.0) AS rank,
                       COALESCE(d.source_url, r.immutable_url) AS immutable_url, s.canonical_url,
                       (SELECT sc.id FROM strategy_cards sc WHERE sc.revision_id=c.revision_id LIMIT 1) AS card_id,
                       (SELECT sc.title FROM strategy_cards sc WHERE sc.revision_id=c.revision_id LIMIT 1) AS card_title
                FROM chunk_fts f
                JOIN chunks c ON c.id=f.chunk_id
                JOIN documents d ON d.id=c.document_id
                JOIN revisions r ON r.id=c.revision_id
                JOIN sources s ON s.id=r.source_id
                WHERE chunk_fts MATCH ?
                ORDER BY rank
                LIMIT ?
                """,
                (expression, limit),
            ).fetchall()
        return [dict(row) for row in rows]

    def list_cards(self, limit: int = 100, offset: int = 0) -> list[dict[str, Any]]:
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT sc.*, s.canonical_url, r.immutable_url, r.revision_key
                FROM strategy_cards sc
                JOIN sources s ON s.id=sc.source_id
                JOIN revisions r ON r.id=sc.revision_id
                ORDER BY sc.created_at DESC
                LIMIT ? OFFSET ?
                """,
                (limit, offset),
            ).fetchall()
        return [self._card_row(row) for row in rows]

    def get_card(self, card_id: str) -> dict[str, Any] | None:
        with self.connect() as connection:
            row = connection.execute(
                """
                SELECT sc.*, s.canonical_url, r.immutable_url, r.revision_key
                FROM strategy_cards sc
                JOIN sources s ON s.id=sc.source_id
                JOIN revisions r ON r.id=sc.revision_id
                WHERE sc.id=?
                """,
                (card_id,),
            ).fetchone()
            if not row:
                return None
            evidence = connection.execute(
                "SELECT * FROM evidence WHERE card_id=? ORDER BY field_name, line_start", (card_id,)
            ).fetchall()
        card = self._card_row(row)
        card["evidence"] = [dict(item) for item in evidence]
        return card

    @staticmethod
    def _card_row(row: sqlite3.Row) -> dict[str, Any]:
        payload = json.loads(row["card_json"])
        payload.pop("evidence", None)
        payload.update(
            {
                "id": row["id"],
                "created_at": row["created_at"],
                "source_url": row["canonical_url"],
                "immutable_url": row["immutable_url"],
                "revision_key": row["revision_key"],
            }
        )
        return payload

    def create_job(self, kind: str, payload: dict[str, Any]) -> str:
        job_id = new_id("job")
        now = utcnow()
        with self.connect() as connection:
            connection.execute(
                """
                INSERT INTO jobs(id, kind, state, stage, input_json, created_at, updated_at)
                VALUES (?, ?, 'RUNNING', 'CREATED', ?, ?, ?)
                """,
                (job_id, kind, stable_json(payload), now, now),
            )
            connection.execute(
                "INSERT INTO job_events(job_id, stage, status, detail, created_at) VALUES (?, 'CREATED', 'completed', '', ?)",
                (job_id, now),
            )
        return job_id

    def update_job(
        self,
        job_id: str,
        *,
        state: str | None = None,
        stage: str | None = None,
        items_processed: int | None = None,
        checkpoint: dict[str, Any] | None = None,
        error: str | None = None,
        detail: str = "",
    ) -> None:
        updates = ["updated_at=?"]
        values: list[Any] = [utcnow()]
        for column, value in (
            ("state", state),
            ("stage", stage),
            ("items_processed", items_processed),
            ("checkpoint_json", stable_json(checkpoint) if checkpoint is not None else None),
            ("error", error),
        ):
            if value is not None:
                updates.append(f"{column}=?")
                values.append(value)
        if state in {"COMPLETED", "PARTIAL_SUCCESS", "FAILED", "CANCELLED"}:
            updates.append("finished_at=?")
            values.append(utcnow())
        values.append(job_id)
        with self.connect() as connection:
            connection.execute(f"UPDATE jobs SET {', '.join(updates)} WHERE id=?", values)
            if stage:
                connection.execute(
                    "INSERT INTO job_events(job_id, stage, status, detail, created_at) VALUES (?, ?, ?, ?, ?)",
                    (job_id, stage, state or "running", detail, utcnow()),
                )

    def list_jobs(self, limit: int = 50) -> list[dict[str, Any]]:
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT * FROM jobs ORDER BY created_at DESC LIMIT ?", (limit,)
            ).fetchall()
        result = []
        for row in rows:
            item = dict(row)
            item["input"] = json.loads(item.pop("input_json"))
            item["checkpoint"] = json.loads(item.pop("checkpoint_json"))
            result.append(item)
        return result

    def create_watch_rule(
        self, name: str, kind: str, config: dict[str, Any], interval_minutes: int, enabled: bool = True
    ) -> dict[str, Any]:
        rule_id = new_id("watch")
        now = datetime.now(timezone.utc)
        next_run = (now + timedelta(minutes=interval_minutes)).isoformat(timespec="seconds")
        with self.connect() as connection:
            connection.execute(
                """
                INSERT INTO watch_rules(
                    id, name, kind, config_json, interval_minutes, enabled,
                    next_run_at, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    rule_id,
                    name,
                    kind,
                    stable_json(config),
                    interval_minutes,
                    int(enabled),
                    next_run,
                    now.isoformat(timespec="seconds"),
                    now.isoformat(timespec="seconds"),
                ),
            )
        return self.get_watch_rule(rule_id) or {}

    def get_watch_rule(self, rule_id: str) -> dict[str, Any] | None:
        with self.connect() as connection:
            row = connection.execute("SELECT * FROM watch_rules WHERE id=?", (rule_id,)).fetchone()
        return self._watch_row(row) if row else None

    def list_watch_rules(self) -> list[dict[str, Any]]:
        with self.connect() as connection:
            rows = connection.execute("SELECT * FROM watch_rules ORDER BY created_at DESC").fetchall()
        return [self._watch_row(row) for row in rows]

    def due_watch_rules(self, now: str | None = None) -> list[dict[str, Any]]:
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT * FROM watch_rules WHERE enabled=1 AND next_run_at<=? ORDER BY next_run_at",
                (now or utcnow(),),
            ).fetchall()
        return [self._watch_row(row) for row in rows]

    @staticmethod
    def _watch_row(row: sqlite3.Row) -> dict[str, Any]:
        item = dict(row)
        item["config"] = json.loads(item.pop("config_json"))
        item["cursor"] = json.loads(item.pop("cursor_json"))
        item["enabled"] = bool(item["enabled"])
        return item

    def mark_watch_run(self, rule_id: str, interval_minutes: int, cursor: dict[str, Any] | None = None) -> None:
        now = datetime.now(timezone.utc)
        next_run = now + timedelta(minutes=interval_minutes)
        with self.connect() as connection:
            connection.execute(
                """
                UPDATE watch_rules
                SET last_run_at=?, next_run_at=?, cursor_json=?, updated_at=?
                WHERE id=?
                """,
                (
                    now.isoformat(timespec="seconds"),
                    next_run.isoformat(timespec="seconds"),
                    stable_json(cursor or {}),
                    now.isoformat(timespec="seconds"),
                    rule_id,
                ),
            )

    def add_message(self, session_id: str, role: str, content: str, citations: list[dict[str, Any]] | None = None) -> None:
        now = utcnow()
        with self.connect() as connection:
            connection.execute(
                """
                INSERT INTO conversations(session_id, created_at, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(session_id) DO UPDATE SET updated_at=excluded.updated_at
                """,
                (session_id, now, now),
            )
            connection.execute(
                "INSERT INTO messages(session_id, role, content, citations_json, created_at) VALUES (?, ?, ?, ?, ?)",
                (session_id, role, content, stable_json(citations or []), now),
            )

    def recent_messages(self, session_id: str, limit: int = 8) -> list[dict[str, Any]]:
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT role, content, citations_json, created_at FROM (
                    SELECT * FROM messages WHERE session_id=? ORDER BY id DESC LIMIT ?
                ) ORDER BY created_at
                """,
                (session_id, limit),
            ).fetchall()
        return [
            {**dict(row), "citations": json.loads(row["citations_json"])} for row in rows
        ]

    def delete_conversation(self, session_id: str) -> bool:
        with self.connect() as connection:
            cursor = connection.execute("DELETE FROM conversations WHERE session_id=?", (session_id,))
        return bool(cursor.rowcount)

    def list_conversations(self, limit: int = 50) -> list[dict[str, Any]]:
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT c.session_id, c.summary, c.created_at, c.updated_at,
                       count(m.id) AS message_count
                FROM conversations c
                LEFT JOIN messages m ON m.session_id=c.session_id
                GROUP BY c.session_id
                ORDER BY c.updated_at DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [dict(row) for row in rows]

    def set_preference(self, key: str, value: Any) -> None:
        with self.connect() as connection:
            connection.execute(
                """
                INSERT INTO preferences(key, value_json, updated_at) VALUES (?, ?, ?)
                ON CONFLICT(key) DO UPDATE SET value_json=excluded.value_json, updated_at=excluded.updated_at
                """,
                (key, stable_json(value), utcnow()),
            )

    def preferences(self) -> dict[str, Any]:
        with self.connect() as connection:
            rows = connection.execute("SELECT key, value_json FROM preferences").fetchall()
        return {row["key"]: json.loads(row["value_json"]) for row in rows}

    def delete_preference(self, key: str) -> bool:
        with self.connect() as connection:
            cursor = connection.execute("DELETE FROM preferences WHERE key=?", (key,))
        return bool(cursor.rowcount)

    def add_notification(self, kind: str, title: str, body: str, source_id: str | None = None) -> str:
        notification_id = new_id("note")
        with self.connect() as connection:
            connection.execute(
                "INSERT INTO notifications(id, kind, title, body, source_id, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                (notification_id, kind, title, body, source_id, utcnow()),
            )
        return notification_id

    def list_notifications(self, limit: int = 50) -> list[dict[str, Any]]:
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT * FROM notifications ORDER BY created_at DESC LIMIT ?", (limit,)
            ).fetchall()
        return [dict(row) for row in rows]

    def list_sources(self, limit: int = 100) -> list[dict[str, Any]]:
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT s.*,
                       count(DISTINCT r.id) AS revision_count,
                       count(DISTINCT sc.id) AS card_count
                FROM sources s
                LEFT JOIN revisions r ON r.source_id=s.id
                LEFT JOIN strategy_cards sc ON sc.source_id=s.id
                GROUP BY s.id
                ORDER BY s.last_seen_at DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        result = []
        for row in rows:
            item = dict(row)
            item["metadata"] = json.loads(item.pop("metadata_json"))
            result.append(item)
        return result

    def audit(self, event_type: str, detail: dict[str, Any], actor: str = "local-user") -> None:
        with self.connect() as connection:
            connection.execute(
                "INSERT INTO audit_events(event_type, actor, detail_json, created_at) VALUES (?, ?, ?, ?)",
                (event_type, actor, stable_json(detail), utcnow()),
            )

    def list_audit_events(self, limit: int = 100) -> list[dict[str, Any]]:
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT * FROM audit_events ORDER BY id DESC LIMIT ?", (limit,)
            ).fetchall()
        result = []
        for row in rows:
            item = dict(row)
            item["detail"] = json.loads(item.pop("detail_json"))
            result.append(item)
        return result

    def dashboard(self) -> dict[str, int]:
        cutoff = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat(timespec="seconds")
        with self.connect() as connection:
            return {
                "strategies": int(connection.execute("SELECT count(*) FROM strategy_cards").fetchone()[0]),
                "sources": int(connection.execute("SELECT count(*) FROM sources").fetchone()[0]),
                "revisions": int(connection.execute("SELECT count(*) FROM revisions").fetchone()[0]),
                "active_watch_rules": int(
                    connection.execute("SELECT count(*) FROM watch_rules WHERE enabled=1").fetchone()[0]
                ),
                "jobs_last_24h": int(
                    connection.execute("SELECT count(*) FROM jobs WHERE created_at>=?", (cutoff,)).fetchone()[0]
                ),
                "notifications": int(
                    connection.execute("SELECT count(*) FROM notifications WHERE read_at IS NULL").fetchone()[0]
                ),
            }
