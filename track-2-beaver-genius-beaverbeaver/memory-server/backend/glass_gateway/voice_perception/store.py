from __future__ import annotations

from copy import deepcopy
import json
import os
from pathlib import Path
import threading
from typing import Any

from .contracts import (
    deterministic_voice_job_id,
    normalize_voice_turn,
    public_voice_job,
)


class VoiceJobStore:
    """Durable voice jobs and turns with embeddings in a mode-0600 sidecar."""

    def __init__(
        self,
        path: str | Path,
        *,
        embedding_path: str | Path,
        max_jobs: int = 10_000,
    ) -> None:
        self.path = Path(path)
        self.turn_path = self.path.with_name(f"{self.path.stem}-turns.json")
        self.embedding_path = Path(embedding_path)
        self.max_jobs = max(100, int(max_jobs))
        self._lock = threading.RLock()

    def create_job(
        self, payload: dict[str, Any], *, created_at_ms: int
    ) -> tuple[dict[str, Any], bool]:
        job_id = deterministic_voice_job_id(
            audio_evidence_id=str(payload["audio_evidence_id"]),
            model_revision=str(payload["model_revision"]),
            config_version=str(payload["config_version"]),
        )
        with self._lock:
            data = self._read_list(self.path, "jobs")
            existing = next(
                (item for item in data["jobs"] if item.get("job_id") == job_id), None
            )
            if existing is not None:
                return public_voice_job(deepcopy(existing)), False
            item = {
                "job_id": job_id,
                "status": "pending",
                "audio_evidence_id": str(payload["audio_evidence_id"]),
                "audio_path": str(payload["audio_path"]),
                "media_type": str(payload.get("media_type") or "audio/wav"),
                "captured_at_ms": int(payload["captured_at_ms"]),
                "duration_ms": int(payload.get("duration_ms") or 0),
                "sample_rate": int(payload.get("sample_rate") or 0),
                "boot_session_id": str(payload.get("boot_session_id") or ""),
                "window_id": str(payload.get("window_id") or ""),
                "speech_present": payload.get("speech_present"),
                "asr_run_id": str(payload.get("asr_run_id") or ""),
                "asr_result": deepcopy(payload.get("asr_result") or {}),
                "model_revision": str(payload["model_revision"]),
                "config_version": str(payload["config_version"]),
                "created_at_ms": int(created_at_ms),
                "started_at_ms": None,
                "completed_at_ms": None,
                "dispatch_attempt_count": 0,
                "latency_ms": None,
                "turn_ids": [],
                "speaker_count": None,
                "eligible_speaker_count": None,
                "error_code": None,
                "error": None,
                "worker_metadata": {},
            }
            data["jobs"].insert(0, item)
            data["jobs"] = data["jobs"][: self.max_jobs]
            self._write_json(self.path, data)
            return public_voice_job(deepcopy(item)), True

    def get_job(self, job_id: str, *, internal: bool = False) -> dict[str, Any] | None:
        with self._lock:
            item = next(
                (
                    item
                    for item in self._read_list(self.path, "jobs")["jobs"]
                    if item.get("job_id") == job_id
                ),
                None,
            )
            if item is None:
                return None
            result = deepcopy(item)
            return result if internal else public_voice_job(result)

    def mark_running(self, job_id: str, *, started_at_ms: int) -> dict[str, Any] | None:
        return self._update_job(
            job_id,
            {
                "status": "running",
                "started_at_ms": int(started_at_ms),
                "error_code": None,
                "error": None,
            },
            allowed={"pending", "running"},
            increment_attempt=True,
        )

    def defer_job(self, job_id: str, *, error: str) -> dict[str, Any] | None:
        return self._update_job(
            job_id,
            {
                "status": "pending",
                "started_at_ms": None,
                "error_code": "worker_unavailable_retrying",
                "error": str(error)[:1000],
            },
            allowed={"pending", "running"},
        )

    def finish_job(
        self,
        job_id: str,
        *,
        status: str,
        turns: list[dict[str, Any]],
        duration_ms: int,
        sample_rate: int,
        speaker_count: int,
        eligible_speaker_count: int,
        latency_ms: float,
        completed_at_ms: int,
        worker_metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if status not in {"ready", "ready_no_speech", "ready_no_eligible_turn"}:
            raise ValueError(f"invalid voice success status: {status}")
        with self._lock:
            jobs = self._read_list(self.path, "jobs")
            job = next((item for item in jobs["jobs"] if item.get("job_id") == job_id), None)
            if job is None:
                raise KeyError(job_id)
            if job.get("status") not in {"pending", "running"}:
                return public_voice_job(deepcopy(job))
            public_turns: list[dict[str, Any]] = []
            vectors = self._read_embeddings()
            for value in turns:
                public, embedding = normalize_voice_turn(
                    value,
                    job_id=job_id,
                    audio_evidence_id=str(job["audio_evidence_id"]),
                    captured_at_ms=int(job["captured_at_ms"]),
                    duration_ms=int(duration_ms),
                    model_revision=str(job["model_revision"]),
                    config_version=str(job["config_version"]),
                )
                public["boot_session_id"] = str(job.get("boot_session_id") or "")
                public["window_id"] = str(job.get("window_id") or "")
                if embedding is not None:
                    vectors[public["turn_id"]] = embedding
                public_turns.append(public)
            existing_turns = self._read_list(self.turn_path, "turns")
            existing_ids = {str(item.get("turn_id")) for item in existing_turns["turns"]}
            existing_turns["turns"].extend(
                item for item in public_turns if item["turn_id"] not in existing_ids
            )
            job.update(
                {
                    "status": status,
                    "duration_ms": int(duration_ms),
                    "sample_rate": int(sample_rate),
                    "completed_at_ms": int(completed_at_ms),
                    "latency_ms": float(latency_ms),
                    "turn_ids": [item["turn_id"] for item in public_turns],
                    "speaker_count": int(speaker_count),
                    "eligible_speaker_count": int(eligible_speaker_count),
                    "worker_metadata": dict(worker_metadata or {}),
                    "error_code": None,
                    "error": None,
                }
            )
            self._write_json(self.turn_path, existing_turns)
            self._write_embeddings(vectors)
            self._write_json(self.path, jobs)
            return public_voice_job(deepcopy(job))

    def fail_job(
        self, job_id: str, *, status: str, error: str, completed_at_ms: int
    ) -> dict[str, Any] | None:
        allowed = {
            "failed_missing_evidence",
            "failed_audio_decode",
            "failed_model",
            "failed_oom",
            "stale_model_revision",
        }
        if status not in allowed:
            raise ValueError(f"invalid voice failure status: {status}")
        return self._update_job(
            job_id,
            {
                "status": status,
                "error_code": status,
                "error": str(error)[:1000],
                "completed_at_ms": int(completed_at_ms),
            },
            allowed={"pending", "running"},
        )

    def turns_for_job(self, job_id: str) -> list[dict[str, Any]]:
        with self._lock:
            return [
                deepcopy(item)
                for item in self._read_list(self.turn_path, "turns")["turns"]
                if item.get("job_id") == job_id
            ]

    def job_for_window(
        self, window_id: str, *, internal: bool = False
    ) -> dict[str, Any] | None:
        with self._lock:
            item = next(
                (
                    item
                    for item in self._read_list(self.path, "jobs")["jobs"]
                    if item.get("window_id") == window_id
                ),
                None,
            )
            if item is None:
                return None
            result = deepcopy(item)
            return result if internal else public_voice_job(result)

    def protected_embedding(self, turn_id: str) -> list[float] | None:
        with self._lock:
            value = self._read_embeddings().get(turn_id)
            return list(value) if isinstance(value, list) else None

    def save_postprocessing(
        self,
        job_id: str,
        *,
        turns: list[dict[str, Any]],
        audio_speakers: list[dict[str, Any]],
        asr_alignment: dict[str, Any],
    ) -> dict[str, Any]:
        """Persist public candidate/alignment projections without vector data."""

        with self._lock:
            turn_data = self._read_list(self.turn_path, "turns")
            updates = {
                str(item.get("turn_id")): item
                for item in turns
                if item.get("turn_id")
            }
            for current in turn_data["turns"]:
                update = updates.get(str(current.get("turn_id") or ""))
                if not update or current.get("job_id") != job_id:
                    continue
                current.update(
                    {
                        "voice_candidate_id": update.get("voice_candidate_id"),
                        "confirmed_person_id": update.get("confirmed_person_id"),
                        "asr_segment_refs": list(update.get("asr_segment_refs") or []),
                    }
                )
            jobs = self._read_list(self.path, "jobs")
            job = next((item for item in jobs["jobs"] if item.get("job_id") == job_id), None)
            if job is None:
                raise KeyError(job_id)
            job["audio_speakers"] = _without_embeddings(audio_speakers)
            job["asr_alignment"] = _without_embeddings(asr_alignment)
            self._write_json(self.turn_path, turn_data)
            self._write_json(self.path, jobs)
            return public_voice_job(deepcopy(job))

    def recent_jobs(self, *, limit: int = 50) -> list[dict[str, Any]]:
        with self._lock:
            return [
                public_voice_job(deepcopy(item))
                for item in self._read_list(self.path, "jobs")["jobs"][: max(0, int(limit))]
            ]

    def delete_turns(self, turn_ids: list[str] | set[str]) -> dict[str, int]:
        """Delete derived speaker turns/vectors while retaining source WAV files."""

        requested = {str(item) for item in turn_ids if item}
        if not requested:
            return {"removed_turns": 0, "removed_embeddings": 0}
        with self._lock:
            turn_data = self._read_list(self.turn_path, "turns")
            embeddings = self._read_embeddings()
            present_turns = {
                str(item.get("turn_id") or "")
                for item in turn_data["turns"]
                if item.get("turn_id") in requested
            }
            present_embeddings = requested.intersection(embeddings)
            if not present_turns and not present_embeddings:
                return {"removed_turns": 0, "removed_embeddings": 0}
            turn_data["turns"] = [
                item for item in turn_data["turns"] if item.get("turn_id") not in requested
            ]
            for turn_id in present_embeddings:
                embeddings.pop(turn_id, None)
            jobs = self._read_list(self.path, "jobs")
            for job in jobs["jobs"]:
                previous = list(job.get("turn_ids") or [])
                current = [item for item in previous if item not in requested]
                if current == previous:
                    continue
                job["turn_ids"] = current
                if not current and job.get("status") == "ready":
                    job["status"] = "ready_no_eligible_turn"
                    job["eligible_speaker_count"] = 0
            self._write_embeddings(embeddings)
            self._write_json(self.turn_path, turn_data)
            self._write_json(self.path, jobs)
            return {
                "removed_turns": len(present_turns),
                "removed_embeddings": len(present_embeddings),
            }

    def recent_turns(self, *, limit: int = 200) -> list[dict[str, Any]]:
        with self._lock:
            return [
                deepcopy(item)
                for item in self._read_list(self.turn_path, "turns")["turns"][
                    : max(0, int(limit))
                ]
            ]

    def recover_incomplete(self) -> list[dict[str, Any]]:
        recovered = []
        for item in self.recent_jobs(limit=self.max_jobs):
            if item.get("status") not in {"pending", "running"}:
                continue
            updated = self._update_job(
                str(item["job_id"]),
                {"status": "pending", "started_at_ms": None},
                allowed={"pending", "running"},
            )
            if updated:
                recovered.append(updated)
        return recovered

    def summary(self) -> dict[str, Any]:
        jobs = self.recent_jobs(limit=self.max_jobs)
        counts: dict[str, int] = {}
        for item in jobs:
            status = str(item.get("status") or "unknown")
            counts[status] = counts.get(status, 0) + 1
        return {
            "total": len(jobs),
            "counts": counts,
            "queue_depth": sum(counts.get(item, 0) for item in ("pending", "running")),
        }

    def _update_job(
        self,
        job_id: str,
        changes: dict[str, Any],
        *,
        allowed: set[str],
        increment_attempt: bool = False,
    ) -> dict[str, Any] | None:
        with self._lock:
            data = self._read_list(self.path, "jobs")
            for item in data["jobs"]:
                if item.get("job_id") != job_id or item.get("status") not in allowed:
                    continue
                item.update(changes)
                if increment_attempt:
                    item["dispatch_attempt_count"] = int(
                        item.get("dispatch_attempt_count") or 0
                    ) + 1
                self._write_json(self.path, data)
                return public_voice_job(deepcopy(item))
            return None

    @staticmethod
    def _read_list(path: Path, key: str) -> dict[str, list[dict[str, Any]]]:
        if not path.is_file():
            return {key: []}
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {key: []}
        values = payload.get(key) if isinstance(payload, dict) else []
        return {key: [item for item in values or [] if isinstance(item, dict)]}

    def _read_embeddings(self) -> dict[str, list[float]]:
        if not self.embedding_path.is_file():
            return {}
        try:
            payload = json.loads(self.embedding_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
        return {
            str(key): [float(item) for item in value]
            for key, value in (payload.items() if isinstance(payload, dict) else [])
            if isinstance(value, list)
        }

    def _write_embeddings(self, data: dict[str, Any]) -> None:
        self._write_json(self.embedding_path, data, protected=True)

    @staticmethod
    def _write_json(path: Path, data: dict[str, Any], *, protected: bool = False) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
        temporary.write_text(
            json.dumps(data, ensure_ascii=False, separators=(",", ":")), encoding="utf-8"
        )
        if protected:
            os.chmod(temporary, 0o600)
        os.replace(temporary, path)
        if protected:
            os.chmod(path, 0o600)


def _without_embeddings(value: Any) -> Any:
    if isinstance(value, list):
        return [_without_embeddings(item) for item in value]
    if isinstance(value, dict):
        return {
            key: _without_embeddings(item)
            for key, item in value.items()
            if key not in {"embedding", "voice_embedding", "face_embedding"}
        }
    return value
