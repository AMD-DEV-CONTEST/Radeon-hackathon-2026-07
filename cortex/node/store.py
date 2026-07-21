from __future__ import annotations

import json
import sqlite3
import time
from collections.abc import Iterable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

SCHEMA = """
CREATE TABLE IF NOT EXISTS articles (
  id            TEXT PRIMARY KEY,
  type          TEXT NOT NULL,
  content       TEXT NOT NULL,
  payload_json  TEXT NOT NULL,
  scope         TEXT NOT NULL,
  agent_sig     BLOB NOT NULL,
  org_sig       BLOB,
  cites_json    TEXT NOT NULL DEFAULT '[]',
  state         TEXT NOT NULL,
  created_at    TEXT NOT NULL,
  published_at  TEXT,
  trust_score   REAL,
  trust_expires TEXT
);
CREATE INDEX IF NOT EXISTS idx_articles_type  ON articles(type);
CREATE INDEX IF NOT EXISTS idx_articles_scope ON articles(scope);
CREATE INDEX IF NOT EXISTS idx_articles_trust ON articles(trust_score DESC);

CREATE TABLE IF NOT EXISTS provenance_edges (
  source_id TEXT NOT NULL,
  cited_id  TEXT NOT NULL,
  PRIMARY KEY (source_id, cited_id)
);

CREATE TABLE IF NOT EXISTS events (
  seq        INTEGER PRIMARY KEY AUTOINCREMENT,
  ts         TEXT NOT NULL,
  event      TEXT NOT NULL,
  article_id TEXT,
  payload_json  TEXT NOT NULL
);
"""


def _ts_iso(dt: datetime) -> str:
    return dt.astimezone(UTC).isoformat() if dt.tzinfo else dt.isoformat()


class ArticleStore:
    def __init__(self, db_path: Path) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self.db_path, isolation_level=None)
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(SCHEMA)

    def close(self) -> None:
        self._conn.close()

    def put(self, article: Any, state: str) -> None:
        self._exec_retry(
            """INSERT OR REPLACE INTO articles
               (id, type, content, payload_json, scope, agent_sig, org_sig,
                cites_json, state, created_at, published_at, trust_score, trust_expires)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                article.id, article.type, article.content,
                json.dumps(article.payload, sort_keys=True, separators=(",", ":")),
                article.scope, bytes(article.agent_signature),
                bytes(article.org_signature) if article.org_signature else None,
                json.dumps(list(article.cites), separators=(",", ":")),
                state, _ts_iso(article.provenance.timestamp), None,
                article.trust_score, _ts_iso(article.trust_expiration) if article.trust_expiration else None,
            ),
        )

    def get(self, article_id: str) -> Any:
        return self._exec_retry("SELECT * FROM articles WHERE id=?", (article_id,)).fetchone()

    def set_state(self, article_id: str, new_state: str) -> None:
        self._exec_retry("UPDATE articles SET state=? WHERE id=?", (new_state, article_id))

    def add_cite(self, source_id: str, cited_id: str) -> None:
        self._exec_retry(
            "INSERT OR IGNORE INTO provenance_edges (source_id, cited_id) VALUES (?, ?)",
            (source_id, cited_id),
        )

    def cited_by(self, article_id: str) -> list[str]:
        cur = self._exec_retry(
            "SELECT source_id FROM provenance_edges WHERE cited_id=?", (article_id,)
        )
        return [r[0] for r in cur.fetchall()]

    def iter_ids(self) -> Iterable[str]:
        cur = self._exec_retry("SELECT id FROM articles", ())
        for row in cur.fetchall():
            yield row[0]

    def event_log_append(self, event: str, article_id: str | None, payload: dict) -> None:
        self._exec_retry(
            "INSERT INTO events (ts, event, article_id, payload_json) VALUES (?,?,?,?)",
            (
                datetime.now(UTC).isoformat(),
                event, article_id,
                json.dumps(payload, sort_keys=True, separators=(",", ":")),
            ),
        )

    def recent_events(self, limit: int = 100) -> list[tuple]:
        cur = self._exec_retry(
            "SELECT seq, event, article_id, payload_json FROM events ORDER BY seq DESC LIMIT ?",
            (limit,),
        )
        return [(r[0], r[1], r[2], r[3]) for r in cur.fetchall()]

    def _exec_retry(self, sql: str, params: tuple) -> sqlite3.Cursor:
        last: sqlite3.OperationalError | None = None
        for _ in range(3):
            try:
                return self._do_exec(sql, params)
            except sqlite3.OperationalError as e:
                last = e
                time.sleep(0.2)
        raise last  # type: ignore[misc]

    def _do_exec(self, sql: str, params: tuple) -> sqlite3.Cursor:
        return self._conn.execute(sql, params)
