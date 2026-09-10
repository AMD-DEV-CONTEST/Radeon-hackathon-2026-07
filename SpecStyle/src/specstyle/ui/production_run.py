"""Production run-one UI binding.

This module adapts Gradio upload values into the file-descriptor boundary owned by
``workflow.run_one``. It does not construct generation, verification, or repair
backends directly.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, replace
from pathlib import Path

from specstyle.errors import DomainError, InfrastructureError
from specstyle.domain.identifiers import JobId, Sha256
from specstyle.ui.app import UiServices
from specstyle.ui.production_ui_inputs import (
    OpenProductionUiFds as _OpenFds,
    ProductionUiRuntimePaths,
    StagedInputs as _StagedInputs,
    UiRunInputError as _UiRunInputError,
    cleanup_staging as _cleanup_staging,
    stage_inputs as _stage_inputs,
)
from specstyle.ui.production_ui_projection import (
    batch_busy as _batch_busy,
    batch_failure as _batch_failure,
    batch_projection as _batch_projection,
    batch_view as _batch_view,
    busy as _busy,
    cancelled as _cancelled,
    cancelled_batch_item as _cancelled_batch_item,
    failed_batch_item as _failed_batch_item,
    failure as _failure,
    failure_projection as _failure_projection,
    projection_with_message as _projection_with_message,
    successful_batch_item as _successful_batch_item,
    status_projection as _status_projection,
    terminal_projection as _terminal_projection,
)
from specstyle.ui.production_ui_state import (
    ProductionTerminalProjection,
    ProductionUiState,
)
from specstyle.ui.view_models import (
    ProductionBatchItemUiView,
    ProductionBatchUiView,
    ProductionRunUiView,
)
from specstyle.workflow.run_one import (
    ProductionRunOneCleanupError,
    ProductionRunOneFds,
    ProductionRunOneResult,
    open_production_run_one,
    reserve_production_run_one,
)
from specstyle.workflow.job_store import JobStore
from specstyle.workflow.production_replay import (
    ProductionReplayAssessment,
    ProductionReplayEvidence,
    assess_production_replay,
    capture_production_replay_evidence,
)


def _capture_replay_evidence(
    result: object, form_fingerprint: Sha256
) -> ProductionReplayEvidence:
    if type(result) is not ProductionRunOneResult:
        raise DomainError("invalid production replay evidence") from None
    return capture_production_replay_evidence(
        result.job_result, result.export_result.bundle, form_fingerprint
    )


def _read_persisted_job_status(state_root: Path, job_id: str) -> str | None:
    store = JobStore(state_root)
    try:
        try:
            state = store.load(JobId(job_id))
        except DomainError as exc:
            if str(exc) == "job not found":
                return None
            raise
        return state.job.status.value
    finally:
        store.close()


@dataclass(frozen=True, slots=True)
class _SingleRunOutcome:
    projection: ProductionTerminalProjection
    replay_evidence: ProductionReplayEvidence | None


@dataclass(frozen=True, slots=True)
class _ReplayRunOutcome:
    message: str
    projection: ProductionTerminalProjection | None


def _safe_message(value: object) -> str:
    return str(value).replace("\t", " ").replace("\r", " ").replace("\n", " ")[:160]


def bind_production_run_one_services(
    base: UiServices,
    paths: ProductionUiRuntimePaths,
    *,
    reserve: Callable[..., object] = reserve_production_run_one,
    open_run_one: Callable[
        [ProductionRunOneFds, object], object
    ] = open_production_run_one,
) -> UiServices:
    if type(base) is not UiServices or type(paths) is not ProductionUiRuntimePaths:
        raise DomainError("invalid production ui services")
    ui_state = ProductionUiState(
        lambda job_id: _read_persisted_job_status(paths.state_root, job_id)
    )

    def run(
        source: object,
        style: object,
        spec: object,
        positive: str,
        negative: str,
        source_url: str | None,
        license_: str | None,
        attribution: str | None,
        consent: str,
    ) -> ProductionRunUiView:
        token = ui_state.try_begin("single", 1)
        if token is None:
            return _busy()
        try:
            outcome = _run(
                paths,
                reserve,
                open_run_one,
                source,
                style,
                spec,
                positive,
                negative,
                source_url,
                license_,
                attribution,
                consent,
                ui_state,
                token,
            )
            ui_state.finish(
                token,
                outcome.projection,
                replay_baseline=outcome.replay_evidence,
            )
            return outcome.projection.run_view
        except BaseException:
            ui_state.abandon(token)
            raise

    def run_batch(
        source: object,
        style: object,
        spec: object,
        positive: str,
        negative: str,
        source_url: str | None,
        license_: str | None,
        attribution: str | None,
        consent: str,
        count: int,
    ) -> ProductionBatchUiView:
        token = ui_state.try_begin("batch", count if type(count) is int else 1)
        if token is None:
            return _batch_busy()
        try:
            view = _run_batch(
                paths,
                reserve,
                open_run_one,
                source,
                style,
                spec,
                positive,
                negative,
                source_url,
                license_,
                attribution,
                consent,
                count,
                ui_state,
                token,
            )
            ui_state.finish(
                token,
                _batch_projection(view, ui_state.item_projections(token)),
            )
            return view
        except BaseException:
            ui_state.abandon(token)
            raise

    def run_replay(
        source: object,
        style: object,
        spec: object,
        positive: str,
        negative: str,
        source_url: str | None,
        license_: str | None,
        attribution: str | None,
        consent: str,
    ) -> str:
        token = ui_state.try_begin("replay", 1)
        if token is None:
            return "replay busy: production run active"
        try:
            baseline = ui_state.replay_baseline(token)
            if baseline is None:
                ui_state.abandon(token)
                return "replay unavailable: run one successful production job first"
            outcome = _run_replay(
                paths,
                reserve,
                open_run_one,
                source,
                style,
                spec,
                positive,
                negative,
                source_url,
                license_,
                attribution,
                consent,
                baseline,
                ui_state,
                token,
            )
            if outcome.projection is None:
                ui_state.abandon(token)
            else:
                ui_state.finish(token, outcome.projection)
            return outcome.message
        except BaseException:
            ui_state.abandon(token)
            raise

    return UiServices(
        base.compile_spec,
        get_job_status=ui_state.get_job_status,
        cancel_job=ui_state.cancel_job,
        get_qa_table=ui_state.get_qa_table,
        get_repair_timeline=ui_state.get_repair_timeline,
        get_export_summary=ui_state.get_export_summary,
        run_replay=run_replay,
        run_production_job=run,
        run_production_batch=run_batch,
        get_preview_readiness=base.get_preview_readiness,
        run_preview_job=base.run_preview_job,
        run_preview_wall=base.run_preview_wall,
    )


def bind_unavailable_production_services(base: UiServices, reason: str) -> UiServices:
    if type(base) is not UiServices or type(reason) is not str or not reason:
        raise DomainError("invalid unavailable production services")
    return replace(
        base,
        run_replay=lambda *_args: reason,
        run_production_job=lambda *_args: _failure("", reason),
        run_production_batch=lambda *_args: _batch_failure(reason),
    )


def _run(
    paths: ProductionUiRuntimePaths,
    reserve: Callable[[], object],
    open_run_one: Callable[[ProductionRunOneFds, object], object],
    source: object,
    style: object,
    spec: object,
    positive: str,
    negative: str,
    source_url: str | None,
    license_: str | None,
    attribution: str | None,
    consent: str,
    ui_state: ProductionUiState,
    token: int,
) -> _SingleRunOutcome:
    job_id = ""
    staged: _StagedInputs | None = None
    try:
        ui_state.set_phase(token, "STAGING")
        staged = _stage_inputs(
            paths,
            source,
            style,
            spec,
            positive,
            negative,
            source_url,
            license_,
            attribution,
            consent,
        )
        reservation = reserve()
        job_id = getattr(getattr(reservation, "job_id", None), "value", "")
        ui_state.set_phase(token, "RESERVED", job_id=job_id)
        if ui_state.is_cancel_requested(token):
            return _SingleRunOutcome(_failure_projection(_cancelled(job_id)), None)
        ui_state.set_phase(token, "OPENING", job_id=job_id)
        return _execute(paths, staged, reservation, open_run_one, ui_state, token)
    except _UiRunInputError as exc:
        return _SingleRunOutcome(
            _failure_projection(_failure(job_id, _safe_message(exc))), None
        )
    except (DomainError, InfrastructureError) as exc:
        return _SingleRunOutcome(
            _failure_projection(_failure(job_id, _safe_message(exc))), None
        )
    except Exception:
        return _SingleRunOutcome(
            _failure_projection(_failure(job_id, "internal error")), None
        )
    finally:
        if staged is not None:
            _cleanup_staging(staged.directory)


def _run_replay(
    paths: ProductionUiRuntimePaths,
    reserve: Callable[..., object],
    open_run_one: Callable[[ProductionRunOneFds, object], object],
    source: object,
    style: object,
    spec: object,
    positive: str,
    negative: str,
    source_url: str | None,
    license_: str | None,
    attribution: str | None,
    consent: str,
    baseline: ProductionReplayEvidence,
    ui_state: ProductionUiState,
    token: int,
) -> _ReplayRunOutcome:
    job_id = ""
    staged: _StagedInputs | None = None
    try:
        ui_state.set_phase(token, "STAGING")
        staged = _stage_inputs(
            paths,
            source,
            style,
            spec,
            positive,
            negative,
            source_url,
            license_,
            attribution,
            consent,
        )
        if staged.form_fingerprint != baseline.form_fingerprint:
            return _ReplayRunOutcome(
                "REJECTED\tsame_input\tinput_form_fingerprint_mismatch", None
            )
        reservation = reserve(baseline.variation_index)
        job_id = getattr(getattr(reservation, "job_id", None), "value", "")
        ui_state.set_phase(token, "RESERVED", job_id=job_id)
        if ui_state.is_cancel_requested(token):
            projection = _failure_projection(_cancelled(job_id))
            return _ReplayRunOutcome(
                "UNVERIFIABLE\tsame_input\treplay_cancelled", projection
            )
        ui_state.set_phase(token, "OPENING", job_id=job_id)
        outcome = _execute(paths, staged, reservation, open_run_one, ui_state, token)
        return _assess_replay_outcome(baseline, outcome)
    except _UiRunInputError as exc:
        message = _safe_message(exc)
        return _ReplayRunOutcome(f"REJECTED\tsame_input\tinput_error={message}", None)
    except (DomainError, InfrastructureError) as exc:
        return _replay_failure(job_id, _safe_message(exc))
    except Exception:
        return _replay_failure(job_id, "internal error")
    finally:
        if staged is not None:
            _cleanup_staging(staged.directory)


def _assess_replay_outcome(
    baseline: ProductionReplayEvidence, outcome: _SingleRunOutcome
) -> _ReplayRunOutcome:
    candidate = outcome.replay_evidence
    if candidate is None:
        status = outcome.projection.run_view.status
        message = f"UNVERIFIABLE\tsame_input\treplay_evidence_unavailable={status}"
        return _ReplayRunOutcome(message, outcome.projection)
    assessment = assess_production_replay(baseline, candidate)
    return _ReplayRunOutcome(
        _format_replay_assessment(baseline, candidate, assessment),
        outcome.projection,
    )


def _replay_failure(job_id: str, message: str) -> _ReplayRunOutcome:
    projection = _failure_projection(_failure(job_id, message)) if job_id else None
    text = f"UNVERIFIABLE\tsame_input\treplay_failed={message}"
    return _ReplayRunOutcome(text, projection)


def _format_replay_assessment(
    baseline: ProductionReplayEvidence,
    candidate: ProductionReplayEvidence,
    assessment: ProductionReplayAssessment,
) -> str:
    metrics = ",".join(
        f"{item.level}:{item.rule_id}={item.delta:.12g}/{item.tolerance:.12g}"
        for item in assessment.metrics
    )
    reasons = ",".join(assessment.reasons) or "none"
    return "\t".join(
        (
            assessment.status,
            assessment.mode,
            f"baseline_job={baseline.job_id}",
            f"replay_job={candidate.job_id}",
            f"baseline_bundle={baseline.bundle_name}",
            f"replay_bundle={candidate.bundle_name}",
            "artifact_hash_equal="
            + ("YES" if assessment.artifact_hash_equal else "NO"),
            "pixel_exact_required=NO",
            f"metrics={metrics or 'none'}",
            f"l3={assessment.l3_status}",
            f"reasons={reasons}",
        )
    )


def _run_batch(
    paths: ProductionUiRuntimePaths,
    reserve: Callable[..., object],
    open_run_one: Callable[[ProductionRunOneFds, object], object],
    source: object,
    style: object,
    spec: object,
    positive: str,
    negative: str,
    source_url: str | None,
    license_: str | None,
    attribution: str | None,
    consent: str,
    count: int,
    ui_state: ProductionUiState,
    token: int,
) -> ProductionBatchUiView:
    if type(count) is not int or not 2 <= count <= 4:
        return _batch_failure("batch count must be an exact int from 2 to 4")
    staged: _StagedInputs | None = None
    try:
        ui_state.set_phase(token, "STAGING")
        staged = _stage_inputs(
            paths,
            source,
            style,
            spec,
            positive,
            negative,
            source_url,
            license_,
            attribution,
            consent,
        )
        stride = staged.max_rounds + 1
        items: list[ProductionBatchItemUiView] = []
        for index in range(count):
            if ui_state.is_cancel_requested(token):
                break
            ui_state.set_phase(token, "STAGING", job_id="", current_index=index)
            outcome = _reserve_batch_item(
                paths,
                staged,
                reserve,
                open_run_one,
                index,
                index * stride,
                ui_state,
                token,
            )
            items.append(outcome.item)
            ui_state.add_item_projection(token, outcome.projection)
            if ui_state.is_cancel_requested(token):
                break
        return _batch_view(tuple(items))
    except _UiRunInputError as exc:
        return _batch_failure(_safe_message(exc))
    except (DomainError, InfrastructureError) as exc:
        return _batch_failure(_safe_message(exc))
    except Exception:
        return _batch_failure("internal error")
    finally:
        if staged is not None:
            _cleanup_staging(staged.directory)


@dataclass(frozen=True, slots=True)
class _BatchItemOutcome:
    item: ProductionBatchItemUiView
    projection: ProductionTerminalProjection


def _item_outcome(item: ProductionBatchItemUiView) -> _BatchItemOutcome:
    return _BatchItemOutcome(item, _failure_projection(item.run))


def _reserve_batch_item(
    paths: ProductionUiRuntimePaths,
    staged: _StagedInputs,
    reserve: Callable[..., object],
    open_run_one: Callable[[ProductionRunOneFds, object], object],
    item_index: int,
    requested_variation: int,
    ui_state: ProductionUiState,
    token: int,
) -> _BatchItemOutcome:
    try:
        reservation = reserve(requested_variation)
        job_id = getattr(getattr(reservation, "job_id", None), "value", "")
        ui_state.set_phase(token, "RESERVED", job_id=job_id, current_index=item_index)
        if ui_state.is_cancel_requested(token):
            return _item_outcome(
                _cancelled_batch_item(item_index, requested_variation, job_id)
            )
    except (DomainError, InfrastructureError) as exc:
        return _item_outcome(
            _failed_batch_item(item_index, requested_variation, "", _safe_message(exc))
        )
    except Exception:
        return _item_outcome(
            _failed_batch_item(item_index, requested_variation, "", "internal error")
        )
    return _execute_batch_item(
        paths,
        staged,
        reservation,
        open_run_one,
        item_index,
        requested_variation,
        job_id,
        ui_state,
        token,
    )


def _execute_batch_item(
    paths: ProductionUiRuntimePaths,
    staged: _StagedInputs,
    reservation: object,
    open_run_one: Callable[[ProductionRunOneFds, object], object],
    item_index: int,
    requested_variation: int,
    job_id: str,
    ui_state: ProductionUiState,
    token: int,
) -> _BatchItemOutcome:
    try:
        ui_state.set_phase(token, "OPENING", job_id=job_id, current_index=item_index)
        with _OpenFds(paths, staged) as fds:
            execution = open_run_one(fds, reservation)
    except (DomainError, InfrastructureError) as exc:
        return _item_outcome(
            _failed_batch_item(
                item_index, requested_variation, job_id, _safe_message(exc)
            )
        )
    except Exception:
        return _item_outcome(
            _failed_batch_item(
                item_index, requested_variation, job_id, "internal error"
            )
        )
    pending_cancel = ui_state.register_execution(token, execution)
    if pending_cancel:
        ui_state.cancel_registered_execution(token)
    try:
        result = execution.run()
    except BaseException as primary:
        _ignored, cleanup_error = _close_single_execution(ui_state, token, execution)
        if not isinstance(primary, Exception):
            if cleanup_error is not None:
                primary.add_note("production batch item cleanup failed")
            raise
        if isinstance(primary, DomainError) and ui_state.is_cancel_requested(token):
            return _item_outcome(
                _cancelled_batch_item(
                    item_index, requested_variation, job_id, cleanup_error
                )
            )
        message = (
            _safe_message(primary)
            if isinstance(primary, (DomainError, InfrastructureError))
            else "internal error"
        )
        return _item_outcome(
            _failed_batch_item(
                item_index, requested_variation, job_id, message, cleanup_error
            )
        )
    ui_state.set_phase(token, "RESULT_READY", job_id=job_id, current_index=item_index)
    cleanup_result, cleanup_error = _close_single_execution(ui_state, token, execution)
    if cleanup_error is not None and cleanup_result is None:
        return _item_outcome(
            _failed_batch_item(
                item_index,
                requested_variation,
                job_id,
                cleanup_error,
                cleanup_error,
            )
        )
    result = cleanup_result if cleanup_result is not None else result
    try:
        projection = _terminal_projection(paths.export_root, result, job_id)
        item = _successful_batch_item(
            paths.export_root,
            result,
            item_index,
            requested_variation,
            staged.max_rounds,
            job_id,
            cleanup_error,
        )
        if cleanup_error is not None:
            projection = _projection_with_message(
                projection, "production run completed; cleanup failed"
            )
        return _BatchItemOutcome(item, projection)
    except (DomainError, InfrastructureError) as exc:
        return _item_outcome(
            _failed_batch_item(
                item_index,
                requested_variation,
                job_id,
                _safe_message(exc),
                cleanup_error,
            )
        )
    except Exception:
        return _item_outcome(
            _failed_batch_item(
                item_index,
                requested_variation,
                job_id,
                "internal error",
                cleanup_error,
            )
        )


def _execute(
    paths: ProductionUiRuntimePaths,
    staged: _StagedInputs,
    reservation: object,
    open_run_one: Callable[[ProductionRunOneFds, object], object],
    ui_state: ProductionUiState,
    token: int,
) -> _SingleRunOutcome:
    job_id = getattr(getattr(reservation, "job_id", None), "value", "")
    with _OpenFds(paths, staged) as fds:
        execution = open_run_one(fds, reservation)
    pending_cancel = ui_state.register_execution(token, execution)
    if pending_cancel:
        ui_state.cancel_registered_execution(token)
    try:
        result = execution.run()
    except BaseException as primary:
        _cleanup_result, cleanup_error = _close_single_execution(
            ui_state, token, execution
        )
        if not isinstance(primary, Exception):
            if cleanup_error is not None:
                primary.add_note("production run cleanup failed")
            raise
        if isinstance(primary, DomainError) and ui_state.is_cancel_requested(token):
            projection = _failure_projection(_cancelled(job_id))
            if cleanup_error is not None:
                projection = _projection_with_message(
                    projection, "production run cancelled; cleanup failed"
                )
            return _SingleRunOutcome(projection, None)
        raise
    ui_state.set_phase(token, "RESULT_READY", job_id=job_id)
    cleanup_result, cleanup_error = _close_single_execution(ui_state, token, execution)
    if cleanup_error is not None and cleanup_result is None:
        try:
            persisted = _read_persisted_job_status(paths.state_root, job_id)
        except Exception:
            persisted = None
        if persisted is not None:
            return _SingleRunOutcome(
                _status_projection(job_id, persisted, cleanup_error), None
            )
        raise InfrastructureError(cleanup_error)
    result = cleanup_result if cleanup_result is not None else result
    projection = _terminal_projection(paths.export_root, result, job_id)
    if cleanup_error is not None:
        projection = _projection_with_message(
            projection, "production run completed; cleanup failed"
        )
    return _SingleRunOutcome(
        projection, _try_capture_replay_evidence(result, staged.form_fingerprint)
    )


def _try_capture_replay_evidence(
    result: object, form_fingerprint: Sha256
) -> ProductionReplayEvidence | None:
    try:
        return _capture_replay_evidence(result, form_fingerprint)
    except Exception:
        return None


def _close_single_execution(
    ui_state: ProductionUiState, token: int, execution: object
) -> tuple[object | None, str | None]:
    try:
        ui_state.close_execution(token, execution)
    except ProductionRunOneCleanupError as exc:
        return exc.result, str(exc)
    except Exception:
        return None, "internal cleanup error"
    return None, None
