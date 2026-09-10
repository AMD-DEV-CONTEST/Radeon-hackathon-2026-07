"""FD-rooted JobStore contract tests.

Each test protects a boundary that would be broken if JobStore returned to
pathname based I/O or allowed a closed descriptor to be reused.
"""

from __future__ import annotations

import os
import gc
import json
from pathlib import Path
from threading import Event as ThreadEvent
from threading import Thread

import pytest

from specstyle.domain.identifiers import JobId, Sha256
from specstyle.errors import DomainError, InfrastructureError
from specstyle.workflow.job_models import (
    Event,
    EventType,
    Job,
    JobBudget,
    JobSnapshot,
    JobStartedPayload,
    JobStatus,
    SpecCompiledPayload,
)
from specstyle.workflow.job_store import JobStore
from specstyle.workflow import _job_store_transaction as transaction
from specstyle.workflow import _job_store_codec as codec


def _snapshot(job_name: str = "fdjob") -> JobSnapshot:
    job_id = JobId(job_name)
    job = Job(
        job_id,
        Sha256("a" * 64),
        ("xhs_grid",),
        JobBudget(1),
        JobStatus.CREATED,
        "2026-07-31T10:20:30.123Z",
        "2026-07-31T10:20:30.123Z",
    )
    return JobSnapshot("specstyle.workflow.snapshot.v1", job, 0, (), ())


def _event(event_type: EventType, before: JobStatus, after: JobStatus) -> Event:
    payload = (
        JobStartedPayload(Sha256("a" * 64), ("xhs_grid",), JobBudget(1))
        if event_type is EventType.JOB_STARTED
        else SpecCompiledPayload(Sha256("a" * 64))
    )
    return Event(
        1,
        JobId("fdjob"),
        event_type,
        before,
        after,
        "2026-08-02T00:00:00.000Z",
        payload,
    )


