"""Bounded multipart image and video ingestion into the local evidence store."""

from __future__ import annotations

import hashlib
import os
import tempfile
from io import BytesIO
from pathlib import Path, PurePath
from typing import Annotated
from uuid import uuid4

import cv2
import numpy as np
from fastapi import APIRouter, File, HTTPException, UploadFile
from PIL import Image, UnidentifiedImageError
from pydantic import Field

from buildguard.config import ImageUploadConfig, VideoUploadConfig
from buildguard.schemas.common import StrictSchema
from buildguard.storage.database import Database
from buildguard.storage.repositories import Repositories


class UploadedImage(StrictSchema):
    evidence_id: str
    storage_name: str
    storage_path: Path
    sha256: str = Field(min_length=64, max_length=64)
    size_bytes: int = Field(ge=1)
    width: int = Field(ge=1)
    height: int = Field(ge=1)
    mime_type: str


class UploadFailure(StrictSchema):
    original_name: str
    error: str


class UploadBatchResult(StrictSchema):
    uploaded: list[UploadedImage] = Field(default_factory=list)
    failures: list[UploadFailure] = Field(default_factory=list)


class UploadedVideo(StrictSchema):
    evidence_id: str
    storage_name: str
    storage_path: Path
    sha256: str = Field(min_length=64, max_length=64)
    size_bytes: int = Field(ge=1)
    width: int = Field(ge=1)
    height: int = Field(ge=1)
    frame_count: int = Field(ge=1)
    fps: float = Field(ge=0)
    duration_seconds: float = Field(ge=0)
    mime_type: str


class VideoUploadBatchResult(StrictSchema):
    uploaded: list[UploadedVideo] = Field(default_factory=list)
    failures: list[UploadFailure] = Field(default_factory=list)


def _safe_original_name(name: str | None) -> str:
    if not name or "\x00" in name or "/" in name or "\\" in name:
        raise ValueError("Unsafe or missing client filename")
    if PurePath(name).name != name or name in {".", ".."}:
        raise ValueError("Path components are not allowed in client filenames")
    return name


def _decode_image(content: bytes) -> tuple[int, int, str]:
    try:
        with Image.open(BytesIO(content)) as image:
            image.verify()
        with Image.open(BytesIO(content)) as image:
            image.load()
            width, height = image.size
            image_format = str(image.format or "").upper()
    except (UnidentifiedImageError, OSError, ValueError) as exc:
        raise ValueError(f"Pillow could not decode image: {exc}") from exc
    decoded = cv2.imdecode(np.frombuffer(content, dtype=np.uint8), cv2.IMREAD_COLOR)
    if decoded is None or decoded.size == 0:
        raise ValueError("OpenCV could not decode image")
    if image_format not in {"JPEG", "PNG"}:
        raise ValueError(f"Decoded image format is not allowed: {image_format}")
    return width, height, image_format


def _inspect_video(path: Path) -> tuple[int, int, int, float, float]:
    capture = cv2.VideoCapture(str(path))
    try:
        if not capture.isOpened():
            raise ValueError("OpenCV could not open video")
        ok, frame = capture.read()
        if not ok or frame is None or frame.size == 0:
            raise ValueError("OpenCV could not decode the first video frame")
        height, width = frame.shape[:2]
        frame_count = max(1, round(capture.get(cv2.CAP_PROP_FRAME_COUNT)))
        fps = max(0.0, float(capture.get(cv2.CAP_PROP_FPS)))
        duration = frame_count / fps if fps > 0 else 0.0
        return int(width), int(height), frame_count, fps, duration
    finally:
        capture.release()


def _persist(
    database: Database,
    root: Path,
    original_name: str,
    mime_type: str,
    extension: str,
    content: bytes,
    width: int,
    height: int,
) -> UploadedImage:
    evidence_id = str(uuid4())
    storage_name = f"{uuid4().hex}{extension}"
    destination = (root / storage_name).resolve()
    try:
        destination.relative_to(root)
    except ValueError as exc:
        raise ValueError("Generated upload path escaped the allowed root") from exc
    digest = hashlib.sha256(content).hexdigest()
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb", dir=root, prefix=".upload-", delete=False
        ) as stream:
            temporary = Path(stream.name)
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, destination)
        with database.session() as session:
            Repositories(session).uploaded_evidence.create(
                evidence_id=evidence_id,
                storage_path=str(destination),
                original_name=original_name,
                mime_type=mime_type,
                sha256=digest,
                size_bytes=len(content),
                width=width,
                height=height,
            )
    except (OSError, RuntimeError, ValueError):
        if temporary is not None:
            temporary.unlink(missing_ok=True)
        destination.unlink(missing_ok=True)
        raise
    return UploadedImage(
        evidence_id=evidence_id,
        storage_name=storage_name,
        storage_path=destination,
        sha256=digest,
        size_bytes=len(content),
        width=width,
        height=height,
        mime_type=mime_type,
    )


