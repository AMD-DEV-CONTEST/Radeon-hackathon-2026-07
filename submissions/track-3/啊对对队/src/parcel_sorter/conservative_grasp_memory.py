from __future__ import annotations

from collections import defaultdict
import hashlib
import math
import statistics
from typing import Any, Mapping, Sequence

from .grasp_scoring import GRASP_FEATURE_NAMES


def _finite_float(value: Any, name: str) -> float:
    result = float(value)
    if not math.isfinite(result):
        raise ValueError(f"{name} must be finite")
    return result


def _feature_rows(rows: Sequence[Mapping[str, Any]]) -> tuple[tuple[float, ...], ...]:
    result = []
    for row in rows:
        values = tuple(
            _finite_float(value, "grasp memory feature")
            for value in row.get("features", ())
        )
        if len(values) != len(GRASP_FEATURE_NAMES):
            raise ValueError("grasp memory feature row has the wrong width")
        result.append(values)
    if not result:
        raise ValueError("grasp memory requires at least one row")
    return tuple(result)


def profile_stratified_group_folds(
    rows: Sequence[Mapping[str, Any]],
    *,
    fold_count: int,
    seed: int,
) -> dict[str, int]:
    """Assign complete physical groups to deterministic profile-balanced folds."""
    if fold_count < 2:
        raise ValueError("fold_count must be at least two")
    profiles_by_group: dict[str, str] = {}
    for row in rows:
        group_id = str(row.get("group_id", ""))
        profile = str(row.get("profile", ""))
        if not group_id or not profile:
            raise ValueError("every grasp row requires group_id and profile")
        previous = profiles_by_group.setdefault(group_id, profile)
        if previous != profile:
            raise ValueError(f"grasp group crosses profiles: {group_id}")
    if not profiles_by_group:
        raise ValueError("grasp rows cannot be empty")

    groups_by_profile: dict[str, list[str]] = defaultdict(list)
    for group_id, profile in profiles_by_group.items():
        groups_by_profile[profile].append(group_id)
    assignments: dict[str, int] = {}
    for profile, group_ids in sorted(groups_by_profile.items()):
        if len(group_ids) < fold_count:
            raise ValueError(
                f"profile {profile} has fewer groups than folds: "
                f"{len(group_ids)} < {fold_count}"
            )

        def stable_key(group_id: str) -> str:
            payload = f"{seed}:{profile}:{group_id}".encode("utf-8")
            return hashlib.sha256(payload).hexdigest()

        for offset, group_id in enumerate(sorted(group_ids, key=stable_key)):
            assignments[group_id] = offset % fold_count
    return assignments


def robust_feature_statistics(
    rows: Sequence[Mapping[str, Any]],
) -> tuple[tuple[float, ...], tuple[float, ...]]:
    """Return median location and robust positive scale for grasp features."""
    features = _feature_rows(rows)
    columns = tuple(zip(*features, strict=True))
    locations = []
    scales = []
    for column in columns:
        location = float(statistics.median(column))
        mad = float(statistics.median(abs(value - location) for value in column))
        scale = 1.4826 * mad
        if scale <= 1e-9:
            scale = float(statistics.pstdev(column))
        if scale <= 1e-9:
            scale = 1.0
        locations.append(location)
        scales.append(scale)
    return tuple(locations), tuple(scales)


def build_memory_index(
    torch: Any,
    rows: Sequence[Mapping[str, Any]],
    *,
    device: str,
) -> dict[str, Any]:
    """Build a normalized tensor index while retaining auditable row metadata."""
    features = _feature_rows(rows)
    locations, scales = robust_feature_statistics(rows)
    tensor = torch.tensor(features, dtype=torch.float32, device=torch.device(device))
    location_tensor = torch.tensor(
        locations, dtype=torch.float32, device=tensor.device
    )
    scale_tensor = torch.tensor(scales, dtype=torch.float32, device=tensor.device)
    tensor = (tensor - location_tensor) / scale_tensor
    profiles = tuple(sorted({str(row["profile"]) for row in rows}))
    profile_ids = {profile: index for index, profile in enumerate(profiles)}
    groups = tuple(sorted({str(row["group_id"]) for row in rows}))
    group_ids = {group_id: index for index, group_id in enumerate(groups)}
    return {
        "rows": tuple(rows),
        "features": tensor,
        "locations": locations,
        "scales": scales,
        "profile_names": profiles,
        "profile_ids": profile_ids,
        "profile_tensor": torch.tensor(
            [profile_ids[str(row["profile"])] for row in rows],
            dtype=torch.long,
            device=tensor.device,
        ),
        "group_tensor": torch.tensor(
            [group_ids[str(row["group_id"])] for row in rows],
            dtype=torch.long,
            device=tensor.device,
        ),
    }


