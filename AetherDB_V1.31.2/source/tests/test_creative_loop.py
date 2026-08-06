import sqlite3

import pytest

import services.database_registry as registry
from api import chapters as chapters_api
from app.dependencies.auth import ADMIN_API_KEY, USER_API_KEY
from main import app
from services.db import close_connection, init_db
from services.import_pipeline import ImportChangeSet, ImportPipeline as RealImportPipeline
from tests.asgi_client import asgi_request


def test_formal_entities_are_written_only_after_changeset_confirmation(tmp_path, monkeypatch):
    root = tmp_path / "runtime"
    monkeypatch.setattr(registry, "REGISTRY_PATH", str(root / "registry.db"))
    monkeypatch.setattr(registry, "DATABASES_ROOT", str(root / "databases"))
    monkeypatch.setattr(registry, "OLD_DB_PATH", str(root / "missing.db"))
    registry.init_registry()
    init_db()

    class ControlledPipeline:
        def __init__(self, *args, **kwargs):
            pass

        def preview(self, text, book_id="default"):
            return ImportChangeSet(
                entities=[
                    {
                        "title": "待确认角色",
                        "type": "character",
                        "content": "仅在确认后写入",
                        "tags": ["test"],
                        "importance": 3,
                    }
                ],
                relations=[],
                book_id=book_id,
            )

        def commit(self, changeset, **kwargs):
            return RealImportPipeline(validators=[], post_commit_hooks=[]).commit(changeset, **kwargs)

    monkeypatch.setattr(chapters_api, "ImportPipeline", ControlledPipeline)
    user = {"X-API-Key": USER_API_KEY}
    admin = {"X-API-Key": ADMIN_API_KEY}

    status, created = asgi_request(
        app,
        "POST",
        "/api/books/default/chapters",
        headers=user,
        params={"title": "测试章节"},
    )
    assert status == 200
    chapter_id = created["chapter_id"]
    assert asgi_request(
        app,
        "PUT",
        f"/api/chapters/{chapter_id}",
        headers=admin,
        params={"content": "这是用于分析的章节正文。" * 10},
    )[0] == 200
    assert asgi_request(
        app,
        "POST",
        f"/api/chapters/{chapter_id}/analyze",
        headers=user,
        params={"analysis_mode": "cloud_model"},
    )[0] == 200
    changeset_status, changeset = asgi_request(
        app,
        "POST",
        f"/api/chapters/{chapter_id}/changeset",
        headers=user,
    )
    assert changeset_status == 200
    changeset_id = changeset["changeset_id"]
    assert asgi_request(
        app,
        "GET",
        f"/api/changesets/{changeset_id}",
        headers=user,
    )[1]["status"] == "pending"

    db_path = registry.get_db_path("default")
    with sqlite3.connect(db_path) as conn:
        before = conn.execute("SELECT COUNT(*) FROM entities WHERE title='待确认角色'").fetchone()[0]
    assert before == 0

    first_status, first = asgi_request(
        app,
        "POST",
        f"/api/changesets/{changeset_id}/confirm",
        headers=user,
    )
    assert first_status == 200
    assert first["idempotent_replay"] is False
    second_status, second = asgi_request(
        app,
        "POST",
        f"/api/changesets/{changeset_id}/confirm",
        headers=user,
    )
    assert second_status == 200
    assert second["idempotent_replay"] is True
    third_status, third = asgi_request(
        app,
        "POST",
        f"/api/chapters/{chapter_id}/changeset/confirm",
        headers=user,
    )
    assert third_status == 200
    assert third["changeset_id"] == changeset_id
    assert third["idempotent_replay"] is True
    with sqlite3.connect(db_path) as conn:
        after = conn.execute("SELECT COUNT(*) FROM entities WHERE title='待确认角色'").fetchone()[0]
        receipts = conn.execute(
            "SELECT COUNT(*) FROM import_task_receipts WHERE task_id=?",
            (changeset_id,),
        ).fetchone()[0]
    assert after == 1
    assert receipts == 1
    confirmed = asgi_request(
        app,
        "GET",
        f"/api/changesets/{changeset_id}",
        headers=user,
    )[1]
    assert confirmed["status"] == "confirmed"
    assert confirmed["result"]["created_entities"] == 1
    close_connection()


def test_changeset_commit_rolls_back_when_confirmation_state_update_fails(tmp_path, monkeypatch):
    root = tmp_path / "runtime"
    monkeypatch.setattr(registry, "REGISTRY_PATH", str(root / "registry.db"))
    monkeypatch.setattr(registry, "DATABASES_ROOT", str(root / "databases"))
    monkeypatch.setattr(registry, "OLD_DB_PATH", str(root / "missing.db"))
    registry.init_registry()
    init_db()
    from services.db import get_db

    db = get_db("default")
    changeset = ImportChangeSet(
        entities=[{"title": "不应残留", "type": "concept", "content": "rollback"}],
        relations=[],
        book_id="default",
    )

    def fail_before_commit(connection):
        raise RuntimeError("state update failed")

    with pytest.raises(RuntimeError):
        RealImportPipeline(validators=[], post_commit_hooks=[]).commit(
            changeset,
            db=db,
            before_commit=fail_before_commit,
        )
    remaining = db.execute("SELECT COUNT(*) FROM entities WHERE title='不应残留'").fetchone()[0]
    assert remaining == 0
    db.close()
    close_connection()


def test_changeset_commit_normalizes_model_importance_labels(tmp_path, monkeypatch):
    root = tmp_path / "runtime"
    monkeypatch.setattr(registry, "REGISTRY_PATH", str(root / "registry.db"))
    monkeypatch.setattr(registry, "DATABASES_ROOT", str(root / "databases"))
    monkeypatch.setattr(registry, "OLD_DB_PATH", str(root / "missing.db"))
    registry.init_registry()
    init_db()

    changeset = ImportChangeSet(
        entities=[
            {
                "title": "Label Importance",
                "type": "concept",
                "content": "Model returned a localized label.",
                "importance": "高",
            }
        ],
        relations=[],
        book_id="default",
    )
    result = RealImportPipeline(validators=[], post_commit_hooks=[]).commit(changeset)

    assert result["created_entities"] == 1
    with sqlite3.connect(registry.get_db_path("default")) as conn:
        stored = conn.execute(
            "SELECT importance FROM entities WHERE title='Label Importance'"
        ).fetchone()[0]
    assert stored == 8
    close_connection()
