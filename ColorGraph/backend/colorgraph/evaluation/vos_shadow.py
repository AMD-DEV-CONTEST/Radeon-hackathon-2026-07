from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from pydantic import Field, model_validator

from colorgraph.evaluation.models import StrictEvaluationModel

VOS_SHADOW_VERSION = "colorgraph.video-object-mask-shadow-evaluation/v1"

VOSModelId = Literal["farneback", "sam21", "sam31", "cutie", "sea_raft"]
REQUIRED_VOS_MODELS: tuple[VOSModelId, ...] = (
    "farneback",
    "sam21",
    "sam31",
    "cutie",
    "sea_raft",
)
VOSScenario = Literal[
    "occlusion",
    "reveal",
    "long_drift",
    "anchor_jump",
    "disappear_reappear",
]
REQUIRED_VOS_SCENARIOS: tuple[VOSScenario, ...] = (
    "occlusion",
    "reveal",
    "long_drift",
    "anchor_jump",
    "disappear_reappear",
)
PlatformId = Literal["windows", "wsl2", "linux"]
AcceleratorId = Literal["cpu", "cuda", "rocm"]
RunStatus = Literal["completed", "blocked", "failed"]
EvidenceClass = Literal["engineering_fixture", "gold"]
MediaOrigin = Literal[
    "camera_original",
    "licensed_stock",
    "published_dataset",
    "procedural",
]


class VOSDatasetEvidence(StrictEvaluationModel):
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


class VOSEvaluationItem(StrictEvaluationModel):
    item_id: str = Field(min_length=1)
    source_group_id: str = Field(min_length=1)
    scenario: VOSScenario
    media_origin: MediaOrigin
    media_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    annotation_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    frame_count: int = Field(gt=1)
    duration_seconds: float = Field(gt=0)
    object_count: int = Field(gt=0)


class VOSCompatibilityEvidence(StrictEvaluationModel):
    platform: PlatformId
    accelerator: AcceleratorId
    status: Literal["passed", "blocked", "failed"]
    report_sha256: str | None = Field(
        default=None,
        pattern=r"^[0-9a-f]{64}$",
    )
    blocker: str | None = None

    @model_validator(mode="after")
    def validate_status(self) -> VOSCompatibilityEvidence:
        if self.status == "passed":
            if self.report_sha256 is None or self.blocker is not None:
                raise ValueError(
                    "passed compatibility evidence requires a report and no blocker"
                )
        elif not self.blocker:
            raise ValueError("blocked/failed compatibility evidence requires a blocker")
        return self


class VOSModelArtifacts(StrictEvaluationModel):
    code_url: str | None = Field(default=None, pattern=r"^https://")
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
    weights_redistribution_allowed: bool | None = None
    checkpoint_sha256: str | None = Field(
        default=None,
        pattern=r"^[0-9a-f]{64}$",
    )
    license_review_sha256: str | None = Field(
        default=None,
        pattern=r"^[0-9a-f]{64}$",
    )
    semantic_anchor_initialization: bool
    reports_occlusion_or_uncertainty: bool
    maximum_objects: int | None = Field(default=None, gt=0)
    window_frames: int | None = Field(default=None, gt=0)
    compatibility: list[VOSCompatibilityEvidence] = Field(default_factory=list)


class VOSObservation(StrictEvaluationModel):
    item_id: str
    prediction_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    temporal_iou_sum: float = Field(ge=0)
    temporal_sample_count: int = Field(gt=0)
    boundary_f_sum: float = Field(ge=0)
    boundary_sample_count: int = Field(gt=0)
    normalized_drift_error_sum: float = Field(ge=0)
    drift_sample_count: int = Field(gt=0)
    lost_object_frames: int = Field(ge=0)
    object_frame_count: int = Field(gt=0)
    identity_switches: int = Field(ge=0)
    reappearance_events: int = Field(ge=0)
    reappearance_reacquired: int = Field(ge=0)
    elapsed_seconds: float = Field(gt=0)
    peak_cpu_memory_mb: float = Field(ge=0)
    peak_gpu_memory_mb: float = Field(ge=0)
    memory_growth_mb: float = Field(ge=0)

    @model_validator(mode="after")
    def validate_counts(self) -> VOSObservation:
        if self.temporal_iou_sum > self.temporal_sample_count:
            raise ValueError("temporal IoU sum exceeds normalized sample count")
        if self.boundary_f_sum > self.boundary_sample_count:
            raise ValueError("Boundary-F sum exceeds normalized sample count")
        if self.normalized_drift_error_sum > self.drift_sample_count:
            raise ValueError("drift error sum exceeds normalized sample count")
        if self.lost_object_frames > self.object_frame_count:
            raise ValueError("lost object frames exceed object-frame count")
        if self.reappearance_reacquired > self.reappearance_events:
            raise ValueError("reacquired events exceed reappearance events")
        return self


