"""WF-001 crash recovery, idempotency, and cancel/fatal audit contract tests."""

from __future__ import annotations

from pathlib import Path


import pytest

from specstyle.domain.identifiers import AttemptId, JobId, Sha256
from specstyle.errors import InfrastructureError
from specstyle.workflow.job_models import (
    AttemptStartedPayload,
    CancelRequestedPayload,
    Event,
    EventType,
    FatalPayload,
    Job,
    JobBudget,
    JobSnapshot,
    JobStartedPayload,
    SpecCompiledPayload,
)
from specstyle.workflow.job_store import JobStore

_TS = "2026-07-31T10:20:30.123Z"
_TS2 = "2026-07-31T10:20:31.123Z"


def _job(status: str = "SPEC_COMPILED") -> Job:
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


def _seed_to(store: JobStore, status: str) -> None:
    from specstyle.workflow.job_models import JobStatus

    store.save_snapshot(
        JobId("job1"),
        JobSnapshot("specstyle.workflow.snapshot.v1", _job("CREATED"), 0, (), ()),
    )
    if status == "CREATED":
        return
    steps = (
        (
            EventType.JOB_STARTED,
            JobStatus.CREATED,
            JobStatus.SPEC_VALIDATED,
            JobStartedPayload(Sha256("a" * 64), ("xhs_grid",), JobBudget(2)),
        ),
        (
            EventType.SPEC_COMPILED,
            JobStatus.SPEC_VALIDATED,
            JobStatus.SPEC_COMPILED,
            SpecCompiledPayload(Sha256("a" * 64)),
        ),
        (
            EventType.ATTEMPT_STARTED,
            JobStatus.SPEC_COMPILED,
            JobStatus.GENERATING,
            AttemptStartedPayload(0, 0, AttemptId("att1"), None),
        ),
    )
    for sequence, (event_type, from_state, to_state, payload) in enumerate(steps, 1):
        store.append_event(
            JobId("job1"),
            Event(
                sequence, JobId("job1"), event_type, from_state, to_state, _TS2, payload
            ),
        )
        if to_state.value == status:
            return
    raise AssertionError(f"unsupported status: {status}")


def test_recovery_rejects_snapshot_sequence_beyond_complete_event_log(
    tmp_path: Path,
) -> None:
    store = JobStore(tmp_path)
    _seed_to(store, "CREATED")
    # Simulate a crash by forging an incorrect snapshot last_sequence.
    directory = tmp_path / "jobs" / "job1"
    import json

    snapshot_data = json.loads((directory / "snapshot.json").read_text())
    snapshot_data["last_sequence"] = 99
    (directory / "snapshot.json").write_text(json.dumps(snapshot_data))
    with pytest.raises(InfrastructureError, match="job store corrupted"):
        store.load(JobId("job1"))


def test_cancelled_job_preserves_audit_no_bundle(tmp_path: Path) -> None:
    store = JobStore(tmp_path)
    _seed_to(store, "GENERATING")
    store.append_event(
        JobId("job1"),
        Event(
            1,
            JobId("job1"),
            EventType.CANCEL_REQUESTED,
            _job("GENERATING").status,
            _job("CANCELLED").status,
            _TS2,
            CancelRequestedPayload("abort"),
        ),
    )
    state = store.load(JobId("job1"))
    assert state.job.status.value == "CANCELLED"  # type: ignore[attr-defined]
    assert state.bundle_names == ()  # type: ignore[attr-defined]


def test_fatal_keeps_prior_attempt_audit(tmp_path: Path) -> None:
    store = JobStore(tmp_path)
    _seed_to(store, "GENERATING")
    store.append_event(
        JobId("job1"),
        Event(
            4,
            JobId("job1"),
            EventType.FATAL,
            _job("GENERATING").status,
            _job("JOB_FAILED").status,
            _TS2,
            FatalPayload("EXPORT_HASH_MISMATCH", "mismatch"),
        ),
    )
    state = store.load(JobId("job1"))
    assert state.job.status.value == "JOB_FAILED"  # type: ignore[attr-defined]
    assert state.attempt_ids == (AttemptId("att1"),)  # type: ignore[attr-defined]
