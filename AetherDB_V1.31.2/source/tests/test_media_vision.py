import io
import json
import math
import struct
from pathlib import Path

import pytest
import sqlite_vec

import api.media_vision as media_vision_api
import services.database_registry as registry
import services.media_vision as media_vision_service
from app.dependencies.auth import ADMIN_API_KEY, USER_API_KEY
from main import app
from services.db import close_connection, get_db, init_db
from services.embedding import MockEmbeddingProvider
from services.media_assets import (
    add_media_annotation,
    cleanup_media_assets,
    import_media_asset,
    transition_media_asset,
)
from services.media_vision import (
    MediaVisionError,
    MediaVisionIndex,
    VISUAL_VECTOR_SPACE,
)
from services.model_packages.manifest import load_package_manifest
from services.model_runtime.scheduler import ResourceScheduler
from services.model_runtime.worker_process import BgeVLClipWorkerAdapter
from tests.asgi_client import asgi_request


def setup_runtime(tmp_path, monkeypatch):
    root = tmp_path / "runtime"
    monkeypatch.setattr(registry, "REGISTRY_PATH", str(root / "registry.db"))
    monkeypatch.setattr(registry, "DATABASES_ROOT", str(root / "databases"))
    monkeypatch.setattr(registry, "OLD_DB_PATH", str(root / "missing.db"))
    registry.init_registry()
    init_db()
    return root


def png_bytes(width: int, height: int) -> bytes:
    return (
        b"\x89PNG\r\n\x1a\n"
        + struct.pack(">I", 13)
        + b"IHDR"
        + struct.pack(">II", width, height)
        + b"\x08\x06\x00\x00\x00"
    )


def unit_vector(index: int, dimensions: int) -> list[float]:
    vector = [0.0] * dimensions
    vector[index] = 1.0
    return vector


class FakeVisionProvider:
    is_aetherdb_local = True

    def __init__(self):
        self.by_hash = {}
        self.image_calls = 0
        self.text_calls = 0

    @staticmethod
    def status():
        return {
            "available": True,
            "model_id": "BAAI/BGE-VL-base",
            "revision": "test-revision",
            "dimensions": 512,
            "vector_space_id": VISUAL_VECTOR_SPACE,
            "remote_code": False,
        }

    def embed_image(self, path, content_hash, *, requested_backend="auto"):
        self.image_calls += 1
        if content_hash not in self.by_hash:
            self.by_hash[content_hash] = unit_vector(len(self.by_hash), 512)
        return self.by_hash[content_hash]

    def embed_text(self, text, *, requested_backend="auto"):
        self.text_calls += 1
        return unit_vector(0 if "red" in text.lower() or "红" in text else 1, 512)


def create_asset(database_id: str, width: int, caption: str) -> dict:
    asset = import_media_asset(
        database_id,
        "default",
        io.BytesIO(png_bytes(width, 3)),
        filename=f"image-{width}.png",
        declared_mime="image/png",
    )
    transition_media_asset(database_id, asset["asset_id"], "approve")
    add_media_annotation(
        database_id,
        asset["asset_id"],
        {
            "annotation_type": "caption",
            "payload": {"text": caption},
            "source_type": "manual",
            "approval_status": "approved",
        },
    )
    return asset


def open_vec_conn(path):
    import sqlite3

    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.enable_load_extension(True)
    sqlite_vec.load(conn)
    return conn


def test_dual_space_index_and_multilingual_text_and_image_search(tmp_path, monkeypatch):
    setup_runtime(tmp_path, monkeypatch)
    first = create_asset("default", 2, "夜空中的红塔")
    second = create_asset("default", 4, "海边的蓝色房屋")
    caption_provider = MockEmbeddingProvider(1024)
    vision_provider = FakeVisionProvider()
    index = MediaVisionIndex(
        "default",
        vision_provider=vision_provider,
        caption_provider=caption_provider,
    )

    first_result = index.index_asset(first["asset_id"], requested_backend="rocm_pytorch")
    second_result = index.index_asset(second["asset_id"], requested_backend="cuda")
    assert first_result["visual"]["dimensions"] == 512
    assert first_result["caption"]["dimensions"] == 1024
    assert first_result["caption"]["indexed"] is True
    assert second_result["visual"]["indexed"] is True

    text_result = index.search_text(
        book_id="default",
        query="夜空中的红塔",
        top_k=10,
    )
    assert text_result["results"][0]["asset_id"] == first["asset_id"]
    assert text_result["channels"]["caption"]["language_scope"] == "multilingual"
    assert text_result["query_persisted"] is False
    assert set(text_result["results"][0]["channels"]) == {"visual", "caption"}
    assert '"vectors"' not in json.dumps(text_result, ensure_ascii=False).lower()

    image_result = index.search_image(
        book_id="default",
        query_asset_id=first["asset_id"],
        top_k=10,
    )
    assert [item["asset_id"] for item in image_result["results"]] == [
        second["asset_id"]
    ]

    conn = open_vec_conn(index.db_path)
    try:
        records = [
            dict(row)
            for row in conn.execute(
                "SELECT * FROM media_vector_records ORDER BY vector_id"
            )
        ]
        assert len(records) == 4
        serialized = json.dumps(records, ensure_ascii=False)
        assert "夜空中的红塔" not in serialized
        assert "海边的蓝色房屋" not in serialized
        assert conn.execute(
            "SELECT COUNT(*) FROM media_visual_vectors_vec"
        ).fetchone()[0] == 2
        assert conn.execute(
            "SELECT COUNT(*) FROM media_caption_vectors_vec"
        ).fetchone()[0] == 2
    finally:
        conn.close()
        close_connection()