class VOSModelRun(StrictEvaluationModel):
    model_id: VOSModelId
    status: RunStatus
    artifacts: VOSModelArtifacts
    observations: list[VOSObservation] = Field(default_factory=list)
    blocker: str | None = None
    error: str | None = None

    @model_validator(mode="after")
    def validate_status(self) -> VOSModelRun:
        if self.status == "completed":
            if not self.observations:
                raise ValueError("completed VOS run requires observations")
            if self.blocker is not None or self.error is not None:
                raise ValueError("completed VOS run cannot carry blocker/error")
        elif self.status == "blocked":
            if not self.blocker:
                raise ValueError("blocked VOS run requires a blocker")
            if self.observations:
                raise ValueError("blocked VOS run cannot carry observations")
        else:
            if not self.error:
                raise ValueError("failed VOS run requires an error")
            if self.observations:
                raise ValueError("failed VOS run cannot carry observations")
        return self


class VOSShadowConfig(StrictEvaluationModel):
    minimum_temporal_iou_improvement: float = Field(
        default=0.02,
        ge=0,
        le=1,
    )
    minimum_boundary_f_improvement: float = Field(default=0.01, ge=0, le=1)
    maximum_scenario_temporal_regression: float = Field(
        default=0.02,
        ge=0,
        le=1,
    )
    maximum_drift_stability_regression: float = Field(
        default=0.01,
        ge=0,
        le=1,
    )
    maximum_lost_frame_rate_regression: float = Field(
        default=0.01,
        ge=0,
        le=1,
    )
    minimum_reappearance_recall: float = Field(default=0.8, ge=0, le=1)
    minimum_processing_fps: float = Field(default=1.0, gt=0)
    maximum_peak_gpu_memory_mb: float = Field(default=16_384, gt=0)
    maximum_memory_growth_mb: float = Field(default=1_024, ge=0)
    long_video_minimum_seconds: float = Field(default=120, gt=0)
    minimum_sam31_quality_gain_over_sam21: float = Field(
        default=0.03,
        ge=0,
        le=3,
    )


class VOSShadowBundle(StrictEvaluationModel):
    schema_version: str = VOS_SHADOW_VERSION
    created_at: datetime
    dataset: VOSDatasetEvidence
    config: VOSShadowConfig = Field(default_factory=VOSShadowConfig)
    items: list[VOSEvaluationItem] = Field(min_length=1)
    runs: list[VOSModelRun] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_bundle(self) -> VOSShadowBundle:
        item_ids = [item.item_id for item in self.items]
        if len(set(item_ids)) != len(item_ids):
            raise ValueError("VOS evaluation item IDs must be unique")
        model_ids = [run.model_id for run in self.runs]
        if len(set(model_ids)) != len(model_ids):
            raise ValueError("VOS model IDs must be unique")
        known_items = {item.item_id: item for item in self.items}
        for run in self.runs:
            observation_ids = [
                observation.item_id for observation in run.observations
            ]
            if len(set(observation_ids)) != len(observation_ids):
                raise ValueError(f"{run.model_id} observation IDs must be unique")
            unknown = set(observation_ids) - set(known_items)
            if unknown:
                raise ValueError(
                    f"{run.model_id} observations reference unknown items: "
                    f"{sorted(unknown)}"
                )
        return self


class VOSScenarioMetrics(StrictEvaluationModel):
    scenario: VOSScenario
    item_count: int = Field(gt=0)
    temporal_iou: float = Field(ge=0, le=1)
    boundary_f: float = Field(ge=0, le=1)
    drift_stability: float = Field(ge=0, le=1)
    lost_object_frame_rate: float = Field(ge=0, le=1)
    identity_switches: int = Field(ge=0)
    reappearance_recall: float | None = Field(default=None, ge=0, le=1)