def test_from_root_fd_survives_caller_close_and_descriptor_reuse(
    tmp_path: Path,
) -> None:
    """Closing/reusing the caller's fd must not redirect state writes."""
    root = tmp_path / "state"
    root.mkdir(mode=0o700)
    caller_fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY)
    store = JobStore.from_root_fd(caller_fd)
    os.close(caller_fd)
    reused_fd = os.open(tmp_path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        store.save_snapshot(JobId("fdjob"), _snapshot())
    finally:
        os.close(reused_fd)
        store.close()

    assert (root / "jobs" / "fdjob" / "snapshot.json").is_file()
    assert not (tmp_path / "jobs").exists()


def test_open_store_remains_bound_to_original_inode_after_path_replacement(
    tmp_path: Path,
) -> None:
    """A rename/replacement after construction must not retarget the store."""
    root = tmp_path / "state"
    replacement = tmp_path / "replacement"
    moved = tmp_path / "moved"
    root.mkdir(mode=0o700)
    replacement.mkdir(mode=0o700)
    store = JobStore(root)
    root.rename(moved)
    replacement.rename(root)
    try:
        store.save_snapshot(JobId("fdjob"), _snapshot())
    finally:
        store.close()

    assert (moved / "jobs" / "fdjob" / "snapshot.json").is_file()
    assert not (root / "jobs").exists()


@pytest.mark.parametrize("binding", ["jobs", "job"])
def test_read_job_rejects_named_directory_rebind_after_transaction_read(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, binding: str
) -> None:
    state_root = tmp_path / "state"
    replacement_root = tmp_path / "replacement"
    state_root.mkdir(mode=0o700)
    replacement_root.mkdir(mode=0o700)
    store = JobStore(state_root)
    replacement = JobStore(replacement_root)
    job_id = JobId("fdjob")
    store.save_snapshot(job_id, _snapshot())
    replacement.save_snapshot(job_id, _snapshot())
    replacement.close()
    original_read = transaction.read
    rebound = False

    def read_then_rebind(*args, **kwargs):
        nonlocal rebound
        result = original_read(*args, **kwargs)
        if not rebound:
            rebound = True
            if binding == "jobs":
                (state_root / "jobs").rename(tmp_path / "displaced-jobs")
                (replacement_root / "jobs").rename(state_root / "jobs")
            else:
                job_path = state_root / "jobs" / job_id.value
                job_path.rename(tmp_path / "displaced-job")
                (replacement_root / "jobs" / job_id.value).rename(job_path)
        return result

    monkeypatch.setattr(transaction, "read", read_then_rebind)
    try:
        with pytest.raises(InfrastructureError, match="^job store corrupted$"):
            store.get_snapshot(job_id)
    finally:
        store.close()
    assert rebound


@pytest.mark.parametrize("operation", ["save_snapshot", "append_event"])
@pytest.mark.parametrize("binding", ["jobs", "job"])
def test_write_rejects_named_directory_rebind_after_transaction_commit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    operation: str,
    binding: str,
) -> None:
    state_root = tmp_path / "state"
    replacement_root = tmp_path / "replacement"
    state_root.mkdir(mode=0o700)
    replacement_root.mkdir(mode=0o700)
    store = JobStore(state_root)
    replacement = JobStore(replacement_root)
    job_id = JobId("fdjob")
    store.save_snapshot(job_id, _snapshot())
    replacement.save_snapshot(job_id, _snapshot())
    replacement.close()
    original_commit = transaction.commit
    rebound = False

    def commit_then_rebind(*args, **kwargs):
        nonlocal rebound
        result = original_commit(*args, **kwargs)
        rebound = True
        if binding == "jobs":
            (state_root / "jobs").rename(tmp_path / "displaced-jobs")
            (replacement_root / "jobs").rename(state_root / "jobs")
        else:
            job_path = state_root / "jobs" / job_id.value
            job_path.rename(tmp_path / "displaced-job")
            (replacement_root / "jobs" / job_id.value).rename(job_path)
        return result

    monkeypatch.setattr(transaction, "commit", commit_then_rebind)
    try:
        with pytest.raises(InfrastructureError, match="^job store corrupted$"):
            if operation == "save_snapshot":
                store.save_snapshot(job_id, _snapshot())
            else:
                store.append_event(
                    job_id,
                    _event(
                        EventType.JOB_STARTED,
                        JobStatus.CREATED,
                        JobStatus.SPEC_VALIDATED,
                    ),
                )
    finally:
        store.close()
    assert rebound


@pytest.mark.parametrize("bad_fd", [True, False, 1.0, "1"])
def test_from_root_fd_requires_exact_integer(bad_fd: object) -> None:
    with pytest.raises(DomainError, match="^invalid job store root$"):
        JobStore.from_root_fd(bad_fd)  # type: ignore[arg-type]


def test_operations_after_close_are_rejected(tmp_path: Path) -> None:
    store = JobStore(tmp_path)
    store.close()

    with pytest.raises(InfrastructureError, match="job store closed"):
        store.list_job_ids()


def test_close_waits_for_active_operation_and_is_idempotent(tmp_path: Path) -> None:
    """A close must not invalidate an already-borrowed root descriptor."""
    store = JobStore(tmp_path)
    entered, release, finished = ThreadEvent(), ThreadEvent(), ThreadEvent()

    def operation() -> None:
        with store._operation():
            entered.set()
            assert release.wait(2)

    worker = Thread(target=operation)
    worker.start()
    assert entered.wait(2)
    closer = Thread(target=lambda: (store.close(), finished.set()))
    closer.start()
    assert not finished.wait(0.1)
    release.set()
    worker.join(2)
    closer.join(2)
    store.close()

    assert finished.is_set()


def test_missing_reads_do_not_accumulate_idle_job_holders(tmp_path: Path) -> None:
    store = JobStore(tmp_path)
    namespace = store._namespace_holder
    try:
        for index in range(128):
            assert store.get_snapshot(JobId(f"missing-{index}")) is None
        gc.collect()
        assert namespace is not None
        assert len(namespace.jobs) == 0
    finally:
        store.close()


