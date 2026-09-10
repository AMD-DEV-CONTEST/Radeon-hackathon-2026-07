"""WF-001 JobStore, state-machine, and recovery contract tests."""

from __future__ import annotations

import gc
import os
from pathlib import Path
from threading import Event as ThreadEvent
from threading import Thread

import pytest

from specstyle.domain.enums import (
    ArtifactStatus,
    DecisionReason,
    RepairStopReason,
)
from specstyle.domain.identifiers import (
    ArtifactId,
    AttemptId,
    DecisionId,
    Identifier,
    JobId,
    RuleId,
    Sha256,
)
from specstyle.errors import DomainError, InfrastructureError
from specstyle.workflow.job_models import (
    AttemptFinishedPayload,
    AttemptStartedPayload,
    CancelRequestedPayload,
    Event,
    EventType,
    ExportPublishedPayload,
    ExportStartedPayload,
    FatalPayload,
    Job,
    JobBudget,
    JobSnapshot,
    JobStartedPayload,
    JobState,
    RepairStepPayload,
    SpecCompiledPayload,
    VerifierFinishedPayload,
)
from specstyle.workflow.job_store import JobStore
from specstyle.workflow.state_machine import (
    TRANSITIONS,
    validate_transition,
)

_TS = "2026-07-31T10:20:30.123Z"
_TS2 = "2026-07-31T10:20:31.123Z"


def _job(status="CREATED") -> Job:
    from specstyle.workflow.job_models import JobStatus

    return Job(
        JobId("job1"),
        Sha256("a" * 64),
        ("xhs_grid",),
        JobBudget(2),
        JobStatus(status),
        _TS,
        _TS,
    )


def _event(
    seq: int,
    event_type: EventType,
    from_state: str,
    to_state: str,
    payload: object,
    ts: str = _TS2,
) -> Event:
    from specstyle.workflow.job_models import JobStatus

    return Event(
        seq,
        JobId("job1"),
        event_type,
        JobStatus(from_state),
        JobStatus(to_state),
        ts,
        payload,
    )


def _store(tmp_path: Path) -> JobStore:
    return JobStore(tmp_path)


def _initial_snapshot(job_id: str) -> JobSnapshot:
    source = _job()
    return JobSnapshot(
        "specstyle.workflow.snapshot.v1",
        Job(
            JobId(job_id),
            source.compiled_spec_hash,
            source.cohort_profiles,
            source.budget,
            source.status,
            source.created_at,
            source.updated_at,
        ),
        0,
        (),
        (),
    )


def _start_payload() -> JobStartedPayload:
    return JobStartedPayload(Sha256("a" * 64), ("xhs_grid",), JobBudget(2))


def _attempt_payload(attempt: str = "att1") -> AttemptStartedPayload:
    return AttemptStartedPayload(0, 0, AttemptId(attempt), None)


def _attempt_finished_payload(attempt: str = "att1") -> AttemptFinishedPayload:
    return AttemptFinishedPayload(
        0, 0, AttemptId(attempt), ArtifactId("art1"), Sha256("b" * 64)
    )


def _verifier_payload(status="APPROVED") -> VerifierFinishedPayload:
    return VerifierFinishedPayload(
        0,
        0,
        ArtifactId("art1"),
        ArtifactStatus(status),
        DecisionReason.ALL_REQUIRED_PASS,
        RepairStopReason.PASS_ALL_REQUIRED,
    )


def _repair_step_payload(child_attempt_id: str = "att2") -> RepairStepPayload:
    return RepairStepPayload(
        0,
        0,
        DecisionId("decision1"),
        Identifier("style_strength_inc"),
        RuleId("STYLE_LOW"),
        AttemptId("att1"),
        AttemptId(child_attempt_id),
    )


def _export_payload(name="bundle1") -> ExportPublishedPayload:
    return ExportPublishedPayload(
        name, Sha256("c" * 64), Sha256("d" * 64), Sha256("e" * 64)
    )


def _seed_started(store: JobStore, tmp_path: Path) -> None:
    store.save_snapshot(
        JobId("job1"), JobSnapshot("specstyle.workflow.snapshot.v1", _job(), 0, (), ())
    )
    store.append_event(
        JobId("job1"),
        _event(1, EventType.JOB_STARTED, "CREATED", "SPEC_VALIDATED", _start_payload()),
    )


def _seed_to(store: JobStore, status: str) -> None:
    store.save_snapshot(
        JobId("job1"), JobSnapshot("specstyle.workflow.snapshot.v1", _job(), 0, (), ())
    )
    if status == "CREATED":
        return
    steps = [
        (EventType.JOB_STARTED, "CREATED", "SPEC_VALIDATED", _start_payload()),
        (
            EventType.SPEC_COMPILED,
            "SPEC_VALIDATED",
            "SPEC_COMPILED",
            SpecCompiledPayload(Sha256("a" * 64)),
        ),
        (
            EventType.ATTEMPT_STARTED,
            "SPEC_COMPILED",
            "GENERATING",
            _attempt_payload("att1"),
        ),
        (
            EventType.ATTEMPT_FINISHED,
            "GENERATING",
            "VERIFYING",
            _attempt_finished_payload("att1"),
        ),
        (
            EventType.VERIFIER_FINISHED,
            "VERIFYING",
            "APPROVED",
            _verifier_payload("APPROVED"),
        ),
        (
            EventType.EXPORT_STARTED,
            "APPROVED",
            "EXPORTING",
            ExportStartedPayload("bundle1"),
        ),
        (
            EventType.EXPORT_PUBLISHED,
            "EXPORTING",
            "COMPLETED",
            _export_payload("bundle1"),
        ),
    ]
    for sequence, (event_type, from_state, to_state, payload) in enumerate(steps, 1):
        store.append_event(
            JobId("job1"),
            _event(sequence, event_type, from_state, to_state, payload),
        )
        if to_state == status:
            return
    raise AssertionError(f"unsupported status: {status}")


