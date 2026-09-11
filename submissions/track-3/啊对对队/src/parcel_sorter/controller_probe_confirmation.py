from __future__ import annotations

from collections import defaultdict
import math
import statistics
from typing import Any, Iterable, Mapping, Sequence

from .controller_faithful_probe import extract_controller_faithful_probe
from .evaluation_statistics import exact_mcnemar_test, paired_mean_difference
from .grasp_scoring import canonical_payload_sha256
from .metrics import wilson_interval


CONFIRMATION_SCHEMA_VERSION = 1
CONFIRMATION_POLICY = "veto-static"
CONFIRMATION_SPLIT = "confirmation"
CONFIRMATION_ACTIVATION_POLICY = "all-boxes"


def _finite_float(value: Any, name: str) -> float:
    result = float(value)
    if not math.isfinite(result):
        raise ValueError(f"{name} must be finite")
    return result


def _probe_eligible(row: Mapping[str, Any]) -> bool:
    features = row["probe"]["feature_map"]
    return (
        float(features["probe_completed"]) == 1.0
        and float(features["probe_safety_aborted"]) == 0.0
        and float(features["contact_acquired"]) == 1.0
        and float(features["terminal_grasp_contact"]) == 1.0
        and float(features["terminal_parcel_lifted"]) == 1.0
    )


def _sample_strata(
    sample: Mapping[str, Any],
    *,
    legacy_profiles: frozenset[str],
) -> dict[str, str]:
    profile = str(sample["profile_id"])
    yaw_degrees = abs(math.degrees(_finite_float(sample["yaw_rad"], "yaw_rad")))
    yaw_folded = yaw_degrees % 90.0
    yaw_from_axis = min(yaw_folded, 90.0 - yaw_folded)
    friction = _finite_float(sample["friction"], "friction")
    mass = _finite_float(sample["mass_kg"], "mass_kg")
    camera_noise = tuple(
        _finite_float(value, "camera_noise_xyz_m")
        for value in sample["camera_noise_xyz_m"]
    )
    if len(camera_noise) != 3:
        raise ValueError("camera_noise_xyz_m must contain three values")
    noise_norm = math.sqrt(sum(value * value for value in camera_noise))
    return {
        "profile_novelty": "legacy_profile" if profile in legacy_profiles else "unseen_profile",
        "yaw_band": (
            "axis_near_0_15deg"
            if yaw_from_axis <= 15.0
            else "oblique_15_30deg"
            if yaw_from_axis <= 30.0
            else "oblique_30_45deg"
        ),
        "friction_band": (
            "low_le_0p50"
            if friction <= 0.50
            else "medium_0p50_0p85"
            if friction <= 0.85
            else "high_gt_0p85"
        ),
        "camera_noise_band": (
            "low_le_0p010m"
            if noise_norm <= 0.010
            else "medium_0p010_0p020m"
            if noise_norm <= 0.020
            else "high_gt_0p020m"
        ),
        "mass_band": (
            "light_le_0p50kg"
            if mass <= 0.50
            else "medium_0p50_1p00kg"
            if mass <= 1.00
            else "heavy_gt_1p00kg"
        ),
    }


