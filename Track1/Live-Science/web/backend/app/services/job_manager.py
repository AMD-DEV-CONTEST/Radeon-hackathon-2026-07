"""Async job queue + worker for animation jobs (single-process, lightweight)."""

from __future__ import annotations

import asyncio
import json
import shutil
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.config import JOBS_DIR, WORKER_COUNT
from app.services import generative_service, phase1_service
from app.storage import JobStore


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


class JobManager:
    def __init__(self, store: JobStore):
        self.store = store
        self.queue: asyncio.Queue[str] = asyncio.Queue()
        self._tasks: list[asyncio.Task] = []

    def start(self) -> None:
        if self._tasks:
            return
        self._mark_stale_failed()
        # Run WORKER_COUNT consumers; each job runs in its own thread.
        self._tasks = [
            asyncio.create_task(self._worker(), name=f"job-worker-{i}")
            for i in range(WORKER_COUNT)
        ]

    async def shutdown(self) -> None:
        """Drain the queue with a timeout, then cancel the worker tasks."""
        try:
            await asyncio.wait_for(self.queue.join(), timeout=15)
        except asyncio.TimeoutError:
            pass
        for task in self._tasks:
            task.cancel()
        if self._tasks:
            await asyncio.gather(*self._tasks, return_exceptions=True)
        self._tasks = []

    def _mark_stale_failed(self) -> None:
        """Mark jobs left in pending/running by a previous process as failed."""
        offset = 0
        while True:
            jobs = self.store.list(limit=200, offset=offset)
            for job in jobs:
                if job.get("status") in ("pending", "running"):
                    self.store.update(job["id"], {
                        "status": "failed",
                        "progress": 1.0,
                        "message": "server restarted before completion",
                        "error": {"type": "StaleJob", "message": "interrupted by server restart"},
                        "updated_at": utcnow(),
                    })
            if len(jobs) < 200:
                break
            offset += len(jobs)

    async def submit(self, job: dict[str, Any]) -> None:
        self.store.create(job)
        await self.queue.put(job["id"])

    async def _worker(self) -> None:
        while True:
            job_id = await self.queue.get()
            try:
                await asyncio.to_thread(self._run, job_id)
            except Exception as exc:  # pragma: no cover - defensive
                self.store.update(job_id, {
                    "status": "failed",
                    "progress": 1.0,
                    "error": {"type": type(exc).__name__, "message": str(exc)},
                    "updated_at": utcnow(),
                })
            finally:
                self.queue.task_done()

    def _set(self, job_id: str, **patch: Any) -> None:
        patch["updated_at"] = utcnow()
        self.store.update(job_id, patch)

    def _run(self, job_id: str) -> None:
        job = self.store.get(job_id)
        if job is None:
            return
        text = job.get("text") or ""
        engine = job.get("engine", "auto")
        self._set(job_id, status="running", progress=0.1, message="started")

        try:
            manifest: dict[str, Any] | None = None
            # Phase 1: DeepSeek program video + bridge route (auto/deterministic/generative)
            self._set(job_id, progress=0.25, message="Phase 1 · generating program video")
            phase1 = phase1_service.run_phase1(job_id, text)
            manifest = phase1.get("manifest") or {}
            route = manifest.get("route")

            needs_model = engine == "generative" or (
                engine == "auto" and route in ("realizable", "hybrid")
            )
            if needs_model:
                self._set(
                    job_id,
                    progress=0.55,
                    message=f"route={route} · FLUX keyframes + LTX video",
                )
                result = generative_service.run_generative(
                    job_id, manifest, text, phase1["run_dir"]
                )
            else:
                self._set(job_id, progress=0.7, message=f"route={route} · using program video")
                result = {
                    "outputs": {
                        "video": phase1["video"],
                        "poster": phase1.get("poster"),
                        "subtitles": phase1.get("subtitles"),
                    },
                    "metrics": {"route": route, "attempts": phase1.get("attempts")},
                }

            result = _normalize_outputs(job_id, result)
            artifacts = _collect_artifacts(job_id, result)
            metrics = dict(result.get("metrics") or {})
            if manifest:
                _write_manifest(job_id, manifest)
                artifacts.setdefault("manifest", f"/api/v1/jobs/{job_id}/files/manifest.json")

            self.store.update(job_id, {
                "status": "completed",
                "progress": 1.0,
                "message": "done",
                "artifacts": artifacts,
                "metrics": metrics,
                "manifest": manifest,
                "error": None,
                "updated_at": utcnow(),
            })
        except Exception as exc:
            self.store.update(job_id, {
                "status": "failed",
                "progress": 1.0,
                "message": "render failed",
                "error": {"type": type(exc).__name__, "message": str(exc)},
                "updated_at": utcnow(),
            })


def _normalize_outputs(job_id: str, result: dict[str, Any]) -> dict[str, Any]:
    """Copy result outputs that live outside the job dir into job_dir root."""
    job_dir = JOBS_DIR / job_id
    job_dir.mkdir(parents=True, exist_ok=True)
    outputs = dict(result.get("outputs") or {})
    for key, value in list(outputs.items()):
        if not isinstance(value, Path):
            continue
        if value.is_file() and not value.parent.resolve().is_relative_to(job_dir.resolve()):
            dest = job_dir / value.name
            shutil.copy2(value, dest)
            outputs[key] = dest
    result["outputs"] = outputs
    return result


def _write_manifest(job_id: str, manifest: dict[str, Any]) -> None:
    (JOBS_DIR / job_id / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def _collect_artifacts(job_id: str, result: dict[str, Any]) -> dict[str, str]:
    """Expose job artifacts as download URLs under /api/v1/jobs/<id>/files/<name>."""
    base = f"/api/v1/jobs/{job_id}/files"
    artifacts: dict[str, str] = {}
    outputs = result.get("outputs") or {}
    for key, path in outputs.items():
        name = Path(str(path)).name
        artifacts[key] = f"{base}/{name}"
    # Canonical `video` alias so the frontend <video> preview resolves.
    if "mp4" in artifacts and "video" not in artifacts:
        artifacts["video"] = artifacts["mp4"]
    return artifacts


def new_job(engine: str, text: str, style: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": uuid.uuid4().hex[:16],
        "engine": engine,
        "status": "pending",
        "progress": 0.0,
        "message": "queued",
        "created_at": utcnow(),
        "updated_at": utcnow(),
        "text": text,
        "style": style,
        "manifest": None,
        "artifacts": {},
        "metrics": {},
        "error": None,
    }
