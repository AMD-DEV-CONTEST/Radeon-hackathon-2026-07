import sqlite3

import services.database_registry as registry
from app.models import ContextMapRequest, ContextNeed
from services.consistency import ConsistencyChecker
from services.context_engine import create_context_map, owner_fingerprint
from services.db import close_connection, get_db, init_db
from services.temporal import create_anchor, create_relation, create_state_segment


def setup_runtime(tmp_path, monkeypatch):
    root = tmp_path / "runtime"
    monkeypatch.setattr(registry, "REGISTRY_PATH", str(root / "registry.db"))
    monkeypatch.setattr(registry, "DATABASES_ROOT", str(root / "databases"))
    monkeypatch.setattr(registry, "OLD_DB_PATH", str(root / "missing.db"))
    registry.init_registry()
    init_db()
    db = get_db("default")
    db.execute(
        "INSERT INTO entities(entity_id,entity_type,title,content,ai_summary,book_id) "
        "VALUES('CHAR_0001','character','Mira','base biography','Mira summary','default')"
    )
    db.execute(
        "INSERT INTO chapters(chapter_id,book_id,chapter_index,title,content) "
        "VALUES('CHP_0001','default',1,'Opening','early chapter')"
    )
    db.execute(
        "INSERT INTO chapters(chapter_id,book_id,chapter_index,title,content) "
        "VALUES('CHP_0002','default',2,'Future reveal','future chapter')"
    )
    db.execute(
        "INSERT INTO timeline_events(id,book_id,title,description) VALUES(1,'default','Early event','known now')"
    )
    db.execute(
        "INSERT INTO timeline_events(id,book_id,title,description) VALUES(2,'default','Future event','not known yet')"
    )
    db.commit()
    db.close()


def anchor(label, event_id=None):
    return create_anchor(
        {
            "database_id": "default",
            "book_id": "default",
            "timeline_id": None,
            "branch_id": None,
            "anchor_type": "event" if event_id else "order_only",
            "label": label,
            "chapter_id": None,
            "event_id": str(event_id) if event_id else None,
            "phase_id": None,
            "absolute_time": None,
            "order_hint": None,
            "confidence": "confirmed",
        }
    )


def relation(timeline_id, source, target):
    return create_relation(
        {
            "database_id": "default",
            "book_id": "default",
            "timeline_id": timeline_id,
            "branch_id": None,
            "source_anchor_id": source["id"],
            "relation_type": "before",
            "target_anchor_id": target["id"],
            "confidence": "confirmed",
            "source_chapter_id": None,
        }
    )


def state(timeline_id, label, start, end=None):
    return create_state_segment(
        {
            "database_id": "default",
            "book_id": "default",
            "entity_id": "CHAR_0001",
            "timeline_id": timeline_id,
            "branch_id": None,
            "valid_from_anchor_id": start["id"] if start else None,
            "valid_to_anchor_id": end["id"] if end else None,
            "state_type": "life_status",
            "state_payload": {"status": label},
            "source_chapter_id": None,
            "source_event_id": None,
            "confidence": "confirmed",
            "supersedes_segment_id": None,
        }
    )


def test_context_map_uses_resolved_state_and_excludes_future_events(tmp_path, monkeypatch):
    setup_runtime(tmp_path, monkeypatch)
    early = anchor("Early", 1)
    future = anchor("Future", 2)
    relation(early["timeline_id"], early, future)
    state(early["timeline_id"], "alive", early, future)
    state(early["timeline_id"], "missing", future)

    result = create_context_map(
        ContextMapRequest(
            task_id="temporal-context",
            task_type="world_consistency",
            database_id="default",
            book_id="default",
            timeline_id=early["timeline_id"],
            anchor_id=early["id"],
            chapter_id="CHP_0001",
            needs=[
                ContextNeed(context_type="mentioned_entities", query="Mira", reason="state"),
                ContextNeed(context_type="timeline_events", query="event", reason="chronology"),
                ContextNeed(context_type="chapter_summaries", query="chapter", reason="history"),
            ],
        ),
        owner_fingerprint("owner"),
    )
    serialized = str(result["candidates"])
    entity = next(item for item in result["candidates"] if item["source_type"] == "entity_state")
    assert "alive" in entity["summary"]
    assert "missing" not in entity["summary"]
    assert "Early event" in serialized
    assert "Future event" not in serialized
    assert "Future reveal" not in serialized
    assert result["profile"]["temporal_context"]["include_future_knowledge"] is False
    close_connection()


def test_consistency_only_flags_overlapping_same_scope_exclusive_states(tmp_path, monkeypatch):
    setup_runtime(tmp_path, monkeypatch)
    start = anchor("Start")
    state(start["timeline_id"], "alive", start)
    state(start["timeline_id"], "dead", start)
    checker = ConsistencyChecker(registry.get_db_path("default"))
    result = checker.check_timeline(book_id="default")
    state_conflicts = [item for item in result.conflicts if item.location.startswith("entity_state_segments:")]
    assert len(state_conflicts) == 1

    with sqlite3.connect(registry.get_db_path("default")) as conn:
        conn.execute(
            "UPDATE entity_state_segments SET branch_id='alternate' WHERE state_payload_json LIKE '%dead%'"
        )
        conn.commit()
    result = checker.check_timeline(book_id="default")
    assert not [item for item in result.conflicts if item.location.startswith("entity_state_segments:")]
    close_connection()
