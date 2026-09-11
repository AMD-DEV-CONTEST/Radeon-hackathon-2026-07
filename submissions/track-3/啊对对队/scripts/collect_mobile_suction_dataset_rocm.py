#!/usr/bin/env python3
"""Collect parameterized mobile suction episodes and merge successful shards."""

from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import math
from pathlib import Path
import shutil
import subprocess
import sys
from typing import Any

from parcel_sorter.mobile_adaptive_retry import classify_mobile_failure


MAX_EXPERT_EPISODE_DATASET_BYTES = 25_000_000
PI05_CAMPAIGN_POLICY_MODES = ("pi05_residual", "pi05_absolute")
PI05_VLA_ROUTING_POLICY_MODES = frozenset((*PI05_CAMPAIGN_POLICY_MODES, "shadow"))
GRASP_MODE_ROUTE_MISMATCH_FAILURE = "grasp_mode_route_mismatch_before_actuation"


def _grasp_mode_route_mismatch(summary: dict[str, Any]) -> bool:
    """Detect a required route mismatch without relying on scene stability."""

    if summary.get("failure_stage") == GRASP_MODE_ROUTE_MISMATCH_FAILURE:
        return True
    policy = summary.get("policy")
    if not isinstance(policy, dict):
        policy = {}
    selection = summary.get("vla_grasp_mode_selection")
    if not isinstance(selection, dict):
        selection = {}
    if selection.get("failure_stage") == GRASP_MODE_ROUTE_MISMATCH_FAILURE:
        return True
    if selection.get("mismatch_before_actuation") is True:
        return True

    def first_present(*values: object) -> object | None:
        for value in values:
            if value is not None:
                return value
        return None

    routes_execution = first_present(
        selection.get("routes_execution"),
        summary.get("vla_routes_grasp_mode"),
        policy.get("vla_routes_grasp_mode"),
    )
    matched = first_present(
        selection.get("matched"),
        summary.get("grasp_mode_match"),
        policy.get("grasp_mode_match"),
    )
    required = first_present(
        selection.get("required"),
        summary.get("grasp_mode_verdict_required"),
        policy.get("grasp_mode_verdict_required"),
    )
    return routes_execution is True and matched is False and required is not False


def _collection_failure_stage(
    return_code: int,
    summary: dict[str, Any],
) -> str | None:
    """Prefer explicit VLA route failures over generic physical-gate labels."""

    if return_code != 0 and not summary:
        return "runtime_failure"
    if not bool(summary.get("success")) and _grasp_mode_route_mismatch(summary):
        return GRASP_MODE_ROUTE_MISMATCH_FAILURE
    return classify_mobile_failure(summary)


