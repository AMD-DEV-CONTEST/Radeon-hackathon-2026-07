from __future__ import annotations

import hashlib
import json
import math
from typing import Any, Mapping, Sequence

from .config import ExperimentConfig
from .cylinder_grasp_planning import (
    CylinderGraspPoseCandidate,
    plan_cylinder_grasp_candidates,
)
from .randomization import DomainRandomizer, ParcelSample


def audit_cylinder_candidate_population(
    config: ExperimentConfig,
    protocol: Mapping[str, Any],
) -> dict[str, Any]:
    """Audit a deterministic outcome-free population without constructing physics."""
    population = protocol["population"]
    planner = protocol["planner"]
    gates = protocol["gates"]
    profile_ids = tuple(str(value) for value in population["profile_ids"])
    episode_starts = {
        str(key): int(value)
        for key, value in population["episode_starts"].items()
    }
    episodes_per_profile = int(population["episodes_per_profile"])
    expected_samples = int(population["expected_samples"])
    errors: list[str] = []
    if (
        episodes_per_profile < 1
        or expected_samples != len(profile_ids) * episodes_per_profile
    ):
        errors.append("population_size_contract")
    if set(episode_starts) != set(profile_ids):
        errors.append("episode_start_profiles")

    configured_profiles = {
        profile.profile_id: profile for profile in config.parcel_profiles
    }
    for profile_id in profile_ids:
        profile = configured_profiles.get(profile_id)
        if profile is None:
            errors.append(f"missing_profile:{profile_id}")
        elif profile.shape != "cylinder" or profile.handling_class != "parallel_jaw":
            errors.append(f"unsupported_profile:{profile_id}")

    randomizer = DomainRandomizer(
        config.randomization,
        config.seed,
        config.parcel_profiles,
    )
    records: list[dict[str, Any]] = []
    for profile_id in profile_ids:
        if profile_id not in configured_profiles or profile_id not in episode_starts:
            continue
        for offset in range(episodes_per_profile):
            episode = episode_starts[profile_id] + offset
            sample = randomizer.sample_profile(profile_id, episode)
            pose = initial_cylinder_pose(sample)
            plan = plan_cylinder_grasp_candidates(
                sample,
                pose,
                hand_clearance_m=float(planner["hand_clearance_m"]),
                jaw_aperture_m=float(planner["jaw_aperture_m"]),
                min_aperture_margin_m=float(planner["min_aperture_margin_m"]),
                min_horizontal_rolling_friction=float(
                    planner["min_horizontal_rolling_friction"]
                ),
                max_parallel_jaw_length_m=float(
                    planner["max_parallel_jaw_length_m"]
                ),
                max_axis_tilt_deg=float(planner["max_axis_tilt_deg"]),
                include_symmetric_wrist=bool(planner["include_symmetric_wrist"]),
                upright_radial_yaw_count=int(planner["upright_radial_yaw_count"]),
                max_upright_vertical_offset_m=float(
                    planner["max_upright_vertical_offset_m"]
                ),
                min_upright_side_overlap_m=float(
                    planner["min_upright_side_overlap_m"]
                ),
                max_horizontal_axial_offset_m=float(
                    planner["max_horizontal_axial_offset_m"]
                ),
                min_horizontal_end_margin_m=float(
                    planner["min_horizontal_end_margin_m"]
                ),
                horizontal_radial_angles_deg=tuple(
                    float(value) for value in planner["horizontal_radial_angles_deg"]
                ),
            )
            record = _sample_record(sample, episode, pose, plan.candidates)
            record.update(
                {
                    "supported": plan.capability.supported,
                    "capability_reason": plan.capability.reason,
                    "aperture_margin_m": plan.capability.aperture_margin_m,
                    "rolling_risk_index": plan.capability.rolling_risk_index,
                }
            )
            records.append(record)

    if len(records) != expected_samples:
        errors.append("observed_sample_count")
    min_candidates = int(gates["min_candidates_per_sample"])
    maximum_quaternion_norm_error = float(gates["max_quaternion_norm_error"])
    maximum_axis_alignment_error = float(gates["max_axis_alignment_error"])
    for record in records:
        key = f"{record['profile_id']}:{record['episode']}"
        if not record["supported"]:
            errors.append(f"unsupported_sample:{key}")
        if int(record["candidate_count"]) < min_candidates:
            errors.append(f"candidate_count:{key}")
        if int(record["unique_candidate_count"]) != int(record["candidate_count"]):
            errors.append(f"duplicate_candidate:{key}")
        if float(record["max_quaternion_norm_error"]) > maximum_quaternion_norm_error:
            errors.append(f"quaternion_norm:{key}")
        if float(record["max_axis_alignment_error"]) > maximum_axis_alignment_error:
            errors.append(f"axis_alignment:{key}")
        if float(record["max_approach_axis_dot"]) > maximum_axis_alignment_error:
            errors.append(f"approach_axis_alignment:{key}")
        if not bool(record["all_finite"]):
            errors.append(f"nonfinite_candidate:{key}")

    summaries = {
        profile_id: _profile_summary(
            tuple(row for row in records if row["profile_id"] == profile_id)
        )
        for profile_id in profile_ids
    }
    canonical_records = json.dumps(
        records,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return {
        "schema_version": "1.0",
        "status": (
            "candidate_population_valid"
            if not errors
            else "candidate_population_invalid"
        ),
        "protocol_id": str(protocol["metadata"]["protocol_id"]),
        "selection_contract": {
            "outcome_fields_read": [],
            "scene_constructed": False,
            "robot_action_executed": False,
            "physics_stepped": False,
        },
        "expected_samples": expected_samples,
        "observed_samples": len(records),
        "profile_summaries": summaries,
        "population_sha256": hashlib.sha256(canonical_records).hexdigest(),
        "samples": records,
        "errors": list(dict.fromkeys(errors)),
    }


def initial_cylinder_pose(sample: ParcelSample) -> tuple[float, ...]:
    """Return the deterministic Genesis spawn pose in wxyz convention."""
    if sample.shape != "cylinder" or sample.dimensions_m is None:
        raise ValueError("initial cylinder pose requires explicit cylinder dimensions")
    half_yaw = sample.yaw_rad / 2
    if sample.orientation_mode == "upright":
        quaternion = (math.cos(half_yaw), 0.0, 0.0, math.sin(half_yaw))
        centre_z_m = sample.dimensions_m[2] / 2
    elif sample.orientation_mode == "horizontal":
        half_pitch = math.pi / 4
        quaternion = (
            math.cos(half_yaw) * math.cos(half_pitch),
            -math.sin(half_yaw) * math.sin(half_pitch),
            math.cos(half_yaw) * math.sin(half_pitch),
            math.sin(half_yaw) * math.cos(half_pitch),
        )
        centre_z_m = sample.dimensions_m[1] / 2
    else:
        raise ValueError("cylinder orientation must be upright or horizontal")
    return (*sample.position_xy, centre_z_m, *quaternion)


def _sample_record(
    sample: ParcelSample,
    episode: int,
    pose: Sequence[float],
    candidates: Sequence[CylinderGraspPoseCandidate],
) -> dict[str, Any]:
    expected_axis = (
        (0.0, 0.0, 1.0)
        if sample.orientation_mode == "upright"
        else (math.cos(sample.yaw_rad), math.sin(sample.yaw_rad), 0.0)
    )
    quaternion_errors = []
    alignment_errors = []
    approach_axis_dots = []
    all_finite = True
    for candidate in candidates:
        values = (
            *candidate.target_position,
            *candidate.target_quaternion,
            *candidate.approach_direction,
            candidate.longitudinal_offset_m,
            candidate.vertical_offset_m,
            candidate.rolling_risk_score,
        )
        all_finite = all_finite and all(math.isfinite(value) for value in values)
        quaternion_errors.append(
            abs(
                math.sqrt(
                    sum(value * value for value in candidate.target_quaternion)
                )
                - 1.0
            )
        )
        if sample.orientation_mode == "horizontal":
            local_x = _rotation_column(candidate.target_quaternion, 0)
            alignment_errors.append(abs(abs(_dot(local_x, expected_axis)) - 1.0))
            approach_axis_dots.append(
                abs(_dot(candidate.approach_direction, expected_axis))
            )
        else:
            alignment_errors.append(0.0)
            approach_axis_dots.append(0.0)
    return {
        "profile_id": sample.profile_id,
        "episode": episode,
        "orientation_mode": sample.orientation_mode,
        "dimensions_m": list(sample.dimensions_m or ()),
        "mass_kg": sample.mass_kg,
        "friction": sample.friction,
        "rolling_friction": sample.rolling_friction,
        "position_xy": list(sample.position_xy),
        "yaw_rad": sample.yaw_rad,
        "pose": list(pose),
        "candidate_count": len(candidates),
        "unique_candidate_count": len(
            {candidate.candidate_id for candidate in candidates}
        ),
        "max_quaternion_norm_error": max(quaternion_errors, default=math.inf),
        "max_axis_alignment_error": max(alignment_errors, default=math.inf),
        "max_approach_axis_dot": max(approach_axis_dots, default=math.inf),
        "all_finite": all_finite,
    }


def _profile_summary(records: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    if not records:
        return {"sample_count": 0}
    dimensions = tuple(
        tuple(float(value) for value in row["dimensions_m"])
        for row in records
    )
    return {
        "sample_count": len(records),
        "supported_count": sum(bool(row["supported"]) for row in records),
        "candidate_count_min": min(int(row["candidate_count"]) for row in records),
        "candidate_count_max": max(int(row["candidate_count"]) for row in records),
        "dimensions_observed_min_m": [
            min(values) for values in zip(*dimensions, strict=True)
        ],
        "dimensions_observed_max_m": [
            max(values) for values in zip(*dimensions, strict=True)
        ],
        "aperture_margin_min_m": min(
            float(row["aperture_margin_m"]) for row in records
        ),
        "aperture_margin_max_m": max(
            float(row["aperture_margin_m"]) for row in records
        ),
        "rolling_risk_index_max": max(
            float(row["rolling_risk_index"]) for row in records
        ),
        "max_quaternion_norm_error": max(
            float(row["max_quaternion_norm_error"]) for row in records
        ),
        "max_axis_alignment_error": max(
            float(row["max_axis_alignment_error"]) for row in records
        ),
        "max_approach_axis_dot": max(
            float(row["max_approach_axis_dot"]) for row in records
        ),
    }


def _rotation_column(
    quaternion: Sequence[float],
    index: int,
) -> tuple[float, float, float]:
    w, x, y, z = quaternion
    columns = (
        (1 - 2 * (y * y + z * z), 2 * (x * y + w * z), 2 * (x * z - w * y)),
        (2 * (x * y - w * z), 1 - 2 * (x * x + z * z), 2 * (y * z + w * x)),
        (2 * (x * z + w * y), 2 * (y * z - w * x), 1 - 2 * (x * x + y * y)),
    )
    return columns[index]


def _dot(left: Sequence[float], right: Sequence[float]) -> float:
    return float(sum(a * b for a, b in zip(left, right, strict=True)))
