from __future__ import annotations

import hashlib
import json
import platform
import sys
from pathlib import Path
from typing import Any

import numpy as np
import torch

from colorgraph.evaluation.manifest import (
    LANDSCAPE_ACCEPTANCE_ANNOTATION_VERSION,
    LANDSCAPE_P0_AUDIT_PROFILE,
    DatasetSplit,
    EvaluationTask,
    GoldSetAuditProfile,
    GoldSetAuditReport,
    GoldSetManifest,
    audit_gold_set,
    load_gold_set_manifest,
    qualified_human_gold_items,
    validate_gold_set_files,
)
from colorgraph.evaluation.metrics import (
    banding_metrics,
    boundary_f1,
    boundary_f_score,
    classification_metrics,
    color_balance_acceptance_metrics,
    color_sweep_metrics,
    delta_e_itp,
    depth_temporal_scale_consistency,
    fleiss_kappa,
    gray_axis_metrics,
    interval_iou,
    mask_overlap_metrics,
    motion_compensated_temporal_stability,
    paired_cluster_bootstrap_difference,
    pairwise_ranking_metrics,
    percentile_latency,
    repair_acceptance_metrics,
    signal_range_metrics,
)
from colorgraph.evaluation.models import (
    EvaluatedMaterial,
    EvaluationReport,
    GoldEvaluationEvidence,
    GoldGatePolicy,
    GoldGateRule,
    HardwareSnapshot,
)
from colorgraph.evaluation.preference import (
    PairwisePreferenceRecord,
    PreferenceTrainingConfig,
    train_bradley_terry_preference,
)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _hardware_snapshot() -> HardwareSnapshot:
    accelerator_available = torch.cuda.is_available()
    runtime = (
        "rocm"
        if accelerator_available and torch.version.hip
        else ("cuda" if accelerator_available else "cpu")
    )
    if accelerator_available:
        properties = torch.cuda.get_device_properties(0)
        device_name = properties.name
        memory_mb = round(properties.total_memory / 1024**2)
    else:
        device_name = platform.processor() or "CPU"
        memory_mb = None
    return HardwareSnapshot(
        operating_system=platform.platform(),
        python_version=sys.version.split()[0],
        torch_version=torch.__version__,
        runtime=runtime,
        device_name=device_name,
        device_memory_mb=memory_mb,
    )


def _as_intervals(values: list[list[int]]) -> list[tuple[int, int]]:
    intervals: list[tuple[int, int]] = []
    for value in values:
        if len(value) != 2 or value[1] < value[0]:
            raise ValueError(f"invalid transition interval: {value!r}")
        intervals.append((int(value[0]), int(value[1])))
    return intervals


def _bootstrap_configuration(section: dict[str, Any]) -> tuple[int, int]:
    samples = int(section.get("bootstrap_samples", 1000))
    seed = int(section.get("bootstrap_seed", 20260730))
    if samples < 20:
        raise ValueError("bootstrap_samples must be at least 20")
    return samples, seed


def _required_boolean(
    item: dict[str, Any],
    key: str,
    *,
    section: str,
) -> bool:
    value = item.get(key)
    if not isinstance(value, bool):
        raise ValueError(f"{section}.{key} must be a JSON boolean")
    return value


def _comparison_summary(
    candidate: list[float],
    baseline: list[float],
    source_group_ids: list[str],
    *,
    prefix: str,
    bootstrap_samples: int,
    bootstrap_seed: int,
) -> dict[str, float]:
    comparison = paired_cluster_bootstrap_difference(
        candidate,
        baseline,
        source_group_ids,
        bootstrap_samples=bootstrap_samples,
        bootstrap_seed=bootstrap_seed,
    )
    return {
        f"candidate_{prefix}": float(np.mean(candidate)),
        f"baseline_{prefix}": float(np.mean(baseline)),
        f"{prefix}_improvement": comparison["mean_difference"],
        f"{prefix}_improvement_ci95_low": comparison[
            "difference_ci95_low"
        ],
        f"{prefix}_improvement_ci95_high": comparison[
            "difference_ci95_high"
        ],
    }


def _analysis_acceptance_metrics(section: dict[str, Any]) -> dict[str, float]:
    return color_balance_acceptance_metrics(
        candidate_exposure_ev=section["candidate_exposure_ev"],
        baseline_exposure_ev=section["baseline_exposure_ev"],
        reference_exposure_ev=section["reference_exposure_ev"],
        candidate_temperature_kelvin=section[
            "candidate_temperature_kelvin"
        ],
        baseline_temperature_kelvin=section[
            "baseline_temperature_kelvin"
        ],
        reference_temperature_kelvin=section[
            "reference_temperature_kelvin"
        ],
        candidate_clipping_ratio=section["candidate_clipping_ratio"],
        baseline_clipping_ratio=section["baseline_clipping_ratio"],
        candidate_tint=section.get("candidate_tint"),
        baseline_tint=section.get("baseline_tint"),
        reference_tint=section.get("reference_tint"),
        cut_after_samples=section.get("cut_after_samples", []),
    )


