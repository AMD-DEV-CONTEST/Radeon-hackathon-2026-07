"""
Tests for BatchScheduler thread serialization and timing.
"""

import time
import threading
from concurrent.futures import ThreadPoolExecutor
from warden.routing.batch_scheduler import BatchScheduler
from warden.tiers.base import CheckResult
from warden.config import Decision


def test_batch_scheduler_size_trigger():
    execution_count = 0

    def mock_executor(texts, contexts):
        nonlocal execution_count
        execution_count += 1
        return [
            CheckResult(decision=Decision.ALLOW, confidence=0.1, tier=2, explanation=f"ok {i}")
            for i, _ in enumerate(texts)
        ]

    scheduler = BatchScheduler(executor_fn=mock_executor, max_batch_size=3, batch_window_ms=500)

    # Submit 3 items concurrently via thread pool so they fill the batch size trigger
    with ThreadPoolExecutor(max_workers=3) as pool:
        futures = [pool.submit(scheduler.submit, f"item {i}", "") for i in range(3)]
        results = [f.result() for f in futures]

    assert len(results) == 3
    assert all(r.decision == Decision.ALLOW for r in results)
    assert execution_count == 1  # Collapsed 3 checks into 1 executor invocation
    scheduler.shutdown()


def test_batch_scheduler_timeout_trigger():
    execution_count = 0

    def mock_executor(texts, contexts):
        nonlocal execution_count
        execution_count += 1
        return [
            CheckResult(decision=Decision.ALLOW, confidence=0.1, tier=2, explanation="timeout batch")
            for _ in texts
        ]

    # Fast timeout window (50ms)
    scheduler = BatchScheduler(executor_fn=mock_executor, max_batch_size=10, batch_window_ms=50)
    
    # Only submit 1 item — should trigger on timeout, not batch size
    start = time.perf_counter()
    result = scheduler.submit("lonely item", "")
    elapsed = (time.perf_counter() - start) * 1000

    assert execution_count == 1
    assert elapsed >= 5  # Should have waited around 10ms for adaptive single-item window
    scheduler.shutdown()


def test_batch_scheduler_serialization_lock():
    """Verify that concurrent batch executions don't intertwine or cause thread race exceptions."""
    active_workers = 0
    max_concurrent_workers = 0
    lock = threading.Lock()

    def slow_executor(texts, contexts):
        nonlocal active_workers, max_concurrent_workers
        with lock:
            active_workers += 1
            max_concurrent_workers = max(max_concurrent_workers, active_workers)
        time.sleep(0.05)  # Simulate slow GPU compute
        with lock:
            active_workers -= 1
        return [CheckResult(decision=Decision.ALLOW, confidence=0.1, tier=2) for _ in texts]

    scheduler = BatchScheduler(executor_fn=slow_executor, max_batch_size=2, batch_window_ms=20)

    with ThreadPoolExecutor(max_workers=6) as pool:
        futures = [pool.submit(scheduler.submit, f"item {i}", "") for i in range(6)]
        results = [f.result() for f in futures]

    assert len(results) == 6
    # Due to _execution_lock, max concurrent executions inside executor_fn must strictly be 1
    assert max_concurrent_workers == 1
    scheduler.shutdown()
