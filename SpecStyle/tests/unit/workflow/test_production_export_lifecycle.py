"""APP-COMPOSE-001E publication races and restart recovery."""

from __future__ import annotations

import gc
import os
from pathlib import Path
import threading
import weakref

import pytest

from specstyle.domain.identifiers import JobId
from specstyle.errors import DomainError, InfrastructureError
from specstyle.exporting import bundle as bundle_module
from specstyle.workflow import production_export_lifecycle as lifecycle
from specstyle.workflow import production_service
from specstyle.workflow.job_models import EventType, ExportStartedPayload, JobStatus
from specstyle.workflow.job_store import JobStore
from tests.unit.workflow.test_job_store import _initial_snapshot
from tests.unit.workflow.test_production_export import (
    _append_case_event,
    _case,
    _export_module,
    _export_runtime,
    _persist_case,
    _runtime,
)
from tests.unit.workflow.test_production_runtime_resilience import (
    _runtime_with_job_store,
)


def _command(case):
    return _runtime(case).prepare_export(case.request, case.result, case.credits)


def _start_exporting(store, case) -> None:
    _append_case_event(
        store,
        case,
        EventType.EXPORT_STARTED,
        case.result.job_state.job.status,
        JobStatus.EXPORTING,
        ExportStartedPayload(case.request.bundle_name),
    )


def _target_fd(path: Path) -> int:
    return os.open(path, os.O_RDONLY | os.O_DIRECTORY)


def _close_stores(artifact_store, report_store) -> None:
    report_store.close()
    artifact_store.close()


def _peer_runtime(runtime, state_root: Path):
    peer = object.__new__(production_service.ProductionRuntime)
    for name in production_service.ProductionRuntime.__slots__:
        setattr(peer, name, getattr(runtime, name))
    peer._job_store = JobStore(state_root)
    peer._state_lock = threading.RLock()
    peer._run_lock = threading.Lock()
    peer._active_job_id = None
    peer._active_cancel = None
    peer._active_cancel_reason = None
    peer._readiness_value = production_service.ProductionRuntimeReadiness.READY
    peer._failure_kind_value = None
    peer._closed = False
    return peer


def _persist_case_payloads(artifact_store, report_store, case) -> None:
    artifact_repository = artifact_store.for_job(case.request.job_id)
    report_repository = report_store.for_attempt(
        case.request.job_id, case.result.request.attempt_id
    )
    try:
        artifact_repository.put(case.result.artifact)
        report_repository.put(case.result.request, case.result.report)
    finally:
        report_repository.close()
        artifact_repository.close()


def test_stage_failure_retains_stale_tree_and_never_fakes_completed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    case = _case()
    state_root, target = tmp_path / "state", tmp_path / "exports"
    state_root.mkdir()
    target.mkdir()
    runtime, store, artifacts, reports = _export_runtime(case, state_root)
    failure = InfrastructureError("stage failed")

    def fail_population(*_args) -> None:
        raise failure

    monkeypatch.setattr(bundle_module, "_populate_staging", fail_population)
    target_fd = _target_fd(target)
    try:
        with pytest.raises(InfrastructureError) as raised:
            runtime.publish_export(_command(case), target_fd)
    finally:
        os.close(target_fd)
        _close_stores(artifacts, reports)

    assert raised.value is failure
    assert store.load(case.request.job_id).job.status is JobStatus.EXPORTING
    assert not (target / "bundle").exists()
    assert len(tuple(target.glob(".specstyle-export-*.tmp"))) == 1