def _quantile(values: Sequence[float], probability: float) -> float:
    if not values:
        raise ValueError("quantile requires at least one value")
    if not 0 < probability <= 1:
        raise ValueError("quantile probability must be in (0, 1]")
    ordered = sorted(float(value) for value in values)
    index = max(0, math.ceil(probability * len(ordered)) - 1)
    return ordered[index]


def calibrate_profile_distance_thresholds(
    torch: Any,
    index: Mapping[str, Any],
    *,
    neighbor_count: int,
    quantile: float,
) -> dict[str, float]:
    """Calibrate kth-neighbor OOD thresholds without using the query group."""
    if neighbor_count < 1:
        raise ValueError("neighbor_count must be positive")
    features = index["features"]
    distances = torch.cdist(features, features)
    same_profile = index["profile_tensor"][:, None] == index["profile_tensor"][None, :]
    different_group = index["group_tensor"][:, None] != index["group_tensor"][None, :]
    distances = distances.masked_fill(~(same_profile & different_group), float("inf"))
    nearest, _indices = torch.topk(
        distances,
        k=neighbor_count,
        dim=1,
        largest=False,
        sorted=True,
    )
    kth = nearest[:, -1]
    if not bool(torch.isfinite(kth).all()):
        raise ValueError("not enough cross-group neighbors for distance calibration")
    if features.device.type == "cuda":
        torch.cuda.synchronize()
    kth_values = kth.detach().cpu().tolist()
    profile_values: dict[str, list[float]] = defaultdict(list)
    rows = index["rows"]
    for row, value in zip(rows, kth_values, strict=True):
        profile_values[str(row["profile"])].append(float(value))
    return {
        profile: _quantile(values, quantile)
        for profile, values in sorted(profile_values.items())
    }


def query_memory_evidence(
    torch: Any,
    index: Mapping[str, Any],
    query_rows: Sequence[Mapping[str, Any]],
    *,
    neighbor_count: int,
) -> list[dict[str, Any]]:
    """Compute same-profile nearest-neighbor evidence on the requested device."""
    if neighbor_count < 1:
        raise ValueError("neighbor_count must be positive")
    query_features = _feature_rows(query_rows)
    device = index["features"].device
    location = torch.tensor(index["locations"], dtype=torch.float32, device=device)
    scale = torch.tensor(index["scales"], dtype=torch.float32, device=device)
    query_tensor = torch.tensor(query_features, dtype=torch.float32, device=device)
    query_tensor = (query_tensor - location) / scale
    try:
        query_profiles = torch.tensor(
            [index["profile_ids"][str(row["profile"])] for row in query_rows],
            dtype=torch.long,
            device=device,
        )
    except KeyError as exc:
        raise ValueError(f"query profile is absent from memory: {exc.args[0]}") from exc
    distances = torch.cdist(query_tensor, index["features"])
    same_profile = query_profiles[:, None] == index["profile_tensor"][None, :]
    distances = distances.masked_fill(~same_profile, float("inf"))
    nearest_distances, nearest_indices = torch.topk(
        distances,
        k=neighbor_count,
        dim=1,
        largest=False,
        sorted=True,
    )
    if not bool(torch.isfinite(nearest_distances).all()):
        raise ValueError("not enough same-profile rows in grasp memory")
    if device.type == "cuda":
        torch.cuda.synchronize()
    distance_rows = nearest_distances.detach().cpu().tolist()
    index_rows = nearest_indices.detach().cpu().tolist()
    memory_rows = index["rows"]
    evidence = []
    for query, distances_row, indices_row in zip(
        query_rows, distance_rows, index_rows, strict=True
    ):
        neighbors = [memory_rows[int(index_value)] for index_value in indices_row]
        unsafe_count = sum(
            bool(row["labels"]["safety_aborted"]) for row in neighbors
        )
        safe_success_count = sum(
            bool(row["labels"]["success"])
            and not bool(row["labels"]["safety_aborted"])
            for row in neighbors
        )
        forces = [
            _finite_float(row["labels"]["max_contact_force_n"], "neighbor force")
            for row in neighbors
        ]
        durations = [
            _finite_float(row["labels"]["duration_seconds"], "neighbor duration")
            for row in neighbors
        ]
        evidence.append(
            {
                "candidate_id": str(query["candidate_id"]),
                "profile": str(query["profile"]),
                "static_rank": int(query["static_rank"]),
                "neighbor_count": neighbor_count,
                "unsafe_neighbor_count": unsafe_count,
                "safe_success_neighbor_count": safe_success_count,
                "force_upper_n": max(forces),
                "duration_median_seconds": float(statistics.median(durations)),
                "kth_distance": float(distances_row[-1]),
                "neighbor_group_ids": [str(row["group_id"]) for row in neighbors],
                "neighbor_candidate_ids": [
                    str(row["candidate_id"]) for row in neighbors
                ],
            }
        )
    return evidence


