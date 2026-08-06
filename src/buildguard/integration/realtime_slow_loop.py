"""Bounded background bridge from realtime detection to deliberate analysis."""

from __future__ import annotations

import logging
import queue
import threading
from collections.abc import Callable

from buildguard.realtime.schemas import RealtimeRiskEvent

LOGGER = logging.getLogger(__name__)


class RealtimeSlowLoop:
    """Keep RAG, risk, report drafting and notifications off camera workers."""

    def __init__(
        self,
        handler: Callable[[RealtimeRiskEvent], object],
        *,
        max_queue_size: int = 100,
        max_attempts: int = 3,
        retry_initial_seconds: float = 0.25,
        retry_multiplier: float = 2.0,
    ) -> None:
        if max_attempts < 1:
            raise ValueError("Realtime slow-loop max_attempts must be positive")
        if retry_initial_seconds < 0 or retry_multiplier < 1:
            raise ValueError("Realtime slow-loop retry policy is invalid")
        self.handler = handler
        self.queue: queue.Queue[RealtimeRiskEvent] = queue.Queue(max_queue_size)
        self.stop_event = threading.Event()
        self.accepted = 0
        self.completed = 0
        self.failed = 0
        self.retried = 0
        self.dead_lettered = 0
        self.max_attempts = max_attempts
        self.retry_initial_seconds = retry_initial_seconds
        self.retry_multiplier = retry_multiplier
        self.thread: threading.Thread | None = None
        self.thread_lock = threading.Lock()

    def _start(self) -> None:
        """Start the worker on first use so app factories do not leak idle threads."""
        with self.thread_lock:
            if self.thread is not None:
                return
            self.thread = threading.Thread(
                target=self._run,
                name="buildguard-realtime-slow-loop",
                daemon=True,
            )
            self.thread.start()

    def submit(self, event: RealtimeRiskEvent) -> bool:
        if self.stop_event.is_set():
            self.failed += 1
            LOGGER.warning("Realtime slow-loop is closed; event %s retained in DB", event.id)
            return False
        self._start()
        try:
            self.queue.put_nowait(event.model_copy(deep=True))
            self.accepted += 1
            return True
        except queue.Full:
            self.failed += 1
            LOGGER.error("Realtime slow-loop queue is full; event %s retained in DB", event.id)
            return False

    def _handle_with_retry(self, event: RealtimeRiskEvent) -> bool:
        delay = self.retry_initial_seconds
        for attempt in range(1, self.max_attempts + 1):
            try:
                self.handler(event)
                return True
            except Exception:
                if attempt >= self.max_attempts:
                    LOGGER.exception(
                        "Realtime slow-loop event %s exhausted %s attempts",
                        event.id,
                        self.max_attempts,
                    )
                    return False
                self.retried += 1
                LOGGER.exception(
                    "Realtime slow-loop event %s failed attempt %s; retrying",
                    event.id,
                    attempt,
                )
                if self.stop_event.wait(delay):
                    return False
                delay *= self.retry_multiplier
        return False

    def _run(self) -> None:
        while not self.stop_event.is_set() or not self.queue.empty():
            try:
                event = self.queue.get(timeout=0.2)
            except queue.Empty:
                continue
            try:
                if self._handle_with_retry(event):
                    self.completed += 1
                else:
                    self.failed += 1
                    self.dead_lettered += 1
            finally:
                self.queue.task_done()

    def metrics(self) -> dict[str, int]:
        return {
            "queue_length": self.queue.qsize(),
            "accepted": self.accepted,
            "completed": self.completed,
            "failed": self.failed,
        }

    def reliability_metrics(self) -> dict[str, int]:
        """Return retry details without changing the established metrics contract."""
        return {
            "retried": self.retried,
            "dead_lettered": self.dead_lettered,
        }

    def close(self) -> None:
        self.stop_event.set()
        if self.thread is not None:
            self.thread.join(timeout=5)
