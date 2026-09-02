import sqlite3

import services.database_registry as registry
from app.dependencies.auth import ADMIN_API_KEY, USER_API_KEY, get_effective_principal
from app.deployment import (
    DeploymentMode,
    EffectivePrincipal,
    EffectiveRole,
    ROLE_CAPABILITIES,
)
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
    return {"X-API-Key": ADMIN_API_KEY}, {"X-API-Key": USER_API_KEY}


def create_anchor(admin, label, order_hint):
    status, body = request(
        "POST",
        "/api/temporal/anchors",
        headers=admin,
        json_body={
            "database_id": "default",
            "book_id": "default",
            "anchor_type": "order_only",
            "label": label,
            "order_hint": order_hint,
        },
    )
    assert status == 201
    return body["anchor"]


def test_anchor_supports_partial_order_without_fake_absolute_time(tmp_path, monkeypatch):
    admin, user = setup_runtime(tmp_path, monkeypatch)
    payload = {
        "database_id": "default",
        "book_id": "default",
        "anchor_type": "order_only",
        "label": "After the oath",
        "order_hint": 2.5,
        "confidence": "inferred",
    }
    assert request("POST", "/api/temporal/anchors", json_body=payload)[0] == 401
    status, body = request("POST", "/api/temporal/anchors", headers=admin, json_body=payload)
    assert status == 201
    anchor = body["anchor"]
    assert anchor["absolute_time"] is None
    assert anchor["confidence"] == "inferred"

    list_status, listed = request(
        "GET",
        "/api/temporal/anchors",
        headers=user,
        params={"database_id": "default", "book_id": "default"},
    )
    assert list_status == 200
    assert listed["timeline_id"] == anchor["timeline_id"]
    assert [item["id"] for item in listed["anchors"]] == [anchor["id"]]
    close_connection()


def test_temporal_writes_use_author_capability_instead_of_system_admin(tmp_path, monkeypatch):
    setup_runtime(tmp_path, monkeypatch)
    payload = {
        "database_id": "default",
        "book_id": "default",
        "anchor_type": "order_only",
        "label": "Author-managed anchor",
    }

    async def author_principal():
        return EffectivePrincipal(
            credential_role="author",
            deployment_mode=DeploymentMode.FULL_SERVER_DEPLOYMENT,
            effective_role=EffectiveRole.AUTHOR,
            capabilities=ROLE_CAPABILITIES[EffectiveRole.AUTHOR],
        )

    async def reader_principal():
        return EffectivePrincipal(
            credential_role="reader",
            deployment_mode=DeploymentMode.FULL_SERVER_DEPLOYMENT,
            effective_role=EffectiveRole.READER,
            capabilities=ROLE_CAPABILITIES[EffectiveRole.READER],
        )

    try:
        app.dependency_overrides[get_effective_principal] = author_principal
        status, body = request("POST", "/api/temporal/anchors", json_body=payload)
        assert status == 201
        assert body["anchor"]["label"] == payload["label"]

        app.dependency_overrides[get_effective_principal] = reader_principal
        status, body = request(
            "POST",
            "/api/temporal/anchors",
            json_body={**payload, "label": "Reader must not write"},
        )
        assert status == 403
        assert body["detail"]["code"] == "CAPABILITY_REQUIRED"
        assert body["detail"]["capability"] == "manage_temporal"
    finally:
        app.dependency_overrides.pop(get_effective_principal, None)
        close_connection()


