import io
import json
import struct
import wave

import pytest

import services.database_registry as registry
import services.media_vision as media_vision
from app.dependencies.auth import USER_API_KEY
from app.models import (
    ContextApprovalItem,
    ContextMapRequest,
    ContextNeed,
    MediaEvidenceBudget,
    TokenBudget,
)
from main import app
from services.audio_contract import (
    create_audio_task,
    register_audio_result,
    review_audio_result,
)
from services.context_engine import (
    approve_context,
    build_evidence_pack,
    create_context_map,
    owner_fingerprint,
)
from services.db import close_connection, get_db, init_db
from services.media_assets import (
    add_media_annotation,
    create_media_binding,
    import_media_asset,
    review_media_annotation,
    transition_media_asset,
)
from services.temporal import create_anchor, create_relation
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
        "INSERT INTO chapters(chapter_id,book_id,chapter_index,title,content) "
        "VALUES('CHP_RAG','default',1,'Current','current text')"
    )
    conn.execute(
        "INSERT INTO chapters(chapter_id,book_id,chapter_index,title,content) "
        "VALUES('CHP_OTHER','default',2,'Other','other text')"
    )
    conn.commit()
    conn.close()


def png_bytes(width=4, height=4):
    return (
        b"\x89PNG\r\n\x1a\n"
        + struct.pack(">I", 13)
        + b"IHDR"
        + struct.pack(">II", width, height)
        + b"\x08\x06\x00\x00\x00"
    )


def wav_bytes():
    stream = io.BytesIO()
    with wave.open(stream, "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(8_000)
        output.writeframes(b"\x00\x00" * 800)
    return stream.getvalue()


def create_asset(modality="image", *, chapter_id="CHP_RAG", caption=None, approved_annotation=True):
    if modality == "image":
        stream = io.BytesIO(png_bytes())
        filename = f"{chapter_id}.png"
        mime = "image/png"
    else:
        stream = io.BytesIO(wav_bytes())
        filename = f"{chapter_id}.wav"
        mime = "audio/wav"
    asset = import_media_asset(
        "default",
        "default",
        stream=stream,
        filename=filename,
        declared_mime=mime,
    )
    transition_media_asset("default", asset["asset_id"], "approve")
    binding = create_media_binding(
        "default",
        asset["asset_id"],
        {
            "book_id": "default",
            "target_type": "chapter",
            "target_id": chapter_id,
            "binding_type": "chapter_reference",
        },
    )
    annotation = None
    if caption is not None:
        annotation = add_media_annotation(
            "default",
            asset["asset_id"],
            {
                "annotation_type": "caption",
                "payload": {"caption": caption},
                "source_type": "model",
                "approval_status": "pending",
            },
        )
        if approved_annotation:
            annotation = review_media_annotation(
                "default",
                asset["asset_id"],
                annotation["annotation_id"],
                approved=True,
            )
    return asset, binding, annotation


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
                {
                    "asset_id": asset_id,
                    "score": 0.95 - index * 0.05,
                }
                for index, asset_id in enumerate(self.asset_ids)
            ],
            "channels": {
                "visual": {"used": True, "vector_space_id": "bge-vl-base-512-v1"},
                "caption": {
                    "used": True,
                    "vector_space_id": "bge-m3-media-caption-1024-v1",
                },
            },
            "degraded": False,
        }


