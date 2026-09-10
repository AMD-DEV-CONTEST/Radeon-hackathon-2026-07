"""APP-COMPOSE-001D production runtime resilience contracts."""

from __future__ import annotations

import importlib
import inspect
from types import SimpleNamespace
import threading

import pytest

from specstyle.domain.identifiers import JobId
from specstyle.errors import DomainError, InfrastructureError
from specstyle.workflow.job_models import (
    CancelRequestedPayload,
    Event,
    EventType,
    FatalPayload,
    JobStatus,
)
from specstyle.workflow.job_store import JobStore
from tests.unit.workflow.test_job_store import (
    _attempt_finished_payload,
    _event,
    _seed_to,
)
from tests.unit.workflow.test_production_service import _request_kwargs


class _CloseProbe:
    def __init__(self, name: str, calls: list[str]) -> None:
        self.name = name
        self.calls = calls

    def close(self) -> None:
        self.calls.append(self.name)


class _NoJobStore:
    def get_snapshot(self, _job_id: JobId, /) -> None:
        return None


def _runtime_for_close(module, calls: list[str]):
    runtime = object.__new__(module._ProductionGenerationRuntime)
    readiness = getattr(module, "_RuntimeReadiness", SimpleNamespace(READY="READY"))
    values = {
        "_loaded": _CloseProbe("loaded", calls),
        "_load_pipeline": lambda: None,
        "_allowlist": object(),
        "_verifier_factory": _CloseProbe("factory", calls),
        "_report_store": _CloseProbe("report", calls),
        "_artifact_store": _CloseProbe("artifact", calls),
        "_environment": object(),
        "_compiler_context": object(),
        "_style_assets": object(),
        "_control_builder": object(),
        "_job_store": _NoJobStore(),
        "_clock": lambda: "2026-08-02T00:00:00.000Z",
        "_state_lock": threading.RLock(),
        "_run_lock": threading.RLock(),
        "_active_job_id": None,
        "_active_cancel": None,
        "_active_cancel_reason": None,
        "_readiness_value": readiness.READY,
        "_failure_kind_value": None,
        "_closed": False,
    }
    for name in module._ProductionGenerationRuntime.__slots__:
        setattr(runtime, name, values[name])
    return runtime


class _AttemptRepository:
    def close(self) -> None:
        pass


class _FailingCloseProbe(_CloseProbe):
    def close(self) -> None:
        super().close()
        raise InfrastructureError(f"{self.name} cleanup failed")


def test_gpu_oom_marker_is_private_slotted_and_structured() -> None:
    errors = importlib.import_module("specstyle.errors")

    assert "_GpuOutOfMemoryError" not in getattr(errors, "__all__", ())
    error_type = getattr(errors, "_GpuOutOfMemoryError")
    error = error_type("safe OOM")

    assert issubclass(error_type, InfrastructureError)
    assert error_type.__slots__ == ()
    assert type(error) is error_type
    assert str(error) == "safe OOM"


def test_runtime_slots_use_the_frozen_private_state_names() -> None:
    module = importlib.import_module("specstyle.workflow.production_service")

    assert module._ProductionGenerationRuntime.__slots__ == (
        "_loaded",
        "_load_pipeline",
        "_allowlist",
        "_verifier_factory",
        "_report_store",
        "_artifact_store",
        "_environment",
        "_compiler_context",
        "_style_assets",
        "_control_builder",
        "_job_store",
        "_clock",
        "_state_lock",
        "_run_lock",
        "_active_job_id",
        "_active_cancel",
        "_active_cancel_reason",
        "_readiness_value",
        "_failure_kind_value",
        "_closed",
    )


def test_persistence_job_store_and_repair_helpers_do_not_hold_gpu_lease() -> None:
    module = importlib.import_module("specstyle.workflow.production_service")

    for name in (
        "_append_event",
        "_persist_artifact",
        "_persist_report",
        "_repair_call",
        "_create_initial_job",
    ):
        assert "_GPU_LEASE" not in inspect.getsource(getattr(module, name))
    assert "with _GPU_LEASE" not in inspect.getsource(
        module._ProductionGenerationRuntime._run_prepared_attempt
    )