def test_temporal_cycle_is_preserved_as_conflict_not_accepted_order(tmp_path, monkeypatch):
    admin, _user = setup_runtime(tmp_path, monkeypatch)
    first = create_anchor(admin, "A", 1)
    second = create_anchor(admin, "B", 2)
    third = create_anchor(admin, "C", 3)

    def relation(source, target):
        return request(
            "POST",
            "/api/temporal/relations",
            headers=admin,
            json_body={
                "database_id": "default",
                "book_id": "default",
                "timeline_id": first["timeline_id"],
                "source_anchor_id": source["id"],
                "relation_type": "before",
                "target_anchor_id": target["id"],
            },
        )

    assert relation(first, second)[1]["relation"]["cycle_detected"] is False
    assert relation(second, third)[1]["relation"]["cycle_detected"] is False
    status, body = relation(third, first)
    assert status == 201
    conflict = body["relation"]
    assert conflict["cycle_detected"] is True
    assert conflict["confidence"] == "conflicting"
    assert conflict["review_status"] == "pending"
    assert conflict["requires_confirmation"] is True

    with sqlite3.connect(registry.get_db_path("default")) as conn:
        old_events = conn.execute("SELECT COUNT(*) FROM timeline_events").fetchone()[0]
        conflicts = conn.execute(
            "SELECT COUNT(*) FROM temporal_relations WHERE confidence='conflicting'"
        ).fetchone()[0]
    assert old_events == 0
    assert conflicts == 1
    close_connection()


def test_relation_rejects_cross_timeline_anchor_scope(tmp_path, monkeypatch):
    admin, _user = setup_runtime(tmp_path, monkeypatch)
    first = create_anchor(admin, "Main", 1)
    db_path = registry.get_db_path("default")
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "INSERT INTO timelines(id,book_id,name,status) VALUES('TL_OTHER','default','Other','active')"
        )
        conn.commit()
    status, body = request(
        "POST",
        "/api/temporal/anchors",
        headers=admin,
        json_body={
            "database_id": "default",
            "book_id": "default",
            "timeline_id": "TL_OTHER",
            "anchor_type": "unknown",
            "label": "Other branch",
        },
    )
    assert status == 201
    other = body["anchor"]
    status, body = request(
        "POST",
        "/api/temporal/relations",
        headers=admin,
        json_body={
            "database_id": "default",
            "book_id": "default",
            "timeline_id": first["timeline_id"],
            "source_anchor_id": first["id"],
            "relation_type": "before",
            "target_anchor_id": other["id"],
        },
    )
    assert status == 409
    assert body["detail"]["code"] == "TEMPORAL_SCOPE_MISMATCH"
    close_connection()


def test_child_timeline_and_subjective_event_sequence_are_non_destructive(tmp_path, monkeypatch):
    admin, user = setup_runtime(tmp_path, monkeypatch)
    divergence = create_anchor(admin, "Divergence", 1)
    status, body = request(
        "POST",
        "/api/temporal/timelines",
        headers=admin,
        json_body={
            "database_id": "default",
            "book_id": "default",
            "name": "Rewritten history",
            "parent_timeline_id": divergence["timeline_id"],
            "divergence_anchor_id": divergence["id"],
        },
    )
    assert status == 201
    child = body["timeline"]
    assert child["parent_timeline_id"] == divergence["timeline_id"]

    db_path = registry.get_db_path("default")
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "INSERT INTO entities(entity_id,entity_type,title,book_id) VALUES('CHAR_TIME','character','Traveler','default')"
        )
        conn.execute(
            "INSERT INTO timeline_events(id,book_id,title,description) VALUES(7,'default','Return','Subjective continuation')"
        )
        conn.commit()
    status, metadata = request(
        "PUT",
        "/api/temporal/events/7/metadata",
        headers=admin,
        json_body={
            "database_id": "default",
            "book_id": "default",
            "timeline_id": divergence["timeline_id"],
            "world_anchor_id": divergence["id"],
            "subjective_sequence": 42,
            "viewpoint_entity_id": "CHAR_TIME",
        },
    )
    assert status == 200
    assert metadata["metadata"]["subjective_sequence"] == 42
    list_status, timelines = request(
        "GET",
        "/api/temporal/timelines",
        headers=user,
        params={"database_id": "default", "book_id": "default"},
    )
    assert list_status == 200
    assert {item["id"] for item in timelines["timelines"]} == {divergence["timeline_id"], child["id"]}
    with sqlite3.connect(db_path) as conn:
        assert conn.execute("SELECT COUNT(*) FROM timeline_events WHERE id=7").fetchone()[0] == 1
    close_connection()