def select_conservative_memory_candidates(
    rows: Sequence[Mapping[str, Any]],
    evidence: Sequence[Mapping[str, Any]],
    *,
    distance_thresholds: Mapping[str, float],
    force_limit_n: float,
    minimum_success_ratio: float,
    maximum_static_rank: int,
) -> list[dict[str, Any]]:
    """Select only supported candidates; otherwise preserve the static baseline."""
    if not rows or len(rows) != len(evidence):
        raise ValueError("rows and memory evidence must have the same nonzero length")
    if force_limit_n <= 0:
        raise ValueError("force_limit_n must be positive")
    if not 0 < minimum_success_ratio <= 1:
        raise ValueError("minimum_success_ratio must be in (0, 1]")
    if maximum_static_rank < 0:
        raise ValueError("maximum_static_rank must be non-negative")
    grouped: dict[str, list[tuple[Mapping[str, Any], dict[str, Any]]]] = defaultdict(list)
    for row, raw_evidence in zip(rows, evidence, strict=True):
        if str(row["candidate_id"]) != str(raw_evidence["candidate_id"]):
            raise ValueError("memory evidence candidate order differs from rows")
        profile = str(row["profile"])
        try:
            distance_limit = _finite_float(
                distance_thresholds[profile], "profile distance threshold"
            )
        except KeyError as exc:
            raise ValueError(f"profile has no distance threshold: {profile}") from exc
        item = dict(raw_evidence)
        neighbor_count = int(item["neighbor_count"])
        required_successes = math.ceil(neighbor_count * minimum_success_ratio)
        reasons = []
        if int(item["unsafe_neighbor_count"]) > 0:
            reasons.append("unsafe_neighbor")
        if int(item["safe_success_neighbor_count"]) < required_successes:
            reasons.append("insufficient_success_support")
        if _finite_float(item["force_upper_n"], "force_upper_n") > force_limit_n:
            reasons.append("neighbor_force_limit")
        if _finite_float(item["kth_distance"], "kth_distance") > distance_limit:
            reasons.append("out_of_distribution")
        if int(row["static_rank"]) > maximum_static_rank:
            reasons.append("static_rank_trust_region")
        item.update(
            {
                "required_success_neighbors": required_successes,
                "distance_threshold": distance_limit,
                "eligible": not reasons,
                "rejection_reasons": reasons,
            }
        )
        grouped[str(row["group_id"])].append((row, item))

    selections = []
    for group_id, candidates in sorted(grouped.items()):
        baseline_row, baseline_evidence = min(
            candidates,
            key=lambda pair: (int(pair[0]["static_rank"]), str(pair[0]["candidate_id"])),
        )
        eligible = [pair for pair in candidates if bool(pair[1]["eligible"])]
        if eligible:
            selected_row, selected_evidence = min(
                eligible,
                key=lambda pair: (
                    -int(pair[1]["safe_success_neighbor_count"]),
                    float(pair[1]["force_upper_n"]),
                    float(pair[1]["kth_distance"]),
                    int(pair[0]["static_rank"]),
                    str(pair[0]["candidate_id"]),
                ),
            )
            decision = "memory_supported"
        else:
            selected_row, selected_evidence = baseline_row, baseline_evidence
            decision = "static_fallback"
        selections.append(
            {
                "group_id": group_id,
                "profile": str(selected_row["profile"]),
                "model_candidate_id": str(selected_row["candidate_id"]),
                "model_success": bool(selected_row["labels"]["success"]),
                "model_safety_aborted": bool(
                    selected_row["labels"]["safety_aborted"]
                ),
                "model_force_n": _finite_float(
                    selected_row["labels"]["max_contact_force_n"], "model force"
                ),
                "model_duration_seconds": _finite_float(
                    selected_row["labels"]["duration_seconds"], "model duration"
                ),
                "baseline_candidate_id": str(baseline_row["candidate_id"]),
                "baseline_success": bool(baseline_row["labels"]["success"]),
                "baseline_safety_aborted": bool(
                    baseline_row["labels"]["safety_aborted"]
                ),
                "baseline_force_n": _finite_float(
                    baseline_row["labels"]["max_contact_force_n"], "baseline force"
                ),
                "baseline_duration_seconds": _finite_float(
                    baseline_row["labels"]["duration_seconds"], "baseline duration"
                ),
                "decision": decision,
                "eligible_candidate_count": len(eligible),
                "memory_evidence": selected_evidence,
            }
        )
    return selections


