from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from pydantic import Field, model_validator

from colorgraph.evaluation.models import StrictEvaluationModel

SEMANTIC_SHADOW_VERSION = "colorgraph.semantic-model-shadow-evaluation/v1"

SemanticModelId = Literal[
    "current_segformer_b0",
    "segformer_b5",
    "oneformer_ade20k_swin_large",
]
REQUIRED_SEMANTIC_MODELS: tuple[SemanticModelId, ...] = (
    "current_segformer_b0",
    "segformer_b5",
    "oneformer_ade20k_swin_large",
)
DEFAULT_KEY_CLASSES: tuple[str, ...] = ("water", "vegetation", "mountain")
MediaOrigin = Literal[
    "camera_original",
    "licensed_stock",
    "published_dataset",
    "procedural",
]
EvidenceClass = Literal["engineering_fixture", "gold"]
RunStatus = Literal["completed", "blocked", "failed"]


class SemanticDatasetEvidence(StrictEvaluationModel):
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


class SemanticEvaluationItem(StrictEvaluationModel):
    item_id: str = Field(min_length=1)
    source_group_id: str = Field(min_length=1)
    media_origin: MediaOrigin
    media_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    annotation_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    frame_count: int = Field(gt=1)
    width: int = Field(gt=0)
    height: int = Field(gt=0)
    annotated_classes: list[str] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_classes(self) -> SemanticEvaluationItem:
        if len(set(self.annotated_classes)) != len(self.annotated_classes):
            raise ValueError("semantic item classes must be unique")
        if any(not value.strip() for value in self.annotated_classes):
            raise ValueError("semantic item classes cannot be empty")
        return self


class SemanticModelArtifacts(StrictEvaluationModel):
    code_url: str | None = Field(default=None, pattern=r"^https://")
    code_license_id: str | None = None
    code_commercial_use_allowed: bool | None = None
    source_revision: str | None = Field(
        default=None,
        pattern=r"^[0-9a-f]{40}$",
    )
    weights_url: str | None = Field(default=None, pattern=r"^https://")
    weights_license_id: str | None = None
    weights_commercial_use_allowed: bool | None = None
    checkpoint_sha256: str | None = Field(
        default=None,
        pattern=r"^[0-9a-f]{64}$",
    )
    label_space: Literal["ade20k"]
    label_mapping_sha256: str | None = Field(
        default=None,
        pattern=r"^[0-9a-f]{64}$",
    )


class SemanticClassCounts(StrictEvaluationModel):
    class_name: str = Field(min_length=1)
    intersection_pixels: int = Field(ge=0)
    union_pixels: int = Field(ge=0)
    predicted_pixels: int = Field(ge=0)
    reference_pixels: int = Field(ge=0)
    matched_predicted_boundary_pixels: int = Field(ge=0)
    predicted_boundary_pixels: int = Field(ge=0)
    matched_reference_boundary_pixels: int = Field(ge=0)
    reference_boundary_pixels: int = Field(ge=0)
    temporal_absolute_error_sum: float = Field(ge=0)
    temporal_sample_count: int = Field(ge=0)

    @model_validator(mode="after")
    def validate_counts(self) -> SemanticClassCounts:
        if self.intersection_pixels > min(
            self.predicted_pixels,
            self.reference_pixels,
        ):
            raise ValueError("semantic intersection exceeds foreground counts")
        expected_union = (
            self.predicted_pixels
            + self.reference_pixels
            - self.intersection_pixels
        )
        if self.union_pixels != expected_union:
            raise ValueError("semantic union is inconsistent with foreground counts")
        if (
            self.matched_predicted_boundary_pixels
            > self.predicted_boundary_pixels
        ):
            raise ValueError("matched predicted boundary count exceeds predictions")
        if (
            self.matched_reference_boundary_pixels
            > self.reference_boundary_pixels
        ):
            raise ValueError("matched reference boundary count exceeds references")
        if self.temporal_absolute_error_sum > self.temporal_sample_count:
            raise ValueError("temporal absolute error exceeds normalized sample count")
        return self


