import asyncio
import uuid
import httpx
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Optional, Dict, Any, List

from app.core import dimensions, motion
from app.core.config import settings
from app.core.gpu_accelerator import LocalAccelerator


class JobStatus(str, Enum):
    QUEUED = "queued"
    SUBMITTED = "submitted"
    RUNNING = "running"
    DOWNLOADING = "downloading"
    DONE = "done"
    FAILED = "failed"


class VideoGenerationJob:
    def __init__(self, *, id: str, source_image_path: Path, full_prompt: str,
                 width: int, height: int, frame_count: int, frame_rate: int,
                 seed: int, preset_id: str, motion_intensity: float = 1.0):
        self.id = id
        self.source_image_path = source_image_path
        self.full_prompt = full_prompt
        self.width = width
        self.height = height
        self.frame_count = frame_count
        self.frame_rate = frame_rate
        self.seed = seed
        self.preset_id = preset_id
        self.motion_intensity = motion_intensity

        self.status = JobStatus.QUEUED
        self.progress_note = ""
        self.error_message: Optional[str] = None
        self.result_video_path: Optional[Path] = None
        self.job_id: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "status": self.status.value,
            "progress_note": self.progress_note,
            "error_message": self.error_message,
            "preset_id": self.preset_id,
            "width": self.width,
            "height": self.height,
            "frame_count": self.frame_count,
            "frame_rate": self.frame_rate,
            "seed": self.seed,
            "motion_intensity": self.motion_intensity,
            "result_video_path": str(self.result_video_path) if self.result_video_path else None,
        }


class ReplicateClient:
    def __init__(self, local_accelerator: Optional[LocalAccelerator] = None):
        self.local_accelerator = local_accelerator or LocalAccelerator()
        self.api_token = settings.REPLICATE_API_TOKEN
        self.use_local = settings.USE_LOCAL_GPU or settings.VIDEO_GENERATION_MODE == "local"

        try:
            import httpx
            self.http_client = httpx
            self.api_available = True
        except ImportError:
            self.api_available = False
            print("WARNING: httpx not available - falling back to local execution")

    async def submit_job(self, job: VideoGenerationJob) -> VideoGenerationJob:
        try:
            if self.use_local and self.local_accelerator.is_gpu_available():
                return await self._execute_locally(job)
            elif self.api_token and self.api_available and settings.VIDEO_GENERATION_MODE != "local":
                return await self._execute_via_replicate(job)
            else:
                return await self._execute_locally(job)
        except Exception as e:
            print(f"Job submission failed: {e}")
            job.status = JobStatus.FAILED
            job.error_message = str(e)
            await self._cleanup_job(job)
            return job

    async def _execute_via_replicate(self, job: VideoGenerationJob) -> VideoGenerationJob:
        predict_url = f"{settings.replicate_api_url}/predictions"
        headers = {
            "Authorization": f"Token {self.api_token}",
            "Content-Type": "application/json",
        }

        payload = {
            "input": {
                "image": self._prepare_input_image(job),
                "prompt": job.full_prompt,
                "width": job.width,
                "height": job.height,
                "num_frames": job.frame_count,
                "fps": job.frame_rate,
                "seed": job.seed,
            }
        }

        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(predict_url, json=payload, headers=headers)
            if resp.status_code not in (200, 201):
                raise Exception(f"Replicate rejected submission ({resp.status_code}): {resp.text}")
            prediction = resp.json()
            job.job_id = prediction.get("id")

        while job.status in [JobStatus.QUEUED, JobStatus.SUBMITTED, JobStatus.RUNNING]:
            await asyncio.sleep(2.0)
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.get(
                    f"{settings.replicate_api_url}/predictions/{job.job_id}",
                    headers=headers
                )
                if resp.status_code != 200:
                    raise Exception(f"Prediction lookup failed: {resp.text}")
                prediction = resp.json()
                if prediction.get("status") == "succeeded":
                    job.status = JobStatus.DOWNLOADING
                    job.result_url = prediction.get("output", [None])[0]
                    break
                elif prediction.get("status") == "failed":
                    job.status = JobStatus.FAILED
                    job.error_message = prediction.get("error")
                    break
                job.status = JobStatus.RUNNING
                job.progress_note = prediction.get("progress_note", "Working...")

        if job.status == JobStatus.DOWNLOADING and getattr(job, "result_url", None):
            await self._download_video(job)
        return job

    async def _execute_locally(self, job: VideoGenerationJob) -> VideoGenerationJob:
        job.status = JobStatus.RUNNING
        job.progress_note = f"Running on {self.local_accelerator.get_backend()} backend..."
        try:
            from app.core.video_pipeline import VideoGenerationPipeline
            pipeline = VideoGenerationPipeline(
                device=self.local_accelerator.get_device(),
                backend=self.local_accelerator.get_backend(),
                fp16=self.local_accelerator.fp16_support,
            )
            result_path = await pipeline.generate_video(
                source_image_path=job.source_image_path,
                prompt=job.full_prompt,
                width=job.width,
                height=job.height,
                num_frames=job.frame_count,
                fps=job.frame_rate,
                seed=job.seed,
            )
            job.status = JobStatus.DONE
            job.result_video_path = result_path
        except Exception as e:
            job.status = JobStatus.FAILED
            job.error_message = str(e)
        finally:
            await self._cleanup_local_resources()
        return job

    async def _download_video(self, job: VideoGenerationJob):
        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.get(job.result_url)
            if resp.status_code != 200:
                raise Exception(f"Video download failed: {resp.status_code}")
            job.status = JobStatus.DOWNLOADING
            video_path = settings.DATA_DIR / "videos" / f"{job.id}.mp4"
            video_path.parent.mkdir(parents=True, exist_ok=True)
            with open(video_path, "wb") as f:
                f.write(resp.content)
            job.result_video_path = video_path

    def _prepare_input_image(self, job: VideoGenerationJob) -> str:
        image_data = Image.open(job.source_image_path)
        if image_data.mode != "RGB":
            image_data = image_data.convert("RGB")
        max_dim = max(job.width, job.height)
        if max(image_data.size) > max_dim:
            ratio = max_dim / max(image_data.size)
            new_size = (int(image_data.size[0] * ratio), int(image_data.size[1] * ratio))
            image_data = image_data.resize(new_size, Image.Resampling.LANCZOS)
        import base64, io
        buffer = io.BytesIO()
        image_data.save(buffer, format="JPEG", quality=95)
        img_str = base64.b64encode(buffer.getvalue()).decode()
        return f"data:image/jpeg;base64,{img_str}"

    async def _cleanup_job(self, job: VideoGenerationJob):
        try:
            if job.source_image_path and job.source_image_path.exists():
                job.source_image_path.unlink()
        except Exception:
            pass

    async def _cleanup_local_resources(self):
        pass


