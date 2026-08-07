"""Single-worker background jobs for the stdio daemon.

GPU work is deliberately serialized.  ``prepare`` and ``start`` are separate
so the daemon can flush the submit reply before a fast worker emits job.done.
"""

from __future__ import annotations

import threading
import uuid
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass
from typing import Any, Callable

from .errors import CancelledError, ExitCode, WorkshopError

Notify = Callable[[str, dict[str, Any]], None]


@dataclass(slots=True)
class JobContext:
    job_id: str
    cancel_event: threading.Event
    notify: Notify

    def progress(self, stage: str, done: int, total: int) -> None:
        self.check_cancelled()
        self.notify(
            "progress",
            {"job": self.job_id, "stage": stage, "done": done, "total": total},
        )

    def check_cancelled(self) -> None:
        if self.cancel_event.is_set():
            raise CancelledError("job cancelled", job=self.job_id)


@dataclass(slots=True)
class _Job:
    label: str
    worker: Callable[[JobContext], Any]
    cancel_event: threading.Event
    future: Future[Any] | None = None


class JobManager:
    def __init__(self, notify: Notify, *, max_workers: int = 1) -> None:
        self._notify = notify
        self._executor = ThreadPoolExecutor(
            max_workers=max_workers, thread_name_prefix="sprite-job"
        )
        self._jobs: dict[str, _Job] = {}
        self._lock = threading.Lock()

    def prepare(self, label: str, worker: Callable[[JobContext], Any]) -> str:
        job_id = uuid.uuid4().hex[:12]
        with self._lock:
            self._jobs[job_id] = _Job(label, worker, threading.Event())
        return job_id

    def start(self, job_id: str) -> None:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None or job.future is not None:
                return
            job.future = self._executor.submit(self._run, job_id, job)

    def cancel(self, job_id: str) -> bool:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                return False
            job.cancel_event.set()
            if job.future is not None:
                job.future.cancel()
            return True

    def _run(self, job_id: str, job: _Job) -> None:
        context = JobContext(job_id, job.cancel_event, self._notify)
        try:
            context.check_cancelled()
            result = job.worker(context)
            context.check_cancelled()
            payload = {"job": job_id, "ok": True, "result": result}
        except WorkshopError as error:
            payload = {"job": job_id, "ok": False, "error": error.to_dict()}
        except Exception as error:  # daemon boundary: never kill the worker
            payload = {
                "job": job_id,
                "ok": False,
                "error": {
                    "code": ExitCode.FAILED,
                    "message": str(error),
                    "details": None,
                },
            }
        self._notify("job.done", payload)
        with self._lock:
            self._jobs.pop(job_id, None)

    def shutdown(self) -> None:
        self._executor.shutdown(wait=False, cancel_futures=True)