def _representative_acceptance_metrics(
    section: dict[str, Any],
) -> dict[str, float]:
    items = section.get("items")
    if not isinstance(items, list) or not items:
        raise ValueError("representative.items must be a non-empty list")
    samples, seed = _bootstrap_configuration(section)
    tolerance = int(section.get("tolerance_frames", 1))
    candidate_usable: list[float] = []
    baseline_usable: list[float] = []
    candidate_scene_f1: list[float] = []
    baseline_scene_f1: list[float] = []
    source_group_ids: list[str] = []
    for item in items:
        if not isinstance(item, dict):
            raise ValueError("representative items must be objects")
        source_group_id = str(item.get("source_group_id", "")).strip()
        if not source_group_id:
            raise ValueError(
                "representative items require source_group_id"
            )
        source_group_ids.append(source_group_id)
        candidate_usable.append(
            float(
                _required_boolean(
                    item,
                    "candidate_usable",
                    section="representative",
                )
            )
        )
        baseline_usable.append(
            float(
                _required_boolean(
                    item,
                    "baseline_usable",
                    section="representative",
                )
            )
        )
        reference_boundaries = item["reference_scene_boundaries"]
        candidate_scene_f1.append(
            boundary_f1(
                item["candidate_scene_boundaries"],
                reference_boundaries,
                tolerance_frames=tolerance,
            )["f1"]
        )
        baseline_scene_f1.append(
            boundary_f1(
                item["baseline_scene_boundaries"],
                reference_boundaries,
                tolerance_frames=tolerance,
            )["f1"]
        )
    metrics = {
        "items": float(len(items)),
        "source_groups": float(len(set(source_group_ids))),
        "bootstrap_samples": float(samples),
    }
    metrics.update(
        _comparison_summary(
            candidate_usable,
            baseline_usable,
            source_group_ids,
            prefix="usable_rate",
            bootstrap_samples=samples,
            bootstrap_seed=seed,
        )
    )
    metrics.update(
        _comparison_summary(
            candidate_scene_f1,
            baseline_scene_f1,
            source_group_ids,
            prefix="downstream_scene_boundary_f1",
            bootstrap_samples=samples,
            bootstrap_seed=seed + 1,
        )
    )
    return metrics


def _scene_acceptance_metrics(section: dict[str, Any]) -> dict[str, float]:
    items = section.get("items")
    if not isinstance(items, list) or not items:
        raise ValueError("scene.items must be a non-empty list")
    samples, seed = _bootstrap_configuration(section)
    tolerance = int(section.get("tolerance_frames", 1))
    candidate_boundary_f1: list[float] = []
    baseline_boundary_f1: list[float] = []
    candidate_label_f1: list[float] = []
    baseline_label_f1: list[float] = []
    candidate_unknown_rate: list[float] = []
    baseline_unknown_rate: list[float] = []
    source_group_ids: list[str] = []
    for item in items:
        if not isinstance(item, dict):
            raise ValueError("scene items must be objects")
        source_group_id = str(item.get("source_group_id", "")).strip()
        if not source_group_id:
            raise ValueError("scene items require source_group_id")
        source_group_ids.append(source_group_id)
        reference_boundaries = item["reference_boundaries"]
        candidate_boundary_f1.append(
            boundary_f1(
                item["candidate_boundaries"],
                reference_boundaries,
                tolerance_frames=tolerance,
            )["f1"]
        )
        baseline_boundary_f1.append(
            boundary_f1(
                item["baseline_boundaries"],
                reference_boundaries,
                tolerance_frames=tolerance,
            )["f1"]
        )
        candidate_labels = classification_metrics(
            item["candidate_labels"],
            item["reference_labels"],
        )
        baseline_labels = classification_metrics(
            item["baseline_labels"],
            item["reference_labels"],
        )
        candidate_label_f1.append(candidate_labels["macro_f1"])
        baseline_label_f1.append(baseline_labels["macro_f1"])
        candidate_unknown_rate.append(candidate_labels["unknown_rate"])
        baseline_unknown_rate.append(baseline_labels["unknown_rate"])
    metrics = {
        "items": float(len(items)),
        "source_groups": float(len(set(source_group_ids))),
        "bootstrap_samples": float(samples),
        "candidate_unknown_rate": float(np.mean(candidate_unknown_rate)),
        "baseline_unknown_rate": float(np.mean(baseline_unknown_rate)),
    }
    metrics.update(
        _comparison_summary(
            candidate_boundary_f1,
            baseline_boundary_f1,
            source_group_ids,
            prefix="boundary_f1_macro",
            bootstrap_samples=samples,
            bootstrap_seed=seed,
        )
    )
    metrics.update(
        _comparison_summary(
            candidate_label_f1,
            baseline_label_f1,
            source_group_ids,
            prefix="label_macro_f1",
            bootstrap_samples=samples,
            bootstrap_seed=seed + 1,
        )
    )
    return metrics