def _validate_episode(item: dict[str, Any], seen: set[str]) -> None:
    episode_id = str(item.get("episode_id", ""))
    if not episode_id or episode_id in seen:
        raise ValueError(f"episode_id must be non-empty and unique: {episode_id!r}")
    seen.add(episode_id)
    cooperative_cradle = bool(item.get("cooperative_cradle", False))
    max_dimension_m = 1.70 if cooperative_cradle else 0.60
    if len(item.get("size_m", ())) != 3 or any(
        not 0.01 <= float(value) <= max_dimension_m for value in item["size_m"]
    ):
        raise ValueError(f"invalid size_m for {episode_id}")
    max_mass_kg = 8.0 if cooperative_cradle else 5.0
    if not 0.05 <= float(item.get("mass_kg", 0.0)) <= max_mass_kg:
        raise ValueError(f"invalid mass_kg for {episode_id}")
    if not 0.1 <= float(item.get("friction", 0.0)) <= 2.0:
        raise ValueError(f"invalid friction for {episode_id}")
    if len(item.get("offset_m", ())) != 2 or any(
        abs(float(value)) > 0.025 for value in item["offset_m"]
    ):
        raise ValueError(f"invalid offset_m for {episode_id}")
    shape = str(item.get("shape", "box"))
    orientation = str(item.get("orientation_mode", "yaw"))
    grasp_mode = str(item.get("grasp_mode", "side_suction"))
    minimum_sealed_cups = int(item.get("minimum_sealed_cups", 2))
    if shape not in {"box", "cylinder"}:
        raise ValueError(f"invalid shape for {episode_id}")
    if orientation not in {"yaw", "upright", "horizontal"}:
        raise ValueError(f"invalid orientation_mode for {episode_id}")
    if grasp_mode not in {"top_suction", "side_suction", "cooperative_cradle"}:
        raise ValueError(f"invalid grasp_mode for {episode_id}")
    if not 1 <= minimum_sealed_cups <= 3:
        raise ValueError(f"invalid minimum_sealed_cups for {episode_id}")
    if (shape == "box") != (orientation == "yaw"):
        raise ValueError(f"shape/orientation mismatch for {episode_id}")
    if shape == "cylinder":
        diameter_indices = (0, 1) if orientation == "upright" else (1, 2)
        if abs(
            float(item["size_m"][diameter_indices[0]])
            - float(item["size_m"][diameter_indices[1]])
        ) > 1e-6:
            raise ValueError(f"cylinder diameter dimensions differ for {episode_id}")
    if not -math.pi <= float(item.get("yaw_rad", 0.0)) <= math.pi:
        raise ValueError(f"invalid yaw_rad for {episode_id}")
    recovery_offset = item.get("recovery_contact_offset_m", (0.0, 0.0))
    if len(recovery_offset) != 2 or any(
        abs(float(value)) > 0.008 for value in recovery_offset
    ):
        raise ValueError(f"invalid recovery_contact_offset_m for {episode_id}")
    penetration_delta = float(item.get("recovery_contact_penetration_delta_m", 0.0))
    if not -0.0015 <= penetration_delta <= 0.0015:
        raise ValueError(
            f"invalid recovery_contact_penetration_delta_m for {episode_id}"
        )
    cradle_delta = float(item.get("recovery_cradle_engagement_delta_m", 0.0))
    if not -0.010 <= cradle_delta <= 0.010:
        raise ValueError(f"invalid recovery_cradle_engagement_delta_m for {episode_id}")
    if cradle_delta and not cooperative_cradle:
        raise ValueError(f"cradle engagement recovery requires cradle mode: {episode_id}")
    left_lift_offset = item.get("recovery_left_lift_offset_m", (0.0, 0.0, 0.0))
    if len(left_lift_offset) != 3 or math.sqrt(
        sum(float(value) ** 2 for value in left_lift_offset)
    ) > 0.005:
        raise ValueError(f"invalid recovery_left_lift_offset_m for {episode_id}")
    if any(float(value) for value in left_lift_offset) and not cooperative_cradle:
        raise ValueError(f"left lift recovery requires cradle mode: {episode_id}")
    right_lift_offset = item.get("recovery_right_lift_offset_m", (0.0, 0.0, 0.0))
    if len(right_lift_offset) != 3 or math.sqrt(
        sum(float(value) ** 2 for value in right_lift_offset)
    ) > 0.008:
        raise ValueError(f"invalid recovery_right_lift_offset_m for {episode_id}")
    if any(float(value) for value in right_lift_offset) and not cooperative_cradle:
        raise ValueError(f"right lift recovery requires cradle mode: {episode_id}")
    approach_scale = float(item.get("recovery_approach_speed_scale", 1.0))
    vertical_scale = float(item.get("recovery_vertical_speed_scale", 1.0))
    if not 0.40 <= approach_scale <= 1.0:
        raise ValueError(f"invalid recovery_approach_speed_scale for {episode_id}")
    if not 0.60 <= vertical_scale <= 1.0:
        raise ValueError(f"invalid recovery_vertical_speed_scale for {episode_id}")
    retry_index = int(item.get("retry_index", 0))
    if not 0 <= retry_index <= 2:
        raise ValueError(f"invalid retry_index for {episode_id}")


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    temporary.replace(path)


def _cli_float(value: Any) -> str:
    """Format physical parameters without exponent syntax confusing argparse."""

    rendered = f"{float(value):.10f}".rstrip("0").rstrip(".")
    return "0" if rendered in {"", "-0"} else rendered


