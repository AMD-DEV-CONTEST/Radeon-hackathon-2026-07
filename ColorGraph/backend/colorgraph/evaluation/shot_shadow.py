from __future__ import annotations

import hashlib
import json
import time
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from pydantic import Field, model_validator

from colorgraph.evaluation.models import StrictEvaluationModel
from colorgraph.evaluation.runtime_memory import process_peak_memory_mb
from colorgraph.media.probe import probe_media
from colorgraph.media.shots import (
    detect_shot_ranges,
    detect_shot_ranges_pyscenedetect,
    pyscenedetect_boundary_frames,
)

SHOT_SHADOW_VERSION = "colorgraph.shot-model-shadow-evaluation/v1"

ShotModelId = Literal[
    "current_detector",
    "pyscenedetect_adaptive",
    "transnetv2",
    "autoshot",
]
REQUIRED_SHOT_MODELS: tuple[ShotModelId, ...] = (
    "current_detector",
    "pyscenedetect_adaptive",
    "transnetv2",
    "autoshot",
)
ShotEventKind = Literal["hard_cut", "fade", "dissolve", "flash", "short_shot"]
BOUNDARY_EVENT_KINDS: tuple[ShotEventKind, ...] = (
    "hard_cut",
    "fade",
    "dissolve",
    "short_shot",
)
MediaOrigin = Literal[
    "camera_original",
    "licensed_stock",
    "published_dataset",
    "procedural",
]
EvidenceClass = Literal["engineering_fixture", "gold"]
RunStatus = Literal["completed", "blocked", "failed"]
ObservableShotModelId = Literal[
    "current_detector",
    "pyscenedetect_adaptive",
]


class ShotEvent(StrictEvaluationModel):
    event_id: str = Field(min_length=1)
    kind: ShotEventKind
    start_frame: int = Field(ge=0)
    end_frame: int = Field(ge=0)

    @model_validator(mode="after")
    def validate_interval(self) -> ShotEvent:
        if self.end_frame < self.start_frame:
            raise ValueError("event end_frame must not precede start_frame")
        return self


class ShotEvaluationItem(StrictEvaluationModel):
    item_id: str = Field(min_length=1)
    source_group_id: str = Field(min_length=1)
    media_origin: MediaOrigin
    media_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    annotation_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    frame_count: int = Field(gt=0)
    fps: float = Field(gt=0)
    events: list[ShotEvent] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_events(self) -> ShotEvaluationItem:
        event_ids = [event.event_id for event in self.events]
        if len(set(event_ids)) != len(event_ids):
            raise ValueError("shot event IDs must be unique within an item")
        if any(event.end_frame >= self.frame_count for event in self.events):
            raise ValueError("shot event lies outside the media frame range")
        return self


class ShotDatasetEvidence(StrictEvaluationModel):
    evidence_class: EvidenceClass
    test_frozen_at: datetime
    annotation_guideline_version: str = Field(min_length=1)
    gold_manifest_sha256: str | None = Field(
        default=None,
        pattern=r"^[0-9a-f]{64}$",
    )
    gold_audit_report_sha256: str | None = Field(
        default=None,
        pattern=r"^[0-9a-f]{64}$",
    )
    independent_reviewer_ids: list[str] = Field(default_factory=list)


class ShotModelArtifacts(StrictEvaluationModel):
    code_url: str | None = Field(
        default=None,
        pattern=r"^(?:https://|workspace://)",
    )
    code_license_id: str | None = None
    code_commercial_use_allowed: bool | None = None
    source_revision: str | None = Field(
        default=None,
        pattern=r"^[0-9a-f]{40}$",
    )
    weights_required: bool
    weights_url: str | None = Field(default=None, pattern=r"^https://")
    weights_license_id: str | None = None
    weights_commercial_use_allowed: bool | None = None
    checkpoint_sha256: str | None = Field(
        default=None,
        pattern=r"^[0-9a-f]{64}$",
    )


