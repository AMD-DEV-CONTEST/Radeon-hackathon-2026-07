"""Tests for Find it.

Some tests exercise a real MPEG-TS sample. Point the test harness at one by
setting the SAMPLE_TS environment variable, e.g.:

    SAMPLE_TS=/path/to/sample.ts pytest -q

If SAMPLE_TS is not set or the file does not exist, those tests are skipped.
"""

import os
import sqlite3
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import main

SAMPLE_TS = Path(os.environ.get("SAMPLE_TS", ""))

client = TestClient(main.app)

needs_sample = pytest.mark.skipif(
    not SAMPLE_TS.exists(), reason="set SAMPLE_TS env var to a real MPEG-TS/MP4 file"
)


# --------------------------------------------------------------------------- #
# Pure unit tests (no I/O)
# --------------------------------------------------------------------------- #

def test_ts_extension_is_allowed():
    assert ".ts" in main.ALLOWED_EXTENSIONS
    assert ".mts" in main.ALLOWED_EXTENSIONS
    assert ".m2ts" in main.ALLOWED_EXTENSIONS


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("25/1", 25.0),
        ("30000/1001", 29.97),
        ("0/0", None),
        ("N/A", None),
        ("30", 30.0),
        (None, None),
    ],
)
def test_fraction_to_float(raw, expected):
    assert main._fraction_to_float(raw) == expected


def test_ts_mime_type_registered():
    import mimetypes

    assert mimetypes.guess_type("x.ts")[0] == "video/mp2t"


def _jpeg_size(data: bytes) -> tuple[int, int]:
    """Return (width, height) of a JPEG by scanning for a SOF marker."""
    import struct

    i = 2  # skip SOI
    while i < len(data):
        if data[i] != 0xFF:
            i += 1
            continue
        marker = data[i + 1]
        if marker in (0xC0, 0xC1, 0xC2):  # SOF0/1/2
            h, w = struct.unpack(">HH", data[i + 5 : i + 9])
            return w, h
        length = struct.unpack(">H", data[i + 2 : i + 4])[0]
        i += 2 + length
    raise AssertionError("no SOF marker found in JPEG")


def test_transform_filter_mapping():
    assert main._transform_filter(0, False) == "null"
    assert main._transform_filter(90, False) == "transpose=1"
    assert main._transform_filter(180, False) == "transpose=1,transpose=1"
    assert main._transform_filter(270, False) == "transpose=2"
    assert main._transform_filter(-90, False) == "transpose=2"      # normalised
    assert main._transform_filter(90, True) == "hflip,transpose=1"  # mirror first
    assert main._transform_filter(0, True) == "hflip"


# --------------------------------------------------------------------------- #
# probe_video() directly against the real file
# --------------------------------------------------------------------------- #

@needs_sample
def test_probe_video_on_real_ts():
    props = main.probe_video(SAMPLE_TS)
    assert props["fps"] == 25.0
    assert props["has_audio"] is True
    assert props["width"] == 1920
    assert props["height"] == 1080
    assert props["container"] == "mpegts"
    assert props["duration"] and props["duration"] > 0
    assert props["size_bytes"] == SAMPLE_TS.stat().st_size


@needs_sample
def test_make_preview_frame_no_transcode_of_source(tmp_path):
    # A single video frame (no audio) is emitted as JPEG...
    size_before = SAMPLE_TS.stat().st_size
    img = main.make_preview_image(SAMPLE_TS, rotation=0, mirror=False, ts=1.0)
    assert img[:2] == b"\xff\xd8"  # JPEG SOI magic
    assert _jpeg_size(img) == (1920, 1080)
    # ...and the source file is left byte-for-byte untouched.
    assert SAMPLE_TS.stat().st_size == size_before


@needs_sample
def test_make_preview_rotation_swaps_dimensions():
    # 90/270 rotate a 1920x1080 frame into 1080x1920; mirror does not.
    assert _jpeg_size(main.make_preview_image(SAMPLE_TS, 90, False)) == (1080, 1920)
    assert _jpeg_size(main.make_preview_image(SAMPLE_TS, 270, False)) == (1080, 1920)
    assert _jpeg_size(main.make_preview_image(SAMPLE_TS, 180, False)) == (1920, 1080)
    assert _jpeg_size(main.make_preview_image(SAMPLE_TS, 0, True)) == (1920, 1080)


# --------------------------------------------------------------------------- #
# HTTP API end-to-end against the real file (isolated upload dir + db)
# --------------------------------------------------------------------------- #