class JobQueue:
    def __init__(self):
        self._jobs: Dict[str, VideoGenerationJob] = {}
        self._next_id = 1
        self._client: Optional[ReplicateClient] = None
        self._running = False

    def start(self):
        self._client = ReplicateClient(
            local_accelerator=LocalAccelerator() if settings.USE_LOCAL_GPU or settings.VIDEO_GENERATION_MODE == "local" else None
        )
        self._running = True
        print(f"JobQueue started. Mode={settings.VIDEO_GENERATION_MODE} | Local={settings.USE_LOCAL_GPU}")

    def submit(self, *, source_image_path: Path, full_prompt: str,
               width: int, height: int, frame_count: int, frame_rate: int,
               seed: int, preset_id: str, motion_intensity: float = 1.0) -> VideoGenerationJob:
        job_id = str(uuid.uuid4())
        job = VideoGenerationJob(
            id=job_id,
            source_image_path=source_image_path,
            full_prompt=full_prompt,
            width=width,
            height=height,
            frame_count=frame_count,
            frame_rate=frame_rate,
            seed=seed,
            preset_id=preset_id,
            motion_intensity=motion_intensity,
        )
        self._jobs[job_id] = job
        asyncio.get_event_loop().create_task(self._process(job))
        return job

    def get(self, job_id: str) -> Optional[VideoGenerationJob]:
        return self._jobs.get(job_id)

    def list_all(self) -> List[VideoGenerationJob]:
        return list(self._jobs.values())

    async def _process(self, job: VideoGenerationJob):
        if not self._client:
            self._client = ReplicateClient()
        await self._client.submit_job(job)


job_queue = JobQueue()
