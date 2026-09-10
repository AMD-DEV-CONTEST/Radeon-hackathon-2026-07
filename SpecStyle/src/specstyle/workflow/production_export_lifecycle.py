"""Crash-safe publication lifecycle for production export commands."""

from __future__ import annotations

from enum import StrEnum
import os
import threading
from typing import Any

from specstyle.domain.identifiers import JobId
from specstyle.errors import DomainError, InfrastructureError
from specstyle.exporting import qa_report as _qa
from specstyle.exporting.bundle import (
    _commit_staged_bundle,
    _dup_root_fd,
    _inspect_final_bundle,
    _stage_bundle,
    _trusted_root_identity,
)
from specstyle.exporting.manifest import _prepare_export
from specstyle.repair.history import RepairHistory
from specstyle.workflow.job_models import (
    Event,
    EventType,
    ExportPublishedPayload,
    ExportStartedPayload,
    JobState,
    JobStatus,
)
from specstyle.workflow.job_store import JobStore
from specstyle.workflow.production_export import (
    ProductionExportCommand,
    ProductionExportResult,
    ProductionRecoveryDisposition,
    ProductionRecoveryEntry,
    _rebuild_production_export_command,
)


class _ExportPhase(StrEnum):
    UNKNOWN = "UNKNOWN"
    STAGING = "STAGING"
    PUBLISHED = "PUBLISHED"


class _ExportLockHolder:
    __slots__ = ("job_holder", "lock", "operation_lock", "phase", "__weakref__")

    def __init__(self, job_holder) -> None:
        self.job_holder = job_holder
        self.lock = job_holder.lock
        self.operation_lock = threading.Lock()
        self.phase = _ExportPhase.UNKNOWN


def _export_lock_holder(store: JobStore, job_id: JobId, /) -> _ExportLockHolder:
    namespace = store._namespace_holder
    job_holder = store._job_lock_holder(job_id)
    with namespace.exports_lock:
        holder = namespace.exports.get(job_id.value)
        if holder is None:
            holder = _ExportLockHolder(job_holder)
            namespace.exports[job_id.value] = holder
    assert type(holder) is _ExportLockHolder
    return holder


def _validate_export_root(target_root_fd: object, /) -> int:
    duplicated = _dup_root_fd(target_root_fd)
    try:
        _trusted_root_identity(os.fstat(duplicated))
    finally:
        os.close(duplicated)
    return target_root_fd


def _prepare_publish_arguments(
    command: object, target_root_fd: object, /
) -> tuple[ProductionExportCommand, int]:
    rebuilt = _rebuild_production_export_command(command)
    return rebuilt, _validate_export_root(target_root_fd)


def _history_attempts(history: RepairHistory, /) -> tuple[tuple[Any, ...], ...]:
    initial = history.initial_attempt
    return (
        (initial.request, initial.artifact, initial.report),
        *(
            (attempt.request, attempt.artifact, attempt.report)
            for attempt in history.repair_attempts
        ),
    )


def _command_attempts(command: ProductionExportCommand, /) -> tuple[Any, ...]:
    return tuple(
        attempt
        for cohort in command.export_request.cohorts
        for item in cohort.items
        for attempt in _history_attempts(item.history)
    )


def _same_material(left: object, right: object, /) -> bool:
    return _qa.canonical_material(left) == _qa.canonical_material(right)


def _validate_export_state(
    command: ProductionExportCommand, state: JobState, /
) -> tuple[Any, ...]:
    attempts = _command_attempts(command)
    statuses = {
        item.terminal.artifact_decision.artifact_status.value
        for cohort in command.export_request.cohorts
        for item in cohort.items
    }
    first_request = attempts[0][0]
    expected_attempt_ids = tuple(attempt[0].attempt_id for attempt in attempts)
    expected_profiles = tuple(
        cohort.output_profile for cohort in command.export_request.cohorts
    )
    if (
        type(state) is not JobState
        or state.job.job_id != command.job_id
        or state.job.status
        not in {JobStatus.APPROVED, JobStatus.MANUAL_REVIEW, JobStatus.REJECTED}
        or statuses != {state.job.status.value}
        or state.job.compiled_spec_hash
        != first_request.compiled_spec.compiled_spec_hash
        or state.job.cohort_profiles != expected_profiles
        or state.attempt_ids != expected_attempt_ids
        or state.bundle_names
    ):
        raise DomainError("invalid production export") from None
    return attempts


