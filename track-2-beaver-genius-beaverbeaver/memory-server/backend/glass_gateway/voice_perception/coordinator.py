from __future__ import annotations

import asyncio
import time
from typing import Any, Callable

import httpx

from .store import VoiceJobStore


class VoiceCoordinator:
    """Restart-safe dispatcher for the independent serialized voice worker."""

    def __init__(
        self,
        *,
        store: VoiceJobStore,
        worker_client: Any,
        model_revision: str,
        config_version: str,
        postprocessor: Any | None = None,
        retry_seconds: float = 5.0,
        now_ms: Callable[[], int] | None = None,
    ) -> None:
        self.store = store
        self.worker_client = worker_client
        self.model_revision = model_revision
        self.config_version = config_version
        self.postprocessor = postprocessor
        self.retry_seconds = max(0.05, float(retry_seconds))
        self.now_ms = now_ms or (lambda: int(time.time() * 1000))
        self._tasks: dict[str, asyncio.Task[None]] = {}
        self._dispatch_lock = asyncio.Lock()
        self._postprocessing_error: str | None = None
        self._stop_event = asyncio.Event()

    async def _store(self, fn, *args, **kwargs) -> Any:
        # The durable job store is a JSON file that is read-modify-written on
        # every transition. Storage can be a slow NTFS-3G mount, so these
        # synchronous writes must never hold the event loop.
        return await asyncio.to_thread(fn, *args, **kwargs)

    async def start(self) -> None:
        self._stop_event.clear()
        if self.postprocessor is not None:
            recent_jobs = await self._store(self.store.recent_jobs, limit=self.store.max_jobs)
            for job in recent_jobs:
                if job.get("status") not in {
                    "ready",
                    "ready_no_speech",
                    "ready_no_eligible_turn",
                } or job.get("asr_alignment"):
                    continue
                internal = await self._store(self.store.get_job, str(job["job_id"]), internal=True) or {}
                try:
                    await asyncio.to_thread(
                        self.postprocessor.process_job,
                        str(job["job_id"]),
                        asr_result=internal.get("asr_result") or {},
                    )
                    self._postprocessing_error = None
                except Exception as exc:
                    self._postprocessing_error = f"{type(exc).__name__}: {exc}"[:500]
        jobs = await self._store(self.store.recover_incomplete)
        for job in jobs:
            self._schedule(str(job["job_id"]))

    async def stop(self) -> None:
        await asyncio.sleep(0)
        self._stop_event.set()
        if self._tasks:
            await asyncio.gather(*list(self._tasks.values()), return_exceptions=True)
        self._tasks.clear()
        await self.worker_client.close()

    async def submit_audio(
        self,
        *,
        audio_evidence_id: str,
        audio_path: str,
        media_type: str,
        captured_at_ms: int,
        duration_ms: int,
        sample_rate: int,
        boot_session_id: str,
        window_id: str,
        speech_present: bool | None,
        asr_run_id: str = "",
        asr_result: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        job, created = await self._store(
            self.store.create_job,
            {
                "audio_evidence_id": audio_evidence_id,
                "audio_path": audio_path,
                "media_type": media_type,
                "captured_at_ms": captured_at_ms,
                "duration_ms": duration_ms,
                "sample_rate": sample_rate,
                "boot_session_id": boot_session_id,
                "window_id": window_id,
                "speech_present": speech_present,
                "asr_run_id": asr_run_id,
                "asr_result": dict(asr_result or {}),
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
        candidates = None
        if self.postprocessor is not None:
            try:
                candidates = await asyncio.to_thread(self.postprocessor.directory.summary)
            except Exception as exc:
                self._postprocessing_error = f"{type(exc).__name__}: {exc}"[:500]
        return {
            "worker": worker,
            "jobs": await self._store(self.store.summary),
            "candidates": candidates,
            "model_revision": self.model_revision,
            "config_version": self.config_version,
            "postprocessing_error": getattr(self, "_postprocessing_error", None),
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
                    result = await self.worker_client.process(
                        {
                            "job_id": job_id,
                            "audio_evidence_id": job["audio_evidence_id"],
                            "audio_path": job["audio_path"],
                            "media_type": job["media_type"],
                            "speech_present": job.get("speech_present"),
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
                            error="voice worker result revision differs from durable job",
                            completed_at_ms=self.now_ms(),
                        )
                        return
                    await self._store(
                        self.store.finish_job,
                        job_id,
                        status=str(result["status"]),
                        turns=[
                            item
                            for item in result.get("turns") or []
                            if isinstance(item, dict)
                        ],
                        duration_ms=int(result["duration_ms"]),
                        sample_rate=int(result["sample_rate"]),
                        speaker_count=int(result.get("speaker_count") or 0),
                        eligible_speaker_count=int(
                            result.get("eligible_speaker_count") or 0
                        ),
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
                    if self.postprocessor is not None:
                        try:
                            await asyncio.to_thread(
                                self.postprocessor.process_job,
                                job_id,
                                asr_result=job.get("asr_result") or {},
                            )
                            self._postprocessing_error = None
                        except Exception as exc:
                            # A successful diarization job remains successful. The
                            # projection is recoverable on restart or evidence read.
                            self._postprocessing_error = (
                                f"{type(exc).__name__}: {exc}"[:500]
                            )
                return
            except httpx.TransportError as exc:
                await self._store(self.store.defer_job, job_id, error=f"{type(exc).__name__}: {exc}")
                try:
                    await asyncio.wait_for(
                        self._stop_event.wait(), timeout=self.retry_seconds
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
            code = str(detail.get("error_code") or "")
            if code in {
                "failed_missing_evidence",
                "failed_audio_decode",
                "failed_model",
                "failed_oom",
                "stale_model_revision",
            }:
                return code, str(detail.get("message") or message)[:1000]
    lowered = message.lower()
    if "no such file" in lowered or "missing evidence" in lowered:
        return "failed_missing_evidence", message
    if "decode" in lowered or "bad wav" in lowered:
        return "failed_audio_decode", message
    if "out of memory" in lowered or "cuda error" in lowered:
        return "failed_oom", message
    return "failed_model", message
