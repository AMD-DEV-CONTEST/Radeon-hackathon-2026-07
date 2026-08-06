from __future__ import annotations

from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor, TimeoutError as FutureTimeoutError
from contextlib import nullcontext
from datetime import UTC, datetime
import json
from pathlib import Path
import shutil
import threading
from typing import Any
from uuid import uuid4

from agent_factory.create_agent.workspace import CreateAgentWorkspace


ProbeJobProgress = Callable[[str, dict[str, Any]], None]
ProbeJobExecution = Callable[
    [CreateAgentWorkspace, ProbeJobProgress, threading.Event],
    dict[str, Any],
]

ACTIVE_PROBE_JOB_STATUSES = {"queued", "running", "cancellation_requested"}
TERMINAL_PROBE_JOB_STATUSES = {"completed", "failed", "cancelled", "interrupted"}


class ProbeJobManager:
    """Process-local worker pool with durable workspace-owned probe job records."""

    def __init__(self) -> None:
        self._executor: ThreadPoolExecutor | None = None
        self._lock = threading.RLock()
        self._futures: dict[str, Future[None]] = {}
        self._cancel_events: dict[str, threading.Event] = {}
        self._execution_locks: dict[tuple[str, str], threading.Lock] = {}

    def submit(
        self,
        *,
        workspace: CreateAgentWorkspace,
        request: dict[str, Any],
        execute: ProbeJobExecution,
    ) -> dict[str, Any]:
        job_id = uuid4().hex
        store = ProbeJobStore(workspace)
        snapshot = store.create(job_id=job_id, request=request)
        cancel_event = threading.Event()
        future = self._executor_for_submit().submit(
            self._run_job,
            workspace,
            job_id,
            snapshot,
            request,
            execute,
            cancel_event,
        )
        with self._lock:
            self._futures[job_id] = future
            self._cancel_events[job_id] = cancel_event
        future.add_done_callback(lambda _future: self._forget(job_id))
        return store.read(job_id)

    def status(
        self,
        *,
        workspace: CreateAgentWorkspace,
        job_id: str,
        wait_seconds: float | None = None,
    ) -> dict[str, Any]:
        future = self._future(job_id)
        if future is not None and wait_seconds is not None and wait_seconds > 0:
            try:
                future.result(timeout=wait_seconds)
            except FutureTimeoutError:
                pass
        return self._recover_or_read(ProbeJobStore(workspace), job_id)

    def list(self, *, workspace: CreateAgentWorkspace) -> list[dict[str, Any]]:
        store = ProbeJobStore(workspace)
        return [
            _job_summary(
                self._recover_or_read(store, str(item.get("job_id") or ""))
            )
            for item in store.list()
        ]

    def cancel(self, *, workspace: CreateAgentWorkspace, job_id: str) -> dict[str, Any]:
        store = ProbeJobStore(workspace)
        current = self._recover_or_read(store, job_id)
        if current.get("status") in TERMINAL_PROBE_JOB_STATUSES:
            return current
        with self._lock:
            cancel_event = self._cancel_events.get(job_id)
            future = self._futures.get(job_id)
        if cancel_event is not None:
            cancel_event.set()
        if future is not None and future.cancel():
            return store.update(
                job_id,
                status="cancelled",
                stage="cancelled",
                completed_at=_now(),
                message="Tool probe cancelled.",
            )
        return store.update(
            job_id,
            status="cancellation_requested",
            message="Tool-probe cancellation requested.",
        )

    def shutdown(self) -> None:
        with self._lock:
            cancel_events = list(self._cancel_events.values())
            executor = self._executor
            self._executor = None
        for cancel_event in cancel_events:
            cancel_event.set()
        if executor is not None:
            executor.shutdown(wait=False, cancel_futures=True)

    def _run_job(
        self,
        workspace: CreateAgentWorkspace,
        job_id: str,
        snapshot: CreateAgentWorkspace,
        request: dict[str, Any],
        execute: ProbeJobExecution,
        cancel_event: threading.Event,
    ) -> None:
        store = ProbeJobStore(workspace)
        store.update(
            job_id,
            status="running",
            stage="preparing_snapshot",
            started_at=_now(),
            message="Preparing the tool-probe snapshot.",
        )

        def progress(stage: str, detail: dict[str, Any]) -> None:
            store.record_progress(job_id, stage=stage, detail=detail)

        try:
            store.materialize_snapshot(snapshot)
            if cancel_event.is_set():
                store.update(
                    job_id,
                    status="cancelled",
                    stage="cancelled",
                    completed_at=_now(),
                    message="Tool probe cancelled.",
                )
                return
            execution_lock = self._execution_lock(workspace, request)
            if execution_lock is not None and execution_lock.locked():
                progress(
                    "waiting_for_tool_slot",
                    {
                        "message": "Waiting for an earlier probe of the same tool to finish.",
                        "tool_id": request.get("tool_id"),
                    },
                )
            execution_context = execution_lock if execution_lock is not None else nullcontext()
            with execution_context:
                result = execute(snapshot, progress, cancel_event)
            cancelled = cancel_event.is_set()
            store.update(
                job_id,
                status="cancelled" if cancelled else "completed",
                stage="cancelled" if cancelled else "completed",
                completed_at=_now(),
                message="Tool probe cancelled." if cancelled else "Tool probe completed.",
                result=result,
            )
        except Exception as exc:
            store.update(
                job_id,
                status="failed",
                stage="failed",
                completed_at=_now(),
                message=f"{type(exc).__name__}: {exc}",
                error={"type": type(exc).__name__, "message": str(exc)},
            )

    def _recover_or_read(self, store: "ProbeJobStore", job_id: str) -> dict[str, Any]:
        current = store.read(job_id)
        if current.get("status") not in ACTIVE_PROBE_JOB_STATUSES:
            return current
        if self._future(job_id) is not None:
            return current
        return store.update(
            job_id,
            status="interrupted",
            stage="interrupted",
            completed_at=_now(),
            message="The backend restarted and interrupted unfinished tool probes.",
        )

    def _future(self, job_id: str) -> Future[None] | None:
        with self._lock:
            return self._futures.get(job_id)

    def _executor_for_submit(self) -> ThreadPoolExecutor:
        with self._lock:
            if self._executor is None:
                self._executor = ThreadPoolExecutor(thread_name_prefix="create-agent-probe")
            return self._executor

    def _execution_lock(
        self,
        workspace: CreateAgentWorkspace,
        request: dict[str, Any],
    ) -> threading.Lock | None:
        if request.get("concurrent") is True:
            return None
        key = (str(workspace.root), str(request.get("tool_id") or ""))
        with self._lock:
            lock = self._execution_locks.get(key)
            if lock is None:
                lock = threading.Lock()
                self._execution_locks[key] = lock
            return lock

    def _forget(self, job_id: str) -> None:
        with self._lock:
            self._futures.pop(job_id, None)
            self._cancel_events.pop(job_id, None)


