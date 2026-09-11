#!/usr/bin/env python3
"""Audit a PI0.5 residual or expert-independent absolute-action dataset."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
from typing import Any

from parcel_sorter.mobile_dataset import MOBILE_STAGE_NAMES
from parcel_sorter.mobile_pi05_contract import (
    MOBILE_PI05_ABSOLUTE_ACTION_NAMES,
    MOBILE_PI05_ABSOLUTE_STATE_NAMES,
    MOBILE_PI05_RESIDUAL_ACTION_NAMES,
    MOBILE_PI05_STATE_NAMES,
    PI05_ARM_AUTHORITY_M,
)
from parcel_sorter.mobile_pi05_normalization import unsafe_quantile_dimensions
from parcel_sorter.mobile_pi05_data_quality import (
    summarize_pi05_action_chunk_activity,
)
from parcel_sorter.mobile_pi05_research_protocol import independent_source_identity


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset-root", type=Path, required=True)
    parser.add_argument("--source-root", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--min-recovery-episodes", type=int, default=2)
    parser.add_argument("--min-independent-sources-per-mode", type=int, default=2)
    args = parser.parse_args()

    import pyarrow.parquet as pq

    root = args.dataset_root.resolve()
    manifest_paths = [
        path
        for path in (
            root / "PI05_RESIDUAL_DATASET_MANIFEST.json",
            root / "PI05_ABSOLUTE_DATASET_MANIFEST.json",
        )
        if path.is_file()
    ]
    manifest_path = manifest_paths[0] if len(manifest_paths) == 1 else None
    info_path = root / "meta/info.json"
    stats_path = root / "meta/stats.json"
    errors: list[str] = []
    if manifest_path is None or not info_path.is_file() or not stats_path.is_file():
        errors.append("missing_manifest_or_info")
        return _finish(args.output, errors, {})
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    info = json.loads(info_path.read_text(encoding="utf-8"))
    stats = json.loads(stats_path.read_text(encoding="utf-8"))
    absolute_contract = manifest.get("action_contract") == "absolute_v1"
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
    state_feature = info.get("features", {}).get("observation.state", {})
    action_feature = info.get("features", {}).get("action", {})
    if state_feature.get("shape") != [len(state_names)]:
        errors.append("state_shape_mismatch")
    if action_feature.get("shape") != [len(action_names)]:
        errors.append("action_shape_mismatch")
    if state_feature.get("names") != list(state_names):
        errors.append("state_names_mismatch")
    if action_feature.get("names") != list(action_names):
        errors.append("action_names_mismatch")

    dataset_files = sorted(root.glob("data/**/*.parquet"))
    source_files = (
        sorted(args.source_root.resolve().glob("data/**/*.parquet"))
        if args.source_root is not None
        else []
    )
    if not dataset_files:
        errors.append("missing_data_files")
    if args.source_root is not None and [p.relative_to(root) for p in dataset_files] != [
        p.relative_to(args.source_root.resolve()) for p in source_files
    ]:
        errors.append("source_file_layout_mismatch")

    total_frames = 0
    nonzero_frames = 0
    nonzero_base_command_frames = 0
    observed_tool_state_mismatch_frames = 0
    action_target_differs_from_observed_tool_frames = 0
    pregrasp_frames = 0
    hidden_pregrasp_mode_frames = 0
    hidden_mode_frames = 0
    episode_actions: dict[int, list[tuple[float, ...]]] = {}
    anchor_reconstruction_max_error_m = 0.0
    progress_min = math.inf
    progress_max = -math.inf
    recovery_entries = [
        item
        for item in manifest.get("episode_manifests", ())
        if item.get("seed_role")
        in {
            "verified_successful_recovery_supervision",
            "verified_successful_absolute_action_supervision",
        }
    ]
    recovery_episode_ids = {item.get("episode_index") for item in recovery_entries}
    independent_recovery_ids = {
        (
            item.get("source_dataset"),
            item.get("source_episode_index"),
            item.get("source_episode_id") or item.get("episode_id"),
        )
        for item in recovery_entries
    }
    mode_source_identities = {
        mode: set() for mode in ("top_suction", "side_suction", "cooperative_cradle")
    }
    try:
        for item in recovery_entries:
            identity = independent_source_identity(item)
            for mode in item.get("grasp_modes") or ():
                if mode not in mode_source_identities:
                    errors.append(f"invalid_grasp_mode:{mode}")
                else:
                    mode_source_identities[mode].add(identity)
    except ValueError as exc:
        errors.append(f"invalid_source_identity:{exc}")
    for file_index, path in enumerate(dataset_files):
        columns = ["episode_index", "observation.stage_id", "observation.state", "action"]
        rows = pq.read_table(path, columns=columns).to_pylist()
        source_rows = (
            pq.read_table(source_files[file_index], columns=["action"]).to_pylist()
            if source_files
            else [None] * len(rows)
        )
        if len(rows) != len(source_rows):
            errors.append(f"source_row_count_mismatch:{path.name}")
            continue
        for row, source_row in zip(rows, source_rows, strict=True):
            total_frames += 1
            state = tuple(float(value) for value in row["observation.state"])
            action = tuple(float(value) for value in row["action"])
            episode_actions.setdefault(int(row["episode_index"]), []).append(action)
            if len(state) != len(state_names) or len(action) != len(action_names):
                errors.append(f"row_contract_mismatch:{path.name}:{total_frames}")
                continue
            if any(not math.isfinite(value) for value in (*state, *action)):
                errors.append(f"non_finite_row:{path.name}:{total_frames}")
                continue
            stage = MOBILE_STAGE_NAMES[_stage_id(row["observation.stage_id"])]
            mode_input = state[52:55]
            mode_hidden = max(map(abs, mode_input)) <= 1e-7
            hidden_mode_frames += int(mode_hidden)
            if stage == "pregrasp":
                pregrasp_frames += 1
                hidden_pregrasp_mode_frames += int(mode_hidden)
            elif manifest.get("mode_conditioning_policy") != "hidden_all_stages" and not math.isclose(
                sum(mode_input), 1.0, abs_tol=1e-6
            ):
                errors.append(f"conditioned_mode_not_one_hot:{path.name}:{total_frames}")
            if absolute_contract:
                current_left = state[24:27]
                current_right = state[31:34]
                observed_left = state[74:77]
                observed_right = state[77:80]
                if max(
                    math.dist(current_left, observed_left),
                    math.dist(current_right, observed_right),
                ) > 1e-7:
                    observed_tool_state_mismatch_frames += 1
                    errors.append(
                        f"observed_tool_state_mismatch:{path.name}:{total_frames}"
                    )
                action_motion = max(
                    math.dist(action[3:6], observed_left),
                    math.dist(action[11:14], observed_right),
                )
                action_target_differs_from_observed_tool_frames += int(
                    action_motion > 1e-5
                )
                nonzero_base_command_frames += int(max(map(abs, action[:3])) > 1e-7)
                is_nonzero = max(max(map(abs, action[:3])), action_motion) > 1e-7
                nonzero_frames += int(is_nonzero)
                progress_index = 22
            else:
                residuals = (*action[3:6], *action[6:9])
                is_nonzero = max(map(abs, residuals)) > 1e-7
                nonzero_frames += int(is_nonzero)
                authority = PI05_ARM_AUTHORITY_M.get(stage, 0.0)
                for start in (3, 6):
                    norm = math.sqrt(
                        sum(value * value for value in action[start : start + 3])
                    )
                    if norm > authority + 1e-6:
                        errors.append(
                            f"residual_authority_violation:{path.name}:{total_frames}"
                        )
                progress_index = 13
            progress_min = min(progress_min, action[progress_index])
            progress_max = max(progress_max, action[progress_index])
            if not 0.0 <= action[progress_index] <= 1.0:
                errors.append(f"progress_out_of_range:{path.name}:{total_frames}")
            if source_row is not None:
                source_action = tuple(float(value) for value in source_row["action"])
                if absolute_contract:
                    if len(source_action) not in {19, 20} or max(
                        abs(action[index] - source_action[index])
                        for index in range(19)
                    ) > 2e-5:
                        errors.append(
                            f"absolute_source_action_mismatch:{path.name}:{total_frames}"
                        )
                else:
                    for anchor_start, residual_start, source_start in (
                        (74, 3, 3),
                        (77, 6, 11),
                    ):
                        error = math.dist(
                            tuple(
                                state[anchor_start + index]
                                + action[residual_start + index]
                                for index in range(3)
                            ),
                            source_action[source_start : source_start + 3],
                        )
                        anchor_reconstruction_max_error_m = max(
                            anchor_reconstruction_max_error_m, error
                        )
                        if error > 2e-5:
                            errors.append(
                                f"anchor_reconstruction_mismatch:{path.name}:{total_frames}"
                            )

    if len(independent_recovery_ids) < args.min_recovery_episodes:
        errors.append("insufficient_verified_recovery_episodes")
    independent_source_counts_by_mode = {
        mode: len(values) for mode, values in mode_source_identities.items()
    }
    errors.extend(
        f"insufficient_independent_sources:{mode}:{count}"
        for mode, count in independent_source_counts_by_mode.items()
        if count < args.min_independent_sources_per_mode
    )
    if absolute_contract:
        if manifest.get("expert_reference_used") is not False:
            errors.append("absolute_contract_uses_expert_reference")
        leakage = manifest.get("target_leakage_audit") or {}
        if leakage.get("action_derived_state_fields") != 0:
            errors.append("absolute_action_target_leakage")
        if leakage.get("mode_input_hidden") is not True:
            errors.append("absolute_mode_input_not_hidden")
        if observed_tool_state_mismatch_frames:
            errors.append("absolute_observed_tool_state_mismatch")
        if action_target_differs_from_observed_tool_frames == 0:
            errors.append("absolute_action_targets_never_differ_from_current_tools")
        if nonzero_base_command_frames != int(
            manifest.get("nonzero_base_command_frames", -1)
        ):
            errors.append("nonzero_base_command_manifest_mismatch")
        if nonzero_base_command_frames == 0:
            errors.append("missing_absolute_transport_supervision")
    elif nonzero_frames != int(
        manifest.get("nonzero_contact_residual_frames", -1)
    ):
        errors.append("nonzero_frame_manifest_mismatch")
    if pregrasp_frames != hidden_pregrasp_mode_frames:
        errors.append("pregrasp_mode_leakage")
    if (
        manifest.get("mode_conditioning_policy") == "hidden_all_stages"
        and hidden_mode_frames != total_frames
    ):
        errors.append("all_stage_mode_leakage")
    if manifest.get("lift_residual_supervision") != "smooth_stage_progress_v2":
        errors.append("lift_residual_supervision_mismatch")
    tasks_path = root / "meta/tasks.parquet"
    task_language_policy = manifest.get("task_language_policy", "source_text")
    if task_language_policy == "mode_neutral_shared_instruction_v1":
        expected_task = manifest.get("mode_neutral_task")
        observed_tasks = set(pq.read_table(tasks_path, columns=["task"])["task"].to_pylist())
        if observed_tasks != {expected_task}:
            errors.append("mode_neutral_task_metadata_mismatch")
        if manifest.get("task_metadata_sha256") != _sha256(tasks_path):
            errors.append("task_metadata_hash_mismatch")
    unsafe_normalization_dimensions: dict[str, list[str]] = {}
    for feature, names in (
        ("observation.state", state_names),
        ("action", action_names),
    ):
        try:
            unsafe = list(unsafe_quantile_dimensions(stats.get(feature, {}), names))
        except ValueError as exc:
            errors.append(f"invalid_normalization_stats:{feature}:{exc}")
            unsafe = []
        unsafe_normalization_dimensions[feature] = unsafe
        errors.extend(f"unsafe_quantile_width:{feature}:{name}" for name in unsafe)
    chunk_activity = (
        None
        if absolute_contract
        else summarize_pi05_action_chunk_activity(
            episode_actions.values(), chunk_size=30
        )
    )
    metrics = {
        "action_contract": manifest.get("action_contract", "residual_v1"),
        "episodes": int(manifest.get("episodes", 0)),
        "verified_recovery_episode_instances": len(recovery_episode_ids),
        "independent_verified_recovery_episodes": len(independent_recovery_ids),
        "independent_source_counts_by_mode": independent_source_counts_by_mode,
        "minimum_independent_sources_per_mode": (
            args.min_independent_sources_per_mode
        ),
        "replayed_training_episodes": len(recovery_episode_ids)
        - len(independent_recovery_ids),
        "frames": total_frames,
        "nonzero_contact_residual_frames": (
            None if absolute_contract else nonzero_frames
        ),
        "nonzero_absolute_action_frames": (
            nonzero_frames if absolute_contract else None
        ),
        "nonzero_base_command_frames": nonzero_base_command_frames,
        "observed_tool_state_mismatch_frames": observed_tool_state_mismatch_frames,
        "action_target_differs_from_observed_tool_frames": (
            action_target_differs_from_observed_tool_frames
        ),
        "pregrasp_frames": pregrasp_frames,
        "hidden_pregrasp_mode_frames": hidden_pregrasp_mode_frames,
        "hidden_mode_frames": hidden_mode_frames,
        "mode_conditioning_policy": manifest.get(
            "mode_conditioning_policy", "pregrasp_hidden"
        ),
        "task_language_policy": task_language_policy,
        "lift_residual_supervision": manifest.get(
            "lift_residual_supervision", "stage_constant_v1"
        ),
        "primitive_progress_range": [progress_min, progress_max],
        "anchor_reconstruction_max_error_m": anchor_reconstruction_max_error_m,
        "source_comparison_enabled": args.source_root is not None,
        "normalization_stats_policy": manifest.get("normalization_stats_policy"),
        "unsafe_normalization_dimensions": unsafe_normalization_dimensions,
        "action_chunk_activity": chunk_activity,
        "idle_chunk_policy": (
            None
            if absolute_contract
            else "audit_only_keep_valid_zero_residuals_until_matched_filter_ablation"
        ),
    }
    return _finish(args.output, errors, metrics)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _stage_id(value: Any) -> int:
    if isinstance(value, list):
        value = value[0]
    result = int(value)
    if not 0 <= result < len(MOBILE_STAGE_NAMES):
        raise ValueError(f"invalid stage id: {result}")
    return result


def _finish(path: Path, errors: list[str], metrics: dict[str, Any]) -> int:
    absolute_contract = metrics.get("action_contract") == "absolute_v1"
    payload = {
        "schema_version": 1,
        "protocol": (
            "pi05-absolute-dataset-audit-v1"
            if absolute_contract
            else "pi05-residual-dataset-audit-v1"
        ),
        "status": "passed" if not errors else "failed",
        "errors": errors[:100],
        "error_count": len(errors),
        "metrics": metrics,
        "claim_boundary": (
            "schema, expert independence, observation-derived tool state, nonzero base "
            "supervision, mode leakage, progress, and normalization audit; physical "
            "success remains linked through the collector summaries"
            if absolute_contract
            else "schema, authority, mode-leakage, progress, and source-action "
            "reconstruction audit; physical success remains linked through the "
            "collector summary"
        ),
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(json.dumps(payload, indent=2))
    return 0 if not errors else 2


if __name__ == "__main__":
    raise SystemExit(main())