class ShotModelObservation(StrictEvaluationModel):
    item_id: str
    predicted_boundaries: list[int] = Field(default_factory=list)
    elapsed_seconds: float = Field(gt=0)
    peak_cpu_memory_mb: float = Field(ge=0)
    peak_gpu_memory_mb: float = Field(ge=0)

    @model_validator(mode="after")
    def validate_boundaries(self) -> ShotModelObservation:
        if self.predicted_boundaries != sorted(set(self.predicted_boundaries)):
            raise ValueError("predicted boundaries must be sorted and unique")
        if any(frame < 0 for frame in self.predicted_boundaries):
            raise ValueError("predicted boundaries must be non-negative")
        return self


class ShotModelRun(StrictEvaluationModel):
    model_id: ShotModelId
    status: RunStatus
    artifacts: ShotModelArtifacts
    observations: list[ShotModelObservation] = Field(default_factory=list)
    blocker: str | None = None
    error: str | None = None

    @model_validator(mode="after")
    def validate_status(self) -> ShotModelRun:
        if self.status == "completed":
            if not self.observations:
                raise ValueError("completed shot-model run requires observations")
            if self.blocker is not None or self.error is not None:
                raise ValueError("completed run cannot carry blocker/error")
        elif self.status == "blocked":
            if not self.blocker:
                raise ValueError("blocked shot-model run requires a blocker")
            if self.observations:
                raise ValueError("blocked shot-model run cannot carry observations")
        else:
            if not self.error:
                raise ValueError("failed shot-model run requires an error")
            if self.observations:
                raise ValueError("failed shot-model run cannot carry observations")
        return self


class ShotShadowConfig(StrictEvaluationModel):
    tolerance_frames: int = Field(default=2, ge=0)
    minimum_overall_f1_improvement: float = Field(default=0.02, ge=0, le=1)
    maximum_kind_recall_regression: float = Field(default=0.02, ge=0, le=1)
    minimum_kind_recall: float = Field(default=0.70, ge=0, le=1)
    maximum_flash_false_trigger_rate: float = Field(default=0.10, ge=0, le=1)


class ShotShadowBundle(StrictEvaluationModel):
    schema_version: str = SHOT_SHADOW_VERSION
    created_at: datetime
    dataset: ShotDatasetEvidence
    config: ShotShadowConfig = Field(default_factory=ShotShadowConfig)
    items: list[ShotEvaluationItem] = Field(min_length=1)
    runs: list[ShotModelRun] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_bundle(self) -> ShotShadowBundle:
        item_ids = [item.item_id for item in self.items]
        if len(set(item_ids)) != len(item_ids):
            raise ValueError("shot evaluation item IDs must be unique")
        model_ids = [run.model_id for run in self.runs]
        if len(set(model_ids)) != len(model_ids):
            raise ValueError("shot model IDs must be unique")
        known_items = set(item_ids)
        for run in self.runs:
            observation_ids = [observation.item_id for observation in run.observations]
            if len(set(observation_ids)) != len(observation_ids):
                raise ValueError(f"{run.model_id} observation item IDs must be unique")
            unknown = set(observation_ids) - known_items
            if unknown:
                raise ValueError(
                    f"{run.model_id} observations reference unknown items: {sorted(unknown)}"
                )
            item_by_id = {item.item_id: item for item in self.items}
            for observation in run.observations:
                if any(
                    frame >= item_by_id[observation.item_id].frame_count
                    for frame in observation.predicted_boundaries
                ):
                    raise ValueError(
                        f"{run.model_id} prediction lies outside "
                        f"{observation.item_id}"
                    )
        return self


class ShotKindMetrics(StrictEvaluationModel):
    reference_events: int = Field(ge=0)
    true_positives: int = Field(ge=0)
    false_negatives: int = Field(ge=0)
    recall: float | None = Field(default=None, ge=0, le=1)
    timing_mae_frames: float | None = Field(default=None, ge=0)
    false_trigger_events: int = Field(default=0, ge=0)
    false_trigger_rate: float | None = Field(default=None, ge=0, le=1)


class ShotBoundaryMetrics(StrictEvaluationModel):
    reference_boundaries: int = Field(ge=0)
    predicted_boundaries: int = Field(ge=0)
    true_positives: int = Field(ge=0)
    false_positives: int = Field(ge=0)
    false_negatives: int = Field(ge=0)
    precision: float = Field(ge=0, le=1)
    recall: float = Field(ge=0, le=1)
    f1: float = Field(ge=0, le=1)
    by_kind: dict[ShotEventKind, ShotKindMetrics]