class SemanticModelObservation(StrictEvaluationModel):
    item_id: str
    prediction_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    class_counts: list[SemanticClassCounts] = Field(min_length=1)
    frames_processed: int = Field(gt=0)
    elapsed_seconds: float = Field(gt=0)
    peak_cpu_memory_mb: float = Field(ge=0)
    peak_gpu_memory_mb: float = Field(ge=0)

    @model_validator(mode="after")
    def validate_classes(self) -> SemanticModelObservation:
        classes = [item.class_name for item in self.class_counts]
        if len(set(classes)) != len(classes):
            raise ValueError("semantic observation classes must be unique")
        return self


class SemanticModelRun(StrictEvaluationModel):
    model_id: SemanticModelId
    status: RunStatus
    artifacts: SemanticModelArtifacts
    operating_system: str = Field(min_length=1)
    runtime: str = Field(min_length=1)
    precision: str = Field(min_length=1)
    observations: list[SemanticModelObservation] = Field(default_factory=list)
    blocker: str | None = None
    error: str | None = None

    @model_validator(mode="after")
    def validate_status(self) -> SemanticModelRun:
        if self.status == "completed":
            if not self.observations:
                raise ValueError("completed semantic run requires observations")
            if self.blocker is not None or self.error is not None:
                raise ValueError("completed semantic run cannot carry blocker/error")
        elif self.status == "blocked":
            if not self.blocker:
                raise ValueError("blocked semantic run requires a blocker")
            if self.observations:
                raise ValueError("blocked semantic run cannot carry observations")
        else:
            if not self.error:
                raise ValueError("failed semantic run requires an error")
            if self.observations:
                raise ValueError("failed semantic run cannot carry observations")
        return self


class SemanticShadowConfig(StrictEvaluationModel):
    key_classes: list[str] = Field(
        default_factory=lambda: list(DEFAULT_KEY_CLASSES),
        min_length=1,
    )
    minimum_key_mean_iou_improvement: float = Field(
        default=0.02,
        ge=0,
        le=1,
    )
    minimum_key_mean_boundary_f_improvement: float = Field(
        default=0.01,
        ge=0,
        le=1,
    )
    maximum_per_class_regression: float = Field(default=0.01, ge=0, le=1)
    maximum_temporal_stability_regression: float = Field(
        default=0.01,
        ge=0,
        le=1,
    )
    minimum_processing_fps: float = Field(default=1.0, gt=0)
    maximum_peak_gpu_memory_mb: float = Field(default=16_384, gt=0)
    minimum_oneformer_quality_gain_over_b5: float = Field(
        default=0.02,
        ge=0,
        le=3,
    )

    @model_validator(mode="after")
    def validate_key_classes(self) -> SemanticShadowConfig:
        if len(set(self.key_classes)) != len(self.key_classes):
            raise ValueError("semantic key classes must be unique")
        return self


class SemanticShadowBundle(StrictEvaluationModel):
    schema_version: str = SEMANTIC_SHADOW_VERSION
    created_at: datetime
    dataset: SemanticDatasetEvidence
    config: SemanticShadowConfig = Field(default_factory=SemanticShadowConfig)
    items: list[SemanticEvaluationItem] = Field(min_length=1)
    runs: list[SemanticModelRun] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_bundle(self) -> SemanticShadowBundle:
        item_ids = [item.item_id for item in self.items]
        if len(set(item_ids)) != len(item_ids):
            raise ValueError("semantic evaluation item IDs must be unique")
        model_ids = [run.model_id for run in self.runs]
        if len(set(model_ids)) != len(model_ids):
            raise ValueError("semantic model IDs must be unique")
        known_items = {item.item_id: item for item in self.items}
        annotated_classes = {
            class_name
            for item in self.items
            for class_name in item.annotated_classes
        }
        missing_key_classes = set(self.config.key_classes) - annotated_classes
        if missing_key_classes:
            raise ValueError(
                "semantic key classes are absent from frozen annotations: "
                f"{sorted(missing_key_classes)}"
            )
        for run in self.runs:
            observation_ids = [
                observation.item_id for observation in run.observations
            ]
            if len(set(observation_ids)) != len(observation_ids):
                raise ValueError(
                    f"{run.model_id} observation item IDs must be unique"
                )
            unknown = set(observation_ids) - set(known_items)
            if unknown:
                raise ValueError(
                    f"{run.model_id} observations reference unknown items: "
                    f"{sorted(unknown)}"
                )
            for observation in run.observations:
                item = known_items[observation.item_id]
                observed_classes = {
                    value.class_name for value in observation.class_counts
                }
                if observed_classes != set(item.annotated_classes):
                    raise ValueError(
                        f"{run.model_id}/{item.item_id} classes do not match "
                        "the frozen annotations"
                    )
                if observation.frames_processed != item.frame_count:
                    raise ValueError(
                        f"{run.model_id}/{item.item_id} frame coverage is incomplete"
                    )
        return self


