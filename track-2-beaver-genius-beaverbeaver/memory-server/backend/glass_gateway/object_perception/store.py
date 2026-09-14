from __future__ import annotations

from copy import deepcopy
import json
import os
from pathlib import Path
import threading
from typing import Any

from .contracts import deterministic_job_id, normalize_detection


class ObjectPerceptionStore:
    """Small durable outbox/result store owned by the gateway."""

    def __init__(self, path: str | Path, *, max_jobs: int = 5000) -> None:
        self.path = Path(path)
        self.max_jobs = max(100, max_jobs)
        self._lock = threading.RLock()

    def create_job(
        self,
        payload: dict[str, Any],
        *,
        created_at_ms: int,
    ) -> tuple[dict[str, Any], bool]:
        vocabulary = dict(payload.get("vocabulary") or {})
        job_id = deterministic_job_id(
            model_version=str(payload["model_version"]),
            evidence_id=str(payload["evidence_id"]),
            vocabulary_hash=str(vocabulary["hash"]),
        )
        with self._lock:
            data = self._read_unlocked()
            existing = next((item for item in data["jobs"] if item.get("job_id") == job_id), None)
            if existing is not None:
                return deepcopy(existing), False
            item = {
                "job_id": job_id,
                "status": "pending",
                "model_id": str(payload["model_id"]),
                "model_version": str(payload["model_version"]),
                "evidence_id": str(payload["evidence_id"]),
                "image_path": str(payload["image_path"]),
                "media_type": str(payload.get("media_type") or "application/octet-stream"),
                "captured_at_ms": int(payload["captured_at_ms"]),
                "window_id": str(payload.get("window_id") or ""),
                "boot_session_key": str(payload.get("boot_session_key") or ""),
                "width": int(payload["width"]) if payload.get("width") else None,
                "height": int(payload["height"]) if payload.get("height") else None,
                "vocabulary": vocabulary,
                "detections": [],
                "latency_ms": None,
                "created_at_ms": int(created_at_ms),
                "started_at_ms": None,
                "completed_at_ms": None,
                "hint_timed_out": False,
                "error": None,
            }
            data["jobs"].insert(0, item)
            data["jobs"] = data["jobs"][: self.max_jobs]
            self._write_unlocked(data)
            return deepcopy(item), True

    def get_job(self, job_id: str) -> dict[str, Any] | None:
        with self._lock:
            item = next(
                (item for item in self._read_unlocked()["jobs"] if item.get("job_id") == job_id),
                None,
            )
            return deepcopy(item) if item else None

    def job_for_evidence(self, evidence_id: str) -> dict[str, Any] | None:
        with self._lock:
            matches = [
                item
                for item in self._read_unlocked()["jobs"]
                if item.get("evidence_id") == evidence_id
            ]
            matches.sort(key=lambda item: int(item.get("created_at_ms") or 0), reverse=True)
            return deepcopy(matches[0]) if matches else None

    def mark_running(self, job_id: str, *, started_at_ms: int) -> dict[str, Any] | None:
        return self._update(
            job_id,
            {"status": "running", "started_at_ms": int(started_at_ms), "error": None},
            allowed={"pending", "running"},
        )

    def mark_hint_timeout(self, job_id: str) -> dict[str, Any] | None:
        return self._update(job_id, {"hint_timed_out": True}, allowed=None)

    def finish_job(
        self,
        job_id: str,
        *,
        detections: list[dict[str, Any]],
        latency_ms: float,
        completed_at_ms: int,
        input_width: int | None = None,
        input_height: int | None = None,
        worker_metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        normalized = [
            normalize_detection(
                item,
                input_width=input_width,
                input_height=input_height,
            )
            for item in detections
        ]
        updated = self._update(
            job_id,
            {
                "status": "ready" if normalized else "ready_empty",
                "detections": normalized,
                "latency_ms": float(latency_ms),
                "completed_at_ms": int(completed_at_ms),
                "input_width": input_width,
                "input_height": input_height,
                "worker_metadata": dict(worker_metadata or {}),
                "error": None,
            },
            allowed={"pending", "running"},
        )
        if updated is None:
            existing = self.get_job(job_id)
            if existing is None:
                raise KeyError(job_id)
            return existing
        return updated

    def fail_job(self, job_id: str, *, error: str, completed_at_ms: int) -> dict[str, Any] | None:
        return self._update(
            job_id,
            {
                "status": "failed",
                "error": str(error),
                "completed_at_ms": int(completed_at_ms),
            },
            allowed={"pending", "running"},
        )

    def mark_stale(self, job_id: str, *, completed_at_ms: int) -> dict[str, Any] | None:
        return self._update(
            job_id,
            {"status": "stale", "completed_at_ms": int(completed_at_ms)},
            allowed={"pending", "running"},
        )

    def recent_jobs(self, *, limit: int = 50) -> list[dict[str, Any]]:
        with self._lock:
            return deepcopy(self._read_unlocked()["jobs"][: max(0, limit)])

    def summary(self) -> dict[str, Any]:
        jobs = self.recent_jobs(limit=self.max_jobs)
        counts: dict[str, int] = {}
        latencies = []
        for item in jobs:
            status = str(item.get("status") or "unknown")
            counts[status] = counts.get(status, 0) + 1
            if item.get("latency_ms") is not None:
                latencies.append(float(item["latency_ms"]))
        latencies.sort()
        return {
            "total": len(jobs),
            "counts": counts,
            "queue_depth": sum(counts.get(item, 0) for item in ("pending", "running")),
            "p50_latency_ms": _percentile(latencies, 0.50),
            "p95_latency_ms": _percentile(latencies, 0.95),
        }

    def recover_incomplete(self, *, now_ms: int, stale_ms: int) -> list[dict[str, Any]]:
        recovered = []
        for item in self.recent_jobs(limit=self.max_jobs):
            if item.get("status") not in {"pending", "running"}:
                continue
            if now_ms - int(item.get("created_at_ms") or 0) > stale_ms:
                self.mark_stale(item["job_id"], completed_at_ms=now_ms)
            else:
                self._update(item["job_id"], {"status": "pending"}, allowed={"pending", "running"})
                recovered.append(self.get_job(item["job_id"]))
        return [item for item in recovered if item]

    def _update(
        self,
        job_id: str,
        changes: dict[str, Any],
        *,
        allowed: set[str] | None,
    ) -> dict[str, Any] | None:
        with self._lock:
            data = self._read_unlocked()
            for item in data["jobs"]:
                if item.get("job_id") != job_id:
                    continue
                if allowed is not None and item.get("status") not in allowed:
                    return None
                item.update(changes)
                self._write_unlocked(data)
                return deepcopy(item)
            return None

    def _read_unlocked(self) -> dict[str, list[dict[str, Any]]]:
        if not self.path.exists():
            return {"jobs": []}
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {"jobs": []}
        jobs = payload.get("jobs") if isinstance(payload, dict) else []
        return {"jobs": [item for item in jobs or [] if isinstance(item, dict)]}

    def _write_unlocked(self, data: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_name(f".{self.path.name}.{os.getpid()}.tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
        os.replace(tmp, self.path)


def _percentile(values: list[float], quantile: float) -> float | None:
    if not values:
        return None
    index = min(len(values) - 1, max(0, round((len(values) - 1) * quantile)))
    return round(values[index], 3)