@needs_sample
def test_api_full_lifecycle_with_ts(tmp_path, monkeypatch):
    # Point uploads + db at a throwaway temp dir so we don't touch real state.
    up = tmp_path / "uploads"
    up.mkdir()
    monkeypatch.setattr(main, "UPLOAD_DIR", up)
    monkeypatch.setattr(main, "DB_PATH", tmp_path / "videos.db")
    main.init_db()

    # 1) /probe (no store)
    with SAMPLE_TS.open("rb") as fh:
        r = client.post("/probe", files={"file": (SAMPLE_TS.name, fh)})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["fps"] == 25.0 and body["has_audio"] is True

    # 2) upload — the raw file is transcoded to MP4 asynchronously on the backend
    with SAMPLE_TS.open("rb") as fh:
        r = client.post(
            "/videos",
            files={"file": (SAMPLE_TS.name, fh)},
            data={"location": "living-room", "name": "ts-test"},
        )
    assert r.status_code == 201, r.text
    vid = r.json()["id"]
    assert r.json()["status"] == "queued"

    # Process transcode synchronously so the .mp4 exists for downstream checks
    import asyncio
    asyncio.run(main._process_transcode_job(vid, 0, False, True))

    # stored file is now .mp4 (transcoded)
    stored = list(up.glob(f"{vid}.*"))
    assert stored and stored[0].suffix == ".mp4"

    # 3) retrieve metadata
    r = client.get(f"/videos/{vid}")
    assert r.status_code == 200
    meta = r.json()
    assert meta["location"] == "living-room"
    assert meta["fps"] == 25.0 and meta["has_audio"] is True
    # container is now mp4 because we transcoded
    assert meta["container"] == "mov,mp4,m4a,3gp,3g2,mj2"

    # 4) stream back with the right content-type (now MP4)
    r = client.get(f"/media/{vid}")
    assert r.status_code == 200
    assert r.headers["content-type"] == "video/mp4"
    # File is transcoded so size may differ from source — just check it's non-empty
    assert len(r.content) > 1000

    # 5) it shows up in the list + locations
    assert any(v["id"] == vid for v in client.get("/videos").json())
    assert "living-room" in client.get("/locations").json()

    # 6) delete removes db row AND file
    assert client.delete(f"/videos/{vid}").status_code == 204
    assert client.get(f"/videos/{vid}").status_code == 404
    assert not list(up.glob(f"{vid}.*"))


@needs_sample
def test_stage_preview_and_rotation_metadata(tmp_path, monkeypatch):
    up = tmp_path / "uploads"
    up.mkdir()
    staging = up / "_staging"
    staging.mkdir()
    monkeypatch.setattr(main, "UPLOAD_DIR", up)
    monkeypatch.setattr(main, "STAGING_DIR", staging)
    monkeypatch.setattr(main, "DB_PATH", tmp_path / "videos.db")
    main.init_db()

    # 1) stage the selected file -> stage_id + probe props
    with SAMPLE_TS.open("rb") as fh:
        r = client.post("/stage", files={"file": (SAMPLE_TS.name, fh)})
    assert r.status_code == 201, r.text
    stage_id = r.json()["stage_id"]
    assert r.json()["fps"] == 25.0

    # 2) ffmpeg-rendered preview updates with rotation (dims swap at 90°)
    r0 = client.get(f"/stage/{stage_id}/preview", params={"rotation": 0, "mirror": 0})
    assert r0.status_code == 200 and r0.headers["content-type"] == "image/jpeg"
    assert _jpeg_size(r0.content) == (1920, 1080)
    r90 = client.get(f"/stage/{stage_id}/preview", params={"rotation": 90, "mirror": 0})
    assert _jpeg_size(r90.content) == (1080, 1920)

    # 3) upload with rotation/mirror — now baked into the transcoded MP4 pixels
    with SAMPLE_TS.open("rb") as fh:
        r = client.post(
            "/videos",
            files={"file": (SAMPLE_TS.name, fh)},
            data={"location": "studio", "rotation": "90", "mirror": "1",
                  "stage_id": stage_id},
        )
    assert r.status_code == 201, r.text
    vid = r.json()["id"]
    # Upload response still shows original params (transcode hasn't run yet)
    assert r.json()["rotation"] == 90 and r.json()["mirror"] is True
    assert not list(staging.glob(f"{stage_id}.*")), "staged file should be removed"

    # Process transcode synchronously so transforms are baked into the MP4 pixels.
    import asyncio
    asyncio.run(main._process_transcode_job(vid, 90, True, True))

    # 4) stored metadata reflects baked-in transforms (identity)
    meta = client.get(f"/videos/{vid}").json()
    assert meta["rotation"] == 0 and meta["mirror"] is False

    # 5) the file on disk is a transcoded MP4, NOT byte-identical to source
    stored = up / meta["stored_name"]
    assert stored.suffix == ".mp4"
    assert stored.stat().st_size > 1000
    # The transform is baked into pixels, so the stored preview (default identity)
    # should show the rotated+mirrored result (1080x1920)
    rprev = client.get(f"/videos/{vid}/preview")
    assert _jpeg_size(rprev.content) == (1080, 1920)
    # explicit override back to identity still works
    rover = client.get(f"/videos/{vid}/preview", params={"rotation": 0, "mirror": 0})
    assert _jpeg_size(rover.content) == (1080, 1920)


