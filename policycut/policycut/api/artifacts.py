"""Export artifact downloads: GET /projects/{id}/artifacts/{kind}."""

from __future__ import annotations

import re
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse

router = APIRouter(tags=["artifacts"])

_KINDS: dict[str, tuple[str, str]] = {
    "video": ("redacted.mp4", "video/mp4"),
    "srt": ("redacted.srt", "application/x-subrip"),
    "audit": ("audit.json", "application/json"),
    "zip": ("policycut_export.zip", "application/zip"),
}


def _slug(name: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9_-]+", "_", name or "").strip("_")
    return slug[:60] or "policycut"


@router.get("/projects/{project_id}/artifacts/{kind}")
def get_artifact(project_id: str, kind: str, request: Request):
    store = request.app.state.store
    project = store.get_project(project_id)
    if project is None:
        raise HTTPException(status_code=404, detail=f"Project not found: {project_id}")
    if kind not in _KINDS:
        raise HTTPException(
            status_code=404,
            detail=f"Unknown artifact kind '{kind}' (expected one of: {', '.join(_KINDS)})",
        )
    filename, media_type = _KINDS[kind]
    path = Path(store.project_dir(project_id)) / "exports" / filename
    if not path.is_file():
        raise HTTPException(
            status_code=404, detail=f"Artifact not generated yet: {filename}"
        )
    return FileResponse(
        path,
        media_type=media_type,
        filename=f"{_slug(project.name)}_{filename}",
    )