def _require_persisted_attempts(runtime: Any, job_id: JobId, attempts) -> None:
    artifact_repository = runtime._artifact_store.for_job(job_id)
    try:
        for request, artifact, report in attempts:
            stored_artifact = artifact_repository(artifact.ref)
            report_repository = runtime._report_store.for_attempt(
                job_id, request.attempt_id
            )
            try:
                stored_report = report_repository()
            finally:
                report_repository.close()
            if not _same_material(stored_artifact, artifact) or not _same_material(
                stored_report, report
            ):
                raise InfrastructureError(
                    "production export persistence mismatch"
                ) from None
    finally:
        artifact_repository.close()


def _export_published_payload(bundle: Any, /) -> ExportPublishedPayload:
    return ExportPublishedPayload(
        bundle.bundle_name,
        bundle.manifest_sha256,
        bundle.payload_sha256,
        bundle.bundle_sha256,
    )


def _close_staged_quietly(staged: Any, /) -> None:
    try:
        staged.close()
    except Exception:
        pass


def _begin_publish(runtime: Any, command: ProductionExportCommand, holder) -> None:
    with holder.lock:
        state = runtime._job_store.load(command.job_id)
        attempts = _validate_export_state(command, state)
        _require_persisted_attempts(runtime, command.job_id, attempts)
        runtime._append_export_event(
            command.job_id,
            EventType.EXPORT_STARTED,
            state.job.status,
            JobStatus.EXPORTING,
            ExportStartedPayload(command.bundle_name),
        )
        holder.phase = _ExportPhase.STAGING


def _commit_publish(runtime: Any, command, staged, holder) -> ProductionExportResult:
    try:
        with holder.lock:
            state = runtime._job_store.load(command.job_id)
            if state.job.status is JobStatus.CANCELLED:
                raise DomainError("production job cancelled") from None
            if state.job.status is not JobStatus.EXPORTING:
                raise InfrastructureError("production export state changed") from None
            holder.phase = _ExportPhase.UNKNOWN
            bundle = _commit_staged_bundle(staged, accept_exact_existing=False)
            holder.phase = _ExportPhase.PUBLISHED
            runtime._append_export_event(
                command.job_id,
                EventType.EXPORT_PUBLISHED,
                JobStatus.EXPORTING,
                JobStatus.COMPLETED,
                _export_published_payload(bundle),
            )
            return ProductionExportResult(
                bundle, runtime._job_store.load(command.job_id)
            )
    except BaseException:
        _close_staged_quietly(staged)
        raise


def _publish_export(
    runtime: Any, command: ProductionExportCommand, target_root_fd: int, /
) -> ProductionExportResult:
    holder = _export_lock_holder(runtime._job_store, command.job_id)
    with holder.operation_lock:
        _begin_publish(runtime, command, holder)
        staged = _stage_bundle(
            command.export_request, target_root_fd, command.bundle_name
        )
        return _commit_publish(runtime, command, staged, holder)


def _rebuild_recovery_commands(value: object, /) -> tuple[ProductionExportCommand, ...]:
    if type(value) is not tuple:
        raise DomainError("invalid production export recovery") from None
    try:
        rebuilt = tuple(_rebuild_production_export_command(item) for item in value)
    except Exception:
        raise DomainError("invalid production export recovery") from None
    identifiers = tuple(item.job_id.value for item in rebuilt)
    if len(identifiers) != len(set(identifiers)):
        raise DomainError("invalid production export recovery") from None
    return rebuilt


def _latest_event(events: tuple[Event, ...], event_type: EventType, /) -> Event | None:
    return next(
        (event for event in reversed(events) if event.event_type is event_type),
        None,
    )


def _validate_recovery_bindings(command, state, events) -> tuple[Any, ...]:
    attempts = _command_attempts(command)
    profiles = tuple(cohort.output_profile for cohort in command.export_request.cohorts)
    statuses = {
        item.terminal.artifact_decision.artifact_status.value
        for cohort in command.export_request.cohorts
        for item in cohort.items
    }
    started = _latest_event(events, EventType.EXPORT_STARTED)
    first_request = attempts[0][0]
    invalid = (
        state.job.job_id != command.job_id
        or state.job.compiled_spec_hash
        != first_request.compiled_spec.compiled_spec_hash
        or state.job.cohort_profiles != profiles
        or state.attempt_ids != tuple(item[0].attempt_id for item in attempts)
        or len(statuses) != 1
        or started is None
        or started.from_state.value not in statuses
        or started.to_state is not JobStatus.EXPORTING
        or type(started.payload) is not ExportStartedPayload
        or started.payload.bundle_name != command.bundle_name
    )
    if invalid:
        raise DomainError("invalid production export recovery") from None
    expected = (command.bundle_name,) if state.job.status is JobStatus.COMPLETED else ()
    if state.bundle_names != expected:
        raise InfrastructureError("production export recovery mismatch") from None
    return attempts