@needs_sample
def test_rejects_non_video_extension(tmp_path, monkeypatch):
    monkeypatch.setattr(main, "DB_PATH", tmp_path / "videos.db")
    main.init_db()
    r = client.post(
        "/probe", files={"file": ("notes.txt", b"hello", "text/plain")}
    )
    assert r.status_code == 415


# --------------------------------------------------------------------------- #
# Transcription import / search tests (no ffmpeg / sample file needed)
# --------------------------------------------------------------------------- #

def _insert_test_video(db_path: Path, video_id: str, **overrides) -> None:
    """Insert a minimal videos row directly into SQLite."""
    defaults = {
        "id": video_id,
        "stored_name": f"{video_id}.mp4",
        "orig_name": "test.mp4",
        "name": "test video",
        "location": "test-room",
        "record_time": "2024-01-01T00:00:00+00:00",
        "upload_time": "2024-01-01T00:00:00+00:00",
        "rotation": 0,
        "mirror": 0,
        "fps": 30.0,
        "has_audio": 1,
        "duration": 10.0,
        "width": 1920,
        "height": 1080,
        "container": "mov,mp4,m4a",
        "size_bytes": 12345,
        "status": "transcoded",
        "transcription_status": "untranscribed",
        "transcription_progress": None,
        "transcode_progress": None,
        "transcode_error": None,
    }
    defaults.update(overrides)
    cols = ", ".join(defaults.keys())
    placeholders = ", ".join("?" * len(defaults))
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute(f"INSERT INTO videos ({cols}) VALUES ({placeholders})", tuple(defaults.values()))
    conn.commit()
    conn.close()


def _sample_payload():
    return {
        "frame_descriptions": [
            {"timestamp": 1.0, "description": "a cat sits on a desk"},
            {"timestamp": 2.0, "description": "a dog runs in the park"},
        ],
        "transcriptions": [
            {"index": 1, "start_seconds": 0.0, "end_seconds": 3.0, "text": "hello world"},
            {"index": 2, "start_seconds": 4.0, "end_seconds": 6.0, "text": "the cat says hello"},
        ],
    }


def test_import_transcriptions(tmp_path, monkeypatch):
    db = tmp_path / "videos.db"
    monkeypatch.setattr(main, "DB_PATH", db)
    main.init_db()
    vid = "a" * 32
    _insert_test_video(db, vid)

    r = client.post(f"/videos/{vid}/transcriptions/import", json=_sample_payload())
    assert r.status_code == 201
    body = r.json()
    assert body["video_id"] == vid
    assert body["frames_imported"] == 2
    assert body["audio_imported"] == 2

    listed = client.get(f"/videos/{vid}/transcriptions").json()
    assert len(listed["frame_descriptions"]) == 2
    assert len(listed["transcriptions"]) == 2


def test_import_transcriptions_replaces_existing(tmp_path, monkeypatch):
    db = tmp_path / "videos.db"
    monkeypatch.setattr(main, "DB_PATH", db)
    main.init_db()
    vid = "a" * 32
    _insert_test_video(db, vid)

    client.post(f"/videos/{vid}/transcriptions/import", json=_sample_payload())
    second = {
        "frame_descriptions": [{"timestamp": 5.0, "description": "only one frame"}],
        "transcriptions": [],
    }
    r = client.post(f"/videos/{vid}/transcriptions/import", json=second)
    assert r.status_code == 201
    assert r.json()["frames_imported"] == 1
    assert r.json()["audio_imported"] == 0

    listed = client.get(f"/videos/{vid}/transcriptions").json()
    assert len(listed["frame_descriptions"]) == 1
    assert len(listed["transcriptions"]) == 0


def test_import_transcriptions_unknown_video(tmp_path, monkeypatch):
    monkeypatch.setattr(main, "DB_PATH", tmp_path / "videos.db")
    main.init_db()
    r = client.post("/videos/nosuchid/transcriptions/import", json=_sample_payload())
    assert r.status_code == 404


