"""Entity ledger — cross-document consistency tracking.

Single-document redaction misses the attack that actually works in practice:
the same person appears in three documents, each redacted in isolation, and the
union of what survives identifies them. The ledger is the memory that catches
this. It is also the long-term-memory capability claimed in the brief.

Aliases are content-addressed, not sequential, so PERSON_A in one session and
PERSON_A in another do not silently merge.
"""
from __future__ import annotations

import json
import sqlite3
from typing import Any

from veil.config import CONFIG
from veil.tools.registry import REGISTRY
from veil.types import content_hash, now_ms

_SCHEMA = """
CREATE TABLE IF NOT EXISTS entities (
    alias        TEXT PRIMARY KEY,
    kind         TEXT NOT NULL,
    attributes   TEXT NOT NULL DEFAULT '{}',
    first_seen   INTEGER NOT NULL,
    last_seen    INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS entity_mentions (
    alias        TEXT NOT NULL,
    document_id  TEXT NOT NULL,
    surface      TEXT NOT NULL,
    ts_ms        INTEGER NOT NULL,
    PRIMARY KEY (alias, document_id, surface)
);
"""


def _con() -> sqlite3.Connection:
    con = sqlite3.connect(CONFIG.storage.db_path)
    con.executescript(_SCHEMA)
    return con


def make_alias(kind: str, canonical: str) -> str:
    """Deterministic pseudonym. Same person, same alias, every document —
    which is what makes cross-document accumulation visible."""
    return f"{kind.upper()}_{content_hash(kind, canonical.lower().strip())[:6].upper()}"


def record_mention(
    canonical: str,
    kind: str,
    document_id: str,
    surface: str,
    attributes: dict[str, Any] | None = None,
) -> str:
    alias = make_alias(kind, canonical)
    ts = now_ms()
    con = _con()
    try:
        row = con.execute(
            "SELECT attributes FROM entities WHERE alias = ?", (alias,)
        ).fetchone()
        merged = json.loads(row[0]) if row else {}
        for k, v in (attributes or {}).items():
            merged.setdefault(k, [])
            if v not in merged[k]:
                merged[k].append(v)
        if row:
            con.execute(
                "UPDATE entities SET attributes = ?, last_seen = ? WHERE alias = ?",
                (json.dumps(merged), ts, alias),
            )
        else:
            con.execute(
                "INSERT INTO entities VALUES (?,?,?,?,?)",
                (alias, kind, json.dumps(merged), ts, ts),
            )
        con.execute(
            "INSERT OR REPLACE INTO entity_mentions VALUES (?,?,?,?)",
            (alias, document_id, surface, ts),
        )
        con.commit()
    finally:
        con.close()
    return alias


@REGISTRY.register(
    name="entity_ledger",
    description=(
        "Look up what is already known about an entity across every document "
        "processed in this workspace. Use this to detect accumulation: "
        "attributes that are individually harmless but jointly identifying "
        "once combined with earlier documents."
    ),
    parameters={
        "type": "object",
        "properties": {
            "alias": {
                "type": "string",
                "description": "Alias to inspect, e.g. PERSON_3F9A2C. Omit to list all.",
            }
        },
    },
)
def entity_ledger(alias: str | None = None) -> dict[str, Any]:
    con = _con()
    try:
        if alias:
            row = con.execute(
                "SELECT alias, kind, attributes, first_seen, last_seen "
                "FROM entities WHERE alias = ?",
                (alias,),
            ).fetchone()
            if not row:
                return {"found": False, "alias": alias}
            docs = [
                {"document_id": d, "surface": s}
                for d, s in con.execute(
                    "SELECT document_id, surface FROM entity_mentions WHERE alias = ?",
                    (alias,),
                ).fetchall()
            ]
            attrs = json.loads(row[2])
            return {
                "found": True,
                "alias": row[0],
                "kind": row[1],
                "known_attributes": attrs,
                "attribute_count": sum(len(v) for v in attrs.values()),
                "documents": docs,
                "accumulation_warning": (
                    "This entity appears in multiple documents; the union of "
                    "attributes may identify them even if each document is "
                    "individually safe."
                )
                if len(docs) > 1
                else None,
            }
        rows = con.execute(
            "SELECT alias, kind, attributes FROM entities ORDER BY last_seen DESC LIMIT 50"
        ).fetchall()
    finally:
        con.close()
    return {
        "entities": [
            {
                "alias": r[0],
                "kind": r[1],
                "attribute_count": sum(len(v) for v in json.loads(r[2]).values()),
            }
            for r in rows
        ]
    }
