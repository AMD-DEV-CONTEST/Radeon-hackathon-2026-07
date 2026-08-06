from __future__ import annotations

import asyncio
import time
from typing import Any, Callable

from .store import ObjectPerceptionStore
from .vocabulary import VocabularyComposer


class ObjectPerceptionCoordinator:
    def __init__(
        self,
        *,
        store: ObjectPerceptionStore,
        vocabulary: VocabularyComposer,
        worker_client,
        model_id: str,
        model_version: str,
        wait_ms: int,
        stale_ms: int,
        review_store,
        now_ms: Callable[[], int] | None = None,
    ) -> None:
        self.store = store
        self.vocabulary = vocabulary
        self.worker_client = worker_client
        self.model_id = model_id
        self.model_version = model_version
        self.wait_ms = max(0, int(wait_ms))
        self.stale_ms = max(1, int(stale_ms))
        self.review_store = review_store
        self.now_ms = now_ms or (lambda: int(time.time() * 1000))
        self._tasks: dict[str, asyncio.Task[None]] = {}
        self._timed_out: set[str] = set()

    async def _store(self, fn, *args, **kwargs) -> Any:
        # The durable job store is a JSON file that is read-modify-written on
        # every transition. Storage can be a slow NTFS-3G mount, so these
        # synchronous writes must never hold the event loop.
        return await asyncio.to_thread(fn, *args, **kwargs)

    async def start(self) -> None:
        jobs = await self._store(
            self.store.recover_incomplete,
            now_ms=self.now_ms(),
            stale_ms=self.stale_ms,
        )
        for job in jobs:
            if job.get("hint_timed_out"):
                self._timed_out.add(str(job["job_id"]))
            self._schedule(job)

    async def stop(self) -> None:
        tasks = list(self._tasks.values())
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        self._tasks.clear()
        await self.worker_client.close()

    async def submit_image(
        self,
        *,
        evidence_id: str,
        image_path: str,
        media_type: str,
        captured_at_ms: int,
        window_id: str,
        boot_session_key: str,
        width: int | None,
        height: int | None,
    ) -> dict[str, Any]:
        vocabulary = self.vocabulary.compose()
        job, created = await self._store(
            self.store.create_job,
            {
                "model_id": self.model_id,
                "model_version": self.model_version,
                "evidence_id": evidence_id,
                "image_path": image_path,
                "media_type": media_type,
                "captured_at_ms": captured_at_ms,
                "window_id": window_id,
                "boot_session_key": boot_session_key,
                "width": width,
                "height": height,
                "vocabulary": vocabulary.to_dict(),
            },
            created_at_ms=self.now_ms(),
        )
        if created or job.get("status") in {"pending", "running"}:
            self._schedule(job)
        return job

    async def hints_for_evidence(
        self,
        evidence_ids: list[str],
        *,
        timeout_ms: int | None = None,
    ) -> dict[str, Any]:
        timeout_seconds = max(0, self.wait_ms if timeout_ms is None else timeout_ms) / 1000
        pending_tasks = []
        for evidence_id in evidence_ids:
            job = await self._store(self.store.job_for_evidence, evidence_id)
            if job and job.get("status") in {"pending", "running"}:
                task = self._tasks.get(str(job["job_id"]))
                if task:
                    pending_tasks.append(task)
        if pending_tasks and timeout_seconds > 0:
            await asyncio.wait(pending_tasks, timeout=timeout_seconds)

        frames = []
        for evidence_id in evidence_ids:
            job = await self._store(self.store.job_for_evidence, evidence_id)
            if job is None:
                frames.append({"evidence_id": evidence_id, "status": "unavailable_failed", "detections": []})
                continue
            status = str(job.get("status"))
            if status in {"pending", "running"}:
                status = "unavailable_timeout"
                self._timed_out.add(str(job["job_id"]))
                await self._store(self.store.mark_hint_timeout, str(job["job_id"]))
            elif status == "failed":
                status = "unavailable_failed"
            frame = {
                "job_id": job["job_id"],
                "evidence_id": evidence_id,
                "status": status,
                "model_id": job.get("model_id"),
                "model_version": job.get("model_version"),
                "vocabulary_hash": (job.get("vocabulary") or {}).get("hash"),
                "detections": job.get("detections") or [],
                "latency_ms": job.get("latency_ms"),
                "error": job.get("error"),
            }
            frames.append(frame)
        aggregate = _aggregate_status([str(item["status"]) for item in frames])
        return {
            "status": aggregate,
            "wait_budget_ms": timeout_ms if timeout_ms is not None else self.wait_ms,
            "frames": frames,
        }

    async def health(self) -> dict[str, Any]:
        try:
            worker = await self.worker_client.health()
        except Exception as exc:
            worker = {"status": "unavailable", "error": f"{type(exc).__name__}: {exc}"}
        return {"worker": worker, "jobs": await self._store(self.store.summary)}

    def _schedule(self, job: dict[str, Any]) -> None:
        job_id = str(job["job_id"])
        existing = self._tasks.get(job_id)
        if existing and not existing.done():
            return
        task = asyncio.create_task(self._dispatch(job_id))
        self._tasks[job_id] = task
        task.add_done_callback(lambda _: self._tasks.pop(job_id, None))

    async def _dispatch(self, job_id: str) -> None:
        job = await self._store(self.store.get_job, job_id)
        if not job or job.get("status") not in {"pending", "running"}:
            return
        if self.now_ms() - int(job.get("created_at_ms") or 0) > self.stale_ms:
            await self._store(self.store.mark_stale, job_id, completed_at_ms=self.now_ms())
            return
        await self._store(self.store.mark_running, job_id, started_at_ms=self.now_ms())
        try:
            vocabulary = dict(job.get("vocabulary") or {})
            result = await self.worker_client.detect(
                {
                    "job_id": job_id,
                    "image_path": job["image_path"],
                    "media_type": job["media_type"],
                    "width": job.get("width"),
                    "height": job.get("height"),
                    "vocabulary": vocabulary.get("prompts") or [],
                    "vocabulary_hash": vocabulary.get("hash"),
                }
            )
            completed_at_ms = self.now_ms()
            if completed_at_ms - int(job.get("created_at_ms") or 0) > self.stale_ms:
                await self._store(self.store.mark_stale, job_id, completed_at_ms=completed_at_ms)
                return
            finished = await self._store(
                self.store.finish_job,
                job_id,
                detections=list(result.get("detections") or []),
                latency_ms=float(result.get("latency_ms") or 0),
                completed_at_ms=completed_at_ms,
                input_width=int(result["input_width"]) if result.get("input_width") else job.get("width"),
                input_height=int(result["input_height"]) if result.get("input_height") else job.get("height"),
                worker_metadata={
                    key: result.get(key)
                    for key in ("model_id", "model_version", "device")
                    if result.get(key) is not None
                },
            )
            if job_id in self._timed_out and finished.get("status") == "ready":
                await self._record_late_candidates(finished)
        except Exception as exc:
            await self._store(
                self.store.fail_job,
                job_id,
                error=f"{type(exc).__name__}: {exc}",
                completed_at_ms=self.now_ms(),
            )

    async def _record_late_candidates(self, job: dict[str, Any]) -> None:
        for detection in job.get("detections") or []:
            await asyncio.to_thread(
                self.review_store.add_object_candidate_observation,
                object_label=detection["label"],
                confidence=detection["confidence"],
                bbox_normalized=detection.get("bbox_normalized"),
                job_id=job["job_id"],
                evidence_id=job["evidence_id"],
                window_id=job.get("window_id"),
                captured_at_ms=job.get("captured_at_ms"),
                vocabulary_hash=(job.get("vocabulary") or {}).get("hash"),
                source="yoloe-26s",
                late=True,
            )


def _aggregate_status(statuses: list[str]) -> str:
    if not statuses:
        return "unavailable_failed"
    if any(item == "ready" for item in statuses):
        return "ready"
    if all(item == "ready_empty" for item in statuses):
        return "ready_empty"
    if any(item == "unavailable_timeout" for item in statuses):
        return "unavailable_timeout"
    if any(item == "stale" for item in statuses):
        return "stale"
    return "unavailable_failed"