def _repair_acceptance_metrics(section: dict[str, Any]) -> dict[str, float]:
    items = section.get("items")
    if not isinstance(items, list) or not items:
        raise ValueError("repair.items must be a non-empty list")
    if any(not isinstance(item, dict) for item in items):
        raise ValueError("repair items must be objects")
    samples, seed = _bootstrap_configuration(section)
    return repair_acceptance_metrics(
        should_accept=[
            _required_boolean(item, "should_accept", section="repair")
            for item in items
        ],
        accepted=[
            _required_boolean(item, "accepted", section="repair")
            for item in items
        ],
        objectives_passed=[
            _required_boolean(
                item,
                "objectives_passed",
                section="repair",
            )
            for item in items
        ],
        hard_safe=[
            _required_boolean(item, "hard_safe", section="repair")
            for item in items
        ],
        side_effect_safe=[
            _required_boolean(
                item,
                "side_effect_safe",
                section="repair",
            )
            for item in items
        ],
        intent_drift_within_limit=[
            _required_boolean(
                item,
                "intent_drift_within_limit",
                section="repair",
            )
            for item in items
        ],
        objective_improvement=[
            float(item["objective_improvement"]) for item in items
        ],
        intent_drift=[float(item["intent_drift"]) for item in items],
        source_group_ids=[
            str(item["source_group_id"]) for item in items
        ],
        bootstrap_samples=samples,
        bootstrap_seed=seed,
    )


def _evaluate_sections(observations: dict[str, Any]) -> dict[str, dict[str, float]]:
    metrics: dict[str, dict[str, float]] = {}

    analysis = observations.get("analysis")
    if isinstance(analysis, dict):
        metrics["analysis"] = _analysis_acceptance_metrics(analysis)

    representative = observations.get("representative")
    if isinstance(representative, dict):
        metrics["representative"] = _representative_acceptance_metrics(
            representative
        )

    shot = observations.get("shot")
    if isinstance(shot, dict):
        section = {
            f"boundary_{key}": value
            for key, value in boundary_f1(
                shot["predicted_boundaries"],
                shot["reference_boundaries"],
                tolerance_frames=int(shot.get("tolerance_frames", 1)),
            ).items()
        }
        section.update(
            {
                f"transition_{key}": value
                for key, value in interval_iou(
                    _as_intervals(shot.get("predicted_transitions", [])),
                    _as_intervals(shot.get("reference_transitions", [])),
                ).items()
            }
        )
        metrics["shot"] = section

    scene = observations.get("scene")
    if isinstance(scene, dict):
        if "items" in scene:
            section = _scene_acceptance_metrics(scene)
        else:
            section = {
                f"boundary_{key}": value
                for key, value in boundary_f1(
                    scene["predicted_boundaries"],
                    scene["reference_boundaries"],
                    tolerance_frames=int(scene.get("tolerance_frames", 1)),
                ).items()
            }
            section.update(
                classification_metrics(
                    scene["predicted_labels"],
                    scene["reference_labels"],
                )
            )
        metrics["scene"] = section

    mask = observations.get("mask")
    if isinstance(mask, dict):
        class_metrics: list[dict[str, float]] = []
        for class_name, values in sorted(mask.get("classes", {}).items()):
            overlap = mask_overlap_metrics(
                np.asarray(values["predicted"]),
                np.asarray(values["reference"]),
            )
            overlap["boundary_f_score"] = boundary_f_score(
                np.asarray(values["predicted"]),
                np.asarray(values["reference"]),
                tolerance_pixels=int(values.get("boundary_tolerance_pixels", 2)),
            )
            metrics[f"mask.{class_name}"] = overlap
            class_metrics.append(overlap)
        aggregate: dict[str, float] = {}
        for key in ("iou", "dice", "boundary_f_score"):
            aggregate[f"macro_{key}"] = (
                float(np.mean([item[key] for item in class_metrics]))
                if class_metrics
                else 0.0
            )
        temporal = mask.get("temporal")
        if isinstance(temporal, dict):
            aggregate.update(
                motion_compensated_temporal_stability(
                    np.asarray(temporal["masks"]),
                    np.asarray(temporal["backward_flows"]),
                    cut_after_frames=temporal.get("cut_after_frames", []),
                )
            )
        metrics["mask"] = aggregate

    depth = observations.get("depth")
    if isinstance(depth, dict):
        metrics["depth"] = depth_temporal_scale_consistency(
            np.asarray(depth["frames"])
        )

    color = observations.get("color")
    if isinstance(color, dict):
        section = color_sweep_metrics(
            np.asarray(color["predicted_lab"]),
            np.asarray(color["reference_lab"]),
        )
        section.update(gray_axis_metrics(np.asarray(color["gray_lab"])))
        if "predicted_ictcp" in color and "reference_ictcp" in color:
            delta_itp = delta_e_itp(
                np.asarray(color["predicted_ictcp"]),
                np.asarray(color["reference_ictcp"]),
            )
            section["delta_e_itp_mean"] = float(np.mean(delta_itp))
            section["delta_e_itp_p95"] = float(np.percentile(delta_itp, 95))
        section.update(signal_range_metrics(np.asarray(color["rgb_signal"])))
        section.update(
            banding_metrics(
                np.asarray(color["ramp"]),
                code_values=int(color.get("ramp_code_values", 1024)),
            )
        )
        metrics["color"] = section

    ranking = observations.get("ranking")
    if isinstance(ranking, dict):
        section: dict[str, float] = {}
        if {"score_a", "score_b", "preference"} <= set(ranking):
            section.update(
                pairwise_ranking_metrics(
                    ranking["score_a"],
                    ranking["score_b"],
                    ranking["preference"],
                )
            )
        if "reviewer_category_counts" in ranking:
            section["reviewer_fleiss_kappa"] = fleiss_kappa(
                np.asarray(ranking["reviewer_category_counts"])
            )
        if "bradley_terry_records" in ranking:
            preference_report = train_bradley_terry_preference(
                [
                    PairwisePreferenceRecord.model_validate(item)
                    for item in ranking["bradley_terry_records"]
                ],
                config=PreferenceTrainingConfig.model_validate(
                    ranking.get("bradley_terry_config", {})
                ),
            )
            section.update(
                {
                    "domain_bt_pairwise_accuracy": (
                        preference_report.test_metrics.pairwise_accuracy
                    ),
                    "domain_bt_log_loss": (
                        preference_report.test_metrics.bradley_terry_log_loss
                    ),
                    "domain_bt_brier": preference_report.test_metrics.brier_score,
                    "domain_bt_ece": (
                        preference_report.test_metrics.expected_calibration_error
                    ),
                    "domain_bt_reviewer_fleiss_kappa": (
                        preference_report.reviewer_agreement.fleiss_kappa
                    ),
                    "domain_bt_all_baselines_significantly_better": float(
                        preference_report.all_required_baselines_significantly_better
                    ),
                }
            )
            for comparison in preference_report.baseline_comparisons:
                prefix = f"domain_bt_vs_{comparison.baseline}"
                section[f"{prefix}_accuracy_difference"] = (
                    comparison.accuracy_difference
                )
                section[f"{prefix}_log_loss_difference"] = (
                    comparison.log_loss_difference
                )
                section[f"{prefix}_significantly_better"] = float(
                    comparison.significantly_better
                )
        if section:
            metrics["ranking"] = section

    repair = observations.get("repair")
    if isinstance(repair, dict):
        metrics["repair"] = _repair_acceptance_metrics(repair)

    engineering = observations.get("engineering")
    if isinstance(engineering, dict):
        section = percentile_latency(engineering["latencies_ms"])
        for key in (
            "fps_1080p",
            "fps_4k",
            "peak_vram_mb",
            "cold_start_seconds",
            "warm_start_seconds",
            "long_video_drift_ratio",
            "long_video_failures",
        ):
            if key in engineering:
                section[key] = float(engineering[key])
        metrics["engineering"] = section
    return metrics


