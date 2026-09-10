from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
import gc
import threading
import weakref

import pytest

from specstyle.domain.identifiers import ArtifactId, JobId, Sha256
from specstyle.errors import DomainError, InfrastructureError
from specstyle.exporting.bundle import ExportedFile
from specstyle.ui.app import UiServices
from specstyle.workflow.run_one import ProductionRunOneCleanupError
from tests.unit.ui.test_production_run import (
    _BatchExecution,
    _batch_args,
    _batch_result,
    _qa_report,
    _roots,
    _uploads,
)


def _unexpected(*_args: object) -> object:
    pytest.fail("base placeholder handler must not be used by production")


def test_production_binding_replaces_placeholder_state_handlers(
    tmp_path: Path,
) -> None:
    from specstyle.ui.production_run import bind_production_run_one_services

    base = UiServices(
        lambda _text: pytest.fail("compile not used"),
        get_job_status=_unexpected,
        cancel_job=_unexpected,
        get_qa_table=_unexpected,
        get_repair_timeline=_unexpected,
        get_export_summary=_unexpected,
        run_replay=_unexpected,
    )

    services = bind_production_run_one_services(base, _roots(tmp_path))

    status = services.get_job_status()
    assert status.job_id == ""
    assert status.status == "IDLE"
    assert status.profile_label == "production"
    assert status.can_cancel is False
    assert status.message == "no production run"
    assert services.cancel_job() == "cancel unavailable; no active production run"
    assert services.get_qa_table() == "no qa"
    assert services.get_repair_timeline() == "no repair"
    assert services.get_export_summary() == "no export"
    assert (
        services.run_replay(
            *_uploads(tmp_path),
            "positive",
            "",
            None,
            None,
            None,
            "not_applicable",
        )
        == "replay unavailable: run one successful production job first"
    )


def test_successful_production_run_updates_real_state_projections(
    tmp_path: Path,
) -> None:
    from specstyle.ui.production_run import bind_production_run_one_services

    roots = _roots(tmp_path)
    approved = roots.export_root / "bundle-run-one-state" / "approved" / "xhs_grid"
    approved.mkdir(parents=True)
    image = approved / "artifact-state.png"
    image.write_bytes(b"png")

    result = SimpleNamespace(
        job_result=SimpleNamespace(
            report=_qa_report(),
            history=SimpleNamespace(
                initial_attempt=SimpleNamespace(
                    artifact=SimpleNamespace(
                        ref=SimpleNamespace(artifact_id=ArtifactId("artifact-initial"))
                    )
                ),
                repair_attempts=(),
            ),
            terminal=SimpleNamespace(
                artifact_decision=SimpleNamespace(
                    repair_stop_reason=SimpleNamespace(value="PASS_ALL_REQUIRED")
                )
            ),
        ),
        export_result=SimpleNamespace(
            bundle=SimpleNamespace(
                bundle_name="bundle-run-one-state",
                bundle_sha256=Sha256("d" * 64),
                files=(
                    ExportedFile(
                        "approved/xhs_grid/artifact-state.png",
                        Sha256("e" * 64),
                        3,
                    ),
                ),
            ),
            job_state=SimpleNamespace(
                job=SimpleNamespace(
                    job_id=JobId("run-one-state"),
                    status=SimpleNamespace(value="COMPLETED"),
                )
            ),
        ),
    )

    class _Execution:
        def run(self) -> object:
            return result

        def close(self) -> None:
            pass

    services = bind_production_run_one_services(
        UiServices(lambda _text: pytest.fail("compile not used")),
        roots,
        reserve=lambda: SimpleNamespace(job_id=JobId("run-one-state")),
        open_run_one=lambda _fds, _reservation: _Execution(),
    )

    view = services.run_production_job(
        *_uploads(tmp_path),
        "positive",
        "",
        None,
        None,
        None,
        "not_applicable",
    )

    assert view.status == "COMPLETED"
    status = services.get_job_status()
    assert status.job_id == "run-one-state"
    assert status.status == "COMPLETED"
    assert status.can_cancel is False
    assert services.get_qa_table() == view.qa_table
    assert "UNVERIFIABLE" in services.get_qa_table()
    assert services.get_repair_timeline().splitlines() == [
        "attempt_index\tartifact_id\taction_id\ttrigger_rule_id\tstop_reason",
        "0\tartifact-initial\t\t\tPASS_ALL_REQUIRED",
    ]
    assert services.get_export_summary() == (
        f"bundle=bundle-run-one-state approved=1 rejected=0 review=0 sha={'d' * 64}"
    )


