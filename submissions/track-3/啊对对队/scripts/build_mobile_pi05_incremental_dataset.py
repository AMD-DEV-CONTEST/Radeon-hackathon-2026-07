#!/usr/bin/env python3
"""Build a derived PI0.5 dataset with achieved local SE(3) actions.

The source absolute-action dataset is never modified. Video and unchanged
metadata are hard-linked when possible; every numeric parquet is rewritten as
a new destination inode. The derived action is 21-D:
base velocity, left/right XYZ deltas, left/right rotation vectors, tool
commands, three mode logits, and primitive progress.
"""

from __future__ import annotations

import argparse
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import shutil
from collections import defaultdict
from typing import Any

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq

from parcel_sorter.mobile_pi05_contract import (
    MOBILE_PI05_ABSOLUTE_ACTION_NAMES,
    MOBILE_PI05_ABSOLUTE_STATE_NAMES,
    MOBILE_PI05_DEPLOYMENT_STATE_V2_NAMES,
    MOBILE_PI05_INCREMENTAL_ACTION_NAMES,
    PI05_GRASP_MODES,
    PI05_MAX_INCREMENTAL_ROTATION_RAD,
    PI05_MAX_INCREMENTAL_TRANSLATION_M,
    encode_pi05_achieved_incremental_action,
    project_pi05_deployment_state_v2,
)
from parcel_sorter.mobile_pi05_research_protocol import (
    PI05_STRATIFIED_STAGE_PANEL_PROTOCOL,
    PI05_TINY_OVERFIT_ROLE,
    build_stage_panel,
    build_stratified_stage_panel,
    validate_stage_panel,
)
from parcel_sorter.mobile_pi05_normalization import stabilize_quantile_stats


PROTOCOL = "parcel-pi05-achieved-incremental-dataset-v2"
SOURCE_MANIFEST = "PI05_ABSOLUTE_DATASET_MANIFEST.json"
DEST_MANIFEST = "PI05_INCREMENTAL_DATASET_MANIFEST.json"
VERIFIED_RECOVERY_SEED_ROLE = "verified_successful_recovery_supervision"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _stats(
    values: np.ndarray,
    names: tuple[str, ...],
) -> tuple[dict[str, Any], tuple[str, ...]]:
    raw = {
        "min": values.min(axis=0).astype(float).tolist(),
        "max": values.max(axis=0).astype(float).tolist(),
        "mean": values.mean(axis=0, dtype=np.float64).tolist(),
        "std": values.std(axis=0, dtype=np.float64).tolist(),
        "count": [int(values.shape[0])],
        "q01": np.quantile(values, 0.01, axis=0).astype(float).tolist(),
        "q10": np.quantile(values, 0.10, axis=0).astype(float).tolist(),
        "q50": np.quantile(values, 0.50, axis=0).astype(float).tolist(),
        "q90": np.quantile(values, 0.90, axis=0).astype(float).tolist(),
        "q99": np.quantile(values, 0.99, axis=0).astype(float).tolist(),
    }
    return stabilize_quantile_stats(raw, names)