def test_close_from_active_run_thread_fails_before_state_or_cancel_mutation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = importlib.import_module("specstyle.workflow.production_service")
    runtime = _runtime_for_close(module, [])
    request = module.ProductionJobRequest(**_request_kwargs())
    expected = object()

    def prepare(active_runtime, _request):
        with pytest.raises(
            InfrastructureError,
            match="^production runtime close from active run$",
        ):
            active_runtime.close()
        assert active_runtime._closed is False
        assert active_runtime.readiness.value == "BUSY"
        event = getattr(active_runtime, "_active_cancel", None)
        assert event is None or not event.is_set()
        return SimpleNamespace(
            report_repository=_AttemptRepository(),
            repository=_AttemptRepository(),
        )

    monkeypatch.setattr(
        module._ProductionGenerationRuntime, "_prepare_initial_attempt", prepare
    )
    monkeypatch.setattr(
        module._ProductionGenerationRuntime,
        "_run_prepared_attempt",
        lambda *_args: expected,
    )

    assert runtime._execute_initial_attempt(request) is expected
    assert runtime._closed is False
    assert runtime.readiness.value == "READY"


def test_external_close_waits_for_active_run_then_completes_cleanup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = importlib.import_module("specstyle.workflow.production_service")
    calls: list[str] = []
    runtime = _runtime_for_close(module, calls)
    request = module.ProductionJobRequest(**_request_kwargs())
    entered = threading.Event()
    release = threading.Event()
    close_done = threading.Event()

    def prepare(_runtime, _request):
        entered.set()
        assert release.wait(2)
        return SimpleNamespace(
            report_repository=_AttemptRepository(),
            repository=_AttemptRepository(),
        )

    monkeypatch.setattr(
        module._ProductionGenerationRuntime, "_prepare_initial_attempt", prepare
    )
    monkeypatch.setattr(
        module._ProductionGenerationRuntime,
        "_run_prepared_attempt",
        lambda *_args: object(),
    )
    run_errors: list[BaseException] = []

    def run() -> None:
        try:
            runtime._execute_initial_attempt(request)
        except BaseException as error:
            run_errors.append(error)

    def close() -> None:
        runtime.close()
        close_done.set()

    runner = threading.Thread(target=run)
    closer = threading.Thread(target=close)
    runner.start()
    assert entered.wait(2)
    closer.start()
    assert not close_done.wait(0.1)
    assert calls == []
    release.set()
    runner.join(2)
    closer.join(2)

    assert not runner.is_alive() and not closer.is_alive()
    assert close_done.is_set()
    assert runtime.readiness.value == "CLOSED"
    assert calls == ["factory", "loaded", "report", "artifact"]


def test_close_preserves_cancel_persistence_error_and_attempts_all_cleanup(
    tmp_path,
) -> None:
    module = importlib.import_module("specstyle.workflow.production_service")
    calls: list[str] = []
    runtime = _runtime_for_close(module, calls)
    cancel_failure = InfrastructureError("cancel persistence failed")

    class FailingCancelStore(JobStore):
        def __init__(self) -> None:
            super().__init__(tmp_path)

        def get_snapshot(self, _job_id):
            return object()

        def load(self, _job_id):
            raise cancel_failure

    runtime._job_store = FailingCancelStore()
    runtime._active_job_id = JobId("job1")
    runtime._active_cancel = threading.Event()
    runtime._verifier_factory = _FailingCloseProbe("factory", calls)
    runtime._report_store = _FailingCloseProbe("report", calls)

    try:
        with pytest.raises(InfrastructureError) as raised:
            runtime.close()
    finally:
        runtime._job_store.close()

    assert raised.value is cancel_failure
    assert calls == ["factory", "loaded", "report", "artifact"]
    assert runtime.readiness.value == "CLOSED"


