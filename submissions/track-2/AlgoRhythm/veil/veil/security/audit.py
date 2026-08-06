"""Hash-chained append-only audit log.

Every consequential action — a run starting, a persona finding something, an
edit being applied, a role viewing a finding — lands here. Each entry carries
the hash of its predecessor, so removing or altering an entry breaks the chain
and `verify()` says exactly where.

This is the artefact that lets a regulated user answer "prove nothing was
quietly deleted". It is also, deliberately, the one part of VEIL that a VEIL
operator cannot edit.
"""
from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from typing import Any

from veil.config import CONFIG
from veil.types import content_hash, now_ms

_GENESIS = "0" * 64

_SCHEMA = """
CREATE TABLE IF NOT EXISTS audit_log (
    seq        INTEGER PRIMARY KEY AUTOINCREMENT,
    ts_ms      INTEGER NOT NULL,
    actor      TEXT NOT NULL,
    action     TEXT NOT NULL,
    payload    TEXT NOT NULL,
    prev_hash  TEXT NOT NULL,
    entry_hash TEXT NOT NULL
);
"""


@dataclass
class ChainStatus:
    ok: bool
    entries: int
    broken_at: int | None = None
    detail: str = ""


class AuditLog:
    def __init__(self, db_path: str | None = None, actor: str = "system") -> None:
        self.db_path = db_path or CONFIG.storage.db_path
        self.actor = actor
        con = self._con()
        try:
            con.executescript(_SCHEMA)
            con.commit()
        finally:
            con.close()

    def _con(self) -> sqlite3.Connection:
        return sqlite3.connect(self.db_path)

    def _tip(self, con: sqlite3.Connection) -> str:
        row = con.execute(
            "SELECT entry_hash FROM audit_log ORDER BY seq DESC LIMIT 1"
        ).fetchone()
        return row[0] if row else _GENESIS

    def append(self, action: str, payload: Any, actor: str | None = None) -> str:
        ts = now_ms()
        who = actor or self.actor
        body = json.dumps(payload, default=str, sort_keys=True)
        con = self._con()
        try:
            prev = self._tip(con)
            entry = content_hash(prev, str(ts), who, action, body)
            con.execute(
                "INSERT INTO audit_log (ts_ms, actor, action, payload, prev_hash, entry_hash) "
                "VALUES (?,?,?,?,?,?)",
                (ts, who, action, body, prev, entry),
            )
            con.commit()
        finally:
            con.close()
        return entry

    def verify(self) -> ChainStatus:
        con = self._con()
        try:
            rows = con.execute(
                "SELECT seq, ts_ms, actor, action, payload, prev_hash, entry_hash "
                "FROM audit_log ORDER BY seq"
            ).fetchall()
        finally:
            con.close()

        prev = _GENESIS
        for seq, ts, actor, action, payload, prev_hash, entry_hash in rows:
            if prev_hash != prev:
                return ChainStatus(
                    False, len(rows), seq,
                    f"Entry {seq} expects predecessor {prev[:12]}… but records {prev_hash[:12]}… "
                    "— an entry was removed or reordered.",
                )
            recomputed = content_hash(prev_hash, str(ts), actor, action, payload)
            if recomputed != entry_hash:
                return ChainStatus(
                    False, len(rows), seq,
                    f"Entry {seq} hash mismatch — its contents were altered after writing.",
                )
            prev = entry_hash

        return ChainStatus(True, len(rows), None, f"{len(rows)} entries, chain intact.")

    def tail(self, n: int = 50) -> list[dict[str, Any]]:
        con = self._con()
        try:
            rows = con.execute(
                "SELECT seq, ts_ms, actor, action, payload, entry_hash "
                "FROM audit_log ORDER BY seq DESC LIMIT ?",
                (n,),
            ).fetchall()
        finally:
            con.close()
        return [
            {
                "seq": r[0],
                "ts_ms": r[1],
                "actor": r[2],
                "action": r[3],
                "payload": json.loads(r[4]),
                "entry_hash": r[5][:16],
            }
            for r in rows
        ]