def _metric_value(
    metrics: dict[str, dict[str, float]],
    path: str,
) -> float:
    section, separator, metric = path.rpartition(".")
    if not separator or section not in metrics or metric not in metrics[section]:
        raise ValueError(f"quality gate references unknown metric {path!r}")
    return metrics[section][metric]


def _evaluate_gates(
    metrics: dict[str, dict[str, float]],
    gates: dict[str, Any],
) -> dict[str, bool]:
    results: dict[str, bool] = {}
    for path, rule in gates.items():
        if not isinstance(rule, dict):
            raise ValueError(f"gate {path!r} must be an object")
        value = _metric_value(metrics, path)
        if "minimum" in rule:
            passed = value >= float(rule["minimum"])
        elif "maximum" in rule:
            passed = value <= float(rule["maximum"])
        else:
            raise ValueError(f"gate {path!r} requires minimum or maximum")
        results[path] = passed
    return results


_SECTION_TASKS: dict[str, frozenset[EvaluationTask]] = {
    "analysis": frozenset({EvaluationTask.ANALYSIS}),
    "representative": frozenset({EvaluationTask.REPRESENTATIVE_FRAME}),
    "shot": frozenset({EvaluationTask.SHOT_BOUNDARY}),
    "scene": frozenset({EvaluationTask.SCENE}),
    "mask": frozenset(
        {
            EvaluationTask.SEMANTIC_MASK,
            EvaluationTask.TEMPORAL_MASK,
        }
    ),
    "depth": frozenset({EvaluationTask.DEPTH}),
    "color": frozenset({EvaluationTask.COLOR}),
    "ranking": frozenset({EvaluationTask.RANKING}),
    "repair": frozenset({EvaluationTask.REPAIR}),
}
_V2_ACCEPTANCE_SECTIONS = frozenset(
    {
        "analysis",
        "representative",
        "scene",
        "ranking",
        "repair",
    }
)