def create_upload_router(
    database: Database,
    upload_root: Path,
    config: ImageUploadConfig,
    video_config: VideoUploadConfig | None = None,
) -> APIRouter:
    if upload_root.is_symlink():
        raise ValueError("Upload root must not be a symbolic link")
    root = upload_root.resolve()
    root.mkdir(parents=True, exist_ok=True)
    allowed_extensions = {item.casefold() for item in config.allowed_extensions}
    allowed_mimes = {item.casefold() for item in config.allowed_mime_types}
    effective_video_config = video_config or VideoUploadConfig()
    allowed_video_extensions = {
        item.casefold() for item in effective_video_config.allowed_extensions
    }
    allowed_video_mimes = {
        item.casefold() for item in effective_video_config.allowed_mime_types
    }
    router = APIRouter(prefix="/uploads", tags=["uploads"])

    @router.post("/images", response_model=UploadBatchResult)
    async def upload_images(
        files: Annotated[list[UploadFile], File()],
    ) -> UploadBatchResult:
        if not files or len(files) > config.max_files:
            raise HTTPException(
                status_code=413,
                detail=f"Upload batch must contain 1..{config.max_files} files",
            )
        uploaded: list[UploadedImage] = []
        failures: list[UploadFailure] = []
        total_bytes = 0
        for upload in files:
            display_name = upload.filename or "<unnamed>"
            try:
                original_name = _safe_original_name(upload.filename)
                extension = Path(original_name).suffix.casefold()
                mime_type = (upload.content_type or "").casefold()
                if extension not in allowed_extensions:
                    raise ValueError(f"Extension is not allowed: {extension or '<none>'}")
                if mime_type not in allowed_mimes:
                    raise ValueError(f"MIME type is not allowed: {mime_type or '<none>'}")
                chunks: list[bytes] = []
                file_bytes = 0
                while chunk := await upload.read(config.chunk_bytes):
                    file_bytes += len(chunk)
                    total_bytes += len(chunk)
                    if file_bytes > config.max_file_bytes:
                        raise ValueError("File exceeds the per-file size limit")
                    if total_bytes > config.max_total_bytes:
                        raise ValueError("Batch exceeds the total size limit")
                    chunks.append(chunk)
                content = b"".join(chunks)
                if not content:
                    raise ValueError("Image file is empty")
                width, height, decoded_format = _decode_image(content)
                expected_format = "JPEG" if mime_type == "image/jpeg" else "PNG"
                if decoded_format != expected_format:
                    raise ValueError("MIME type does not match decoded image format")
                uploaded.append(
                    _persist(
                        database,
                        root,
                        original_name,
                        mime_type,
                        extension,
                        content,
                        width,
                        height,
                    )
                )
            except (OSError, RuntimeError, ValueError) as exc:
                failures.append(
                    UploadFailure(original_name=display_name, error=str(exc))
                )
            finally:
                await upload.close()
        return UploadBatchResult(uploaded=uploaded, failures=failures)

    @router.post("/videos", response_model=VideoUploadBatchResult)
    async def upload_videos(
        files: Annotated[list[UploadFile], File()],
    ) -> VideoUploadBatchResult:
        if not files or len(files) > effective_video_config.max_files:
            raise HTTPException(
                status_code=413,
                detail=(
                    "Video upload batch must contain "
                    f"1..{effective_video_config.max_files} files"
                ),
            )
        uploaded: list[UploadedVideo] = []
        failures: list[UploadFailure] = []
        total_bytes = 0
        for upload in files:
            display_name = upload.filename or "<unnamed>"
            temporary: Path | None = None
            destination: Path | None = None
            try:
                original_name = _safe_original_name(upload.filename)
                extension = Path(original_name).suffix.casefold()
                mime_type = (upload.content_type or "").casefold()
                if extension not in allowed_video_extensions:
                    raise ValueError(
                        f"Video extension is not allowed: {extension or '<none>'}"
                    )
                if mime_type not in allowed_video_mimes:
                    raise ValueError(
                        f"Video MIME type is not allowed: {mime_type or '<none>'}"
                    )
                digest = hashlib.sha256()
                size_bytes = 0
                with tempfile.NamedTemporaryFile(
                    mode="wb",
                    dir=root,
                    prefix=".video-upload-",
                    suffix=extension,
                    delete=False,
                ) as stream:
                    temporary = Path(stream.name)
                    while chunk := await upload.read(effective_video_config.chunk_bytes):
                        size_bytes += len(chunk)
                        total_bytes += len(chunk)
                        if size_bytes > effective_video_config.max_file_bytes:
                            raise ValueError("Video exceeds the per-file size limit")
                        if total_bytes > effective_video_config.max_total_bytes:
                            raise ValueError("Video batch exceeds the total size limit")
                        digest.update(chunk)
                        stream.write(chunk)
                    stream.flush()
                    os.fsync(stream.fileno())
                if size_bytes == 0:
                    raise ValueError("Video file is empty")
                width, height, frame_count, fps, duration = _inspect_video(temporary)
                evidence_id = str(uuid4())
                storage_name = f"{uuid4().hex}{extension}"
                destination = (root / storage_name).resolve()
                destination.relative_to(root)
                os.replace(temporary, destination)
                temporary = None
                with database.session() as session:
                    Repositories(session).uploaded_evidence.create(
                        evidence_id=evidence_id,
                        storage_path=str(destination),
                        original_name=original_name,
                        mime_type=mime_type,
                        sha256=digest.hexdigest(),
                        size_bytes=size_bytes,
                        width=width,
                        height=height,
                    )
                uploaded.append(
                    UploadedVideo(
                        evidence_id=evidence_id,
                        storage_name=storage_name,
                        storage_path=destination,
                        sha256=digest.hexdigest(),
                        size_bytes=size_bytes,
                        width=width,
                        height=height,
                        frame_count=frame_count,
                        fps=fps,
                        duration_seconds=duration,
                        mime_type=mime_type,
                    )
                )
            except (OSError, RuntimeError, ValueError) as exc:
                if temporary is not None:
                    temporary.unlink(missing_ok=True)
                if destination is not None:
                    destination.unlink(missing_ok=True)
                failures.append(UploadFailure(original_name=display_name, error=str(exc)))
            finally:
                await upload.close()
        return VideoUploadBatchResult(uploaded=uploaded, failures=failures)

    return router