def confirmation_rows(
    payload: Mapping[str, Any],
    *,
    source: str,
    source_sha256: str,
    legacy_profiles: frozenset[str],
) -> list[dict[str, Any]]:
    contract = payload.get("contract")
    sample = payload.get("sample")
    if not isinstance(contract, Mapping) or not isinstance(sample, Mapping):
        raise ValueError("confirmation source requires contract and sample mappings")
    if not bool(contract.get("controller_faithful")) or not bool(
        contract.get("fresh_scene_per_rollout")
    ):
        raise ValueError("confirmation source violates the controller-faithful contract")
    if str(contract.get("planning_activation_policy")) != CONFIRMATION_ACTIVATION_POLICY:
        raise ValueError(
            f"confirmation source must use {CONFIRMATION_ACTIVATION_POLICY} activation"
        )
    profile = str(payload["profile"])
    episode = int(payload["episode"])
    if str(sample.get("profile_id")) != profile:
        raise ValueError("confirmation sample profile differs from source profile")
    strata = _sample_strata(sample, legacy_profiles=legacy_profiles)
    rows: list[dict[str, Any]] = []
    seen: set[tuple[str, int]] = set()
    for rollout in payload.get("rollouts", ()):  # type: ignore[union-attr]
        if not isinstance(rollout, Mapping):
            raise ValueError("confirmation rollout must be a mapping")
        candidate_id = str(rollout["candidate_id"])
        repeat = int(rollout["repeat"])
        key = candidate_id, repeat
        if key in seen:
            raise ValueError(f"duplicate confirmation rollout: {key}")
        seen.add(key)
        if str(rollout["selected_candidate_id"]) != candidate_id:
            raise ValueError("confirmation requested/selected candidate mismatch")
        rows.append(
            {
                "source": source,
                "source_sha256": source_sha256,
                "split": CONFIRMATION_SPLIT,
                "group_id": f"{profile}:{episode}",
                "profile": profile,
                "episode": episode,
                "candidate_id": candidate_id,
                "repeat": repeat,
                "static_rank": int(rollout["static_rank"]),
                "sample": dict(sample),
                "strata": strata,
                # All-box confirmation intentionally includes candidates that
                # can time out before the pre-place boundary. Their complete
                # trace is retained and the extractor marks probe_completed=0,
                # making them ineligible without fabricating a boundary.
                "probe": extract_controller_faithful_probe(
                    payload,
                    rollout,
                    allow_incomplete=True,
                ),
                "labels": {
                    "success": bool(rollout["success"]),
                    "safety_aborted": bool(rollout["safety_aborted"]),
                    "dropped": bool(rollout.get("dropped", False)),
                    "max_contact_force_n": _finite_float(
                        rollout["max_contact_force_n"], "max_contact_force_n"
                    ),
                    "duration_seconds": _finite_float(
                        rollout["duration_seconds"], "duration_seconds"
                    ),
                },
            }
        )
    if not rows:
        raise ValueError("confirmation source contains no rollouts")
    return rows


def build_confirmation_dataset(
    sources: Iterable[tuple[str, Mapping[str, Any], str]],
    *,
    legacy_profiles: frozenset[str],
) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    artifacts: list[dict[str, str]] = []
    seen_sources: set[str] = set()
    seen_rows: set[tuple[str, int, str, int]] = set()
    for source, payload, source_sha256 in sources:
        if source in seen_sources:
            raise ValueError(f"duplicate confirmation source: {source}")
        seen_sources.add(source)
        artifacts.append({"path": source, "sha256": source_sha256})
        for row in confirmation_rows(
            payload,
            source=source,
            source_sha256=source_sha256,
            legacy_profiles=legacy_profiles,
        ):
            key = (
                str(row["profile"]),
                int(row["episode"]),
                str(row["candidate_id"]),
                int(row["repeat"]),
            )
            if key in seen_rows:
                raise ValueError(f"duplicate confirmation row: {key}")
            seen_rows.add(key)
            rows.append(row)
    if not rows:
        raise ValueError("confirmation dataset requires at least one source")
    result: dict[str, Any] = {
        "schema_version": CONFIRMATION_SCHEMA_VERSION,
        "split": CONFIRMATION_SPLIT,
        "policy": CONFIRMATION_POLICY,
        "source_artifacts": artifacts,
        "row_count": len(rows),
        "group_count": len({str(row["group_id"]) for row in rows}),
        "profiles": sorted({str(row["profile"]) for row in rows}),
        "rows": rows,
    }
    result["dataset_sha256"] = canonical_payload_sha256(result)
    return result


