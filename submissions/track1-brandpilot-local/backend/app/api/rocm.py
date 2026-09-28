from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse

from app.core.config import experimental_rocm_enabled
from app.core.security import require_demo_auth
from app.schemas.rocm import RocmGenerationRequest
from app.services.rocm_jobs import rocm_jobs
from app.services.store import store

router = APIRouter(
    prefix="/experimental/rocm",
    tags=["experimental-rocm"],
    dependencies=[Depends(require_demo_auth)],
)


def require_enabled() -> None:
    if not experimental_rocm_enabled():
        raise HTTPException(status_code=503, detail="Experimental ROCm mode is disabled")


@router.get("/status")
def status() -> dict:
    return rocm_jobs.status()


@router.post("/projects/{project_id}/generate", status_code=202)
def generate(
    project_id: str,
    payload: RocmGenerationRequest,
    _: None = Depends(require_enabled),
) -> dict:
    project = store.get(project_id)
    if not project.get("asset"):
        raise HTTPException(status_code=409, detail="Upload a product asset before generation")
    try:
        return rocm_jobs.submit(
            project,
            payload.creative_style,
            payload.output_format,
            payload.seed,
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.get("/jobs/{job_id}")
def get_job(job_id: str, _: None = Depends(require_enabled)) -> dict:
    try:
        return rocm_jobs.get(job_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Experimental job not found") from exc


@router.get("/jobs/{job_id}/output")
def get_output(job_id: str, _: None = Depends(require_enabled)) -> FileResponse:
    try:
        output = rocm_jobs.output_path(job_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Experimental output is not available") from exc
    except ValueError as exc:
        raise HTTPException(status_code=404, detail="Experimental output is not available") from exc
    return FileResponse(output, media_type="image/png", filename="brandpilot-rocm-output.png")
