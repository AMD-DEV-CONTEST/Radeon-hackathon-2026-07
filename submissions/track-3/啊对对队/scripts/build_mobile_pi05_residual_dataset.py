#!/usr/bin/env python3
"""Convert verified mobile primitives into the PI0.5 residual seed contract."""

from __future__ import annotations

import argparse
from collections import deque
import hashlib
import json
import math
from pathlib import Path
import re
import shutil
import tomllib
from typing import Any

from parcel_sorter.mobile_dataset import (
    MOBILE_STAGE_NAMES,
    infer_mobile_policy_modality,
    mobile_policy_visual_keys,
)
from parcel_sorter.mobile_grasp_routing import route_mobile_grasp
from parcel_sorter.mobile_pi05_contract import (
    MOBILE_PI05_ABSOLUTE_ACTION_NAMES,
    MOBILE_PI05_ABSOLUTE_STATE_NAMES,
    MOBILE_PI05_RESIDUAL_ACTION_NAMES,
    MOBILE_PI05_STATE_NAMES,
    PI05_FORCE_HISTORY_LENGTH,
    PI05_GRASP_MODES,
    PI05ResidualContext,
    build_primitive_progress_targets,
    build_pi05_recovery_residual,
    encode_pi05_absolute_state,
    encode_pi05_state,
    smooth_lift_residual_fraction,
)
from parcel_sorter.mobile_pi05_normalization import (
    constant_dimensions,
    stabilize_quantile_stats,
)


