"""Local multi-turn memory + evidence/artifact stores (SQLite/JSON, all local).

Implemented here: SessionMemory / EvidenceStore / ArtifactStore.
(TaskState and Preferences were named in early design docs but are NOT
implemented in this module -- the orchestrator keeps task state in-memory and
preferences live in the UI/CLI config. Docs claiming otherwise are stale.)

Everything persists under <workspace>/.screwshell/ — private by default,
nothing ever leaves the machine.
"""
from __future__ import annotations

import json
import os
import sqlite3
import time
import uuid
from dataclasses import asdict, dataclass, field
from typing import Any, Optional


def _now() -> float:
    return round(time.time(), 3)


class ArtifactStore:
    """Raw tool payloads, off the LLM context."""

    def __init__(self, root: str):
        self.root = os.path.join(root, "artifacts")
        os.makedirs(self.root, exist_ok=True)

    def put(self, kind: str, payload: Any) -> str:
        aid = f"{kind}-{uuid.uuid4().hex[:10]}"
        with open(os.path.join(self.root, aid + ".json"), "w", encoding="utf-8") as f:
            json.dump({"kind": kind, "ts": _now(), "payload": payload},
                      f, ensure_ascii=False, default=str)
        return aid

    def get(self, aid: str) -> Any:
        p = os.path.join(self.root, aid + ".json")
        if not os.path.isfile(p):
            return None
        with open(p, encoding="utf-8") as f:
            return json.load(f)["payload"]


@dataclass
class EvidenceCard:
    claim: str
    citations: list[dict]           # [{source, start_line, end_line, ...}]
    confidence: float = 0.7
    id: str = field(default_factory=lambda: "ev-" + uuid.uuid4().hex[:8])
    created: float = field(default_factory=_now)
    ttl_s: Optional[float] = None   # None = session-long

    @property
    def expired(self) -> bool:
        return self.ttl_s is not None and _now() > self.created + self.ttl_s

    def cite_str(self) -> str:
        return "; ".join(
            f"{c['source']}#L{c.get('start_line','?')}-L{c.get('end_line','?')}"
            for c in self.citations[:4])


class EvidenceStore:
    def __init__(self, root: str):
        self.path = os.path.join(root, "evidence.json")
        self.cards: list[EvidenceCard] = []
        self._load()

    def _load(self):
        if os.path.isfile(self.path):
            with open(self.path, encoding="utf-8") as f:
                self.cards = [EvidenceCard(**c) for c in json.load(f)]

    def _save(self):
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        with open(self.path, "w", encoding="utf-8") as f:
            json.dump([asdict(c) for c in self.cards], f, ensure_ascii=False, indent=1)

    def add(self, card: EvidenceCard) -> EvidenceCard:
        self.cards.append(card)
        self._save()
        return card

    def active(self) -> list[EvidenceCard]:
        return [c for c in self.cards if not c.expired]

    def context_block(self, limit: int = 8) -> str:
        cards = self.active()[-limit:]
        if not cards:
            return "(no evidence collected yet)"
        return "\n".join(
            f"- [{c.id}] {c.claim[:220]}  (sources: {c.cite_str()}, conf {c.confidence})"
            for c in cards)


class SessionMemory:
    """Multi-turn history in SQLite; survives restarts."""

    def __init__(self, root: str, session_id: str = "default"):
        os.makedirs(root, exist_ok=True)
        self.db = sqlite3.connect(os.path.join(root, "memory.db"),
                                  check_same_thread=False)
        self.session_id = session_id
        self.db.execute(
            "CREATE TABLE IF NOT EXISTS turns (session TEXT, ts REAL, role TEXT, "
            "content TEXT, meta TEXT)")
        self.db.execute(
            "CREATE TABLE IF NOT EXISTS kv (session TEXT, k TEXT, v TEXT, "
            "PRIMARY KEY (session, k))")
        self.db.commit()

    def add_turn(self, role: str, content: str, **meta):
        self.db.execute("INSERT INTO turns VALUES (?,?,?,?,?)",
                        (self.session_id, _now(), role, content,
                         json.dumps(meta, default=str)))
        self.db.commit()

    def history(self, limit: int = 12) -> list[dict]:
        """Return the MOST RECENT ``limit`` turns, ordered oldest-first.

        Two properties must hold at once, and it is easy to break one while
        fixing the other:

        1. **Recency window** -- the model must see the LATEST turns. A plain
           ``ORDER BY ts ASC LIMIT n`` returns the OLDEST n turns, so past turn
           n the model would never see what it just said (silent amnesia: no
           error, the answers merely drift off-topic and repeat questions).
        2. **Deterministic order under ts ties** -- turns written within the
           same clock tick share a ``ts``; the original ``ORDER BY ts DESC`` +
           ``reversed()`` flipped their relative order. ``rowid`` (monotonic
           insertion order) is the tiebreak.

        The inner query takes the most recent n (DESC), the outer one re-sorts
        them chronologically (ASC), so both properties hold.
        """
        rows = self.db.execute(
            "SELECT role, content FROM ("
            "  SELECT role, content, ts, rowid AS rid FROM turns WHERE session=?"
            "  ORDER BY ts DESC, rid DESC LIMIT ?"
            ") ORDER BY ts ASC, rid ASC",
            (self.session_id, limit)).fetchall()
        return [{"role": r, "content": c} for r, c in rows]

    def set(self, k: str, v: Any):
        self.db.execute("INSERT OR REPLACE INTO kv VALUES (?,?,?)",
                        (self.session_id, k, json.dumps(v, default=str)))
        self.db.commit()

    def get(self, k: str, default=None):
        row = self.db.execute("SELECT v FROM kv WHERE session=? AND k=?",
                              (self.session_id, k)).fetchone()
        return json.loads(row[0]) if row else default


@dataclass
class TaskCard:
    goal: str
    steps: list[dict] = field(default_factory=list)  # {desc, skill, status, note}
    id: str = field(default_factory=lambda: "task-" + uuid.uuid4().hex[:8])
    created: float = field(default_factory=_now)
    decisions: list[str] = field(default_factory=list)

    def render(self) -> str:
        icon = {"pending": "[ ]", "running": "[~]", "done": "[x]", "failed": "[!]"}
        lines = [f"Task {self.id}: {self.goal}"]
        for i, s in enumerate(self.steps, 1):
            lines.append(f"  {icon.get(s.get('status','pending'),'[ ]')} "
                         f"{i}. ({s.get('skill','agent')}) {s['desc']}")
        return "\n".join(lines)
