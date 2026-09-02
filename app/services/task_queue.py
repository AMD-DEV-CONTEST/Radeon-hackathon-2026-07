"""Stage J — Task Queue: concurrency control with global and per-project quotas.

Provides a semaphore-based queue that gates LLM and Embedding calls so that
the local GPU never receives more concurrent requests than configured.
Supports cancellation via user-provided ``asyncio.Event`` handles.
"""

from __future__ import annotations

import asyncio
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Coroutine

from app.config import Settings


@dataclass
class QueueStats:
    """Real-time metrics for the task queue."""

    active_llm_calls: int = 0
    active_embedding_calls: int = 0
    queued_calls: int = 0
    total_completed: int = 0
    total_cancelled: int = 0
    total_timeouts: int = 0
    total_errors: int = 0
    last_update: float = field(default_factory=time.time)


class TaskQueue:
    """Concurrency-controlled task queue with per-project quotas.

    Usage::

        queue = TaskQueue(settings)
        result = await queue.enqueue_llm(
            project_id="demo",
            cancel_event=asyncio.Event(),
            callable=my_async_llm_call()
        )
    """

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

        # Global semaphores
        # The production runner executes synchronous tools in worker threads.
        # Threading semaphores keep one quota across those separate event loops.
        self._llm_semaphore = threading.BoundedSemaphore(settings.global_max_concurrent_llm_calls)
        self._embedding_semaphore = threading.BoundedSemaphore(
            settings.global_max_concurrent_embedding_calls
        )

        # Per-project semaphores (lazy)
        self._project_llm_semaphores: dict[str, threading.BoundedSemaphore] = {}
        self._project_embedding_semaphores: dict[str, threading.BoundedSemaphore] = {}

        self._stats = QueueStats()
        self._lock = threading.Lock()

    @property
    def stats(self) -> QueueStats:
        with self._lock:
            self._stats.last_update = time.time()
            return QueueStats(**self._stats.__dict__)

    # ------------------------------------------------------------------
    # public API
    # ------------------------------------------------------------------

    async def enqueue_llm(
        self,
        project_id: str,
        *,
        cancel_event: asyncio.Event,
        callable: Callable[..., Coroutine[Any, Any, Any]],
        **kwargs: Any,
    ) -> Any:
        """Enqueue an LLM call with concurrent-limits gating.

        Waits for both the global and per-project semaphores, respects
        ``cancel_event``, and records metrics.
        """
        return await self._enqueue(
            project_id=project_id,
            global_sem=self._llm_semaphore,
            project_sems=self._project_llm_semaphores,
            max_per_project=self._settings.per_project_max_concurrent_llm_calls,
            timeout=self._settings.llm_call_queue_timeout_seconds,
            cancel_event=cancel_event,
            callable=callable,
            kind="llm",
            **kwargs,
        )

    async def enqueue_embedding(
        self,
        project_id: str,
        *,
        cancel_event: asyncio.Event,
        callable: Callable[..., Coroutine[Any, Any, Any]],
        **kwargs: Any,
    ) -> Any:
        """Enqueue an Embedding call with concurrent-limits gating."""
        return await self._enqueue(
            project_id=project_id,
            global_sem=self._embedding_semaphore,
            project_sems=self._project_embedding_semaphores,
            max_per_project=self._settings.per_project_max_concurrent_embedding_calls,
            timeout=self._settings.embedding_call_queue_timeout_seconds,
            cancel_event=cancel_event,
            callable=callable,
            kind="embedding",
            **kwargs,
        )

    async def status(self) -> dict[str, Any]:
        """Return current queue status as a dict for monitoring."""
        stats = self.stats
        return {
            "active_llm_calls": stats.active_llm_calls,
            "active_embedding_calls": stats.active_embedding_calls,
            "queued_calls": stats.queued_calls,
            "total_completed": stats.total_completed,
            "total_cancelled": stats.total_cancelled,
            "total_timeouts": stats.total_timeouts,
            "total_errors": stats.total_errors,
            "global_llm_capacity": self._settings.global_max_concurrent_llm_calls,
            "global_embedding_capacity": self._settings.global_max_concurrent_embedding_calls,
        }

    # ------------------------------------------------------------------
    # internal
    # ------------------------------------------------------------------

    async def _enqueue(
        self,
        project_id: str,
        global_sem: asyncio.Semaphore,
        project_sems: dict[str, threading.BoundedSemaphore],
        max_per_project: int,
        timeout: float,
        cancel_event: asyncio.Event,
        callable: Callable[..., Coroutine[Any, Any, Any]],
        kind: str,
        **kwargs: Any,
    ) -> Any:
        """Core enqueue logic shared between LLM and Embedding calls."""

        # Lazy per-project semaphore
        with self._lock:
            if project_id not in project_sems:
                project_sems[project_id] = threading.BoundedSemaphore(max_per_project)
            project_sem = project_sems[project_id]
            self._stats.queued_calls += 1

        # Acquire both semaphores with timeout
        try:
            # Acquire project quota first (finer granularity), then global
            # quota.  Polling lets cancellation interrupt a queued request.
            await self._acquire(project_sem, cancel_event, timeout)
            try:
                await self._acquire(global_sem, cancel_event, timeout)
            except BaseException:
                project_sem.release()
                raise
        except asyncio.TimeoutError:
            with self._lock:
                self._stats.queued_calls -= 1
                self._stats.total_timeouts += 1
            raise RuntimeError(
                f"{kind.upper()} call for project {project_id!r} timed out "
                f"waiting for a slot (timeout={timeout}s)"
            )
        except asyncio.CancelledError:
            with self._lock:
                self._stats.queued_calls -= 1
                self._stats.total_cancelled += 1
            raise

        # Bump active counters
        with self._lock:
            if kind == "llm":
                self._stats.active_llm_calls += 1
            else:
                self._stats.active_embedding_calls += 1
            self._stats.queued_calls -= 1

        try:
            # Check for cancellation before execution
            if cancel_event.is_set():
                with self._lock:
                    self._stats.total_cancelled += 1
                raise asyncio.CancelledError(
                    f"{kind.upper()} call for project {project_id!r} was cancelled"
                )

            result = await callable(**kwargs)
            with self._lock:
                self._stats.total_completed += 1
            return result
        except asyncio.CancelledError:
            with self._lock:
                self._stats.total_cancelled += 1
            raise
        except Exception:
            with self._lock:
                self._stats.total_errors += 1
            raise
        finally:
            with self._lock:
                if kind == "llm":
                    self._stats.active_llm_calls = max(0, self._stats.active_llm_calls - 1)
                else:
                    self._stats.active_embedding_calls = max(
                        0, self._stats.active_embedding_calls - 1
                    )
            project_sem.release()
            global_sem.release()

    async def _acquire(
        self,
        semaphore: threading.BoundedSemaphore,
        cancel_event: asyncio.Event,
        timeout: float,
    ) -> None:
        deadline = time.monotonic() + timeout
        while True:
            if cancel_event.is_set():
                raise asyncio.CancelledError("queue request was cancelled before execution")
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise asyncio.TimeoutError
            acquired = await asyncio.to_thread(semaphore.acquire, True, min(0.1, remaining))
            if acquired:
                return


# Singleton-style module-level accessor
_task_queue_instance: TaskQueue | None = None


def get_task_queue(settings: Settings | None = None) -> TaskQueue:
    """Return the module-level TaskQueue instance, creating it if needed."""
    global _task_queue_instance
    if _task_queue_instance is None:
        if settings is None:
            settings = Settings()
        _task_queue_instance = TaskQueue(settings)
    return _task_queue_instance