def _validate_gold_audit_profile_floor(
    profile: GoldSetAuditProfile,
) -> None:
    required = LANDSCAPE_P0_AUDIT_PROFILE
    weaker_fields: list[str] = []
    for field_name in (
        "minimum_shot_boundary_items",
        "minimum_scene_items",
        "minimum_complex_mask_depth_source_groups",
        "minimum_unique_cameras",
    ):
        if getattr(profile, field_name) < getattr(required, field_name):
            weaker_fields.append(field_name)
    missing_tags = set(required.required_tags) - set(profile.required_tags)
    if missing_tags:
        weaker_fields.append(
            "required_tags=" + ",".join(sorted(missing_tags))
        )
    if required.require_commercial_use and not profile.require_commercial_use:
        weaker_fields.append("require_commercial_use")
    if weaker_fields:
        raise ValueError(
            "Gold audit profile is weaker than landscape-p0/v1: "
            + "; ".join(weaker_fields)
        )


def _unique_material_ids(
    values: Any,
    *,
    label: str,
) -> list[str]:
    if not isinstance(values, list) or not values:
        raise ValueError(f"{label} must be a non-empty list")
    normalized = [str(value).strip() for value in values]
    if any(not value for value in normalized):
        raise ValueError(f"{label} cannot contain empty values")
    if len(normalized) != len(set(normalized)):
        raise ValueError(f"{label} must contain unique values")
    return normalized


def _section_observed_material_ids(
    section_name: str,
    payload: dict[str, Any],
) -> list[str]:
    if section_name == "analysis":
        material_ids = _unique_material_ids(
            payload.get("material_ids"),
            label="analysis.material_ids",
        )
        sample_material_ids = payload.get("sample_material_ids")
        if not isinstance(sample_material_ids, list) or not sample_material_ids:
            raise ValueError(
                "analysis.sample_material_ids must bind every measured sample"
            )
        if len(sample_material_ids) != len(payload["candidate_exposure_ev"]):
            raise ValueError(
                "analysis.sample_material_ids must match balance samples"
            )
        if set(str(value) for value in sample_material_ids) != set(material_ids):
            raise ValueError(
                "analysis samples must cover every bound material exactly by ID"
            )
        return material_ids
    if section_name in {"representative", "scene", "repair"}:
        items = payload.get("items")
        if not isinstance(items, list) or not items:
            raise ValueError(f"{section_name}.items must be a non-empty list")
        material_ids = [
            str(item.get("material_id", "")).strip()
            for item in items
            if isinstance(item, dict)
        ]
        if len(material_ids) != len(items) or any(
            not value for value in material_ids
        ):
            raise ValueError(
                f"{section_name} items require material_id"
            )
        if len(material_ids) != len(set(material_ids)):
            raise ValueError(
                f"{section_name} material_id values must be unique"
            )
        return material_ids
    return _unique_material_ids(
        payload.get("material_ids"),
        label=f"{section_name}.material_ids",
    )


def _validate_ranking_sources(
    payload: dict[str, Any],
    *,
    manifest: GoldSetManifest,
    qualified_ids: set[str],
    bound_test_ids: set[str],
) -> None:
    records = payload.get("bradley_terry_records")
    if not isinstance(records, list) or not records:
        raise ValueError(
            "Gold-qualified ranking requires bradley_terry_records"
        )
    ranking_items = {
        item.source_group_id: item
        for item in manifest.items
        if item.task == EvaluationTask.RANKING and item.id in qualified_ids
    }
    if not ranking_items:
        raise ValueError("manifest has no qualified human ranking materials")
    observed_test_sources: set[str] = set()
    for record in records:
        if not isinstance(record, dict):
            raise ValueError("ranking records must be objects")
        source_id = str(record.get("source_id", "")).strip()
        item = ranking_items.get(source_id)
        if item is None:
            raise ValueError(
                f"ranking source {source_id!r} is not qualified by the manifest"
            )
        split = str(record.get("split", ""))
        if split != item.split.value:
            raise ValueError(
                f"ranking source {source_id!r} split does not match manifest"
            )
        if item.split == DatasetSplit.TEST:
            observed_test_sources.add(source_id)
    expected_test_sources = {
        item.source_group_id
        for item in manifest.items
        if item.id in bound_test_ids
    }
    if observed_test_sources != expected_test_sources:
        raise ValueError(
            "ranking test records must exactly cover bound test source groups"
        )


