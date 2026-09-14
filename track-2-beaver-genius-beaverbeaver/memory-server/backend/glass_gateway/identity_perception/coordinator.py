from __future__ import annotations

import asyncio
import time
from typing import Any, Callable

import httpx

from .store import IdentityJobStore


class IdentityCoordinator:
    """Gateway-side durable dispatcher; never exposes worker embeddings."""

    def __init__(
        self,
        *,
        store: IdentityJobStore,
        worker_client: Any,
        model_revision: str,
        config_version: str,
        candidate_processor: Any | None = None,
        retry_seconds: float = 5.0,
        now_ms: Callable[[], int] | None = None,
    ) -> None:
        self.store = store
        self.worker_client = worker_client
        self.model_revision = model_revision
        self.config_version = config_version
        self.candidate_processor = candidate_processor
        self.retry_seconds = max(0.05, float(retry_seconds))
        self.now_ms = now_ms or (lambda: int(time.time() * 1000))
        self._tasks: dict[str, asyncio.Task[None]] = {}
        # The production worker is configured for one inference at a time. Keep
        # dispatch and candidate projection in the same FIFO critical section so
        # a backlog cannot reach the online candidate directory in arbitrary HTTP
        # completion order and change otherwise identical clustering results.
        self._dispatch_lock = asyncio.Lock()
        self._candidate_error: str | None = None
        self._stop_event = asyncio.Event()

    async def _store(self, fn, *args, **kwargs) -> Any:
        # The durable job store is a JSON file that is read-modify-written on
        # every transition. Storage can be a slow NTFS-3G mount, so these
        # synchronous writes must never hold the event loop.
        return await asyncio.to_thread(fn, *args, **kwargs)

    async def start(self) -> None:
        self._stop_event.clear()
        if self.candidate_processor is not None:
            try:
                await asyncio.to_thread(self.candidate_processor.recover_unassigned)
                self._candidate_error = None
            except Exception as exc:
                self._candidate_error = f"{type(exc).__name__}: {exc}"[:500]
        jobs = await self._store(self.store.recover_incomplete)
        for job in jobs:
            self._schedule(str(job["job_id"]))

    async def stop(self) -> None:
        # Let freshly scheduled work enter dispatch before signalling retry
        # sleepers to exit. This preserves graceful completion for in-flight
        # local inference while still making an offline-worker shutdown fast.
        await asyncio.sleep(0)
        self._stop_event.set()
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
        boot_session_id: str,
        window_id: str,
    ) -> dict[str, Any]:
        job, created = await self._store(
            self.store.create_job,
            {
                "evidence_id": evidence_id,
                "image_path": image_path,
                "media_type": media_type,
                "captured_at_ms": captured_at_ms,
                "boot_session_id": boot_session_id,
                "window_id": window_id,
                "model_revision": self.model_revision,
                "config_version": self.config_version,
            },
            created_at_ms=self.now_ms(),
        )
        if created or job.get("status") in {"pending", "running"}:
            self._schedule(str(job["job_id"]))
        return job

    async def health(self) -> dict[str, Any]:
        try:
            worker = await self.worker_client.health()
        except Exception as exc:
            worker = {
                "status": "unavailable",
                "error": f"{type(exc).__name__}: {exc}"[:500],
            }
        candidate_summary = None
        if self.candidate_processor is not None:
            try:
                candidate_summary = await asyncio.to_thread(self.candidate_processor.summary)
            except Exception as exc:
                self._candidate_error = f"{type(exc).__name__}: {exc}"[:500]
        return {
            "worker": worker,
            "jobs": await self._store(self.store.summary),
            "candidates": candidate_summary,
            "candidate_error": self._candidate_error,
            "model_revision": self.model_revision,
            "config_version": self.config_version,
        }

    def _schedule(self, job_id: str) -> None:
        current = self._tasks.get(job_id)
        if current and not current.done():
            return
        task = asyncio.create_task(self._dispatch(job_id))
        self._tasks[job_id] = task
        task.add_done_callback(lambda _: self._tasks.pop(job_id, None))

    async def _dispatch(self, job_id: str) -> None:
        while not self._stop_event.is_set():
            job = await self._store(self.store.get_job, job_id, internal=True)
            if not job or job.get("status") not in {"pending", "running"}:
                return
            await self._store(self.store.mark_running, job_id, started_at_ms=self.now_ms())
            try:
                async with self._dispatch_lock:
                    result = await self.worker_client.recognize(
                        {
                            "job_id": job_id,
                            "evidence_id": job["evidence_id"],
                            "image_path": job["image_path"],
                            "media_type": job["media_type"],
                            "expected_model_revision": job["model_revision"],
                            "expected_config_version": job["config_version"],
                        }
                    )
                    if (
                        str(result.get("model_revision")) != str(job["model_revision"])
                        or str(result.get("config_version"))
                        != str(job["config_version"])
                    ):
                        await self._store(
                            self.store.fail_job,
                            job_id,
                            status="stale_model_revision",
                            error="worker result revision differs from durable job",
                            completed_at_ms=self.now_ms(),
                        )
                        return
                    await self._store(
                        self.store.finish_job,
                        job_id,
                        observations=[
                            item
                            for item in result.get("observations") or []
                            if isinstance(item, dict)
                        ],
                        input_width=int(result["input_width"]),
                        input_height=int(result["input_height"]),
                        latency_ms=float(result.get("latency_ms") or 0.0),
                        completed_at_ms=self.now_ms(),
                        worker_metadata={
                            key: result.get(key)
                            for key in (
                                "model_id",
                                "model_revision",
                                "config_version",
                                "device",
                            )
                            if result.get(key) is not None
                        },
                    )
                    if self.candidate_processor is not None:
                        try:
                            await asyncio.to_thread(self.candidate_processor.process_job, job_id)
                            self._candidate_error = None
                        except Exception as exc:
                            # Candidate projection is recoverable and must not turn a
                            # successful face inference into a failed evidence job.
                            self._candidate_error = f"{type(exc).__name__}: {exc}"[:500]
                return
            except httpx.TransportError as exc:
                await self._store(
                    self.store.defer_job,
                    job_id,
                    error=f"{type(exc).__name__}: {exc}",
                )
                try:
                    await asyncio.wait_for(
                        self._stop_event.wait(),
                        timeout=self.retry_seconds,
                    )
                except asyncio.TimeoutError:
                    continue
                return
            except Exception as exc:
                status, message = _failure_from_exception(exc)
                await self._store(
                    self.store.fail_job,
                    job_id,
                    status=status,
                    error=message,
                    completed_at_ms=self.now_ms(),
                )
                return


def _failure_from_exception(exc: Exception) -> tuple[str, str]:
    message = f"{type(exc).__name__}: {exc}"[:1000]
    if isinstance(exc, httpx.HTTPStatusError):
        try:
            detail = exc.response.json().get("detail")
        except Exception:
            detail = None
        if isinstance(detail, dict):
            error_code = str(detail.get("error_code") or "")
            worker_message = str(detail.get("message") or message)
            if error_code in {
                "failed_missing_evidence",
                "failed_model",
                "failed_oom",
                "stale_model_revision",
            }:
                return error_code, worker_message[:1000]
    lowered = message.lower()
    if "no such file" in lowered or "missing evidence" in lowered:
        return "failed_missing_evidence", message
    if "out of memory" in lowered or "cuda error" in lowered:
        return "failed_oom", message
    return "failed_model", message