class ProbeJobStore:
    def __init__(self, workspace: CreateAgentWorkspace) -> None:
        self.workspace = workspace
        self.root = workspace.factory_dir / "probe_jobs"
        self._lock = threading.RLock()

    def create(self, *, job_id: str, request: dict[str, Any]) -> CreateAgentWorkspace:
        job_root = self.root / job_id
        job_root.mkdir(parents=True, exist_ok=False)
        payload = {
            "version": "create_agent_probe_job.v1",
            "job_id": job_id,
            "workspace_path": str(self.workspace.root),
            "snapshot_path": str(job_root / "snapshot"),
            "status": "queued",
            "stage": "queued",
            "message": "The tool probe entered the background queue.",
            "request": request,
            "latest_progress": {},
            "stage_history": [],
            "progress_sequence": 0,
            "result": None,
            "error": None,
            "created_at": _now(),
            "started_at": None,
            "updated_at": _now(),
            "completed_at": None,
        }
        self._write(job_id, payload)
        return CreateAgentWorkspace(job_root / "snapshot")

    def materialize_snapshot(self, snapshot: CreateAgentWorkspace) -> None:
        shutil.copytree(
            self.workspace.root,
            snapshot.root,
            ignore=shutil.ignore_patterns(".factory", ".agent_runtime", "__pycache__"),
        )

    def read(self, job_id: str) -> dict[str, Any]:
        path = self._job_path(job_id)
        if not path.is_file():
            raise ValueError(f"probe job not found: {job_id}")
        value = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(value, dict):
            raise ValueError(f"probe job record is invalid: {job_id}")
        return value

    def list(self) -> list[dict[str, Any]]:
        if not self.root.is_dir():
            return []
        jobs: list[dict[str, Any]] = []
        for path in self.root.glob("*/job.json"):
            try:
                value = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if isinstance(value, dict):
                jobs.append(value)
        return sorted(jobs, key=lambda item: str(item.get("created_at") or ""), reverse=True)

    def update(self, job_id: str, **changes: Any) -> dict[str, Any]:
        with self._lock:
            current = self.read(job_id)
            updated = {**current, **changes, "updated_at": _now()}
            self._write(job_id, updated)
            return updated

    def record_progress(self, job_id: str, *, stage: str, detail: dict[str, Any]) -> None:
        with self._lock:
            current = self.read(job_id)
            sequence = int(current.get("progress_sequence") or 0) + 1
            event = {
                "sequence": sequence,
                "timestamp": _now(),
                "stage": stage,
                "detail": detail,
            }
            event_path = self._job_root(job_id) / "events.jsonl"
            with event_path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(event, ensure_ascii=False) + "\n")
            stage_history = list(current.get("stage_history") or [])
            if not stage_history or stage_history[-1].get("stage") != stage:
                stage_history.append(
                    {
                        "sequence": sequence,
                        "timestamp": event["timestamp"],
                        "stage": stage,
                    }
                )
            self._write(
                job_id,
                {
                    **current,
                    "stage": stage,
                    "message": str(detail.get("message") or current.get("message") or ""),
                    "latest_progress": event,
                    "stage_history": stage_history,
                    "progress_sequence": sequence,
                    "updated_at": event["timestamp"],
                },
            )

    def _write(self, job_id: str, payload: dict[str, Any]) -> None:
        path = self._job_path(job_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
        temporary.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        temporary.replace(path)

    def _job_root(self, job_id: str) -> Path:
        safe_job_id = "".join(char for char in job_id if char.isalnum() or char in {"-", "_"})
        if not safe_job_id or safe_job_id != job_id:
            raise ValueError("invalid probe job id")
        return self.root / safe_job_id

    def _job_path(self, job_id: str) -> Path:
        return self._job_root(job_id) / "job.json"


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _job_summary(job: dict[str, Any]) -> dict[str, Any]:
    request = job.get("request") if isinstance(job.get("request"), dict) else {}
    return {
        "job_id": job.get("job_id"),
        "tool_id": request.get("tool_id"),
        "package_digest": request.get("package_digest"),
        "status": job.get("status"),
        "stage": job.get("stage"),
        "message": job.get("message"),
        "latest_progress": job.get("latest_progress"),
        "progress_sequence": job.get("progress_sequence"),
        "created_at": job.get("created_at"),
        "started_at": job.get("started_at"),
        "updated_at": job.get("updated_at"),
        "completed_at": job.get("completed_at"),
    }


probe_job_manager = ProbeJobManager()