def _validate_gold_bindings(
    manifest: GoldSetManifest,
    observations: dict[str, Any],
    metric_sections: set[str],
    *,
    qualified_items: list[Any],
) -> dict[str, list[str]]:
    bindings = observations.get("gold_bindings")
    if not isinstance(bindings, dict):
        raise ValueError(
            "Gold-qualified evaluation requires a gold_bindings object"
        )
    unknown_bindings = set(bindings) - metric_sections
    missing_bindings = metric_sections - set(bindings)
    if unknown_bindings or missing_bindings:
        raise ValueError(
            "gold_bindings must exactly match evaluated metric sections; "
            f"missing={sorted(missing_bindings)}; "
            f"unexpected={sorted(unknown_bindings)}"
        )
    item_by_id = {item.id: item for item in manifest.items}
    qualified_by_id = {item.id: item for item in qualified_items}
    qualified_ids = set(qualified_by_id)
    validated: dict[str, list[str]] = {}
    for section_name in sorted(metric_sections):
        allowed_tasks = _SECTION_TASKS.get(section_name)
        if allowed_tasks is None:
            raise ValueError(
                f"section {section_name!r} cannot be Gold-qualified"
            )
        bound_ids = _unique_material_ids(
            bindings[section_name],
            label=f"gold_bindings.{section_name}",
        )
        payload = observations.get(section_name)
        if not isinstance(payload, dict):
            raise ValueError(
                f"Gold-bound section {section_name!r} must be an object"
            )
        observed_ids = _section_observed_material_ids(
            section_name,
            payload,
        )
        if set(observed_ids) != set(bound_ids):
            raise ValueError(
                f"{section_name} observations do not exactly match "
                "their Gold binding"
            )
        if section_name in {"representative", "scene", "repair"}:
            for observed_item in payload["items"]:
                material_id = str(observed_item["material_id"])
                manifest_item = item_by_id.get(material_id)
                if (
                    manifest_item is not None
                    and str(observed_item.get("source_group_id", ""))
                    != manifest_item.source_group_id
                ):
                    raise ValueError(
                        f"{section_name} material {material_id!r} source "
                        "group does not match manifest"
                    )
        for material_id in bound_ids:
            item = item_by_id.get(material_id)
            if item is None:
                raise ValueError(
                    f"Gold binding references unknown material {material_id!r}"
                )
            if material_id not in qualified_by_id:
                raise ValueError(
                    f"Gold binding material {material_id!r} lacks accepted "
                    "independent human truth"
                )
            if item.split != DatasetSplit.TEST or not item.frozen:
                raise ValueError(
                    f"Gold binding material {material_id!r} is not frozen test"
                )
            if item.task not in allowed_tasks:
                raise ValueError(
                    f"Gold binding material {material_id!r} has task "
                    f"{item.task.value!r}, expected "
                    f"{sorted(task.value for task in allowed_tasks)}"
                )
        expected_ids = {
            item.id
            for item in qualified_items
            if item.split == DatasetSplit.TEST
            and item.task in allowed_tasks
        }
        if set(bound_ids) != expected_ids:
            raise ValueError(
                f"Gold section {section_name!r} must cover every qualified "
                f"test material; missing={sorted(expected_ids - set(bound_ids))}; "
                f"unexpected={sorted(set(bound_ids) - expected_ids)}"
            )
        if (
            section_name in _V2_ACCEPTANCE_SECTIONS
            and manifest.annotation_guideline_version
            != LANDSCAPE_ACCEPTANCE_ANNOTATION_VERSION
        ):
            raise ValueError(
                f"Gold section {section_name!r} requires annotation guideline "
                f"{LANDSCAPE_ACCEPTANCE_ANNOTATION_VERSION!r}"
            )
        if section_name == "ranking":
            _validate_ranking_sources(
                payload,
                manifest=manifest,
                qualified_ids=qualified_ids,
                bound_test_ids=set(bound_ids),
            )
        validated[section_name] = bound_ids
    return validated