class SemanticClassMetrics(StrictEvaluationModel):
    class_name: str
    reference_pixels: int = Field(ge=0)
    reference_boundary_pixels: int = Field(ge=0)
    temporal_sample_count: int = Field(ge=0)
    iou: float = Field(ge=0, le=1)
    dice: float = Field(ge=0, le=1)
    boundary_precision: float = Field(ge=0, le=1)
    boundary_recall: float = Field(ge=0, le=1)
    boundary_f: float = Field(ge=0, le=1)
    temporal_mean_absolute_error: float = Field(ge=0, le=1)
    temporal_stability: float = Field(ge=0, le=1)


class SemanticModelReport(StrictEvaluationModel):
    model_id: SemanticModelId
    status: RunStatus
    blocker: str | None
    error: str | None
    artifact_gate_passed: bool
    artifact_blockers: list[str]
    evaluated_items: int = Field(ge=0)
    class_metrics: dict[str, SemanticClassMetrics] = Field(default_factory=dict)
    macro_iou: float | None = Field(default=None, ge=0, le=1)
    macro_boundary_f: float | None = Field(default=None, ge=0, le=1)
    key_mean_iou: float | None = Field(default=None, ge=0, le=1)
    key_min_iou: float | None = Field(default=None, ge=0, le=1)
    key_mean_boundary_f: float | None = Field(default=None, ge=0, le=1)
    key_min_boundary_f: float | None = Field(default=None, ge=0, le=1)
    key_mean_temporal_stability: float | None = Field(default=None, ge=0, le=1)
    processing_fps: float | None = Field(default=None, gt=0)
    peak_cpu_memory_mb: float | None = Field(default=None, ge=0)
    peak_gpu_memory_mb: float | None = Field(default=None, ge=0)
    candidate_quality_gate_passed: bool = False
    candidate_quality_blockers: list[str] = Field(default_factory=list)


class SemanticShadowReport(StrictEvaluationModel):
    schema_version: str = SEMANTIC_SHADOW_VERSION
    evaluator_version: str = SEMANTIC_SHADOW_VERSION
    created_at: datetime
    input_path: str
    input_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    status: Literal["complete", "partial"]
    release_status: Literal["shadow_only", "eligible_default_candidate"]
    recommended_candidate: Literal[
        "segformer_b5",
        "oneformer_ade20k_swin_large",
    ] | None
    dataset: SemanticDatasetEvidence
    config: SemanticShadowConfig
    reports: list[SemanticModelReport]
    gates: dict[str, bool]
    missing_models: list[SemanticModelId]
    notes: list[str] = Field(default_factory=list)


def _safe_ratio(
    numerator: int | float,
    denominator: int | float,
    *,
    empty_value: float = 0.0,
) -> float:
    return float(numerator / denominator) if denominator else empty_value


def _artifact_blockers(run: SemanticModelRun) -> list[str]:
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
    if artifacts.weights_url is None:
        blockers.append("weights_source_missing")
    if not artifacts.weights_license_id:
        blockers.append("weights_license_missing")
    if artifacts.weights_commercial_use_allowed is not True:
        blockers.append("weights_commercial_use_not_cleared")
    if artifacts.checkpoint_sha256 is None:
        blockers.append("checkpoint_sha256_unfrozen")
    if artifacts.label_mapping_sha256 is None:
        blockers.append("label_mapping_sha256_missing")
    return sorted(set(blockers))