class ShotModelReport(StrictEvaluationModel):
    model_id: ShotModelId
    status: RunStatus
    blocker: str | None
    error: str | None
    artifact_gate_passed: bool
    artifact_blockers: list[str]
    evaluated_items: int = Field(ge=0)
    metrics: ShotBoundaryMetrics | None = None
    processing_fps: float | None = Field(default=None, gt=0)
    peak_cpu_memory_mb: float | None = Field(default=None, ge=0)
    peak_gpu_memory_mb: float | None = Field(default=None, ge=0)
    candidate_quality_gate_passed: bool = False
    candidate_quality_blockers: list[str] = Field(default_factory=list)


class ShotShadowReport(StrictEvaluationModel):
    schema_version: str = SHOT_SHADOW_VERSION
    evaluator_version: str = SHOT_SHADOW_VERSION
    created_at: datetime
    input_path: str
    input_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    status: Literal["complete", "partial"]
    release_status: Literal["shadow_only", "eligible_default_candidate"]
    recommended_candidate: Literal["transnetv2", "autoshot"] | None
    dataset: ShotDatasetEvidence
    config: ShotShadowConfig
    reports: list[ShotModelReport]
    gates: dict[str, bool]
    missing_models: list[ShotModelId]
    notes: list[str] = Field(default_factory=list)


def _safe_ratio(numerator: int | float, denominator: int | float) -> float:
    return float(numerator / denominator) if denominator else 0.0


def _artifact_blockers(run: ShotModelRun) -> list[str]:
    artifacts = run.artifacts
    blockers: list[str] = []
    if run.status != "completed":
        blockers.append("model_run_not_completed")
    if artifacts.code_url is None:
        blockers.append("code_source_missing")
    if not artifacts.code_license_id:
        blockers.append("code_license_missing")
    if artifacts.code_commercial_use_allowed is not True:
        blockers.append("code_commercial_use_not_cleared")
    if artifacts.source_revision is None:
        blockers.append("source_revision_unfrozen")
    if artifacts.weights_required:
        if artifacts.weights_url is None:
            blockers.append("weights_source_missing")
        if not artifacts.weights_license_id:
            blockers.append("weights_license_missing")
        if artifacts.weights_commercial_use_allowed is not True:
            blockers.append("weights_commercial_use_not_cleared")
        if artifacts.checkpoint_sha256 is None:
            blockers.append("checkpoint_sha256_unfrozen")
    return sorted(set(blockers))


def _distance_to_event(frame: int, event: ShotEvent) -> int:
    if frame < event.start_frame:
        return event.start_frame - frame
    if frame > event.end_frame:
        return frame - event.end_frame
    return 0


