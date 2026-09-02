"""Project CRUD, source upload, policy parse/save, media info and previews."""

from __future__ import annotations

import logging
import re
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Body, File, HTTPException, Request, Response, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

router = APIRouter(tags=["projects"])

_ALLOWED_EXTS = {"mp4", "mov", "mkv", "avi", "webm", "m4v", "mpg", "mpeg", "mts", "ts"}
_MIME_BY_EXT = {
    "mp4": "video/mp4",
    "m4v": "video/mp4",
    "mov": "video/quicktime",
    "mkv": "video/x-matroska",
    "avi": "video/x-msvideo",
    "webm": "video/webm",
    "mpg": "video/mpeg",
    "mpeg": "video/mpeg",
    "ts": "video/mp2t",
    "mts": "video/mp2t",
}


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def _store(request: Request):
    return request.app.state.store


def _settings(request: Request):
    return request.app.state.settings


def _get_project_or_404(store, project_id: str):
    project = store.get_project(project_id)
    if project is None:
        raise HTTPException(status_code=404, detail=f"Project not found: {project_id}")
    return project


class CreateProjectBody(BaseModel):
    name: str = Field(min_length=1, max_length=200)


class RenameProjectBody(BaseModel):
    name: str = Field(min_length=1, max_length=200)


class ParsePolicyBody(BaseModel):
    text: str = Field(min_length=1)


# ---------------------------------------------------------------------------
# CRUD
# ---------------------------------------------------------------------------


@router.get("/projects")
def list_projects(request: Request) -> dict:
    store = _store(request)
    projects = store.list_projects()
    try:
        projects = sorted(projects, key=lambda p: p.updated_at, reverse=True)
    except Exception:
        pass
    return {"projects": [p.model_dump() for p in projects]}


@router.post("/projects", status_code=201)
def create_project(body: CreateProjectBody, request: Request):
    store = _store(request)
    project = store.create_project(body.name.strip())
    return project


@router.get("/projects/{project_id}")
def get_project(project_id: str, request: Request):
    return _get_project_or_404(_store(request), project_id)


@router.patch("/projects/{project_id}")
def rename_project(project_id: str, body: RenameProjectBody, request: Request):
    store = _store(request)
    project = _get_project_or_404(store, project_id)
    project.name = body.name.strip()
    project.updated_at = _utcnow()
    store.save_project(project)
    return project


@router.delete("/projects/{project_id}", status_code=204)
def delete_project(project_id: str, request: Request) -> Response:
    store = _store(request)
    _get_project_or_404(store, project_id)
    store.delete_project(project_id)
    return Response(status_code=204)


# ---------------------------------------------------------------------------
# Source upload
# ---------------------------------------------------------------------------


def _safe_ext(filename: str | None) -> str:
    ext = ""
    if filename and "." in filename:
        ext = filename.rsplit(".", 1)[-1].lower()
        ext = re.sub(r"[^a-z0-9]", "", ext)[:5]
    return ext if ext in _ALLOWED_EXTS else "mp4"


def _probe_media(path: Path):
    """Call the media.probe module (name is flexible across implementations)."""
    from policycut.media import probe as probe_mod

    for name in ("probe_media", "probe", "get_media_info", "ffprobe", "probe_video"):
        fn = getattr(probe_mod, name, None)
        if callable(fn):
            info = fn(path)
            if info is None:
                raise ValueError("ffprobe returned no media information")
            if isinstance(info, dict):
                from policycut.core.models import MediaInfo

                info = MediaInfo.model_validate(info)
            return info
    raise RuntimeError("media probe function not available")


def _make_thumbnail(src: Path, dst: Path, duration_s: float) -> None:
    """Best-effort single-frame thumbnail via ffmpeg."""
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        return
    seek = max(0.0, min(1.0, float(duration_s) * 0.25))
    try:
        dst.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(
            [
                ffmpeg, "-y", "-ss", f"{seek:.2f}", "-i", str(src),
                "-frames:v", "1", "-vf", "scale=480:-2", str(dst),
            ],
            capture_output=True,
            timeout=30,
            check=False,
        )
    except Exception:
        logger.debug("thumbnail generation failed", exc_info=True)


