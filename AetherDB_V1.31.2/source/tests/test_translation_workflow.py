import json

import api.translate as translation_api
import services.database_registry as registry
from app.dependencies.auth import ADMIN_API_KEY, USER_API_KEY
from main import app
from services.db import close_connection, get_db, init_db
from services.model_execution.results import ModelTaskResult
from services.translation_service import parse_translation_output
from tests.asgi_client import asgi_request


ADMIN = {"X-API-Key": ADMIN_API_KEY}
USER = {"X-API-Key": USER_API_KEY}


class FakeTranslationGateway:
    def __init__(self, output=None):
        self.output = output or json.dumps(
            {
                "title": "The Northern Beacon",
                "content": "Above the snowline, the watcher lights the beacon.",
            }
        )
        self.requests = []

    async def execute(self, request):
        self.requests.append(request)
        return ModelTaskResult(
            task_id=request.task_id,
            model_profile_id=request.user_selected_model_id or "local-translator",
            provider_id="local-provider",
            provider_model_name="author-model",
            raw_provider_request_id="provider-request",
            content=self.output,
            usage={"input_tokens": 100, "output_tokens": 40},
        )


def setup_runtime(tmp_path, monkeypatch):
    root = tmp_path / "runtime"
    monkeypatch.setattr(registry, "REGISTRY_PATH", str(root / "registry.db"))
    monkeypatch.setattr(registry, "DATABASES_ROOT", str(root / "databases"))
    monkeypatch.setattr(registry, "OLD_DB_PATH", str(root / "missing.db"))
    registry.init_registry()
    init_db()


def request(method, path, *, headers=ADMIN, json_body=None, params=None):
    return asgi_request(
        app,
        method,
        path,
        headers=headers,
        json_body=json_body,
        params=params,
    )


def create_source(title="北境灯塔", content="雪线之上，守望者点亮了灯塔。"):
    status, chapter = request(
        "POST",
        "/api/books/default/chapters",
        headers=USER,
        json_body={"title": title, "language_code": "zh-CN"},
    )
    assert status == 200
    assert request(
        "PUT",
        f"/api/chapters/{chapter['chapter_id']}",
        json_body={"title": title, "content": content},
    )[0] == 200
    return request("GET", f"/api/chapters/{chapter['chapter_id']}")[1]["chapter"]


def install_gateway(fake):
    app.dependency_overrides[translation_api.get_translation_gateway] = lambda: fake


def remove_gateway():
    app.dependency_overrides.pop(translation_api.get_translation_gateway, None)


def test_entity_translation_is_scoped_reviewed_and_marked_stale(tmp_path, monkeypatch):
    setup_runtime(tmp_path, monkeypatch)
    status, created = request(
        "POST",
        "/api/entity",
        headers=USER,
        json_body={
            "entity_type": "location",
            "title": "靖川营",
            "content": "被围困的军营。",
            "book_id": "default",
        },
    )
    assert status == 200
    entity_id = created["entity_id"]

    status, mismatch = request(
        "POST",
        f"/api/entity/{entity_id}/translate",
        json_body={
            "book_id": "another-book",
            "language": "en-US",
            "title": "Jingchuan Camp",
            "content": "A besieged military camp.",
        },
    )
    assert status == 409
    assert mismatch["detail"]["code"] == "ENTITY_TRANSLATION_SCOPE_MISMATCH"

    status, draft = request(
        "POST",
        f"/api/entity/{entity_id}/translate",
        json_body={
            "book_id": "default",
            "language": "en-us",
            "title": "Jingchuan Camp",
            "content": "A besieged military camp.",
        },
    )
    assert status == 200
    assert draft["language"] == "en-US"
    assert draft["translation_status"] == "draft"
    assert draft["approval_status"] == "pending_review"
    assert len(draft["source_hash"]) == 64

    assert request(
        "POST",
        f"/api/entity-translations/{draft['id']}/review",
        json_body={
            "action": "approve",
            "expected_source_hash": draft["source_hash"],
        },
    )[1]["translation_status"] == "approved"

    assert request(
        "PUT",
        f"/api/entity/{entity_id}",
        json_body={"content": "军营仍在收缩防线。"},
    )[0] == 200
    status, translations = request(
        "GET",
        f"/api/entity/{entity_id}/translations",
        headers=USER,
    )
    assert status == 200
    assert translations[0]["translation_status"] == "stale"
    assert translations[0]["approval_status"] == "outdated"

    db = get_db()
    audit_text = "\n".join(
        f"{row['description']} {row['details']}"
        for row in db.execute(
            "SELECT description,details FROM audit_log "
            "WHERE event_type LIKE 'entity.translation.%'"
        ).fetchall()
    )
    assert "A besieged military camp." not in audit_text
    db.close()
    close_connection()


