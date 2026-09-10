from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
import threading

import pytest

from specstyle.domain.identifiers import JobId
from specstyle.ui.app import UiServices
from tests.unit.ui.test_production_run import (
    _BatchExecution,
    _batch_args,
    _batch_result,
    _roots,
)


def test_production_single_and_batch_share_the_same_active_run_lock(
    tmp_path: Path,
) -> None:
    from specstyle.ui.production_run import bind_production_run_one_services

    roots = _roots(tmp_path)
    first_running = threading.Event()
    release_first = threading.Event()
    variations: list[int] = []

    def reserve(variation_index: int):
        variations.append(variation_index)
        return SimpleNamespace(
            job_id=JobId(f"run-one-{len(variations)}"),
            variation_index=variation_index,
        )

    class _BlockingExecution(_BatchExecution):
        def run(self):
            if len(variations) == 1:
                first_running.set()
                assert release_first.wait(timeout=2)
            return super().run()

    def opener(_fds, reservation):
        sequence = len(variations)
        return _BlockingExecution(
            _batch_result(
                reservation.job_id.value,
                reservation.variation_index,
                100 + sequence,
                200 + sequence,
            )
        )

    service = bind_production_run_one_services(
        UiServices(lambda _text: pytest.fail("compile not used")),
        roots,
        reserve=reserve,
        open_run_one=opener,
    )
    completed: list[object] = []
    thread = threading.Thread(
        target=lambda: completed.append(
            service.run_production_batch(*_batch_args(tmp_path), 2)
        )
    )
    thread.start()
    assert first_running.wait(timeout=2)

    busy = service.run_production_job(*_batch_args(tmp_path))
    busy_batch = service.run_production_batch(*_batch_args(tmp_path), 2)
    assert variations == [0]
    release_first.set()
    thread.join(timeout=2)

    assert not thread.is_alive()
    assert busy.status == "BUSY"
    assert busy_batch.status == "BUSY"
    assert busy_batch.message == "production run busy"
    assert busy_batch.items == ()
    assert variations == [0, 2]
    assert completed[0].status == "COMPLETED"


def test_job_result_service_binding_preserves_the_batch_callable() -> None:
    from specstyle.ui.app import bind_job_result_services

    def batch(*_args: object) -> object:
        return object()

    base = UiServices(
        lambda _text: pytest.fail("compile not used"),
        run_production_batch=batch,
    )

    bound = bind_job_result_services(
        base,
        job_id="job-1",
        result=None,
        profile="production",
        on_cancel=None,
    )

    assert bound.run_production_batch is batch
