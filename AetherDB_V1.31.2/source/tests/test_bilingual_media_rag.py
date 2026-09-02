import io
import struct

import pytest

import services.database_registry as registry
import services.media_vision as media_vision
from app.dependencies.auth import USER_API_KEY
from app.models import ContextApprovalItem, ContextMapRequest, ContextNeed, TokenBudget
from main import app
from services.chapter_localization import (
    chapter_content_hash,
    create_linked_localization,
    ensure_chapter_localizations,
    synchronize_chapter_localization,
)
from services.context_engine import (
    approve_context,
    build_evidence_pack,
    create_context_map,
    owner_fingerprint,
)
from services.db import close_connection, get_db, init_db
from services.media_assets import (
    MediaAssetError,
    add_media_annotation,
    create_media_binding,
    import_media_asset,
    list_effective_chapter_media,
    transition_media_asset,
)
from tests.asgi_client import asgi_request


def setup_runtime(tmp_path, monkeypatch):
    root = tmp_path / "runtime"
    monkeypatch.setattr(registry, "REGISTRY_PATH", str(root / "registry.db"))
    monkeypatch.setattr(registry, "DATABASES_ROOT", str(root / "databases"))
    monkeypatch.setattr(registry, "OLD_DB_PATH", str(root / "missing.db"))
    registry.init_registry()
    init_db()
    conn = get_db()
    conn.execute(
        """INSERT INTO chapters(
            chapter_id,book_id,chapter_index,title,content,status,is_active
        ) VALUES(
            'CHP_ZH','default',1,'烽火','AetherKey 中文源章节','draft',1
        )"""
    )
    ensure_chapter_localizations(conn, database_id="default")
    create_linked_localization(
        conn,
        base_chapter_id="CHP_ZH",
        chapter_id="CHP_EN",
        language_code="en-US",
        title="Beacon",
        database_id="default",
    )
    conn.execute(
        "UPDATE chapters SET content='AetherKey approved English chapter' "
        "WHERE chapter_id='CHP_EN'"
    )
    synchronize_chapter_localization(
        conn,
        "CHP_EN",
        database_id="default",
    )
    source = conn.execute(
        "SELECT content_group_id,content_hash FROM chapter_localizations "
        "WHERE chapter_id='CHP_ZH'"
    ).fetchone()
    conn.execute(
        """UPDATE chapter_localizations
              SET translation_status='approved',approval_status='approved',
                  source_revision_hash=?
            WHERE chapter_id='CHP_EN'""",
        (source["content_hash"],),
    )
    conn.commit()
    conn.close()
    return source["content_group_id"]


def png_bytes(width=4, height=4):
    return (
        b"\x89PNG\r\n\x1a\n"
        + struct.pack(">I", 13)
        + b"IHDR"
        + struct.pack(">II", width, height)
        + b"\x08\x06\x00\x00\x00"
    )


def create_asset(*, width=4):
    asset = import_media_asset(
        "default",
        "default",
        stream=io.BytesIO(png_bytes(width, width)),
        filename=f"image-{width}.png",
        declared_mime="image/png",
    )
    return transition_media_asset("default", asset["asset_id"], "approve")


def add_caption(asset_id, text, language_code):
    return add_media_annotation(
        "default",
        asset_id,
        {
            "annotation_type": "caption",
            "payload": {"caption": text},
            "source_type": "manual",
            "approval_status": "approved",
            "language_code": language_code,
        },
    )


def token_budget():
    return TokenBudget(
        total_context_tokens=4096,
        reserved_instruction=500,
        reserved_current_text=500,
        reserved_evidence=1800,
        reserved_output=1000,
    )


class FakeMediaIndex:
    def __init__(self, asset_ids):
        self.asset_ids = asset_ids
        self.calls = []

    def search_text(self, **kwargs):
        self.calls.append(kwargs)
        return {
            "results": [
                {"asset_id": asset_id, "score": 0.9}
                for asset_id in self.asset_ids
            ],
            "channels": {
                "caption": {
                    "used": True,
                    "vector_space_id": "bge-m3-media-caption-1024-v1",
                }
            },
            "degraded": False,
        }


def test_effective_media_prefers_language_override_and_deduplicates(
    tmp_path,
    monkeypatch,
):
    content_group_id = setup_runtime(tmp_path, monkeypatch)
    shared = create_asset(width=5)
    generic_only = create_asset(width=6)
    for asset in (shared, generic_only):
        create_media_binding(
            "default",
            asset["asset_id"],
            {
                "book_id": "default",
                "target_type": "content_group",
                "target_id": content_group_id,
                "binding_type": "chapter_illustration",
            },
        )
    create_media_binding(
        "default",
        shared["asset_id"],
        {
            "book_id": "default",
            "target_type": "chapter",
            "target_id": "CHP_EN",
            "language_code": "en-US",
            "binding_type": "chapter_illustration",
        },
    )

    english = list_effective_chapter_media(
        "default",
        book_id="default",
        chapter_id="CHP_EN",
    )
    assert english["language_code"] == "en-US"
    assert len(english["assets"]) == 2
    by_id = {item["asset_id"]: item for item in english["assets"]}
    assert by_id[shared["asset_id"]]["effective_binding"]["scope"] == "language_specific"
    assert by_id[generic_only["asset_id"]]["effective_binding"]["scope"] == "content_group"

    chinese = list_effective_chapter_media(
        "default",
        book_id="default",
        chapter_id="CHP_ZH",
    )
    assert chinese["language_code"] == "zh-CN"
    assert {
        item["asset_id"] for item in chinese["assets"]
    } == {shared["asset_id"], generic_only["asset_id"]}
    assert all(
        item["effective_binding"]["scope"] == "content_group"
        for item in chinese["assets"]
    )

    with pytest.raises(MediaAssetError) as mismatch:
        create_media_binding(
            "default",
            generic_only["asset_id"],
            {
                "book_id": "default",
                "target_type": "chapter",
                "target_id": "CHP_EN",
                "language_code": "zh-CN",
                "binding_type": "language_mismatch",
            },
        )
    assert mismatch.value.code == "LANGUAGE_BINDING_MISMATCH"

    status, body = asgi_request(
        app,
        "GET",
        "/api/media-assets/effective",
        headers={"X-API-Key": USER_API_KEY},
        params={
            "database_id": "default",
            "book_id": "default",
            "chapter_id": "CHP_EN",
        },
    )
    assert status == 200
    assert body["resolution_order"] == ["language_specific", "content_group"]
    close_connection()