def _require_published_event(events: tuple[Event, ...], bundle: Any, /) -> None:
    published = _latest_event(events, EventType.EXPORT_PUBLISHED)
    if (
        published is None
        or published is not events[-1]
        or published.from_state is not JobStatus.EXPORTING
        or published.to_state is not JobStatus.COMPLETED
        or type(published.payload) is not ExportPublishedPayload
        or not _same_material(published.payload, _export_published_payload(bundle))
    ):
        raise InfrastructureError("production export recovery mismatch") from None


def _recovery_entry(job_id, disposition, result=None) -> ProductionRecoveryEntry:
    return ProductionRecoveryEntry(job_id, disposition, result)


def _recover_completed(runtime, command, target_root_fd, state, events):
    attempts = _validate_recovery_bindings(command, state, events)
    _require_persisted_attempts(runtime, command.job_id, attempts)
    bundle = _inspect_final_bundle(
        _prepare_export(command.export_request), target_root_fd, command.bundle_name
    )
    if bundle is None:
        raise InfrastructureError("production export recovery mismatch") from None
    _require_published_event(events, bundle)
    return ProductionExportResult(bundle, state)


def _prepare_recovery_export(runtime, command, target_root_fd, state, events, holder):
    attempts = _validate_recovery_bindings(command, state, events)
    _require_persisted_attempts(runtime, command.job_id, attempts)
    prepared = _prepare_export(command.export_request)
    holder.phase = _ExportPhase.UNKNOWN
    bundle = _inspect_final_bundle(prepared, target_root_fd, command.bundle_name)
    holder.phase = _ExportPhase.STAGING if bundle is None else _ExportPhase.PUBLISHED
    return bundle


def _commit_recovery(runtime, command, staged, bundle, holder):
    with holder.lock:
        state = runtime._job_store.load(command.job_id)
        if state.job.status is JobStatus.CANCELLED:
            raise DomainError("production job cancelled") from None
        if state.job.status is not JobStatus.EXPORTING:
            raise InfrastructureError("production export state changed") from None
        if bundle is None:
            holder.phase = _ExportPhase.UNKNOWN
            bundle = _commit_staged_bundle(staged, accept_exact_existing=True)
        holder.phase = _ExportPhase.PUBLISHED
        runtime._append_export_event(
            command.job_id,
            EventType.EXPORT_PUBLISHED,
            JobStatus.EXPORTING,
            JobStatus.COMPLETED,
            _export_published_payload(bundle),
        )
        return ProductionExportResult(bundle, runtime._job_store.load(command.job_id))


def _recover_exporting(runtime, command, target_root_fd, state, events, holder):
    with holder.lock:
        bundle = _prepare_recovery_export(
            runtime, command, target_root_fd, state, events, holder
        )
    staged = None
    try:
        if bundle is None:
            try:
                staged = _stage_bundle(
                    command.export_request, target_root_fd, command.bundle_name
                )
            except BaseException:
                with holder.lock:
                    holder.phase = _ExportPhase.STAGING
                raise
        return _commit_recovery(runtime, command, staged, bundle, holder)
    except BaseException:
        if staged is not None:
            _close_staged_quietly(staged)
        raise


def _recover_one(runtime, job_id, command, target_root_fd):
    if command is None:
        return _recovery_entry(
            job_id, ProductionRecoveryDisposition.SKIPPED_MISSING_COMMAND
        )
    holder = _export_lock_holder(runtime._job_store, job_id)
    with holder.operation_lock:
        with holder.lock:
            state = runtime._job_store.load(job_id)
            if state.job.status in {JobStatus.CANCELLED, JobStatus.JOB_FAILED}:
                return _recovery_entry(
                    job_id, ProductionRecoveryDisposition.SKIPPED_TERMINAL
                )
            events = runtime._job_store.list_events(job_id)
            if state.job.status is JobStatus.COMPLETED:
                result = _recover_completed(
                    runtime, command, target_root_fd, state, events
                )
                return _recovery_entry(
                    job_id, ProductionRecoveryDisposition.ALREADY_COMPLETED, result
                )
            if state.job.status is not JobStatus.EXPORTING:
                return _recovery_entry(
                    job_id, ProductionRecoveryDisposition.SKIPPED_NOT_EXPORTABLE
                )
        result = _recover_exporting(
            runtime, command, target_root_fd, state, events, holder
        )
        return _recovery_entry(job_id, ProductionRecoveryDisposition.RECOVERED, result)


def _recover_exports(runtime: Any, commands: object, target_root_fd: object, /):
    rebuilt = _rebuild_recovery_commands(commands)
    target_root_fd = _validate_export_root(target_root_fd)
    by_job = {command.job_id.value: command for command in rebuilt}
    return tuple(
        _recover_one(runtime, job_id, by_job.get(job_id.value), target_root_fd)
        for job_id in runtime._job_store.list_job_ids()
    )