STAT_KEYS = ("min", "max", "mean", "std", "q01", "q10", "q50", "q90", "q99")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--catalog", type=Path, default=Path("configs/catalog_v2.toml"))
    parser.add_argument(
        "--action-contract",
        choices=("residual_v1", "absolute_v1"),
        default="residual_v1",
    )
    parser.add_argument(
        "--collection-summary",
        type=Path,
        help=(
            "collector summary whose successful recovery labels correspond to the "
            "merged source episodes; omit only for zero-residual seed conversion"
        ),
    )
    args = parser.parse_args()
    if not (args.source / "meta/info.json").is_file():
        parser.error("source must be a LeRobot dataset")
    if args.output.exists():
        parser.error("output must not already exist")

    import numpy as np
    import pyarrow as pa
    import pyarrow.parquet as pq

    source = args.source.resolve()
    output = args.output.resolve()
    absolute_contract = args.action_contract == "absolute_v1"
    state_names = (
        MOBILE_PI05_ABSOLUTE_STATE_NAMES
        if absolute_contract
        else MOBILE_PI05_STATE_NAMES
    )
    action_names = (
        MOBILE_PI05_ABSOLUTE_ACTION_NAMES
        if absolute_contract
        else MOBILE_PI05_RESIDUAL_ACTION_NAMES
    )
    source_info = json.loads((source / "meta/info.json").read_text(encoding="utf-8"))
    policy_visual_modality = infer_mobile_policy_modality(
        source_info.get("features", {})
    )
    policy_visual_keys = list(mobile_policy_visual_keys(policy_visual_modality))
    profiles = _profile_defaults(args.catalog)
    task_rows = pq.read_table(source / "meta/tasks.parquet").to_pylist()
    tasks = {int(row["task_index"]): str(row["task"]) for row in task_rows}
    source_files = sorted(source.glob("data/**/*.parquet"))
    if not source_files:
        parser.error("source contains no parquet episodes")
    source_episode_indices = sorted(
        {
            int(value)
            for path in source_files
            for value in pq.read_table(path, columns=["episode_index"])
            .column("episode_index")
            .to_pylist()
        }
    )
    recovery_labels = _load_recovery_labels(
        args.collection_summary,
        source_episode_indices,
    )
    source_hashes = {_relative(path, source): _sha256(path) for path in source_files}
    shutil.copytree(source, output)

    all_states: list[list[float]] = []
    all_actions: list[list[float]] = []
    episode_stats: dict[int, dict[str, dict[str, list[float]]]] = {}
    episode_manifests = []
    for source_path in source_files:
        table = pq.read_table(source_path)
        rows = table.select(
            ["episode_index", "task_index", "observation.stage_id", "observation.state", "action"]
        ).to_pylist()
        inferred_progress = build_primitive_progress_targets(
            MOBILE_STAGE_NAMES[_stage_id(row["observation.stage_id"])] for row in rows
        )
        left_history: deque[float] = deque(maxlen=PI05_FORCE_HISTORY_LENGTH)
        right_history: deque[float] = deque(maxlen=PI05_FORCE_HISTORY_LENGTH)
        converted_states = []
        converted_actions = []
        profiles_seen: set[str] = set()
        modes_seen: set[str] = set()
        nonzero_contact_residual_frames = 0
        nonzero_base_command_frames = 0
        recovery_source_episode_id = None
        for row_index, row in enumerate(rows):
            state = tuple(float(value) for value in row["observation.state"])
            action = tuple(float(value) for value in row["action"])
            if len(state) != 43 or len(action) not in {19, 20}:
                raise ValueError("source must use the 43-D/19-or-20-D mobile contract")
            task = tasks[int(row["task_index"])]
            episode_index = int(row["episode_index"])
            recovery = recovery_labels[episode_index]
            profile_id = recovery.get("profile_id") or _profile_from_task(task, profiles)
            if profile_id not in profiles:
                raise ValueError(
                    f"collector profile is absent from catalog: {profile_id!r}"
                )
            profile = {**profiles[profile_id], **recovery.get("profile", {})}
            recovery_source_episode_id = recovery.get("episode_id")
            profiles_seen.add(profile_id)
            modes_seen.add(str(profile["grasp_mode"]))
            stage = MOBILE_STAGE_NAMES[_stage_id(row["observation.stage_id"])]
            left_history.append(abs(state[38]))
            right_history.append(abs(state[39]))
            sealed_count = profile["minimum_sealed_cups"] if abs(state[38]) > 0.5 else 0
            primitive_progress = (
                float(action[19]) if len(action) == 20 else inferred_progress[row_index]
            )
            left_contact_offset = None
            right_contact_offset = None
            if stage in {"lift", "transport"}:
                engagement_delta = float(recovery["cradle_engagement_delta_m"])
                lift_fraction = (
                    smooth_lift_residual_fraction(
                        primitive_progress,
                        float(recovery["vertical_speed_scale"]),
                    )
                    if stage == "lift"
                    else 1.0
                )
                left_lift_offset = tuple(
                    float(value) * lift_fraction
                    for value in recovery["left_lift_offset_m"]
                )
                right_lift_offset = tuple(
                    float(value) * lift_fraction
                    for value in recovery["right_lift_offset_m"]
                )
                if max(map(abs, left_lift_offset)) > 0.0:
                    left_contact_offset = left_lift_offset
                candidate_right_offset = tuple(
                    float(recovery["right_tool_axis_world"][index])
                    * engagement_delta
                    + right_lift_offset[index]
                    for index in range(3)
                )
                if max(map(abs, candidate_right_offset)) > 0.0:
                    right_contact_offset = candidate_right_offset
            recovery_residual = build_pi05_recovery_residual(
                contact_offset_m=recovery["contact_offset_m"],
                contact_penetration_delta_m=float(
                    recovery["contact_penetration_delta_m"]
                ),
                approach_axis_world=recovery["approach_axis_world"],
                left_contact_offset_m=left_contact_offset,
                right_contact_offset_m=right_contact_offset,
                stage=stage,
                grasp_mode=profile["grasp_mode"],
            )
            left_residual = recovery_residual.left_contact_residual_m
            right_residual = recovery_residual.right_contact_residual_m
            if max((*map(abs, left_residual), *map(abs, right_residual))) > 1e-7:
                nonzero_contact_residual_frames += 1
            if max(map(abs, action[:3])) > 1e-7:
                nonzero_base_command_frames += 1
            context = PI05ResidualContext(
                sealed_cup_mask=tuple(index < sealed_count for index in range(3)),
                parcel_shape=profile["shape"],
                parcel_size_m=profile["size_m"],
                parcel_mass_kg=profile["mass_kg"],
                grasp_mode=profile["grasp_mode"],
                retry_index=int(recovery["retry_index"]),
                stage=stage,
                left_force_history_n=tuple(left_history),
                right_force_history_n=tuple(right_history),
                left_contact_anchor_m=tuple(
                    action[3 + index] - left_residual[index] for index in range(3)
                ),
                right_contact_anchor_m=tuple(
                    action[11 + index] - right_residual[index] for index in range(3)
                ),
                grasp_mode_conditioned=False,
            )
            converted_states.append(
                list(
                    encode_pi05_absolute_state(state, context)
                    if absolute_contract
                    else encode_pi05_state(state, context)
                )
            )
            mode_logits = [
                1.0 if name == profile["grasp_mode"] else -1.0
                for name in PI05_GRASP_MODES
            ]
            converted_actions.append(
                [*action[:19], *mode_logits, primitive_progress]
                if absolute_contract
                else [
                    0.0,
                    0.0,
                    0.0,
                    *left_residual,
                    *right_residual,
                    *mode_logits,
                    float(action[10]),
                    primitive_progress,
                ]
            )
        state_index = table.schema.get_field_index("observation.state")
        action_index = table.schema.get_field_index("action")
        table = table.set_column(
            state_index,
            "observation.state",
            pa.array(converted_states, type=pa.list_(pa.float32(), len(state_names))),
        )
        table = table.set_column(
            action_index,
            "action",
            pa.array(
                converted_actions,
                type=pa.list_(pa.float32(), len(action_names)),
            ),
        )
        destination = output / source_path.relative_to(source)
        pq.write_table(table, destination)
        episode_index = int(rows[0]["episode_index"])
        episode_stats[episode_index] = {
            "observation.state": _stats(converted_states, np),
            "action": _stats(converted_actions, np),
        }
        all_states.extend(converted_states)
        all_actions.extend(converted_actions)
        episode_manifests.append(
            {
                "episode_index": episode_index,
                "frames": len(rows),
                "profiles": sorted(profiles_seen),
                "grasp_modes": sorted(modes_seen),
                "source_episode_id": recovery_source_episode_id,
                "nonzero_contact_residual_frames": nonzero_contact_residual_frames,
                "nonzero_base_command_frames": nonzero_base_command_frames,
                "seed_role": (
                    "verified_successful_absolute_action_supervision"
                    if absolute_contract
                    else (
                        "verified_successful_recovery_supervision"
                        if nonzero_contact_residual_frames
                        else "mode_progress_and_zero_residual_initialization"
                    )
                ),
            }
        )

    _rewrite_info(
        output,
        state_names=state_names,
        action_names=action_names,
        action_contract=args.action_contract,
    )
    normalization_summary = _rewrite_global_stats(
        output,
        all_states,
        all_actions,
        np,
        state_names=state_names,
        action_names=action_names,
    )
    _rewrite_episode_stats(output, episode_stats, pa, pq)
    output_hashes = {
        _relative(path, output): _sha256(path)
        for path in sorted(output.glob("data/**/*.parquet"))
    }
    manifest = {
        "schema_version": 1,
        "protocol": (
            "pash-pi05-absolute-action-v1"
            if absolute_contract
            else "pash-pi05-residual-seed-v1"
        ),
        "source_dataset": str(source),
        "output_dataset": str(output),
        "episodes": len(episode_manifests),
        "frames": len(all_actions),
        "state_dimension": len(state_names),
        "state_names": list(state_names),
        "action_contract": args.action_contract,
        "action_dimension": len(action_names),
        "action_names": list(action_names),
        "policy_visual_modality": policy_visual_modality,
        "policy_visual_keys": policy_visual_keys,
        "mode_conditioning_policy": "hidden_all_stages",
        "lift_residual_supervision": "smooth_stage_progress_v2",
        "source_data_sha256": source_hashes,
        "output_data_sha256": output_hashes,
        "episode_manifests": episode_manifests,
        "mode_episode_counts": {
            mode: sum(mode in item.get("grasp_modes", ()) for item in episode_manifests)
            for mode in PI05_GRASP_MODES
        },
        "verified_recovery_summary": (
            str(args.collection_summary.resolve())
            if args.collection_summary is not None
            else None
        ),
        "nonzero_contact_residual_frames": sum(
            item["nonzero_contact_residual_frames"] for item in episode_manifests
        ),
        "nonzero_base_command_frames": sum(
            item["nonzero_base_command_frames"] for item in episode_manifests
        ),
        "expert_reference_used": not absolute_contract,
        "target_leakage_audit": (
            {
                "action_derived_state_fields": 0,
                "tool_position_state_source": "observation.state current end-effector pose",
                "mode_input_hidden": True,
            }
            if absolute_contract
            else None
        ),
        "normalization_stats_policy": "direct_frame_quantiles_with_degenerate_fallback_v1",
        "normalization_summary": normalization_summary,
        "claim_boundary": (
            "absolute action labels come only from verified physically successful "
            "episodes; state inputs contain current observed tool poses and never "
            "action-derived targets"
            if absolute_contract
            else (
                "corrective residual labels are admitted only from collector episodes with "
                "verified physical task success; failed trials remain replay evidence and are "
                "never treated as action demonstrations"
                if args.collection_summary is not None
                else "seed dataset initializes grasp mode, suction intent, primitive progress, "
                "and zero residual behavior only; corrective residual claims require separately "
                "verified successful recovery trajectories"
            )
        ),
    }
    manifest_name = (
        "PI05_ABSOLUTE_DATASET_MANIFEST.json"
        if absolute_contract
        else "PI05_RESIDUAL_DATASET_MANIFEST.json"
    )
    (output / manifest_name).write_text(
        json.dumps(manifest, indent=2), encoding="utf-8"
    )
    print(json.dumps({**manifest, "state_names": "see manifest", "episode_manifests": "see manifest"}, indent=2))
    return 0