def test_cancel_during_staging_prevents_open_and_finishes_cancelled(
    tmp_path: Path,
) -> None:
    from specstyle.ui.production_run import bind_production_run_one_services

    roots = _roots(tmp_path)
    reserve_entered = threading.Event()
    release_reserve = threading.Event()
    opened = False

    def reserve() -> object:
        reserve_entered.set()
        assert release_reserve.wait(timeout=2)
        return SimpleNamespace(job_id=JobId("run-one-cancelled"))

    def opener(_fds: object, _reservation: object) -> object:
        nonlocal opened
        opened = True
        pytest.fail("cancelled staging must not open production execution")

    services = bind_production_run_one_services(
        UiServices(lambda _text: pytest.fail("compile not used")),
        roots,
        reserve=reserve,
        open_run_one=opener,
    )
    completed: list[object] = []
    thread = threading.Thread(
        target=lambda: completed.append(
            services.run_production_job(
                *_uploads(tmp_path),
                "positive",
                "",
                None,
                None,
                None,
                "not_applicable",
            )
        )
    )
    thread.start()
    assert reserve_entered.wait(timeout=2)

    status = services.get_job_status()
    assert status.status == "STAGING"
    assert status.can_cancel is True
    assert status.message == "single phase=STAGING"
    assert services.cancel_job() == "cancel requested"
    assert services.cancel_job() == "cancel already requested"
    release_reserve.set()
    thread.join(timeout=2)

    assert not thread.is_alive()
    assert opened is False
    assert completed[0].status == "CANCELLED"
    terminal = services.get_job_status()
    assert terminal.job_id == "run-one-cancelled"
    assert terminal.status == "CANCELLED"
    assert terminal.can_cancel is False
    assert list(roots.staging_root.iterdir()) == []


def test_cancel_during_open_is_delivered_to_registered_execution(
    tmp_path: Path,
) -> None:
    from specstyle.ui.production_run import bind_production_run_one_services

    roots = _roots(tmp_path)
    open_entered = threading.Event()
    release_open = threading.Event()
    cancel_called = threading.Event()
    cancel_calls = 0

    class _Execution:
        def run(self) -> object:
            raise DomainError("production job cancelled")

        def cancel(self, *, reason: str) -> object:
            nonlocal cancel_calls
            assert reason == "user requested"
            cancel_calls += 1
            cancel_called.set()
            return SimpleNamespace(
                job=SimpleNamespace(status=SimpleNamespace(value="CANCELLED"))
            )

        def close(self) -> None:
            pass

    def opener(_fds: object, _reservation: object) -> object:
        open_entered.set()
        assert release_open.wait(timeout=2)
        return _Execution()

    services = bind_production_run_one_services(
        UiServices(lambda _text: pytest.fail("compile not used")),
        roots,
        reserve=lambda: SimpleNamespace(job_id=JobId("run-one-opening-cancel")),
        open_run_one=opener,
    )
    completed: list[object] = []
    thread = threading.Thread(
        target=lambda: completed.append(
            services.run_production_job(
                *_uploads(tmp_path),
                "positive",
                "",
                None,
                None,
                None,
                "not_applicable",
            )
        )
    )
    thread.start()
    assert open_entered.wait(timeout=2)

    assert services.cancel_job() == "cancel requested"
    release_open.set()
    thread.join(timeout=2)

    assert not thread.is_alive()
    assert cancel_called.is_set()
    assert cancel_calls == 1
    assert completed[0].status == "CANCELLED"