def test_close_cancel_error_releases_run_and_second_close_waiter(tmp_path) -> None:
    module = importlib.import_module("specstyle.workflow.production_service")
    calls: list[str] = []
    runtime = _runtime_for_close(module, calls)
    cancel_failure = InfrastructureError("cancel persistence failed")
    attempted = threading.Event()
    run_entered, release_run = threading.Event(), threading.Event()
    second_done = threading.Event()

    class FailingCancelStore(JobStore):
        def __init__(self) -> None:
            super().__init__(tmp_path)

        def get_snapshot(self, _job_id):
            return object()

        def load(self, _job_id):
            attempted.set()
            raise cancel_failure

    runtime._job_store = FailingCancelStore()
    runtime._active_job_id = JobId("job1")
    runtime._active_cancel = threading.Event()
    runtime._verifier_factory = _FailingCloseProbe("factory", calls)
    runtime._report_store = _FailingCloseProbe("report", calls)
    first_errors: list[BaseException] = []
    second_errors: list[BaseException] = []

    def hold_run() -> None:
        with runtime._run_lock:
            run_entered.set()
            assert release_run.wait(2)

    def capture_close(errors, done=None) -> None:
        try:
            runtime.close()
        except BaseException as error:
            errors.append(error)
        finally:
            if done is not None:
                done.set()

    runner = threading.Thread(target=hold_run)
    first = threading.Thread(target=lambda: capture_close(first_errors))
    second = threading.Thread(target=lambda: capture_close(second_errors, second_done))
    runner.start()
    assert run_entered.wait(2)
    first.start()
    assert attempted.wait(2)
    second.start()
    assert not second_done.wait(0.1)
    release_run.set()
    for thread in (runner, first, second):
        thread.join(2)
    runtime._job_store.close()

    assert all(not thread.is_alive() for thread in (runner, first, second))
    assert first_errors == [cancel_failure] and second_errors == []
    assert calls == ["factory", "loaded", "report", "artifact"]


def _runtime_with_job_store(module, store: JobStore):
    runtime = _runtime_for_close(module, [])
    runtime._job_store = store
    return runtime


def _seed_terminal(store: JobStore, status: str) -> None:
    if status == "COMPLETED":
        _seed_to(store, status)
        return
    _seed_to(store, "GENERATING")
    if status == "CANCELLED":
        event_type = EventType.CANCEL_REQUESTED
        payload = CancelRequestedPayload("seed")
    else:
        event_type = EventType.FATAL
        payload = FatalPayload("GENERATION_FAILED", "generation failed")
    store.append_event(
        JobId("job1"),
        _event(4, event_type, "GENERATING", status, payload),
    )


def test_cancel_missing_job_reports_not_found_without_creating_snapshot(
    tmp_path,
) -> None:
    module = importlib.import_module("specstyle.workflow.production_service")
    store = JobStore(tmp_path)
    runtime = _runtime_with_job_store(module, store)

    with pytest.raises(DomainError, match="^job not found$"):
        runtime.cancel(JobId("missing"))

    assert store.get_snapshot(JobId("missing")) is None


def test_cancel_is_idempotent_for_durable_cancelled_job(tmp_path) -> None:
    module = importlib.import_module("specstyle.workflow.production_service")
    store = JobStore(tmp_path)
    _seed_terminal(store, "CANCELLED")
    runtime = _runtime_with_job_store(module, store)
    existing = store.list_events(JobId("job1"))

    first = runtime.cancel(JobId("job1"), reason="stop")
    second = runtime.cancel(JobId("job1"), reason="different")

    assert first.job.status is JobStatus.CANCELLED
    assert second == first
    assert store.list_events(JobId("job1")) == existing


@pytest.mark.parametrize("status", ("JOB_FAILED", "COMPLETED"))
def test_cancel_rejects_non_cancelled_terminal_job(tmp_path, status: str) -> None:
    module = importlib.import_module("specstyle.workflow.production_service")
    store = JobStore(tmp_path)
    _seed_terminal(store, status)
    runtime = _runtime_with_job_store(module, store)

    with pytest.raises(DomainError, match="^job is terminal$"):
        runtime.cancel(JobId("job1"))


class _TransitionRaceStore(JobStore):
    def __init__(self, root, terminal: bool) -> None:
        super().__init__(root)
        self.terminal = terminal
        self.raced = False

    def append_event(self, job_id: JobId, event: Event, /) -> Event:
        if event.event_type is EventType.CANCEL_REQUESTED and not self.raced:
            self.raced = True
            raced = (
                Event(
                    1,
                    job_id,
                    EventType.FATAL,
                    JobStatus.GENERATING,
                    JobStatus.JOB_FAILED,
                    event.timestamp,
                    FatalPayload("GENERATION_FAILED", "generation failed"),
                )
                if self.terminal
                else Event(
                    1,
                    job_id,
                    EventType.ATTEMPT_FINISHED,
                    JobStatus.GENERATING,
                    JobStatus.VERIFYING,
                    event.timestamp,
                    _attempt_finished_payload("att1"),
                )
            )
            super().append_event(job_id, raced)
        return super().append_event(job_id, event)


