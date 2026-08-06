"""Atomic JSON project storage (contract section 5).

Layout (under ``data_dir``):

- ``projects/<pid>/project.json``            Project
- ``projects/<pid>/policy.json``             PolicySpec
- ``projects/<pid>/events.json``             list[RedactionEvent]
- ``projects/<pid>/jobs.json``               list[Job]
- ``projects/<pid>/review_history.jsonl``    append-only review log
- ``jobs_index.json``                        {job_id: project_id}

All writes are atomic (tmp file + ``os.replace``); all reads tolerate
missing or corrupt files. Pure python + pydantic — no torch/ffmpeg.
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from policycut.core.ids import new_project_id
from policycut.core.models import Job, Project, RedactionEvent

logger = logging.getLogger(__name__)

__all__ = ["ProjectStore", "utc_now_iso", "atomic_write_json"]


def utc_now_iso() -> str:
    """Current UTC time as compact ISO 8601 with Z suffix."""
    return (
        datetime.now(timezone.utc)
        .isoformat(timespec="milliseconds")
        .replace("+00:00", "Z")
    )


def atomic_write_json(path: Path, payload: Any) -> None:
    """Serialize ``payload`` to JSON and atomically replace ``path``."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.parent / f".{path.name}.{uuid.uuid4().hex[:8]}.tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, ensure_ascii=False, indent=2)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
    finally:
        if tmp.exists():
            try:
                tmp.unlink()
            except OSError:
                pass


def _read_json(path: Path) -> Any:
    """Tolerant JSON read: returns None on missing/corrupt file."""
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except FileNotFoundError:
        return None
    except (json.JSONDecodeError, OSError) as exc:
        logger.warning("Unreadable JSON file %s: %s", path.name, exc)
        return None


