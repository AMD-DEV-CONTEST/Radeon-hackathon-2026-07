from __future__ import annotations

import asyncio
import time
from typing import Any

from glass_gateway.identity_perception.store import IdentityJobStore
from glass_gateway.identity_perception.directory import IdentityDirectoryStore


class ProductionIdentityRecognizer:
    """Read already-produced face assignments without running CUDA in gateway.

    A short bounded wait lets the normal single-frame worker result join the
    current Capsule. A slow or unavailable worker never prevents ASR, MiMo or
    EverOS from continuing; its durable job remains visible in the evidence UI.
    """

    def __init__(
        self,
        *,
        job_store: IdentityJobStore,
        directory: IdentityDirectoryStore,
        voice_recognizer: Any | None = None,
        wait_ms: int = 350,
        poll_ms: int = 25,
    ) -> None:
        self.job_store = job_store
        self.directory = directory
        self.voice_recognizer = voice_recognizer
        self.wait_ms = max(0, int(wait_ms))
        self.poll_ms = max(5, int(poll_ms))

    async def recognize_window(
        self,
        *,
        images: list[dict[str, Any]],
        **kwargs: Any,
    ) -> dict[str, Any]:
        evidence_ids = [
            str(item.get("id") or "").strip()
            for item in images
            if str(item.get("id") or "").strip()
        ]
        if evidence_ids and self.wait_ms:
            await self._wait_for_terminal(evidence_ids)

        frames = [self._frame_projection(evidence_id) for evidence_id in evidence_ids]
        visible_people = [
            person
            for frame in frames
            for person in frame.get("visible_people", [])
        ]
        audio_speakers: list[dict[str, Any]] = []
        voice_perception: dict[str, Any] = {"status": "not_requested"}
        if self.voice_recognizer is not None:
            voice_result = await self.voice_recognizer.recognize_window(
                images=[],
                **kwargs,
            )
            audio_speakers = [
                item
                for item in voice_result.get("audio_speakers", [])
                if isinstance(item, dict)
            ]
            voice_perception = (
                dict(voice_result.get("voice_perception") or {})
                if isinstance(voice_result, dict)
                else {"status": "failed"}
            )
        return {
            "visible_people": visible_people,
            "audio_speakers": audio_speakers,
            "identity_perception": self._processing_summary(frames),
            "voice_perception": voice_perception,
        }

    async def _wait_for_terminal(self, evidence_ids: list[str]) -> None:
        deadline = time.monotonic() + self.wait_ms / 1000
        while time.monotonic() < deadline:
            jobs = [self.job_store.job_for_evidence(value) for value in evidence_ids]
            if not any(
                job and job.get("status") in {"pending", "running"}
                for job in jobs
            ):
                return
            await asyncio.sleep(self.poll_ms / 1000)

    def _frame_projection(self, evidence_id: str) -> dict[str, Any]:
        job = self.job_store.job_for_evidence(evidence_id)
        if job is None:
            return {
                "evidence_id": evidence_id,
                "status": "not_requested",
                "visible_people": [],
            }
        observations = self.job_store.observations_for_job(str(job["job_id"]))
        public = self.directory.public_snapshot()
        assignments = {
            str(item.get("observation_id")): item
            for item in public.get("assignments", [])
            if item.get("observation_id")
        }
        people = {
            str(item.get("person_id")): item
            for item in public.get("people", [])
            if item.get("status") == "active" and item.get("person_id")
        }
        visible = [
            self._visible_person(observation, assignments.get(str(observation["observation_id"])), people)
            for observation in observations
        ]
        return {
            "evidence_id": evidence_id,
            "job_id": job.get("job_id"),
            "status": job.get("status"),
            "face_count": job.get("face_count"),
            "latency_ms": job.get("latency_ms"),
            "model_revision": job.get("model_revision"),
            "config_version": job.get("config_version"),
            "error_code": job.get("error_code"),
            "error": job.get("error"),
            "visible_people": visible,
        }

    @staticmethod
    def _visible_person(
        observation: dict[str, Any],
        assignment: dict[str, Any] | None,
        people: dict[str, dict[str, Any]],
    ) -> dict[str, Any]:
        assignment = dict(assignment or {})
        confirmed_id = str(assignment.get("confirmed_person_id") or "").strip() or None
        candidate_id = str(assignment.get("candidate_id") or "").strip() or None
        confirmed = people.get(confirmed_id or "")
        name = (
            str(confirmed.get("display_name") or confirmed_id)
            if confirmed
            else candidate_id or "未分配人脸"
        )
        confidence = (
            assignment.get("match_confidence")
            if confirmed_id
            else assignment.get("suggestion_confidence")
        )
        if not isinstance(confidence, (int, float)):
            confidence = observation.get("detection_score")
        return {
            "name": name,
            "candidate_id": candidate_id,
            "candidate_status": "confirmed" if confirmed_id else "candidate",
            "confirmed_person_id": confirmed_id,
            "suggested_person_id": assignment.get("suggested_person_id"),
            "suggestion_status": assignment.get("gallery_decision_status"),
            "confidence": confidence,
            "source": "identity_worker",
            "evidence_id": observation.get("evidence_id"),
            "observation_id": observation.get("observation_id"),
            "bbox": observation.get("bbox") or [],
            "quality": observation.get("quality") or {},
            "identity_preassigned": True,
        }

    @staticmethod
    def _processing_summary(frames: list[dict[str, Any]]) -> dict[str, Any]:
        statuses = [str(item.get("status") or "not_requested") for item in frames]
        if not statuses:
            status = "not_requested"
        elif any(value in {"pending", "running"} for value in statuses):
            status = "pending"
        elif any(value.startswith("failed_") or value == "stale_model_revision" for value in statuses):
            status = "partial_failure" if any(value.startswith("ready") for value in statuses) else "failed"
        else:
            status = "completed"
        return {
            "status": status,
            "frame_count": len(frames),
            "face_count": sum(len(item.get("visible_people") or []) for item in frames),
            "frames": frames,
        }

    def evidence_status(self, evidence_ids: list[str]) -> dict[str, Any]:
        """Return the current, possibly late, public projection for the Web UI."""

        return self._processing_summary(
            [self._frame_projection(str(value)) for value in evidence_ids if str(value)]
        )

    def voice_evidence_status(self, window_id: str) -> dict[str, Any]:
        recognizer = self.voice_recognizer
        if recognizer is None or not hasattr(recognizer, "evidence_status"):
            return {"status": "not_requested", "audio_speakers": []}
        return recognizer.evidence_status(window_id)