def test_context_map_only_exposes_approved_bound_media_and_late_fusion(tmp_path, monkeypatch):
    setup_runtime(tmp_path, monkeypatch)
    current, _binding, approved = create_asset(
        caption="A crimson tower above the harbor",
    )
    create_asset(
        chapter_id="CHP_OTHER",
        caption="A crimson tower in another chapter",
    )
    _pending_asset, _pending_binding, pending = create_asset(
        caption="A pending crimson tower",
        approved_annotation=False,
    )
    fake = FakeMediaIndex([current["asset_id"]])
    monkeypatch.setattr(media_vision, "default_media_vision_index", lambda _database_id: fake)

    result = create_context_map(
        ContextMapRequest(
            task_id="media-context",
            task_type="world_consistency",
            database_id="default",
            book_id="default",
            chapter_id="CHP_RAG",
            needs=[
                ContextNeed(
                    context_type="media_assets",
                    query="crimson tower",
                    reason="visual evidence",
                    media_modalities=["image"],
                )
            ],
        ),
        owner_fingerprint("owner"),
    )
    assert len(result["candidates"]) == 1
    candidate = result["candidates"][0]
    assert candidate["source_id"] == approved["annotation_id"]
    assert candidate["modality"] == "image"
    assert candidate["metadata"]["asset_id"] == current["asset_id"]
    assert candidate["metadata"]["raw_media_included"] is False
    assert pending["annotation_id"] not in json.dumps(result)
    assert "relative_path" not in json.dumps(result)
    assert fake.calls[0]["target_type"] == "chapter"
    assert fake.calls[0]["target_id"] == "CHP_RAG"
    channels = result["profile"]["retrieval_channels"]["0:media_assets"]
    assert channels["visual_caption_vectors"]["fusion"] == "server_late_fusion"
    close_connection()


def test_media_budget_and_source_reapproval_are_enforced_at_evidence_time(tmp_path, monkeypatch):
    setup_runtime(tmp_path, monkeypatch)
    first, _binding, first_annotation = create_asset(caption="silver city gate")
    second, _binding, second_annotation = create_asset(caption="silver city wall")
    fake = FakeMediaIndex([first["asset_id"], second["asset_id"]])
    monkeypatch.setattr(media_vision, "default_media_vision_index", lambda _database_id: fake)
    owner = owner_fingerprint("owner")
    context_map = create_context_map(
        ContextMapRequest(
            task_id="media-budget",
            task_type="world_consistency",
            database_id="default",
            book_id="default",
            chapter_id="CHP_RAG",
            needs=[
                ContextNeed(
                    context_type="image_evidence",
                    query="silver city",
                    reason="setting",
                )
            ],
        ),
        owner,
    )
    approve_context(
        "default",
        "media-budget",
        [
            ContextApprovalItem(candidate_id=item["candidate_id"], approved=True)
            for item in context_map["candidates"]
        ],
        owner,
    )
    pack = build_evidence_pack(
        "default",
        "media-budget",
        owner,
        token_budget(),
        MediaEvidenceBudget(max_items=1, allowed_modalities=["image"]),
    )
    assert len(pack["items"]) == 1
    assert pack["used_media_items"] == 1
    assert pack["used_media_by_modality"] == {"image": 1}
    assert pack["raw_media_bytes"] == 0
    assert pack["items"][0]["media_reference"]["raw_media_included"] is False

    included_source = pack["items"][0]["source_id"]
    included_candidate = pack["items"][0]["candidate_id"]
    conn = get_db()
    original_metadata = conn.execute(
        "SELECT metadata_json FROM context_candidates WHERE candidate_id=?",
        (included_candidate,),
    ).fetchone()[0]
    conn.execute(
        "UPDATE context_candidates SET metadata_json=? WHERE candidate_id=?",
        (json.dumps({"asset_id": "asset-tampered"}), included_candidate),
    )
    conn.commit()
    conn.close()
    with pytest.raises(ValueError):
        build_evidence_pack(
            "default",
            "media-budget",
            owner,
            token_budget(),
            MediaEvidenceBudget(max_items=2, allowed_modalities=["image"]),
        )
    conn = get_db()
    conn.execute(
        "UPDATE context_candidates SET metadata_json=? WHERE candidate_id=?",
        (original_metadata, included_candidate),
    )
    conn.commit()
    conn.close()

    annotation = (
        first_annotation
        if first_annotation["annotation_id"] == included_source
        else second_annotation
    )
    asset = first if first_annotation["annotation_id"] == included_source else second
    review_media_annotation(
        "default",
        asset["asset_id"],
        annotation["annotation_id"],
        approved=False,
    )
    stale_pack = build_evidence_pack(
        "default",
        "media-budget",
        owner,
        token_budget(),
        MediaEvidenceBudget(max_items=2, allowed_modalities=["image"]),
    )
    assert included_source not in [item["source_id"] for item in stale_pack["items"]]
    assert stale_pack["stale_candidate_ids"]
    close_connection()