@router.post("/projects/{project_id}/source")
async def upload_source(project_id: str, request: Request, file: UploadFile = File(...)):
    store = _store(request)
    settings = _settings(request)
    project = _get_project_or_404(store, project_id)

    ext = _safe_ext(file.filename)
    src_dir = Path(store.project_dir(project_id)) / "source"
    if src_dir.is_dir():
        for old in src_dir.glob("original.*"):
            try:
                old.unlink()
            except OSError:
                pass
    dest = Path(store.path(project_id, "source", f"original.{ext}"))

    try:
        with open(dest, "wb") as out:
            while True:
                chunk = await file.read(1024 * 1024)
                if not chunk:
                    break
                out.write(chunk)
    finally:
        await file.close()

    try:
        info = _probe_media(dest)
    except Exception as exc:
        dest.unlink(missing_ok=True)
        raise HTTPException(
            status_code=400,
            detail=f"Could not read the uploaded video (ffprobe): {exc}",
        )

    max_seconds = float(getattr(settings, "max_video_seconds", 60.0))
    duration = float(getattr(info, "duration_s", 0.0))
    if duration <= 0:
        dest.unlink(missing_ok=True)
        raise HTTPException(
            status_code=400,
            detail="The uploaded file has no readable video duration; it may be corrupt.",
        )
    if duration > max_seconds + 0.05:
        dest.unlink(missing_ok=True)
        raise HTTPException(
            status_code=400,
            detail=(
                f"Video is {duration:.1f}s long; the maximum supported length is "
                f"{max_seconds:.0f}s. Please trim it and upload again."
            ),
        )

    thumb = Path(store.path(project_id, "working", "thumbnail.jpg"))
    _make_thumbnail(dest, thumb, duration)

    updates = {"filename": file.filename or dest.name}
    try:
        updates["size_bytes"] = dest.stat().st_size
    except OSError:
        pass
    project.media = info.model_copy(update=updates) if hasattr(info, "model_copy") else info
    project.updated_at = _utcnow()
    store.save_project(project)
    return project


@router.get("/projects/{project_id}/media")
def get_media(project_id: str, request: Request):
    project = _get_project_or_404(_store(request), project_id)
    if project.media is None:
        raise HTTPException(status_code=404, detail="No media uploaded for this project")
    return project.media


# ---------------------------------------------------------------------------
# Policy
# ---------------------------------------------------------------------------


@router.post("/projects/{project_id}/policy/parse")
def parse_policy_endpoint(project_id: str, body: ParsePolicyBody, request: Request) -> dict:
    store = _store(request)
    project = _get_project_or_404(store, project_id)
    try:
        from policycut.policy.parser import parse_policy  # lazy: may load an LLM

        result = parse_policy(body.text)
    except Exception as exc:
        logger.exception("policy parsing failed")
        raise HTTPException(status_code=500, detail=f"Policy parsing failed: {exc}")
    if isinstance(result, tuple) and len(result) == 2:
        spec, source = result
    else:  # tolerate an implementation returning just the spec
        spec, source = result, "keyword_fallback"
    project.policy_text = body.text
    project.updated_at = _utcnow()
    store.save_project(project)
    return {
        "spec": spec.model_dump() if hasattr(spec, "model_dump") else spec,
        "source": source,
    }


@router.put("/projects/{project_id}/policy")
def save_policy(project_id: str, request: Request, body: dict = Body(...)) -> dict:
    store = _store(request)
    project = _get_project_or_404(store, project_id)
    payload = body.get("spec", body) if isinstance(body, dict) else body
    from policycut.policy.schema import PolicySpec

    try:
        spec = PolicySpec.model_validate(payload)
    except Exception as exc:
        raise HTTPException(status_code=422, detail=f"Invalid policy spec: {exc}")
    store.save_policy(project_id, spec)
    project.updated_at = _utcnow()
    store.save_project(project)
    return spec.model_dump()


# ---------------------------------------------------------------------------
# Previews / thumbnail
# ---------------------------------------------------------------------------


def _find_source_file(store, project_id: str) -> Path | None:
    src_dir = Path(store.project_dir(project_id)) / "source"
    if src_dir.is_dir():
        for path in sorted(src_dir.iterdir()):
            if path.is_file() and path.stem == "original":
                return path
    return None


@router.get("/projects/{project_id}/preview/original")
def preview_original(project_id: str, request: Request):
    store = _store(request)
    _get_project_or_404(store, project_id)
    normalized = Path(store.project_dir(project_id)) / "working" / "normalized.mp4"
    if normalized.is_file():
        return FileResponse(normalized, media_type="video/mp4")
    source = _find_source_file(store, project_id)
    if source is not None:
        ext = source.suffix.lstrip(".").lower()
        return FileResponse(source, media_type=_MIME_BY_EXT.get(ext, "video/mp4"))
    raise HTTPException(status_code=404, detail="No media available for preview")


@router.get("/projects/{project_id}/preview/overlay")
def preview_overlay(project_id: str, request: Request):
    store = _store(request)
    _get_project_or_404(store, project_id)
    overlay = Path(store.project_dir(project_id)) / "working" / "review_overlay.mp4"
    if not overlay.is_file():
        # No overlay (e.g. zero events) — fall back to the normalized preview
        normalized = Path(store.project_dir(project_id)) / "working" / "normalized.mp4"
        if normalized.is_file():
            return FileResponse(normalized, media_type="video/mp4")
        raise HTTPException(status_code=404, detail="Review overlay not generated yet")
    return FileResponse(overlay, media_type="video/mp4")


@router.get("/projects/{project_id}/thumbnail")
def thumbnail(project_id: str, request: Request):
    store = _store(request)
    _get_project_or_404(store, project_id)
    thumb = Path(store.project_dir(project_id)) / "working" / "thumbnail.jpg"
    if not thumb.is_file():
        raise HTTPException(status_code=404, detail="Thumbnail not generated yet")
    return FileResponse(thumb, media_type="image/jpeg")
