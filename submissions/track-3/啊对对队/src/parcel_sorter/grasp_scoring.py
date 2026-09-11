from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
import tomllib
from typing import Any, Iterable, Mapping, Sequence


GRASP_FEATURE_SCHEMA_VERSION = 1
GRASP_FEATURE_NAMES = (
    "parcel_size_x_m",
    "parcel_size_y_m",
    "parcel_size_z_m",
    "parcel_mass_kg",
    "parcel_friction",
    "parcel_rolling_friction",
    "spawn_x_m",
    "spawn_y_m",
    "spawn_yaw_sin",
    "spawn_yaw_cos",
    "action_delay_steps",
    "destination_side",
    "target_dx_m",
    "target_dy_m",
    "target_z_m",
    "target_qw",
    "target_qx",
    "target_qy",
    "target_qz",
    "longitudinal_offset_m",
    "vertical_offset_m",
    "wrist_is_symmetric_pi",
    "seed_is_historical_reset",
    "seed_is_collision_free_reset",
    "minimum_singular_value",
    "joint_distance_rad",
    "nonfinger_clearance_m",
    "static_rank",
)
GRASP_LABEL_NAMES = (
    "safety_aborted",
    "success",
    "max_contact_force_n",
    "duration_seconds",
)

GRASP_COLLECTION_ACTIVATION_POLICIES = {
    "reset-fallback",
    "geometry-eligible",
}


def sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def canonical_payload_sha256(payload: Mapping[str, Any]) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def load_grasp_split_protocol(path: str | Path) -> dict[tuple[str, int], str]:
    with Path(path).open("rb") as handle:
        payload = tomllib.load(handle)
    assignments: dict[tuple[str, int], str] = {}
    for row in payload.get("splits", ()):  # type: ignore[union-attr]
        split = str(row["name"])
        profile = str(row["profile_id"])
        for episode in row["episode_ids"]:
            key = (profile, int(episode))
            if key in assignments:
                raise ValueError(
                    f"duplicate grasp split assignment for {profile} episode {episode}"
                )
            assignments[key] = split
    if not assignments:
        raise ValueError("grasp split protocol contains no episode assignments")
    return assignments


def load_grasp_collection_activation_policy(path: str | Path) -> str:
    """Return the frozen controller branch used to generate candidate labels."""
    with Path(path).open("rb") as handle:
        payload = tomllib.load(handle)
    collection = payload.get("collection", {})
    policy = str(collection.get("planning_activation_policy", "reset-fallback"))
    if policy not in GRASP_COLLECTION_ACTIVATION_POLICIES:
        raise ValueError(f"unsupported grasp collection activation policy: {policy}")
    return policy


def _finite_float(value: Any, name: str) -> float:
    result = float(value)
    if not math.isfinite(result):
        raise ValueError(f"{name} must be finite")
    return result


def _finite_vector(value: Any, length: int, name: str) -> tuple[float, ...]:
    result = tuple(_finite_float(item, name) for item in value)
    if len(result) != length:
        raise ValueError(f"{name} must contain {length} values")
    return result