def _validate_gate_policy(
    manifest: GoldSetManifest,
    observations: dict[str, Any],
    metric_sections: set[str],
    qualified_items: list[Any],
    *,
    manifest_sha256: str,
    gate_policy_path: str | Path,
) -> tuple[GoldGatePolicy, str, str, str]:
    resolved_policy = Path(gate_policy_path).resolve()
    policy_content = resolved_policy.read_bytes()
    policy = GoldGatePolicy.model_validate_json(policy_content)
    calibration_observation = (
        resolved_policy.parent / policy.calibration_observation_path
    ).resolve()
    if (
        not calibration_observation.is_relative_to(resolved_policy.parent)
        or not calibration_observation.is_file()
    ):
        raise FileNotFoundError(
            "Gold calibration observation is missing or outside the gate "
            f"policy directory: {calibration_observation}"
        )
    calibration_content = calibration_observation.read_bytes()
    calibration_sha256 = hashlib.sha256(calibration_content).hexdigest()
    if calibration_sha256 != policy.calibration_observation_sha256:
        raise ValueError("Gold calibration observation checksum mismatch")
    try:
        calibration_payload = json.loads(calibration_content)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError(
            "Gold calibration observation must be a UTF-8 JSON object"
        ) from error
    if not isinstance(calibration_payload, dict):
        raise ValueError(
            "Gold calibration observation must be a UTF-8 JSON object"
        )
    if (
        calibration_payload.get("schema_version")
        != "colorgraph.gold-calibration-observations/v1"
        or calibration_payload.get("manifest_id") != manifest.id
        or calibration_payload.get("manifest_version") != manifest.version
    ):
        raise ValueError(
            "Gold calibration observation does not match the manifest"
        )
    if calibration_payload.get("test_materials_accessed") is not False:
        raise ValueError(
            "Gold calibration observation must explicitly exclude test access"
        )
    calibration_bindings = calibration_payload.get(
        "section_material_ids"
    )
    if not isinstance(calibration_bindings, dict):
        raise ValueError(
            "Gold calibration observation requires section material bindings"
        )
    normalized_calibration_bindings = {
        section: sorted(
            _unique_material_ids(
                material_ids,
                label=(
                    "calibration_observation.section_material_ids."
                    f"{section}"
                ),
            )
        )
        for section, material_ids in calibration_bindings.items()
    }
    normalized_policy_bindings = {
        section: sorted(material_ids)
        for section, material_ids in policy.calibration_material_ids.items()
    }
    if normalized_calibration_bindings != normalized_policy_bindings:
        raise ValueError(
            "Gold calibration observation material bindings do not match "
            "the gate policy"
        )
    calibration_gates = calibration_payload.get("gates")
    if not isinstance(calibration_gates, dict):
        raise ValueError(
            "Gold calibration observation requires frozen metric gates"
        )
    normalized_calibration_gates = {
        path: GoldGateRule.model_validate(rule).model_dump(
            mode="json",
            exclude_none=True,
        )
        for path, rule in calibration_gates.items()
    }
    normalized_policy_gates = {
        path: rule.model_dump(mode="json", exclude_none=True)
        for path, rule in policy.gates.items()
    }
    if normalized_calibration_gates != normalized_policy_gates:
        raise ValueError(
            "Gold calibration observation gates do not match the gate policy"
        )
    if (
        policy.manifest_id != manifest.id
        or policy.manifest_version != manifest.version
        or policy.manifest_sha256 != manifest_sha256
    ):
        raise ValueError("Gold gate policy does not match the manifest")
    if (
        policy.annotation_guideline_version
        != manifest.annotation_guideline_version
    ):
        raise ValueError(
            "Gold gate policy annotation guideline does not match manifest"
        )
    policy_sections = set(policy.calibration_material_ids)
    if policy_sections != metric_sections:
        raise ValueError(
            "Gold gate policy sections must exactly match evaluated sections; "
            f"missing={sorted(metric_sections - policy_sections)}; "
            f"unexpected={sorted(policy_sections - metric_sections)}"
        )
    normalized_observation_gates = {
        path: GoldGateRule.model_validate(rule).model_dump(
            mode="json",
            exclude_none=True,
        )
        for path, rule in observations.get("gates", {}).items()
    }
    if normalized_policy_gates != normalized_observation_gates:
        raise ValueError(
            "evaluation gates do not exactly match the frozen Gold gate policy"
        )
    gate_sections = {
        path.partition(".")[0]
        for path in policy.gates
        if path.partition(".")[1]
    }
    if gate_sections != metric_sections:
        raise ValueError(
            "Gold gate policy must define at least one gate for every "
            "evaluated section and no other section"
        )
    qualified_by_id = {item.id: item for item in qualified_items}
    for section_name in sorted(metric_sections):
        allowed_tasks = _SECTION_TASKS[section_name]
        calibration_ids = _unique_material_ids(
            policy.calibration_material_ids[section_name],
            label=(
                "gate_policy.calibration_material_ids."
                f"{section_name}"
            ),
        )
        expected_ids = {
            item.id
            for item in qualified_items
            if item.split == DatasetSplit.CALIBRATION
            and item.task in allowed_tasks
        }
        if set(calibration_ids) != expected_ids:
            raise ValueError(
                f"Gold gate policy section {section_name!r} must cover every "
                "qualified calibration material"
            )
        if any(
            qualified_by_id[material_id].split != DatasetSplit.CALIBRATION
            for material_id in calibration_ids
        ):
            raise ValueError(
                "Gold gate policy may bind calibration materials only"
            )
    annotator_ids = {
        annotator_id
        for item in qualified_items
        for annotator_id in item.annotation_provenance.annotator_ids
    }
    if not set(policy.approved_by).isdisjoint(annotator_ids):
        raise ValueError(
            "Gold gate policy approvers must be independent of annotators"
        )
    return (
        policy,
        str(resolved_policy),
        hashlib.sha256(policy_content).hexdigest(),
        str(calibration_observation),
    )


