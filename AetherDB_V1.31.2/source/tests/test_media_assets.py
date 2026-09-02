import hashlib
import io
import json
import sqlite3
import struct
import wave
from pathlib import Path

import services.database_registry as registry
import api.backup as backup_api
from app.dependencies.auth import ADMIN_API_KEY, USER_API_KEY
from main import app
from services.db import close_connection, get_db, init_db
from services.media_assets import (
    MediaAssetError,
    cleanup_media_assets,
    get_media_content,
    import_media_asset,
)
from tests.asgi_client import asgi_request


def setup_runtime(tmp_path, monkeypatch):
    root = tmp_path / "runtime"
    monkeypatch.setattr(registry, "REGISTRY_PATH", str(root / "registry.db"))
    monkeypatch.setattr(registry, "DATABASES_ROOT", str(root / "databases"))
    monkeypatch.setattr(registry, "OLD_DB_PATH", str(root / "missing.db"))
    registry.init_registry()
    init_db()
    return root


def png_bytes(width=2, height=3):
    # Signature and IHDR dimensions are sufficient for storage-layer validation.
    return b"\x89PNG\r\n\x1a\n" + struct.pack(">I", 13) + b"IHDR" + struct.pack(">II", width, height) + b"\x08\x06\x00\x00\x00"


def wav_bytes():
    stream = io.BytesIO()
    with wave.open(stream, "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(8_000)
        output.writeframes(b"\x00\x00" * 800)
    return stream.getvalue()


def mp4_container_bytes():
    # Minimal ISO BMFF ftyp box. Codec parsing belongs to the optional FFmpeg runtime.
    return b"\x00\x00\x00\x18ftypisom\x00\x00\x02\x00isomiso2"


def multipart(fields, filename, content_type, payload):
    boundary = "----aetherdb-media-test"
    chunks = []
    for name, value in fields.items():
        chunks.append(
            f"--{boundary}\r\nContent-Disposition: form-data; name=\"{name}\"\r\n\r\n{value}\r\n".encode()
        )
    chunks.append(
        (
            f"--{boundary}\r\n"
            f"Content-Disposition: form-data; name=\"file\"; filename=\"{filename}\"\r\n"
            f"Content-Type: {content_type}\r\n\r\n"
        ).encode()
    )
    chunks.extend([payload, f"\r\n--{boundary}--\r\n".encode()])
    return b"".join(chunks), f"multipart/form-data; boundary={boundary}"


def test_schema_and_content_addressed_deduplication(tmp_path, monkeypatch):
    root = setup_runtime(tmp_path, monkeypatch)
    payload = png_bytes()
    first = import_media_asset(
        "default",
        "default",
        stream=__import__("io").BytesIO(payload),
        filename="cover.png",
        declared_mime="image/png",
    )
    second = import_media_asset(
        "default",
        "default",
        stream=__import__("io").BytesIO(payload),
        filename="cover-copy.png",
        declared_mime="image/png",
    )

    assert first["asset_id"] != second["asset_id"]
    assert first["relative_path"] == second["relative_path"]
    assert not Path(first["relative_path"]).is_absolute()
    assert first["metadata"] == {"width": 2, "height": 3}
    object_path, _ = get_media_content("default", first["asset_id"])
    assert object_path.read_bytes() == payload
    assert object_path.is_relative_to(root / "databases" / "default" / "assets")

    db = get_db()
    tables = {
        row[0]
        for row in db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'media_%'"
        )
    }
    assert tables == {
        "media_assets",
        "media_asset_versions",
        "media_asset_derivatives",
        "media_annotations",
        "media_asset_bindings",
        "media_vector_records",
        "media_generation_tasks",
        "media_generation_events",
    }
    assert db.execute("PRAGMA foreign_key_check").fetchall() == []
    db.close()
    close_connection()


