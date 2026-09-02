"""Single-worker job queue (contract section 6).

One global JobQueue lives on ``app.state``. Jobs run sequentially on a
daemon worker thread. Progress is persisted through ProjectStore (throttled
to >= 0.3s between saves, forced on stage changes and terminal states); the
SSE endpoint polls the store, and in-memory subscriber queues are notified
for lower-latency streaming when desired.

Job functions have signature ``fn(job, progress_cb)`` or
``fn(job, progress_cb, cancel_event)`` — arity is detected so pipelines can
receive their cancellation event directly. ``JobCancelled`` may be raised
by a pipeline to abort cleanly.
"""

from __future__ import annotations

import inspect
import logging
import queue as _queue
import threading
import time
from typing import Callable, Optional

from policycut.core.models import Job
from policycut.core.storage import ProjectStore, utc_now_iso

logger = logging.getLogger(__name__)

__all__ = ["JobQueue", "JobCancelled", "ProgressCallback"]

# cb(stage, progress, message="", metrics=None)
ProgressCallback = Callable[..., None]

_SAVE_THROTTLE_S = 0.3
_SENTINEL = object()


class JobCancelled(Exception):
    """Raised inside a pipeline when its cancel event was set."""


class JobQueue:
    """Sequential background job executor with cancellation and progress."""

    def __init__(self, store: ProjectStore):
        self.store = store
        self._queue: _queue.Queue = _queue.Queue()
        self._lock = threading.RLock()
        self._cancel_events: dict[str, threading.Event] = {}
        self._subscribers: dict[str, list[_queue.Queue]] = {}
        self._current_job_id: str | None = None
        self._worker = threading.Thread(
            target=self._worker_loop, name="policycut-job-worker", daemon=True
        )
        self._worker.start()

    # -- public API -----------------------------------------------------------

    def submit(self, job: Job, fn: Callable) -> Job:
        """Queue a job for execution. Persists it as ``queued`` first."""
        job.status = "queued"
        job.created_at = job.created_at or utc_now_iso()
        with self._lock:
            self._cancel_events[job.id] = threading.Event()
        self.store.save_job(job)
        self._notify(job)
        self._queue.put((job, fn))
        logger.info("Job %s (%s) queued for project %s", job.id, job.type, job.project_id)
        return job

    def cancel(self, job_id: str) -> Job | None:
        """Request cancellation. Queued jobs are cancelled immediately;
        running jobs stop at their next cancellation checkpoint."""
        with self._lock:
            event = self._cancel_events.get(job_id)
            if event is not None:
                event.set()
            running = self._current_job_id == job_id
        job = self.store.get_job(job_id)
        if job is None:
            return None
        if job.status == "queued" and not running:
            job.status = "cancelled"
            job.finished_at = utc_now_iso()
            job.message = "Cancelled before start"
            self.store.save_job(job)
            self._notify(job)
        logger.info("Cancellation requested for job %s", job_id)
        return job

    def cancel_event(self, job_id: str) -> Optional[threading.Event]:
        """Return the cancel event for a job (for pipeline checkpoints)."""
        with self._lock:
            return self._cancel_events.get(job_id)

    def is_busy(self) -> bool:
        """True when a job is running or waiting in the queue."""
        with self._lock:
            return self._current_job_id is not None or not self._queue.empty()

    def recover(self, store: ProjectStore) -> int:
        """Mark jobs left queued/running by a previous process as
        ``server_restarted``. Call once at startup. Returns count fixed."""
        fixed = 0
        for project in store.list_projects():
            jobs = store.load_jobs(project.id)
            for job in jobs:
                if job.status in ("queued", "running"):
                    job.status = "server_restarted"
                    job.finished_at = job.finished_at or utc_now_iso()
                    job.message = "Server restarted while job was in progress"
                    store.save_job(job)
                    fixed += 1
            if project.status in ("analyzing", "rendering"):
                project.status = "error"
                project.error = "Interrupted by server restart"
                store.save_project(project)
        if fixed:
            logger.warning("Recovered %d stale job(s) after restart", fixed)
        return fixed

    # -- subscriptions (in-memory; SSE endpoint may also poll the store) -------

    def subscribe(self, job_id: str) -> _queue.Queue:
        """Register a subscriber queue receiving Job snapshots (dicts)."""
        q: _queue.Queue = _queue.Queue()
        with self._lock:
            self._subscribers.setdefault(job_id, []).append(q)
        return q

    def unsubscribe(self, job_id: str, q: _queue.Queue) -> None:
        with self._lock:
            subs = self._subscribers.get(job_id, [])
            if q in subs:
                subs.remove(q)
            if not subs:
                self._subscribers.pop(job_id, None)

    def shutdown(self) -> None:
        """Stop the worker after current job (used by tests)."""
        self._queue.put(_SENTINEL)

    # -- worker -----------------------------------------------------------------

    def _worker_loop(self) -> None:
        while True:
            item = self._queue.get()
            if item is _SENTINEL:
                return
            job, fn = item
            try:
                self._run_one(job, fn)
            except Exception:  # never kill the worker thread
                logger.exception("Unexpected worker error for job %s", job.id)
            finally:
                self._queue.task_done()

    def _run_one(self, job: Job, fn: Callable) -> None:
        with self._lock:
            cancel_event = self._cancel_events.setdefault(job.id, threading.Event())
            self._current_job_id = job.id

        # Refresh from store in case cancel() flipped it while queued.
        stored = self.store.get_job(job.id)
        if (stored is not None and stored.status == "cancelled") or cancel_event.is_set():
            job.status = "cancelled"
            job.finished_at = utc_now_iso()
            self.store.save_job(job)
            self._notify(job)
            self._finish(job.id)
            return

        job.status = "running"
        job.started_at = utc_now_iso()
        self.store.save_job(job)
        self._notify(job)

        last_save = [0.0]

        def progress_cb(
            stage: str,
            progress: float,
            message: str = "",
            metrics: dict | None = None,
        ) -> None:
            stage_changed = stage != job.stage
            job.stage = stage
            job.progress = max(0.0, min(1.0, float(progress)))
            if message:
                job.message = message
            if metrics:
                # Pipelines pass {STAGE_NAME: entry}; merge stage-keyed maps
                # directly so job.metrics stays flat ({stage: entry}).
                if all(isinstance(v, dict) for v in metrics.values()):
                    for key, entry in metrics.items():
                        merged = dict(job.metrics.get(key, {}))
                        merged.update(entry)
                        job.metrics[key] = merged
                else:
                    merged = dict(job.metrics.get(stage, {}))
                    merged.update(metrics)
                    job.metrics[stage] = merged
            now = time.monotonic()
            if stage_changed or (now - last_save[0]) >= _SAVE_THROTTLE_S:
                last_save[0] = now
                try:
                    self.store.save_job(job)
                except Exception:
                    logger.exception("Failed to persist progress for job %s", job.id)
            self._notify(job)

        try:
            self._call(fn, job, progress_cb, cancel_event)
            if cancel_event.is_set():
                job.status = "cancelled"
                job.message = job.message or "Cancelled"
            else:
                job.status = "done"
                job.progress = 1.0
        except JobCancelled:
            job.status = "cancelled"
            job.message = job.message or "Cancelled"
        except Exception as exc:
            if cancel_event.is_set():
                job.status = "cancelled"
                job.message = job.message or "Cancelled"
            else:
                logger.exception("Job %s failed", job.id)
                job.status = "error"
                job.error = f"{type(exc).__name__}: {exc}"
                job.message = job.error
        finally:
            job.finished_at = utc_now_iso()
            try:
                self.store.save_job(job)
            except Exception:
                logger.exception("Failed to persist final state for job %s", job.id)
            self._notify(job, final=True)
            self._finish(job.id)

    @staticmethod
    def _call(fn: Callable, job: Job, cb: ProgressCallback, cancel_event: threading.Event) -> None:
        """Invoke fn with (job, cb) or (job, cb, cancel_event) based on arity."""
        try:
            params = inspect.signature(fn).parameters
            positional = [
                p
                for p in params.values()
                if p.kind
                in (inspect.Parameter.POSITIONAL_ONLY, inspect.Parameter.POSITIONAL_OR_KEYWORD)
            ]
            wants_cancel = len(positional) >= 3 or any(
                p.kind == inspect.Parameter.VAR_POSITIONAL for p in params.values()
            )
        except (TypeError, ValueError):
            wants_cancel = False
        if wants_cancel:
            fn(job, cb, cancel_event)
        else:
            fn(job, cb)

    def _finish(self, job_id: str) -> None:
        with self._lock:
            self._current_job_id = None
            self._cancel_events.pop(job_id, None)

    def _notify(self, job: Job, final: bool = False) -> None:
        snapshot = job.model_dump(mode="json")
        if final:
            snapshot["_final"] = True
        with self._lock:
            subs = list(self._subscribers.get(job.id, []))
        for q in subs:
            try:
                q.put_nowait(snapshot)
            except Exception:
                pass