def _static_row_by_candidate(payload: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    rows: dict[str, Mapping[str, Any]] = {}
    for row in payload.get("static_feasible_candidates", ()):  # type: ignore[union-attr]
        candidate_id = str(row["candidate_id"])
        if candidate_id in rows:
            raise ValueError(f"duplicate static candidate: {candidate_id}")
        rows[candidate_id] = row
    if not rows:
        raise ValueError("counterfactual payload has no static feasible candidates")
    return rows


def grasp_candidate_feature_vector(
    payload: Mapping[str, Any],
    rollout: Mapping[str, Any],
) -> tuple[float, ...]:
    sample = payload["sample"]
    if not isinstance(sample, Mapping):
        raise ValueError("counterfactual sample must be a mapping")
    candidate_id = str(rollout["candidate_id"])
    try:
        static = _static_row_by_candidate(payload)[candidate_id]
    except KeyError as exc:
        raise ValueError(f"missing static row for candidate {candidate_id}") from exc

    dimensions = _finite_vector(sample["dimensions_m"], 3, "dimensions_m")
    position = _finite_vector(sample["position_xy"], 2, "position_xy")
    target = _finite_vector(static["target_position"], 3, "target_position")
    quaternion = _finite_vector(static["target_quaternion"], 4, "target_quaternion")
    yaw = _finite_float(sample["yaw_rad"], "yaw_rad")
    destination = str(sample["destination"])
    if destination not in {"left", "right"}:
        raise ValueError(f"unsupported destination: {destination}")
    seed_name = str(static["seed_name"])
    if seed_name not in {"current", "historical_reset", "collision_free_reset"}:
        raise ValueError(f"unsupported IK seed: {seed_name}")
    wrist_variant = str(static["wrist_variant"])
    if wrist_variant not in {"canonical", "symmetric_pi"}:
        raise ValueError(f"unsupported wrist variant: {wrist_variant}")

    values = (
        *dimensions,
        _finite_float(sample["mass_kg"], "mass_kg"),
        _finite_float(sample["friction"], "friction"),
        _finite_float(sample["rolling_friction"], "rolling_friction"),
        *position,
        math.sin(yaw),
        math.cos(yaw),
        _finite_float(sample["action_delay_steps"], "action_delay_steps"),
        1.0 if destination == "right" else -1.0,
        target[0] - position[0],
        target[1] - position[1],
        target[2],
        *quaternion,
        _finite_float(static["longitudinal_offset_m"], "longitudinal_offset_m"),
        _finite_float(static["vertical_offset_m"], "vertical_offset_m"),
        1.0 if wrist_variant == "symmetric_pi" else 0.0,
        1.0 if seed_name == "historical_reset" else 0.0,
        1.0 if seed_name == "collision_free_reset" else 0.0,
        _finite_float(static["minimum_singular_value"], "minimum_singular_value"),
        _finite_float(static["joint_distance_rad"], "joint_distance_rad"),
        _finite_float(static["nonfinger_clearance_m"], "nonfinger_clearance_m"),
        _finite_float(static["static_rank"], "static_rank"),
    )
    if len(values) != len(GRASP_FEATURE_NAMES):
        raise AssertionError("grasp feature implementation does not match schema")
    return tuple(float(value) for value in values)


def counterfactual_rows(
    payload: Mapping[str, Any],
    *,
    source: str,
    split: str,
) -> list[dict[str, Any]]:
    if str(payload.get("status", "complete")) != "complete":
        raise ValueError("counterfactual source did not generate labels")
    contract = payload.get("contract")
    if not isinstance(contract, Mapping):
        raise ValueError("counterfactual payload has no contract")
    if not contract.get("controller_faithful") or not contract.get("fresh_scene_per_rollout"):
        raise ValueError("labels require controller-faithful fresh-scene rollouts")
    force_abort_n = _finite_float(contract["force_abort_n"], "force_abort_n")
    if force_abort_n <= 0:
        raise ValueError("force_abort_n must be positive")

    profile = str(payload["profile"])
    episode = int(payload["episode"])
    rows: list[dict[str, Any]] = []
    seen: set[tuple[str, int]] = set()
    for rollout in payload.get("rollouts", ()):  # type: ignore[union-attr]
        candidate_id = str(rollout["candidate_id"])
        repeat = int(rollout["repeat"])
        key = (candidate_id, repeat)
        if key in seen:
            raise ValueError(f"duplicate rollout label: {candidate_id} repeat {repeat}")
        seen.add(key)
        if str(rollout["selected_candidate_id"]) != candidate_id:
            raise ValueError(
                f"requested/selected candidate mismatch for {candidate_id} repeat {repeat}"
            )
        max_force = _finite_float(
            rollout["max_contact_force_n"], "max_contact_force_n"
        )
        duration = _finite_float(rollout["duration_seconds"], "duration_seconds")
        safety_aborted = bool(rollout["safety_aborted"])
        if safety_aborted != (max_force > force_abort_n):
            raise ValueError(
                f"force-abort label mismatch for {candidate_id} repeat {repeat}"
            )
        success = bool(rollout["success"])
        if success and safety_aborted:
            raise ValueError("a safety-aborted rollout cannot be labeled successful")
        rows.append(
            {
                "source": source,
                "split": split,
                "group_id": f"{profile}:{episode}",
                "profile": profile,
                "episode": episode,
                "candidate_id": candidate_id,
                "repeat": repeat,
                "static_rank": int(rollout["static_rank"]),
                "features": list(grasp_candidate_feature_vector(payload, rollout)),
                "labels": {
                    "safety_aborted": safety_aborted,
                    "success": success,
                    "max_contact_force_n": max_force,
                    "duration_seconds": duration,
                },
            }
        )
    if not rows:
        raise ValueError("counterfactual payload has no rollout labels")
    return rows


def build_grasp_candidate_dataset(
    sources: Iterable[tuple[str, Mapping[str, Any], str, str]],
) -> dict[str, Any]:
    artifacts: list[dict[str, str]] = []
    rows: list[dict[str, Any]] = []
    seen_sources: set[str] = set()
    seen_labels: set[tuple[str, int, str, int]] = set()
    for source, payload, source_sha256, split in sources:
        if source in seen_sources:
            raise ValueError(f"duplicate grasp dataset source: {source}")
        seen_sources.add(source)
        artifacts.append({"path": source, "sha256": source_sha256})
        source_rows = counterfactual_rows(payload, source=source, split=split)
        for row in source_rows:
            key = (
                str(row["profile"]),
                int(row["episode"]),
                str(row["candidate_id"]),
                int(row["repeat"]),
            )
            if key in seen_labels:
                raise ValueError(
                    "duplicate grasp label across sources: "
                    f"{key[0]} episode {key[1]} {key[2]} repeat {key[3]}"
                )
            seen_labels.add(key)
        rows.extend(source_rows)
    if not rows:
        raise ValueError("grasp candidate dataset requires at least one source")
    result: dict[str, Any] = {
        "schema_version": 1,
        "feature_schema_version": GRASP_FEATURE_SCHEMA_VERSION,
        "feature_names": list(GRASP_FEATURE_NAMES),
        "label_names": list(GRASP_LABEL_NAMES),
        "source_artifacts": artifacts,
        "row_count": len(rows),
        "group_count": len({str(row["group_id"]) for row in rows}),
        "splits": {
            split: sum(row["split"] == split for row in rows)
            for split in sorted({str(row["split"]) for row in rows})
        },
        "rows": rows,
    }
    result["dataset_sha256"] = canonical_payload_sha256(result)
    return result


def grouped_grasp_row_indices(
    rows: Sequence[Mapping[str, Any]],
) -> tuple[tuple[int, ...], ...]:
    """Return stable candidate indices grouped by physical episode."""
    if not rows:
        raise ValueError("grasp rows cannot be empty")
    groups: dict[str, list[int]] = {}
    for index, row in enumerate(rows):
        group_id = str(row.get("group_id", ""))
        if not group_id:
            raise ValueError("every grasp row requires a group_id")
        groups.setdefault(group_id, []).append(index)
    return tuple(tuple(groups[group_id]) for group_id in sorted(groups))


def groupwise_grasp_preference_pairs(
    rows: Sequence[Mapping[str, Any]],
) -> dict[str, tuple[tuple[tuple[int, int], ...], ...]]:
    """Build within-episode lexicographic safety and success preferences.

    Each pair is ``(preferred, disfavored)``. Safety pairs compare every safe
    candidate against every force-aborted candidate. Success pairs compare
    successful candidates only against other safe candidates, so success can
    never compensate for a safety violation.
    """
    safety_groups: list[tuple[tuple[int, int], ...]] = []
    success_groups: list[tuple[tuple[int, int], ...]] = []
    for indices in grouped_grasp_row_indices(rows):
        safe = [
            index
            for index in indices
            if not bool(rows[index]["labels"]["safety_aborted"])
        ]
        unsafe = [
            index
            for index in indices
            if bool(rows[index]["labels"]["safety_aborted"])
        ]
        safety_pairs = tuple((left, right) for left in safe for right in unsafe)
        if safety_pairs:
            safety_groups.append(safety_pairs)

        successful = [
            index for index in safe if bool(rows[index]["labels"]["success"])
        ]
        safe_failures = [
            index for index in safe if not bool(rows[index]["labels"]["success"])
        ]
        success_pairs = tuple(
            (left, right) for left in successful for right in safe_failures
        )
        if success_pairs:
            success_groups.append(success_pairs)
    return {
        "safety": tuple(safety_groups),
        "success": tuple(success_groups),
    }


def grasp_prediction_rank_key(
    prediction: Mapping[str, Any],
    *,
    unsafe_probability_threshold: float = 0.5,
) -> tuple[Any, ...]:
    if not 0 < unsafe_probability_threshold < 1:
        raise ValueError("unsafe_probability_threshold must be between zero and one")
    unsafe = _finite_float(prediction["unsafe_probability"], "unsafe_probability")
    success = _finite_float(prediction["success_probability"], "success_probability")
    force = _finite_float(prediction["predicted_force_n"], "predicted_force_n")
    duration = _finite_float(
        prediction["predicted_duration_seconds"], "predicted_duration_seconds"
    )
    if not 0 <= unsafe <= 1 or not 0 <= success <= 1:
        raise ValueError("prediction probabilities must be within [0, 1]")
    return (
        unsafe >= unsafe_probability_threshold,
        unsafe,
        -success,
        force,
        duration,
        int(prediction.get("static_rank", 2**31 - 1)),
        str(prediction.get("candidate_id", "")),
    )


def evaluate_ranked_grasp_predictions(
    rows: Sequence[Mapping[str, Any]],
    predictions: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    if not rows or len(rows) != len(predictions):
        raise ValueError("rows and predictions must contain the same nonzero items")
    groups: dict[str, list[tuple[Mapping[str, Any], Mapping[str, Any]]]] = {}
    for row, prediction in zip(rows, predictions, strict=True):
        if str(row["candidate_id"]) != str(prediction["candidate_id"]):
            raise ValueError("prediction candidate order does not match dataset rows")
        groups.setdefault(str(row["group_id"]), []).append((row, prediction))
    selected: list[dict[str, Any]] = []
    for group_id, candidates in sorted(groups.items()):
        model_row, model_prediction = min(
            candidates,
            key=lambda pair: grasp_prediction_rank_key(pair[1]),
        )
        baseline_row, _ = min(candidates, key=lambda pair: int(pair[0]["static_rank"]))
        selected.append(
            {
                "group_id": group_id,
                "profile": str(model_row["profile"]),
                "model_candidate_id": model_row["candidate_id"],
                "model_success": bool(model_row["labels"]["success"]),
                "model_safety_aborted": bool(
                    model_row["labels"]["safety_aborted"]
                ),
                "model_force_n": _finite_float(
                    model_row["labels"]["max_contact_force_n"],
                    "model_force_n",
                ),
                "model_duration_seconds": _finite_float(
                    model_row["labels"]["duration_seconds"],
                    "model_duration_seconds",
                ),
                "baseline_candidate_id": baseline_row["candidate_id"],
                "baseline_success": bool(baseline_row["labels"]["success"]),
                "baseline_safety_aborted": bool(
                    baseline_row["labels"]["safety_aborted"]
                ),
                "baseline_force_n": _finite_float(
                    baseline_row["labels"]["max_contact_force_n"],
                    "baseline_force_n",
                ),
                "baseline_duration_seconds": _finite_float(
                    baseline_row["labels"]["duration_seconds"],
                    "baseline_duration_seconds",
                ),
                "model_prediction": dict(model_prediction),
            }
        )

    def summarize(group_rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
        count = len(group_rows)
        if count < 1:
            raise ValueError("ranked grasp summary requires at least one group")
        return {
            "group_count": count,
            "model_successes": sum(bool(row["model_success"]) for row in group_rows),
            "model_safety_aborts": sum(
                bool(row["model_safety_aborted"]) for row in group_rows
            ),
            "baseline_successes": sum(
                bool(row["baseline_success"]) for row in group_rows
            ),
            "baseline_safety_aborts": sum(
                bool(row["baseline_safety_aborted"]) for row in group_rows
            ),
            "success_gains": sum(
                bool(row["model_success"]) and not bool(row["baseline_success"])
                for row in group_rows
            ),
            "success_losses": sum(
                not bool(row["model_success"]) and bool(row["baseline_success"])
                for row in group_rows
            ),
            "safety_abort_reductions": sum(
                not bool(row["model_safety_aborted"])
                and bool(row["baseline_safety_aborted"])
                for row in group_rows
            ),
            "safety_abort_regressions": sum(
                bool(row["model_safety_aborted"])
                and not bool(row["baseline_safety_aborted"])
                for row in group_rows
            ),
            "model_mean_force_n": sum(
                float(row["model_force_n"]) for row in group_rows
            )
            / count,
            "baseline_mean_force_n": sum(
                float(row["baseline_force_n"]) for row in group_rows
            )
            / count,
            "model_mean_duration_seconds": sum(
                float(row["model_duration_seconds"]) for row in group_rows
            )
            / count,
            "baseline_mean_duration_seconds": sum(
                float(row["baseline_duration_seconds"]) for row in group_rows
            )
            / count,
        }

    result = summarize(selected)
    profiles = sorted({str(row["profile"]) for row in selected})
    result.update(
        {
            "per_profile": {
                profile: summarize(
                    [row for row in selected if str(row["profile"]) == profile]
                )
                for profile in profiles
            },
            "selected": selected,
        }
    )
    return result
def validate_feature_names(feature_names: Sequence[str]) -> None:
    if tuple(feature_names) != GRASP_FEATURE_NAMES:
        raise ValueError("grasp feature schema does not match the runtime contract")