def test_only_approved_captions_enter_local_bge_m3_channel(tmp_path, monkeypatch):
    setup_runtime(tmp_path, monkeypatch)
    asset = import_media_asset(
        "default",
        "default",
        io.BytesIO(png_bytes(7, 9)),
        filename="pending.png",
        declared_mime="image/png",
    )
    add_media_annotation(
        "default",
        asset["asset_id"],
        {
            "annotation_type": "caption",
            "payload": {"text": "unapproved private description"},
            "source_type": "model",
            "approval_status": "pending",
        },
    )
    index = MediaVisionIndex(
        "default",
        vision_provider=FakeVisionProvider(),
        caption_provider=MockEmbeddingProvider(1024),
    )
    result = index.index_asset(asset["asset_id"])
    assert result["caption"]["indexed"] is False
    assert result["caption"]["reason"] == "no_approved_caption"
    status = index.status(book_id="default")
    assert status["counts"] == {"visual": 1, "caption": 0}
    assert status["caption_runtime"]["external_embedding_allowed"] is False
    close_connection()


def test_retention_cleanup_removes_virtual_vectors_before_metadata_cascade(
    tmp_path,
    monkeypatch,
):
    setup_runtime(tmp_path, monkeypatch)
    asset = import_media_asset(
        "default",
        "default",
        io.BytesIO(png_bytes(12, 13)),
        filename="temporary.png",
        declared_mime="image/png",
    )
    index = MediaVisionIndex(
        "default",
        vision_provider=FakeVisionProvider(),
        caption_provider=MockEmbeddingProvider(1024),
    )
    index.index_asset(asset["asset_id"])
    conn = get_db()
    conn.execute(
        "UPDATE media_assets SET created_at=datetime('now','-8 days') WHERE asset_id=?",
        (asset["asset_id"],),
    )
    conn.commit()
    conn.close()

    result = cleanup_media_assets("default", retention_days=7)
    assert result["removed_assets"] == 1
    conn = open_vec_conn(index.db_path)
    try:
        assert conn.execute("SELECT COUNT(*) FROM media_vector_records").fetchone()[0] == 0
        assert conn.execute(
            "SELECT COUNT(*) FROM media_visual_vectors_vec"
        ).fetchone()[0] == 0
    finally:
        conn.close()
        close_connection()


def test_media_vision_api_requires_auth_and_never_returns_vectors(
    tmp_path,
    monkeypatch,
):
    setup_runtime(tmp_path, monkeypatch)

    class StubIndex:
        def status(self, *, book_id=None):
            return {
                "counts": {"visual": 0, "caption": 0},
                "vector_spaces": {
                    "visual": {"dimensions": 512},
                    "caption": {"dimensions": 1024},
                },
            }

    monkeypatch.setattr(
        media_vision_api,
        "default_media_vision_index",
        lambda _database_id: StubIndex(),
    )
    assert asgi_request(
        app,
        "GET",
        "/api/media-vision/status",
        params={"database_id": "default"},
    )[0] == 401
    status, payload = asgi_request(
        app,
        "GET",
        "/api/media-vision/status",
        headers={"X-API-Key": USER_API_KEY},
        params={"database_id": "default"},
    )
    assert status == 200
    assert "embedding" not in json.dumps(payload).lower()
    close_connection()