def test_only_approved_audio_transcript_enters_evidence_without_raw_audio(tmp_path, monkeypatch):
    setup_runtime(tmp_path, monkeypatch)
    asset, _binding, _annotation = create_asset(modality="audio")
    task = create_audio_task(
        {
            "database_id": "default",
            "book_id": "default",
            "operation": "audio.asr.transcribe",
            "source_asset_ids": [asset["asset_id"]],
        }
    )
    pending = register_audio_result(
        "default",
        task["task_id"],
        {
            "result_type": "transcript",
            "content_text": "The witness saw a blue comet.",
            "metadata": {"language": "en"},
        },
    )
    result_id = pending["results"][0]["result_id"]
    owner = owner_fingerprint("owner")
    before = create_context_map(
        ContextMapRequest(
            task_id="audio-before",
            task_type="world_consistency",
            database_id="default",
            book_id="default",
            chapter_id="CHP_RAG",
            needs=[
                ContextNeed(
                    context_type="audio_transcripts",
                    query="blue comet",
                    reason="witness",
                )
            ],
        ),
        owner,
    )
    assert before["candidates"] == []

    review_audio_result("default", result_id, approved=True)
    after = create_context_map(
        ContextMapRequest(
            task_id="audio-after",
            task_type="world_consistency",
            database_id="default",
            book_id="default",
            chapter_id="CHP_RAG",
            needs=[
                ContextNeed(
                    context_type="audio_transcripts",
                    query="blue comet",
                    reason="witness",
                )
            ],
        ),
        owner,
    )
    assert len(after["candidates"]) == 1
    candidate = after["candidates"][0]
    assert candidate["source_type"] == "audio_transcript"
    assert candidate["modality"] == "audio"
    approve_context(
        "default",
        "audio-after",
        [ContextApprovalItem(candidate_id=candidate["candidate_id"], approved=True)],
        owner,
    )
    pack = build_evidence_pack(
        "default",
        "audio-after",
        owner,
        token_budget(),
        MediaEvidenceBudget(max_items=2, allowed_modalities=["audio"]),
    )
    serialized = json.dumps(pack, ensure_ascii=False)
    assert "blue comet" in serialized
    assert "relative_path" not in serialized
    assert pack["raw_media_bytes"] == 0
    assert pack["items"][0]["media_reference"]["asset_id"] == asset["asset_id"]
    close_connection()