def _evaluate_observations(
    observations: list[SemanticModelObservation],
    *,
    key_classes: list[str],
) -> tuple[
    dict[str, SemanticClassMetrics],
    float,
    float,
    float,
    float,
    float,
    float,
    float,
    float,
    float,
]:
    totals: dict[str, dict[str, int | float]] = {}
    total_frames = 0
    total_seconds = 0.0
    peak_cpu = 0.0
    peak_gpu = 0.0
    for observation in observations:
        total_frames += observation.frames_processed
        total_seconds += observation.elapsed_seconds
        peak_cpu = max(peak_cpu, observation.peak_cpu_memory_mb)
        peak_gpu = max(peak_gpu, observation.peak_gpu_memory_mb)
        for counts in observation.class_counts:
            total = totals.setdefault(
                counts.class_name,
                {
                    "intersection": 0,
                    "union": 0,
                    "predicted": 0,
                    "reference": 0,
                    "matched_predicted_boundary": 0,
                    "predicted_boundary": 0,
                    "matched_reference_boundary": 0,
                    "reference_boundary": 0,
                    "temporal_error": 0.0,
                    "temporal_samples": 0,
                },
            )
            total["intersection"] += counts.intersection_pixels
            total["union"] += counts.union_pixels
            total["predicted"] += counts.predicted_pixels
            total["reference"] += counts.reference_pixels
            total[
                "matched_predicted_boundary"
            ] += counts.matched_predicted_boundary_pixels
            total["predicted_boundary"] += counts.predicted_boundary_pixels
            total[
                "matched_reference_boundary"
            ] += counts.matched_reference_boundary_pixels
            total["reference_boundary"] += counts.reference_boundary_pixels
            total["temporal_error"] += counts.temporal_absolute_error_sum
            total["temporal_samples"] += counts.temporal_sample_count

    class_metrics: dict[str, SemanticClassMetrics] = {}
    for class_name, total in sorted(totals.items()):
        iou = _safe_ratio(
            total["intersection"],
            total["union"],
            empty_value=1.0,
        )
        dice = _safe_ratio(
            2 * total["intersection"],
            total["predicted"] + total["reference"],
            empty_value=1.0,
        )
        boundary_precision = _safe_ratio(
            total["matched_predicted_boundary"],
            total["predicted_boundary"],
            empty_value=1.0,
        )
        boundary_recall = _safe_ratio(
            total["matched_reference_boundary"],
            total["reference_boundary"],
            empty_value=1.0,
        )
        boundary_f = _safe_ratio(
            2 * boundary_precision * boundary_recall,
            boundary_precision + boundary_recall,
            empty_value=1.0,
        )
        temporal_error = _safe_ratio(
            total["temporal_error"],
            total["temporal_samples"],
        )
        class_metrics[class_name] = SemanticClassMetrics(
            class_name=class_name,
            reference_pixels=int(total["reference"]),
            reference_boundary_pixels=int(total["reference_boundary"]),
            temporal_sample_count=int(total["temporal_samples"]),
            iou=iou,
            dice=dice,
            boundary_precision=boundary_precision,
            boundary_recall=boundary_recall,
            boundary_f=boundary_f,
            temporal_mean_absolute_error=temporal_error,
            temporal_stability=max(0.0, 1.0 - temporal_error),
        )

    values = list(class_metrics.values())
    key_values = [
        class_metrics[class_name]
        for class_name in key_classes
        if class_name in class_metrics
    ]
    macro_iou = sum(value.iou for value in values) / len(values)
    macro_boundary = sum(value.boundary_f for value in values) / len(values)
    key_mean_iou = sum(value.iou for value in key_values) / len(key_values)
    key_min_iou = min(value.iou for value in key_values)
    key_mean_boundary = (
        sum(value.boundary_f for value in key_values) / len(key_values)
    )
    key_min_boundary = min(value.boundary_f for value in key_values)
    key_temporal = (
        sum(value.temporal_stability for value in key_values) / len(key_values)
    )
    return (
        class_metrics,
        macro_iou,
        macro_boundary,
        key_mean_iou,
        key_min_iou,
        key_mean_boundary,
        key_min_boundary,
        key_temporal,
        total_frames / total_seconds,
        peak_cpu,
        peak_gpu,
    )