class VOSModelReport(StrictEvaluationModel):
    model_id: VOSModelId
    status: RunStatus
    blocker: str | None
    error: str | None
    artifact_gate_passed: bool
    artifact_blockers: list[str]
    compatibility_matrix_documented: bool
    deployment_compatibility_passed: bool
    evaluated_items: int = Field(ge=0)
    scenario_metrics: dict[VOSScenario, VOSScenarioMetrics] = Field(
        default_factory=dict
    )
    temporal_iou: float | None = Field(default=None, ge=0, le=1)
    boundary_f: float | None = Field(default=None, ge=0, le=1)
    drift_stability: float | None = Field(default=None, ge=0, le=1)
    lost_object_frame_rate: float | None = Field(default=None, ge=0, le=1)
    identity_switches: int | None = Field(default=None, ge=0)
    reappearance_recall: float | None = Field(default=None, ge=0, le=1)
    processing_fps: float | None = Field(default=None, gt=0)
    peak_cpu_memory_mb: float | None = Field(default=None, ge=0)
    peak_gpu_memory_mb: float | None = Field(default=None, ge=0)
    maximum_memory_growth_mb: float | None = Field(default=None, ge=0)
    candidate_gate_passed: bool = False
    candidate_blockers: list[str] = Field(default_factory=list)


class VOSShadowReport(StrictEvaluationModel):
    schema_version: str = VOS_SHADOW_VERSION
    evaluator_version: str = VOS_SHADOW_VERSION
    created_at: datetime
    input_path: str
    input_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    status: Literal["complete", "partial"]
    release_status: Literal["shadow_only", "eligible_candidates"]
    dataset: VOSDatasetEvidence
    config: VOSShadowConfig
    reports: list[VOSModelReport]
    gates: dict[str, bool]
    missing_models: list[VOSModelId]
    eligible_candidates: list[VOSModelId]
    recommended_primary: Literal["sam21", "sam31"] | None
    recommended_vos_fallback: Literal["cutie"] | None
    recommended_flow_fallback: Literal["sea_raft"] | None
    notes: list[str] = Field(default_factory=list)


def _safe_ratio(
    numerator: int | float,
    denominator: int | float,
    *,
    empty_value: float = 0.0,
) -> float:
    return float(numerator / denominator) if denominator else empty_value


def _compatibility_matrix_documented(
    artifacts: VOSModelArtifacts,
) -> bool:
    platforms = {item.platform for item in artifacts.compatibility}
    accelerators = {item.accelerator for item in artifacts.compatibility}
    return (
        {"windows", "wsl2", "linux"} <= platforms
        and {"cuda", "rocm"} <= accelerators
    )


def _deployment_compatibility_passed(
    model_id: VOSModelId,
    artifacts: VOSModelArtifacts,
) -> bool:
    passed = [item for item in artifacts.compatibility if item.status == "passed"]
    if model_id == "sam31":
        return any(
            item.platform in {"wsl2", "linux"} and item.accelerator == "cuda"
            for item in passed
        )
    if model_id == "farneback":
        return any(item.accelerator == "cpu" for item in passed)
    return any(
        item.accelerator in {"cuda", "rocm"}
        and item.platform in {"windows", "wsl2", "linux"}
        for item in passed
    )


def _artifact_blockers(run: VOSModelRun) -> list[str]:
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
    if artifacts.license_review_sha256 is None:
        blockers.append("license_review_missing")
    if artifacts.weights_required:
        if artifacts.weights_url is None:
            blockers.append("weights_source_missing")
        if not artifacts.weights_license_id:
            blockers.append("weights_license_missing")
        if artifacts.weights_commercial_use_allowed is not True:
            blockers.append("weights_commercial_use_not_cleared")
        if artifacts.weights_redistribution_allowed is not True:
            blockers.append("weights_redistribution_not_cleared")
        if artifacts.checkpoint_sha256 is None:
            blockers.append("checkpoint_sha256_unfrozen")
    if (
        run.model_id in {"sam21", "sam31", "cutie"}
        and not artifacts.semantic_anchor_initialization
    ):
        blockers.append("semantic_anchor_initialization_missing")
    if run.model_id == "sam31":
        if artifacts.maximum_objects is None:
            blockers.append("maximum_objects_unbounded")
        if artifacts.window_frames is None:
            blockers.append("window_frames_unbounded")
    if run.model_id == "sea_raft" and not artifacts.reports_occlusion_or_uncertainty:
        blockers.append("occlusion_uncertainty_output_missing")
    if not _compatibility_matrix_documented(artifacts):
        blockers.append("platform_accelerator_matrix_incomplete")
    if not _deployment_compatibility_passed(run.model_id, artifacts):
        blockers.append("deployment_compatibility_not_passed")
    return sorted(set(blockers))


