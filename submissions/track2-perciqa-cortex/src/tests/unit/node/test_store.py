import sqlite3
import time
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from cortex.node.store import ArticleStore


def make_article(
    art_id: str = "id-1",
    content: str = "hello",
    scope: str = "public",
    state: str = "signed",
) -> SimpleNamespace:
    return SimpleNamespace(
        id=art_id,
        type="finding",
        content=content,
        payload={"k": "v"},
        scope=scope,
        agent_signature=b"\x01\x02",
        org_signature=None,
        cites=[],
        provenance=SimpleNamespace(
            producer_agent="did:percq:agent:a",
            producer_org="did:percq:org:soc-alpha",
            computation_ref=None,
            source_data_hash=None,
            source_data_schema=None,
            run_id="r1",
            timestamp=datetime(2026, 7, 18, 12, 0, tzinfo=UTC),
        ),
        created_at=datetime(2026, 7, 18, 12, 0, tzinfo=UTC),
        trust_score=None,
        trust_expiration=None,
    )


def test_schema_idempotent_reopen(tmp_path: Path) -> None:
    db = tmp_path / "articles.sqlite"
    s1 = ArticleStore(db)
    s1.close()
    s2 = ArticleStore(db)
    s2.close()
    conn = sqlite3.connect(db)
    rows = conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
    conn.close()
    names = {r[0] for r in rows}
    assert {"articles", "provenance_edges", "events"}.issubset(names)


def test_put_get_round_trip(tmp_path: Path) -> None:
    s = ArticleStore(tmp_path / "a.sqlite")
    art = make_article()
    s.put(art, state="signed")
    got = s.get("id-1")
    assert got is not None
    assert got["id"] == "id-1"
    assert got["content"] == "hello"
    assert got["scope"] == "public"
    assert got["state"] == "signed"
    s.close()


def test_set_state(tmp_path: Path) -> None:
    s = ArticleStore(tmp_path / "a.sqlite")
    s.put(make_article(), state="signed")
    s.set_state("id-1", "indexed")
    assert s.get("id-1")["state"] == "indexed"
    s.close()


def test_cited_by(tmp_path: Path) -> None:
    s = ArticleStore(tmp_path / "a.sqlite")
    s.put(make_article("base"), state="signed")
    s.put(make_article("deriv"), state="signed")
    s.add_cite("deriv", "base")
    assert s.cited_by("base") == ["deriv"]
    s.close()


def test_event_log_append_and_recent(tmp_path: Path) -> None:
    s = ArticleStore(tmp_path / "a.sqlite")
    s.event_log_append("node.started", None, {"pid": 1})
    s.event_log_append("node.embed.completed", "id-1", {"ms": 12})
    ev = s.recent_events(limit=10)
    assert len(ev) == 2
    # recent_events returns DESC by seq, so latest first
    assert ev[0][1] == "node.embed.completed"
    assert ev[1][1] == "node.started"
    assert ev[0][2] == "id-1"
    s.close()


def test_operational_error_retries(tmp_path: Path, monkeypatch) -> None:
    s = ArticleStore(tmp_path / "a.sqlite")
    calls = {"n": 0}

    def boom(sql: str, params: tuple = ()) -> Any:
        calls["n"] += 1
        if calls["n"] < 3:
            raise sqlite3.OperationalError("database is locked")
        return s._conn.execute(sql, params)

    monkeypatch.setattr(s, "_do_exec", boom)
    monkeypatch.setattr(time, "sleep", lambda _x: None)
    s.event_log_append("test.event", None, {"ok": True})
    assert calls["n"] >= 3
    s.close()
