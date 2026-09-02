import sqlite3

import services.database_registry as registry
from app.dependencies.auth import ADMIN_API_KEY, USER_API_KEY
from main import app
from services.db import close_connection, init_db
from tests.asgi_client import asgi_request


def request(method, path, *, json_body=None, headers=None, params=None):
    return asgi_request(app, method, path, json_body=json_body, headers=headers, params=params)


def setup_runtime(tmp_path, monkeypatch):
    root = tmp_path / "runtime"
    monkeypatch.setattr(registry, "REGISTRY_PATH", str(root / "registry.db"))
    monkeypatch.setattr(registry, "DATABASES_ROOT", str(root / "databases"))
    monkeypatch.setattr(registry, "OLD_DB_PATH", str(root / "missing.db"))
    registry.init_registry()
    init_db()
    db_path = registry.get_db_path("default")
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "INSERT INTO entities(entity_id,entity_type,title,book_id) VALUES('CHAR_0001','character','Mira','default')"
        )
        conn.execute(
            "INSERT INTO chapters(chapter_id,book_id,chapter_index,title) VALUES('CHP_0001','default',1,'Opening')"
        )
        conn.commit()
    return {"X-API-Key": ADMIN_API_KEY}, {"X-API-Key": USER_API_KEY}


def anchor(admin, label, order):
    status, body = request(
        "POST",
        "/api/temporal/anchors",
        headers=admin,
        json_body={
            "database_id": "default",
            "book_id": "default",
            "anchor_type": "order_only",
            "label": label,
            "order_hint": order,
        },
    )
    assert status == 201
    return body["anchor"]


def before(admin, timeline_id, source, target):
    status, _ = request(
        "POST",
        "/api/temporal/relations",
        headers=admin,
        json_body={
            "database_id": "default",
            "book_id": "default",
            "timeline_id": timeline_id,
            "source_anchor_id": source["id"],
            "relation_type": "before",
            "target_anchor_id": target["id"],
        },
    )
    assert status == 201


def segment(admin, timeline_id, state, start=None, end=None, supersedes=None):
    payload = {
        "database_id": "default",
        "book_id": "default",
        "entity_id": "CHAR_0001",
        "timeline_id": timeline_id,
        "state_type": "psychological",
        "state_payload": {"dominant_state": state},
        "valid_from_anchor_id": start["id"] if start else None,
        "valid_to_anchor_id": end["id"] if end else None,
        "supersedes_segment_id": supersedes,
    }
    status, body = request(
        "POST", "/api/temporal/state-segments", headers=admin, json_body=payload
    )
    assert status == 201
    return body["segment"]


def test_resolver_excludes_future_state_and_resolves_valid_interval(tmp_path, monkeypatch):
    admin, user = setup_runtime(tmp_path, monkeypatch)
    first = anchor(admin, "Before loss", 1)
    second = anchor(admin, "After loss", 2)
    third = anchor(admin, "Recovery", 3)
    before(admin, first["timeline_id"], first, second)
    before(admin, first["timeline_id"], second, third)
    segment(admin, first["timeline_id"], "trusting", first, second)
    segment(admin, first["timeline_id"], "guarded", second, None)

    status, at_first = request(
        "GET",
        "/api/entities/CHAR_0001/resolved-state",
        headers=user,
        params={
            "database_id": "default",
            "book_id": "default",
            "timeline_id": first["timeline_id"],
            "anchor_id": first["id"],
        },
    )
    assert status == 200
    assert at_first["fields"]["psychological"]["value"]["dominant_state"] == "trusting"

    status, at_third = request(
        "GET",
        "/api/entities/CHAR_0001/resolved-state",
        headers=user,
        params={
            "database_id": "default",
            "book_id": "default",
            "timeline_id": first["timeline_id"],
            "anchor_id": third["id"],
        },
    )
    assert status == 200
    assert at_third["fields"]["psychological"]["value"]["dominant_state"] == "guarded"
    close_connection()


def test_unordered_open_states_remain_conflicting_until_superseded(tmp_path, monkeypatch):
    admin, user = setup_runtime(tmp_path, monkeypatch)
    first = anchor(admin, "Unknown phase", 1)
    old = segment(admin, first["timeline_id"], "uncertain")
    segment(admin, first["timeline_id"], "determined")
    status, unresolved = request(
        "GET",
        "/api/entities/CHAR_0001/resolved-state",
        headers=user,
        params={"database_id": "default", "book_id": "default", "timeline_id": first["timeline_id"]},
    )
    assert status == 200
    assert unresolved["fields"]["psychological"]["confidence"] == "conflicting"
    assert unresolved["warnings"]

    replacement = segment(admin, first["timeline_id"], "resolved", supersedes=old["id"])
    history_status, history = request(
        "GET",
        "/api/entities/CHAR_0001/state-history",
        headers=user,
        params={"database_id": "default", "book_id": "default", "timeline_id": first["timeline_id"]},
    )
    assert history_status == 200
    archived = next(item for item in history["segments"] if item["id"] == old["id"])
    assert archived["superseded_by"] == replacement["id"]
    assert len(history["segments"]) == 3
    close_connection()


def test_chapter_context_defaults_to_no_future_knowledge(tmp_path, monkeypatch):
    admin, user = setup_runtime(tmp_path, monkeypatch)
    current = anchor(admin, "Opening", 1)
    payload = {
        "database_id": "default",
        "book_id": "default",
        "timeline_id": current["timeline_id"],
        "anchor_id": current["id"],
        "viewpoint_entity_id": "CHAR_0001",
    }
    assert request("PUT", "/api/chapters/CHP_0001/temporal-context", json_body=payload)[0] == 401
    status, body = request(
        "PUT", "/api/chapters/CHP_0001/temporal-context", headers=admin, json_body=payload
    )
    assert status == 200
    assert body["context"]["include_future_knowledge"] is False
    get_status, fetched = request(
        "GET",
        "/api/chapters/CHP_0001/temporal-context",
        headers=user,
        params={"database_id": "default", "book_id": "default"},
    )
    assert get_status == 200
    assert fetched["context"]["anchor_id"] == current["id"]
    assert fetched["context"]["include_future_knowledge"] is False
    close_connection()