def _profile_defaults(catalog_path: Path) -> dict[str, dict[str, Any]]:
    catalog = tomllib.loads(catalog_path.read_text(encoding="utf-8"))
    result = {}
    for profile in catalog["parcel_profiles"]:
        size = tuple(
            (float(low) + float(high)) / 2.0
            for low, high in zip(profile["dimensions_min_m"], profile["dimensions_max_m"], strict=True)
        )
        mass = (float(profile["mass_kg_min"]) + float(profile["mass_kg_max"])) / 2.0
        route = route_mobile_grasp(
            shape=str(profile["shape"]),
            orientation_mode=str(profile["orientation_mode"]),
            size_m=size,
            mass_kg=mass,
            handling_class=str(profile["handling_class"]),
        )
        result[str(profile["profile_id"])] = {
            "shape": str(profile["shape"]),
            "size_m": size,
            "mass_kg": mass,
            "grasp_mode": route.mode,
            "minimum_sealed_cups": route.minimum_sealed_cups,
        }
    return result


def _load_recovery_labels(
    summary_path: Path | None,
    episode_indices: list[int],
) -> dict[int, dict[str, Any]]:
    zero = {
        "episode_id": None,
        "profile_id": None,
        "contact_offset_m": (0.0, 0.0),
        "contact_penetration_delta_m": 0.0,
        "approach_axis_world": (0.0, 0.0, 1.0),
        "right_tool_axis_world": (0.0, 0.0, 1.0),
        "cradle_engagement_delta_m": 0.0,
        "left_lift_offset_m": (0.0, 0.0, 0.0),
        "right_lift_offset_m": (0.0, 0.0, 0.0),
        "vertical_speed_scale": 1.0,
        "retry_index": 0,
        "profile": {},
    }
    if summary_path is None:
        return {episode_index: dict(zero) for episode_index in episode_indices}
    payload = json.loads(summary_path.read_text(encoding="utf-8"))
    successful = [
        item
        for item in payload.get("results", ())
        if bool(item.get("success"))
    ]
    declared_order = payload.get("successful_episode_order")
    observed_order = [str(item.get("episode_id")) for item in successful]
    if declared_order is not None and list(map(str, declared_order)) != observed_order:
        raise ValueError("collector successful_episode_order does not match result order")
    if len(successful) != len(episode_indices):
        raise ValueError(
            "successful collector episodes must match merged source episode count: "
            f"{len(successful)} != {len(episode_indices)}"
        )
    labels = {}
    for episode_index, item in zip(episode_indices, successful, strict=True):
        recovery = item.get("recovery_label") or {}
        parameters = item.get("parameters") or {}
        if not bool(recovery.get("verified_success")):
            raise ValueError(
                f"episode {item.get('episode_id')} lacks a verified recovery label"
            )
        approach_axis = recovery.get("approach_axis_world")
        if not isinstance(approach_axis, list) or len(approach_axis) != 3:
            raise ValueError(
                f"episode {item.get('episode_id')} lacks a three-dimensional approach axis"
            )
        cradle_delta = float(recovery.get("cradle_engagement_delta_m", 0.0))
        right_axis = recovery.get("right_tool_axis_world")
        if abs(cradle_delta) > 0.0 and (
            not isinstance(right_axis, list) or len(right_axis) != 3
        ):
            raise ValueError(
                f"episode {item.get('episode_id')} lacks a right-tool recovery axis"
            )
        right_lift_offset = tuple(recovery.get("right_lift_offset_m", (0.0, 0.0, 0.0)))
        if len(right_lift_offset) != 3 or math.sqrt(
            sum(float(value) ** 2 for value in right_lift_offset)
        ) > 0.008:
            raise ValueError(
                f"episode {item.get('episode_id')} has an invalid right lift offset"
            )
        left_lift_offset = tuple(recovery.get("left_lift_offset_m", (0.0, 0.0, 0.0)))
        if len(left_lift_offset) != 3 or math.sqrt(
            sum(float(value) ** 2 for value in left_lift_offset)
        ) > 0.005:
            raise ValueError(
                f"episode {item.get('episode_id')} has an invalid left lift offset"
            )
        vertical_speed_scale = float(parameters.get("recovery_vertical_speed_scale", 1.0))
        if not 0.60 <= vertical_speed_scale <= 1.0:
            raise ValueError(
                f"episode {item.get('episode_id')} has an invalid vertical speed scale"
            )
        size_m = tuple(parameters.get("size_m", ()))
        mass_kg = float(parameters.get("mass_kg", 0.0))
        grasp_mode = str(
            recovery.get("grasp_mode", parameters.get("grasp_mode", ""))
        )
        if len(size_m) != 3 or min(map(float, size_m)) <= 0.0 or mass_kg <= 0.0:
            raise ValueError(
                f"episode {item.get('episode_id')} lacks valid parcel size or mass"
            )
        if grasp_mode not in PI05_GRASP_MODES:
            raise ValueError(
                f"episode {item.get('episode_id')} lacks a valid grasp mode"
            )
        labels[episode_index] = {
            "episode_id": str(item.get("episode_id")),
            "profile_id": str(item.get("profile")),
            "contact_offset_m": tuple(recovery.get("contact_offset_m", (0.0, 0.0))),
            "contact_penetration_delta_m": float(
                recovery.get("contact_penetration_delta_m", 0.0)
            ),
            "approach_axis_world": tuple(approach_axis),
            "right_tool_axis_world": tuple(right_axis or (0.0, 0.0, 1.0)),
            "cradle_engagement_delta_m": cradle_delta,
            "left_lift_offset_m": left_lift_offset,
            "right_lift_offset_m": right_lift_offset,
            "vertical_speed_scale": vertical_speed_scale,
            "retry_index": int(recovery.get("retry_index", 0)),
            "profile": {
                "shape": str(parameters.get("shape", "box")),
                "size_m": size_m,
                "mass_kg": mass_kg,
                "grasp_mode": grasp_mode,
                "minimum_sealed_cups": int(
                    parameters.get("minimum_sealed_cups", 2)
                ),
            },
        }
    return labels


