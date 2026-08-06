"""Bounded background enforcement for configured workspace retention."""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable
from typing import Any

from buildguard.workspace.retention import RetentionCleaner, RetentionResult

LOGGER = logging.getLogger(__name__)
RetentionSink = Callable[[str, float, dict[str, Any]], None]


class RetentionLoop:
    """Run cleanup immediately and periodically; disabled policies never delete."""

    def __init__(
        self,
        cleaner: RetentionCleaner,
        interval_seconds: float,
        *,
        performance_sink: RetentionSink | None = None,
    ) -> None:
        if interval_seconds <= 0:
            raise ValueError("retention interval must be positive")
        self.cleaner = cleaner
        self.interval_seconds = interval_seconds
        self.performance_sink = performance_sink
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._lock = threading.RLock()
        self.last_result: RetentionResult | None = None

    def run_once(self) -> RetentionResult:
        started = time.perf_counter()
        result = self.cleaner.cleanup(dry_run=False)
        with self._lock:
            self.last_result = result
        if self.performance_sink is not None:
            self.performance_sink(
                "retention_cleanup",
                (time.perf_counter() - started) * 1000,
                {
                    "candidate_count": len(result.candidates),
                    "deleted_count": len(result.deleted),
                    "error_count": len(result.errors),
                },
            )
        return result

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                self.run_once()
            except Exception:
                LOGGER.exception("Automatic retention cleanup failed")
            if self._stop.wait(self.interval_seconds):
                break

    def start(self) -> None:
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                return
            self._stop.clear()
            self._thread = threading.Thread(
                target=self._run,
                name="buildguard-retention",
                daemon=True,
            )
            self._thread.start()

    def close(self, timeout_seconds: float = 5.0) -> None:
        self._stop.set()
        thread = self._thread
        if thread is not None:
            thread.join(timeout_seconds)
