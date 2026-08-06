from io import BytesIO
from pathlib import Path

import cv2
import numpy as np
from fastapi import FastAPI
from fastapi.testclient import TestClient
from PIL import Image
from sqlalchemy import func, select

from buildguard.api.routes_upload import create_upload_router
from buildguard.config import ImageUploadConfig, VideoUploadConfig
from buildguard.storage.database import Database
from buildguard.storage.models import UploadedEvidenceModel


def _image(image_format: str = "PNG") -> bytes:
    output = BytesIO()
    Image.new("RGB", (8, 6), color=(10, 20, 30)).save(output, format=image_format)
    return output.getvalue()


def _video(path: Path) -> bytes:
    writer = cv2.VideoWriter(
        str(path),
        cv2.VideoWriter_fourcc(*"MJPG"),
        5,
        (32, 24),
    )
    assert writer.isOpened()
    for value in (20, 80, 140):
        writer.write(np.full((24, 32, 3), value, dtype=np.uint8))
    writer.release()
    return path.read_bytes()


def _client(
    tmp_path: Path, config: ImageUploadConfig | None = None
) -> tuple[TestClient, Database, Path]:
    root = tmp_path / "workspace" / "uploads"
    database = Database(tmp_path / "workspace" / "database" / "buildguard.db")
    database.initialize()
    app = FastAPI()
    app.include_router(create_upload_router(database, root, config or ImageUploadConfig()))
    return TestClient(app), database, root


def test_upload_accepts_jpeg_png_and_persists_random_names(tmp_path: Path) -> None:
    client, database, root = _client(tmp_path)
    response = client.post(
        "/uploads/images",
        files=[
            ("files", ("camera.jpg", _image("JPEG"), "image/jpeg")),
            ("files", ("camera.png", _image("PNG"), "image/png")),
        ],
    )

    assert response.status_code == 200
    payload = response.json()
    assert len(payload["uploaded"]) == 2
    assert payload["failures"] == []
    assert all("/" not in item["storage_name"] for item in payload["uploaded"])
    assert all((root / item["storage_name"]).is_file() for item in payload["uploaded"])
    with database.session() as session:
        count = session.scalar(select(func.count()).select_from(UploadedEvidenceModel))
    assert count == 2


def test_upload_contains_bad_files_and_rejects_traversal(tmp_path: Path) -> None:
    client, _, root = _client(tmp_path)
    response = client.post(
        "/uploads/images",
        files=[
            ("files", ("good.png", _image(), "image/png")),
            ("files", ("../escape.png", _image(), "image/png")),
            ("files", ("fake.jpg", b"plain text", "image/jpeg")),
            ("files", ("bad.png", b"\x89PNG damaged", "image/png")),
            ("files", ("empty.png", b"", "image/png")),
            ("files", ("wrong.gif", _image(), "image/png")),
        ],
    )

    assert response.status_code == 200
    assert len(response.json()["uploaded"]) == 1
    assert len(response.json()["failures"]) == 5
    assert not (tmp_path / "workspace" / "escape.png").exists()
    assert len(list(root.glob("*"))) == 1


def test_upload_enforces_size_and_mime_without_stopping_batch(tmp_path: Path) -> None:
    config = ImageUploadConfig(
        max_files=3,
        max_file_bytes=100,
        max_total_bytes=300,
        chunk_bytes=4096,
    )
    client, _, _ = _client(tmp_path, config)
    png = _image()
    response = client.post(
        "/uploads/images",
        files=[
            ("files", ("large.png", png + b"x" * 100, "image/png")),
            ("files", ("mime.png", png, "text/plain")),
        ],
    )

    assert response.status_code == 200
    assert len(response.json()["failures"]) == 2
    too_many = client.post(
        "/uploads/images",
        files=[
            ("files", (f"{index}.png", png, "image/png"))
            for index in range(4)
        ],
    )
    assert too_many.status_code == 413


def test_duplicate_content_gets_distinct_evidence_records(tmp_path: Path) -> None:
    client, _, _ = _client(tmp_path)
    content = _image()
    response = client.post(
        "/uploads/images",
        files=[
            ("files", ("one.png", content, "image/png")),
            ("files", ("two.png", content, "image/png")),
        ],
    )
    uploaded = response.json()["uploaded"]

    assert uploaded[0]["sha256"] == uploaded[1]["sha256"]
    assert uploaded[0]["evidence_id"] != uploaded[1]["evidence_id"]
    assert uploaded[0]["storage_name"] != uploaded[1]["storage_name"]


def test_video_upload_validates_decodes_and_persists_metadata(tmp_path: Path) -> None:
    client, database, root = _client(tmp_path)
    content = _video(tmp_path / "fixture.avi")

    response = client.post(
        "/uploads/videos",
        files=[("files", ("inspection.avi", content, "video/x-msvideo"))],
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["failures"] == []
    uploaded = payload["uploaded"][0]
    assert uploaded["frame_count"] >= 3
    assert uploaded["width"] == 32
    assert uploaded["height"] == 24
    assert uploaded["duration_seconds"] > 0
    assert (root / uploaded["storage_name"]).is_file()
    with database.session() as session:
        count = session.scalar(select(func.count()).select_from(UploadedEvidenceModel))
    assert count == 1


def test_video_upload_rejects_fake_content_and_unsafe_names(tmp_path: Path) -> None:
    root = tmp_path / "workspace" / "uploads"
    database = Database(tmp_path / "workspace" / "database" / "buildguard.db")
    database.initialize()
    app = FastAPI()
    app.include_router(
        create_upload_router(
            database,
            root,
            ImageUploadConfig(),
            VideoUploadConfig(max_files=2),
        )
    )
    client = TestClient(app)

    response = client.post(
        "/uploads/videos",
        files=[
            ("files", ("fake.mp4", b"not a video", "video/mp4")),
            ("files", ("../escape.avi", b"not a video", "video/x-msvideo")),
        ],
    )

    assert response.status_code == 200
    assert response.json()["uploaded"] == []
    assert len(response.json()["failures"]) == 2
    assert list(root.glob("*")) == []