def _profile_from_task(task: str, profiles: dict[str, dict[str, Any]]) -> str:
    normalized_task = re.sub(r"[_-]+", " ", task).lower()
    matches = [
        profile
        for profile in profiles
        if re.search(
            rf"\b{re.escape(re.sub(r'[_-]+', ' ', profile).lower())}\b",
            normalized_task,
        )
    ]
    if len(matches) != 1:
        raise ValueError(f"cannot uniquely infer parcel profile from task: {task!r}")
    return matches[0]


def _stage_id(value: Any) -> int:
    if isinstance(value, list):
        value = value[0]
    stage_id = int(value)
    if not 0 <= stage_id < len(MOBILE_STAGE_NAMES):
        raise ValueError(f"invalid stage id: {stage_id}")
    return stage_id


def _stats(values: list[list[float]], np: Any) -> dict[str, list[float]]:
    array = np.asarray(values, dtype=np.float64)
    return {
        "count": [len(values)],
        "min": array.min(axis=0).tolist(),
        "max": array.max(axis=0).tolist(),
        "mean": array.mean(axis=0).tolist(),
        "std": array.std(axis=0).tolist(),
        "q01": np.quantile(array, 0.01, axis=0).tolist(),
        "q10": np.quantile(array, 0.10, axis=0).tolist(),
        "q50": np.quantile(array, 0.50, axis=0).tolist(),
        "q90": np.quantile(array, 0.90, axis=0).tolist(),
        "q99": np.quantile(array, 0.99, axis=0).tolist(),
    }


