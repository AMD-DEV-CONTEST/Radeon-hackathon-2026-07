from __future__ import annotations

import copy
import pickle
import threading

import pytest


def _start_contender() -> tuple[threading.Event, threading.Event, threading.Thread]:
    from specstyle.generation.gpu_runtime_lane import acquire_gpu_runtime_lane

    started = threading.Event()
    acquired = threading.Event()

    def contend() -> None:
        started.set()
        with acquire_gpu_runtime_lane():
            acquired.set()

    thread = threading.Thread(target=contend, daemon=True)
    thread.start()
    assert started.wait(1.0)
    return started, acquired, thread


def test_runtime_lane_blocks_a_second_owner_until_the_first_closes() -> None:
    from specstyle.generation.gpu_runtime_lane import acquire_gpu_runtime_lane

    first = acquire_gpu_runtime_lane()
    _started, acquired, thread = _start_contender()
    try:
        assert not acquired.wait(0.1)
    finally:
        first.close()
    assert acquired.wait(1.0)
    thread.join(1.0)
    assert not thread.is_alive()


def test_runtime_lane_lease_is_idempotent_and_nontransferable() -> None:
    from specstyle.generation.gpu_runtime_lane import acquire_gpu_runtime_lane

    lease = acquire_gpu_runtime_lane()
    for operation in (copy.copy, copy.deepcopy, pickle.dumps):
        with pytest.raises(TypeError):
            operation(lease)
    lease.close()
    lease.close()

    with acquire_gpu_runtime_lane():
        pass


def test_runtime_lane_try_acquire_reports_busy_without_blocking() -> None:
    from specstyle.generation.gpu_runtime_lane import (
        acquire_gpu_runtime_lane,
        try_acquire_gpu_runtime_lane,
    )

    first = acquire_gpu_runtime_lane()
    try:
        assert try_acquire_gpu_runtime_lane() is None
    finally:
        first.close()
    second = try_acquire_gpu_runtime_lane()
    assert second is not None
    second.close()
