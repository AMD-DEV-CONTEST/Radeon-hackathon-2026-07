import json

import services.database_registry as registry
from app.dependencies.auth import ADMIN_API_KEY, USER_API_KEY
from main import app
from services.db import close_connection, get_db, init_db
from tests.asgi_client import asgi_request


ADMIN = {"X-API-Key": ADMIN_API_KEY}
USER = {"X-API-Key": USER_API_KEY}


def setup_runtime(tmp_path, monkeypatch):
    root = tmp_path / "runtime"
    monkeypatch.setattr(registry, "REGISTRY_PATH", str(root / "registry.db"))
    monkeypatch.setattr(registry, "DATABASES_ROOT", str(root / "databases"))
    monkeypatch.setattr(registry, "OLD_DB_PATH", str(root / "missing.db"))
    registry.init_registry()
    init_db()


def request(method, path, *, headers=USER, json_body=None, params=None):
    return asgi_request(
        app,
        method,
        path,
        headers=headers,
        json_body=json_body,
        params=params,
    )


def create_source(title="源章节", language_code="zh-CN"):
    status, body = request(
        "POST",
        "/api/books/default/chapters",
        json_body={"title": title, "volume_id": "VOL_1", "language_code": language_code},
    )
    assert status == 200
    return body


def create_localization(chapter_id, language_code="en-US"):
    status, body = request(
        "POST",
        f"/api/chapters/{chapter_id}/localizations",
        headers=ADMIN,
        json_body={"language_code": language_code},
    )
    assert status == 200
    return body


def test_legacy_chapters_are_mapped_idempotently_without_changing_ids(tmp_path, monkeypatch):
    setup_runtime(tmp_path, monkeypatch)
    db = get_db()
    db.execute(
        "UPDATE books SET metadata=? WHERE book_id='default'",
        (json.dumps({"source_language": "en-us"}),),
    )
    db.execute(
        "INSERT INTO chapters(chapter_id,book_id,chapter_index,title,content) "
        "VALUES('CHP_LEGACY','default',7,'Legacy','Original text')"
    )
    db.commit()
    db.close()

    init_db()
    init_db()
    db = get_db()
    chapter = db.execute(
        "SELECT chapter_id,title FROM chapters WHERE chapter_id='CHP_LEGACY'"
    ).fetchone()
    localization = db.execute(
        "SELECT * FROM chapter_localizations WHERE chapter_id='CHP_LEGACY'"
    ).fetchone()
    group_count = db.execute("SELECT COUNT(*) FROM content_groups").fetchone()[0]
    localization_count = db.execute(
        "SELECT COUNT(*) FROM chapter_localizations"
    ).fetchone()[0]

    assert chapter["chapter_id"] == "CHP_LEGACY"
    assert chapter["title"] == "Legacy"
    assert localization["language_code"] == "en-US"
    assert localization["is_source"] == 1
    assert localization["translation_status"] == "approved"
    assert localization["content_hash"] == localization["source_revision_hash"]
    assert group_count == 1
    assert localization_count == 1
    close_connection()


def test_linked_language_versions_share_identity_order_and_list_contract(tmp_path, monkeypatch):
    setup_runtime(tmp_path, monkeypatch)
    source = create_source()
    source_id = source["chapter_id"]

    assert request(
        "POST",
        f"/api/chapters/{source_id}/localizations",
        headers=None,
        json_body={"language_code": "en-US"},
    )[0] == 401

    created = create_localization(source_id)
    target = created["chapter"]
    assert target["chapter_id"] != source_id
    assert target["content_group_id"] == source["content_group_id"]
    assert target["source_chapter_id"] == source_id
    assert target["language_code"] == "en-US"
    assert target["is_source"] == 0
    assert target["chapter_index"] == source["chapter_index"]
    assert target["volume_id"] == source["volume_id"]
    assert target["translation_status"] == "draft"

    status, default_list = request("GET", "/api/books/default/chapters")
    assert status == 200
    assert [item["chapter_id"] for item in default_list["chapters"]] == [source_id]

    status, english_list = request(
        "GET",
        "/api/books/default/chapters",
        params={"language_code": "en-us"},
    )
    assert status == 200
    assert english_list["language_code"] == "en-US"
    assert [item["chapter_id"] for item in english_list["chapters"]] == [
        target["chapter_id"]
    ]

    status, localizations = request(
        "GET",
        f"/api/content-groups/{source['content_group_id']}/localizations",
    )
    assert status == 200
    assert localizations["source_chapter_id"] == source_id
    assert len(localizations["localizations"]) == 2
    assert sum(item["is_source"] for item in localizations["localizations"]) == 1

    duplicate_status, duplicate = request(
        "POST",
        f"/api/chapters/{source_id}/localizations",
        headers=ADMIN,
        json_body={"language_code": "en-US"},
    )
    assert duplicate_status == 409
    assert duplicate["detail"]["code"] == "CHAPTER_LOCALIZATION_EXISTS"
    assert request(
        "POST",
        f"/api/chapters/{source_id}/localizations",
        headers=ADMIN,
        json_body={"language_code": "../bad"},
    )[0] == 422
    close_connection()