def test_future_bound_media_is_excluded_from_current_temporal_context(tmp_path, monkeypatch):
    setup_runtime(tmp_path, monkeypatch)

    def anchor(label):
        return create_anchor(
            {
                "database_id": "default",
                "book_id": "default",
                "timeline_id": None,
                "branch_id": None,
                "anchor_type": "order_only",
                "label": label,
                "chapter_id": None,
                "event_id": None,
                "phase_id": None,
                "absolute_time": None,
                "order_hint": None,
                "confidence": "confirmed",
            }
        )

    early = anchor("Early")
    future = anchor("Future")
    create_relation(
        {
            "database_id": "default",
            "book_id": "default",
            "timeline_id": early["timeline_id"],
            "branch_id": None,
            "source_anchor_id": early["id"],
            "relation_type": "before",
            "target_anchor_id": future["id"],
            "confidence": "confirmed",
            "source_chapter_id": None,
        }
    )
    visible, visible_binding, visible_annotation = create_asset(caption="temporal sigil")
    future_asset, future_binding, future_annotation = create_asset(caption="future temporal sigil")
    conn = get_db()
    conn.execute(
        "UPDATE media_asset_bindings SET timeline_id=?,valid_from_anchor_id=? WHERE binding_id=?",
        (early["timeline_id"], early["id"], visible_binding["binding_id"]),
    )
    conn.execute(
        "UPDATE media_asset_bindings SET timeline_id=?,valid_from_anchor_id=? WHERE binding_id=?",
        (early["timeline_id"], future["id"], future_binding["binding_id"]),
    )
    conn.commit()
    conn.close()
    fake = FakeMediaIndex([visible["asset_id"], future_asset["asset_id"]])
    monkeypatch.setattr(media_vision, "default_media_vision_index", lambda _database_id: fake)

    context_map = create_context_map(
        ContextMapRequest(
            task_id="media-temporal",
            task_type="world_consistency",
            database_id="default",
            book_id="default",
            chapter_id="CHP_RAG",
            timeline_id=early["timeline_id"],
            anchor_id=early["id"],
            needs=[
                ContextNeed(
                    context_type="image_evidence",
                    query="temporal sigil",
                    reason="timeline",
                )
            ],
        ),
        owner_fingerprint("owner"),
    )
    source_ids = {item["source_id"] for item in context_map["candidates"]}
    assert visible_annotation["annotation_id"] in source_ids
    assert future_annotation["annotation_id"] not in source_ids

    other_asset, _other_binding, other_annotation = create_asset(
        chapter_id="CHP_OTHER",
        caption="future chapter sigil",
    )
    monkeypatch.setattr(
        media_vision,
        "default_media_vision_index",
        lambda _database_id: FakeMediaIndex([other_asset["asset_id"]]),
    )
    future_chapter = create_context_map(
        ContextMapRequest(
            task_id="future-chapter-media",
            task_type="world_consistency",
            database_id="default",
            book_id="default",
            chapter_id="CHP_RAG",
            timeline_id=early["timeline_id"],
            anchor_id=early["id"],
            needs=[
                ContextNeed(
                    context_type="image_evidence",
                    query="future chapter sigil",
                    reason="future chapter",
                    target_type="chapter",
                    target_id="CHP_OTHER",
                )
            ],
        ),
        owner_fingerprint("owner"),
    )
    assert future_chapter["candidates"] == []
    assert other_annotation["annotation_id"] not in json.dumps(future_chapter)

    event_asset, event_binding, event_annotation = create_asset(caption="future event sigil")
    conn = get_db()
    conn.execute(
        "INSERT INTO timeline_events(id,book_id,title,description) "
        "VALUES(42,'default','Future event','future')"
    )
    conn.execute(
        "UPDATE temporal_anchors SET event_id='42' WHERE id=?",
        (future["id"],),
    )
    conn.execute(
        "UPDATE media_asset_bindings SET target_type='event',target_id='42',"
        "timeline_id=NULL,valid_from_anchor_id=NULL WHERE binding_id=?",
        (event_binding["binding_id"],),
    )
    conn.commit()
    conn.close()
    monkeypatch.setattr(
        media_vision,
        "default_media_vision_index",
        lambda _database_id: FakeMediaIndex([event_asset["asset_id"]]),
    )
    future_event = create_context_map(
        ContextMapRequest(
            task_id="future-event-media",
            task_type="world_consistency",
            database_id="default",
            book_id="default",
            chapter_id="CHP_RAG",
            timeline_id=early["timeline_id"],
            anchor_id=early["id"],
            needs=[
                ContextNeed(
                    context_type="image_evidence",
                    query="future event sigil",
                    reason="future event",
                    target_type="event",
                    target_id="42",
                )
            ],
        ),
        owner_fingerprint("owner"),
    )
    assert future_event["candidates"] == []
    assert event_annotation["annotation_id"] not in json.dumps(future_event)
    close_connection()


def test_model_annotation_review_route_is_authenticated_and_text_safe(tmp_path, monkeypatch):
    setup_runtime(tmp_path, monkeypatch)
    asset, _binding, annotation = create_asset(
        caption="private model caption",
        approved_annotation=False,
    )
    path = (
        f"/api/media-assets/{asset['asset_id']}/annotations/"
        f"{annotation['annotation_id']}/review"
    )
    assert asgi_request(
        app,
        "POST",
        path,
        params={"database_id": "default"},
        json_body={"approved": True},
    )[0] == 401
    status, body = asgi_request(
        app,
        "POST",
        path,
        headers={"X-API-Key": USER_API_KEY},
        params={"database_id": "default"},
        json_body={"approved": True},
    )
    assert status == 200
    assert body["annotation"]["approval_status"] == "approved"
    conn = get_db()
    audit = json.dumps(
        [dict(row) for row in conn.execute("SELECT * FROM audit_log").fetchall()],
        ensure_ascii=False,
    )
    assert "media_asset.annotation_review" in audit
    assert "private model caption" not in audit
    conn.close()
    close_connection()