def select_veto_static(rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[str(row["group_id"])].append(row)
    if not grouped:
        raise ValueError("confirmation selection requires at least one group")
    selections: list[dict[str, Any]] = []
    for group_id, candidates in sorted(grouped.items()):
        ordered = sorted(
            candidates,
            key=lambda row: (int(row["static_rank"]), str(row["candidate_id"])),
        )
        baseline = ordered[0]
        selected = next((row for row in ordered if _probe_eligible(row)), None)
        model_labels = selected["labels"] if selected is not None else None
        baseline_labels = baseline["labels"]
        selections.append(
            {
                "group_id": group_id,
                "profile": str(baseline["profile"]),
                "strata": dict(baseline["strata"]),
                "policy": CONFIRMATION_POLICY,
                "decision": "probe_selected" if selected is not None else "safe_abstain",
                "model_candidate_id": str(selected["candidate_id"]) if selected else None,
                "baseline_candidate_id": str(baseline["candidate_id"]),
                "model_success": bool(model_labels["success"]) if model_labels else False,
                "baseline_success": bool(baseline_labels["success"]),
                "model_safety_aborted": bool(model_labels["safety_aborted"]) if model_labels else False,
                "baseline_safety_aborted": bool(baseline_labels["safety_aborted"]),
                "model_dropped": bool(model_labels["dropped"]) if model_labels else False,
                "baseline_dropped": bool(baseline_labels["dropped"]),
                "model_force_n": float(model_labels["max_contact_force_n"]) if model_labels else None,
                "baseline_force_n": float(baseline_labels["max_contact_force_n"]),
                "model_duration_seconds": float(model_labels["duration_seconds"]) if model_labels else None,
                "baseline_duration_seconds": float(baseline_labels["duration_seconds"]),
                "eligible_candidate_count": sum(_probe_eligible(row) for row in ordered),
                "probe_candidate_count": len(ordered),
                "probe_consumed_trace_frames": sum(
                    int(row["probe"]["consumed_trace_frames"]) for row in ordered
                ),
            }
        )
    return selections


def _rate(outcomes: Sequence[bool]) -> dict[str, int | float]:
    count = sum(outcomes)
    low, high = wilson_interval(count, len(outcomes))
    return {
        "count": count,
        "trials": len(outcomes),
        "rate": count / len(outcomes),
        "ci95_low": low,
        "ci95_high": high,
    }


def _one_sided_reduction_test(
    baseline: Sequence[bool], candidate: Sequence[bool]
) -> dict[str, int | float]:
    two_sided = exact_mcnemar_test(baseline, candidate)
    reductions = int(two_sided["baseline_only_positive"])
    regressions = int(two_sided["candidate_only_positive"])
    discordant = reductions + regressions
    p_value = (
        1.0
        if discordant == 0
        else sum(
            math.comb(discordant, index)
            for index in range(reductions, discordant + 1)
        )
        / (2**discordant)
    )
    return {
        **two_sided,
        "alternative": "candidate_has_fewer_positive_outcomes",
        "p_value_one_sided_exact": p_value,
    }


def _paired_summary(items: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    if not items:
        raise ValueError("confirmation summary requires at least one group")
    model_success = [bool(row["model_success"]) for row in items]
    baseline_success = [bool(row["baseline_success"]) for row in items]
    model_aborts = [bool(row["model_safety_aborted"]) for row in items]
    baseline_aborts = [bool(row["baseline_safety_aborted"]) for row in items]
    model_drops = [bool(row["model_dropped"]) for row in items]
    baseline_drops = [bool(row["baseline_dropped"]) for row in items]
    executed = [row for row in items if row["model_force_n"] is not None]
    result: dict[str, Any] = {
        "group_count": len(items),
        "safe_abstentions": sum(str(row["decision"]) == "safe_abstain" for row in items),
        "changed_from_baseline": sum(row["model_candidate_id"] != row["baseline_candidate_id"] for row in items),
        "success": {
            "baseline": _rate(baseline_success),
            "candidate": _rate(model_success),
            "paired": exact_mcnemar_test(baseline_success, model_success),
        },
        "safety_abort": {
            "baseline": _rate(baseline_aborts),
            "candidate": _rate(model_aborts),
            "paired": _one_sided_reduction_test(baseline_aborts, model_aborts),
        },
        "drop": {
            "baseline": _rate(baseline_drops),
            "candidate": _rate(model_drops),
            "paired": exact_mcnemar_test(baseline_drops, model_drops),
        },
        "executed_group_count": len(executed),
        "probe_consumed_trace_frames": sum(int(row["probe_consumed_trace_frames"]) for row in items),
    }
    if executed:
        result["executed_max_contact_force_n"] = paired_mean_difference(
            [float(row["baseline_force_n"]) for row in executed],
            [float(row["model_force_n"]) for row in executed],
            bootstrap_samples=2_000,
            permutation_samples=2_000,
        )
        result["executed_duration_seconds"] = paired_mean_difference(
            [float(row["baseline_duration_seconds"]) for row in executed],
            [float(row["model_duration_seconds"]) for row in executed],
            bootstrap_samples=2_000,
            permutation_samples=2_000,
        )
    else:
        result["executed_max_contact_force_n"] = None
        result["executed_duration_seconds"] = None
    return result


def summarize_confirmation(selections: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    overall = _paired_summary(selections)
    overall["by_profile"] = {
        profile: _paired_summary([row for row in selections if str(row["profile"]) == profile])
        for profile in sorted({str(row["profile"]) for row in selections})
    }
    stratum_names = sorted(
        {name for row in selections for name in row["strata"]}
    )
    overall["by_stratum"] = {
        name: {
            value: _paired_summary(
                [row for row in selections if str(row["strata"][name]) == value]
            )
            for value in sorted({str(row["strata"][name]) for row in selections})
        }
        for name in stratum_names
    }
    overall["selections"] = [dict(row) for row in selections]
    return overall


def audit_confirmation(
    summary: Mapping[str, Any],
    *,
    expected_groups: int,
    expected_groups_per_profile: int,
    min_safety_abort_reductions: int,
    min_profiles_with_safety_reduction: int,
    safety_alpha: float,
    selection_p95_ms: float,
    max_selection_p95_ms: float,
) -> dict[str, Any]:
    reasons: list[str] = []
    if int(summary["group_count"]) != expected_groups:
        reasons.append("incomplete_confirmation_population")
    success_pairs = summary["success"]["paired"]
    abort_pairs = summary["safety_abort"]["paired"]
    drop_pairs = summary["drop"]["paired"]
    if int(success_pairs["baseline_only_positive"]) > 0:
        reasons.append("any_success_loss")
    if int(abort_pairs["candidate_only_positive"]) > 0:
        reasons.append("any_safety_abort_regression")
    if int(drop_pairs["candidate_only_positive"]) > 0:
        reasons.append("any_drop_regression")
    reductions = int(abort_pairs["baseline_only_positive"])
    if reductions < min_safety_abort_reductions:
        reasons.append("insufficient_safety_abort_reductions")
    improving_profiles = []
    for profile, row in sorted(summary["by_profile"].items()):
        if int(row["group_count"]) != expected_groups_per_profile:
            reasons.append("incomplete_profile_population")
        if int(row["success"]["paired"]["baseline_only_positive"]) > 0:
            reasons.append("per_profile_success_loss")
        if int(row["safety_abort"]["paired"]["candidate_only_positive"]) > 0:
            reasons.append("per_profile_safety_regression")
        if int(row["safety_abort"]["paired"]["baseline_only_positive"]) > 0:
            improving_profiles.append(profile)
    if len(improving_profiles) < min_profiles_with_safety_reduction:
        reasons.append("safety_benefit_concentrated")
    if float(abort_pairs["p_value_one_sided_exact"]) > safety_alpha:
        reasons.append("safety_reduction_not_statistically_confirmed")
    if selection_p95_ms >= max_selection_p95_ms:
        reasons.append("selection_latency_gate_failed")
    reasons = list(dict.fromkeys(reasons))
    passes = not reasons
    return {
        "status": "confirmation_passed" if passes else "confirmation_failed",
        "passes": passes,
        "policy": CONFIRMATION_POLICY,
        "reasons": reasons,
        "safety_abort_reductions": reductions,
        "profiles_with_safety_reduction": improving_profiles,
        "selection_p95_ms": selection_p95_ms,
        "online_parallel_probe_authorized": passes,
        "runtime_activation_authorized": False,
        "v2_holdout_opened": False,
    }
