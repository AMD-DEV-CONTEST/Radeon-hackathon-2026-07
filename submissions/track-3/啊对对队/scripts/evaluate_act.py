from __future__ import annotations

import argparse
from dataclasses import asdict, replace
import json
from pathlib import Path

from parcel_sorter.config import load_config
from parcel_sorter.dataset import JsonlTrajectoryWriter
from parcel_sorter.episode_plan import build_episode_plan
from parcel_sorter.genesis_env import GenesisParcelEnv
from parcel_sorter.metrics import MetricsAccumulator
from parcel_sorter.policy import LeRobotPolicyAdapter, SlowFastVLAExpertPolicy
from parcel_sorter.provenance import runtime_report
from parcel_sorter.randomization import DomainRandomizer
from parcel_sorter.runner import run_policy_episode, save_episode_writers
from parcel_sorter.task_conditioning import build_conditioned_task


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Evaluate an ACT, Diffusion, or SmolVLA LeRobot checkpoint in Genesis"
    )
    parser.add_argument("--checkpoint", required=True)
    parser.add_argument("--config", default="configs/baseline.toml")
    parser.add_argument("--backend", choices=("rocm", "cuda"), default="rocm")
    parser.add_argument("--episodes", type=int, default=10)
    parser.add_argument("--start-episode", type=int, default=0)
    parser.add_argument(
        "--profile",
        action="append",
        dest="selected_profiles",
        help="evaluate this profile; repeat for matched per-profile evaluation",
    )
    parser.add_argument("--output", default="outputs/eval-act")
    parser.add_argument("--nominal", action="store_true")
    parser.add_argument("--record-video", action="store_true")
    parser.add_argument(
        "--n-action-steps",
        type=int,
        help="override how many predicted actions are executed before replanning",
    )
    parser.add_argument(
        "--action-position-mode",
        choices=("absolute", "delta"),
        default="absolute",
        help="interpret the first three policy outputs as absolute XYZ or XYZ deltas",
    )
    parser.add_argument("--fail-on-unsuccessful", action="store_true")
    parser.add_argument(
        "--dynamic-task-text",
        action="store_true",
        help="condition the policy on parcel profile and destination bin",
    )
    parser.add_argument(
        "--slow-fast-vla",
        action="store_true",
        help="run slow VLA residual updates inside the fast expert safety controller",
    )
    parser.add_argument("--vla-refresh-steps", type=int, default=3)
    parser.add_argument("--vla-residual-limit-m", type=float, default=0.01)
    parser.add_argument("--vla-min-progress-ratio", type=float, default=0.5)
    parser.add_argument(
        "--collision-checked-reset",
        action="store_true",
        help="enable the collision-tested fallback reset used by the expert safety layer",
    )
    parser.add_argument(
        "--geometry-aware-grasp-planning",
        action="store_true",
        help="enable Radeon IK/collision-ranked shape-aware grasp planning",
    )
    parser.add_argument(
        "--tri-suction",
        action="store_true",
        help="enable the physical three-cup suction end effector",
    )
    args = parser.parse_args()
    if args.episodes < 1 or args.start_episode < 0:
        parser.error("episodes must be positive and start-episode cannot be negative")
    if args.vla_refresh_steps < 1:
        parser.error("vla-refresh-steps must be positive")
    if args.vla_residual_limit_m < 0:
        parser.error("vla-residual-limit-m cannot be negative")
    if not 0 < args.vla_min_progress_ratio <= 1:
        parser.error("vla-min-progress-ratio must be in (0, 1]")

    config = load_config(args.config)
    if args.nominal:
        config = replace(config, randomization=replace(config.randomization, enabled=False))
    if (
        args.collision_checked_reset
        or args.geometry_aware_grasp_planning
        or args.tri_suction
    ):
        config = replace(
            config,
            task=replace(
                config.task,
                geometry_aware_grasp_planning_enabled=(
                    config.task.geometry_aware_grasp_planning_enabled
                    or args.geometry_aware_grasp_planning
                ),
                tri_suction_enabled=(
                    config.task.tri_suction_enabled or args.tri_suction
                ),
            ),
            control=replace(
                config.control,
                collision_checked_reset_enabled=(
                    config.control.collision_checked_reset_enabled
                    or args.collision_checked_reset
                ),
            ),
        )
    try:
        config.validate()
    except ValueError as exc:
        parser.error(str(exc))
    output = Path(args.output)
    output.mkdir(parents=True, exist_ok=True)
    writer = JsonlTrajectoryWriter(output / "audit_dataset")
    policy = LeRobotPolicyAdapter(
        args.checkpoint,
        config,
        action_steps_override=args.n_action_steps,
        action_position_mode=args.action_position_mode,
    )
    randomizer = DomainRandomizer(config.randomization, config.seed, config.parcel_profiles)
    try:
        plan = build_episode_plan(
            config.parcel_profiles,
            args.episodes,
            args.start_episode,
            tuple(args.selected_profiles or ()),
        )
    except ValueError as exc:
        parser.error(str(exc))
    metrics = MetricsAccumulator()
    profile_metrics: dict[str, MetricsAccumulator] = {}
    reports = []

    for offset, spec in enumerate(plan):
        episode_index = spec.episode_index
        sample = (
            randomizer.sample(episode_index)
            if spec.profile_id is None
            else randomizer.sample_profile(spec.profile_id, episode_index)
        )
        writer.assert_episode_available(episode_index)
        video_path = None
        if args.record_video or (config.output.record_first_episode and offset == 0):
            video_path = output / "videos" / f"episode_{episode_index:06d}.mp4"
        with GenesisParcelEnv(
            config,
            sample,
            backend=args.backend,
            video_path=video_path,
            capture_sensors=True,
        ) as env:
            episode_policy = policy
            if args.slow_fast_vla:
                episode_policy = SlowFastVLAExpertPolicy(
                    policy,
                    env.expert,
                    refresh_steps=args.vla_refresh_steps,
                    residual_limit_m=args.vla_residual_limit_m,
                    min_progress_ratio=args.vla_min_progress_ratio,
                )
            episode_policy.reset()
            report = run_policy_episode(
                env,
                config,
                sample,
                episode_index,
                episode_policy,
                (writer,),
                task_instruction=(
                    build_conditioned_task(sample.profile_id, sample.destination)
                    if args.dynamic_task_text
                    else None
                ),
            )
            if args.slow_fast_vla:
                report.safety_summary["slow_fast_vla"] = episode_policy.summary()
        save_episode_writers(report, writer, None)
        reports.append(report.to_dict())
        metrics.add(report.result)
        profile_metrics.setdefault(sample.profile_id, MetricsAccumulator()).add(report.result)
        print(
            json.dumps(
                {
                    "episode": episode_index,
                    "profile": sample.profile_id,
                    "success": report.result.success,
                }
            )
        )

    payload = {
        "runtime": runtime_report(),
        "checkpoint": str(Path(args.checkpoint).resolve()),
        "policy_type": policy.policy_type,
        "n_action_steps_override": args.n_action_steps,
        "action_position_mode": args.action_position_mode,
        "dynamic_task_text": args.dynamic_task_text,
        "slow_fast_vla": args.slow_fast_vla,
        "vla_refresh_steps": args.vla_refresh_steps,
        "vla_residual_limit_m": args.vla_residual_limit_m,
        "vla_min_progress_ratio": args.vla_min_progress_ratio,
        "evaluation_range": {
            "start_episode": min(spec.episode_index for spec in plan),
            "end_episode": max(spec.episode_index for spec in plan),
            "num_episodes": len(plan),
            "profile_filter": list(args.selected_profiles or ()),
            "episodes_per_profile": args.episodes if args.selected_profiles else None,
        },
        "config": asdict(config),
        "summary": metrics.summary(),
        "profile_summaries": {
            profile_id: accumulator.summary()
            for profile_id, accumulator in sorted(profile_metrics.items())
        },
        "episodes": reports,
    }
    with (output / "summary.json").open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
    print(json.dumps(payload["summary"], ensure_ascii=False, indent=2))
    all_successful = all(report["result"]["success"] for report in reports)
    return 2 if args.fail_on_unsuccessful and not all_successful else 0


if __name__ == "__main__":
    raise SystemExit(main())