def _evaluate_observations(
    items: dict[str, ShotEvaluationItem],
    observations: list[ShotModelObservation],
    *,
    tolerance_frames: int,
) -> tuple[ShotBoundaryMetrics, int, float, float, float]:
    reference_count = 0
    prediction_count = 0
    true_positives = 0
    kind_reference = {kind: 0 for kind in BOUNDARY_EVENT_KINDS}
    kind_true_positive = {kind: 0 for kind in BOUNDARY_EVENT_KINDS}
    kind_timing_errors: dict[ShotEventKind, list[int]] = {
        kind: [] for kind in BOUNDARY_EVENT_KINDS
    }
    flash_events = 0
    flash_false_triggers = 0
    elapsed_seconds = 0.0
    processed_frames = 0
    peak_cpu = 0.0
    peak_gpu = 0.0

    for observation in observations:
        item = items[observation.item_id]
        elapsed_seconds += observation.elapsed_seconds
        processed_frames += item.frame_count
        peak_cpu = max(peak_cpu, observation.peak_cpu_memory_mb)
        peak_gpu = max(peak_gpu, observation.peak_gpu_memory_mb)
        predictions = observation.predicted_boundaries
        boundary_events = [event for event in item.events if event.kind != "flash"]
        reference_count += len(boundary_events)
        prediction_count += len(predictions)
        for event in boundary_events:
            kind_reference[event.kind] += 1

        unmatched = set(range(len(boundary_events)))
        for prediction in predictions:
            candidates = [
                index
                for index in unmatched
                if _distance_to_event(prediction, boundary_events[index])
                <= tolerance_frames
            ]
            if not candidates:
                continue
            best = min(
                candidates,
                key=lambda index: (
                    _distance_to_event(prediction, boundary_events[index]),
                    abs(
                        prediction
                        - (
                            boundary_events[index].start_frame
                            + boundary_events[index].end_frame
                        )
                        / 2
                    ),
                    index,
                ),
            )
            event = boundary_events[best]
            unmatched.remove(best)
            true_positives += 1
            kind_true_positive[event.kind] += 1
            kind_timing_errors[event.kind].append(
                _distance_to_event(prediction, event)
            )

        for event in (event for event in item.events if event.kind == "flash"):
            flash_events += 1
            if any(
                _distance_to_event(prediction, event) <= tolerance_frames
                for prediction in predictions
            ):
                flash_false_triggers += 1

    false_positives = prediction_count - true_positives
    false_negatives = reference_count - true_positives
    precision = _safe_ratio(true_positives, prediction_count)
    recall = _safe_ratio(true_positives, reference_count)
    f1 = _safe_ratio(2 * precision * recall, precision + recall)
    by_kind: dict[ShotEventKind, ShotKindMetrics] = {}
    for kind in BOUNDARY_EVENT_KINDS:
        references = kind_reference[kind]
        matches = kind_true_positive[kind]
        errors = kind_timing_errors[kind]
        by_kind[kind] = ShotKindMetrics(
            reference_events=references,
            true_positives=matches,
            false_negatives=references - matches,
            recall=_safe_ratio(matches, references) if references else None,
            timing_mae_frames=(
                _safe_ratio(sum(errors), len(errors)) if errors else None
            ),
        )
    by_kind["flash"] = ShotKindMetrics(
        reference_events=flash_events,
        true_positives=0,
        false_negatives=0,
        recall=None,
        timing_mae_frames=None,
        false_trigger_events=flash_false_triggers,
        false_trigger_rate=(
            _safe_ratio(flash_false_triggers, flash_events)
            if flash_events
            else None
        ),
    )
    return (
        ShotBoundaryMetrics(
            reference_boundaries=reference_count,
            predicted_boundaries=prediction_count,
            true_positives=true_positives,
            false_positives=false_positives,
            false_negatives=false_negatives,
            precision=precision,
            recall=recall,
            f1=f1,
            by_kind=by_kind,
        ),
        processed_frames,
        elapsed_seconds,
        peak_cpu,
        peak_gpu,
    )


def _candidate_quality_blockers(
    report: ShotModelReport,
    baseline: ShotModelReport | None,
    config: ShotShadowConfig,
) -> list[str]:
    if report.metrics is None or baseline is None or baseline.metrics is None:
        return ["candidate_or_baseline_metrics_missing"]
    blockers: list[str] = []
    if (
        report.metrics.f1
        < baseline.metrics.f1 + config.minimum_overall_f1_improvement
    ):
        blockers.append("overall_f1_improvement_not_met")
    for kind in BOUNDARY_EVENT_KINDS:
        value = report.metrics.by_kind[kind].recall
        baseline_value = baseline.metrics.by_kind[kind].recall
        if value is None or baseline_value is None:
            blockers.append(f"{kind}_coverage_missing")
            continue
        if value < config.minimum_kind_recall:
            blockers.append(f"{kind}_minimum_recall_not_met")
        if value + config.maximum_kind_recall_regression < baseline_value:
            blockers.append(f"{kind}_recall_regressed")
    flash_rate = report.metrics.by_kind["flash"].false_trigger_rate
    if flash_rate is None:
        blockers.append("flash_coverage_missing")
    elif flash_rate > config.maximum_flash_false_trigger_rate:
        blockers.append("flash_false_trigger_rate_exceeded")
    if not report.artifact_gate_passed:
        blockers.append("artifact_gate_not_passed")
    return sorted(set(blockers))