def test_chapter_model_draft_is_durable_and_only_applies_after_approval(
    tmp_path,
    monkeypatch,
):
    setup_runtime(tmp_path, monkeypatch)
    source = create_source()
    fake = FakeTranslationGateway()
    install_gateway(fake)
    try:
        status, generated = request(
            "POST",
            f"/api/chapters/{source['chapter_id']}/translations",
            json_body={
                "target_language_code": "en-US",
                "model_profile_id": "local-translator",
                "request_id": "translation-test-1",
            },
        )
        assert status == 200
        task = generated["translation"]
        assert task["task_status"] == "review_required"
        assert task["approval_status"] == "pending_review"
        assert task["target_chapter_id"] is None
        assert task["provider_model_name"] == "author-model"
        assert fake.requests[0].task_type == "translation.chapter"
        assert fake.requests[0].privacy_level == "local_only"
        assert fake.requests[0].user_selected_model_id == "local-translator"
        assert source["content"] in fake.requests[0].messages[1]["content"]

        status, localizations = request(
            "GET",
            f"/api/chapters/{source['chapter_id']}/localizations",
            headers=USER,
        )
        assert status == 200
        assert len(localizations["localizations"]) == 1

        status, updated = request(
            "PUT",
            f"/api/translations/{task['translation_id']}",
            json_body={
                "title": "The Northern Watch",
                "content": "The reviewed English draft.",
            },
        )
        assert status == 200
        assert updated["translation"]["output_format"] == "author_edited"

        status, approved = request(
            "POST",
            f"/api/translations/{task['translation_id']}/approve",
            json_body={
                "expected_source_revision_hash": task["source_revision_hash"],
            },
        )
        assert status == 200
        target = approved["chapter"]
        assert target["chapter_id"] != source["chapter_id"]
        assert target["content_group_id"] == source["content_group_id"]
        assert target["language_code"] == "en-US"
        assert target["content"] == "The reviewed English draft."
        assert target["translation_status"] == "approved"
        assert target["approval_status"] == "approved"

        status, replayed = request(
            "POST",
            f"/api/chapters/{source['chapter_id']}/translations",
            json_body={
                "target_language_code": "en-US",
                "model_profile_id": "local-translator",
                "request_id": "translation-test-1",
            },
        )
        assert status == 200
        assert replayed["status"] == "replayed"
        assert len(fake.requests) == 1
    finally:
        remove_gateway()
        close_connection()


def test_translation_output_parser_accepts_wrapped_provider_json():
    title, content, output_format = parse_translation_output(
        """Here is the translation:
```json
{"translated_title":"The Camp","translated_content":"The night was quiet."}
```
""",
        source_title="源标题",
    )

    assert title == "The Camp"
    assert content == "The night was quiet."
    assert output_format == "json"


def test_source_change_prevents_old_model_draft_approval(tmp_path, monkeypatch):
    setup_runtime(tmp_path, monkeypatch)
    source = create_source()
    fake = FakeTranslationGateway(output="A recoverable plain-text draft.")
    install_gateway(fake)
    try:
        status, generated = request(
            "POST",
            f"/api/chapters/{source['chapter_id']}/translations",
            json_body={
                "target_language_code": "en-US",
                "cloud_upload_confirmed": True,
                "request_id": "translation-stale-test",
            },
        )
        assert status == 200
        task = generated["translation"]
        assert task["output_format"] == "plain_text_recovery"
        assert fake.requests[0].privacy_level == "private"

        assert request(
            "PUT",
            f"/api/chapters/{source['chapter_id']}",
            json_body={"content": "源章节在审核前发生了变化。"},
        )[0] == 200
        status, conflict = request(
            "POST",
            f"/api/translations/{task['translation_id']}/approve",
            json_body={
                "expected_source_revision_hash": task["source_revision_hash"],
            },
        )
        assert status == 409
        assert conflict["detail"]["code"] == "TRANSLATION_SOURCE_CHANGED"

        status, listing = request(
            "GET",
            f"/api/chapters/{source['chapter_id']}/translations",
            headers=USER,
        )
        assert status == 200
        assert listing["translations"][0]["task_status"] == "stale"
        assert listing["translations"][0]["draft_content"] == (
            "A recoverable plain-text draft."
        )
    finally:
        remove_gateway()
        close_connection()


def test_manual_chapter_translation_requires_explicit_review(tmp_path, monkeypatch):
    setup_runtime(tmp_path, monkeypatch)
    source = create_source()
    status, created = request(
        "POST",
        f"/api/chapters/{source['chapter_id']}/localizations",
        json_body={"language_code": "en-US"},
    )
    assert status == 200
    target = created["chapter"]
    assert request(
        "PUT",
        f"/api/chapters/{target['chapter_id']}",
        json_body={
            "title": "Northern Beacon",
            "content": "A manually translated chapter.",
        },
    )[0] == 200
    source_hash = next(
        item["content_hash"]
        for item in created["localizations"]
        if item["is_source"]
    )
    status, reviewed = request(
        "POST",
        f"/api/chapters/{target['chapter_id']}/translation-review",
        json_body={
            "action": "approve",
            "expected_source_revision_hash": source_hash,
        },
    )
    assert status == 200
    assert reviewed["chapter"]["translation_status"] == "approved"
    assert reviewed["chapter"]["approval_status"] == "approved"
    close_connection()