class ProjectStore:
    """Filesystem-backed store for projects, events, policies and jobs."""

    def __init__(self, data_dir: Path):
        self.data_dir = Path(data_dir)
        self.projects_dir = self.data_dir / "projects"
        self.projects_dir.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()

    # -- paths --------------------------------------------------------------

    def project_dir(self, pid: str) -> Path:
        return self.projects_dir / pid

    def path(self, pid: str, *parts: str) -> Path:
        """Path inside the project dir; parent directories are created."""
        p = self.project_dir(pid).joinpath(*parts)
        p.parent.mkdir(parents=True, exist_ok=True)
        return p

    @property
    def jobs_index_path(self) -> Path:
        return self.data_dir / "jobs_index.json"

    # -- projects -----------------------------------------------------------

    def list_projects(self) -> list[Project]:
        projects: list[Project] = []
        if not self.projects_dir.exists():
            return projects
        for entry in sorted(self.projects_dir.iterdir()):
            if not entry.is_dir():
                continue
            raw = _read_json(entry / "project.json")
            if not isinstance(raw, dict):
                continue
            try:
                projects.append(Project.model_validate(raw))
            except Exception as exc:
                logger.warning("Skipping invalid project %s: %s", entry.name, exc)
        projects.sort(key=lambda p: p.updated_at, reverse=True)
        return projects

    def create_project(self, name: str) -> Project:
        now = utc_now_iso()
        project = Project(
            id=new_project_id(),
            name=name.strip() or "Untitled project",
            created_at=now,
            updated_at=now,
        )
        with self._lock:
            self.project_dir(project.id).mkdir(parents=True, exist_ok=True)
            atomic_write_json(
                self.project_dir(project.id) / "project.json",
                project.model_dump(mode="json"),
            )
        return project

    def get_project(self, pid: str) -> Project | None:
        raw = _read_json(self.project_dir(pid) / "project.json")
        if not isinstance(raw, dict):
            return None
        try:
            return Project.model_validate(raw)
        except Exception as exc:
            logger.warning("Invalid project.json for %s: %s", pid, exc)
            return None

    def save_project(self, project: Project) -> None:
        project.updated_at = utc_now_iso()
        with self._lock:
            atomic_write_json(
                self.project_dir(project.id) / "project.json",
                project.model_dump(mode="json"),
            )

    def delete_project(self, pid: str) -> None:
        with self._lock:
            shutil.rmtree(self.project_dir(pid), ignore_errors=True)
            index = self._load_jobs_index()
            pruned = {jid: p for jid, p in index.items() if p != pid}
            if pruned != index:
                atomic_write_json(self.jobs_index_path, pruned)

    # -- events ---------------------------------------------------------------

    def load_events(self, pid: str) -> list[RedactionEvent]:
        raw = _read_json(self.project_dir(pid) / "events.json")
        items = raw.get("events") if isinstance(raw, dict) else raw
        events: list[RedactionEvent] = []
        if not isinstance(items, list):
            return events
        for item in items:
            try:
                events.append(RedactionEvent.model_validate(item))
            except Exception as exc:
                logger.warning("Skipping invalid event in %s: %s", pid, exc)
        return events

    def save_events(self, pid: str, events: list[RedactionEvent]) -> None:
        with self._lock:
            atomic_write_json(
                self.project_dir(pid) / "events.json",
                [e.model_dump(mode="json") for e in events],
            )

    # -- policy ---------------------------------------------------------------

    def load_policy(self, pid: str):
        """Return the saved PolicySpec or None (tolerant)."""
        raw = _read_json(self.project_dir(pid) / "policy.json")
        if not isinstance(raw, dict):
            return None
        try:
            from policycut.policy.schema import PolicySpec  # lazy: keep core pure

            return PolicySpec.model_validate(raw)
        except ImportError:
            logger.warning("policy.schema unavailable; returning None for %s", pid)
            return None
        except Exception as exc:
            logger.warning("Invalid policy.json for %s: %s", pid, exc)
            return None

    def save_policy(self, pid: str, spec) -> None:
        """Persist a PolicySpec (pydantic model or plain dict)."""
        payload = spec.model_dump(mode="json") if hasattr(spec, "model_dump") else spec
        with self._lock:
            atomic_write_json(self.project_dir(pid) / "policy.json", payload)

    # -- jobs -----------------------------------------------------------------

    def load_jobs(self, pid: str) -> list[Job]:
        raw = _read_json(self.project_dir(pid) / "jobs.json")
        jobs: list[Job] = []
        if not isinstance(raw, list):
            return jobs
        for item in raw:
            try:
                jobs.append(Job.model_validate(item))
            except Exception as exc:
                logger.warning("Skipping invalid job in %s: %s", pid, exc)
        return jobs

    def save_job(self, job: Job) -> None:
        """Upsert a job into its project's jobs.json and the global index."""
        with self._lock:
            jobs = self.load_jobs(job.project_id)
            replaced = False
            for i, existing in enumerate(jobs):
                if existing.id == job.id:
                    jobs[i] = job
                    replaced = True
                    break
            if not replaced:
                jobs.append(job)
            atomic_write_json(
                self.project_dir(job.project_id) / "jobs.json",
                [j.model_dump(mode="json") for j in jobs],
            )
            index = self._load_jobs_index()
            if index.get(job.id) != job.project_id:
                index[job.id] = job.project_id
                atomic_write_json(self.jobs_index_path, index)

    def get_job(self, job_id: str) -> Job | None:
        index = self._load_jobs_index()
        pid = index.get(job_id)
        candidates = [pid] if pid else [p.id for p in self.list_projects()]
        for candidate in candidates:
            for job in self.load_jobs(candidate):
                if job.id == job_id:
                    return job
        return None

    def _load_jobs_index(self) -> dict[str, str]:
        raw = _read_json(self.jobs_index_path)
        if isinstance(raw, dict):
            return {str(k): str(v) for k, v in raw.items()}
        return {}

    # -- review history ---------------------------------------------------------

    def append_review_history(self, pid: str, entry: dict) -> None:
        """Append one JSON line to review_history.jsonl (adds ts if missing)."""
        record = dict(entry)
        record.setdefault("ts", utc_now_iso())
        path = self.path(pid, "review_history.jsonl")
        with self._lock:
            with open(path, "a", encoding="utf-8") as fh:
                fh.write(json.dumps(record, ensure_ascii=False) + "\n")