def test_search_frames_and_audio(tmp_path, monkeypatch):
    db = tmp_path / "videos.db"
    monkeypatch.setattr(main, "DB_PATH", db)
    main.init_db()
    vid = "a" * 32
    _insert_test_video(db, vid)
    client.post(f"/videos/{vid}/transcriptions/import", json=_sample_payload())

    r = client.get("/search", params={"q": "cat"})
    assert r.status_code == 200
    results = r.json()["results"]
    assert len(results) == 2
    sources = {x["source"] for x in results}
    assert sources == {"frame", "audio"}


def test_search_highlight_and_context(tmp_path, monkeypatch):
    db = tmp_path / "videos.db"
    monkeypatch.setattr(main, "DB_PATH", db)
    main.init_db()
    vid = "a" * 32
    _insert_test_video(db, vid, duration=10.0)
    client.post(f"/videos/{vid}/transcriptions/import", json=_sample_payload())

    r = client.get("/search", params={"q": "cat"})
    results = r.json()["results"]
    assert results
    for item in results:
        assert "<mark>" in item["excerpt"]
        assert item["context_start"] == max(0.0, item["timestamp"] - 3.0)
        assert item["context_end"] <= 10.0


def test_search_source_filter(tmp_path, monkeypatch):
    db = tmp_path / "videos.db"
    monkeypatch.setattr(main, "DB_PATH", db)
    main.init_db()
    vid = "a" * 32
    _insert_test_video(db, vid)
    client.post(f"/videos/{vid}/transcriptions/import", json=_sample_payload())

    r = client.get("/search", params={"q": "cat", "source": "frame"})
    assert r.status_code == 200
    results = r.json()["results"]
    assert all(x["source"] == "frame" for x in results)
    assert any("cat" in x["text"].lower() for x in results)


def test_search_substring_short_query(tmp_path, monkeypatch):
    db = tmp_path / "videos.db"
    monkeypatch.setattr(main, "DB_PATH", db)
    main.init_db()
    vid = "a" * 32
    _insert_test_video(db, vid)
    client.post(f"/videos/{vid}/transcriptions/import", json=_sample_payload())

    # Single-character queries rely on the INSTR fallback.
    r = client.get("/search", params={"q": "a"})
    assert r.status_code == 200
    assert len(r.json()["results"]) > 0


# --------------------------------------------------------------------------- #
# Image / audio query helpers (mock mode)
# --------------------------------------------------------------------------- #