def _copy_and_validate_provenance(
    source_manifest: dict[str, Any],
) -> dict[str, Any]:
    raw_episode_manifests = source_manifest.get("episode_manifests", [])
    if not isinstance(raw_episode_manifests, list):
        raise ValueError("source episode_manifests must be a list")
    episode_manifests: list[dict[str, Any]] = []
    for index, item in enumerate(raw_episode_manifests):
        if not isinstance(item, dict):
            raise ValueError(f"source episode manifest {index} must be an object")
        episode_manifests.append(deepcopy(item))

    recovery_summary = deepcopy(source_manifest.get("verified_recovery_summary"))
    recovery_summaries = deepcopy(source_manifest.get("verified_recovery_summaries"))
    if recovery_summaries is not None and not isinstance(recovery_summaries, list):
        raise ValueError("source verified_recovery_summaries must be a list")
    has_recovery_evidence = recovery_summary is not None or bool(recovery_summaries)
    recovery_entries = [
        item
        for item in episode_manifests
        if item.get("seed_role") == VERIFIED_RECOVERY_SEED_ROLE
    ]
    supervision_provenance = source_manifest.get("supervision_provenance")
    if supervision_provenance == "verified_recovery":
        invalid_roles = [
            item.get("seed_role")
            for item in episode_manifests
            if item.get("seed_role") != VERIFIED_RECOVERY_SEED_ROLE
        ]
        if invalid_roles:
            raise ValueError(
                "verified-recovery source contains a contradictory episode seed role"
            )
    if recovery_entries and not has_recovery_evidence:
        raise ValueError("verified-recovery episode lacks bound recovery evidence")
    if has_recovery_evidence and not recovery_entries:
        raise ValueError("recovery evidence has no verified-recovery episode")
    if recovery_entries and supervision_provenance in {
        "deterministic_expert_demonstration",
        "unverified_zero_seed",
    }:
        raise ValueError(
            "verified-recovery episode contradicts source supervision provenance"
        )
    return {
        "episode_manifests": episode_manifests,
        "verified_recovery_summary": recovery_summary,
        "verified_recovery_summaries": recovery_summaries,
        "verified_expert_demonstration_summary": deepcopy(
            source_manifest.get("verified_expert_demonstration_summary")
        ),
        "supervision_provenance": supervision_provenance,
    }


def _convert(
    actions: np.ndarray,
    states: np.ndarray,
    achieved_next_states: np.ndarray,
) -> np.ndarray:
    if actions.ndim != 2 or actions.shape[1] != len(MOBILE_PI05_ABSOLUTE_ACTION_NAMES):
        raise ValueError(f"expected 23-D absolute actions, got {actions.shape}")
    if states.ndim != 2 or states.shape[1] != len(MOBILE_PI05_ABSOLUTE_STATE_NAMES):
        raise ValueError(f"expected 80-D observable states, got {states.shape}")
    if achieved_next_states.shape != states.shape:
        raise ValueError(
            "achieved next states must have the same shape as current states"
        )
    converted = np.empty((actions.shape[0], len(MOBILE_PI05_INCREMENTAL_ACTION_NAMES)), dtype=np.float32)
    for index, (action, state, achieved) in enumerate(
        zip(actions, states, achieved_next_states, strict=True)
    ):
        converted[index] = encode_pi05_achieved_incremental_action(
            action.tolist(), state.tolist(), achieved.tolist()
        )
    if not np.isfinite(converted).all():
        raise ValueError("incremental action conversion produced non-finite values")
    return converted


