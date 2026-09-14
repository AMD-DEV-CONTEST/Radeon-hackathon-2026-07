from __future__ import annotations

from copy import deepcopy
import json
import os
from pathlib import Path
import threading
from typing import Any

from .contracts import (
    deterministic_face_job_id,
    normalize_face_observation,
    public_job,
)


class IdentityJobStore:
    """Durable face job/observation store with embeddings kept in a separate file."""

    def __init__(
        self,
        path: str | Path,
        *,
        embedding_path: str | Path,
        max_jobs: int = 10_000,
    ) -> None:
        self.path = Path(path)
        self.embedding_path = Path(embedding_path)
        self.max_jobs = max(100, int(max_jobs))
        self._lock = threading.RLock()

    def create_job(
        self,
        payload: dict[str, Any],
        *,
        created_at_ms: int,
    ) -> tuple[dict[str, Any], bool]:
        job_id = deterministic_face_job_id(
            evidence_id=str(payload["evidence_id"]),
            model_revision=str(payload["model_revision"]),
            config_version=str(payload["config_version"]),
        )
        with self._lock:
            data = self._read_jobs_unlocked()
            existing = next(
                (item for item in data["jobs"] if item.get("job_id") == job_id),
                None,
            )
            if existing is not None:
                return public_job(deepcopy(existing)), False
            item = {
                "job_id": job_id,
                "status": "pending",
                "evidence_id": str(payload["evidence_id"]),
                "image_path": str(payload["image_path"]),
                "media_type": str(payload.get("media_type") or "application/octet-stream"),
                "captured_at_ms": int(payload["captured_at_ms"]),
                "boot_session_id": str(payload.get("boot_session_id") or ""),
                "window_id": str(payload.get("window_id") or ""),
                "model_revision": str(payload["model_revision"]),
                "config_version": str(payload["config_version"]),
                "created_at_ms": int(created_at_ms),
                "dispatch_attempt_count": 0,
                "started_at_ms": None,
                "completed_at_ms": None,
                "latency_ms": None,
                "observation_ids": [],
                "face_count": None,
                "error_code": None,
                "error": None,
                "worker_metadata": {},
            }
            data["jobs"].insert(0, item)
            data["jobs"] = data["jobs"][: self.max_jobs]
            self._write_jobs_unlocked(data)
            return public_job(deepcopy(item)), True

    def get_job(self, job_id: str, *, internal: bool = False) -> dict[str, Any] | None:
        with self._lock:
            item = next(
                (
                    item
                    for item in self._read_jobs_unlocked()["jobs"]
                    if item.get("job_id") == job_id
                ),
                None,
            )
            if item is None:
                return None
            result = deepcopy(item)
            return result if internal else public_job(result)

    def job_for_evidence(self, evidence_id: str) -> dict[str, Any] | None:
        with self._lock:
            matches = [
                item
                for item in self._read_jobs_unlocked()["jobs"]
                if item.get("evidence_id") == evidence_id
            ]
            matches.sort(key=lambda item: int(item.get("created_at_ms") or 0), reverse=True)
            return public_job(deepcopy(matches[0])) if matches else None

    def mark_running(self, job_id: str, *, started_at_ms: int) -> dict[str, Any] | None:
        with self._lock:
            data = self._read_jobs_unlocked()
            for item in data["jobs"]:
                if item.get("job_id") != job_id:
                    continue
                if item.get("status") not in {"pending", "running"}:
                    return None
                item.update(
                    {
                        "status": "running",
                        "started_at_ms": int(started_at_ms),
                        "dispatch_attempt_count": int(
                            item.get("dispatch_attempt_count") or 0
                        )
                        + 1,
                        "error_code": None,
                        "error": None,
                    }
                )
                self._write_jobs_unlocked(data)
                return public_job(deepcopy(item))
            return None

    def defer_job(self, job_id: str, *, error: str) -> dict[str, Any] | None:
        """Persist a transient transport failure for restart-safe retry."""

        return self._update_job(
            job_id,
            {
                "status": "pending",
                "started_at_ms": None,
                "completed_at_ms": None,
                "error_code": "worker_unavailable_retrying",
                "error": str(error)[:1000],
            },
            allowed={"pending", "running"},
        )

    def finish_job(
        self,
        job_id: str,
        *,
        observations: list[dict[str, Any]],
        input_width: int,
        input_height: int,
        latency_ms: float,
        completed_at_ms: int,
        worker_metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        with self._lock:
            data = self._read_jobs_unlocked()
            job = next((item for item in data["jobs"] if item.get("job_id") == job_id), None)
            if job is None:
                raise KeyError(job_id)
            if job.get("status") not in {"pending", "running"}:
                return public_job(deepcopy(job))
            vectors = self._read_embeddings_unlocked()
            public_observations: list[dict[str, Any]] = []
            for value in observations:
                public, embedding = normalize_face_observation(
                    value,
                    job_id=job_id,
                    evidence_id=str(job["evidence_id"]),
                    captured_at_ms=int(job["captured_at_ms"]),
                    model_revision=str(job["model_revision"]),
                    config_version=str(job["config_version"]),
                    input_width=int(input_width),
                    input_height=int(input_height),
                )
                public["boot_session_id"] = str(job.get("boot_session_id") or "")
                public["window_id"] = str(job.get("window_id") or "")
                vectors[public["observation_id"]] = embedding
                public_observations.append(public)
            observation_data = self._read_observations_unlocked()
            existing_ids = {
                str(item.get("observation_id"))
                for item in observation_data["observations"]
            }
            observation_data["observations"].extend(
                item
                for item in public_observations
                if item["observation_id"] not in existing_ids
            )
            job.update(
                {
                    "status": "ready" if public_observations else "ready_no_face",
                    "completed_at_ms": int(completed_at_ms),
                    "latency_ms": float(latency_ms),
                    "face_count": len(public_observations),
                    "observation_ids": [
                        item["observation_id"] for item in public_observations
                    ],
                    "worker_metadata": dict(worker_metadata or {}),
                    "error_code": None,
                    "error": None,
                }
            )
            self._write_embeddings_unlocked(vectors)
            self._write_observations_unlocked(observation_data)
            self._write_jobs_unlocked(data)
            return public_job(deepcopy(job))

    def fail_job(
        self,
        job_id: str,
        *,
        status: str,
        error: str,
        completed_at_ms: int,
    ) -> dict[str, Any] | None:
        allowed_statuses = {
            "failed_missing_evidence",
            "failed_model",
            "failed_oom",
            "stale_model_revision",
        }
        if status not in allowed_statuses:
            raise ValueError(f"invalid face failure status: {status}")
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

    def observations_for_job(self, job_id: str) -> list[dict[str, Any]]:
        with self._lock:
            return [
                deepcopy(item)
                for item in self._read_observations_unlocked()["observations"]
                if item.get("job_id") == job_id
            ]

    def recent_observations(self, *, limit: int = 10_000) -> list[dict[str, Any]]:
        with self._lock:
            observations = self._read_observations_unlocked()["observations"]
            observations.sort(
                key=lambda item: int(item.get("captured_at_ms") or 0), reverse=True
            )
            return deepcopy(observations[: max(0, int(limit))])

    def protected_embedding(self, observation_id: str) -> list[float] | None:
        with self._lock:
            value = self._read_embeddings_unlocked().get(observation_id)
            return list(value) if isinstance(value, list) else None

    def delete_observations(self, observation_ids: list[str] | set[str]) -> dict[str, int]:
        """Remove derived face observations and their protected embeddings.

        The source image is raw memory evidence and is deliberately outside this
        store. Its retention is managed by the memory evidence policy.
        """

        requested = {str(item) for item in observation_ids if item}
        if not requested:
            return {"removed_observations": 0, "removed_embeddings": 0}
        with self._lock:
            observations = self._read_observations_unlocked()
            embeddings = self._read_embeddings_unlocked()
            present_observations = {
                str(item.get("observation_id") or "")
                for item in observations["observations"]
                if item.get("observation_id") in requested
            }
            present_embeddings = requested.intersection(embeddings)
            if not present_observations and not present_embeddings:
                return {"removed_observations": 0, "removed_embeddings": 0}

            observations["observations"] = [
                item
                for item in observations["observations"]
                if item.get("observation_id") not in requested
            ]
            for observation_id in present_embeddings:
                embeddings.pop(observation_id, None)
            jobs = self._read_jobs_unlocked()
            for job in jobs["jobs"]:
                old_ids = list(job.get("observation_ids") or [])
                new_ids = [item for item in old_ids if item not in requested]
                if new_ids == old_ids:
                    continue
                job["observation_ids"] = new_ids
                job["face_count"] = len(new_ids)
                if not new_ids and job.get("status") == "ready":
                    job["status"] = "ready_no_face"
            self._write_embeddings_unlocked(embeddings)
            self._write_observations_unlocked(observations)
            self._write_jobs_unlocked(jobs)
            return {
                "removed_observations": len(present_observations),
                "removed_embeddings": len(present_embeddings),
            }

    def recent_jobs(self, *, limit: int = 50) -> list[dict[str, Any]]:
        with self._lock:
            return [
                public_job(deepcopy(item))
                for item in self._read_jobs_unlocked()["jobs"][: max(0, int(limit))]
            ]

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

    def recover_incomplete(self) -> list[dict[str, Any]]:
        recovered: list[dict[str, Any]] = []
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

    def _update_job(
        self,
        job_id: str,
        changes: dict[str, Any],
        *,
        allowed: set[str],
    ) -> dict[str, Any] | None:
        with self._lock:
            data = self._read_jobs_unlocked()
            for item in data["jobs"]:
                if item.get("job_id") != job_id:
                    continue
                if item.get("status") not in allowed:
                    return None
                item.update(changes)
                self._write_jobs_unlocked(data)
                return public_job(deepcopy(item))
            return None

    def _read_jobs_unlocked(self) -> dict[str, list[dict[str, Any]]]:
        return self._read_list_file(self.path, "jobs")

    def _read_observations_unlocked(self) -> dict[str, list[dict[str, Any]]]:
        return self._read_list_file(
            self.path.with_name(f"{self.path.stem}-observations.json"),
            "observations",
        )

    @staticmethod
    def _read_list_file(path: Path, key: str) -> dict[str, list[dict[str, Any]]]:
        if not path.is_file():
            return {key: []}
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {key: []}
        values = payload.get(key) if isinstance(payload, dict) else []
        return {key: [item for item in values or [] if isinstance(item, dict)]}

    def _read_embeddings_unlocked(self) -> dict[str, list[float]]:
        if not self.embedding_path.is_file():
            return {}
        try:
            payload = json.loads(self.embedding_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
        if not isinstance(payload, dict):
            return {}
        return {
            str(key): [float(item) for item in value]
            for key, value in payload.items()
            if isinstance(value, list)
        }

    def _write_jobs_unlocked(self, data: dict[str, Any]) -> None:
        self._atomic_json(self.path, data, protected=False)

    def _write_observations_unlocked(self, data: dict[str, Any]) -> None:
        self._atomic_json(
            self.path.with_name(f"{self.path.stem}-observations.json"),
            data,
            protected=False,
        )

    def _write_embeddings_unlocked(self, data: dict[str, Any]) -> None:
        self._atomic_json(self.embedding_path, data, protected=True)

    @staticmethod
    def _atomic_json(path: Path, data: dict[str, Any], *, protected: bool) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
        temporary.write_text(
            json.dumps(data, ensure_ascii=False, separators=(",", ":")),
            encoding="utf-8",
        )
        if protected:
            os.chmod(temporary, 0o600)
        os.replace(temporary, path)
        if protected:
            os.chmod(path, 0o600)