def _candidate_quality_blockers(
    report: SemanticModelReport,
    baseline: SemanticModelReport | None,
    config: SemanticShadowConfig,
) -> list[str]:
    if not report.class_metrics or baseline is None or not baseline.class_metrics:
        return ["candidate_or_baseline_metrics_missing"]
    blockers: list[str] = []
    if not report.artifact_gate_passed:
        blockers.append("artifact_gate_not_passed")
    for class_name in config.key_classes:
        candidate = report.class_metrics.get(class_name)
        current = baseline.class_metrics.get(class_name)
        if candidate is None or current is None:
            blockers.append(f"{class_name}_coverage_missing")
            continue
        if (
            candidate.reference_pixels <= 0
            or candidate.reference_boundary_pixels <= 0
            or candidate.temporal_sample_count <= 0
        ):
            blockers.append(f"{class_name}_gold_signal_missing")
        if candidate.iou + config.maximum_per_class_regression < current.iou:
            blockers.append(f"{class_name}_iou_regressed")
        if (
            candidate.boundary_f + config.maximum_per_class_regression
            < current.boundary_f
        ):
            blockers.append(f"{class_name}_boundary_f_regressed")
    if (
        report.key_mean_iou is None
        or baseline.key_mean_iou is None
        or report.key_mean_iou
        < baseline.key_mean_iou + config.minimum_key_mean_iou_improvement
    ):
        blockers.append("key_mean_iou_improvement_not_met")
    if (
        report.key_mean_boundary_f is None
        or baseline.key_mean_boundary_f is None
        or report.key_mean_boundary_f
        < baseline.key_mean_boundary_f
        + config.minimum_key_mean_boundary_f_improvement
    ):
        blockers.append("key_mean_boundary_f_improvement_not_met")
    if (
        report.key_mean_temporal_stability is None
        or baseline.key_mean_temporal_stability is None
        or report.key_mean_temporal_stability
        + config.maximum_temporal_stability_regression
        < baseline.key_mean_temporal_stability
    ):
        blockers.append("temporal_stability_regressed")
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
    return sorted(set(blockers))


def _quality_score(report: SemanticModelReport) -> float:
    return (
        float(report.key_mean_iou or 0)
        + float(report.key_mean_boundary_f or 0)
        + float(report.key_mean_temporal_stability or 0)
    )