def test_bge_vl_package_and_worker_freeze_safe_runtime_boundary():
    manifest = load_package_manifest(
        Path(__file__).resolve().parents[1]
        / "resources"
        / "model_packages"
        / "aetherdb-bge-vl-base.json"
    )
    assert manifest.package_id == "aetherdb.bge-vl-base"
    assert manifest.embedding.dimension == 512
    assert manifest.source.revision == "cc4c733ed997dbee4ac70ccffb911e70c9c24b93"
    assert "rocm_pytorch" in manifest.supported_backends
    assert all(not item.path.endswith(".py") for item in manifest.files)
    assert sum(item.size for item in manifest.files) == 303_203_348

    adapter = BgeVLClipWorkerAdapter(Path("."))
    capabilities = adapter.capabilities()
    assert capabilities["remote_code"] is False
    assert capabilities["vector_dimension"] == 512
    assert ResourceScheduler._device_supports_backend(
        "rocm_migraphx",
        "rocm_pytorch",
    )
    assert math.isclose(sum(value * value for value in unit_vector(0, 512)), 1.0)


def test_versioned_visual_migration_switch_rollback_and_reload_consistency(
    tmp_path,
    monkeypatch,
):
    setup_runtime(tmp_path, monkeypatch)
    first = create_asset("default", 21, "red tower")
    second = create_asset("default", 22, "blue house")
    provider = FakeVisionProvider()
    index = MediaVisionIndex(
        "default",
        vision_provider=provider,
        caption_provider=MockEmbeddingProvider(1024),
    )
    index.index_asset(first["asset_id"])
    index.index_asset(second["asset_id"])
    old_space_id = index.active_visual_space_id()
    conn = open_vec_conn(index.db_path)
    try:
        source_before = conn.execute(
            """SELECT asset_id,content_hash,lifecycle_status
                 FROM media_assets ORDER BY asset_id"""
        ).fetchall()
        old_count = conn.execute(
            """SELECT COUNT(*) FROM media_vector_records
                WHERE channel='visual' AND vector_space_id=?""",
            (old_space_id,),
        ).fetchone()[0]
    finally:
        conn.close()

    target = index.create_visual_space()
    assert target["image_preprocess_version"]
    assert target["query_template_version"] == "clip-text-query-v1"
    assert target["pooling"] == "clip-projected-pooled-v1"
    assert target["precision"] == "float32"
    task = index.create_migration_task(target["space_id"], start=False)
    result = index.run_migration_task(task["task_id"])
    assert result["status"] == "completed"
    assert result["successful_items"] == 2
    assert "source_hash" not in json.dumps(result)
    assert index.active_visual_space_id() == old_space_id

    validation = index.validate_visual_space(target["space_id"])
    assert validation["valid"] is True
    activated = index.activate_visual_space(target["space_id"])
    assert activated["active_space_id"] == target["space_id"]
    assert activated["rollback_space_id"] == old_space_id

    reloaded_provider = FakeVisionProvider()
    reloaded = MediaVisionIndex(
        "default",
        vision_provider=reloaded_provider,
        caption_provider=MockEmbeddingProvider(1024),
    )
    image_results = reloaded.search_image(
        book_id="default",
        query_asset_id=first["asset_id"],
    )
    assert image_results["results"][0]["asset_id"] == second["asset_id"]
    assert reloaded_provider.image_calls == 0

    calls_before_rollback = provider.image_calls
    rolled_back = index.rollback_visual_space()
    assert rolled_back["active_space_id"] == old_space_id
    assert rolled_back["rollback_space_id"] == target["space_id"]
    assert provider.image_calls == calls_before_rollback
    conn = open_vec_conn(index.db_path)
    try:
        assert conn.execute(
            """SELECT COUNT(*) FROM media_vector_records
                WHERE channel='visual' AND vector_space_id=?""",
            (old_space_id,),
        ).fetchone()[0] == old_count
        assert conn.execute(
            """SELECT COUNT(*) FROM media_vector_records
                WHERE channel='visual' AND vector_space_id=?""",
            (target["space_id"],),
        ).fetchone()[0] == 2
        assert conn.execute(
            """SELECT asset_id,content_hash,lifecycle_status
                 FROM media_assets ORDER BY asset_id"""
        ).fetchall() == source_before
    finally:
        conn.close()
        close_connection()