def _build_achieved_transition_lookup(
    data_paths: list[Path],
) -> tuple[dict[tuple[Path, int], np.ndarray], dict[str, int]]:
    frames_by_episode: dict[int, list[tuple[int, Path, int, int, np.ndarray]]] = defaultdict(list)
    for path in data_paths:
        table = pq.read_table(
            path,
            columns=[
                "episode_index",
                "frame_index",
                "observation.stage_id",
                "observation.state",
            ],
        )
        rows = table.to_pylist()
        for row_index, row in enumerate(rows):
            state = np.asarray(row["observation.state"], dtype=np.float32)
            if state.shape != (len(MOBILE_PI05_ABSOLUTE_STATE_NAMES),):
                raise ValueError(f"expected 80-D observable state, got {state.shape}")
            stage_value = row["observation.stage_id"]
            stage_id = int(stage_value[0] if isinstance(stage_value, list) else stage_value)
            frames_by_episode[int(row["episode_index"])].append(
                (int(row["frame_index"]), path, row_index, stage_id, state)
            )

    lookup: dict[tuple[Path, int], np.ndarray] = {}
    transition_frames = 0
    boundary_zeroed_frames = 0
    terminal_zeroed_frames = 0
    source_quaternion_sign_flips = 0
    for episode_index, frames in frames_by_episode.items():
        frames.sort(key=lambda item: item[0])
        frame_indices = [item[0] for item in frames]
        if len(frame_indices) != len(set(frame_indices)):
            raise ValueError(f"duplicate frame indices in episode {episode_index}")
        for offset, current in enumerate(frames):
            _, path, row_index, stage_id, state = current
            if offset + 1 >= len(frames):
                achieved = state
                terminal_zeroed_frames += 1
            else:
                next_frame = frames[offset + 1]
                if next_frame[0] != current[0] + 1:
                    raise ValueError(
                        f"non-contiguous frame indices in episode {episode_index}: "
                        f"{current[0]} -> {next_frame[0]}"
                    )
                if next_frame[3] != stage_id:
                    achieved = state
                    boundary_zeroed_frames += 1
                else:
                    achieved = next_frame[4]
                    transition_frames += 1
                    for start in (27, 34):
                        if float(np.dot(state[start : start + 4], achieved[start : start + 4])) < 0.0:
                            source_quaternion_sign_flips += 1
            lookup[(path, row_index)] = achieved
    return lookup, {
        "episodes": len(frames_by_episode),
        "transition_frames": transition_frames,
        "stage_boundary_zeroed_frames": boundary_zeroed_frames,
        "episode_terminal_zeroed_frames": terminal_zeroed_frames,
        "source_quaternion_sign_flips": source_quaternion_sign_flips,
    }