def evaluate_semantic_shadow(
    bundle: SemanticShadowBundle,
    *,
    input_path: str,
    input_sha256: str,
    created_at: datetime | None = None,
) -> SemanticShadowReport:
    item_ids = {item.item_id for item in bundle.items}
    run_by_model = {run.model_id: run for run in bundle.runs}
    missing_models = [
        model_id
        for model_id in REQUIRED_SEMANTIC_MODELS
        if model_id not in run_by_model
    ]
    model_reports: list[SemanticModelReport] = []
    for model_id in REQUIRED_SEMANTIC_MODELS:
        run = run_by_model.get(model_id)
        if run is None:
            continue
        artifact_blockers = _artifact_blockers(run)
        report = SemanticModelReport(
            model_id=model_id,
            status=run.status,
            blocker=run.blocker,
            error=run.error,
            artifact_gate_passed=not artifact_blockers,
            artifact_blockers=artifact_blockers,
            evaluated_items=len(run.observations),
        )
        if run.status == "completed":
            (
                report.class_metrics,
                report.macro_iou,
                report.macro_boundary_f,
                report.key_mean_iou,
                report.key_min_iou,
                report.key_mean_boundary_f,
                report.key_min_boundary_f,
                report.key_mean_temporal_stability,
                report.processing_fps,
                report.peak_cpu_memory_mb,
                report.peak_gpu_memory_mb,
            ) = _evaluate_observations(
                run.observations,
                key_classes=bundle.config.key_classes,
            )
        model_reports.append(report)

    report_by_model = {report.model_id: report for report in model_reports}
    baseline = report_by_model.get("current_segformer_b0")
    for model_id in ("segformer_b5", "oneformer_ade20k_swin_large"):
        report = report_by_model.get(model_id)
        if report is None:
            continue
        blockers = _candidate_quality_blockers(report, baseline, bundle.config)
        report.candidate_quality_blockers = blockers
        report.candidate_quality_gate_passed = not blockers

    full_matrix_completed = (
        not missing_models
        and all(
            run_by_model[model_id].status == "completed"
            and {observation.item_id for observation in run_by_model[model_id].observations}
            == item_ids
            for model_id in REQUIRED_SEMANTIC_MODELS
        )
    )
    dataset_is_gold = (
        bundle.dataset.evidence_class == "gold"
        and bundle.dataset.gold_manifest_sha256 is not None
        and bundle.dataset.gold_audit_report_sha256 is not None
        and bool(bundle.dataset.independent_reviewer_ids)
        and bundle.dataset.annotation_guideline_version != "unversioned"
        and all(item.media_origin != "procedural" for item in bundle.items)
    )
    required_key_class_coverage = (
        baseline is not None
        and all(
            class_name in baseline.class_metrics
            and baseline.class_metrics[class_name].reference_pixels > 0
            and baseline.class_metrics[class_name].reference_boundary_pixels > 0
            and baseline.class_metrics[class_name].temporal_sample_count > 0
            for class_name in bundle.config.key_classes
        )
    )
    artifacts_frozen_and_licensed = (
        full_matrix_completed
        and all(report.artifact_gate_passed for report in model_reports)
    )
    eligible = {
        report.model_id: report
        for report in model_reports
        if report.model_id != "current_segformer_b0"
        and report.candidate_quality_gate_passed
    }
    candidate: Literal[
        "segformer_b5",
        "oneformer_ade20k_swin_large",
    ] | None = None
    b5 = eligible.get("segformer_b5")
    oneformer = eligible.get("oneformer_ade20k_swin_large")
    if b5 is not None and oneformer is not None:
        candidate = (
            "oneformer_ade20k_swin_large"
            if _quality_score(oneformer)
            >= _quality_score(b5)
            + bundle.config.minimum_oneformer_quality_gain_over_b5
            else "segformer_b5"
        )
    elif b5 is not None:
        candidate = "segformer_b5"
    elif oneformer is not None:
        candidate = "oneformer_ade20k_swin_large"

    gates = {
        "frozen_human_gold_test": dataset_is_gold,
        "required_key_class_coverage": required_key_class_coverage,
        "required_model_matrix_completed": full_matrix_completed,
        "artifacts_frozen_and_commercially_cleared": (
            artifacts_frozen_and_licensed
        ),
        "candidate_key_class_quality_and_runtime": candidate is not None,
    }
    release_allowed = all(gates.values())
    return SemanticShadowReport(
        created_at=created_at or datetime.now(UTC),
        input_path=input_path,
        input_sha256=input_sha256,
        status="complete" if full_matrix_completed else "partial",
        release_status=(
            "eligible_default_candidate" if release_allowed else "shadow_only"
        ),
        recommended_candidate=candidate if release_allowed else None,
        dataset=bundle.dataset,
        config=bundle.config,
        reports=model_reports,
        gates=gates,
        missing_models=missing_models,
        notes=[
            (
                "The candidate gate uses water/vegetation/mountain class metrics; "
                "macro averages cannot hide a key-class regression."
            ),
            (
                "SegFormer-B5 is the lower-migration preference unless OneFormer "
                "clears the configured additional quality margin."
            ),
            (
                "A complete engineering fixture remains shadow-only; only frozen, "
                "independently reviewed Gold evidence can authorize a default model."
            ),
            "Public-paper metrics are not accepted as ColorGraph observations.",
        ],
    )


def evaluate_semantic_shadow_file(
    input_path: str | Path,
    output_path: str | Path,
) -> SemanticShadowReport:
    source = Path(input_path).resolve()
    content = source.read_bytes()
    bundle = SemanticShadowBundle.model_validate_json(content)
    report = evaluate_semantic_shadow(
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