def evaluate_shot_shadow(
    bundle: ShotShadowBundle,
    *,
    input_path: str,
    input_sha256: str,
    created_at: datetime | None = None,
) -> ShotShadowReport:
    item_by_id = {item.item_id: item for item in bundle.items}
    run_by_model = {run.model_id: run for run in bundle.runs}
    missing_models = [
        model_id for model_id in REQUIRED_SHOT_MODELS if model_id not in run_by_model
    ]
    model_reports: list[ShotModelReport] = []
    for model_id in REQUIRED_SHOT_MODELS:
        run = run_by_model.get(model_id)
        if run is None:
            continue
        artifact_blockers = _artifact_blockers(run)
        report = ShotModelReport(
            model_id=model_id,
            status=run.status,
            blocker=run.blocker,
            error=run.error,
            artifact_gate_passed=not artifact_blockers,
            artifact_blockers=artifact_blockers,
            evaluated_items=len(run.observations),
        )
        if run.status == "completed":
            metrics, frames, elapsed, peak_cpu, peak_gpu = _evaluate_observations(
                item_by_id,
                run.observations,
                tolerance_frames=bundle.config.tolerance_frames,
            )
            report.metrics = metrics
            report.processing_fps = frames / elapsed
            report.peak_cpu_memory_mb = peak_cpu
            report.peak_gpu_memory_mb = peak_gpu
        model_reports.append(report)

    report_by_model = {report.model_id: report for report in model_reports}
    baseline = report_by_model.get("current_detector")
    for model_id in ("transnetv2", "autoshot"):
        report = report_by_model.get(model_id)
        if report is None:
            continue
        blockers = _candidate_quality_blockers(report, baseline, bundle.config)
        report.candidate_quality_blockers = blockers
        report.candidate_quality_gate_passed = not blockers

    required_set = set(REQUIRED_SHOT_MODELS)
    full_matrix_completed = (
        not missing_models
        and all(
            run_by_model[model_id].status == "completed"
            and {
                observation.item_id
                for observation in run_by_model[model_id].observations
            }
            == set(item_by_id)
            for model_id in required_set
        )
    )
    transition_coverage_complete = all(
        any(event.kind == kind for item in bundle.items for event in item.events)
        for kind in (*BOUNDARY_EVENT_KINDS, "flash")
    )
    dataset_is_gold = (
        bundle.dataset.evidence_class == "gold"
        and bundle.dataset.gold_manifest_sha256 is not None
        and bundle.dataset.gold_audit_report_sha256 is not None
        and bool(bundle.dataset.independent_reviewer_ids)
        and bundle.dataset.annotation_guideline_version != "unversioned"
        and all(item.media_origin != "procedural" for item in bundle.items)
    )
    artifacts_frozen_and_licensed = (
        full_matrix_completed
        and all(report.artifact_gate_passed for report in model_reports)
    )
    eligible_reports = [
        report
        for report in model_reports
        if report.model_id in {"transnetv2", "autoshot"}
        and report.candidate_quality_gate_passed
        and report.metrics is not None
    ]
    recommended = (
        max(
            eligible_reports,
            key=lambda report: (
                report.metrics.f1 if report.metrics is not None else -1,
                report.model_id,
            ),
        ).model_id
        if eligible_reports
        else None
    )
    gates = {
        "frozen_human_gold_test": dataset_is_gold,
        "transition_coverage_complete": transition_coverage_complete,
        "required_model_matrix_completed": full_matrix_completed,
        "artifacts_frozen_and_commercially_cleared": (
            artifacts_frozen_and_licensed
        ),
        "candidate_quality_improvement": recommended is not None,
    }
    release_allowed = all(gates.values())
    return ShotShadowReport(
        created_at=created_at or datetime.now(UTC),
        input_path=input_path,
        input_sha256=input_sha256,
        status="complete" if full_matrix_completed else "partial",
        release_status=(
            "eligible_default_candidate" if release_allowed else "shadow_only"
        ),
        recommended_candidate=recommended if release_allowed else None,
        dataset=bundle.dataset,
        config=bundle.config,
        reports=model_reports,
        gates=gates,
        missing_models=missing_models,
        notes=[
            "PySceneDetect Adaptive and the current detector remain CPU fallbacks.",
            (
                "A complete engineering fixture remains shadow-only; only frozen, "
                "independently reviewed Gold evidence can authorize a default candidate."
            ),
            "Public-paper metrics are not accepted as ColorGraph observations.",
        ],
    )


