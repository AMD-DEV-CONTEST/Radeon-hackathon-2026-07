from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable
from uuid import uuid4

from app.core.config import (
    VALIDATED_MODEL_ID,
    VALIDATED_MODEL_REVISION,
    experimental_rocm_enabled,
    rocm_output_root,
)
from app.services.prompts import build_commercial_prompt
from app.services.store import ProjectStore, store

logger = logging.getLogger("brandpilot.rocm")
ACTIVE_STATUSES = {"queued", "loading_model", "preprocessing", "generating", "saving"}
DISCLOSURE = (
    "Generated locally on an AMD Radeon GPU through PyTorch and ROCm. "
    "Experimental output; human review required."
)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def safe_failure(exc: Exception) -> str:
    message = str(exc)[:1000]
    message = re.sub(r"https?://\S+", "[url]", message)
    message = re.sub(r"(?:[A-Za-z]:\\|/)[^\s\"']+", "[path]", message)
    message = re.sub(
        r"(?i)\b(?:bearer|token|secret|password|access[_ -]?code)\b"
        r"\s*[:=]?\s*[A-Za-z0-9._~+/=-]{8,}",
        "[credential]",
        message,
    )
    return f"{type(exc).__name__}: {message[:500]}"


class RocmJobService:
    def __init__(
        self,
        *,
        project_store: ProjectStore = store,
        output_root: Path | None = None,
        pipeline_factory: Callable[[Path], Any] | None = None,
        status_provider: Callable[[], dict[str, Any]] | None = None,
    ):
        self.store = project_store
        self.output_root = (output_root or rocm_output_root()).resolve()
        self.pipeline_factory = pipeline_factory or self._default_pipeline_factory
        self.status_provider = status_provider or self._default_status_provider
        self._jobs: dict[str, dict[str, Any]] = {}
        self._state_lock = threading.Lock()
        self._pipeline_lock = threading.Lock()
        self._executor: ThreadPoolExecutor | None = None
        self._pipeline: Any | None = None

    @staticmethod
    def _default_pipeline_factory(output_dir: Path) -> Any:
        repository_root = Path(__file__).resolve().parents[3]
        if str(repository_root) not in sys.path:
            sys.path.insert(0, str(repository_root))
        from inference.rocm_pipeline import RocmCampaignPipeline, RocmPipelineConfig

        cache = os.getenv("MODEL_CACHE_DIR", "").strip()
        model_id = os.getenv("MODEL_ID", "").strip() or VALIDATED_MODEL_ID
        revision = (
            os.getenv("MODEL_REVISION", "").strip() or VALIDATED_MODEL_REVISION
        )
        if model_id != VALIDATED_MODEL_ID or revision != VALIDATED_MODEL_REVISION:
            raise RuntimeError(
                "Experimental mode requires the validated SDXL model and exact revision."
            )
        config = RocmPipelineConfig(
            model_id=model_id,
            model_revision=revision,
            model_cache_dir=Path(cache).expanduser() if cache else None,
            output_dir=output_dir,
            device=os.getenv("DEVICE", "cuda"),
            dtype=os.getenv("DTYPE", "float16"),
            local_files_only=os.getenv("MODEL_LOCAL_FILES_ONLY", "true").lower()
            not in {"0", "false", "no"},
            ip_adapter_model_id=None,
            controlnet_model_id=None,
        )
        return RocmCampaignPipeline(config)

    @staticmethod
    def _default_status_provider() -> dict[str, Any]:
        try:
            import torch
        except (ImportError, OSError) as exc:
            return {
                "gpu_connected": False,
                "rocm_available": False,
                "device": None,
                "pytorch_version": None,
                "hip_version": None,
                "message": f"ROCm PyTorch unavailable: {type(exc).__name__}",
            }
        hip = getattr(getattr(torch, "version", None), "hip", None)
        available = bool(torch.cuda.is_available() and torch.cuda.device_count() > 0)
        device = torch.cuda.get_device_name(0) if available else None
        is_amd = bool(device and ("amd" in device.lower() or "radeon" in device.lower()))
        confirmed = bool(hip and available and is_amd)
        return {
            "gpu_connected": confirmed,
            "rocm_available": confirmed,
            "device": device if confirmed else None,
            "pytorch_version": str(getattr(torch, "__version__", "")) or None,
            "hip_version": str(hip) if hip else None,
            "message": "AMD Radeon HIP device verified." if confirmed else "AMD Radeon HIP device unavailable.",
        }

    def status(self) -> dict[str, Any]:
        if not experimental_rocm_enabled():
            return {
                "enabled": False,
                "gpu_connected": False,
                "rocm_available": False,
                "inference_mode": "mock",
                "device": None,
                "model_id": VALIDATED_MODEL_ID,
                "model_revision": VALIDATED_MODEL_REVISION,
                "model_loaded": False,
                "message": "Experimental ROCm mode is disabled.",
            }
        info = self.status_provider()
        return {
            "enabled": True,
            **info,
            "inference_mode": "rocm_experimental",
            "model_id": VALIDATED_MODEL_ID,
            "model_revision": VALIDATED_MODEL_REVISION,
            "model_loaded": self._pipeline is not None,
        }

    def submit(
        self, project: dict[str, Any], creative_style: str, output_format: str, seed: int
    ) -> dict[str, Any]:
        with self._state_lock:
            if any(job["status"] in ACTIVE_STATUSES for job in self._jobs.values()):
                raise RuntimeError("Only one experimental GPU generation job may be active.")
            job_id = str(uuid4())
            job = {
                "job_id": job_id,
                "project_id": project["project_id"],
                "status": "queued",
                "stage": "queued",
                "current_step": None,
                "total_steps": None,
                "created_at": utc_now(),
                "started_at": None,
                "completed_at": None,
                "failure": None,
                "result": None,
                "output_available": False,
                "model_id": VALIDATED_MODEL_ID,
                "model_revision": VALIDATED_MODEL_REVISION,
                "inference_mode": "rocm_experimental",
                "gpu_confirmation": False,
                "_creative_style": creative_style,
                "_output_format": output_format,
                "_seed": seed,
            }
            self._jobs[job_id] = job
            project["status"] = "generating"
            project["generation_state"] = "queued"
            project["active_rocm_job_id"] = job_id
            project["last_generation_failure"] = None
            self.store.save(project)
            if self._executor is None:
                self._executor = ThreadPoolExecutor(
                    max_workers=1, thread_name_prefix="rocm-job"
                )
            self._executor.submit(self._run, job_id)
            return self.public_job(job)

    def get(self, job_id: str) -> dict[str, Any]:
        with self._state_lock:
            job = self._jobs.get(job_id)
            if job is None:
                raise KeyError(job_id)
            return self.public_job(job)

    def public_job(self, job: dict[str, Any]) -> dict[str, Any]:
        return {
            key: deepcopy(value)
            for key, value in job.items()
            if not key.startswith("_")
        }

    def _update(self, job_id: str, **values: Any) -> None:
        with self._state_lock:
            self._jobs[job_id].update(values)

    def _persist_stage(self, job_id: str, stage: str) -> None:
        with self._state_lock:
            project_id = self._jobs[job_id]["project_id"]
        project = self.store.get(project_id)
        project["status"] = "generating"
        project["generation_state"] = stage
        project["active_rocm_job_id"] = job_id
        self.store.save(project)

    @staticmethod
    def _release_gpu_cache() -> None:
        try:
            import torch

            if torch.cuda.is_available():
                torch.cuda.empty_cache()
        except (ImportError, OSError, AttributeError, RuntimeError):
            return

    def _run(self, job_id: str) -> None:
        started = time.perf_counter()
        self._update(job_id, status="loading_model", stage="loading_model", started_at=utc_now())
        self._persist_stage(job_id, "loading_model")
        try:
            with self._state_lock:
                job = dict(self._jobs[job_id])
            project = self.store.get(job["project_id"])
            asset = project.get("asset")
            if not asset:
                raise RuntimeError("Uploaded product asset is unavailable.")
            input_path = (
                self.store.projects
                / project["project_id"]
                / "assets"
                / asset["storage_name"]
            ).resolve()
            expected_assets = (
                self.store.projects / project["project_id"] / "assets"
            ).resolve()
            if input_path.parent != expected_assets or not input_path.is_file():
                raise RuntimeError("Uploaded product asset is unavailable.")

            result_id = str(uuid4())
            project_output = (self.output_root / project["project_id"]).resolve()
            if project_output.parent != self.output_root:
                raise RuntimeError("Unsafe output location.")
            project_output.mkdir(parents=True, exist_ok=True)
            output_path = project_output / f"{result_id}.png"

            model_load_seconds = 0.0
            with self._pipeline_lock:
                if self._pipeline is None:
                    pipeline = self.pipeline_factory(project_output)
                    load_started = time.perf_counter()
                    pipeline.load_model()
                    model_load_seconds = time.perf_counter() - load_started
                    self._pipeline = pipeline
                status = self.status_provider()
                if not status.get("gpu_connected") or not status.get("rocm_available"):
                    raise RuntimeError("AMD Radeon HIP verification failed; CPU execution refused.")

                self._update(job_id, status="preprocessing", stage="preprocessing")
                self._persist_stage(job_id, "preprocessing")
                prompt, negative_prompt = build_commercial_prompt(
                    project["configuration"],
                    job["_creative_style"],
                    job["_output_format"],
                )

                def on_step(current: int, total: int) -> None:
                    self._update(
                        job_id,
                        status="generating",
                        stage="generating",
                        current_step=current,
                        total_steps=total,
                    )

                self._update(job_id, status="generating", stage="generating")
                self._persist_stage(job_id, "generating")
                generated = self._pipeline.generate_ad_image(
                    input_path,
                    {"prompt": prompt, "negative_prompt": negative_prompt},
                    job["_output_format"],
                    output_path=output_path,
                    progress_callback=on_step,
                    seed=job["_seed"],
                )

            self._update(job_id, status="saving", stage="saving")
            self._persist_stage(job_id, "saving")
            total_seconds = time.perf_counter() - started
            result = {
                "result_id": result_id,
                "job_id": job_id,
                "project_id": project["project_id"],
                "mode": "rocm",
                "experimental": True,
                "gpu_connected": True,
                "rocm_available": True,
                "model_id": generated["model_id"],
                "model_revision": generated["model_revision"],
                "pipeline_class": generated["pipeline_class"],
                "creative_style": job["_creative_style"],
                "style": job["_creative_style"],
                "output_format": job["_output_format"],
                "image_url": f"/experimental/rocm/jobs/{job_id}/output",
                "prompt": prompt,
                "negative_prompt": negative_prompt,
                "width": generated["width"],
                "height": generated["height"],
                "steps": generated["steps"],
                "strength": generated["strength"],
                "guidance_scale": generated["guidance_scale"],
                "seed": generated["seed"],
                "model_load_seconds": model_load_seconds,
                "generation_seconds": generated["generation_seconds"],
                "total_seconds": total_seconds,
                "peak_allocated_vram_bytes": generated[
                    "peak_allocated_gpu_memory_bytes"
                ],
                "peak_reserved_vram_bytes": generated[
                    "peak_reserved_gpu_memory_bytes"
                ],
                "gpu_device_name": generated["gpu_device_name"],
                "pytorch_version": generated["pytorch_version"],
                "hip_rocm_version": generated["hip_rocm_version"],
                "input_sha256": sha256_file(input_path),
                "output_sha256": sha256_file(output_path),
                "generated_at": utc_now(),
                "disclosure": DISCLOSURE,
                "human_review_status": "pending",
                "review_note": None,
                "headline": "",
                "caption": "",
                "call_to_action": "",
                "created_at": utc_now(),
                "artifact_id": output_path.name,
            }
            metadata_path = project_output / f"{result_id}.json"
            metadata_path.write_text(
                json.dumps(
                    {key: value for key, value in result.items() if not key.startswith("_")},
                    indent=2,
                ),
                encoding="utf-8",
            )
            project["results"] = [
                item for item in project.get("results", []) if item.get("mode") != "rocm"
            ] + [result]
            project["status"] = "completed"
            project["generation_state"] = "completed"
            project["active_rocm_job_id"] = None
            project["last_generation_failure"] = None
            self.store.save(project)
            public_result = {
                key: value for key, value in result.items() if not key.startswith("_")
            }
            self._update(
                job_id,
                status="completed",
                stage="completed",
                completed_at=utc_now(),
                result=public_result,
                output_available=True,
                gpu_confirmation=True,
                current_step=generated["steps"],
                total_steps=generated["steps"],
                _output_path=str(output_path),
            )
        except Exception as exc:
            failure = safe_failure(exc)
            logger.error(
                "Experimental ROCm job failed without fallback: %s", type(exc).__name__
            )
            try:
                with self._state_lock:
                    project_id = self._jobs[job_id]["project_id"]
                project = self.store.get(project_id)
                project["status"] = "failed"
                project["generation_state"] = "failed"
                project["active_rocm_job_id"] = None
                project["last_generation_failure"] = failure
                self.store.save(project)
            except Exception:
                logger.error("Failed to persist sanitised experimental failure state.")
            self._release_gpu_cache()
            self._update(
                job_id,
                status="failed",
                stage="failed",
                completed_at=utc_now(),
                failure=failure,
                output_available=False,
            )

    def output_path(self, job_id: str) -> Path:
        with self._state_lock:
            job = self._jobs.get(job_id)
            if not job or job["status"] != "completed" or not job.get("_output_path"):
                raise KeyError(job_id)
            path = Path(job["_output_path"]).resolve()
            expected = (self.output_root / job["project_id"]).resolve()
            if path.parent != expected or path.suffix.lower() != ".png" or not path.is_file():
                raise ValueError("Unsafe or unavailable output artifact.")
            return path

    def shutdown(self) -> None:
        if self._executor is not None:
            self._executor.shutdown(wait=True, cancel_futures=False)
            self._executor = None


rocm_jobs = RocmJobService()