def test_media_rag_prefers_current_language_then_falls_back_without_duplicates(
    tmp_path,
    monkeypatch,
):
    content_group_id = setup_runtime(tmp_path, monkeypatch)
    asset = create_asset(width=7)
    create_media_binding(
        "default",
        asset["asset_id"],
        {
            "book_id": "default",
            "target_type": "content_group",
            "target_id": content_group_id,
            "binding_type": "chapter_illustration",
        },
    )
    create_media_binding(
        "default",
        asset["asset_id"],
        {
            "book_id": "default",
            "target_type": "chapter",
            "target_id": "CHP_EN",
            "binding_type": "chapter_illustration",
        },
    )
    chinese = add_caption(asset["asset_id"], "sigil 中文说明", "zh-CN")
    english = add_caption(asset["asset_id"], "sigil English description", "en-US")
    fake = FakeMediaIndex([asset["asset_id"]])
    monkeypatch.setattr(media_vision, "default_media_vision_index", lambda _database_id: fake)
    owner = owner_fingerprint("owner")

    result = create_context_map(
        ContextMapRequest(
            task_id="bilingual-media-en",
            task_type="world_consistency",
            database_id="default",
            book_id="default",
            chapter_id="CHP_EN",
            language_code="en-US",
            needs=[
                ContextNeed(
                    context_type="image_evidence",
                    query="sigil",
                    reason="setting evidence",
                )
            ],
        ),
        owner,
    )
    assert len(result["candidates"]) == 1
    candidate = result["candidates"][0]
    assert candidate["source_id"] == english["annotation_id"]
    assert candidate["metadata"]["binding_scope"] == "language_specific"
    assert candidate["metadata"]["language_code"] == "en-US"
    assert candidate["metadata"]["content_group_id"] == content_group_id
    assert [call["target_type"] for call in fake.calls] == [
        "chapter",
        "content_group",
    ]

    conn = get_db()
    conn.execute(
        "UPDATE media_annotations SET is_stale=1 WHERE annotation_id=?",
        (english["annotation_id"],),
    )
    conn.commit()
    conn.close()
    fallback = create_context_map(
        ContextMapRequest(
            task_id="bilingual-media-fallback",
            task_type="world_consistency",
            database_id="default",
            book_id="default",
            chapter_id="CHP_EN",
            language_code="en-US",
            needs=[
                ContextNeed(
                    context_type="image_evidence",
                    query="sigil",
                    reason="setting evidence",
                )
            ],
        ),
        owner,
    )
    assert len(fallback["candidates"]) == 1
    assert fallback["candidates"][0]["source_id"] == chinese["annotation_id"]
    assert fallback["candidates"][0]["metadata"]["language_code"] == "zh-CN"
    close_connection()


def test_chapter_rag_prefers_language_and_evidence_rejects_stale_translation(
    tmp_path,
    monkeypatch,
):
    content_group_id = setup_runtime(tmp_path, monkeypatch)
    owner = owner_fingerprint("owner")
    result = create_context_map(
        ContextMapRequest(
            task_id="bilingual-chapter-rag",
            task_type="world_consistency",
            database_id="default",
            book_id="default",
            chapter_id="CHP_EN",
            language_code="en-US",
            needs=[
                ContextNeed(
                    context_type="chapter_summaries",
                    query="AetherKey",
                    reason="continuity",
                )
            ],
        ),
        owner,
    )
    assert len(result["candidates"]) == 1
    candidate = result["candidates"][0]
    assert candidate["source_id"] == "CHP_EN"
    assert candidate["metadata"]["content_group_id"] == content_group_id
    assert candidate["metadata"]["localization_role"] == "translation"

    approve_context(
        "default",
        result["task_id"],
        [ContextApprovalItem(candidate_id=candidate["candidate_id"], approved=True)],
        owner,
    )
    current = build_evidence_pack(
        "default",
        result["task_id"],
        owner,
        token_budget(),
    )
    assert len(current["items"]) == 1

    conn = get_db()
    conn.execute(
        "UPDATE chapters SET content='AetherKey 修订后的中文源章节' "
        "WHERE chapter_id='CHP_ZH'"
    )
    ensure_chapter_localizations(conn, database_id="default")
    conn.commit()
    assert conn.execute(
        "SELECT translation_status FROM chapter_localizations "
        "WHERE chapter_id='CHP_EN'"
    ).fetchone()[0] == "stale"
    conn.close()

    stale = build_evidence_pack(
        "default",
        result["task_id"],
        owner,
        token_budget(),
    )
    assert stale["items"] == []
    assert stale["stale_candidate_ids"] == [candidate["candidate_id"]]

    conn = get_db()
    source = conn.execute(
        "SELECT title,content FROM chapters WHERE chapter_id='CHP_ZH'"
    ).fetchone()
    assert chapter_content_hash(source["title"], source["content"])
    conn.close()
    close_connection()