def _sha256_file(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def _mode_statistics(
    results: list[dict[str, Any]], modes: list[str]
) -> dict[str, dict[str, Any]]:
    statistics = {}
    for mode in modes:
        selected = [
            item
            for item in results
            if str((item.get("parameters") or {}).get("grasp_mode")) == mode
        ]
        successes = sum(bool(item.get("success")) for item in selected)
        attempts = len(selected)
        statistics[mode] = {
            "attempts": attempts,
            "successes": successes,
            "failures": attempts - successes,
            "success_rate": successes / attempts if attempts else None,
        }
    return statistics


def _quota_statistics(
    results: list[dict[str, Any]], quotas: dict[str, int]
) -> dict[str, Any]:
    accepted_by_cell = {cell: 0 for cell in quotas}
    for item in results:
        if not bool(item.get("success")):
            continue
        cell = str((item.get("parameters") or {}).get("design_cell", ""))
        if cell in accepted_by_cell:
            accepted_by_cell[cell] += 1
    remaining_by_cell = {
        cell: max(0, target - accepted_by_cell[cell])
        for cell, target in quotas.items()
    }
    return {
        "enabled": bool(quotas),
        "target_successes": sum(quotas.values()),
        "accepted_successes": sum(accepted_by_cell.values()),
        "accepted_by_design_cell": accepted_by_cell,
        "remaining_by_design_cell": remaining_by_cell,
        "complete": bool(quotas) and not any(remaining_by_cell.values()),
    }


def _pilot_yield_gate(
    mode_statistics: dict[str, dict[str, Any]],
    minimum_attempts_per_mode: int,
    minimum_success_rate_per_mode: float,
) -> dict[str, Any]:
    enabled = (
        minimum_attempts_per_mode > 0 and minimum_success_rate_per_mode > 0.0
    )
    required_successes = (
        math.ceil(
            minimum_attempts_per_mode * minimum_success_rate_per_mode - 1e-12
        )
        if enabled
        else 0
    )
    futile_modes = (
        [
            mode
            for mode, item in mode_statistics.items()
            if int(item["attempts"]) < minimum_attempts_per_mode
            and int(item["successes"])
            + (minimum_attempts_per_mode - int(item["attempts"]))
            < required_successes
        ]
        if enabled
        else []
    )
    mature = enabled and all(
        int(item["attempts"]) >= minimum_attempts_per_mode
        for item in mode_statistics.values()
    )
    rate_failed_modes = (
        [
            mode
            for mode, item in mode_statistics.items()
            if float(item["success_rate"]) < minimum_success_rate_per_mode
        ]
        if mature
        else []
    )
    failed_modes = sorted(set(futile_modes + rate_failed_modes))
    return {
        "enabled": enabled,
        "minimum_attempts_per_mode": minimum_attempts_per_mode,
        "minimum_success_rate_per_mode": minimum_success_rate_per_mode,
        "required_successes_per_mode": required_successes,
        "mature": mature,
        "futile_modes": futile_modes,
        "failed_modes": failed_modes,
        "status": (
            "failed"
            if failed_modes
            else "passed"
            if mature
            else "pending"
            if enabled
            else "disabled"
        ),
    }


def _verified_collection_success(
    return_code: int,
    summary: dict[str, Any],
    *,
    audit_only: bool,
    dataset_root: Path,
) -> bool:
    task_success = return_code == 0 and bool(summary.get("success"))
    if audit_only:
        return task_success
    dataset = summary.get("dataset") or {}
    return bool(
        task_success
        and dataset.get("saved") is True
        and int(dataset.get("frames", 0)) > 0
        and dataset.get("storage_format") == "video"
        and 0 < int(dataset.get("bytes", 0)) <= MAX_EXPERT_EPISODE_DATASET_BYTES
        and dataset_root.is_dir()
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--backend", choices=("rocm", "cuda"), default="rocm")
    parser.add_argument(
        "--wrist-rgbd",
        action="store_true",
        help="record and provide synchronized left-wrist RGB-D in every rollout",
    )
    parser.add_argument("--max-episodes", type=int)
    parser.add_argument(
        "--profile",
        action="append",
        help="run only the selected profile; repeat to select multiple profiles",
    )
    parser.add_argument(
        "--episode-id",
        action="append",
        help="run only the selected episode id; repeat to select multiple episodes",
    )
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--audit-only", action="store_true")
    parser.add_argument(
        "--record-pi05-absolute-replay",
        action="store_true",
        help="record only full-authority successful absolute-VLA episodes",
    )
    parser.add_argument("--smolvla-checkpoint", type=Path)
    parser.add_argument(
        "--vla-policy-service-ready",
        type=Path,
        help="reuse a locally persistent PI0.5 policy process across episodes",
    )
    parser.add_argument(
        "--policy-mode",
        choices=(
            "shadow",
            "base_residual",
            "base_arm_residual",
            "base_dual_arm_residual",
            "pi05_residual",
            "pi05_absolute",
        ),
        default="shadow",
    )
    parser.add_argument("--policy-hz", type=int, default=3)
    parser.add_argument(
        "--pi05-chunk-execution-protocol",
        choices=(
            "first-action-hold-v1",
            "pi05-window-aggregate-v1",
            "pi05-open-loop-queue-v1",
        ),
        default="first-action-hold-v1",
    )
    parser.add_argument("--pi05-chunk-execution-steps", type=int, default=1)
    parser.add_argument(
        "--pi05-stage-chunk-execution-steps",
        type=json.loads,
        help="optional JSON object overriding PI0.5 execution steps per task stage",
    )
    parser.add_argument(
        "--require-vla-goal-verdict",
        action="store_true",
        help="require the VLA progress latch and geometric goal verifier",
    )
    parser.add_argument(
        "--require-vla-grasp-mode",
        action="store_true",
        help="require PI0.5 to select the configured safe grasp family before execution",
    )
    parser.add_argument(
        "--record-media-per-profile",
        action="store_true",
        help="record MP4 and final PNG for the first episode of each profile",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=1,
        help="Concurrent isolated rollout processes; values above one require --audit-only",
    )
    parser.add_argument(
        "--pilot-min-attempts-per-mode",
        type=int,
        default=0,
        help="evaluate the pilot yield gate after every mode reaches this count",
    )
    parser.add_argument(
        "--pilot-min-success-rate",
        type=float,
        default=0.0,
        help="stop collection when any mature mode falls below this success rate",
    )
    parser.add_argument(
        "--enforce-config-success-quotas",
        action="store_true",
        help="stop each design cell at the successful-episode quota in the plan",
    )
    args = parser.parse_args()
    if args.output.exists() and any(args.output.iterdir()) and not args.resume:
        parser.error(f"output directory must be new or empty: {args.output}")
    if args.max_episodes is not None and args.max_episodes < 1:
        parser.error("max-episodes must be positive")
    if args.workers < 1:
        parser.error("workers must be positive")
    if args.workers > 1 and not args.audit_only:
        parser.error("parallel workers are supported only for audit-only campaigns")
    gate_count_enabled = args.pilot_min_attempts_per_mode > 0
    gate_rate_enabled = args.pilot_min_success_rate > 0.0
    if args.pilot_min_attempts_per_mode < 0:
        parser.error("pilot minimum attempts per mode must be non-negative")
    if gate_count_enabled != gate_rate_enabled:
        parser.error("pilot yield gate requires both count and success-rate thresholds")
    if not 0.0 <= args.pilot_min_success_rate <= 1.0:
        parser.error("pilot minimum success rate must be in [0, 1]")
    if (gate_count_enabled or args.enforce_config_success_quotas) and args.workers != 1:
        parser.error("yield gates and success quotas require one sequential worker")
    if args.enforce_config_success_quotas and args.audit_only:
        parser.error("success quotas require recorded training episodes")
    if args.record_pi05_absolute_replay and args.audit_only:
        parser.error("absolute replay recording is incompatible with audit-only")
    if args.policy_mode != "shadow" and args.smolvla_checkpoint is None:
        parser.error("base_residual mode requires --smolvla-checkpoint")
    if args.vla_policy_service_ready is not None and args.smolvla_checkpoint is None:
        parser.error("persistent policy service requires --smolvla-checkpoint")
    if (
        args.vla_policy_service_ready is not None
        and not args.vla_policy_service_ready.is_file()
    ):
        parser.error("persistent policy service ready file is missing")
    if not 1 <= args.pi05_chunk_execution_steps <= 30:
        parser.error("PI0.5 chunk execution steps must be in [1, 30]")
    if args.pi05_stage_chunk_execution_steps is not None:
        if not isinstance(args.pi05_stage_chunk_execution_steps, dict):
            parser.error("PI0.5 stage chunk execution steps must be a JSON object")
        allowed_chunk_stages = {
            "pregrasp",
            "grasp_approach",
            "lift",
            "transport",
            "place",
            "release",
        }
        unknown_chunk_stages = (
            set(args.pi05_stage_chunk_execution_steps) - allowed_chunk_stages
        )
        if unknown_chunk_stages:
            parser.error(
                "unsupported PI0.5 stage chunk keys: "
                f"{sorted(unknown_chunk_stages)}"
            )
        if any(
            not isinstance(value, int) or not 1 <= value <= 30
            for value in args.pi05_stage_chunk_execution_steps.values()
        ):
            parser.error("each PI0.5 stage chunk execution step must be in [1, 30]")
    if (
        args.pi05_chunk_execution_protocol == "first-action-hold-v1"
        and (
            args.pi05_chunk_execution_steps != 1
            or any(
                value != 1
                for value in (args.pi05_stage_chunk_execution_steps or {}).values()
            )
        )
    ):
        parser.error("first-action hold requires one chunk execution step in every stage")
    if (
        args.pi05_chunk_execution_protocol != "first-action-hold-v1"
        and args.policy_mode not in {"pi05_residual", "pi05_absolute"}
    ):
        parser.error("multi-step chunk execution requires a PI0.5 policy mode")
    if args.require_vla_goal_verdict and args.smolvla_checkpoint is None:
        parser.error("VLA goal verdict requires --smolvla-checkpoint")
    if args.require_vla_grasp_mode and (
        args.smolvla_checkpoint is None
        or args.policy_mode not in PI05_VLA_ROUTING_POLICY_MODES
    ):
        parser.error("VLA grasp-mode selection requires PI0.5 or shadow mode")
    if args.record_pi05_absolute_replay and (
        args.smolvla_checkpoint is None
        or args.policy_mode != "pi05_absolute"
        or not args.require_vla_goal_verdict
        or not args.require_vla_grasp_mode
    ):
        parser.error(
            "absolute replay requires pi05_absolute, mode routing, and goal verdict"
        )
    if args.wrist_rgbd and args.audit_only and args.smolvla_checkpoint is None:
        parser.error("audit-only wrist RGB-D requires a VLA checkpoint")

    config = json.loads(args.config.read_text(encoding="utf-8"))
    episodes = list(config.get("episodes", ()))
    if args.profile:
        selected_profiles = set(args.profile)
        episodes = [
            item for item in episodes if str(item.get("profile")) in selected_profiles
        ]
    if args.episode_id:
        selected_episode_ids = set(args.episode_id)
        episodes = [
            item
            for item in episodes
            if str(item.get("episode_id")) in selected_episode_ids
        ]
    if args.max_episodes is not None:
        episodes = episodes[: args.max_episodes]
    if not episodes:
        parser.error("collection config contains no episodes")
    requested_modes = sorted({str(item.get("grasp_mode")) for item in episodes})
    success_quotas: dict[str, int] = {}
    if args.enforce_config_success_quotas:
        if args.profile or args.episode_id or args.max_episodes is not None:
            parser.error("success quotas cannot be combined with episode filters")
        raw_quotas = config.get("success_quotas_by_design_cell")
        if not isinstance(raw_quotas, dict) or not raw_quotas:
            parser.error("collection config has no success quotas")
        if any(
            not isinstance(cell, str)
            or not isinstance(target, int)
            or isinstance(target, bool)
            or target < 1
            for cell, target in raw_quotas.items()
        ):
            parser.error("success quotas must map design-cell names to positive integers")
        available_cells = {str(item.get("design_cell", "")) for item in episodes}
        missing_cells = set(raw_quotas) - available_cells
        extra_cells = available_cells - set(raw_quotas)
        if missing_cells or extra_cells:
            parser.error(
                "success quota cells must exactly match planned design cells: "
                f"missing={sorted(missing_cells)}, extra={sorted(extra_cells)}"
            )
        success_quotas = dict(raw_quotas)
    seen: set[str] = set()
    for item in episodes:
        _validate_episode(item, seen)
    seen_order = {
        str(item["episode_id"]): index for index, item in enumerate(episodes)
    }

    root = Path(__file__).resolve().parent.parent
    runtime_contract = {
        "config_sha256": _sha256_file(args.config),
        "collector_sha256": _sha256_file(Path(__file__).resolve()),
        "failure_classifier_sha256": _sha256_file(
            root / "src/parcel_sorter/mobile_adaptive_retry.py"
        ),
        "python_executable": str(Path(sys.executable).resolve()),
    }
    checkpoint_selection: dict[str, Any] | None = None
    if args.smolvla_checkpoint is not None:
        checkpoint_selection = {
            "source": "direct_path",
            "checkpoint": str(args.smolvla_checkpoint),
        }
        if args.smolvla_checkpoint.is_file():
            from parcel_sorter.checkpoint_registry import load_active_checkpoint

            selected = load_active_checkpoint(args.smolvla_checkpoint, project_root=root)
            args.smolvla_checkpoint = selected.checkpoint
            checkpoint_selection = {"source": "promoted_registry", **selected.to_dict()}
    args.output.mkdir(parents=True, exist_ok=True)
    existing_results: dict[str, dict[str, Any]] = {}
    resumed_runtime_contracts: list[dict[str, Any]] = []
    existing_summary_path = args.output / "collection-summary.json"
    if args.resume and existing_summary_path.is_file():
        existing = json.loads(existing_summary_path.read_text(encoding="utf-8"))
        previous_contracts = [
            contract
            for contract in (
                *existing.get("resumed_runtime_contracts", ()),
                existing.get("runtime_contract"),
            )
            if isinstance(contract, dict) and contract != runtime_contract
        ]
        for contract in previous_contracts:
            if contract not in resumed_runtime_contracts:
                resumed_runtime_contracts.append(contract)
        existing_results = {
            str(item["episode_id"]): item for item in existing.get("results", ())
        }
    results = []
    successful_roots = []
    pending = []
    media_episode_ids: set[str] = set()
    if args.record_media_per_profile:
        recorded_profiles: set[str] = set()
        for item in episodes:
            profile = str(item["profile"])
            if profile not in recorded_profiles:
                recorded_profiles.add(profile)
                media_episode_ids.add(str(item["episode_id"]))
    for item in episodes:
        episode_id = str(item["episode_id"])
        shard = args.output / "shards" / episode_id
        dataset_root = shard / "lerobot_dataset"
        retained = existing_results.get(episode_id)
        if retained is not None:
            summary_path = Path(str(retained.get("summary", "")))
            retained_complete = bool(
                summary_path.is_file()
                and (
                    args.audit_only
                    or not retained.get("success")
                    or dataset_root.is_dir()
                )
            )
            if retained_complete:
                if retained.get("success") and not args.audit_only:
                    successful_roots.append(dataset_root.resolve())
                results.append(retained)
                continue
        pending.append(item)

    def collect_one(item: dict[str, Any]) -> dict[str, Any]:
        episode_id = str(item["episode_id"])
        shard = args.output / "shards" / episode_id
        dataset_root = shard / "lerobot_dataset"
        command = [
            sys.executable,
            str(root / "scripts/evaluate_mobile_suction_lift_rocm.py"),
            "--backend",
            args.backend,
            "--output",
            str(shard / "run"),
            "--parcel-profile",
            str(item["profile"]),
            "--parcel-shape",
            str(item.get("shape", "box")),
            "--parcel-orientation",
            str(item.get("orientation_mode", "yaw")),
            "--parcel-yaw-rad",
            _cli_float(item.get("yaw_rad", 0.0)),
            "--grasp-mode",
            str(item.get("grasp_mode", "side_suction")),
            "--minimum-sealed-cups",
            str(int(item.get("minimum_sealed_cups", 2))),
            "--parcel-size-m",
            *(_cli_float(value) for value in item["size_m"]),
            "--parcel-mass-kg",
            _cli_float(item["mass_kg"]),
            "--parcel-friction",
            _cli_float(item["friction"]),
            "--parcel-offset-m",
            *(_cli_float(value) for value in item["offset_m"]),
            "--recovery-contact-offset-m",
            *(
                _cli_float(value)
                for value in item.get("recovery_contact_offset_m", (0.0, 0.0))
            ),
            "--recovery-contact-penetration-delta-m",
            _cli_float(item.get("recovery_contact_penetration_delta_m", 0.0)),
            "--recovery-cradle-engagement-delta-m",
            _cli_float(item.get("recovery_cradle_engagement_delta_m", 0.0)),
            "--recovery-left-lift-offset-m",
            *(
                _cli_float(value)
                for value in item.get(
                    "recovery_left_lift_offset_m", (0.0, 0.0, 0.0)
                )
            ),
            "--recovery-right-lift-offset-m",
            *(
                _cli_float(value)
                for value in item.get(
                    "recovery_right_lift_offset_m", (0.0, 0.0, 0.0)
                )
            ),
            "--recovery-approach-speed-scale",
            _cli_float(item.get("recovery_approach_speed_scale", 1.0)),
            "--recovery-vertical-speed-scale",
            _cli_float(item.get("recovery_vertical_speed_scale", 1.0)),
            "--recovery-lift-height-delta-m",
            _cli_float(item.get("recovery_lift_height_delta_m", 0.0)),
            "--recovery-placement-clearance-m",
            _cli_float(item.get("recovery_placement_clearance_m", 0.015)),
            "--retry-index",
            str(int(item.get("retry_index", 0))),
        ]
        if item.get("cooperative_cradle"):
            command.append("--cooperative-cradle")
        if item.get("cradle_contact_memory"):
            command.append("--cradle-contact-memory")
        if args.wrist_rgbd:
            command.append("--wrist-rgbd")
        if not args.audit_only:
            command.extend(
                (
                    "--record-pi05-absolute-dataset"
                    if args.record_pi05_absolute_replay
                    else "--record-dataset",
                    str(dataset_root),
                )
            )
        if args.smolvla_checkpoint is not None:
            command.extend(
                (
                    "--smolvla-checkpoint",
                    str(args.smolvla_checkpoint),
                    "--policy-mode",
                    args.policy_mode,
                    "--policy-hz",
                    str(args.policy_hz),
                    "--pi05-chunk-execution-protocol",
                    args.pi05_chunk_execution_protocol,
                    "--pi05-chunk-execution-steps",
                    str(args.pi05_chunk_execution_steps),
                )
            )
            if args.pi05_stage_chunk_execution_steps is not None:
                command.extend(
                    (
                        "--pi05-stage-chunk-execution-steps",
                        json.dumps(
                            args.pi05_stage_chunk_execution_steps,
                            separators=(",", ":"),
                        ),
                    )
                )
            if args.require_vla_goal_verdict:
                command.append("--require-vla-goal-verdict")
            if args.require_vla_grasp_mode:
                command.append("--require-vla-grasp-mode")
            if args.vla_policy_service_ready is not None:
                command.extend(
                    (
                        "--vla-policy-service-ready",
                        str(args.vla_policy_service_ready),
                    )
                )
        if item.get("task_text"):
            command.extend(("--task-text", str(item["task_text"])))
        if episode_id in media_episode_ids:
            command.extend(
                (
                    "--record-video",
                    str(shard / "run" / "media" / f"{episode_id}.mp4"),
                    "--snapshot",
                    str(shard / "run" / "media" / f"{episode_id}.png"),
                )
            )
        shard.mkdir(parents=True, exist_ok=True)
        log_path = shard / "collector.log"
        with log_path.open("w", encoding="utf-8") as log:
            completed = subprocess.run(command, stdout=log, stderr=subprocess.STDOUT)
        summary_path = shard / "run/summary.json"
        summary = (
            json.loads(summary_path.read_text(encoding="utf-8"))
            if summary_path.is_file()
            else {}
        )
        success = _verified_collection_success(
            completed.returncode,
            summary,
            audit_only=args.audit_only,
            dataset_root=dataset_root,
        )
        return {
            "episode_id": episode_id,
            "profile": item["profile"],
            "parameters": item,
            "return_code": completed.returncode,
            "success": success,
            "failure_stage": _collection_failure_stage(completed.returncode, summary),
            "lift_success": summary.get("lift_success"),
            "transport_success": summary.get("transport_success"),
            "placed_before_release": summary.get("placed_before_release"),
            "released": summary.get("released"),
            "place_force_safety_abort": summary.get("place_force_safety_abort"),
            "placement_error_m": summary.get("placement_error_m"),
            "max_suction_force_n": summary.get("suction", {}).get(
                "max_suction_force_n"
            ),
            "max_contact_force_n": summary.get("suction", {}).get(
                "max_contact_force_n"
            ),
            "max_cradle_contact_force_n": (
                (summary.get("cradle") or {}).get("physical") or {}
            ).get("max_contact_force_n"),
            "frames": summary.get("dataset", {}).get("frames", 0),
            "dataset_saved": bool(summary.get("dataset", {}).get("saved")),
            "dataset_storage_format": summary.get("dataset", {}).get(
                "storage_format"
            ),
            "dataset_bytes": summary.get("dataset", {}).get("bytes", 0),
            "recovery_label": {
                "verified_success": success,
                "contact_offset_m": summary.get("recovery_parameters", {}).get(
                    "contact_offset_m",
                    list(item.get("recovery_contact_offset_m", (0.0, 0.0))),
                ),
                "contact_penetration_delta_m": summary.get(
                    "recovery_parameters", {}
                ).get(
                    "contact_penetration_delta_m",
                    item.get("recovery_contact_penetration_delta_m", 0.0),
                ),
                "approach_axis_world": summary.get("approach_axis_world"),
                "right_tool_axis_world": summary.get("right_tool_axis_world"),
                "cradle_engagement_delta_m": summary.get(
                    "recovery_parameters", {}
                ).get(
                    "cradle_engagement_delta_m",
                    item.get("recovery_cradle_engagement_delta_m", 0.0),
                ),
                "left_lift_offset_m": summary.get("recovery_parameters", {}).get(
                    "left_lift_offset_m",
                    list(item.get("recovery_left_lift_offset_m", (0.0, 0.0, 0.0))),
                ),
                "right_lift_offset_m": summary.get("recovery_parameters", {}).get(
                    "right_lift_offset_m",
                    list(item.get("recovery_right_lift_offset_m", (0.0, 0.0, 0.0))),
                ),
                "grasp_mode": summary.get("grasp_mode", item.get("grasp_mode")),
                "retry_index": int(item.get("retry_index", 0)),
            },
            "media": summary.get("media"),
            "summary": str(summary_path.resolve()),
            "log": str(log_path.resolve()),
        }

    yield_gate_failed = False
    quota_target_reached = False
    skipped_by_satisfied_quota = 0

    def control_state() -> tuple[dict[str, Any], dict[str, Any]]:
        mode_statistics = _mode_statistics(results, requested_modes)
        yield_gate = _pilot_yield_gate(
            mode_statistics,
            args.pilot_min_attempts_per_mode,
            args.pilot_min_success_rate,
        )
        return yield_gate, _quota_statistics(results, success_quotas)

    def write_progress(status: str) -> None:
        yield_gate, quota_statistics = control_state()
        _write_json(
            args.output / "collection-summary.json",
            {
                "schema_version": 1,
                "collection_id": config.get("collection_id"),
                "runtime_contract": runtime_contract,
                "resumed_runtime_contracts": resumed_runtime_contracts,
                "requested_episodes": len(episodes),
                "completed_episodes": len(results),
                "unattempted_episodes": len(episodes) - len(results),
                "successful_episodes": sum(
                    bool(result.get("success")) for result in results
                ),
                "mode_statistics": _mode_statistics(results, requested_modes),
                "yield_gate": yield_gate,
                "success_quota": quota_statistics,
                "skipped_by_satisfied_quota": skipped_by_satisfied_quota,
                "policy_visual_modality": (
                    "rgbd_wrist" if args.wrist_rgbd else "rgbd"
                ),
                "results": results,
                "status": status,
            },
        )

    def retain_result(result: dict[str, Any]) -> None:
        results.append(result)
        if result["success"] and not args.audit_only:
            successful_roots.append(
                (
                    args.output
                    / "shards"
                    / result["episode_id"]
                    / "lerobot_dataset"
                ).resolve()
            )
        results.sort(key=lambda item: seen_order[str(item["episode_id"])])

    initial_gate, initial_quota = control_state()
    yield_gate_failed = initial_gate["status"] == "failed"
    quota_target_reached = bool(initial_quota["complete"])
    if args.workers == 1:
        for item in pending:
            if yield_gate_failed or quota_target_reached:
                break
            if success_quotas:
                cell = str(item.get("design_cell", ""))
                quota_state = _quota_statistics(results, success_quotas)
                if (
                    quota_state["accepted_by_design_cell"][cell]
                    >= success_quotas[cell]
                ):
                    skipped_by_satisfied_quota += 1
                    continue
            retain_result(collect_one(item))
            yield_gate, quota_state = control_state()
            yield_gate_failed = yield_gate["status"] == "failed"
            quota_target_reached = bool(quota_state["complete"])
            write_progress(
                "yield_gate_failed"
                if yield_gate_failed
                else "success_quota_reached"
                if quota_target_reached
                else "collecting"
            )
    else:
        executor = ThreadPoolExecutor(max_workers=args.workers)
        try:
            for result in executor.map(collect_one, pending):
                retain_result(result)
                write_progress("collecting")
        finally:
            executor.shutdown(wait=True)

    merged_root = args.output / "lerobot_dataset"
    merge_error = None
    if successful_roots and not args.audit_only:
        if merged_root.exists():
            if not args.resume:
                raise RuntimeError(f"merged dataset already exists: {merged_root}")
            # The merged dataset is derived; source shards remain immutable and auditable.
            shutil.rmtree(merged_root)
        if args.record_pi05_absolute_replay:
            merge_command = [
                sys.executable,
                str(root / "scripts/merge_mobile_pi05_residual_datasets.py"),
                *(
                    argument
                    for source in successful_roots
                    for argument in ("--source", str(source))
                ),
                "--output",
                str(merged_root),
            ]
        else:
            editor = shutil.which("lerobot-edit-dataset")
            if editor is None:
                adjacent_editor = Path(sys.executable).parent / "lerobot-edit-dataset"
                editor = str(adjacent_editor) if adjacent_editor.is_file() else None
            if editor is None:
                raise RuntimeError("lerobot-edit-dataset is required to merge episode shards")
            repo_ids = ["local/mobile-bimanual-parcel-expert"] * len(successful_roots)
            merge_command = [
                editor,
                "--operation.type",
                "merge",
                "--operation.repo_ids",
                json.dumps(repo_ids),
                "--operation.roots",
                json.dumps([str(path) for path in successful_roots]),
                "--operation.concatenate_videos",
                "false",
                "--operation.concatenate_data",
                "false",
                "--new_repo_id",
                "local/mobile-bimanual-parcel-multiprofile",
                "--new_root",
                str(merged_root),
                "--push_to_hub",
                "false",
            ]
        merge_log = args.output / "merge.log"
        with merge_log.open("w", encoding="utf-8") as log:
            merged = subprocess.run(merge_command, stdout=log, stderr=subprocess.STDOUT)
        if merged.returncode != 0:
            merge_error = f"dataset merge failed with exit code {merged.returncode}"

    successful_count = sum(bool(result.get("success")) for result in results)
    final_yield_gate, final_quota = control_state()
    status = (
        "completed_audit_only"
        if args.audit_only and len(results) == len(episodes)
        else "yield_gate_failed"
        if yield_gate_failed
        else "success_quota_not_reached"
        if success_quotas and not quota_target_reached
        else
        "passed"
        if len(successful_roots) >= 2 and merge_error is None and merged_root.is_dir()
        else "insufficient_successes"
        if len(successful_roots) < 2
        else "merge_failed"
    )
    payload = {
        "schema_version": 1,
        "collection_id": config.get("collection_id"),
        "config": str(args.config.resolve()),
        "runtime_contract": runtime_contract,
        "resumed_runtime_contracts": resumed_runtime_contracts,
        "requested_episodes": len(episodes),
        "completed_episodes": len(results),
        "unattempted_episodes": len(episodes) - len(results),
        "successful_episodes": successful_count,
        "failed_episodes": len(results) - successful_count,
        "mode_statistics": _mode_statistics(results, requested_modes),
        "yield_gate": final_yield_gate,
        "success_quota": final_quota,
        "skipped_by_satisfied_quota": skipped_by_satisfied_quota,
        "policy_visual_modality": "rgbd_wrist" if args.wrist_rgbd else "rgbd",
        "merged_dataset_root": str(merged_root.resolve()) if merged_root.is_dir() else None,
        "checkpoint_selection": checkpoint_selection,
        "goal_verdict_required": args.require_vla_goal_verdict,
        "grasp_mode_verdict_required": args.require_vla_grasp_mode,
        "persistent_policy_service": bool(args.vla_policy_service_ready),
        "media_episode_ids": sorted(media_episode_ids),
        "merge_error": merge_error,
        "results": results,
        "successful_episode_order": [
            str(result["episode_id"])
            for result in results
            if bool(result.get("success"))
        ],
        "status": status,
        "claim_boundary": (
            "audit-only campaign; no episode is written to or merged into training data"
            if args.audit_only
            else (
                "only full-authority successful absolute-VLA episodes are merged; "
                "failed, fallback, safety-blended, and force-violating runs are excluded"
                if args.record_pi05_absolute_replay
                else "successful expert episodes are merged for training; failed runs remain audit-only"
            )
        ),
    }
    _write_json(args.output / "collection-summary.json", payload)
    print(json.dumps(payload))
    return 0 if status in {"passed", "completed_audit_only"} else 2


if __name__ == "__main__":
    raise SystemExit(main())