def _rewrite_info(
    root: Path,
    *,
    state_names: tuple[str, ...],
    action_names: tuple[str, ...],
    action_contract: str,
) -> None:
    path = root / "meta/info.json"
    info = json.loads(path.read_text(encoding="utf-8"))
    info["features"]["observation.state"]["shape"] = [len(state_names)]
    info["features"]["observation.state"]["names"] = list(state_names)
    info["features"]["action"]["shape"] = [len(action_names)]
    info["features"]["action"]["names"] = list(action_names)
    info["features"]["action"]["info"] = {"contract": action_contract}
    path.write_text(json.dumps(info, indent=2), encoding="utf-8")


def _rewrite_global_stats(
    root: Path,
    states: list[list[float]],
    actions: list[list[float]],
    np: Any,
    *,
    state_names: tuple[str, ...],
    action_names: tuple[str, ...],
) -> dict[str, dict[str, list[str]]]:
    path = root / "meta/stats.json"
    stats = json.loads(path.read_text(encoding="utf-8"))
    state_stats, state_fallback = stabilize_quantile_stats(
        _stats(states, np), state_names
    )
    action_stats, action_fallback = stabilize_quantile_stats(
        _stats(actions, np), action_names
    )
    stats["observation.state"] = state_stats
    stats["action"] = action_stats
    path.write_text(json.dumps(stats, indent=2), encoding="utf-8")
    return {
        "observation.state": {
            "constant_dimensions": list(
                constant_dimensions(state_stats, state_names)
            ),
            "degenerate_quantile_fallback_dimensions": list(state_fallback),
        },
        "action": {
            "constant_dimensions": list(
                constant_dimensions(action_stats, action_names)
            ),
            "degenerate_quantile_fallback_dimensions": list(action_fallback),
        },
    }


def _rewrite_episode_stats(root: Path, episode_stats: dict[int, dict[str, dict[str, list[float]]]], pa: Any, pq: Any) -> None:
    for path in sorted((root / "meta/episodes").glob("**/*.parquet")):
        table = pq.read_table(path)
        rows = table.to_pylist()
        for feature in ("observation.state", "action"):
            for key in STAT_KEYS:
                column = f"stats/{feature}/{key}"
                index = table.schema.get_field_index(column)
                if index < 0:
                    continue
                values = [episode_stats[int(row["episode_index"])][feature][key] for row in rows]
                table = table.set_column(index, column, pa.array(values))
        pq.write_table(table, path)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _relative(path: Path, root: Path) -> str:
    return str(path.relative_to(root)).replace("\\", "/")


if __name__ == "__main__":
    raise SystemExit(main())