def _evaluate_observations(
    observations: list[VOSObservation],
    items: dict[str, VOSEvaluationItem],
) -> tuple[
    dict[VOSScenario, VOSScenarioMetrics],
    float,
    float,
    float,
    float,
    int,
    float | None,
    float,
    float,
    float,
    float,
]:
    totals: dict[VOSScenario, dict[str, int | float]] = {}
    total_frames = 0
    total_seconds = 0.0
    peak_cpu = 0.0
    peak_gpu = 0.0
    maximum_growth = 0.0
    for observation in observations:
        scenario = items[observation.item_id].scenario
        total = totals.setdefault(
            scenario,
            {
                "items": 0,
                "temporal_sum": 0.0,
                "temporal_count": 0,
                "boundary_sum": 0.0,
                "boundary_count": 0,
                "drift_sum": 0.0,
                "drift_count": 0,
                "lost": 0,
                "object_frames": 0,
                "identity_switches": 0,
                "reappearance_events": 0,
                "reappearance_reacquired": 0,
            },
        )
        total["items"] += 1
        total["temporal_sum"] += observation.temporal_iou_sum
        total["temporal_count"] += observation.temporal_sample_count
        total["boundary_sum"] += observation.boundary_f_sum
        total["boundary_count"] += observation.boundary_sample_count
        total["drift_sum"] += observation.normalized_drift_error_sum
        total["drift_count"] += observation.drift_sample_count
        total["lost"] += observation.lost_object_frames
        total["object_frames"] += observation.object_frame_count
        total["identity_switches"] += observation.identity_switches
        total["reappearance_events"] += observation.reappearance_events
        total["reappearance_reacquired"] += observation.reappearance_reacquired
        total_frames += items[observation.item_id].frame_count
        total_seconds += observation.elapsed_seconds
        peak_cpu = max(peak_cpu, observation.peak_cpu_memory_mb)
        peak_gpu = max(peak_gpu, observation.peak_gpu_memory_mb)
        maximum_growth = max(maximum_growth, observation.memory_growth_mb)

    scenario_metrics: dict[VOSScenario, VOSScenarioMetrics] = {}
    for scenario, total in sorted(totals.items()):
        temporal_iou = _safe_ratio(
            total["temporal_sum"],
            total["temporal_count"],
        )
        boundary_f = _safe_ratio(
            total["boundary_sum"],
            total["boundary_count"],
        )
        drift_error = _safe_ratio(total["drift_sum"], total["drift_count"])
        reappearance_recall = (
            _safe_ratio(
                total["reappearance_reacquired"],
                total["reappearance_events"],
            )
            if total["reappearance_events"]
            else None
        )
        scenario_metrics[scenario] = VOSScenarioMetrics(
            scenario=scenario,
            item_count=int(total["items"]),
            temporal_iou=temporal_iou,
            boundary_f=boundary_f,
            drift_stability=max(0.0, 1.0 - drift_error),
            lost_object_frame_rate=_safe_ratio(
                total["lost"],
                total["object_frames"],
            ),
            identity_switches=int(total["identity_switches"]),
            reappearance_recall=reappearance_recall,
        )

    values = list(scenario_metrics.values())
    reappearance_events = sum(
        int(total["reappearance_events"]) for total in totals.values()
    )
    reappearance_reacquired = sum(
        int(total["reappearance_reacquired"]) for total in totals.values()
    )
    return (
        scenario_metrics,
        sum(value.temporal_iou for value in values) / len(values),
        sum(value.boundary_f for value in values) / len(values),
        sum(value.drift_stability for value in values) / len(values),
        sum(value.lost_object_frame_rate for value in values) / len(values),
        sum(value.identity_switches for value in values),
        (
            reappearance_reacquired / reappearance_events
            if reappearance_events
            else None
        ),
        total_frames / total_seconds,
        peak_cpu,
        peak_gpu,
        maximum_growth,
    )


