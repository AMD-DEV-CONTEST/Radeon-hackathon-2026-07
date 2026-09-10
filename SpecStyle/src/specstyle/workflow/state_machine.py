"""WF-001 job state machine, transition validation, and event replay.

Derived from contracts section 5, whose state names govern
CREATED/SPEC_VALIDATED/.../COMPLETED/JOB_FAILED/CANCELLED/RECOVERABLE_ERROR.
APPROVED, MANUAL_REVIEW, and REJECTED are cohort/item decision states awaiting
EXPORTING; the normal terminal job state is COMPLETED.
"""

from __future__ import annotations

from specstyle.errors import DomainError

from specstyle.workflow.job_models import (
    Event,
    EventType,
    Job,
    JobSnapshot,
    JobState,
    JobStatus,
    JobStartedPayload,
    SpecCompiledPayload,
)

TRANSITIONS: dict[JobStatus, frozenset[JobStatus]] = {
    JobStatus.CREATED: frozenset(
        {JobStatus.SPEC_VALIDATED, JobStatus.CANCELLED, JobStatus.JOB_FAILED}
    ),
    JobStatus.SPEC_VALIDATED: frozenset(
        {JobStatus.SPEC_COMPILED, JobStatus.CANCELLED, JobStatus.JOB_FAILED}
    ),
    JobStatus.SPEC_COMPILED: frozenset(
        {JobStatus.GENERATING, JobStatus.CANCELLED, JobStatus.JOB_FAILED}
    ),
    JobStatus.GENERATING: frozenset(
        {
            JobStatus.VERIFYING,
            JobStatus.RECOVERABLE_ERROR,
            JobStatus.CANCELLED,
            JobStatus.JOB_FAILED,
        }
    ),
    JobStatus.VERIFYING: frozenset(
        {
            JobStatus.APPROVED,
            JobStatus.MANUAL_REVIEW,
            JobStatus.REJECTED,
            JobStatus.REPAIR_SELECTING,
            JobStatus.RECOVERABLE_ERROR,
            JobStatus.CANCELLED,
            JobStatus.JOB_FAILED,
        }
    ),
    JobStatus.APPROVED: frozenset(
        {JobStatus.EXPORTING, JobStatus.CANCELLED, JobStatus.JOB_FAILED}
    ),
    JobStatus.MANUAL_REVIEW: frozenset(
        {JobStatus.EXPORTING, JobStatus.CANCELLED, JobStatus.JOB_FAILED}
    ),
    JobStatus.REJECTED: frozenset(
        {JobStatus.EXPORTING, JobStatus.CANCELLED, JobStatus.JOB_FAILED}
    ),
    JobStatus.REPAIR_SELECTING: frozenset(
        {
            JobStatus.REPAIRING,
            JobStatus.REJECTED,
            JobStatus.RECOVERABLE_ERROR,
            JobStatus.CANCELLED,
            JobStatus.JOB_FAILED,
        }
    ),
    JobStatus.REPAIRING: frozenset(
        {
            JobStatus.VERIFYING,
            JobStatus.RECOVERABLE_ERROR,
            JobStatus.CANCELLED,
            JobStatus.JOB_FAILED,
        }
    ),
    JobStatus.EXPORTING: frozenset(
        {
            JobStatus.COMPLETED,
            JobStatus.RECOVERABLE_ERROR,
            JobStatus.CANCELLED,
            JobStatus.JOB_FAILED,
        }
    ),
    JobStatus.RECOVERABLE_ERROR: frozenset(
        {
            JobStatus.GENERATING,
            JobStatus.VERIFYING,
            JobStatus.REPAIR_SELECTING,
            JobStatus.REPAIRING,
            JobStatus.EXPORTING,
            JobStatus.CANCELLED,
            JobStatus.JOB_FAILED,
        }
    ),
    JobStatus.COMPLETED: frozenset(),
    JobStatus.JOB_FAILED: frozenset(),
    JobStatus.CANCELLED: frozenset(),
}

