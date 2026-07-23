"""
FrameForge backend -- FastAPI app.

Routes:
  GET  /api/settings               -> current settings (token status, model)
  POST /api/settings               -> update settings at runtime (token, model)
  GET  /api/presets                -> list of motion presets for the picker UI
  POST /api/jobs                   -> upload image + submit a render job
  POST /api/jobs/draw              -> submit from canvas
  GET  /api/jobs                   -> list all jobs (most recent first)
  GET  /api/jobs/{job_id}          -> single job status
  GET  /api/jobs/{job_id}/video    -> download/stream the finished video
  GET  /api/jobs/{job_id}/thumb    -> download/stream a thumbnail
"""

import random
import base64
import shutil
import uuid
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel

from app.core import dimensions, motion
from app.core.config import settings
from app.core.gpu_accelerator import LocalAccelerator
from app.core.job_queue import job_queue, JobStatus

app = FastAPI(title="FrameForge", version="0.2.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
async def on_startup():
    settings.ensure_dirs()
    job_queue.start()


# --- Settings endpoints (API key / model) ---

class SettingsUpdate(BaseModel):
    api_token: Optional[str] = None
    model: Optional[str] = None


@app.get("/api/settings")
async def get_settings():
    token = settings.REPLICATE_API_TOKEN
    return {
        "api_token_configured": token is not None and len(token) > 0,
        "api_token_preview": f"{token[:4]}...{token[-4:]}" if token and len(token) > 8 else ("set" if token else None),
        "model": settings.REPLICATE_MODEL,
        "timeout_seconds": settings.REPLICATE_TIMEOUT_SECONDS,
        "video_generation_mode": settings.VIDEO_GENERATION_MODE,
        "use_local_gpu": settings.USE_LOCAL_GPU,
    }


@app.get("/api/gpu")
async def get_gpu_info():
    accel = LocalAccelerator()
    return {
        "backend": accel.get_backend(),
        "device": accel.get_device(),
        "is_gpu_available": accel.is_gpu_available(),
        "fp16_support": accel.fp16_support,
        "device_name": _gpu_name(accel.get_backend()),
    }


def _gpu_name(backend: str) -> str:
    if backend == "cuda":
        import torch
        return torch.cuda.get_device_name() if torch.cuda.is_available() else "NVIDIA GPU"
    if backend == "rocm":
        import torch
        return torch.cuda.get_device_name() if torch.cuda.is_available() else "AMD GPU (ROCm)"
    if backend == "directml":
        return "AMD GPU (DirectML)"
    if backend == "mps":
        return "Apple Silicon"
    return "CPU"


@app.post("/api/settings")
async def update_settings(body: SettingsUpdate):
    if body.api_token is not None:
        settings.REPLICATE_API_TOKEN = body.api_token.strip() or None
    if body.model is not None:
        settings.REPLICATE_MODEL = body.model.strip()
    token = settings.REPLICATE_API_TOKEN
    return {
        "api_token_configured": token is not None and len(token) > 0,
        "api_token_preview": f"{token[:4]}...{token[-4:]}" if token and len(token) > 8 else ("set" if token else None),
        "model": settings.REPLICATE_MODEL,
    }


@app.get("/api/presets")
async def get_presets():
    return {"presets": motion.list_presets()}


@app.post("/api/jobs")
async def create_job(
    image: UploadFile = File(...),
    preset_id: str = Form(...),
    subject_prompt: str = Form(...),
    custom_motion_prompt: str = Form(""),
    width: int = Form(768),
    height: int = Form(512),
    seconds: float = Form(4.0),
    frame_rate: int = Form(24),
    seed: int = Form(-1),
    motion_intensity: float = Form(1.0),
):
    # --- Validate preset ---
    valid_preset_ids = {p["id"] for p in motion.list_presets()}
    if preset_id not in valid_preset_ids:
        raise HTTPException(400, f"Unknown preset_id '{preset_id}'. Valid options: {sorted(valid_preset_ids)}")

    # --- Save uploaded image to disk ---
    upload_id = str(uuid.uuid4())
    suffix = Path(image.filename or "upload.png").suffix or ".png"
    saved_path = settings.DATA_DIR / "uploads" / f"{upload_id}{suffix}"
    with open(saved_path, "wb") as f:
        shutil.copyfileobj(image.file, f)

    # --- Dimension snapping (LTX Video requires 32n+1 dimensions) ---
    pipeline_config = {"max_short_side": 768, "tier_name": "Local GPU"}
    snapped = dimensions.snap_dimensions(
        pipeline_config=pipeline_config,
        requested_width=width,
        requested_height=height,
        requested_seconds=seconds,
        frame_rate=frame_rate,
    )

    # --- Motion preset -> prompt ---
    try:
        motion_result = motion.build_motion_prompt(
            preset_id=preset_id,
            subject_prompt=subject_prompt,
            custom_motion_prompt=custom_motion_prompt,
        )
    except KeyError:
        raise HTTPException(400, f"Unknown preset_id '{preset_id}'")

    actual_seed = seed if seed >= 0 else random.randint(0, 2**31 - 1)

    job = job_queue.submit(
        source_image_path=saved_path,
        full_prompt=motion_result["full_prompt"],
        width=snapped["width"],
        height=snapped["height"],
        frame_count=snapped["frame_count"],
        frame_rate=frame_rate,
        seed=actual_seed,
        preset_id=preset_id,
        motion_intensity=motion_intensity,
    )

    return {
        "job": job.to_dict(),
        "dimension_adjustment_note": snapped["adjustment_note"],
    }


@app.get("/api/jobs")
async def list_jobs():
    jobs = job_queue.list_all()
    return {
        "jobs": [
            {
                "id": j.id,
                "status": j.status.value,
                "progress_note": j.progress_note,
                "error_message": j.error_message,
                "preset_id": j.preset_id,
                "width": j.width,
                "height": j.height,
                "frame_count": j.frame_count,
                "frame_rate": j.frame_rate,
                "seed": j.seed,
                "result_video_path": str(j.result_video_path) if j.result_video_path else None,
            }
            for j in jobs
        ]
    }


@app.get("/api/jobs/{job_id}")
async def get_job(job_id: str):
    job = job_queue.get(job_id)
    if job is None:
        raise HTTPException(404, "Job not found")
    return {
        "id": job.id,
        "status": job.status.value,
        "progress_note": job.progress_note,
        "error_message": job.error_message,
        "preset_id": job.preset_id,
        "width": job.width,
        "height": job.height,
        "frame_count": job.frame_count,
        "frame_rate": job.frame_rate,
        "seed": job.seed,
        "result_video_path": str(job.result_video_path) if job.result_video_path else None,
    }


@app.get("/api/jobs/{job_id}/video")
async def get_job_video(job_id: str):
    job = job_queue.get(job_id)
    if job is None:
        raise HTTPException(404, "Job not found")
    if job.status != JobStatus.DONE or job.result_video_path is None:
        raise HTTPException(409, f"Job is not finished yet (status: {job.status.value})")
    if not job.result_video_path.exists():
        raise HTTPException(410, "Result file is no longer available on disk")
    return FileResponse(job.result_video_path, media_type="video/mp4", filename=f"frameforge_{job_id}.mp4")


@app.get("/api/jobs/{job_id}/thumb")
async def get_job_thumb(job_id: str):
    job = job_queue.get(job_id)
    if job is None:
        raise HTTPException(404, "Job not found")
    if job.status != JobStatus.DONE or job.result_video_path is None:
        raise HTTPException(409, f"Job is not finished yet (status: {job.status.value})")
    if not job.result_video_path.exists():
        raise HTTPException(410, "Result file is no longer available on disk")

    thumb = _extract_thumb(job.result_video_path)
    if thumb is None:
        raise HTTPException(500, "Thumbnail extraction failed")
    return FileResponse(thumb, media_type="image/jpeg", filename=f"frameforge_{job_id}.jpg")


def _extract_thumb(video_path: Path) -> Optional[Path]:
    try:
        import subprocess
        thumb_path = video_path.with_suffix(".jpg")
        subprocess.run(
            [
                "ffmpeg",
                "-y",
                "-i",
                str(video_path),
                "-ss",
                "00:00:00.5",
                "-vframes",
                "1",
                "-q:v",
                "2",
                str(thumb_path),
            ],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        return thumb_path if thumb_path.exists() else None
    except FileNotFoundError:
        return None
    except subprocess.CalledProcessError:
        return None


class DrawJobRequest(BaseModel):
    canvas_data_uri: str
    preset_id: str
    subject_prompt: str
    custom_motion_prompt: str = ""
    width: int = 768
    height: int = 512
    seconds: float = 4.0
    frame_rate: int = 24
    seed: int = -1
    motion_intensity: float = 1.0


@app.post("/api/jobs/draw")
async def create_draw_job(body: DrawJobRequest):
    valid_preset_ids = {p["id"] for p in motion.list_presets()}
    if body.preset_id not in valid_preset_ids:
        raise HTTPException(400, f"Unknown preset_id '{body.preset_id}'. Valid options: {sorted(valid_preset_ids)}")

    data_uri = body.canvas_data_uri
    if "," in data_uri:
        header, b64data = data_uri.split(",", 1)
    else:
        header, b64data = "", data_uri

    try:
        img_bytes = base64.b64decode(b64data)
    except Exception:
        raise HTTPException(400, "Invalid base64 canvas data")

    upload_id = str(uuid.uuid4())
    saved_path = settings.DATA_DIR / "uploads" / f"{upload_id}.png"
    with open(saved_path, "wb") as f:
        f.write(img_bytes)

    pipeline_config = {"max_short_side": 768, "tier_name": "Local GPU"}
    snapped = dimensions.snap_dimensions(
        pipeline_config=pipeline_config,
        requested_width=body.width,
        requested_height=body.height,
        requested_seconds=body.seconds,
        frame_rate=body.frame_rate,
    )

    try:
        motion_result = motion.build_motion_prompt(
            preset_id=body.preset_id,
            subject_prompt=body.subject_prompt,
            custom_motion_prompt=body.custom_motion_prompt,
        )
    except KeyError:
        raise HTTPException(400, f"Unknown preset_id '{body.preset_id}'")

    actual_seed = body.seed if body.seed >= 0 else random.randint(0, 2**31 - 1)

    job = job_queue.submit(
        source_image_path=saved_path,
        full_prompt=motion_result["full_prompt"],
        width=snapped["width"],
        height=snapped["height"],
        frame_count=snapped["frame_count"],
        frame_rate=body.frame_rate,
        seed=actual_seed,
        preset_id=body.preset_id,
        motion_intensity=body.motion_intensity,
    )

    return {
        "job": job.to_dict(),
        "dimension_adjustment_note": snapped["adjustment_note"],
    }


@app.get("/api/health")
async def health():
    return {"status": "ok"}