def _candidate_blockers(
    report: VOSModelReport,
    baseline: VOSModelReport | None,
    config: VOSShadowConfig,
) -> list[str]:
    if not report.scenario_metrics or baseline is None or not baseline.scenario_metrics:
        return ["candidate_or_baseline_metrics_missing"]
    blockers: list[str] = []
    if not report.artifact_gate_passed:
        blockers.append("artifact_gate_not_passed")
    if not baseline.artifact_gate_passed:
        blockers.append("baseline_artifact_gate_not_passed")
    for scenario in REQUIRED_VOS_SCENARIOS:
        candidate = report.scenario_metrics.get(scenario)
        current = baseline.scenario_metrics.get(scenario)
        if candidate is None or current is None:
            blockers.append(f"{scenario}_coverage_missing")
            continue
        if (
            candidate.temporal_iou
            + config.maximum_scenario_temporal_regression
            < current.temporal_iou
        ):
            blockers.append(f"{scenario}_temporal_iou_regressed")
    if (
        report.temporal_iou is None
        or baseline.temporal_iou is None
        or report.temporal_iou
        < baseline.temporal_iou + config.minimum_temporal_iou_improvement
    ):
        blockers.append("temporal_iou_improvement_not_met")
    if (
        report.boundary_f is None
        or baseline.boundary_f is None
        or report.boundary_f
        < baseline.boundary_f + config.minimum_boundary_f_improvement
    ):
        blockers.append("boundary_f_improvement_not_met")
    if (
        report.drift_stability is None
        or baseline.drift_stability is None
        or report.drift_stability
        + config.maximum_drift_stability_regression
        < baseline.drift_stability
    ):
        blockers.append("drift_stability_regressed")
    if (
        report.lost_object_frame_rate is None
        or baseline.lost_object_frame_rate is None
        or report.lost_object_frame_rate
        > baseline.lost_object_frame_rate
        + config.maximum_lost_frame_rate_regression
    ):
        blockers.append("lost_object_frame_rate_regressed")
    if (
        report.reappearance_recall is None
        or report.reappearance_recall < config.minimum_reappearance_recall
    ):
        blockers.append("reappearance_recall_below_minimum")
    if (
        report.processing_fps is None
        or report.processing_fps < config.minimum_processing_fps
    ):
        blockers.append("processing_fps_below_minimum")
    if (
        report.peak_gpu_memory_mb is None
        or report.peak_gpu_memory_mb > config.maximum_peak_gpu_memory_mb
    ):
        blockers.append("peak_gpu_memory_exceeded")
    if (
        report.maximum_memory_growth_mb is None
        or report.maximum_memory_growth_mb > config.maximum_memory_growth_mb
    ):
        blockers.append("memory_growth_exceeded")
    return sorted(set(blockers))


def _quality_score(report: VOSModelReport) -> float:
    return (
        float(report.temporal_iou or 0)
        + float(report.boundary_f or 0)
        + float(report.drift_stability or 0)
        - float(report.lost_object_frame_rate or 0)
    )