_EVENT_TO_STATE: dict[EventType, frozenset[JobStatus]] = {
    EventType.JOB_STARTED: frozenset({JobStatus.SPEC_VALIDATED}),
    EventType.SPEC_COMPILED: frozenset({JobStatus.SPEC_COMPILED}),
    EventType.ATTEMPT_STARTED: frozenset({JobStatus.GENERATING}),
    EventType.ATTEMPT_FINISHED: frozenset({JobStatus.VERIFYING}),
    EventType.VERIFIER_FINISHED: frozenset(
        {
            JobStatus.APPROVED,
            JobStatus.MANUAL_REVIEW,
            JobStatus.REJECTED,
            JobStatus.REPAIR_SELECTING,
        }
    ),
    EventType.REPAIR_STEP: frozenset({JobStatus.REPAIRING}),
    EventType.EXPORT_STARTED: frozenset({JobStatus.EXPORTING}),
    EventType.EXPORT_PUBLISHED: frozenset({JobStatus.COMPLETED}),
    EventType.RECOVERABLE: frozenset({JobStatus.RECOVERABLE_ERROR}),
    EventType.CANCEL_REQUESTED: frozenset({JobStatus.CANCELLED}),
    EventType.FATAL: frozenset({JobStatus.JOB_FAILED}),
}


def validate_transition(
    from_state: JobStatus,
    to_state: JobStatus,
    event_type: EventType,
    /,
) -> None:
    """Validate membership in TRANSITIONS and the event-type-to-state mapping."""
    if to_state not in TRANSITIONS.get(from_state, frozenset()):
        raise DomainError("invalid job transition") from None
    if to_state not in _EVENT_TO_STATE.get(event_type, frozenset()):
        raise DomainError("invalid job transition") from None


def replay_events(snapshot: JobSnapshot, events: tuple[object, ...], /) -> JobState:
    """Replay and advance events after a snapshot with per-event validation.

    Duplicate sequence, attempt ID, or bundle name, and non-contiguous order,
    raise ``DomainError("invalid job event") from None``.
    """
    try:
        if type(snapshot) is not JobSnapshot or type(events) is not tuple:
            raise DomainError("invalid job event")
        if type(snapshot.job) is not Job:
            raise DomainError("invalid job event")
        status = snapshot.job.status
        last = snapshot.last_sequence
        attempts: list[str] = [a.value for a in snapshot.attempt_ids]
        bundles: list[str] = list(snapshot.bundle_names)
        updated_at = snapshot.job.updated_at
        for event in events:
            if type(event) is not Event:
                raise DomainError("invalid job event")
            if (
                event.job_id != snapshot.job.job_id
                or event.sequence != last + 1
                or event.from_state is not status
                or event.timestamp < updated_at
            ):
                raise DomainError("invalid job event")
            _check_bound_payload(snapshot.job, event)
            validate_transition(status, event.to_state, event.event_type)
            _check_idempotent(event, attempts, bundles)
            status = event.to_state
            last = event.sequence
            updated_at = event.timestamp
        new_job = Job(
            snapshot.job.job_id,
            snapshot.job.compiled_spec_hash,
            snapshot.job.cohort_profiles,
            snapshot.job.budget,
            status,
            snapshot.job.created_at,
            updated_at,
        )
        from specstyle.domain.identifiers import AttemptId

        return JobState(
            new_job,
            last,
            tuple(AttemptId(a) for a in attempts),
            tuple(bundles),
        )
    except (DomainError, AttributeError, TypeError, ValueError):
        raise DomainError("invalid job event") from None


def _check_idempotent(event: object, attempts: list[str], bundles: list[str]) -> None:
    if event.event_type is EventType.ATTEMPT_STARTED:  # type: ignore[attr-defined]
        aid = event.payload.attempt_id.value  # type: ignore[attr-defined]
        if aid in attempts:
            raise DomainError("invalid job event") from None
        attempts.append(aid)
    elif event.event_type is EventType.REPAIR_STEP:  # type: ignore[attr-defined]
        aid = event.payload.child_attempt_id.value  # type: ignore[attr-defined]
        if aid in attempts:
            raise DomainError("invalid job event") from None
        attempts.append(aid)
    elif event.event_type is EventType.EXPORT_PUBLISHED:  # type: ignore[attr-defined]
        bn = event.payload.bundle_name  # type: ignore[attr-defined]
        if bn in bundles:
            raise DomainError("invalid job event") from None
        bundles.append(bn)


def _check_bound_payload(job: Job, event: Event) -> None:
    """Verify that event logs cannot replace immutable genesis material."""
    if event.event_type is EventType.JOB_STARTED:
        payload = event.payload
        if (
            type(payload) is not JobStartedPayload
            or payload.compiled_spec_hash != job.compiled_spec_hash
            or payload.cohort_profiles != job.cohort_profiles
            or payload.budget != job.budget
        ):
            raise DomainError("invalid job event") from None
    elif event.event_type is EventType.SPEC_COMPILED:
        payload = event.payload
        if (
            type(payload) is not SpecCompiledPayload
            or payload.compiled_spec_hash != job.compiled_spec_hash
        ):
            raise DomainError("invalid job event") from None