def test_live_job_operation_keeps_shared_holder_until_unlock(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    first = JobStore(tmp_path)
    second = JobStore(tmp_path)
    job_id = JobId("fdjob")
    entered, release, second_done = ThreadEvent(), ThreadEvent(), ThreadEvent()
    original_read = JobStore._read_job

    def blocked_read(store, root_fd, current_job_id):
        if store is first and current_job_id == job_id:
            entered.set()
            assert release.wait(2)
        return original_read(store, root_fd, current_job_id)

    monkeypatch.setattr(JobStore, "_read_job", blocked_read)
    first_thread = Thread(target=lambda: first.get_snapshot(job_id))
    second_thread = Thread(
        target=lambda: (second.get_snapshot(job_id), second_done.set())
    )
    try:
        first_thread.start()
        assert entered.wait(2)
        second_thread.start()
        assert not second_done.wait(0.1)
        release.set()
        first_thread.join(2)
        second_thread.join(2)
        assert second_done.is_set()
    finally:
        release.set()
        first.close()
        second.close()


def test_close_marks_descriptor_dead_after_kernel_close_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A close error after kernel success must never leave a reusable fd owned."""
    import specstyle.workflow.job_store as store_mod

    store = JobStore(tmp_path)
    original_close = store_mod.os.close
    target = store._root_fd
    calls: list[int] = []

    def close_then_fail(fd: int) -> None:
        calls.append(fd)
        original_close(fd)
        if fd == target:
            raise OSError("kernel close succeeded before reporting failure")

    monkeypatch.setattr(store_mod.os, "close", close_then_fail)
    with pytest.raises(InfrastructureError, match="^job store io failed$"):
        store.close()
    reused = os.open(tmp_path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        assert store._root_fd == -1
        store.close()
        assert calls.count(target) == 1
    finally:
        original_close(reused)


def test_genesis_publishes_canonical_clean_marker_and_only_fixed_slots(
    tmp_path: Path,
) -> None:
    store = JobStore(tmp_path)
    try:
        store.save_snapshot(JobId("fdjob"), _snapshot())
    finally:
        store.close()

    job_dir = tmp_path / "jobs" / "fdjob"
    marker = job_dir / ".specstyle-state.marker"
    data = marker.read_bytes()
    assert (
        data
        == json.dumps(
            json.loads(data), sort_keys=True, separators=(",", ":"), allow_nan=False
        ).encode()
    )
    assert json.loads(data) == {
        "version": 1,
        "phase": "CLEAN",
        "generation": 0,
        "snapshot_sha256": __import__("hashlib")
        .sha256((job_dir / "snapshot.json").read_bytes())
        .hexdigest(),
        "events_sha256": None,
    }
    assert set(path.name for path in job_dir.iterdir()) <= {
        "snapshot.json",
        "events.ndjson",
        ".specstyle-state.marker",
        ".specstyle-state.marker.swap",
        ".specstyle-snapshot.swap",
        ".specstyle-events.swap",
    }


def test_clean_marker_hash_mismatch_fails_closed(tmp_path: Path) -> None:
    store = JobStore(tmp_path)
    job_id = JobId("fdjob")
    try:
        store.save_snapshot(job_id, _snapshot())
        snapshot = tmp_path / "jobs" / "fdjob" / "snapshot.json"
        snapshot.write_bytes(json.dumps(json.loads(snapshot.read_bytes())).encode())
        with pytest.raises(InfrastructureError, match="^job store corrupted$"):
            store.load(job_id)
    finally:
        store.close()


def test_world_writable_state_file_fails_closed(tmp_path: Path) -> None:
    store = JobStore(tmp_path)
    job_id = JobId("fdjob")
    try:
        store.save_snapshot(job_id, _snapshot())
        snapshot = tmp_path / "jobs" / "fdjob" / "snapshot.json"
        snapshot.chmod(0o622)
        with pytest.raises(InfrastructureError, match="^job store corrupted$"):
            store.load(job_id)
    finally:
        store.close()


def test_pending_marker_is_facade_corruption(tmp_path: Path) -> None:
    store = JobStore(tmp_path)
    job_id = JobId("fdjob")
    store.save_snapshot(job_id, _snapshot())
    job_dir = tmp_path / "jobs" / "fdjob"
    snapshot = (job_dir / transaction.SNAPSHOT).read_bytes()
    (job_dir / transaction.MARKER).write_bytes(
        transaction.marker_bytes("PENDING", 1, snapshot, None)
    )
    try:
        with pytest.raises(InfrastructureError, match="^job store corrupted$"):
            store.load(job_id)
    finally:
        store.close()


def test_generation_exhaustion_is_zero_mutation_through_facade(tmp_path: Path) -> None:
    store = JobStore(tmp_path)
    job_id = JobId("fdjob")
    snapshot = _snapshot()
    store.save_snapshot(job_id, snapshot)
    job_dir = tmp_path / "jobs" / "fdjob"
    snapshot_data = (job_dir / transaction.SNAPSHOT).read_bytes()
    (job_dir / transaction.MARKER).write_bytes(
        transaction.marker_bytes(
            "CLEAN", transaction.MAX_GENERATION, snapshot_data, None
        )
    )
    before = {path.name: path.read_bytes() for path in job_dir.iterdir()}
    try:
        with pytest.raises(
            InfrastructureError, match="^job store generation exhausted$"
        ):
            store.save_snapshot(job_id, snapshot)
    finally:
        store.close()
    assert {path.name: path.read_bytes() for path in job_dir.iterdir()} == before


def test_legacy_read_is_nonmutating_and_next_write_migrates(tmp_path: Path) -> None:
    job_id = JobId("fdjob")
    snapshot = _snapshot()
    job_dir = tmp_path / "jobs" / job_id.value
    job_dir.mkdir(parents=True)
    (job_dir / transaction.SNAPSHOT).write_bytes(codec.encode_snapshot(snapshot))
    store = JobStore(tmp_path)
    try:
        assert store.load(job_id).last_sequence == 0
        assert not (job_dir / transaction.MARKER).exists()
        store.save_snapshot(job_id, snapshot)
    finally:
        store.close()
    marker = json.loads((job_dir / transaction.MARKER).read_bytes())
    assert marker["phase"] == "CLEAN" and marker["generation"] == 1


def test_symlinked_state_leaf_fails_closed(tmp_path: Path) -> None:
    store = JobStore(tmp_path)
    store.save_snapshot(JobId("fdjob"), _snapshot())
    leaf = tmp_path / "jobs" / "fdjob" / "snapshot.json"
    outside = tmp_path / "outside"
    outside.write_bytes(leaf.read_bytes())
    leaf.unlink()
    leaf.symlink_to(outside)
    try:
        with pytest.raises(InfrastructureError, match="job store corrupted"):
            store.load(JobId("fdjob"))
    finally:
        store.close()


def test_unknown_job_directory_entry_fails_closed(tmp_path: Path) -> None:
    store = JobStore(tmp_path)
    store.save_snapshot(JobId("fdjob"), _snapshot())
    (tmp_path / "jobs" / "fdjob" / "unknown").mkdir()
    try:
        with pytest.raises(InfrastructureError, match="^job store corrupted$"):
            store.load(JobId("fdjob"))
    finally:
        store.close()


def test_list_skips_structurally_safe_slot_only_job_directory(tmp_path: Path) -> None:
    job_dir = tmp_path / "jobs" / "fdjob"
    job_dir.mkdir(parents=True)
    (job_dir / transaction.SNAPSHOT_SWAP).write_bytes(b"partial")
    store = JobStore(tmp_path)
    try:
        assert store.list_job_ids() == ()
    finally:
        store.close()


def test_missing_job_does_not_leak_jobs_fd(tmp_path: Path) -> None:
    (tmp_path / "jobs").mkdir()
    store = JobStore(tmp_path)
    before = len(os.listdir("/dev/fd"))
    for _ in range(50):
        assert store.get_snapshot(JobId("missing")) is None
    after = len(os.listdir("/dev/fd"))
    store.close()

    assert after == before


def test_save_snapshot_rejects_final_leaf_swap_before_replace(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A same-name replacement after the read must never be overwritten."""
    import specstyle.workflow.job_store as store_mod

    store = JobStore(tmp_path)
    job_id = JobId("fdjob")
    store.save_snapshot(job_id, _snapshot())
    final = tmp_path / "jobs" / job_id.value / "snapshot.json"
    attacker = tmp_path / "attacker-snapshot"
    attacker.write_bytes(final.read_bytes())
    original_replace = store_mod.os.replace
    original_stat = store_mod.os.stat
    swapped = False
    snapshot_stats = 0

    def swap_before_final_check(name, *args, **kwargs):
        nonlocal swapped, snapshot_stats
        if name == "snapshot.json":
            snapshot_stats += 1
        if not swapped and snapshot_stats == 3:
            swapped = True
            original_replace(attacker, final)
        return original_stat(name, *args, **kwargs)

    monkeypatch.setattr(store_mod.os, "stat", swap_before_final_check)
    try:
        with pytest.raises(InfrastructureError, match="^job store corrupted$"):
            store.save_snapshot(job_id, _snapshot())
    finally:
        store.close()

    assert swapped
    assert final.exists()
    assert not attacker.exists()


def test_append_event_rejects_events_leaf_swap_before_replace(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An attacker may not replace the previously-read event journal."""
    import specstyle.workflow.job_store as store_mod

    store = JobStore(tmp_path)
    job_id = JobId("fdjob")
    store.save_snapshot(job_id, _snapshot())
    store.append_event(
        job_id,
        _event(EventType.JOB_STARTED, JobStatus.CREATED, JobStatus.SPEC_VALIDATED),
    )
    final = tmp_path / "jobs" / job_id.value / "events.ndjson"
    attacker = tmp_path / "attacker-events"
    attacker.write_bytes(final.read_bytes())
    original_replace = store_mod.os.replace
    original_stat = store_mod.os.stat
    events_stats = 0
    swapped = False

    def swap_before_final_check(name, *args, **kwargs):
        nonlocal events_stats, swapped
        if name == "events.ndjson":
            events_stats += 1
        if not swapped and events_stats == 3:
            swapped = True
            original_replace(attacker, final)
        return original_stat(name, *args, **kwargs)

    monkeypatch.setattr(store_mod.os, "stat", swap_before_final_check)
    try:
        with pytest.raises(InfrastructureError, match="^job store corrupted$"):
            store.append_event(
                job_id,
                _event(
                    EventType.SPEC_COMPILED,
                    JobStatus.SPEC_VALIDATED,
                    JobStatus.SPEC_COMPILED,
                ),
            )
    finally:
        store.close()

    assert swapped
    assert final.exists()
    assert not attacker.exists()


def test_unknown_temp_namespace_entry_prevents_orphan_deletion(tmp_path: Path) -> None:
    """Failing closed must not mutate a directory containing an unknown entry."""
    store = JobStore(tmp_path)
    job_id = JobId("fdjob")
    store.save_snapshot(job_id, _snapshot())
    job_dir = tmp_path / "jobs" / job_id.value
    orphan = job_dir / ".snapshot.json.0123456789abcdef0123456789abcdef.tmp"
    orphan.write_bytes(b"")
    orphan.chmod(0o600)
    (job_dir / "unknown").write_bytes(b"x")
    try:
        with pytest.raises(InfrastructureError, match="^job store corrupted$"):
            store.get_snapshot(job_id)
    finally:
        store.close()

    assert orphan.exists()
