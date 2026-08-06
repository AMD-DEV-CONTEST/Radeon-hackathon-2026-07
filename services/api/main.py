import os
import warnings
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, File, UploadFile, Depends, HTTPException, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from sqlalchemy.orm import Session

from config import settings
from models import init_db, get_db, GenerationJob, JobStatus
# Import memory models so their tables are registered before init_db()
import agents.memory  # noqa: F401
from storage import save_upload
from jobs.tasks import generate_3d_task
from shared.schemas.job import JobCreateRequest, JobResponse
from routers import styles, agent


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Ensure SQLite parent directory exists before initializing tables.
    if settings.database_url.startswith("sqlite:///./"):
        db_file = Path(settings.database_url.replace("sqlite:///./", ""))
        db_file.parent.mkdir(parents=True, exist_ok=True)
    init_db()
    yield


app = FastAPI(
    title=settings.app_name,
    debug=settings.app_debug,
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[origin.strip() for origin in settings.cors_origins.split(",")],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(styles.router)
app.include_router(agent.router)


def _resolve_safe_path(path: str) -> Path:
    """Resolve a requested path while preventing directory traversal."""
    base = Path.cwd().resolve()
    target = (base / path).resolve()
    if not str(target).startswith(str(base)):
        raise HTTPException(status_code=400, detail="Invalid path")
    return target


@app.get("/health")
def health():
    return {"status": "ok", "app": settings.app_name}


@app.get("/health/gpu")
def health_gpu():
    """Return ROCm / AMD GPU availability and basic device info.

    This endpoint is useful for demonstrating that the tool runs on AMD Radeon GPUs.
    """
    info = {
        "rocm_available": False,
        "hip_version": None,
        "gpu_name": None,
        "gpu_count": 0,
        "gpu_memory_mb": None,
        "torch_cuda_available": False,
        "use_rocm_forced": os.environ.get("USE_ROCM", "false").lower() in ("1", "true", "yes"),
    }
    try:
        import torch

        info["torch_cuda_available"] = bool(torch.cuda.is_available())
        info["hip_version"] = getattr(torch.version, "hip", None)
        if info["hip_version"] is not None and torch.cuda.is_available():
            info["rocm_available"] = True
            info["gpu_count"] = torch.cuda.device_count()
            if info["gpu_count"] > 0:
                props = torch.cuda.get_device_properties(0)
                info["gpu_name"] = torch.cuda.get_device_name(0)
                info["gpu_memory_mb"] = int(props.total_memory / 1024**2)
    except ImportError:
        pass
    except Exception as exc:
        warnings.warn(f"GPU health check failed: {exc}")

    return info


@app.post("/upload")
async def upload(file: UploadFile = File(...)):
    if not file.content_type or not file.content_type.startswith("image/"):
        raise HTTPException(status_code=400, detail="Only image files are allowed")
    import uuid
    job_id = str(uuid.uuid4())
    saved = save_upload(file, job_id)
    return {
        "job_id": job_id,
        "filename": file.filename,
        "path": str(saved),
        "content_type": file.content_type,
    }


@app.post("/jobs", response_model=JobResponse)
def create_job(payload: JobCreateRequest, background_tasks: BackgroundTasks, db: Session = Depends(get_db)):
    job = GenerationJob(
        status=JobStatus.PENDING.value,
        input_image_path=payload.input_image_path,
        style=payload.style,
        prompt=payload.prompt,
        output_mode=payload.output_mode,
    )
    db.add(job)
    db.commit()
    db.refresh(job)

    background_tasks.add_task(
        generate_3d_task.delay,
        job_id=job.id,
        input_image_path=job.input_image_path,
        style=job.style,
        prompt=job.prompt,
    )

    return JobResponse.model_validate(job)


@app.get("/jobs/{job_id}", response_model=JobResponse)
def get_job(job_id: str, db: Session = Depends(get_db)):
    job = db.query(GenerationJob).filter(GenerationJob.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return JobResponse.model_validate(job)


@app.get("/files/{file_path:path}")
def serve_file(file_path: str):
    target = _resolve_safe_path(file_path)
    if not target.exists():
        raise HTTPException(status_code=404, detail="File not found")
    return FileResponse(target)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