def test_image_to_text_mock(tmp_path, monkeypatch):
    monkeypatch.setenv("MOCK_MODE", "true")
    monkeypatch.setattr(main, "DB_PATH", tmp_path / "videos.db")
    # Reset AI config so it picks up the mock env var
    import ai_clients
    ai_clients._AI_CONFIG = None
    main.init_db()

    # Create a tiny valid JPEG
    img_bytes = _make_tiny_jpeg(64, 48)
    r = client.post(
        "/search/helpers/image-to-text",
        files={"file": ("test.jpg", img_bytes, "image/jpeg")},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert "text" in body
    assert "MOCK" in body["text"]


def test_audio_to_text_mock(tmp_path, monkeypatch):
    monkeypatch.setenv("MOCK_MODE", "true")
    monkeypatch.setattr(main, "DB_PATH", tmp_path / "videos.db")
    import ai_clients
    ai_clients._AI_CONFIG = None
    main.init_db()

    r = client.post(
        "/search/helpers/audio-to-text",
        files={"file": ("test.wav", _make_tiny_wav(), "audio/wav")},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert "text" in body
    assert "MOCK" in body["text"]


def test_image_to_text_rejects_bad_format(tmp_path, monkeypatch):
    monkeypatch.setattr(main, "DB_PATH", tmp_path / "videos.db")
    main.init_db()
    r = client.post(
        "/search/helpers/image-to-text",
        files={"file": ("test.bmp", b"data", "image/bmp")},
    )
    assert r.status_code == 415


# --------------------------------------------------------------------------- #
# Transcription job lifecycle (mock mode)
# --------------------------------------------------------------------------- #


def _make_tiny_jpeg(w: int = 64, h: int = 48) -> bytes:
    """Create a minimal valid JPEG for testing."""
    import struct

    def _sob(n: int) -> bytes:
        return struct.pack(">H", n)

    # JFIF header
    data = b"\xff\xd8"  # SOI
    data += b"\xff\xe0" + _sob(16) + b"JFIF\x00" + b"\x01\x01\x00\x00\x01\x00\x01\x00\x00"
    # DQT (quantization table)
    data += b"\xff\xdb" + _sob(67) + b"\x00" + bytes(64)
    # SOF0
    data += b"\xff\xc0" + _sob(17) + b"\x08" + struct.pack(">HH", h, w) + b"\x03\x01\x11\x00"
    # DHT
    data += b"\xff\xc4" + _sob(29) + b"\x00\x01\x01\x01\x01\x01\x01\x01\x01\x00" + bytes(15)
    # SOS
    data += b"\xff\xda" + _sob(12) + b"\x01\x01\x00\x00\x3f\x00" + bytes(4)
    data += b"\xff\xd9"  # EOI
    return data


def _make_tiny_wav(duration_ms: int = 200) -> bytes:
    """Create a minimal valid WAV file (mono, 8 kHz, 8-bit PCM)."""
    import struct

    sample_rate = 8000
    num_samples = int(sample_rate * duration_ms / 1000)
    bits_per_sample = 8
    num_channels = 1
    byte_rate = sample_rate * num_channels * bits_per_sample // 8
    block_align = num_channels * bits_per_sample // 8
    data_size = num_samples * num_channels * bits_per_sample // 8

    # fmt sub-chunk
    fmt = struct.pack("<IHHIIHH", 16, 1, num_channels, sample_rate, byte_rate, block_align, bits_per_sample)
    # data sub-chunk (silence)
    data = struct.pack("<I", data_size) + bytes(data_size)

    riff_size = 4 + (8 + len(fmt)) + (8 + data_size)
    wav = b"RIFF" + struct.pack("<I", riff_size) + b"WAVEfmt " + fmt + b"data" + data
    return wav


@needs_sample
def test_transcription_job_lifecycle_mock(tmp_path, monkeypatch):
    """Full transcription lifecycle: upload -> transcribe -> poll -> complete."""
    monkeypatch.setenv("MOCK_MODE", "true")
    import ai_clients
    ai_clients._AI_CONFIG = None

    up = tmp_path / "uploads"
    up.mkdir()
    monkeypatch.setattr(main, "UPLOAD_DIR", up)
    monkeypatch.setattr(main, "DB_PATH", tmp_path / "videos.db")
    main.init_db()

    # Upload a sample (status='queued')
    with SAMPLE_TS.open("rb") as fh:
        r = client.post(
            "/videos",
            files={"file": (SAMPLE_TS.name, fh)},
            data={"location": "transcribe-test"},
        )
    assert r.status_code == 201, r.text
    vid = r.json()["id"]
    assert r.json()["status"] == "queued"

    # Process transcode synchronously so the video can be transcribed.
    import asyncio
    asyncio.run(main._process_transcode_job(vid, 0, False, True))

    # Create transcription job
    r = client.post(f"/videos/{vid}/transcribe")
    assert r.status_code == 201, r.text
    body = r.json()
    job_id = body["job_id"]
    assert body["status"] == "queued"
    assert body["total_chunks"] > 0

    # Process the job synchronously in-test (simulating the worker)
    from main import _process_job

    asyncio.run(_process_job(job_id))

    # Check job status -> completed
    r = client.get(f"/transcribe/jobs/{job_id}")
    assert r.status_code == 200
    data = r.json()
    assert data["job"]["status"] == "completed"
    assert all(c["status"] == "completed" for c in data["chunks"])

    # Check that transcriptions were inserted
    r = client.get(f"/videos/{vid}/transcriptions")
    assert r.status_code == 200
    tx = r.json()
    assert len(tx["frame_descriptions"]) > 0
    assert len(tx["transcriptions"]) > 0

    # Duplicate job creation should be rejected
    r = client.post(f"/videos/{vid}/transcribe")
    assert r.status_code == 409, r.text
    assert "already exists" in r.text


# --------------------------------------------------------------------------- #
# Cascading deletes still work with new tables
# --------------------------------------------------------------------------- #


def test_delete_video_cascades_transcriptions(tmp_path, monkeypatch):
    db = tmp_path / "videos.db"
    monkeypatch.setattr(main, "DB_PATH", db)
    main.init_db()
    vid = "a" * 32
    _insert_test_video(db, vid)
    client.post(f"/videos/{vid}/transcriptions/import", json=_sample_payload())

    assert client.delete(f"/videos/{vid}").status_code == 204

    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    frames = conn.execute(
        "SELECT * FROM frame_descriptions WHERE video_id = ?", (vid,)
    ).fetchall()
    audio = conn.execute(
        "SELECT * FROM audio_transcriptions WHERE video_id = ?", (vid,)
    ).fetchall()
    conn.close()
    assert len(frames) == 0
    assert len(audio) == 0
