"""WF-001 properties for terminal reachability and idempotent event replay."""

from __future__ import annotations

import random

import pytest

from specstyle.domain.identifiers import JobId, Sha256
from specstyle.errors import DomainError
from specstyle.workflow.job_models import (
    TERMINAL_STATUSES,
    EventType,
    Job,
    JobBudget,
    JobSnapshot,
    JobStatus,
)
from specstyle.workflow.state_machine import (
    TRANSITIONS,
    replay_events,
    validate_transition,
)

_TS = "2026-07-31T10:20:30.123Z"


def _job(status: JobStatus) -> Job:
    return Job(
        JobId("job1"),
        Sha256("a" * 64),
        ("xhs_grid",),
        JobBudget(2),
        status,
        _TS,
        _TS,
    )


def test_random_legal_transitions_reach_terminal() -> None:
    rng = random.Random(20260731)
    for _ in range(200):
        status = JobStatus.CREATED
        for _ in range(50):
            if status in TERMINAL_STATUSES:
                break
            targets = [t for t in TRANSITIONS[status]]
            if not targets:
                break
            status = rng.choice(targets)
        assert status in TERMINAL_STATUSES


def test_replay_idempotent_on_empty_events() -> None:
    snapshot = JobSnapshot(
        "specstyle.workflow.snapshot.v1", _job(JobStatus.GENERATING), 1, (), ()
    )
    first = replay_events(snapshot, ())
    second = replay_events(snapshot, ())
    assert first.job.status == second.job.status
    assert first.last_sequence == second.last_sequence == 1


def test_terminal_state_rejects_all_progress() -> None:
    for terminal in TERMINAL_STATUSES:
        for target in TRANSITIONS[terminal]:
            with pytest.raises(DomainError):
                validate_transition(terminal, target, EventType.JOB_STARTED)
