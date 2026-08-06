import sqlite3

import pytest
from pydantic import ValidationError

import services.database_registry as registry
from app.models import ContextApprovalItem, ContextApprovalRequest, ContextMapRequest, ContextNeed
from services.context_engine import approve_context, create_context_map, owner_fingerprint
from services.db import close_connection, get_db, init_db


def setup_data(tmp_path, monkeypatch):
    root = tmp_path / "runtime"
    monkeypatch.setattr(registry, "REGISTRY_PATH", str(root / "registry.db"))
    monkeypatch.setattr(registry, "DATABASES_ROOT", str(root / "databases"))
    monkeypatch.setattr(registry, "OLD_DB_PATH", str(root / "missing.db"))
    registry.init_registry()
    init_db()
    db = get_db("default")
    for entity_id, title in (("CHR_A", "林川"), ("CHR_B", "北城")):
        db.execute(
            "INSERT INTO entities(entity_id,entity_type,title,content,ai_summary,book_id) VALUES (?,?,?,?,?,?)",
            (entity_id, "character", title, f"{title}正文", f"{title}摘要", "default"),
        )
    db.commit()
    db.close()


def make_map(task_id, query, owner):
    return create_context_map(
        ContextMapRequest(
            task_id=task_id,
            task_type="world_consistency",
            database_id="default",
            book_id="default",
            needs=[ContextNeed(context_type="mentioned_entities", query=query, reason="facts")],
        ),
        owner,
    )


def test_approval_uses_server_candidate_and_does_not_modify_entities(tmp_path, monkeypatch):
    setup_data(tmp_path, monkeypatch)
    owner = owner_fingerprint("owner-a")
    context_map = make_map("task-a", "林川", owner)
    candidate_id = context_map["candidates"][0]["candidate_id"]
    db_path = registry.get_db_path("default")
    with sqlite3.connect(db_path) as conn:
        entity_before = conn.execute("SELECT content FROM entities WHERE entity_id='CHR_A'").fetchone()[0]

    result = approve_context(
        "default",
        "task-a",
        [ContextApprovalItem(candidate_id=candidate_id, approved=True)],
        owner,
    )
    assert result["approved_candidate_ids"] == [candidate_id]
    with sqlite3.connect(db_path) as conn:
        entity_after = conn.execute("SELECT content FROM entities WHERE entity_id='CHR_A'").fetchone()[0]
        event = conn.execute(
            "SELECT event_type FROM audit_log WHERE target='task-a' ORDER BY log_id DESC LIMIT 1"
        ).fetchone()[0]
    assert entity_after == entity_before
    assert event == "context.approval"
    close_connection()


def test_cross_owner_and_cross_task_candidate_approval_are_rejected(tmp_path, monkeypatch):
    setup_data(tmp_path, monkeypatch)
    owner_a = owner_fingerprint("owner-a")
    owner_b = owner_fingerprint("owner-b")
    map_a = make_map("task-a", "林川", owner_a)
    map_b = make_map("task-b", "北城", owner_a)
    item_a = ContextApprovalItem(candidate_id=map_a["candidates"][0]["candidate_id"], approved=True)
    item_b = ContextApprovalItem(candidate_id=map_b["candidates"][0]["candidate_id"], approved=True)

    with pytest.raises(KeyError):
        approve_context("default", "task-a", [item_a], owner_b)
    with pytest.raises(ValueError):
        approve_context("default", "task-a", [item_b], owner_a)
    close_connection()


def test_approval_payload_cannot_submit_candidate_content():
    with pytest.raises(ValidationError):
        ContextApprovalRequest.model_validate(
            {
                "items": [
                    {
                        "candidate_id": "ctx-" + "a" * 32,
                        "approved": True,
                        "summary": "client supplied content",
                    }
                ]
            }
        )
