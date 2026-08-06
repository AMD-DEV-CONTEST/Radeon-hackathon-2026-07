"""
Batch Scheduler for Tier 2 GPU tasks.

Aggregates incoming checks and dispatches them in batches to maximize
GPU utilization on AMD Radeon hardware. Uses a timed queue approach.
"""

from __future__ import annotations

import logging
import threading
import time
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Callable, Any, Optional

from warden.tiers.base import CheckResult
from warden.config import Decision

logger = logging.getLogger(__name__)


@dataclass
class BatchItem:
    """A single item waiting for batch execution."""
    text: str
    context: str
    future: Future
    enqueued_at: float = field(default_factory=time.perf_counter)


class BatchScheduler:
    """
    Groups individual checks into batches for efficient GPU execution.

    Triggers a batch run when either:
    1. The queue reaches max_batch_size
    2. The oldest item in the queue has waited batch_window_ms
    """

    def __init__(
        self,
        executor_fn: Callable[[list[str], list[str]], list[CheckResult]],
        max_batch_size: int = 8,
        batch_window_ms: int = 100,
    ):
        """
        Args:
            executor_fn: The function that actually runs the batch on the GPU.
                         Takes lists of texts and contexts, returns list of CheckResults.
            max_batch_size: Maximum items per batch.
            batch_window_ms: Maximum time to wait before dispatching a partial batch.
        """
        self.executor_fn = executor_fn
        self.max_batch_size = max_batch_size
        self.batch_window_ms = batch_window_ms / 1000.0  # Convert to seconds

        self._queue: list[BatchItem] = []
        self._lock = threading.Lock()
        self._execution_lock = threading.Lock()
        self._thread_pool = ThreadPoolExecutor(max_workers=1)
        self._dispatch_timer: Optional[threading.Timer] = None
        self._running = True

    def submit(self, text: str, context: str = "", timeout: float = 30.0) -> CheckResult:
        """
        Submit a check and block until the batch result is ready.
        """
        future = Future()
        item = BatchItem(text=text, context=context, future=future)

        with self._lock:
            self._queue.append(item)
            queue_len = len(self._queue)

            # If we hit max batch size, dispatch immediately
            if queue_len >= self.max_batch_size:
                if self._dispatch_timer is not None:
                    self._dispatch_timer.cancel()
                    self._dispatch_timer = None
                batch_to_run = self._queue[:self.max_batch_size]
                self._queue = self._queue[self.max_batch_size:]
                self._thread_pool.submit(self._execute_batch, batch_to_run)
            
            # Otherwise, adaptive timer
            else:
                current_window = 0.01 if queue_len == 1 else self.batch_window_ms
                
                # If a second item arrives, expand the window to wait for more
                if queue_len == 2 and self._dispatch_timer is not None:
                    self._dispatch_timer.cancel()
                    self._dispatch_timer = None
                    
                if self._dispatch_timer is None:
                    self._dispatch_timer = threading.Timer(
                        current_window, self._dispatch_on_timeout
                    )
                    self._dispatch_timer.start()

        # Block until result is ready (or timeout)
        try:
            return future.result(timeout=timeout)
        except Exception as e:
            logger.error(f"Batch execution failed or timed out: {e}")
            return CheckResult(
                decision=Decision.UNCERTAIN,
                confidence=0.5,
                tier=2,
                explanation=f"Batch execution error: {e}",
                errored=True,
            )

    def _dispatch_on_timeout(self):
        """Called when the batch window expires."""
        with self._lock:
            if not self._queue:
                self._dispatch_timer = None
                return
            batch_to_run = self._queue[:]
            self._queue.clear()
            self._dispatch_timer = None

        if batch_to_run:
            self._thread_pool.submit(self._execute_batch, batch_to_run)

    def _execute_batch(self, batch: list[BatchItem]):
        """Run the actual batch execution and set future results."""
        if not batch:
            return

        texts = [item.text for item in batch]
        contexts = [item.context for item in batch]

        try:
            # Serialize actual GPU execution with lock to prevent llama-cpp thread crashes
            with self._execution_lock:
                results = self.executor_fn(texts, contexts)

            # Map results back to futures
            for item, result in zip(batch, results):
                if not item.future.done():
                    item.future.set_result(result)
                    
        except Exception as e:
            logger.error(f"Batch execution threw an exception: {e}")
            for item in batch:
                if not item.future.done():
                    item.future.set_exception(e)

    def shutdown(self):
        """Clean up resources."""
        self._running = False
        if self._dispatch_timer:
            self._dispatch_timer.cancel()
        self._thread_pool.shutdown(wait=False)