def summarize_conservative_selections(
    selections: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    if not selections:
        raise ValueError("selection summary requires at least one group")

    def summarize(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
        count = len(rows)
        return {
            "group_count": count,
            "model_successes": sum(bool(row["model_success"]) for row in rows),
            "model_safety_aborts": sum(
                bool(row["model_safety_aborted"]) for row in rows
            ),
            "baseline_successes": sum(bool(row["baseline_success"]) for row in rows),
            "baseline_safety_aborts": sum(
                bool(row["baseline_safety_aborted"]) for row in rows
            ),
            "success_gains": sum(
                bool(row["model_success"]) and not bool(row["baseline_success"])
                for row in rows
            ),
            "success_losses": sum(
                not bool(row["model_success"]) and bool(row["baseline_success"])
                for row in rows
            ),
            "safety_abort_reductions": sum(
                not bool(row["model_safety_aborted"])
                and bool(row["baseline_safety_aborted"])
                for row in rows
            ),
            "safety_abort_regressions": sum(
                bool(row["model_safety_aborted"])
                and not bool(row["baseline_safety_aborted"])
                for row in rows
            ),
            "model_mean_force_n": sum(float(row["model_force_n"]) for row in rows)
            / count,
            "baseline_mean_force_n": sum(
                float(row["baseline_force_n"]) for row in rows
            )
            / count,
            "model_mean_duration_seconds": sum(
                float(row["model_duration_seconds"]) for row in rows
            )
            / count,
            "baseline_mean_duration_seconds": sum(
                float(row["baseline_duration_seconds"]) for row in rows
            )
            / count,
            "static_fallbacks": sum(
                str(row["decision"]) == "static_fallback" for row in rows
            ),
            "changed_from_baseline": sum(
                str(row["model_candidate_id"]) != str(row["baseline_candidate_id"])
                for row in rows
            ),
        }

    result = summarize(selections)
    profiles = sorted({str(row["profile"]) for row in selections})
    result["per_profile"] = {
        profile: summarize(
            [row for row in selections if str(row["profile"]) == profile]
        )
        for profile in profiles
    }
    result["selections"] = [dict(row) for row in selections]
    return result


def audit_cross_validated_candidate(
    name: str,
    summary: Mapping[str, Any],
    fold_summaries: Sequence[Mapping[str, Any]],
    *,
    expected_group_count: int,
    expected_profile_group_count: int,
    max_warm_p95_ms: float,
    warm_p95_ms: float,
) -> dict[str, Any]:
    if not name:
        raise ValueError("candidate name cannot be empty")
    reasons = []
    if int(summary["group_count"]) != expected_group_count:
        reasons.append("incomplete_oof_groups")
    profile_regressions = []
    for profile, row in sorted(summary["per_profile"].items()):
        if int(row["group_count"]) != expected_profile_group_count:
            reasons.append("incomplete_profile_groups")
        if int(row["model_safety_aborts"]) > int(row["baseline_safety_aborts"]):
            profile_regressions.append(profile)
    if profile_regressions:
        reasons.append("per_profile_safety_regression")
    fold_regressions = [
        index
        for index, row in enumerate(fold_summaries)
        if int(row["model_safety_aborts"]) > int(row["baseline_safety_aborts"])
    ]
    if fold_regressions:
        reasons.append("per_fold_safety_regression")
    if not (
        int(summary["model_safety_aborts"])
        < int(summary["baseline_safety_aborts"])
        or int(summary["model_successes"]) > int(summary["baseline_successes"])
    ):
        reasons.append("no_task_or_safety_improvement")
    if warm_p95_ms >= max_warm_p95_ms:
        reasons.append("radeon_latency_gate_failed")
    return {
        "name": name,
        "passes": not reasons,
        "reasons": reasons,
        "profile_regressions": profile_regressions,
        "fold_regressions": fold_regressions,
        "warm_p95_ms": warm_p95_ms,
        "summary": dict(summary),
    }


def select_cross_validated_candidate(
    audits: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    if not audits:
        raise ValueError("provide at least one cross-validated candidate")
    eligible = [row for row in audits if bool(row["passes"])]
    if not eligible:
        return {
            "status": "no_cv_candidate",
            "selected": None,
            "new_physics_authorized": False,
        }
    selected = min(
        eligible,
        key=lambda row: (
            int(row["summary"]["model_safety_aborts"]),
            -int(row["summary"]["model_successes"]),
            float(row["summary"]["model_mean_force_n"]),
            int(row["summary"]["changed_from_baseline"]),
            float(row["warm_p95_ms"]),
            str(row["name"]),
        ),
    )
    return {
        "status": "cv_candidate_found",
        "selected": str(selected["name"]),
        "new_physics_authorized": False,
    }