def evaluate_shot_shadow_file(
    input_path: str | Path,
    output_path: str | Path,
) -> ShotShadowReport:
    source = Path(input_path).resolve()
    content = source.read_bytes()
    bundle = ShotShadowBundle.model_validate_json(content)
    report = evaluate_shot_shadow(
        bundle,
        input_path=str(source),
        input_sha256=hashlib.sha256(content).hexdigest(),
    )
    destination = Path(output_path).resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        json.dumps(report.model_dump(mode="json"), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return report


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(8 * 1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def capture_shot_model_observations(
    bundle: ShotShadowBundle,
    *,
    model_id: ObservableShotModelId,
    media_paths: Mapping[str, str | Path],
) -> ShotShadowBundle:
    """Capture real CPU fallback observations into a frozen shadow bundle."""
    expected_items = {item.item_id for item in bundle.items}
    supplied_items = set(media_paths)
    if supplied_items != expected_items:
        missing = sorted(expected_items - supplied_items)
        unexpected = sorted(supplied_items - expected_items)
        raise ValueError(
            "shot observation media bindings must exactly cover bundle items; "
            f"missing={missing}; unexpected={unexpected}"
        )
    run_index = next(
        (
            index
            for index, run in enumerate(bundle.runs)
            if run.model_id == model_id
        ),
        None,
    )
    if run_index is None:
        raise ValueError(f"shot bundle does not define model run {model_id}")

    observations: list[ShotModelObservation] = []
    for item in bundle.items:
        media_path = Path(media_paths[item.item_id]).resolve()
        if not media_path.is_file():
            raise FileNotFoundError(media_path)
        actual_sha256 = _file_sha256(media_path)
        if actual_sha256 != item.media_sha256:
            raise ValueError(
                f"{item.item_id} media SHA-256 mismatch: "
                f"{actual_sha256} != {item.media_sha256}"
            )
        media = probe_media(media_path)
        if media.frame_count != item.frame_count:
            raise ValueError(
                f"{item.item_id} frame count mismatch: "
                f"{media.frame_count} != {item.frame_count}"
            )
        fps_tolerance = max(1e-3, item.fps * 1e-4)
        if abs(media.fps - item.fps) > fps_tolerance:
            raise ValueError(
                f"{item.item_id} FPS mismatch: {media.fps} != {item.fps}"
            )

        started = time.perf_counter()
        if model_id == "current_detector":
            ranges = detect_shot_ranges(media_path)
        else:
            ranges = detect_shot_ranges_pyscenedetect(media_path)
        elapsed = max(time.perf_counter() - started, 1e-9)
        observations.append(
            ShotModelObservation(
                item_id=item.item_id,
                predicted_boundaries=pyscenedetect_boundary_frames(
                    ranges,
                    fps=item.fps,
                ),
                elapsed_seconds=elapsed,
                peak_cpu_memory_mb=process_peak_memory_mb(),
                peak_gpu_memory_mb=0,
            )
        )

    updated_runs = list(bundle.runs)
    updated_runs[run_index] = ShotModelRun(
        model_id=model_id,
        status="completed",
        artifacts=bundle.runs[run_index].artifacts,
        observations=observations,
    )
    return ShotShadowBundle.model_validate(
        bundle.model_copy(
            deep=True,
            update={"runs": updated_runs},
        ).model_dump(mode="python")
    )


def capture_shot_model_observations_file(
    input_path: str | Path,
    output_path: str | Path,
    *,
    model_id: ObservableShotModelId,
    media_paths: Mapping[str, str | Path],
) -> ShotShadowBundle:
    source = Path(input_path).resolve()
    bundle = ShotShadowBundle.model_validate_json(source.read_bytes())
    captured = capture_shot_model_observations(
        bundle,
        model_id=model_id,
        media_paths=media_paths,
    )
    destination = Path(output_path).resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        json.dumps(
            captured.model_dump(mode="json"),
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    return captured