def build(
    source: Path,
    destination: Path,
    *,
    deployment_state_v2: bool = False,
) -> dict[str, Any]:
    source = source.resolve()
    destination = destination.resolve()
    if destination.exists():
        raise FileExistsError(f"destination already exists: {destination}")
    info_path = source / "meta" / "info.json"
    stats_path = source / "meta" / "stats.json"
    manifest_path = source / SOURCE_MANIFEST
    if not info_path.is_file() or not stats_path.is_file() or not manifest_path.is_file():
        raise FileNotFoundError("source must contain info.json, stats.json, and the absolute manifest")
    info = json.loads(info_path.read_text(encoding="utf-8"))
    source_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    source_panel = None
    if source_manifest.get("dataset_role") == "tiny_overfit_contract_only":
        source_panel_path = source / "PI05_TINY_OVERFIT_PANEL.json"
        if not source_panel_path.is_file():
            raise FileNotFoundError("tiny-overfit source is missing its frozen panel")
        source_panel = json.loads(source_panel_path.read_text(encoding="utf-8"))
        validate_stage_panel(source_panel, expected_role=PI05_TINY_OVERFIT_ROLE)
        if Path(str(source_panel.get("dataset_root"))).resolve() != source:
            raise ValueError("tiny-overfit source panel points at another dataset")
    action_feature = info.get("features", {}).get("action", {})
    if action_feature.get("shape") != [23] or action_feature.get("names") != list(MOBILE_PI05_ABSOLUTE_ACTION_NAMES):
        raise ValueError("source info.json is not the frozen 23-D absolute contract")
    source_info_sha = _sha256(info_path)
    source_stats_sha = _sha256(stats_path)
    source_manifest_sha = _sha256(manifest_path)

    try:
        shutil.copytree(source, destination, copy_function=os.link)
        copy_mode = "hardlink_then_replace_numeric_parquet"
        for relative in (Path("meta/info.json"), Path("meta/stats.json")):
            target = destination / relative
            target.unlink()
            shutil.copy2(source / relative, target)
    except OSError:
        if destination.exists():
            shutil.rmtree(destination)
        shutil.copytree(source, destination, copy_function=shutil.copy2)
        copy_mode = "full_copy"

    invalidated_relatives = (
        Path(SOURCE_MANIFEST),
        Path("meta/train_stats.json"),
        Path("PARCEL_TRAIN_STATS_MANIFEST.json"),
        Path("PARCEL_PI05_SAMPLING_MANIFEST.json"),
        Path("PARCEL_SUCCESS_SPLIT_BINDING.json"),
        Path("PI05_TINY_OVERFIT_PANEL.json"),
        Path("TINY_OVERFIT_BUILD_AUDIT.json"),
    )
    invalidated_files: list[str] = []
    for relative in invalidated_relatives:
        target = destination / relative
        if target.exists():
            target.unlink()
            invalidated_files.append(str(relative).replace("\\", "/"))

    data_paths = sorted((destination / "data").rglob("*.parquet"))
    transition_lookup, transition_audit = _build_achieved_transition_lookup(data_paths)
    action_batches: list[np.ndarray] = []
    state_batches: list[np.ndarray] = []
    parquet_hashes: dict[str, str] = {}
    for path in data_paths:
        table = pq.read_table(path)
        actions = np.asarray(table["action"].to_pylist(), dtype=np.float32)
        states = np.asarray(table["observation.state"].to_pylist(), dtype=np.float32)
        achieved_next_states = np.asarray(
            [transition_lookup[(path, index)] for index in range(table.num_rows)],
            dtype=np.float32,
        )
        converted = _convert(actions, states, achieved_next_states)
        action_batches.append(converted)
        flat = pa.array(converted.reshape(-1), type=pa.float32())
        column = pa.FixedSizeListArray.from_arrays(flat, len(MOBILE_PI05_INCREMENTAL_ACTION_NAMES))
        action_index = table.schema.get_field_index("action")
        transformed = table.set_column(
            action_index,
            pa.field("action", column.type),
            column,
        )
        if deployment_state_v2:
            projected_states = np.asarray(
                [project_pi05_deployment_state_v2(row) for row in states],
                dtype=np.float32,
            )
            state_batches.append(projected_states)
            state_flat = pa.array(projected_states.reshape(-1), type=pa.float32())
            state_column = pa.FixedSizeListArray.from_arrays(
                state_flat, len(MOBILE_PI05_DEPLOYMENT_STATE_V2_NAMES)
            )
            state_index = transformed.schema.get_field_index("observation.state")
            transformed = transformed.set_column(
                state_index,
                pa.field("observation.state", state_column.type),
                state_column,
            )
        temporary = path.with_suffix(".parquet.tmp")
        pq.write_table(transformed, temporary)
        temporary.replace(path)
        parquet_hashes[str(path.relative_to(destination)).replace("\\", "/")] = _sha256(path)

    if not action_batches:
        raise ValueError("source contains no action parquet files")
    all_actions = np.concatenate(action_batches, axis=0)
    updated_info = dict(info)
    updated_info["features"] = dict(updated_info["features"])
    action_info = dict(action_feature.get("info") or {})
    action_contract = (
        "incremental_se3_deployment_v2"
        if deployment_state_v2
        else "incremental_se3_v1"
    )
    action_info["contract"] = action_contract
    updated_info["features"]["action"] = {
        **action_feature,
        "shape": [len(MOBILE_PI05_INCREMENTAL_ACTION_NAMES)],
        "names": list(MOBILE_PI05_INCREMENTAL_ACTION_NAMES),
        "info": action_info,
    }
    if deployment_state_v2:
        source_state_feature = dict(
            updated_info["features"].get("observation.state") or {}
        )
        state_info = dict(source_state_feature.get("info") or {})
        state_info.update(
            {
                "contract": "deployment_state_v2",
                "exact_goal_coordinates": False,
                "numeric_grasp_mode_router": False,
                "external_stage_one_hot": False,
            }
        )
        updated_info["features"]["observation.state"] = {
            **source_state_feature,
            "shape": [len(MOBILE_PI05_DEPLOYMENT_STATE_V2_NAMES)],
            "names": list(MOBILE_PI05_DEPLOYMENT_STATE_V2_NAMES),
            "info": state_info,
        }
    destination_info_path = destination / "meta" / "info.json"
    destination_info_path.write_text(
        json.dumps(updated_info, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    destination_stats_path = destination / "meta" / "stats.json"
    updated_stats = json.loads(destination_stats_path.read_text(encoding="utf-8"))
    action_stats, action_quantile_fallback = _stats(
        all_actions, MOBILE_PI05_INCREMENTAL_ACTION_NAMES
    )
    updated_stats["action"] = action_stats
    state_quantile_fallback: tuple[str, ...] = ()
    if deployment_state_v2:
        if not state_batches:
            raise RuntimeError("deployment-state-v2 conversion produced no states")
        state_stats, state_quantile_fallback = _stats(
            np.concatenate(state_batches, axis=0),
            MOBILE_PI05_DEPLOYMENT_STATE_V2_NAMES,
        )
        updated_stats["observation.state"] = state_stats
    destination_stats_path.write_text(
        json.dumps(updated_stats, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    persisted_info = json.loads(destination_info_path.read_text(encoding="utf-8"))
    persisted_action = persisted_info.get("features", {}).get("action", {})
    if (
        persisted_action.get("shape") != [len(MOBILE_PI05_INCREMENTAL_ACTION_NAMES)]
        or persisted_action.get("names")
        != list(MOBILE_PI05_INCREMENTAL_ACTION_NAMES)
        or (persisted_action.get("info") or {}).get("contract")
        != action_contract
    ):
        raise RuntimeError("persisted incremental action metadata failed its contract")
    persisted_state = persisted_info.get("features", {}).get("observation.state", {})
    if deployment_state_v2 and (
        persisted_state.get("shape") != [len(MOBILE_PI05_DEPLOYMENT_STATE_V2_NAMES)]
        or persisted_state.get("names")
        != list(MOBILE_PI05_DEPLOYMENT_STATE_V2_NAMES)
        or (persisted_state.get("info") or {}).get("contract")
        != "deployment_state_v2"
    ):
        raise RuntimeError("persisted deployment-state-v2 metadata failed its contract")
    provenance = _copy_and_validate_provenance(source_manifest)
    derived_manifest = {
        "schema_version": 1,
        "protocol": PROTOCOL,
        "action_contract": action_contract,
        "state_contract": (
            "deployment_state_v2" if deployment_state_v2 else "absolute_state_v1"
        ),
        "source": str(source),
        "destination": str(destination),
        "source_manifest": SOURCE_MANIFEST,
        "source_manifest_sha256": source_manifest_sha,
        "source_info_sha256": source_info_sha,
        "source_stats_sha256": source_stats_sha,
        "source_protocol": source_manifest.get("protocol"),
        "dataset_role": source_manifest.get("dataset_role"),
        "performance_data": source_manifest.get("performance_data"),
        "episode_manifests": provenance["episode_manifests"],
        "mode_episode_counts": source_manifest.get("mode_episode_counts"),
        "training_grasp_modes": source_manifest.get("training_grasp_modes"),
        "verified_recovery_summary": provenance["verified_recovery_summary"],
        "verified_expert_demonstration_summary": provenance[
            "verified_expert_demonstration_summary"
        ],
        "supervision_provenance": provenance["supervision_provenance"],
        "verified_recovery_summaries": provenance["verified_recovery_summaries"],
        "mode_conditioning_policy": source_manifest.get("mode_conditioning_policy"),
        "task_language_policy": source_manifest.get("task_language_policy"),
        "target_leakage_audit": source_manifest.get("target_leakage_audit"),
        "policy_visual_keys": source_manifest.get("policy_visual_keys"),
        "normalization_stats_policy": (
            "direct_frame_quantiles_with_degenerate_fallback_v1"
        ),
        "degenerate_quantile_fallback_dimensions": {
            "observation.state": list(state_quantile_fallback),
            "action": list(action_quantile_fallback),
        },
        "nonzero_base_command_frames": source_manifest.get("nonzero_base_command_frames"),
        "expert_reference_used": source_manifest.get("expert_reference_used"),
        "copy_mode": copy_mode,
        "invalidated_stale_artifacts": invalidated_files,
        "frame_count": int(all_actions.shape[0]),
        "dataset_info_sha256": _sha256(destination_info_path),
        "dataset_stats_sha256": _sha256(destination_stats_path),
        "state_current_left_position_indices": (
            [62, 63, 64] if deployment_state_v2 else [74, 75, 76]
        ),
        "state_current_right_position_indices": (
            [65, 66, 67] if deployment_state_v2 else [77, 78, 79]
        ),
        "policy_state_forbidden_fields_absent": (
            [
                "goal_x",
                "goal_y",
                "goal_yaw",
                "mode_top_suction",
                "mode_side_suction",
                "mode_cooperative_cradle",
                *(f"stage_{stage}" for stage in (
                    "pregrasp",
                    "grasp_approach",
                    "lift",
                    "transport",
                    "place",
                    "release",
                )),
            ]
            if deployment_state_v2
            else []
        ),
        "label_source": "same_episode_same_stage_next_achieved_robot_state",
        "transition_offset_frames": 1,
        "stage_boundary_policy": "zero_arm_delta_never_cross_stage",
        "episode_terminal_policy": "zero_arm_delta",
        "base_and_tool_policy": "preserve_recorded_action_channels",
        "max_translation_norm_m": PI05_MAX_INCREMENTAL_TRANSLATION_M,
        "max_rotation_vector_norm_rad": PI05_MAX_INCREMENTAL_ROTATION_RAD,
        "transition_audit": transition_audit,
        "rotation_policy": "shortest_rotation_vector_achieved_next_times_current_inverse",
        "tool_and_mode_channels_preserved": True,
        "parquet_sha256": parquet_hashes,
        "claim_boundary": (
            "derived same-episode achieved-transition labels; no planner/expert target "
            "is encoded as an arm delta and no new independent demonstrations are created"
        ),
    }
    destination_manifest_path = destination / DEST_MANIFEST
    destination_manifest_path.write_text(
        json.dumps(derived_manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    if source_panel is not None:
        if source_panel.get("protocol") == PI05_STRATIFIED_STAGE_PANEL_PROTOCOL:
            destination_panel = build_stratified_stage_panel(
                source_panel["observations"],
                role=PI05_TINY_OVERFIT_ROLE,
                dataset_root=destination,
                dataset_manifest_sha256=_sha256(destination_manifest_path),
                stratification_key=str(source_panel["stratification_key"]),
                required_strata=source_panel["required_strata"],
                minimum_observations_per_stratum_stage=int(
                    source_panel["minimum_observations_per_stratum_stage"]
                ),
                minimum_independent_sources_per_stratum_stage=int(
                    source_panel["minimum_independent_sources_per_stratum_stage"]
                ),
            )
        else:
            destination_panel = build_stage_panel(
                source_panel["observations"],
                role=PI05_TINY_OVERFIT_ROLE,
                dataset_root=destination,
                dataset_manifest_sha256=_sha256(destination_manifest_path),
                minimum_observations_per_mode_stage=1,
                minimum_independent_sources_per_mode=1,
                required_grasp_modes=(
                    source_panel.get("required_grasp_modes") or PI05_GRASP_MODES
                ),
            )
        (destination / "PI05_TINY_OVERFIT_PANEL.json").write_text(
            json.dumps(destination_panel, ensure_ascii=False, indent=2, sort_keys=True)
            + "\n",
            encoding="utf-8",
        )
    if _sha256(info_path) != source_info_sha or _sha256(stats_path) != source_stats_sha:
        raise RuntimeError("source metadata changed while building the derived dataset")
    return derived_manifest


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("destination", type=Path)
    parser.add_argument("--deployment-state-v2", action="store_true")
    args = parser.parse_args()
    print(
        json.dumps(
            build(
                args.source,
                args.destination,
                deployment_state_v2=args.deployment_state_v2,
            ),
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