def test_cancel_reloads_and_retries_after_nonterminal_append_race(tmp_path) -> None:
    module = importlib.import_module("specstyle.workflow.production_service")
    store = _TransitionRaceStore(tmp_path, terminal=False)
    _seed_to(store, "GENERATING")
    runtime = _runtime_with_job_store(module, store)

    state = runtime.cancel(JobId("job1"), reason="race")

    assert state.job.status is JobStatus.CANCELLED
    assert [event.event_type for event in store.list_events(JobId("job1"))][-2:] == [
        EventType.ATTEMPT_FINISHED,
        EventType.CANCEL_REQUESTED,
    ]


def test_cancel_terminal_race_never_overwrites_job_failed(tmp_path) -> None:
    module = importlib.import_module("specstyle.workflow.production_service")
    store = _TransitionRaceStore(tmp_path, terminal=True)
    _seed_to(store, "GENERATING")
    runtime = _runtime_with_job_store(module, store)

    with pytest.raises(DomainError, match="^job is terminal$"):
        runtime.cancel(JobId("job1"), reason="race")

    assert store.load(JobId("job1")).job.status is JobStatus.JOB_FAILED


def test_cancel_checks_closed_before_job_id_and_reason_validation() -> None:
    module = importlib.import_module("specstyle.workflow.production_service")
    runtime = _runtime_for_close(module, [])
    runtime._closed = True

    with pytest.raises(InfrastructureError, match="^production runtime closed$"):
        runtime.cancel(object(), reason=object())


class _ManyTransitionRaceStore(JobStore):
    def __init__(self, root) -> None:
        super().__init__(root)
        self.statuses = [
            JobStatus.GENERATING,
            JobStatus.VERIFYING,
            JobStatus.REPAIR_SELECTING,
            JobStatus.REPAIRING,
        ]
        self.index = 0
        self.append_calls = 0

    def load(self, _job_id: JobId, /):
        return SimpleNamespace(job=SimpleNamespace(status=self.statuses[self.index]))

    def append_event(self, _job_id: JobId, _event: Event, /) -> Event:
        self.append_calls += 1
        if self.index < len(self.statuses) - 1:
            self.index += 1
            raise DomainError("invalid job transition")
        self.statuses[self.index] = JobStatus.CANCELLED
        return _event


def test_cancel_reloads_through_more_than_two_nonterminal_races(tmp_path) -> None:
    module = importlib.import_module("specstyle.workflow.production_service")
    store = _ManyTransitionRaceStore(tmp_path)
    runtime = _runtime_for_close(module, [])
    runtime._job_store = store

    try:
        state = runtime.cancel(JobId("job1"), reason="race")
    finally:
        store.close()

    assert state.job.status is JobStatus.CANCELLED
    assert store.append_calls == 4


def test_in_memory_cancel_event_is_not_the_cancel_linearization_point(tmp_path) -> None:
    module = importlib.import_module("specstyle.workflow.production_service")
    runtime = _runtime_for_close(module, [])
    runtime._active_job_id = JobId("job1")
    runtime._active_cancel = threading.Event()
    runtime._active_cancel.set()

    assert runtime._cancellation_won(JobId("job1")) is False

    store = JobStore(tmp_path)
    _seed_to(store, "GENERATING")
    runtime._job_store = store
    assert runtime._cancellation_won(JobId("job1")) is False

    runtime.cancel(JobId("job1"), reason="durable")
    assert runtime._cancellation_won(JobId("job1")) is True


def _quarantined_runtime(module, calls: list[str]):
    runtime = _runtime_for_close(module, calls)
    runtime._readiness_value = module._RuntimeReadiness.QUARANTINED
    runtime._failure_kind_value = module._RuntimeFailureKind.GPU_OOM
    runtime._verifier_factory = None
    return runtime