def test_save_and_load_initial_snapshot(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store.save_snapshot(
        JobId("job1"),
        JobSnapshot("specstyle.workflow.snapshot.v1", _job(), 0, (), ()),
    )
    state = store.load(JobId("job1"))
    assert state.job.status.value == "CREATED"  # type: ignore[attr-defined]
    assert state.last_sequence == 0  # type: ignore[attr-defined]


def test_list_job_ids_returns_empty_or_ascii_sorted_ids(tmp_path: Path) -> None:
    store = _store(tmp_path)
    assert store.list_job_ids() == ()
    (tmp_path / "jobs").mkdir()
    assert store.list_job_ids() == ()

    for value in ("job-z", "job-2", "Job-a", "job-10"):
        store.save_snapshot(JobId(value), _initial_snapshot(value))

    assert store.list_job_ids() == (
        JobId("Job-a"),
        JobId("job-10"),
        JobId("job-2"),
        JobId("job-z"),
    )


@pytest.mark.parametrize("name", [".hidden", "bad name", "évil"])
def test_list_job_ids_rejects_hostile_unknown_entries(
    tmp_path: Path, name: str
) -> None:
    store = _store(tmp_path)
    jobs = tmp_path / "jobs"
    jobs.mkdir()
    (jobs / name).mkdir()

    with pytest.raises(InfrastructureError, match="^job store corrupted$"):
        store.list_job_ids()


@pytest.mark.parametrize("entry_type", ["regular", "symlink"])
def test_list_job_ids_rejects_invalid_jobs_root_type(
    tmp_path: Path, entry_type: str
) -> None:
    jobs = tmp_path / "jobs"
    if entry_type == "regular":
        jobs.write_bytes(b"not a namespace")
    else:
        outside = tmp_path / "outside"
        outside.mkdir()
        jobs.symlink_to(outside, target_is_directory=True)

    with pytest.raises(InfrastructureError, match="^job store corrupted$"):
        _store(tmp_path).list_job_ids()


@pytest.mark.parametrize("entry_type", ["regular", "symlink", "empty_directory"])
def test_list_job_ids_rejects_invalid_job_directory_types(
    tmp_path: Path, entry_type: str
) -> None:
    store = _store(tmp_path)
    store.save_snapshot(JobId("valid"), _initial_snapshot("valid"))
    jobs = tmp_path / "jobs"
    entry = jobs / "other"
    if entry_type == "regular":
        entry.write_bytes(b"not a job")
    elif entry_type == "symlink":
        entry.symlink_to(jobs / "valid", target_is_directory=True)
    else:
        entry.mkdir()

    with pytest.raises(InfrastructureError, match="^job store corrupted$"):
        store.list_job_ids()


@pytest.mark.parametrize("mutation", ["corrupt", "aliased"])
def test_list_job_ids_rejects_corrupt_or_aliased_snapshot(
    tmp_path: Path, mutation: str
) -> None:
    store = _store(tmp_path)
    store.save_snapshot(JobId("job1"), _initial_snapshot("job1"))
    job_dir = tmp_path / "jobs" / "job1"
    if mutation == "corrupt":
        (job_dir / "snapshot.json").write_bytes(b"{")
    else:
        job_dir.rename(tmp_path / "jobs" / "job2")

    with pytest.raises(InfrastructureError, match="^job store corrupted$"):
        store.list_job_ids()


def test_list_job_ids_detects_job_directory_replacement_after_validation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import specstyle.workflow.job_store as store_mod

    store = _store(tmp_path)
    store.save_snapshot(JobId("job1"), _initial_snapshot("job1"))
    replacement_root = tmp_path / "replacement-root"
    replacement_root.mkdir()
    replacement_store = _store(replacement_root)
    replacement_store.save_snapshot(JobId("job1"), _initial_snapshot("job1"))
    original_validate = store_mod._validated_state_from_fd

    def replace_after_validation(job_fd, identity, job_id):
        state = original_validate(job_fd, identity, job_id)
        job_dir = tmp_path / "jobs" / "job1"
        job_dir.rename(tmp_path / "displaced-job1")
        (replacement_root / "jobs" / "job1").rename(job_dir)
        return state

    monkeypatch.setattr(store_mod, "_validated_state_from_fd", replace_after_validation)
    with pytest.raises(InfrastructureError, match="^job store corrupted$"):
        store.list_job_ids()


def test_list_job_ids_rejects_jobs_tree_rebind_after_entry_validation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = _store(tmp_path)
    store.save_snapshot(JobId("job1"), _initial_snapshot("job1"))
    replacement_root = tmp_path / "replacement-root"
    replacement_root.mkdir()
    replacement_store = _store(replacement_root)
    replacement_store.save_snapshot(JobId("job1"), _initial_snapshot("job1"))
    replacement_store.close()
    original_validate = store._validated_listed_job
    rebound = False

    def rebind_after_validation(jobs_fd: int, name: str, /):
        nonlocal rebound
        result = original_validate(jobs_fd, name)
        if not rebound:
            rebound = True
            (tmp_path / "jobs").rename(tmp_path / "displaced-jobs")
            (replacement_root / "jobs").rename(tmp_path / "jobs")
        return result

    monkeypatch.setattr(store, "_validated_listed_job", rebind_after_validation)
    with pytest.raises(InfrastructureError, match="^job store corrupted$"):
        store.list_job_ids()
    assert rebound


def test_list_job_ids_does_not_resolve_jobs_path_after_construction(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = _store(tmp_path)
    jobs = tmp_path / "jobs"
    jobs.mkdir()
    del monkeypatch
    assert store.list_job_ids() == ()


@pytest.mark.parametrize("filename", ["snapshot.json", "events.ndjson"])
@pytest.mark.parametrize("alias_type", ["symlink", "hardlink"])
def test_list_job_ids_rejects_aliased_state_files(
    tmp_path: Path, filename: str, alias_type: str
) -> None:
    store = _store(tmp_path)
    _seed_started(store, tmp_path)
    path = tmp_path / "jobs" / "job1" / filename
    alias = tmp_path / f"outside-{filename}"
    if alias_type == "symlink":
        path.rename(alias)
        path.symlink_to(alias)
    else:
        os.link(path, alias)

    with pytest.raises(InfrastructureError, match="^job store corrupted$"):
        store.list_job_ids()


def test_list_job_ids_uses_bounded_descriptor_reads(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import specstyle.workflow.job_store as store_mod

    store = _store(tmp_path)
    _seed_started(store, tmp_path)
    real_read = os.read
    requests: list[int] = []

    def bounded_read(fd: int, amount: int) -> bytes:
        requests.append(amount)
        return real_read(fd, amount)

    monkeypatch.setattr(store_mod.os, "read", bounded_read)
    assert store.list_job_ids() == (JobId("job1"),)
    assert requests
    assert max(requests) <= 64 * 1024


def test_list_job_ids_detects_state_file_mutation_during_descriptor_read(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import specstyle.workflow.job_store as store_mod

    store = _store(tmp_path)
    store.save_snapshot(JobId("job1"), _initial_snapshot("job1"))
    snapshot = tmp_path / "jobs" / "job1" / "snapshot.json"
    content = snapshot.read_bytes()
    replacement = tmp_path / "replacement-snapshot.json"
    replacement.write_bytes(content)
    replacement.chmod(0o600)
    real_read = os.read
    mutated = False

    def mutate_after_read(fd: int, amount: int) -> bytes:
        nonlocal mutated
        result = real_read(fd, amount)
        if result and not mutated:
            mutated = True
            replacement.replace(snapshot)
        return result

    monkeypatch.setattr(store_mod.os, "read", mutate_after_read)
    with pytest.raises(InfrastructureError, match="^job store corrupted$"):
        store.list_job_ids()
    assert mutated is True


def test_list_job_ids_rejects_optional_corrupt_events_hidden_during_open(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import specstyle.workflow.job_store as store_mod

    store = _store(tmp_path)
    _seed_started(store, tmp_path)
    events = tmp_path / "jobs" / "job1" / "events.ndjson"
    events.write_bytes(b"{")
    hidden = tmp_path / "hidden-events.ndjson"
    real_open = os.open
    triggered = False

    def hide_during_open(path, flags, mode=0o777, *, dir_fd=None):
        nonlocal triggered
        if not triggered and dir_fd is not None and os.fspath(path) == "events.ndjson":
            triggered = True
            events.rename(hidden)
            try:
                return real_open(path, flags, mode, dir_fd=dir_fd)
            finally:
                hidden.rename(events)
        return real_open(path, flags, mode, dir_fd=dir_fd)

    monkeypatch.setattr(store_mod.os, "open", hide_during_open)
    with pytest.raises(InfrastructureError, match="^job store corrupted$"):
        store.list_job_ids()
    assert triggered is True
    assert events.read_bytes() == b"{"


@pytest.mark.parametrize("mutation", ["delete_snapshot", "add_unknown"])
def test_list_job_ids_rechecks_namespace_after_state_validation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mutation: str
) -> None:
    import specstyle.workflow.job_store as store_mod

    store = _store(tmp_path)
    store.save_snapshot(JobId("job1"), _initial_snapshot("job1"))
    job_dir = tmp_path / "jobs" / "job1"
    original_validate = store_mod._validated_snapshot

    def mutate_after_validation(*args, **kwargs):
        state = original_validate(*args, **kwargs)
        if mutation == "delete_snapshot":
            (job_dir / "snapshot.json").unlink()
        else:
            (job_dir / "hostile.unknown").write_bytes(b"unknown")
        return state

    monkeypatch.setattr(store_mod, "_validated_snapshot", mutate_after_validation)
    with pytest.raises(InfrastructureError, match="^job store corrupted$"):
        store.list_job_ids()


@pytest.mark.parametrize("name", ["hostile.unknown", "snapshot.tmp"])
def test_list_job_ids_rejects_static_unknown_job_state_entries(
    tmp_path: Path, name: str
) -> None:
    store = _store(tmp_path)
    store.save_snapshot(JobId("job1"), _initial_snapshot("job1"))
    (tmp_path / "jobs" / "job1" / name).write_bytes(b"unknown")

    with pytest.raises(InfrastructureError, match="^job store corrupted$"):
        store.list_job_ids()


def test_list_job_ids_rejects_symlinked_unknown_state_entry_without_following(
    tmp_path: Path,
) -> None:
    store = _store(tmp_path)
    store.save_snapshot(JobId("job1"), _initial_snapshot("job1"))
    outside = tmp_path / "outside-state"
    outside.write_bytes(b"do not read")
    unknown = tmp_path / "jobs" / "job1" / "looks-valid"
    unknown.symlink_to(outside)

    with pytest.raises(InfrastructureError, match="^job store corrupted$"):
        store.list_job_ids()
    assert outside.read_bytes() == b"do not read"


def test_list_job_ids_detects_same_name_replacement_after_entry_validation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = _store(tmp_path)
    store.save_snapshot(JobId("job1"), _initial_snapshot("job1"))
    replacement_root = tmp_path / "replacement-root"
    replacement_root.mkdir()
    replacement_store = _store(replacement_root)
    replacement_store.save_snapshot(JobId("job1"), _initial_snapshot("job1"))
    original_validate = store._validated_listed_job
    replaced = False

    def replace_after_validation(jobs_fd: int, name: str, /):
        nonlocal replaced
        result = original_validate(jobs_fd, name)
        if not replaced:
            replaced = True
            job_dir = tmp_path / "jobs" / name
            job_dir.rename(tmp_path / "displaced-job1")
            (replacement_root / "jobs" / name).rename(job_dir)
        return result

    monkeypatch.setattr(store, "_validated_listed_job", replace_after_validation)
    with pytest.raises(InfrastructureError, match="^job store corrupted$"):
        store.list_job_ids()


def test_list_job_ids_closes_descriptors_on_success_and_corruption(
    tmp_path: Path,
) -> None:
    fd_root = next(
        (
            candidate
            for candidate in (Path("/proc/self/fd"), Path("/dev/fd"))
            if candidate.is_dir()
        ),
        None,
    )
    if fd_root is None:
        pytest.skip("descriptor namespace unavailable")
    store = _store(tmp_path)
    store.save_snapshot(JobId("job1"), _initial_snapshot("job1"))
    gc.collect()
    before = len(os.listdir(fd_root))

    for _ in range(50):
        assert store.list_job_ids() == (JobId("job1"),)
    after_success = len(os.listdir(fd_root))
    (tmp_path / "jobs" / "job1" / "snapshot.json").write_bytes(b"{")
    for _ in range(50):
        with pytest.raises(InfrastructureError, match="^job store corrupted$"):
            store.list_job_ids()

    assert (before, after_success, len(os.listdir(fd_root))) == (
        before,
        before,
        before,
    )


@pytest.mark.parametrize("mutation", ["added", "removed"])
def test_list_job_ids_detects_namespace_change_after_enumeration(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mutation: str
) -> None:
    store = _store(tmp_path)
    store.save_snapshot(JobId("job1"), _initial_snapshot("job1"))
    jobs = tmp_path / "jobs"
    original_validate = store._validated_listed_job
    mutated = False

    def mutate_after_validation(jobs_fd: int, name: str, /):
        nonlocal mutated
        result = original_validate(jobs_fd, name)
        if not mutated:
            mutated = True
            if mutation == "added":
                (jobs / "late").mkdir()
            else:
                (jobs / name).rename(tmp_path / "removed-job")
        return result

    monkeypatch.setattr(store, "_validated_listed_job", mutate_after_validation)
    with pytest.raises(InfrastructureError, match="^job store corrupted$"):
        store.list_job_ids()


def test_list_job_ids_retries_legitimate_completed_namespace_addition(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    first = _store(tmp_path)
    second = _store(tmp_path)
    first.save_snapshot(JobId("job1"), _initial_snapshot("job1"))
    original = first._validated_listed_job
    additions = 0

    def add_after_validation(jobs_fd: int, name: str, /):
        nonlocal additions
        result = original(jobs_fd, name)
        if additions < 5:
            additions += 1
            added = f"job{additions + 1}"
            second.save_snapshot(JobId(added), _initial_snapshot(added))
        return result

    monkeypatch.setattr(first, "_validated_listed_job", add_after_validation)
    try:
        assert first.list_job_ids() == tuple(
            JobId(f"job{index}") for index in range(1, 7)
        )
    finally:
        first.close()
        second.close()


def test_save_snapshot_rejects_cross_job_before_creating_directory(
    tmp_path: Path,
) -> None:
    store = _store(tmp_path)
    with pytest.raises(DomainError, match="invalid job snapshot"):
        store.save_snapshot(
            JobId("other"),
            JobSnapshot("specstyle.workflow.snapshot.v1", _job(), 0, (), ()),
        )
    assert not (tmp_path / "jobs" / "other").exists()


@pytest.mark.parametrize(
    ("event_type", "from_state", "to_state", "payload"),
    [
        (
            EventType.JOB_STARTED,
            "CREATED",
            "SPEC_VALIDATED",
            JobStartedPayload(Sha256("b" * 64), ("xhs_grid",), JobBudget(2)),
        ),
        (
            EventType.SPEC_COMPILED,
            "SPEC_VALIDATED",
            "SPEC_COMPILED",
            SpecCompiledPayload(Sha256("b" * 64)),
        ),
    ],
)
def test_append_rejects_payload_hash_not_bound_to_genesis(
    tmp_path: Path,
    event_type: EventType,
    from_state: str,
    to_state: str,
    payload: object,
) -> None:
    store = _store(tmp_path)
    if event_type is EventType.SPEC_COMPILED:
        _seed_started(store, tmp_path)
    else:
        _seed_to(store, "CREATED")
    with pytest.raises(DomainError, match="invalid job event"):
        store.append_event(
            JobId("job1"), _event(1, event_type, from_state, to_state, payload)
        )


def test_append_event_and_replay(tmp_path: Path) -> None:
    store = _store(tmp_path)
    _seed_started(store, tmp_path)
    state = store.load(JobId("job1"))
    assert state.job.status.value == "SPEC_VALIDATED"  # type: ignore[attr-defined]
    assert state.last_sequence == 1  # type: ignore[attr-defined]


def test_load_returns_exact_job_state(tmp_path: Path) -> None:
    store = _store(tmp_path)
    _seed_to(store, "CREATED")
    assert type(store.load(JobId("job1"))) is JobState


def test_append_serializes_competing_store_instances(tmp_path: Path) -> None:
    store_a = _store(tmp_path)
    root_fd = os.open(tmp_path, os.O_RDONLY | os.O_DIRECTORY)
    store_b = JobStore.from_root_fd(root_fd)
    os.close(root_fd)
    _seed_to(store_a, "CREATED")
    errors: list[BaseException] = []
    holding, release, completed = ThreadEvent(), ThreadEvent(), ThreadEvent()

    def hold_first_store() -> None:
        with store_a._job_lock(JobId("job1")):
            holding.set()
            assert release.wait(2)

    def append_from_second_store() -> None:
        assert holding.wait(2)
        try:
            store_b.append_event(
                JobId("job1"),
                _event(
                    1,
                    EventType.JOB_STARTED,
                    "CREATED",
                    "SPEC_VALIDATED",
                    _start_payload(),
                ),
            )
        except BaseException as cause:
            errors.append(cause)
        finally:
            completed.set()

    first = Thread(target=hold_first_store)
    second = Thread(target=append_from_second_store)
    first.start()
    second.start()
    assert holding.wait(2)
    assert not completed.wait(0.1)
    release.set()
    first.join(timeout=2)
    second.join(timeout=2)
    assert not first.is_alive() and not second.is_alive()
    assert errors == []
    assert [event.sequence for event in store_a.list_events(JobId("job1"))] == [1]


def test_job_lock_registry_collects_idle_holders_and_contends_live_job(
    tmp_path: Path,
) -> None:
    store = _store(tmp_path)
    for index in range(100):
        with store._job_lock(JobId(f"job{index}")):
            pass
    gc.collect()
    assert len(store._namespace_holder.jobs) == 0

    holding = ThreadEvent()
    release = ThreadEvent()
    contender_entered = ThreadEvent()

    def hold_first() -> None:
        with store._job_lock(JobId("job1")):
            holding.set()
            assert release.wait(timeout=2)

    def acquire_same_job() -> None:
        assert holding.wait(timeout=2)
        with store._job_lock(JobId("job1")):
            contender_entered.set()

    first = Thread(target=hold_first)
    second = Thread(target=acquire_same_job)
    first.start()
    second.start()
    assert not contender_entered.wait(timeout=0.1)
    release.set()
    first.join(timeout=2)
    second.join(timeout=2)
    assert not first.is_alive() and not second.is_alive()
    assert contender_entered.is_set()


def test_forged_snapshot_and_event_are_normalized_to_domain_errors(
    tmp_path: Path,
) -> None:
    store = _store(tmp_path)
    snapshot = JobSnapshot("specstyle.workflow.snapshot.v1", _job(), 0, (), ())
    object.__setattr__(snapshot, "last_sequence", "bad")
    with pytest.raises(DomainError, match="invalid job snapshot"):
        store.save_snapshot(JobId("job1"), snapshot)

    _seed_to(store, "SPEC_COMPILED")
    payload = _attempt_payload()
    object.__setattr__(payload, "attempt_id", "bad")
    event = _event(
        3,
        EventType.ATTEMPT_STARTED,
        "SPEC_COMPILED",
        "GENERATING",
        payload,
    )
    object.__setattr__(event, "timestamp", 1)
    with pytest.raises(DomainError, match="invalid job event"):
        store.append_event(JobId("job1"), event)

    forged_type = _event(
        3,
        EventType.ATTEMPT_STARTED,
        "SPEC_COMPILED",
        "GENERATING",
        _attempt_payload("att2"),
    )
    object.__setattr__(forged_type, "event_type", "ATTEMPT_STARTED")
    with pytest.raises(DomainError, match="invalid job event"):
        store.append_event(JobId("job1"), forged_type)

    forged_job_id = JobId("job1")
    object.__delattr__(forged_job_id, "value")
    with pytest.raises(DomainError, match="invalid job event"):
        store.load(forged_job_id)


def test_append_rejects_coercible_forged_payload_without_writing(
    tmp_path: Path,
) -> None:
    store = _store(tmp_path)
    _seed_to(store, "SPEC_COMPILED")
    path = tmp_path / "jobs" / "job1" / "events.ndjson"
    before = path.read_bytes()
    payload = _attempt_payload("att1")
    object.__setattr__(payload, "attempt_id", "att1")
    with pytest.raises(DomainError, match="invalid job event"):
        store.append_event(
            JobId("job1"),
            _event(
                3,
                EventType.ATTEMPT_STARTED,
                "SPEC_COMPILED",
                "GENERATING",
                payload,
            ),
        )
    assert path.read_bytes() == before


@pytest.mark.parametrize(
    ("target", "value"),
    [
        ("budget", True),
        ("status", "CREATED"),
    ],
)
def test_save_rejects_coercible_forged_snapshot_before_overwrite(
    tmp_path: Path, target: str, value: object
) -> None:
    store = _store(tmp_path)
    initial = JobSnapshot("specstyle.workflow.snapshot.v1", _job(), 0, (), ())
    store.save_snapshot(JobId("job1"), initial)
    path = tmp_path / "jobs" / "job1" / "snapshot.json"
    before = path.read_bytes()
    candidate = JobSnapshot("specstyle.workflow.snapshot.v1", _job(), 0, (), ())
    if target == "budget":
        object.__setattr__(candidate.job.budget, "max_attempts_per_item", value)
    else:
        object.__setattr__(candidate.job, "status", value)
    with pytest.raises(DomainError, match="invalid job snapshot"):
        store.save_snapshot(JobId("job1"), candidate)
    assert path.read_bytes() == before


def test_snapshot_lookup_does_not_depend_on_path_exists(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = _store(tmp_path)

    monkeypatch.setattr(Path, "exists", lambda self: (_ for _ in ()).throw(OSError()))
    assert store.get_snapshot(JobId("job1")) is None


def test_rejects_invalid_transition(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store.save_snapshot(
        JobId("job1"),
        JobSnapshot("specstyle.workflow.snapshot.v1", _job(), 0, (), ()),
    )
    with pytest.raises(DomainError, match="invalid job transition"):
        store.append_event(
            JobId("job1"),
            _event(1, EventType.JOB_STARTED, "CREATED", "VERIFYING", _start_payload()),
        )


def test_rejects_duplicate_attempt(tmp_path: Path) -> None:
    store = _store(tmp_path)
    _seed_to(store, "GENERATING")
    with pytest.raises(DomainError, match="duplicate job attempt"):
        store.append_event(
            JobId("job1"),
            _event(
                2,
                EventType.ATTEMPT_STARTED,
                "VERIFYING",
                "GENERATING",
                _attempt_payload("att1"),
            ),
        )


def test_verifier_finished_nullable_repair_stop_reason_round_trips(
    tmp_path: Path,
) -> None:
    store = _store(tmp_path)
    _seed_to(store, "VERIFYING")
    payload = VerifierFinishedPayload(
        0,
        0,
        ArtifactId("art1"),
        ArtifactStatus.REJECTED,
        DecisionReason.REQUIRED_GATE_FAILED,
        None,
    )
    store.append_event(
        JobId("job1"),
        _event(
            5,
            EventType.VERIFIER_FINISHED,
            "VERIFYING",
            "REPAIR_SELECTING",
            payload,
        ),
    )

    persisted = store.list_events(JobId("job1"))[-1]

    assert persisted.payload == payload
    assert persisted.payload.repair_stop_reason is None  # type: ignore[union-attr]


def _seed_repair_selecting(store: JobStore) -> None:
    _seed_to(store, "VERIFYING")
    store.append_event(
        JobId("job1"),
        _event(
            5,
            EventType.VERIFIER_FINISHED,
            "VERIFYING",
            "REPAIR_SELECTING",
            VerifierFinishedPayload(
                0,
                0,
                ArtifactId("art1"),
                ArtifactStatus.REJECTED,
                DecisionReason.REQUIRED_GATE_FAILED,
                RepairStopReason.MAX_ROUNDS,
            ),
        ),
    )


def test_repair_step_rejects_duplicate_child_attempt(tmp_path: Path) -> None:
    store = _store(tmp_path)
    _seed_repair_selecting(store)

    with pytest.raises(DomainError, match="duplicate job attempt"):
        store.append_event(
            JobId("job1"),
            _event(
                6,
                EventType.REPAIR_STEP,
                "REPAIR_SELECTING",
                "REPAIRING",
                _repair_step_payload("att1"),
            ),
        )


def test_repair_step_registers_child_attempt(tmp_path: Path) -> None:
    store = _store(tmp_path)
    _seed_repair_selecting(store)
    store.append_event(
        JobId("job1"),
        _event(
            6,
            EventType.REPAIR_STEP,
            "REPAIR_SELECTING",
            "REPAIRING",
            _repair_step_payload(),
        ),
    )

    state = store.load(JobId("job1"))

    assert state.attempt_ids == (AttemptId("att1"), AttemptId("att2"))


def test_rejects_duplicate_export(tmp_path: Path) -> None:
    from specstyle.workflow.state_machine import replay_events

    snapshot = JobSnapshot(
        "specstyle.workflow.snapshot.v1", _job("EXPORTING"), 1, (), ("bundle1",)
    )
    with pytest.raises(DomainError, match="invalid job event"):
        replay_events(
            snapshot,
            (
                _event(
                    2,
                    EventType.EXPORT_PUBLISHED,
                    "EXPORTING",
                    "COMPLETED",
                    _export_payload("bundle1"),
                ),
            ),
        )


def test_rejects_terminal_progress(tmp_path: Path) -> None:
    store = _store(tmp_path)
    _seed_to(store, "COMPLETED")
    with pytest.raises(DomainError, match="job is terminal"):
        store.append_event(
            JobId("job1"),
            _event(
                1,
                EventType.EXPORT_PUBLISHED,
                "EXPORTING",
                "COMPLETED",
                _export_payload(),
            ),
        )


def test_partial_json_fail_closed(tmp_path: Path) -> None:
    store = _store(tmp_path)
    directory = tmp_path / "jobs" / "job1"
    directory.mkdir(parents=True)
    (directory / "snapshot.json").write_bytes(
        b'{"schema_version":"specstyle.workflow.snapsho'
    )
    with pytest.raises(InfrastructureError, match="job store corrupted"):
        store.load(JobId("job1"))


def test_corrupted_snapshot_unknown_key_fail_closed(tmp_path: Path) -> None:
    store = _store(tmp_path)
    directory = tmp_path / "jobs" / "job1"
    directory.mkdir(parents=True)
    (directory / "snapshot.json").write_bytes(
        b'{"schema_version":"specstyle.workflow.snapshot.v1","job":{},"last_sequence":0,"attempt_ids":[],"bundle_names":[],"extra":1}'
    )
    with pytest.raises(InfrastructureError, match="job store corrupted"):
        store.load(JobId("job1"))


def test_cancel_race_blocks_subsequent_events(tmp_path: Path) -> None:
    store = _store(tmp_path)
    _seed_to(store, "GENERATING")
    store.append_event(
        JobId("job1"),
        _event(
            1,
            EventType.CANCEL_REQUESTED,
            "GENERATING",
            "CANCELLED",
            CancelRequestedPayload("user abort"),
        ),
    )
    with pytest.raises(DomainError, match="job is terminal"):
        store.append_event(
            JobId("job1"),
            _event(
                2,
                EventType.ATTEMPT_FINISHED,
                "GENERATING",
                "VERIFYING",
                _attempt_finished_payload(),
            ),
        )


def test_fatal_blocks_export(tmp_path: Path) -> None:
    store = _store(tmp_path)
    _seed_to(store, "GENERATING")
    store.append_event(
        JobId("job1"),
        _event(
            1,
            EventType.FATAL,
            "GENERATING",
            "JOB_FAILED",
            FatalPayload("GENERATION_OOM", "oom"),
        ),
    )
    with pytest.raises(DomainError, match="job is terminal"):
        store.append_event(
            JobId("job1"),
            _event(
                2,
                EventType.EXPORT_PUBLISHED,
                "EXPORTING",
                "COMPLETED",
                _export_payload(),
            ),
        )


def test_recovery_replays_events_after_snapshot(tmp_path: Path) -> None:
    store = _store(tmp_path)
    _seed_to(store, "SPEC_COMPILED")
    store.append_event(
        JobId("job1"),
        _event(
            3,
            EventType.ATTEMPT_STARTED,
            "SPEC_COMPILED",
            "GENERATING",
            _attempt_payload("att1"),
        ),
    )
    store.save_snapshot(
        JobId("job1"),
        JobSnapshot(
            "specstyle.workflow.snapshot.v1",
            store.load(JobId("job1")).job,
            3,
            (AttemptId("att1"),),
            (),
        ),
    )
    store.append_event(
        JobId("job1"),
        _event(
            4,
            EventType.ATTEMPT_FINISHED,
            "GENERATING",
            "VERIFYING",
            _attempt_finished_payload("att1"),
        ),
    )
    state = store.load(JobId("job1"))
    assert state.job.status.value == "VERIFYING"  # type: ignore[attr-defined]
    assert state.last_sequence == 4  # type: ignore[attr-defined]
    assert [a.value for a in state.attempt_ids] == ["att1"]  # type: ignore[attr-defined]


def test_rejects_out_of_order_sequence(tmp_path: Path) -> None:
    from specstyle.workflow.job_store import _canonical_json, _event_to_primitive

    store = _store(tmp_path)
    store.save_snapshot(
        JobId("job1"), JobSnapshot("specstyle.workflow.snapshot.v1", _job(), 0, (), ())
    )
    directory = tmp_path / "jobs" / "job1"
    directory.mkdir(parents=True, exist_ok=True)
    e1 = _event(
        1,
        EventType.JOB_STARTED,
        "CREATED",
        "SPEC_VALIDATED",
        _start_payload(),
    )
    e3 = _event(
        3,
        EventType.SPEC_COMPILED,
        "SPEC_VALIDATED",
        "SPEC_COMPILED",
        SpecCompiledPayload(Sha256("a" * 64)),
    )
    with open(directory / "events.ndjson", "wb") as handle:
        handle.write(_canonical_json(_event_to_primitive(e1)) + b"\n")
        handle.write(_canonical_json(_event_to_primitive(e3)) + b"\n")
    with pytest.raises(InfrastructureError, match="job store corrupted"):
        store.load(JobId("job1"))


def test_load_unknown_job_raises(tmp_path: Path) -> None:
    store = _store(tmp_path)
    with pytest.raises(DomainError, match="job not found"):
        store.load(JobId("missing"))


def test_validate_transition_rejects_unknown_mapping(tmp_path: Path) -> None:
    from specstyle.workflow.job_models import JobStatus

    with pytest.raises(DomainError, match="invalid job transition"):
        validate_transition(
            JobStatus.GENERATING, JobStatus.COMPLETED, EventType.ATTEMPT_STARTED
        )


def test_terminal_states_have_no_exits() -> None:
    from specstyle.workflow.job_models import JobStatus

    for status in (JobStatus.COMPLETED, JobStatus.JOB_FAILED, JobStatus.CANCELLED):
        assert TRANSITIONS[status] == frozenset()


def test_full_lifecycle_created_to_completed(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store.save_snapshot(
        JobId("job1"),
        JobSnapshot("specstyle.workflow.snapshot.v1", _job("CREATED"), 0, (), ()),
    )
    store.append_event(
        JobId("job1"),
        _event(1, EventType.JOB_STARTED, "CREATED", "SPEC_VALIDATED", _start_payload()),
    )
    store.append_event(
        JobId("job1"),
        _event(
            2,
            EventType.SPEC_COMPILED,
            "SPEC_VALIDATED",
            "SPEC_COMPILED",
            SpecCompiledPayload(Sha256("a" * 64)),
        ),
    )
    store.append_event(
        JobId("job1"),
        _event(
            3,
            EventType.ATTEMPT_STARTED,
            "SPEC_COMPILED",
            "GENERATING",
            _attempt_payload("att1"),
        ),
    )
    store.append_event(
        JobId("job1"),
        _event(
            4,
            EventType.ATTEMPT_FINISHED,
            "GENERATING",
            "VERIFYING",
            _attempt_finished_payload("att1"),
        ),
    )
    store.append_event(
        JobId("job1"),
        _event(
            5,
            EventType.VERIFIER_FINISHED,
            "VERIFYING",
            "APPROVED",
            _verifier_payload("APPROVED"),
        ),
    )
    store.append_event(
        JobId("job1"),
        _event(
            6,
            EventType.EXPORT_STARTED,
            "APPROVED",
            "EXPORTING",
            ExportStartedPayload("bundle1"),
        ),
    )
    store.append_event(
        JobId("job1"),
        _event(
            7,
            EventType.EXPORT_PUBLISHED,
            "EXPORTING",
            "COMPLETED",
            _export_payload("bundle1"),
        ),
    )
    state = store.load(JobId("job1"))
    assert state.job.status.value == "COMPLETED"  # type: ignore[attr-defined]
    assert state.last_sequence == 7  # type: ignore[attr-defined]
    assert state.job.terminal is True  # type: ignore[attr-defined]
    assert state.bundle_names == ("bundle1",)  # type: ignore[attr-defined]


def test_corrupted_enum_value_fail_closed(tmp_path: Path) -> None:
    from specstyle.workflow.job_store import _canonical_json, _event_to_primitive

    store = _store(tmp_path)
    store.save_snapshot(
        JobId("job1"), JobSnapshot("specstyle.workflow.snapshot.v1", _job(), 0, (), ())
    )
    directory = tmp_path / "jobs" / "job1"
    good = _event(
        1,
        EventType.JOB_STARTED,
        "CREATED",
        "SPEC_VALIDATED",
        _start_payload(),
    )
    bad = _event_to_primitive(good)
    bad["from_state"] = "NOT_A_STATE"
    bad["sequence"] = 2
    with open(directory / "events.ndjson", "wb") as handle:
        handle.write(_canonical_json(_event_to_primitive(good)) + b"\n")
        handle.write(_canonical_json(bad) + b"\n")
    with pytest.raises(InfrastructureError, match="job store corrupted"):
        store.load(JobId("job1"))


def test_corrupted_attempt_ids_type_fail_closed(tmp_path: Path) -> None:
    import json

    store = _store(tmp_path)
    store.save_snapshot(
        JobId("job1"), JobSnapshot("specstyle.workflow.snapshot.v1", _job(), 0, (), ())
    )
    directory = tmp_path / "jobs" / "job1"
    data = json.loads((directory / "snapshot.json").read_text())
    data["attempt_ids"] = "abc"
    (directory / "snapshot.json").write_text(json.dumps(data))
    with pytest.raises(InfrastructureError, match="job store corrupted"):
        store.load(JobId("job1"))


def test_append_event_fsyncs_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """append_event fsyncs the directory after the file for crash idempotency."""
    import specstyle.workflow.job_store as store_mod

    calls: list[int] = []
    real = store_mod.os.fsync

    def spy(fd: int):
        calls.append(fd)
        return real(fd)

    monkeypatch.setattr(store_mod.os, "fsync", spy)
    store = _store(tmp_path)
    store.save_snapshot(
        JobId("job1"),
        JobSnapshot("specstyle.workflow.snapshot.v1", _job("CREATED"), 0, (), ()),
    )
    store.append_event(
        JobId("job1"),
        _event(1, EventType.JOB_STARTED, "CREATED", "SPEC_VALIDATED", _start_payload()),
    )
    assert len(calls) >= 2


def test_append_event_dir_fsync_failure_raises(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import specstyle.workflow.job_store as store_mod

    def boom(fd: int):
        raise OSError("dir fsync denied")

    store = _store(tmp_path)
    store.save_snapshot(
        JobId("job1"),
        JobSnapshot("specstyle.workflow.snapshot.v1", _job("CREATED"), 0, (), ()),
    )
    monkeypatch.setattr(store_mod.os, "fsync", boom)
    with pytest.raises(InfrastructureError, match="job store io failed"):
        store.append_event(
            JobId("job1"),
            _event(
                1, EventType.JOB_STARTED, "CREATED", "SPEC_VALIDATED", _start_payload()
            ),
        )


def test_append_event_rejects_forged_from_state(tmp_path: Path) -> None:
    store = _store(tmp_path)
    _seed_to(store, "SPEC_COMPILED")
    with pytest.raises(DomainError, match="invalid job transition"):
        store.append_event(
            JobId("job1"),
            _event(
                1,
                EventType.ATTEMPT_STARTED,
                "CREATED",
                "GENERATING",
                _attempt_payload("att1"),
            ),
        )


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("job_id", "other"),
        ("status", "SPEC_COMPILED"),
    ],
)
def test_disk_snapshot_path_and_genesis_tampering_fail_closed(
    tmp_path: Path, field: str, value: str
) -> None:
    import json

    store = _store(tmp_path)
    _seed_to(store, "CREATED")
    path = tmp_path / "jobs" / "job1" / "snapshot.json"
    data = json.loads(path.read_text())
    data["job"][field] = value
    path.write_text(json.dumps(data))
    with pytest.raises(InfrastructureError, match="job store corrupted"):
        store.get_snapshot(JobId("job1"))


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("from_state", "CREATED"),
        ("sequence", 3),
        ("timestamp", _TS),
    ],
)
def test_disk_event_semantic_tampering_is_corruption(
    tmp_path: Path, field: str, value: object
) -> None:
    import json

    store = _store(tmp_path)
    _seed_to(store, "SPEC_COMPILED")
    path = tmp_path / "jobs" / "job1" / "events.ndjson"
    records = [json.loads(line) for line in path.read_text().splitlines()]
    records[-1][field] = value
    path.write_text("".join(json.dumps(record) + "\n" for record in records))
    with pytest.raises(InfrastructureError, match="job store corrupted"):
        store.list_events(JobId("job1"))


def test_disk_snapshot_prefix_must_include_derived_attempts_in_order(
    tmp_path: Path,
) -> None:
    import json

    store = _store(tmp_path)
    _seed_to(store, "GENERATING")
    path = tmp_path / "jobs" / "job1" / "snapshot.json"
    data = json.loads(path.read_text())
    data.update(
        {
            "last_sequence": 3,
            "job": {
                **data["job"],
                "status": "GENERATING",
                "updated_at": _TS2,
            },
            "attempt_ids": [],
        }
    )
    path.write_text(json.dumps(data))
    with pytest.raises(InfrastructureError, match="job store corrupted"):
        store.load(JobId("job1"))


def test_save_snapshot_rejects_old_prefix_and_preserves_disk_bytes(
    tmp_path: Path,
) -> None:
    store = _store(tmp_path)
    _seed_to(store, "SPEC_COMPILED")
    current = store.load(JobId("job1"))
    store.save_snapshot(
        JobId("job1"),
        JobSnapshot(
            "specstyle.workflow.snapshot.v1",
            current.job,
            current.last_sequence,
            current.attempt_ids,
            current.bundle_names,
        ),
    )
    path = tmp_path / "jobs" / "job1" / "snapshot.json"
    before = path.read_bytes()
    with pytest.raises(DomainError, match="invalid job snapshot"):
        store.save_snapshot(
            JobId("job1"),
            JobSnapshot("specstyle.workflow.snapshot.v1", _job(), 0, (), ()),
        )
    assert path.read_bytes() == before


def test_save_snapshot_accepts_only_exact_same_sequence_idempotency(
    tmp_path: Path,
) -> None:
    store = _store(tmp_path)
    initial = JobSnapshot("specstyle.workflow.snapshot.v1", _job(), 0, (), ())
    store.save_snapshot(JobId("job1"), initial)
    store.save_snapshot(JobId("job1"), initial)
    with pytest.raises(DomainError, match="invalid job snapshot"):
        store.save_snapshot(
            JobId("job1"),
            JobSnapshot(
                "specstyle.workflow.snapshot.v1", _job("SPEC_VALIDATED"), 0, (), ()
            ),
        )


def test_orphan_events_fail_closed_for_load_list_and_snapshot(tmp_path: Path) -> None:
    from specstyle.workflow.job_store import _canonical_json, _event_to_primitive

    store = _store(tmp_path)
    directory = tmp_path / "jobs" / "job1"
    directory.mkdir(parents=True)
    event = _event(
        1, EventType.JOB_STARTED, "CREATED", "SPEC_VALIDATED", _start_payload()
    )
    (directory / "events.ndjson").write_bytes(
        _canonical_json(_event_to_primitive(event)) + b"\n"
    )
    for operation in (store.load, store.list_events, store.get_snapshot):
        with pytest.raises(InfrastructureError, match="job store corrupted"):
            operation(JobId("job1"))


def test_save_snapshot_directory_fsync_failure_is_io_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import specstyle.workflow.job_store as store_mod

    def boom(fd: int):
        raise OSError("dir fsync denied")

    monkeypatch.setattr(store_mod.os, "fsync", boom)
    with pytest.raises(InfrastructureError, match="job store io failed"):
        _store(tmp_path).save_snapshot(
            JobId("job1"),
            JobSnapshot("specstyle.workflow.snapshot.v1", _job(), 0, (), ()),
        )