def test_running_status_reads_job_store_and_cancel_calls_live_execution(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from specstyle.ui import production_run

    roots = _roots(tmp_path)
    run_entered = threading.Event()
    cancel_called = threading.Event()
    close_called = threading.Event()
    cancel_calls = 0

    def read_status(_root: Path, job_id: str) -> str:
        assert job_id == "run-one-live"
        return "CANCELLED" if cancel_called.is_set() else "GENERATING"

    monkeypatch.setattr(
        production_run, "_read_persisted_job_status", read_status, raising=False
    )

    class _Execution:
        def run(self) -> object:
            run_entered.set()
            assert cancel_called.wait(timeout=2)
            raise DomainError("production job cancelled")

        def cancel(self, *, reason: str) -> object:
            nonlocal cancel_calls
            assert reason == "user requested"
            cancel_calls += 1
            cancel_called.set()
            return SimpleNamespace(
                job=SimpleNamespace(status=SimpleNamespace(value="CANCELLED"))
            )

        def close(self) -> None:
            assert cancel_called.is_set()
            close_called.set()

    services = production_run.bind_production_run_one_services(
        UiServices(lambda _text: pytest.fail("compile not used")),
        roots,
        reserve=lambda: SimpleNamespace(job_id=JobId("run-one-live")),
        open_run_one=lambda _fds, _reservation: _Execution(),
    )
    completed: list[object] = []
    thread = threading.Thread(
        target=lambda: completed.append(
            services.run_production_job(
                *_uploads(tmp_path),
                "positive",
                "",
                None,
                None,
                None,
                "not_applicable",
            )
        )
    )
    thread.start()
    assert run_entered.wait(timeout=2)

    status = services.get_job_status()
    assert status.job_id == "run-one-live"
    assert status.status == "GENERATING"
    assert status.message == "single phase=ACTIVE"
    assert services.cancel_job() == "cancel requested; job status=CANCELLED"
    thread.join(timeout=2)

    assert not thread.is_alive()
    assert cancel_calls == 1
    assert close_called.is_set()
    assert completed[0].status == "CANCELLED"
    assert services.get_job_status().status == "CANCELLED"


def test_cancelling_batch_stops_reserving_later_items(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from specstyle.ui import production_run

    roots = _roots(tmp_path)
    run_entered = threading.Event()
    cancel_called = threading.Event()
    variations: list[int] = []

    monkeypatch.setattr(
        production_run,
        "_read_persisted_job_status",
        lambda _root, _job_id: "GENERATING",
    )

    def reserve(variation: int) -> object:
        variations.append(variation)
        return SimpleNamespace(
            job_id=JobId(f"run-one-batch-{len(variations)}"),
            variation_index=variation,
        )

    class _Execution:
        def run(self) -> object:
            run_entered.set()
            assert cancel_called.wait(timeout=2)
            raise DomainError("production job cancelled")

        def cancel(self, *, reason: str) -> object:
            assert reason == "user requested"
            cancel_called.set()
            return SimpleNamespace(
                job=SimpleNamespace(status=SimpleNamespace(value="CANCELLED"))
            )

        def close(self) -> None:
            pass

    services = production_run.bind_production_run_one_services(
        UiServices(lambda _text: pytest.fail("compile not used")),
        roots,
        reserve=reserve,
        open_run_one=lambda _fds, _reservation: _Execution(),
    )
    completed: list[object] = []
    thread = threading.Thread(
        target=lambda: completed.append(
            services.run_production_batch(
                *_uploads(tmp_path),
                "positive",
                "",
                None,
                None,
                None,
                "not_applicable",
                3,
            )
        )
    )
    thread.start()
    assert run_entered.wait(timeout=2)

    status = services.get_job_status()
    assert status.job_id == "run-one-batch-1"
    assert status.status == "GENERATING"
    assert status.message == (
        "batch phase=ACTIVE item=1/3 aggregate_ui=yes "
        "completed=0 failed=0 cancelled=0 remaining=3"
    )
    assert services.cancel_job() == "cancel requested; job status=CANCELLED"
    thread.join(timeout=2)

    assert not thread.is_alive()
    assert variations == [0]
    assert completed[0].status == "CANCELLED"
    assert len(completed[0].items) == 1
    assert completed[0].items[0].run.status == "CANCELLED"
    assert services.get_job_status().status == "CANCELLED"


def test_production_state_redacts_and_bounds_domain_errors(tmp_path: Path) -> None:
    from specstyle.ui.production_run import bind_production_run_one_services

    unsafe = "open\tfailed\n/private/input\r" + "x" * 300
    services = bind_production_run_one_services(
        UiServices(lambda _text: pytest.fail("compile not used")),
        _roots(tmp_path),
        reserve=lambda: SimpleNamespace(job_id=JobId("run-one-error")),
        open_run_one=lambda _fds, _reservation: (_ for _ in ()).throw(
            InfrastructureError(unsafe)
        ),
    )

    view = services.run_production_job(
        *_uploads(tmp_path),
        "positive",
        "",
        None,
        None,
        None,
        "not_applicable",
    )

    assert view.status == "JOB_FAILED"
    assert view.message.startswith("open failed /private/input ")
    assert not {"\t", "\n", "\r"}.intersection(view.message)
    assert len(view.message) == 160
    assert services.get_job_status().message == view.message


def test_production_gradio_events_use_independent_concurrency_groups() -> None:
    from specstyle.ui.app import _enable_production_queue, _production_event_options

    assert _production_event_options("run") == {
        "concurrency_id": "production-run",
        "concurrency_limit": 2,
    }
    assert _production_event_options("control") == {
        "concurrency_id": "production-control",
        "concurrency_limit": 4,
    }
    with pytest.raises(DomainError, match="invalid production event kind"):
        _production_event_options("other")

    calls: list[dict[str, object]] = []

    class _Blocks:
        def queue(self, **kwargs: object) -> object:
            calls.append(kwargs)
            return self

    blocks = _Blocks()
    assert _enable_production_queue(blocks) is blocks
    assert calls == [{"default_concurrency_limit": 1}]


def test_batch_controls_aggregate_real_item_projections(tmp_path: Path) -> None:
    from specstyle.ui.production_run import bind_production_run_one_services

    roots = _roots(tmp_path)
    reservations: list[int] = []

    def reserve(variation: int) -> object:
        reservations.append(variation)
        return SimpleNamespace(
            job_id=JobId(f"run-one-projection-{len(reservations)}"),
            variation_index=variation,
        )

    def opener(_fds: object, reservation: object) -> object:
        index = len(reservations)
        result = _batch_result(
            reservation.job_id.value,
            reservation.variation_index,
            100 + index,
            200 + index,
        )
        result.job_result.report = _qa_report()
        result.job_result.history.initial_attempt.artifact = SimpleNamespace(
            ref=SimpleNamespace(artifact_id=ArtifactId(f"artifact-initial-{index}"))
        )
        result.job_result.history.repair_attempts = ()
        result.job_result.terminal = SimpleNamespace(
            artifact_decision=SimpleNamespace(
                repair_stop_reason=SimpleNamespace(value="PASS_ALL_REQUIRED")
            )
        )
        return _BatchExecution(result)

    services = bind_production_run_one_services(
        UiServices(lambda _text: pytest.fail("compile not used")),
        roots,
        reserve=reserve,
        open_run_one=opener,
    )

    view = services.run_production_batch(*_batch_args(tmp_path), 2)

    assert view.status == "COMPLETED"
    assert services.get_qa_table().count("UNVERIFIABLE") == 2
    repair = services.get_repair_timeline()
    assert "item=0" in repair
    assert "artifact-initial-1" in repair
    assert "item=1" in repair
    assert "artifact-initial-2" in repair
    export = services.get_export_summary()
    assert "item=0 bundle=bundle-run-one-projection-1" in export
    assert "item=1 bundle=bundle-run-one-projection-2" in export


def test_stale_status_retry_reads_new_job_without_holding_state_lock(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from specstyle.ui import production_run

    roots = _roots(tmp_path)
    first_run_entered = threading.Event()
    second_run_entered = threading.Event()
    finish_first = threading.Event()
    finish_second = threading.Event()
    first_reader_entered = threading.Event()
    release_first_reader = threading.Event()
    control_was_unblocked: list[bool] = []
    services = None

    def status_reader(_root: Path, job_id: str) -> str:
        if job_id == "run-one-token-1":
            first_reader_entered.set()
            assert release_first_reader.wait(timeout=2)
            return "GENERATING"
        assert job_id == "run-one-token-2"
        responses: list[str] = []
        control = threading.Thread(
            target=lambda: responses.append(services.cancel_job())
        )
        control.start()
        control.join(timeout=0.5)
        control_was_unblocked.append(not control.is_alive())
        return "GENERATING"

    monkeypatch.setattr(production_run, "_read_persisted_job_status", status_reader)
    reservations: list[str] = []

    def reserve() -> object:
        job_id = f"run-one-token-{len(reservations) + 1}"
        reservations.append(job_id)
        return SimpleNamespace(job_id=JobId(job_id))

    class _Execution:
        def __init__(self, sequence: int) -> None:
            self.sequence = sequence

        def run(self) -> object:
            entered = first_run_entered if self.sequence == 1 else second_run_entered
            finish = finish_first if self.sequence == 1 else finish_second
            entered.set()
            assert finish.wait(timeout=3)
            return _batch_result(
                f"run-one-token-{self.sequence}",
                0,
                100 + self.sequence,
                200 + self.sequence,
            )

        def cancel(self, *, reason: str) -> object:
            assert reason == "user requested"
            return SimpleNamespace(
                job=SimpleNamespace(status=SimpleNamespace(value="CANCELLED"))
            )

        def close(self) -> None:
            pass

    services = production_run.bind_production_run_one_services(
        UiServices(lambda _text: pytest.fail("compile not used")),
        roots,
        reserve=reserve,
        open_run_one=lambda _fds, _reservation: _Execution(len(reservations)),
    )
    args = (*_uploads(tmp_path), "positive", "", None, None, None, "not_applicable")
    first = threading.Thread(target=lambda: services.run_production_job(*args))
    first.start()
    assert first_run_entered.wait(timeout=2)
    statuses: list[object] = []
    status_thread = threading.Thread(
        target=lambda: statuses.append(services.get_job_status())
    )
    status_thread.start()
    assert first_reader_entered.wait(timeout=2)

    finish_first.set()
    first.join(timeout=2)
    second = threading.Thread(target=lambda: services.run_production_job(*args))
    second.start()
    assert second_run_entered.wait(timeout=2)
    release_first_reader.set()
    status_thread.join(timeout=2)

    assert not status_thread.is_alive()
    assert statuses[0].job_id == "run-one-token-2"
    assert control_was_unblocked == [True]
    finish_second.set()
    second.join(timeout=2)
    assert not second.is_alive()


def test_batch_status_discards_previous_item_read_with_same_token() -> None:
    from specstyle.ui.production_ui_state import ProductionUiState

    first_reader_entered = threading.Event()
    release_first_reader = threading.Event()
    reader_calls: list[str] = []

    def status_reader(job_id: str) -> str:
        reader_calls.append(job_id)
        if job_id == "run-one-batch-stale-1":
            first_reader_entered.set()
            assert release_first_reader.wait(timeout=2)
            return "GENERATING"
        assert job_id == "run-one-batch-stale-2"
        return "VERIFYING"

    state = ProductionUiState(status_reader)
    token = state.try_begin("batch", 2)
    assert token is not None
    state.set_phase(
        token,
        "ACTIVE",
        job_id="run-one-batch-stale-1",
        current_index=0,
    )
    statuses: list[object] = []
    thread = threading.Thread(target=lambda: statuses.append(state.get_job_status()))
    thread.start()
    assert first_reader_entered.wait(timeout=2)

    state.set_phase(
        token,
        "ACTIVE",
        job_id="run-one-batch-stale-2",
        current_index=1,
    )
    release_first_reader.set()
    thread.join(timeout=2)

    assert not thread.is_alive()
    assert reader_calls == ["run-one-batch-stale-1", "run-one-batch-stale-2"]
    assert statuses[0].job_id == "run-one-batch-stale-2"
    assert statuses[0].status == "VERIFYING"
    assert "item=2/2" in statuses[0].message


def test_batch_remains_cancelable_between_completed_items(tmp_path: Path) -> None:
    from specstyle.ui.production_run import bind_production_run_one_services

    roots = _roots(tmp_path)
    second_reserve_entered = threading.Event()
    release_second_reserve = threading.Event()
    variations: list[int] = []
    opens = 0

    def reserve(variation: int) -> object:
        variations.append(variation)
        if len(variations) == 2:
            second_reserve_entered.set()
            assert release_second_reserve.wait(timeout=2)
        return SimpleNamespace(
            job_id=JobId(f"run-one-gap-{len(variations)}"),
            variation_index=variation,
        )

    def opener(_fds: object, reservation: object) -> object:
        nonlocal opens
        opens += 1
        return _BatchExecution(
            _batch_result(
                reservation.job_id.value,
                reservation.variation_index,
                100 + opens,
                200 + opens,
            )
        )

    services = bind_production_run_one_services(
        UiServices(lambda _text: pytest.fail("compile not used")),
        roots,
        reserve=reserve,
        open_run_one=opener,
    )
    completed: list[object] = []
    thread = threading.Thread(
        target=lambda: completed.append(
            services.run_production_batch(*_batch_args(tmp_path), 3)
        )
    )
    thread.start()
    assert second_reserve_entered.wait(timeout=2)

    status = services.get_job_status()
    assert status.status == "STAGING"
    assert status.message == (
        "batch phase=STAGING item=2/3 aggregate_ui=yes "
        "completed=1 failed=0 cancelled=0 remaining=2"
    )
    assert services.get_qa_table() == "item=0\nno qa"
    assert services.get_repair_timeline() == "item=0\nno repair"
    assert services.get_export_summary().startswith(
        "item=0 bundle=bundle-run-one-gap-1"
    )
    assert services.cancel_job() == "cancel requested"
    release_second_reserve.set()
    thread.join(timeout=2)

    assert not thread.is_alive()
    assert variations == [0, 2]
    assert opens == 1
    assert completed[0].status == "PARTIAL"
    assert tuple(item.run.status for item in completed[0].items) == (
        "COMPLETED",
        "CANCELLED",
    )


def test_single_cleanup_failure_preserves_completed_projection(tmp_path: Path) -> None:
    from specstyle.ui.production_run import bind_production_run_one_services

    roots = _roots(tmp_path)
    result = _batch_result("run-one-cleanup", 0, 101, 201)

    class _Execution:
        def run(self) -> object:
            return result

        def close(self) -> None:
            raise ProductionRunOneCleanupError(result)

    services = bind_production_run_one_services(
        UiServices(lambda _text: pytest.fail("compile not used")),
        roots,
        reserve=lambda: SimpleNamespace(job_id=JobId("run-one-cleanup")),
        open_run_one=lambda _fds, _reservation: _Execution(),
    )

    view = services.run_production_job(
        *_uploads(tmp_path),
        "positive",
        "",
        None,
        None,
        None,
        "not_applicable",
    )

    assert view.status == "COMPLETED"
    assert view.bundle_name == "bundle-run-one-cleanup"
    assert view.message == "production run completed; cleanup failed"
    assert services.get_job_status().status == "COMPLETED"
    assert "bundle=bundle-run-one-cleanup" in services.get_export_summary()


def test_cleanup_without_result_uses_persisted_terminal_status(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from specstyle.ui import production_run

    roots = _roots(tmp_path)
    result = _batch_result("run-one-cleanup-state", 0, 101, 201)
    monkeypatch.setattr(
        production_run,
        "_read_persisted_job_status",
        lambda _root, job_id: (
            "COMPLETED" if job_id == "run-one-cleanup-state" else None
        ),
    )

    class _Execution:
        def run(self) -> object:
            return result

        def close(self) -> None:
            raise ProductionRunOneCleanupError(None)

    services = production_run.bind_production_run_one_services(
        UiServices(lambda _text: pytest.fail("compile not used")),
        roots,
        reserve=lambda: SimpleNamespace(job_id=JobId("run-one-cleanup-state")),
        open_run_one=lambda _fds, _reservation: _Execution(),
    )

    view = services.run_production_job(
        *_uploads(tmp_path),
        "positive",
        "",
        None,
        None,
        None,
        "not_applicable",
    )

    assert view.status == "COMPLETED"
    assert view.message == "production run-one cleanup failed"
    assert view.bundle_name == ""
    assert view.qa_table == "no qa"
    assert services.get_export_summary() == "no export"
    assert services.get_job_status().status == "COMPLETED"


def test_completed_job_wins_cancel_race(tmp_path: Path) -> None:
    from specstyle.ui.production_run import bind_production_run_one_services

    roots = _roots(tmp_path)
    run_entered = threading.Event()
    cancel_attempted = threading.Event()
    result = _batch_result("run-one-completion-race", 0, 101, 201)

    class _Execution:
        def run(self) -> object:
            run_entered.set()
            assert cancel_attempted.wait(timeout=2)
            return result

        def cancel(self, *, reason: str) -> object:
            assert reason == "user requested"
            cancel_attempted.set()
            return SimpleNamespace(
                job=SimpleNamespace(status=SimpleNamespace(value="COMPLETED"))
            )

        def close(self) -> None:
            pass

    services = bind_production_run_one_services(
        UiServices(lambda _text: pytest.fail("compile not used")),
        roots,
        reserve=lambda: SimpleNamespace(job_id=JobId("run-one-completion-race")),
        open_run_one=lambda _fds, _reservation: _Execution(),
    )
    completed: list[object] = []
    thread = threading.Thread(
        target=lambda: completed.append(
            services.run_production_job(
                *_uploads(tmp_path),
                "positive",
                "",
                None,
                None,
                None,
                "not_applicable",
            )
        )
    )
    thread.start()
    assert run_entered.wait(timeout=2)

    assert services.cancel_job() == "cancel unavailable; job status=COMPLETED"
    thread.join(timeout=2)

    assert not thread.is_alive()
    assert completed[0].status == "COMPLETED"
    assert services.get_job_status().status == "COMPLETED"


def test_terminal_state_does_not_retain_execution_or_result(tmp_path: Path) -> None:
    from specstyle.ui.production_run import bind_production_run_one_services

    roots = _roots(tmp_path)
    references: dict[str, weakref.ReferenceType[object]] = {}

    class _Result:
        pass

    class _Execution:
        def __init__(self, result: object) -> None:
            self.result = result

        def run(self) -> object:
            return self.result

        def close(self) -> None:
            pass

    def opener(_fds: object, _reservation: object) -> object:
        base = _batch_result("run-one-gc", 0, 101, 201)
        result = _Result()
        result.job_result = base.job_result
        result.export_result = base.export_result
        execution = _Execution(result)
        references["result"] = weakref.ref(result)
        references["execution"] = weakref.ref(execution)
        return execution

    services = bind_production_run_one_services(
        UiServices(lambda _text: pytest.fail("compile not used")),
        roots,
        reserve=lambda: SimpleNamespace(job_id=JobId("run-one-gc")),
        open_run_one=opener,
    )

    view = services.run_production_job(
        *_uploads(tmp_path),
        "positive",
        "",
        None,
        None,
        None,
        "not_applicable",
    )
    gc.collect()

    assert view.status == "COMPLETED"
    assert references["result"]() is None
    assert references["execution"]() is None
    assert services.get_export_summary().startswith("bundle=bundle-run-one-gc")


def test_cancel_waits_for_close_gate_and_never_uses_closed_execution(
    tmp_path: Path,
) -> None:
    from specstyle.ui.production_run import bind_production_run_one_services

    roots = _roots(tmp_path)
    close_entered = threading.Event()
    release_close = threading.Event()
    cancel_finished = threading.Event()
    cancel_calls = 0
    result = _batch_result("run-one-close-gate", 0, 101, 201)

    class _Execution:
        def run(self) -> object:
            return result

        def cancel(self, *, reason: str) -> object:
            nonlocal cancel_calls
            cancel_calls += 1
            pytest.fail(f"closed execution received cancel: {reason}")

        def close(self) -> None:
            close_entered.set()
            assert release_close.wait(timeout=2)

    services = bind_production_run_one_services(
        UiServices(lambda _text: pytest.fail("compile not used")),
        roots,
        reserve=lambda: SimpleNamespace(job_id=JobId("run-one-close-gate")),
        open_run_one=lambda _fds, _reservation: _Execution(),
    )
    run_thread = threading.Thread(
        target=lambda: services.run_production_job(
            *_uploads(tmp_path),
            "positive",
            "",
            None,
            None,
            None,
            "not_applicable",
        )
    )
    run_thread.start()
    assert close_entered.wait(timeout=2)
    responses: list[str] = []
    cancel_thread = threading.Thread(
        target=lambda: (
            responses.append(services.cancel_job()),
            cancel_finished.set(),
        )
    )
    cancel_thread.start()
    assert not cancel_finished.wait(timeout=0.1)

    release_close.set()
    run_thread.join(timeout=2)
    cancel_thread.join(timeout=2)

    assert not run_thread.is_alive()
    assert not cancel_thread.is_alive()
    assert cancel_calls == 0
    assert responses == ["cancel unavailable; latest run is terminal"]