def evaluate_vos_shadow(
    bundle: VOSShadowBundle,
    *,
    input_path: str,
    input_sha256: str,
    created_at: datetime | None = None,
) -> VOSShadowReport:
    items = {item.item_id: item for item in bundle.items}
    run_by_model = {run.model_id: run for run in bundle.runs}
    missing_models = [
        model_id for model_id in REQUIRED_VOS_MODELS if model_id not in run_by_model
    ]
    model_reports: list[VOSModelReport] = []
    for model_id in REQUIRED_VOS_MODELS:
        run = run_by_model.get(model_id)
        if run is None:
            continue
        artifact_blockers = _artifact_blockers(run)
        report = VOSModelReport(
            model_id=model_id,
            status=run.status,
            blocker=run.blocker,
            error=run.error,
            artifact_gate_passed=not artifact_blockers,
            artifact_blockers=artifact_blockers,
            compatibility_matrix_documented=_compatibility_matrix_documented(
                run.artifacts
            ),
            deployment_compatibility_passed=_deployment_compatibility_passed(
                model_id,
                run.artifacts,
            ),
            evaluated_items=len(run.observations),
        )
        if run.status == "completed":
            (
                report.scenario_metrics,
                report.temporal_iou,
                report.boundary_f,
                report.drift_stability,
                report.lost_object_frame_rate,
                report.identity_switches,
                report.reappearance_recall,
                report.processing_fps,
                report.peak_cpu_memory_mb,
                report.peak_gpu_memory_mb,
                report.maximum_memory_growth_mb,
            ) = _evaluate_observations(run.observations, items)
        model_reports.append(report)

    report_by_model = {report.model_id: report for report in model_reports}
    baseline = report_by_model.get("farneback")
    for model_id in ("sam21", "sam31", "cutie", "sea_raft"):
        report = report_by_model.get(model_id)
        if report is None:
            continue
        blockers = _candidate_blockers(report, baseline, bundle.config)
        if model_id == "sam31":
            sam21_comparison = report_by_model.get("sam21")
            if sam21_comparison is None or not sam21_comparison.scenario_metrics:
                blockers.append("sam21_same_gold_comparison_missing")
            elif (
                _quality_score(report)
                < _quality_score(sam21_comparison)
                + bundle.config.minimum_sam31_quality_gain_over_sam21
            ):
                blockers.append("sam31_quality_gain_over_sam21_not_met")
            blockers = sorted(set(blockers))
        report.candidate_blockers = blockers
        report.candidate_gate_passed = not blockers

    scenarios = {item.scenario for item in bundle.items}
    required_scenario_coverage = set(REQUIRED_VOS_SCENARIOS) <= scenarios
    long_video_coverage = any(
        item.scenario == "long_drift"
        and item.duration_seconds >= bundle.config.long_video_minimum_seconds
        for item in bundle.items
    )
    dataset_is_gold = (
        bundle.dataset.evidence_class == "gold"
        and bundle.dataset.gold_manifest_sha256 is not None
        and bundle.dataset.gold_audit_report_sha256 is not None
        and bool(bundle.dataset.independent_reviewer_ids)
        and bundle.dataset.annotation_guideline_version != "unversioned"
        and all(item.media_origin != "procedural" for item in bundle.items)
    )
    model_rows_documented = not missing_models
    common_gates_passed = (
        dataset_is_gold
        and required_scenario_coverage
        and long_video_coverage
        and model_rows_documented
    )
    eligible = [
        report.model_id
        for report in model_reports
        if report.model_id != "farneback"
        and report.candidate_gate_passed
        and common_gates_passed
    ]

    sam21 = report_by_model.get("sam21")
    sam31 = report_by_model.get("sam31")
    recommended_primary: Literal["sam21", "sam31"] | None = None
    if "sam21" in eligible:
        recommended_primary = "sam21"
    if (
        "sam31" in eligible
        and sam31 is not None
        and sam21 is not None
        and sam21.scenario_metrics
        and _quality_score(sam31)
        >= _quality_score(sam21)
        + bundle.config.minimum_sam31_quality_gain_over_sam21
    ):
        recommended_primary = "sam31"
    recommended_vos_fallback = "cutie" if "cutie" in eligible else None
    recommended_flow_fallback = "sea_raft" if "sea_raft" in eligible else None
    release_allowed = bool(eligible)
    all_runs_completed = (
        model_rows_documented
        and all(
            run_by_model[model_id].status == "completed"
            and {item.item_id for item in bundle.items}
            == {
                observation.item_id
                for observation in run_by_model[model_id].observations
            }
            for model_id in REQUIRED_VOS_MODELS
        )
    )
    return VOSShadowReport(
        created_at=created_at or datetime.now(UTC),
        input_path=input_path,
        input_sha256=input_sha256,
        status="complete" if all_runs_completed else "partial",
        release_status="eligible_candidates" if release_allowed else "shadow_only",
        dataset=bundle.dataset,
        config=bundle.config,
        reports=model_reports,
        gates={
            "frozen_human_gold_test": dataset_is_gold,
            "required_scenario_coverage": required_scenario_coverage,
            "long_video_coverage": long_video_coverage,
            "required_model_rows_documented": model_rows_documented,
            "at_least_one_candidate_quality_license_runtime_gate": bool(eligible),
        },
        missing_models=missing_models,
        eligible_candidates=eligible,
        recommended_primary=recommended_primary,
        recommended_vos_fallback=recommended_vos_fallback,
        recommended_flow_fallback=recommended_flow_fallback,
        notes=[
            (
                "All candidates use the same frozen items for occlusion, reveal, "
                "long drift, anchor jumps, and disappearance/reappearance."
            ),
            (
                "SAM 3.1 can replace SAM 2.1 only after license/distribution, "
                "WSL2/Linux CUDA, bounded object/window, memory, and additional "
                "quality-gain gates pass."
            ),
            (
                "Cutie and SEA-RAFT are reported as VOS and flow fallbacks; paper "
                "benchmarks are not accepted as ColorGraph observations."
            ),
            (
                "Engineering fixtures remain shadow-only; recommendations require "
                "frozen, independently reviewed Gold evidence."
            ),
        ],
    )


def evaluate_vos_shadow_file(
    input_path: str | Path,
    output_path: str | Path,
) -> VOSShadowReport:
    source = Path(input_path).resolve()
    content = source.read_bytes()
    bundle = VOSShadowBundle.model_validate_json(content)
    report = evaluate_vos_shadow(
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