def test_reopen_replaces_quarantined_pipeline_and_factory_atomically(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = importlib.import_module("specstyle.workflow.production_service")
    calls: list[str] = []
    runtime = _quarantined_runtime(module, calls)
    old_loaded = runtime._loaded
    fresh_loaded = _CloseProbe("fresh-loaded", calls)
    fresh_factory = _CloseProbe("fresh-factory", calls)
    runtime._load_pipeline = lambda: (calls.append("load"), fresh_loaded)[1]
    runtime._allowlist = object()

    def create_factory(loaded, allowlist):
        calls.append("factory")
        assert loaded is fresh_loaded
        assert allowlist is runtime._allowlist
        return fresh_factory

    monkeypatch.setattr(module, "_create_production_verifier_factory", create_factory)

    runtime.reopen()

    assert runtime._loaded is fresh_loaded and runtime._loaded is not old_loaded
    assert runtime._verifier_factory is fresh_factory
    assert runtime.readiness.value == "READY"
    assert runtime.failure_kind is None
    assert calls == ["load", "factory"]


def test_failed_reopen_stays_quarantined_and_cleanup_cannot_mask_primary(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = importlib.import_module("specstyle.workflow.production_service")
    calls: list[str] = []
    runtime = _quarantined_runtime(module, calls)
    old_loaded = runtime._loaded
    fresh_loaded = _FailingCloseProbe("fresh-loaded", calls)
    primary = InfrastructureError("reopen factory failed")
    runtime._load_pipeline = lambda: fresh_loaded
    monkeypatch.setattr(
        module,
        "_create_production_verifier_factory",
        lambda *_args: (_ for _ in ()).throw(primary),
    )

    with pytest.raises(InfrastructureError) as raised:
        runtime.reopen()

    assert raised.value is primary
    assert runtime._loaded is old_loaded
    assert runtime._verifier_factory is None
    assert runtime.readiness.value == "QUARANTINED"
    assert runtime.failure_kind.value == "GPU_OOM"
    assert calls == ["fresh-loaded"]


@pytest.mark.parametrize("closed", (False, True))
def test_reopen_requires_quarantined_and_closed_has_priority(closed: bool) -> None:
    module = importlib.import_module("specstyle.workflow.production_service")
    runtime = _runtime_for_close(module, [])
    runtime._closed = closed
    if closed:
        runtime._readiness_value = module._RuntimeReadiness.CLOSED
        message = "production runtime closed"
    else:
        message = "production runtime is not quarantined"
    runtime._load_pipeline = lambda: (_ for _ in ()).throw(
        AssertionError("reopen must fail before loading")
    )

    with pytest.raises(InfrastructureError, match=f"^{message}$"):
        runtime.reopen()


@pytest.mark.parametrize(
    ("closed", "readiness", "message"),
    (
        (True, "QUARANTINED", "production runtime closed"),
        (False, "QUARANTINED", "production runtime quarantined"),
        (False, "BUSY", "production runtime busy"),
    ),
)
def test_run_state_priority_precedes_request_validation(
    closed: bool, readiness: str, message: str
) -> None:
    module = importlib.import_module("specstyle.workflow.production_service")
    runtime = _runtime_for_close(module, [])
    runtime._closed = closed
    runtime._readiness_value = module._RuntimeReadiness(readiness)

    with pytest.raises(InfrastructureError, match=f"^{message}$"):
        runtime.run(object())


def test_close_and_reopen_are_mutually_exclusive(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = importlib.import_module("specstyle.workflow.production_service")
    calls: list[str] = []
    runtime = _quarantined_runtime(module, calls)
    old_loaded = runtime._loaded
    fresh_loaded = _CloseProbe("fresh-loaded", calls)
    fresh_factory = _CloseProbe("fresh-factory", calls)
    load_entered = threading.Event()
    release_load = threading.Event()
    close_done = threading.Event()
    runtime._active_cancel = threading.Event()

    def blocked_load():
        load_entered.set()
        assert release_load.wait(2)
        return fresh_loaded

    runtime._load_pipeline = blocked_load
    monkeypatch.setattr(
        module,
        "_create_production_verifier_factory",
        lambda *_args: fresh_factory,
    )
    reopen_errors: list[BaseException] = []

    def reopen() -> None:
        try:
            runtime.reopen()
        except BaseException as error:
            reopen_errors.append(error)

    def close() -> None:
        runtime.close()
        close_done.set()

    reopen_thread = threading.Thread(target=reopen)
    close_thread = threading.Thread(target=close)
    reopen_thread.start()
    assert load_entered.wait(2)
    close_thread.start()
    assert runtime._active_cancel.wait(2)
    assert runtime.readiness.value == "CLOSED"
    assert not close_done.wait(0.1)
    release_load.set()
    reopen_thread.join(2)
    close_thread.join(2)

    assert not reopen_thread.is_alive() and not close_thread.is_alive()
    assert len(reopen_errors) == 1
    assert type(reopen_errors[0]) is InfrastructureError
    assert str(reopen_errors[0]) == "production runtime closed"
    assert runtime._loaded is old_loaded
    assert runtime._verifier_factory is None
    assert runtime.readiness.value == "CLOSED"
    assert "fresh-factory" in calls and "fresh-loaded" in calls