def _gold_evaluation_evidence(
    manifest: GoldSetManifest,
    observations: dict[str, Any],
    metric_sections: set[str],
    *,
    audit_path: str | Path | None,
    gate_policy_path: str | Path | None,
    manifest_sha256: str,
    require_passed_gold: bool,
) -> GoldEvaluationEvidence | None:
    if audit_path is None:
        if require_passed_gold:
            raise ValueError(
                "require_passed_gold requires an audited Gold report"
            )
        return None
    resolved_audit = Path(audit_path).resolve()
    audit_content = resolved_audit.read_bytes()
    report = GoldSetAuditReport.model_validate_json(audit_content)
    if (
        report.manifest_id != manifest.id
        or report.manifest_version != manifest.version
    ):
        raise ValueError("Gold audit report does not match the manifest")
    _validate_gold_audit_profile_floor(report.profile)
    recomputed = audit_gold_set(manifest, report.profile)
    if recomputed != report:
        raise ValueError(
            "Gold audit report is stale or does not match a fresh audit"
        )
    if require_passed_gold and not report.passed:
        raise ValueError("Gold audit report has not passed")
    qualified_items = qualified_human_gold_items(manifest, report.profile)
    bindings: dict[str, list[str]] = {}
    fully_bound = False
    policy: GoldGatePolicy | None = None
    resolved_policy_path: str | None = None
    policy_sha256: str | None = None
    resolved_calibration_observation_path: str | None = None
    if "gold_bindings" in observations:
        bindings = _validate_gold_bindings(
            manifest,
            observations,
            metric_sections,
            qualified_items=qualified_items,
        )
        if gate_policy_path is None:
            raise ValueError(
                "Gold-bound evaluation requires a frozen gate policy"
            )
        (
            policy,
            resolved_policy_path,
            policy_sha256,
            resolved_calibration_observation_path,
        ) = _validate_gate_policy(
            manifest,
            observations,
            metric_sections,
            qualified_items,
            manifest_sha256=manifest_sha256,
            gate_policy_path=gate_policy_path,
        )
        fully_bound = True
    elif require_passed_gold:
        raise ValueError(
            "Gold-qualified evaluation requires complete section bindings"
        )
    if (
        policy is None
        or resolved_policy_path is None
        or policy_sha256 is None
        or resolved_calibration_observation_path is None
    ):
        if require_passed_gold:
            raise ValueError(
                "Gold-qualified evaluation requires a frozen gate policy"
            )
        return None
    return GoldEvaluationEvidence(
        audit_path=str(resolved_audit),
        audit_sha256=hashlib.sha256(audit_content).hexdigest(),
        audit_passed=report.passed,
        annotation_guideline_version=(
            manifest.annotation_guideline_version
        ),
        gate_policy_path=resolved_policy_path,
        gate_policy_sha256=policy_sha256,
        gate_policy_id=policy.policy_id,
        calibration_observation_path=(
            resolved_calibration_observation_path
        ),
        calibration_observation_sha256=(
            policy.calibration_observation_sha256
        ),
        qualified_test_material_ids=sorted(
            item.id
            for item in qualified_items
            if item.split == DatasetSplit.TEST
        ),
        section_material_ids=bindings,
        all_sections_fully_bound=fully_bound,
    )


def evaluate_observations(
    manifest_path: str | Path,
    observation_path: str | Path,
    output_path: str | Path,
    *,
    dataset_root: str | Path | None = None,
    gold_audit_path: str | Path | None = None,
    gate_policy_path: str | Path | None = None,
    require_passed_gold: bool = False,
) -> EvaluationReport:
    resolved_manifest = Path(manifest_path).resolve()
    resolved_observations = Path(observation_path).resolve()
    manifest = load_gold_set_manifest(resolved_manifest)
    manifest_sha256 = _sha256(resolved_manifest)
    validate_gold_set_files(
        manifest,
        (
            Path(dataset_root).resolve()
            if dataset_root is not None
            else resolved_manifest.parent
        ),
    )
    observations = json.loads(resolved_observations.read_text(encoding="utf-8"))
    if not isinstance(observations, dict):
        raise ValueError("evaluation observations must be a JSON object")
    metrics = _evaluate_sections(observations)
    if not metrics:
        raise ValueError("evaluation observations contain no supported metric sections")
    gates = _evaluate_gates(metrics, observations.get("gates", {}))
    if require_passed_gold and not gates:
        raise ValueError(
            "Gold-qualified evaluation requires explicit frozen quality gates"
        )
    logical_metric_sections = {
        section_name.partition(".")[0] for section_name in metrics
    }
    gold_evidence = _gold_evaluation_evidence(
        manifest,
        observations,
        logical_metric_sections,
        audit_path=gold_audit_path,
        gate_policy_path=gate_policy_path,
        manifest_sha256=manifest_sha256,
        require_passed_gold=require_passed_gold,
    )
    gold_qualified = bool(
        gold_evidence is not None
        and gold_evidence.audit_passed
        and gold_evidence.all_sections_fully_bound
    )
    release_eligible = bool(
        gold_qualified and gates and all(gates.values())
    )
    report = EvaluationReport(
        manifest_id=manifest.id,
        manifest_version=manifest.version,
        manifest_sha256=manifest_sha256,
        observation_sha256=_sha256(resolved_observations),
        configuration=observations.get("configuration", {}),
        hardware=_hardware_snapshot(),
        materials=[
            EvaluatedMaterial(
                id=item.id,
                task=item.task.value,
                split=item.split.value,
                media_sha256=item.media_sha256,
                annotation_sha256=item.annotation_sha256,
            )
            for item in manifest.items
        ],
        metrics=metrics,
        gates=gates,
        evidence_status=(
            "gold_qualified" if gold_qualified else "engineering_only"
        ),
        release_eligible=release_eligible,
        gold_evidence=gold_evidence,
        notes=[
            "test split is frozen and must not be used for parameter tuning",
            (
                "Gold qualification requires a freshly reproduced passing "
                "audit and exact coverage of every qualified test material."
            ),
        ],
    )
    destination = Path(output_path).resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(report.model_dump_json(indent=2), encoding="utf-8")
    return report
