"""Job submission, status, gallery, and artifact download endpoints."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse

from app.config import JOBS_DIR
from app.schemas import JobCreate, JobListResponse, JobOut
from app.services.job_manager import JobManager, new_job

router = APIRouter(prefix="/api/v1/jobs", tags=["jobs"])


def _manager(request: Request) -> JobManager:
    """Resolve the JobManager installed on app.state by app.main lifespan."""
    mgr = getattr(request.app.state, "manager", None)
    if mgr is None:
        raise HTTPException(status_code=503, detail="job manager not ready")
    return mgr


@router.post("", response_model=JobOut)
async def create_job(request: Request, req: JobCreate) -> JobOut:
    if not req.text or not req.text.strip():
        raise HTTPException(status_code=422, detail="provide `text`")
    job = new_job(req.engine, req.text.strip(), req.style)
    await _manager(request).submit(job)
    return JobOut(**{k: job[k] for k in JobOut.model_fields if k in job})


@router.get("", response_model=JobListResponse)
def list_jobs(request: Request, limit: int = 50, offset: int = 0) -> JobListResponse:
    limit = max(1, min(limit, 200))
    mgr = _manager(request)
    rows = mgr.store.list(limit=limit, offset=offset)
    total = mgr.store.count()
    return JobListResponse(
        jobs=[JobOut(**{k: r[k] for k in JobOut.model_fields if k in r}) for r in rows],
        total=total,
    )


@router.get("/{job_id}", response_model=JobOut)
def get_job(request: Request, job_id: str) -> JobOut:
    job = _manager(request).store.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="job not found")
    return JobOut(**{k: job[k] for k in JobOut.model_fields if k in job})


@router.get("/{job_id}/files/{filename}")
def download_artifact(job_id: str, filename: str) -> FileResponse:
    job_dir = JOBS_DIR / job_id
    path = (job_dir / filename).resolve()
    if not path.is_relative_to(job_dir.resolve()) or not path.is_file():
        raise HTTPException(status_code=404, detail="artifact not found")
    return FileResponse(path, filename=filename)
