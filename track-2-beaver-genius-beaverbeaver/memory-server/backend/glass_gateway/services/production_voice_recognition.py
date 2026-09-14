from __future__ import annotations

import asyncio
from pathlib import Path
import time
from typing import Any
import wave

from glass_gateway.voice_perception.coordinator import VoiceCoordinator
from glass_gateway.voice_perception.directory import VoiceCandidateDirectory
from glass_gateway.voice_perception.postprocessor import VoiceCandidatePostprocessor
from glass_gateway.voice_perception.store import VoiceJobStore


class ProductionVoiceRecognizer:
    """Submit WAV evidence and expose bounded/late public voice projections."""

    def __init__(
        self,
        *,
        coordinator: VoiceCoordinator,
        job_store: VoiceJobStore,
        directory: VoiceCandidateDirectory,
        postprocessor: VoiceCandidatePostprocessor,
        wait_ms: int = 350,
        poll_ms: int = 25,
    ) -> None:
        self.coordinator = coordinator
        self.job_store = job_store
        self.directory = directory
        self.postprocessor = postprocessor
        self.wait_ms = max(0, int(wait_ms))
        self.poll_ms = max(5, int(poll_ms))

    async def recognize_window(
        self,
        *,
        window_id: str,
        boot_session_id: str,
        captured_at_ms: int,
        wav_path: str,
        sample_rate: int,
        speech_present: bool,
        asr_result: dict[str, Any] | None = None,
        **_: Any,
    ) -> dict[str, Any]:
        duration_ms, probed_rate = _probe_wave(Path(wav_path))
        job = await self.coordinator.submit_audio(
            audio_evidence_id=f"window-audio:{window_id}",
            audio_path=str(Path(wav_path).resolve()),
            media_type="audio/wav",
            captured_at_ms=captured_at_ms,
            duration_ms=duration_ms,
            sample_rate=probed_rate or sample_rate,
            boot_session_id=boot_session_id,
            window_id=window_id,
            speech_present=speech_present,
            asr_run_id=str((asr_result or {}).get("asr_run_id") or ""),
            asr_result=asr_result,
        )
        if self.wait_ms:
            await self._wait_for_terminal(str(job["job_id"]))
        projection = await asyncio.to_thread(
            self._projection_for_job, str(job["job_id"])
        )
        return {
            "audio_speakers": list(projection.get("audio_speakers") or []),
            "voice_perception": projection,
        }

    async def _wait_for_terminal(self, job_id: str) -> None:
        deadline = time.monotonic() + self.wait_ms / 1000
        while time.monotonic() < deadline:
            job = self.job_store.get_job(job_id)
            if job and job.get("status") not in {"pending", "running"}:
                return
            await asyncio.sleep(self.poll_ms / 1000)

    def evidence_status(self, window_id: str) -> dict[str, Any]:
        job = self.job_store.job_for_window(window_id)
        if job is None:
            return {
                "status": "not_requested",
                "window_id": window_id,
                "audio_speakers": [],
                "turns": [],
            }
        return self._projection_for_job(str(job["job_id"]))

    def _projection_for_job(self, job_id: str) -> dict[str, Any]:
        job = self.job_store.get_job(job_id)
        if job is None:
            return {"status": "not_requested", "audio_speakers": [], "turns": []}
        status = str(job.get("status") or "pending")
        if status in {"ready", "ready_no_speech", "ready_no_eligible_turn"} and not job.get(
            "asr_alignment"
        ):
            internal = self.job_store.get_job(job_id, internal=True) or {}
            try:
                self.postprocessor.process_job(
                    job_id, asr_result=internal.get("asr_result") or {}
                )
                job = self.job_store.get_job(job_id) or job
            except Exception:
                return {
                    **_job_projection(job, self.job_store.turns_for_job(job_id)),
                    "status": "postprocessing_failed",
                    "error_code": "postprocessing_failed",
                    "audio_speakers": [],
                }
        return _job_projection(job, self.job_store.turns_for_job(job_id))


def _job_projection(job: dict[str, Any], turns: list[dict[str, Any]]) -> dict[str, Any]:
    raw_status = str(job.get("status") or "pending")
    if raw_status in {"pending", "running"}:
        status = raw_status
    elif raw_status.startswith("failed_") or raw_status == "stale_model_revision":
        status = "failed"
    else:
        status = "completed"
    return {
        "status": status,
        "job_status": raw_status,
        "job_id": job.get("job_id"),
        "window_id": job.get("window_id"),
        "audio_evidence_id": job.get("audio_evidence_id"),
        "speaker_count": job.get("speaker_count"),
        "eligible_speaker_count": job.get("eligible_speaker_count"),
        "latency_ms": job.get("latency_ms"),
        "model_revision": job.get("model_revision"),
        "config_version": job.get("config_version"),
        "error_code": job.get("error_code"),
        "asr_alignment": job.get("asr_alignment") or {},
        "audio_speakers": list(job.get("audio_speakers") or []),
        "turns": turns,
    }


def _probe_wave(path: Path) -> tuple[int, int]:
    with wave.open(str(path), "rb") as handle:
        frames = int(handle.getnframes())
        sample_rate = int(handle.getframerate())
    return round(frames / max(1, sample_rate) * 1000), sample_rate