def test_post_rename_failure_converges_through_exact_existing_recovery(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    case = _case()
    state_root, target = tmp_path / "state", tmp_path / "exports"
    state_root.mkdir()
    target.mkdir()
    runtime, store, artifacts, reports = _export_runtime(case, state_root)
    command = _command(case)
    original_commit = lifecycle._commit_staged_bundle
    failure = InfrastructureError("lost acknowledgement after rename")

    def fail_after_commit(*args, **kwargs):
        original_commit(*args, **kwargs)
        raise failure

    monkeypatch.setattr(lifecycle, "_commit_staged_bundle", fail_after_commit)
    target_fd = _target_fd(target)
    try:
        with pytest.raises(InfrastructureError) as raised:
            runtime.publish_export(command, target_fd)
        assert raised.value is failure
        assert (target / "bundle" / "manifest.json").is_file()
        assert store.load(case.request.job_id).job.status is JobStatus.EXPORTING
        with pytest.raises(InfrastructureError, match="recovery required"):
            runtime.cancel(case.request.job_id)
        monkeypatch.setattr(lifecycle, "_commit_staged_bundle", original_commit)
        entries = runtime.recover_exports((command,), target_fd)
    finally:
        os.close(target_fd)
        _close_stores(artifacts, reports)

    assert (
        entries[0].disposition
        is _export_module().ProductionRecoveryDisposition.RECOVERED
    )
    assert entries[0].result is not None
    assert entries[0].result.job_state.job.status is JobStatus.COMPLETED


def test_cancel_during_staging_wins_and_prevents_rename(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    case = _case()
    state_root, target = tmp_path / "state", tmp_path / "exports"
    state_root.mkdir()
    target.mkdir()
    runtime, store, artifacts, reports = _export_runtime(case, state_root)
    entered, release = threading.Event(), threading.Event()
    original_stage = lifecycle._stage_bundle

    def blocked_stage(*args):
        entered.set()
        assert release.wait(2)
        return original_stage(*args)

    monkeypatch.setattr(lifecycle, "_stage_bundle", blocked_stage)
    errors: list[Exception] = []
    target_fd = _target_fd(target)

    def publish() -> None:
        try:
            runtime.publish_export(_command(case), target_fd)
        except Exception as error:
            errors.append(error)

    thread = threading.Thread(target=publish)
    thread.start()
    assert entered.wait(2)
    cancelled = runtime.cancel(case.request.job_id)
    release.set()
    thread.join(2)
    os.close(target_fd)
    _close_stores(artifacts, reports)

    assert not thread.is_alive()
    assert cancelled.job.status is JobStatus.CANCELLED
    assert len(errors) == 1 and isinstance(errors[0], DomainError)
    assert store.load(case.request.job_id).job.status is JobStatus.CANCELLED
    assert not (target / "bundle").exists()


def test_cancel_during_recovery_staging_wins_before_commit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    case = _case()
    state_root, target = tmp_path / "state", tmp_path / "exports"
    state_root.mkdir()
    target.mkdir()
    runtime, store, artifacts, reports = _export_runtime(case, state_root)
    _start_exporting(store, case)
    entered, release, cancel_done = (
        threading.Event(),
        threading.Event(),
        threading.Event(),
    )
    original_stage = lifecycle._stage_bundle

    def blocked_stage(*args):
        entered.set()
        assert release.wait(3)
        return original_stage(*args)

    monkeypatch.setattr(lifecycle, "_stage_bundle", blocked_stage)
    recovery_errors: list[Exception] = []
    cancel_errors: list[Exception] = []
    cancelled: list[object] = []
    target_fd = _target_fd(target)
    recovery_thread = threading.Thread(
        target=lambda: _capture_error(
            recovery_errors,
            lambda: runtime.recover_exports((_command(case),), target_fd),
        )
    )

    def cancel() -> None:
        try:
            cancelled.append(runtime.cancel(case.request.job_id))
        except Exception as error:
            cancel_errors.append(error)
        finally:
            cancel_done.set()

    recovery_thread.start()
    assert entered.wait(3)
    cancel_thread = threading.Thread(target=cancel)
    cancel_thread.start()
    cancelled_while_staging = cancel_done.wait(0.2)
    release.set()
    recovery_thread.join(3)
    cancel_thread.join(3)
    os.close(target_fd)
    _close_stores(artifacts, reports)

    assert cancelled_while_staging
    assert cancel_errors == []
    assert len(cancelled) == 1 and cancelled[0].job.status is JobStatus.CANCELLED
    assert len(recovery_errors) == 1 and isinstance(recovery_errors[0], DomainError)
    assert store.load(case.request.job_id).job.status is JobStatus.CANCELLED
    assert not (target / "bundle").exists()


def test_recovery_stage_failure_releases_operation_for_a_retry(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    case = _case()
    state_root, target = tmp_path / "state", tmp_path / "exports"
    state_root.mkdir()
    target.mkdir()
    runtime, store, artifacts, reports = _export_runtime(case, state_root)
    _start_exporting(store, case)
    command = _command(case)
    original_stage = lifecycle._stage_bundle
    failure = InfrastructureError("recovery stage failed")
    calls = 0

    def fail_once(*args):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise failure
        return original_stage(*args)

    monkeypatch.setattr(lifecycle, "_stage_bundle", fail_once)
    target_fd = _target_fd(target)
    try:
        with pytest.raises(InfrastructureError) as raised:
            runtime.recover_exports((command,), target_fd)
        recovered = runtime.recover_exports((command,), target_fd)
    finally:
        os.close(target_fd)
        _close_stores(artifacts, reports)

    assert raised.value is failure
    assert calls == 2
    assert recovered[0].result is not None
    assert store.load(case.request.job_id).job.status is JobStatus.COMPLETED


def test_rename_winner_completes_before_waiting_cancel_observes_terminal(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    case = _case()
    state_root, target = tmp_path / "state", tmp_path / "exports"
    state_root.mkdir()
    target.mkdir()
    runtime, store, artifacts, reports = _export_runtime(case, state_root)
    entered, release = threading.Event(), threading.Event()
    original_commit = lifecycle._commit_staged_bundle

    def blocked_commit(*args, **kwargs):
        entered.set()
        assert release.wait(2)
        return original_commit(*args, **kwargs)

    monkeypatch.setattr(lifecycle, "_commit_staged_bundle", blocked_commit)
    publish_results: list[object] = []
    cancel_errors: list[Exception] = []
    target_fd = _target_fd(target)
    publisher = threading.Thread(
        target=lambda: publish_results.append(
            runtime.publish_export(_command(case), target_fd)
        )
    )

    def cancel() -> None:
        try:
            runtime.cancel(case.request.job_id)
        except Exception as error:
            cancel_errors.append(error)

    publisher.start()
    assert entered.wait(2)
    canceller = threading.Thread(target=cancel)
    canceller.start()
    assert canceller.is_alive()
    release.set()
    publisher.join(2)
    canceller.join(2)
    os.close(target_fd)
    _close_stores(artifacts, reports)

    assert len(publish_results) == 1
    assert len(cancel_errors) == 1
    assert isinstance(cancel_errors[0], DomainError)
    assert store.load(case.request.job_id).job.status is JobStatus.COMPLETED


def test_completed_recovery_reinspects_exact_bundle_without_new_event(
    tmp_path: Path,
) -> None:
    case = _case()
    state_root, target = tmp_path / "state", tmp_path / "exports"
    state_root.mkdir()
    target.mkdir()
    runtime, store, artifacts, reports = _export_runtime(case, state_root)
    command = _command(case)
    target_fd = _target_fd(target)
    try:
        published = runtime.publish_export(command, target_fd)
        before = store.list_events(case.request.job_id)
        entries = runtime.recover_exports((command,), target_fd)
    finally:
        os.close(target_fd)
        _close_stores(artifacts, reports)

    assert (
        entries[0].disposition
        is _export_module().ProductionRecoveryDisposition.ALREADY_COMPLETED
    )
    assert entries[0].result == published
    assert store.list_events(case.request.job_id) == before


def test_conflicting_final_fails_recovery_closed(
    tmp_path: Path,
) -> None:
    case = _case()
    state_root, target = tmp_path / "state", tmp_path / "exports"
    state_root.mkdir()
    target.mkdir()
    runtime, store, artifacts, reports = _export_runtime(case, state_root)
    _start_exporting(store, case)
    conflict = target / "bundle"
    conflict.mkdir(mode=0o700)
    (conflict / "manifest.json").write_bytes(b"{}")
    target_fd = _target_fd(target)
    try:
        with pytest.raises(DomainError):
            runtime.recover_exports((_command(case),), target_fd)
    finally:
        os.close(target_fd)
        _close_stores(artifacts, reports)

    assert store.load(case.request.job_id).job.status is JobStatus.EXPORTING
    assert (conflict / "manifest.json").read_bytes() == b"{}"


def test_recovery_rejects_duplicate_commands_before_touching_jobs(
    tmp_path: Path,
) -> None:
    case = _case()
    state_root, target = tmp_path / "state", tmp_path / "exports"
    state_root.mkdir()
    target.mkdir()
    runtime, _store, artifacts, reports = _export_runtime(case, state_root)
    command = _command(case)
    target_fd = _target_fd(target)
    try:
        with pytest.raises(DomainError, match="invalid production export recovery"):
            runtime.recover_exports((command, command), target_fd)
    finally:
        os.close(target_fd)
        _close_stores(artifacts, reports)


def test_missing_recovery_commands_follow_stable_job_order(tmp_path: Path) -> None:
    state_root, target = tmp_path / "state", tmp_path / "exports"
    state_root.mkdir()
    target.mkdir()
    store = JobStore(state_root)
    for job_id in ("job-z", "Job-a", "job-10"):
        store.save_snapshot(JobId(job_id), _initial_snapshot(job_id))
    runtime = _runtime_with_job_store(production_service, store)
    target_fd = _target_fd(target)
    try:
        entries = runtime.recover_exports((), target_fd)
    finally:
        os.close(target_fd)

    assert tuple(entry.job_id.value for entry in entries) == (
        "Job-a",
        "job-10",
        "job-z",
    )
    assert all(
        entry.disposition
        is _export_module().ProductionRecoveryDisposition.SKIPPED_MISSING_COMMAND
        for entry in entries
    )


def test_export_holders_are_strong_per_live_inode_namespace_then_collectable(
    tmp_path: Path,
) -> None:
    import specstyle.workflow.job_store as store_module

    first_store = JobStore(tmp_path)
    second_store = JobStore(tmp_path)
    identity = first_store._root_identity
    first = lifecycle._export_lock_holder(first_store, JobId("job-a"))
    same = lifecycle._export_lock_holder(second_store, JobId("job-a"))
    other = lifecycle._export_lock_holder(first_store, JobId("job-b"))
    namespace_reference = weakref.ref(first_store._namespace_holder)

    assert first is same
    assert first is not other
    assert first.job_holder is first_store._job_lock_holder(JobId("job-a"))
    assert other.lock.acquire(blocking=False)
    other.lock.release()
    first_store.close()
    del first_store
    gc.collect()
    assert namespace_reference() is second_store._namespace_holder

    second_store.close()
    del second_store, first, same, other
    gc.collect()
    assert namespace_reference() is None
    assert identity not in store_module._NAMESPACE_HOLDERS


def test_idle_export_and_job_holders_are_collectable_in_live_namespace(
    tmp_path: Path,
) -> None:
    store = JobStore(tmp_path)
    namespace = store._namespace_holder
    held = lifecycle._export_lock_holder(store, JobId("job-held"))
    try:
        for index in range(128):
            lifecycle._export_lock_holder(store, JobId(f"job-{index}"))
        gc.collect()
        assert namespace is not None
        assert tuple(namespace.exports) == ("job-held",)
        assert tuple(namespace.jobs) == ("job-held",)
        assert held.job_holder is namespace.jobs["job-held"]
        del held
        gc.collect()
        assert len(namespace.exports) == 0
        assert len(namespace.jobs) == 0
    finally:
        store.close()


def test_export_lock_blocks_direct_job_store_operation_for_same_job(
    tmp_path: Path,
) -> None:
    store = JobStore(tmp_path)
    job_id = JobId("job-a")
    holder = lifecycle._export_lock_holder(store, job_id)
    entered = threading.Event()
    finished = threading.Event()
    errors: list[BaseException] = []

    def read_job() -> None:
        entered.set()
        try:
            store.get_snapshot(job_id)
        except BaseException as cause:
            errors.append(cause)
        finally:
            finished.set()

    thread = threading.Thread(target=read_job)
    try:
        with holder.lock:
            thread.start()
            assert entered.wait(2)
            assert not finished.wait(0.1)
        assert finished.wait(2)
        thread.join(2)
        assert not thread.is_alive()
        assert errors == []
    finally:
        store.close()


def test_persistence_tamper_fails_before_export_started(
    tmp_path: Path,
) -> None:
    case = _case()
    state_root, target = tmp_path / "state", tmp_path / "exports"
    state_root.mkdir()
    target.mkdir()
    runtime, store, artifacts, reports = _export_runtime(case, state_root)
    artifact_id = case.result.artifact.ref.artifact_id.value
    artifact_file = (
        tmp_path
        / "state-persistence"
        / "jobs"
        / case.request.job_id.value
        / "artifacts"
        / artifact_id
        / "artifact.png"
    )
    artifact_file.write_bytes(b"tampered")
    before = store.list_events(case.request.job_id)
    target_fd = _target_fd(target)
    try:
        with pytest.raises(InfrastructureError):
            runtime.publish_export(_command(case), target_fd)
    finally:
        os.close(target_fd)
        _close_stores(artifacts, reports)

    assert store.list_events(case.request.job_id) == before
    assert not tuple(target.iterdir())


def test_published_event_failure_leaves_exact_final_for_recovery(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    case = _case()
    state_root, target = tmp_path / "state", tmp_path / "exports"
    state_root.mkdir()
    target.mkdir()
    runtime, store, artifacts, reports = _export_runtime(case, state_root)
    command = _command(case)
    original_append = production_service.ProductionRuntime._append_export_event
    failure = InfrastructureError("event append failed")

    def fail_published(self, job_id, event_type, from_state, to_state, payload):
        if event_type is EventType.EXPORT_PUBLISHED:
            raise failure
        return original_append(self, job_id, event_type, from_state, to_state, payload)

    monkeypatch.setattr(
        production_service.ProductionRuntime,
        "_append_export_event",
        fail_published,
    )
    target_fd = _target_fd(target)
    try:
        with pytest.raises(InfrastructureError) as raised:
            runtime.publish_export(command, target_fd)
        assert raised.value is failure
        assert store.load(case.request.job_id).job.status is JobStatus.EXPORTING
        assert (target / "bundle" / "manifest.json").is_file()
        with pytest.raises(InfrastructureError, match="recovery required"):
            runtime.cancel(case.request.job_id)
        monkeypatch.setattr(
            production_service.ProductionRuntime,
            "_append_export_event",
            original_append,
        )
        recovered = runtime.recover_exports((command,), target_fd)
    finally:
        os.close(target_fd)
        _close_stores(artifacts, reports)

    assert recovered[0].result is not None
    assert recovered[0].result.job_state.job.status is JobStatus.COMPLETED


def test_completed_bundle_tamper_is_never_reported_already_completed(
    tmp_path: Path,
) -> None:
    case = _case()
    state_root, target = tmp_path / "state", tmp_path / "exports"
    state_root.mkdir()
    target.mkdir()
    runtime, store, artifacts, reports = _export_runtime(case, state_root)
    command = _command(case)
    target_fd = _target_fd(target)
    try:
        runtime.publish_export(command, target_fd)
        (target / "bundle" / "manifest.json").write_bytes(b"{}")
        with pytest.raises(DomainError):
            runtime.recover_exports((command,), target_fd)
    finally:
        os.close(target_fd)
        _close_stores(artifacts, reports)

    assert store.load(case.request.job_id).job.status is JobStatus.COMPLETED


def test_recovery_distinguishes_not_exportable_and_terminal_jobs(
    tmp_path: Path,
) -> None:
    module = _export_module()
    case = _case()
    state_root, target = tmp_path / "state", tmp_path / "exports"
    state_root.mkdir()
    target.mkdir()
    runtime, _store, artifacts, reports = _export_runtime(case, state_root)
    command = _command(case)
    target_fd = _target_fd(target)
    try:
        skipped = runtime.recover_exports((command,), target_fd)
        runtime.cancel(case.request.job_id)
        terminal = runtime.recover_exports((command,), target_fd)
    finally:
        os.close(target_fd)
        _close_stores(artifacts, reports)

    assert (
        skipped[0].disposition
        is module.ProductionRecoveryDisposition.SKIPPED_NOT_EXPORTABLE
    )
    assert (
        terminal[0].disposition is module.ProductionRecoveryDisposition.SKIPPED_TERMINAL
    )


def test_recovery_requires_exact_tuple_and_trusted_root_fd(tmp_path: Path) -> None:
    case = _case()
    state_root, target = tmp_path / "state", tmp_path / "exports"
    state_root.mkdir()
    target.mkdir()
    runtime, _store, artifacts, reports = _export_runtime(case, state_root)
    command = _command(case)
    target_fd = _target_fd(target)
    try:
        with pytest.raises(DomainError):
            runtime.recover_exports([command], target_fd)
        with pytest.raises(DomainError):
            runtime.recover_exports((command,), True)
    finally:
        os.close(target_fd)
        _close_stores(artifacts, reports)


def test_close_waits_for_in_progress_recovery_before_closing_stores(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    case = _case()
    state_root, target = tmp_path / "state", tmp_path / "exports"
    state_root.mkdir()
    target.mkdir()
    runtime, store, _artifacts, _reports = _export_runtime(case, state_root)
    _start_exporting(store, case)
    entered, release, close_done = (
        threading.Event(),
        threading.Event(),
        threading.Event(),
    )
    original_stage = lifecycle._stage_bundle

    def blocked_stage(*args):
        entered.set()
        assert release.wait(2)
        return original_stage(*args)

    monkeypatch.setattr(lifecycle, "_stage_bundle", blocked_stage)
    recovery_errors: list[Exception] = []
    close_errors: list[Exception] = []
    target_fd = _target_fd(target)

    def recover() -> None:
        try:
            runtime.recover_exports((_command(case),), target_fd)
        except Exception as error:
            recovery_errors.append(error)

    def close() -> None:
        try:
            runtime.close()
        except Exception as error:
            close_errors.append(error)
        finally:
            close_done.set()

    recoverer = threading.Thread(target=recover)
    closer = threading.Thread(target=close)
    recoverer.start()
    assert entered.wait(2)
    closer.start()
    close_waited = not close_done.wait(0.1)
    release.set()
    recoverer.join(2)
    closer.join(2)
    os.close(target_fd)

    assert close_waited
    assert not recoverer.is_alive() and not closer.is_alive()
    assert recovery_errors == [] and close_errors == []
    assert store.load(case.request.job_id).job.status is JobStatus.COMPLETED


@pytest.mark.parametrize("recovering", (False, True))
def test_active_export_operation_rejects_same_thread_close_without_mutation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    recovering: bool,
) -> None:
    case = _case()
    state_root, target = tmp_path / "state", tmp_path / "exports"
    state_root.mkdir()
    target.mkdir()
    runtime, store, artifacts, reports = _export_runtime(case, state_root)
    command = _command(case)
    if recovering:
        _start_exporting(store, case)
    original_stage = lifecycle._stage_bundle
    close_attempts: list[InfrastructureError] = []

    def stage(*args):
        with pytest.raises(
            InfrastructureError, match="close from active run"
        ) as raised:
            runtime.close()
        close_attempts.append(raised.value)
        return original_stage(*args)

    monkeypatch.setattr(lifecycle, "_stage_bundle", stage)
    target_fd = _target_fd(target)
    try:
        if recovering:
            runtime.recover_exports((command,), target_fd)
        else:
            runtime.publish_export(command, target_fd)
    finally:
        os.close(target_fd)
        _close_stores(artifacts, reports)

    assert len(close_attempts) == 1
    assert runtime._closed is False
    assert store.load(case.request.job_id).job.status is JobStatus.COMPLETED


def test_same_job_serializes_while_different_job_remains_independent(
    tmp_path: Path,
) -> None:
    store = JobStore(tmp_path)
    held = lifecycle._export_lock_holder(store, JobId("job-a"))
    same = lifecycle._export_lock_holder(store, JobId("job-a"))
    different = lifecycle._export_lock_holder(store, JobId("job-b"))
    same_entered, different_entered = threading.Event(), threading.Event()

    def acquire(holder, entered) -> None:
        with holder.lock:
            entered.set()

    held.lock.acquire()
    same_thread = threading.Thread(target=acquire, args=(same, same_entered))
    different_thread = threading.Thread(
        target=acquire, args=(different, different_entered)
    )
    same_thread.start()
    different_thread.start()
    assert different_entered.wait(2)
    assert not same_entered.wait(0.1)
    held.lock.release()
    same_thread.join(2)
    different_thread.join(2)

    assert same_entered.is_set()
    assert not same_thread.is_alive() and not different_thread.is_alive()


@pytest.mark.parametrize("first_stage_fails", (False, True))
def test_peer_recovery_waits_for_the_whole_same_job_publish_operation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    first_stage_fails: bool,
) -> None:
    case = _case()
    state_root, target = tmp_path / "state", tmp_path / "exports"
    state_root.mkdir()
    target.mkdir()
    publisher, store, artifacts, reports = _export_runtime(case, state_root)
    recoverer = _peer_runtime(publisher, state_root)
    command = _command(case)
    first_entered, release_first, second_entered = (
        threading.Event(),
        threading.Event(),
        threading.Event(),
    )
    call_lock = threading.Lock()
    stage_calls = 0
    failure = InfrastructureError("first stage failed")
    original_stage = lifecycle._stage_bundle

    def controlled_stage(*args):
        nonlocal stage_calls
        with call_lock:
            stage_calls += 1
            position = stage_calls
        if position == 1:
            first_entered.set()
            assert release_first.wait(3)
            if first_stage_fails:
                raise failure
        else:
            second_entered.set()
        return original_stage(*args)

    monkeypatch.setattr(lifecycle, "_stage_bundle", controlled_stage)
    publish_errors: list[Exception] = []
    recovery_errors: list[Exception] = []
    target_fd = _target_fd(target)
    publish_thread = threading.Thread(
        target=lambda: _capture_error(
            publish_errors, lambda: publisher.publish_export(command, target_fd)
        )
    )
    recovery_thread = threading.Thread(
        target=lambda: _capture_error(
            recovery_errors, lambda: recoverer.recover_exports((command,), target_fd)
        )
    )
    publish_thread.start()
    assert first_entered.wait(3)
    recovery_thread.start()
    serialized = not second_entered.wait(0.2)
    release_first.set()
    publish_thread.join(3)
    recovery_thread.join(3)
    os.close(target_fd)
    _close_stores(artifacts, reports)

    assert serialized
    assert not publish_thread.is_alive() and not recovery_thread.is_alive()
    assert recovery_errors == []
    if first_stage_fails:
        assert publish_errors == [failure]
        assert stage_calls == 2
    else:
        assert publish_errors == []
        assert stage_calls == 1
    assert store.load(case.request.job_id).job.status is JobStatus.COMPLETED


def _capture_error(errors: list[Exception], operation) -> None:
    try:
        operation()
    except Exception as error:
        errors.append(error)


def test_peer_publish_for_a_different_job_stages_in_parallel(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    first, second = _case(job_id="job-a"), _case(job_id="job-b")
    state_root = tmp_path / "state"
    first_target, second_target = tmp_path / "exports-a", tmp_path / "exports-b"
    state_root.mkdir()
    first_target.mkdir()
    second_target.mkdir()
    first_runtime, store, artifacts, reports = _export_runtime(first, state_root)
    _persist_case(store, second)
    _persist_case_payloads(artifacts, reports, second)
    second_runtime = _peer_runtime(first_runtime, state_root)
    first_entered, release_first, second_entered = (
        threading.Event(),
        threading.Event(),
        threading.Event(),
    )
    first_fd, second_fd = _target_fd(first_target), _target_fd(second_target)
    original_stage = lifecycle._stage_bundle

    def controlled_stage(*args):
        if args[1] == first_fd:
            first_entered.set()
            assert release_first.wait(3)
        elif args[1] == second_fd:
            second_entered.set()
        return original_stage(*args)

    monkeypatch.setattr(lifecycle, "_stage_bundle", controlled_stage)
    errors: list[Exception] = []
    first_thread = threading.Thread(
        target=lambda: _capture_error(
            errors,
            lambda: first_runtime.publish_export(_command(first), first_fd),
        )
    )
    second_thread = threading.Thread(
        target=lambda: _capture_error(
            errors,
            lambda: second_runtime.publish_export(_command(second), second_fd),
        )
    )
    first_thread.start()
    assert first_entered.wait(3)
    second_thread.start()
    parallel = second_entered.wait(3)
    release_first.set()
    first_thread.join(3)
    second_thread.join(3)
    os.close(first_fd)
    os.close(second_fd)
    _close_stores(artifacts, reports)

    assert parallel
    assert errors == []
    assert not first_thread.is_alive() and not second_thread.is_alive()
    assert store.load(first.request.job_id).job.status is JobStatus.COMPLETED
    assert store.load(second.request.job_id).job.status is JobStatus.COMPLETED


def test_missing_report_fails_before_staging_or_state_change(tmp_path: Path) -> None:
    case = _case()
    state_root, target = tmp_path / "state", tmp_path / "exports"
    state_root.mkdir()
    target.mkdir()
    runtime, store, artifacts, reports = _export_runtime(case, state_root)
    report_file = (
        tmp_path
        / "state-persistence"
        / "jobs"
        / case.request.job_id.value
        / "reports"
        / case.result.request.attempt_id.value
        / "report.json"
    )
    report_file.unlink()
    before = store.list_events(case.request.job_id)
    target_fd = _target_fd(target)
    try:
        with pytest.raises(InfrastructureError):
            runtime.publish_export(_command(case), target_fd)
    finally:
        os.close(target_fd)
        _close_stores(artifacts, reports)

    assert store.list_events(case.request.job_id) == before
    assert not tuple(target.iterdir())