def test_visual_source_revision_change_fails_validation_without_pointer_switch(
    tmp_path,
    monkeypatch,
):
    setup_runtime(tmp_path, monkeypatch)
    asset = create_asset("default", 31, "revision fixture")
    index = MediaVisionIndex(
        "default",
        vision_provider=FakeVisionProvider(),
        caption_provider=MockEmbeddingProvider(1024),
    )
    index.index_asset(asset["asset_id"])
    old_space_id = index.active_visual_space_id()
    target = index.create_visual_space()
    task = index.create_migration_task(target["space_id"], start=False)
    assert index.run_migration_task(task["task_id"])["status"] == "completed"

    conn = get_db("default")
    conn.execute(
        "UPDATE media_assets SET lifecycle_status='archived' WHERE asset_id=?",
        (asset["asset_id"],),
    )
    conn.commit()
    conn.close()
    validation = index.validate_visual_space(target["space_id"])
    assert validation["valid"] is False
    assert validation["status"] == "failed"
    assert validation["failure_code"] == "SOURCE_REVISION_CHANGED"
    assert validation["stale"] == 1
    assert index.active_visual_space_id() == old_space_id
    close_connection()


def test_visual_gc_rejects_task_and_pointer_references(tmp_path, monkeypatch):
    setup_runtime(tmp_path, monkeypatch)
    create_asset("default", 41, "gc fixture")
    index = MediaVisionIndex(
        "default",
        vision_provider=FakeVisionProvider(),
        caption_provider=MockEmbeddingProvider(1024),
    )
    failed = index.create_visual_space()
    task = index.create_migration_task(failed["space_id"], start=False)
    index.mark_visual_space_failed(failed["space_id"], "FIXTURE_FAILURE")
    with pytest.raises(MediaVisionError) as task_ref:
        index.garbage_collect_visual_space(
            failed["space_id"],
            confirm_space_id=failed["space_id"],
        )
    assert task_ref.value.code == "VISUAL_SPACE_TASK_REFERENCE"
    index.cancel_migration_task(task["task_id"])

    with pytest.raises(MediaVisionError) as mismatch:
        index.garbage_collect_visual_space(
            failed["space_id"],
            confirm_space_id="wrong-space",
        )
    assert mismatch.value.code == "VISUAL_SPACE_GC_CONFIRMATION_MISMATCH"
    assert index.garbage_collect_visual_space(
        failed["space_id"],
        confirm_space_id=failed["space_id"],
    )["deleted"] is True
    active_id = index.active_visual_space_id()
    with pytest.raises(MediaVisionError) as protected:
        index.garbage_collect_visual_space(
            active_id,
            confirm_space_id=active_id,
        )
    assert protected.value.code == "VISUAL_SPACE_PROTECTED"
    close_connection()


def test_visual_space_management_api_rejects_untrusted_paths(tmp_path, monkeypatch):
    setup_runtime(tmp_path, monkeypatch)
    status, _ = asgi_request(
        app,
        "POST",
        "/api/media-vision/spaces",
        json_body={"database_id": "default", "requested_backend": "auto"},
    )
    assert status == 401
    status, payload = asgi_request(
        app,
        "POST",
        "/api/media-vision/spaces",
        headers={"X-API-Key": ADMIN_API_KEY},
        json_body={
            "database_id": "default",
            "requested_backend": "auto",
            "path": "C:/private/image.png",
        },
    )
    assert status == 422
    assert payload["detail"][0]["type"] == "extra_forbidden"
    close_connection()


def test_visual_migration_restart_recovery_requeues_only_persisted_work(
    tmp_path,
    monkeypatch,
):
    setup_runtime(tmp_path, monkeypatch)
    create_asset("default", 51, "restart fixture")
    index = MediaVisionIndex(
        "default",
        vision_provider=FakeVisionProvider(),
        caption_provider=MockEmbeddingProvider(1024),
    )
    target = index.create_visual_space()
    task = index.create_migration_task(target["space_id"], start=False)
    conn = open_vec_conn(index.db_path)
    try:
        conn.execute(
            "UPDATE media_vision_migration_tasks SET status='running' WHERE task_id=?",
            (task["task_id"],),
        )
        conn.execute(
            "UPDATE media_vision_migration_items SET status='running' WHERE task_id=?",
            (task["task_id"],),
        )
        conn.commit()
    finally:
        conn.close()
    submitted = []
    monkeypatch.setattr(
        media_vision_service,
        "_submit_visual_migration",
        lambda database_id, task_id: submitted.append((database_id, task_id)),
    )

    recovered = media_vision_service.recover_interrupted_visual_migrations()

    assert recovered == {"recovered": 1, "queued": 1}
    assert submitted == [("default", task["task_id"])]
    restored = index.get_migration_task(task["task_id"])
    assert restored["status"] == "queued"
    assert {item["status"] for item in restored["items"]} == {"queued"}
    close_connection()