def test_upload_lifecycle_binding_range_and_soft_delete(tmp_path, monkeypatch):
    setup_runtime(tmp_path, monkeypatch)
    db = get_db()
    db.execute(
        "INSERT INTO chapters(chapter_id,book_id,title) VALUES ('CHP_MEDIA','default','Media')"
    )
    db.commit()
    db.close()
    payload = png_bytes(8, 9)
    body, content_type = multipart(
        {"database_id": "default", "book_id": "default", "source_type": "imported"},
        "cover.png",
        "image/png",
        payload,
    )

    assert asgi_request(
        app,
        "POST",
        "/api/media-assets",
        body=body,
        content_type=content_type,
    )[0] == 401
    status, created = asgi_request(
        app,
        "POST",
        "/api/media-assets",
        headers={"X-API-Key": USER_API_KEY},
        body=body,
        content_type=content_type,
    )
    assert status == 201
    asset_id = created["asset"]["asset_id"]
    assert created["asset"]["lifecycle_status"] == "temporary"

    status, blocked = asgi_request(
        app,
        "POST",
        f"/api/media-assets/{asset_id}/bindings",
        headers={"X-API-Key": USER_API_KEY},
        params={"database_id": "default"},
        json_body={
            "book_id": "default",
            "target_type": "chapter",
            "target_id": "CHP_MEDIA",
            "binding_type": "chapter_illustration",
        },
    )
    assert status == 409
    assert blocked["detail"]["code"] == "ASSET_NOT_APPROVED"

    status, approved = asgi_request(
        app,
        "POST",
        f"/api/media-assets/{asset_id}/approve",
        headers={"X-API-Key": USER_API_KEY},
        params={"database_id": "default"},
    )
    assert status == 200
    assert approved["asset"]["lifecycle_status"] == "approved"

    status, result = asgi_request(
        app,
        "POST",
        f"/api/media-assets/{asset_id}/bindings",
        headers={"X-API-Key": USER_API_KEY},
        params={"database_id": "default"},
        json_body={
            "book_id": "default",
            "target_type": "chapter",
            "target_id": "CHP_MEDIA",
            "binding_type": "chapter_illustration",
        },
    )
    assert status == 201
    binding_id = result["binding"]["binding_id"]

    status, listed = asgi_request(
        app,
        "GET",
        "/api/media-assets",
        headers={"X-API-Key": USER_API_KEY},
        params={
            "database_id": "default",
            "book_id": "default",
            "target_type": "chapter",
            "target_id": "CHP_MEDIA",
        },
    )
    assert status == 200
    assert [item["asset_id"] for item in listed["assets"]] == [asset_id]

    status, partial = asgi_request(
        app,
        "GET",
        f"/api/media-assets/{asset_id}/content",
        headers={"X-API-Key": USER_API_KEY, "Range": "bytes=0-7"},
        params={"database_id": "default"},
    )
    assert status == 206
    assert partial == payload[:8]

    assert asgi_request(
        app,
        "DELETE",
        f"/api/media-assets/{asset_id}",
        headers={"X-API-Key": USER_API_KEY},
        params={"database_id": "default"},
    )[0] == 409
    assert asgi_request(
        app,
        "DELETE",
        f"/api/media-assets/{asset_id}/bindings/{binding_id}",
        headers={"X-API-Key": USER_API_KEY},
        params={"database_id": "default"},
    )[0] == 204
    status, deleted = asgi_request(
        app,
        "DELETE",
        f"/api/media-assets/{asset_id}",
        headers={"X-API-Key": USER_API_KEY},
        params={"database_id": "default"},
    )
    assert status == 200
    assert deleted["asset"]["lifecycle_status"] == "soft_deleted"
    close_connection()


def test_rejects_spoofed_media_and_cross_book_or_missing_targets(tmp_path, monkeypatch):
    setup_runtime(tmp_path, monkeypatch)
    try:
        import_media_asset(
            "default",
            "default",
            stream=__import__("io").BytesIO(b"<script>alert(1)</script>"),
            filename="../../attack.png",
            declared_mime="image/png",
        )
        raise AssertionError("spoofed media should be rejected")
    except MediaAssetError as error:
        assert error.code == "UNSUPPORTED_MEDIA_TYPE"

    asset = import_media_asset(
        "default",
        "default",
        stream=__import__("io").BytesIO(png_bytes()),
        filename="valid.png",
        declared_mime="image/png",
    )
    asgi_request(
        app,
        "POST",
        f"/api/media-assets/{asset['asset_id']}/approve",
        headers={"X-API-Key": ADMIN_API_KEY},
        params={"database_id": "default"},
    )
    status, response = asgi_request(
        app,
        "POST",
        f"/api/media-assets/{asset['asset_id']}/bindings",
        headers={"X-API-Key": USER_API_KEY},
        params={"database_id": "default"},
        json_body={
            "book_id": "default",
            "target_type": "entity",
            "target_id": "MISSING_ENTITY",
            "binding_type": "depicts",
        },
    )
    assert status == 404
    assert response["detail"]["code"] == "BINDING_TARGET_NOT_FOUND"
    close_connection()


def test_audio_assets_work_without_any_audio_model(tmp_path, monkeypatch):
    setup_runtime(tmp_path, monkeypatch)
    payload = wav_bytes()
    asset = import_media_asset(
        "default",
        "default",
        stream=io.BytesIO(payload),
        filename="narration.wav",
        declared_mime="audio/wav",
    )
    assert asset["modality"] == "audio"
    assert asset["mime_type"] == "audio/wav"
    assert asset["metadata"] == {
        "duration_seconds": 0.1,
        "sample_rate": 8_000,
        "channels": 1,
    }
    path, _ = get_media_content("default", asset["asset_id"])
    assert path.read_bytes() == payload
    close_connection()