def test_source_revision_marks_existing_translation_stale_without_deleting_it(
    tmp_path,
    monkeypatch,
):
    setup_runtime(tmp_path, monkeypatch)
    source = create_source()
    source_id = source["chapter_id"]
    target = create_localization(source_id)["chapter"]
    target_id = target["chapter_id"]

    target_text = "A preserved English translation."
    status, _ = request(
        "PUT",
        f"/api/chapters/{target_id}",
        headers=ADMIN,
        json_body={"title": "English title", "content": target_text},
    )
    assert status == 200
    db = get_db()
    db.execute(
        "UPDATE chapter_localizations "
        "SET translation_status='approved',approval_status='approved' "
        "WHERE chapter_id=?",
        (target_id,),
    )
    db.commit()
    source_before = db.execute(
        "SELECT content_revision,content_hash FROM chapter_localizations WHERE chapter_id=?",
        (source_id,),
    ).fetchone()
    db.close()

    status, saved = request(
        "PUT",
        f"/api/chapters/{source_id}",
        headers=ADMIN,
        json_body={"title": "源章节修订", "content": "源正文已经修改。"},
    )
    assert status == 200
    assert saved["localization"]["content_revision"] == source_before["content_revision"] + 1
    assert saved["localization"]["content_hash"] != source_before["content_hash"]
    assert saved["localization"]["stale_localization_count"] == 1

    status, target_response = request("GET", f"/api/chapters/{target_id}")
    assert status == 200
    stale = target_response["chapter"]
    assert stale["content"] == target_text
    assert stale["translation_status"] == "stale"
    assert stale["approval_status"] == "outdated"
    assert stale["source_revision_hash"] != saved["localization"]["content_hash"]

    status, target_saved = request(
        "PUT",
        f"/api/chapters/{target_id}",
        headers=ADMIN,
        json_body={"content": f"{target_text} Edited."},
    )
    assert status == 200
    assert target_saved["localization"]["translation_status"] == "stale"
    assert target_saved["localization"]["approval_status"] == "outdated"
    close_connection()


def test_localizations_share_temporal_context_and_source_delete_scope(
    tmp_path,
    monkeypatch,
):
    setup_runtime(tmp_path, monkeypatch)
    source = create_source()
    source_id = source["chapter_id"]
    target = create_localization(source_id)["chapter"]
    target_id = target["chapter_id"]

    db = get_db()
    db.execute(
        "INSERT INTO entities(entity_id,entity_type,title,book_id) "
        "VALUES('CHAR_LOCALIZED','character','Mira','default')"
    )
    db.commit()
    db.close()
    status, anchor = request(
        "POST",
        "/api/temporal/anchors",
        headers=ADMIN,
        json_body={
            "database_id": "default",
            "book_id": "default",
            "anchor_type": "order_only",
            "label": "Opening",
            "order_hint": 1,
        },
    )
    assert status == 201
    anchor = anchor["anchor"]
    context = {
        "database_id": "default",
        "book_id": "default",
        "timeline_id": anchor["timeline_id"],
        "anchor_id": anchor["id"],
        "viewpoint_entity_id": "CHAR_LOCALIZED",
    }
    assert request(
        "PUT",
        f"/api/chapters/{source_id}/temporal-context",
        headers=ADMIN,
        json_body=context,
    )[0] == 200

    status, target_context = request(
        "GET",
        f"/api/chapters/{target_id}/temporal-context",
        params={"database_id": "default", "book_id": "default"},
    )
    assert status == 200
    assert target_context["context"]["anchor_id"] == anchor["id"]
    assert target_context["context"]["viewpoint_entity_id"] == "CHAR_LOCALIZED"

    status, deleted = request(
        "DELETE",
        f"/api/chapters/{source_id}",
        headers=ADMIN,
    )
    assert status == 200
    assert deleted["deleted_localizations"] == 2
    assert request("GET", "/api/books/default/chapters")[1]["chapters"] == []
    close_connection()