def test_video_assets_work_without_a_video_runtime(tmp_path, monkeypatch):
    setup_runtime(tmp_path, monkeypatch)
    payload = mp4_container_bytes()
    asset = import_media_asset(
        "default",
        "default",
        stream=io.BytesIO(payload),
        filename="reference.mp4",
        declared_mime="video/mp4",
    )

    assert asset["modality"] == "video"
    assert asset["mime_type"] == "video/mp4"
    assert asset["metadata"] == {}
    path, _ = get_media_content("default", asset["asset_id"])
    assert path.read_bytes() == payload
    close_connection()


def test_gc_preserves_shared_object_until_last_logical_reference(tmp_path, monkeypatch):
    setup_runtime(tmp_path, monkeypatch)
    payload = png_bytes()
    assets = [
        import_media_asset(
            "default",
            "default",
            stream=__import__("io").BytesIO(payload),
            filename=f"copy-{index}.png",
            declared_mime="image/png",
        )
        for index in range(2)
    ]
    path, _ = get_media_content("default", assets[0]["asset_id"])
    conn = get_db()
    conn.execute("UPDATE media_assets SET created_at=datetime('now','-8 days')")
    conn.commit()
    conn.close()

    # Keep the second logical record recent: the first row and its version are
    # removed, but their shared object remains referenced.
    conn = get_db()
    conn.execute(
        "UPDATE media_assets SET created_at=CURRENT_TIMESTAMP WHERE asset_id=?",
        (assets[1]["asset_id"],),
    )
    conn.commit()
    conn.close()
    result = cleanup_media_assets("default", retention_days=7)
    assert result["removed_assets"] == 1
    assert result["removed_objects"] == 0
    assert path.exists()

    conn = get_db()
    conn.execute(
        "UPDATE media_assets SET created_at=datetime('now','-8 days') WHERE asset_id=?",
        (assets[1]["asset_id"],),
    )
    conn.commit()
    conn.close()
    result = cleanup_media_assets("default", retention_days=7)
    assert result["removed_assets"] == 1
    assert result["removed_objects"] == 1
    assert not path.exists()
    close_connection()


def test_backup_is_scoped_to_registered_runtime_and_excludes_media_by_default(tmp_path, monkeypatch):
    root = setup_runtime(tmp_path, monkeypatch)
    backup_root = root / "backups"
    monkeypatch.setattr(backup_api, "BACKUP_DIR", str(backup_root))
    asset = import_media_asset(
        "default",
        "default",
        stream=__import__("io").BytesIO(png_bytes()),
        filename="private-cover.png",
        declared_mime="image/png",
    )

    meta = backup_api.create_data_backup("isolated", database_id="default")
    backup_path = backup_root / meta["name"]
    assert meta["database_id"] == "default"
    assert meta["media_object_count"] == 1
    assert meta["media_files_included"] is False
    assert not (backup_path / "media_files").exists()
    assert (backup_path / "database_snapshot.db").exists()
    manifest = json.loads((backup_path / "media_manifest.json").read_text(encoding="utf-8"))
    assert manifest[0]["content_hash"] == asset["content_hash"]

    with sqlite3.connect(backup_path / "database_snapshot.db") as snapshot:
        assert snapshot.execute("SELECT COUNT(*) FROM media_assets").fetchone()[0] == 1
        assert snapshot.execute("SELECT COUNT(*) FROM entities").fetchone()[0] == 0
        assert snapshot.execute("PRAGMA quick_check").fetchone()[0] == "ok"
    close_connection()


def test_full_media_backup_repairs_changed_object_on_restore(tmp_path, monkeypatch):
    root = setup_runtime(tmp_path, monkeypatch)
    backup_root = root / "backups"
    monkeypatch.setattr(backup_api, "BACKUP_DIR", str(backup_root))
    payload = png_bytes(11, 13)
    asset = import_media_asset(
        "default",
        "default",
        stream=io.BytesIO(payload),
        filename="restorable.png",
        declared_mime="image/png",
    )
    meta = backup_api.create_data_backup(
        "full media",
        database_id="default",
        include_media_files=True,
    )
    object_path, _ = get_media_content("default", asset["asset_id"])
    object_path.write_bytes(b"changed")

    status, restored = asgi_request(
        app,
        "POST",
        f"/api/backup/restore/{meta['name']}",
        headers={"X-API-Key": ADMIN_API_KEY},
    )
    assert status == 200
    assert restored["backup"]["media_files_included"] is True
    repaired_path, repaired_asset = get_media_content("default", asset["asset_id"])
    assert repaired_asset["content_hash"] == hashlib.sha256(payload).hexdigest()
    assert repaired_path.read_bytes() == payload
    close_connection()
