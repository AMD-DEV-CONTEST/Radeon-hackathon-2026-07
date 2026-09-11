from __future__ import annotations

import argparse
from dataclasses import asdict, replace
import json
from pathlib import Path

from parcel_sorter.collection_plan import load_collection_requests
from parcel_sorter.config import load_config
from parcel_sorter.dataset import JsonlTrajectoryWriter, LeRobotTrajectoryWriter
from parcel_sorter.episode_plan import build_episode_plan, build_profile_episode_plan
from parcel_sorter.genesis_env import GenesisParcelEnv
from parcel_sorter.metrics import MetricsAccumulator
from parcel_sorter.provenance import runtime_report
from parcel_sorter.randomization import DomainRandomizer
from parcel_sorter.runner import run_expert_episode, save_episode_writers


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the deterministic Genesis parcel-sorting expert")
    parser.add_argument("--config", default="configs/baseline.toml")
    parser.add_argument("--backend", choices=("rocm", "cuda", "cpu"), default="rocm")
    parser.add_argument("--episodes", type=int, default=3)
    parser.add_argument("--start-episode", type=int, default=0)
    parser.add_argument(
        "--profile",
        action="append",
        dest="selected_profiles",
        help="collect this training profile; repeat for balanced per-profile collection",
    )
    parser.add_argument(
        "--collection-plan",
        help="frozen JSON from plan_balanced_collection.py; supports per-profile episode counts",
    )
    parser.add_argument(
        "--allow-unready-collection",
        action="store_true",
        help="acknowledge that a plan contains profiles requiring expert diagnostics",
    )
    parser.add_argument("--output", default=None)
    parser.add_argument("--viewer", action="store_true")
    parser.add_argument("--record-video", action="store_true")
    parser.add_argument("--lerobot", action="store_true")
    parser.add_argument("--record-sensors", action="store_true")
    parser.add_argument(
        "--nominal",
        action="store_true",
        help="disable domain randomization for deterministic hardware calibration",
    )
    parser.add_argument("--fail-on-unsuccessful", action="store_true")
    parser.add_argument(
        "--reset-qpos",
        type=float,
        nargs=9,
        metavar=("J1", "J2", "J3", "J4", "J5", "J6", "J7", "F1", "F2"),
        help="override the nine-joint reset pose for a controlled diagnostic",
    )
    parser.add_argument(
        "--size-aware-approach",
        action="store_true",
        help="enable geometry-aware horizontal-transit clearance for a controlled diagnostic",
    )
    parser.add_argument(
        "--approach-clearance-margin",
        type=float,
        default=None,
        help="add a fixed metres margin to size-aware transit clearance",
    )
    parser.add_argument(
        "--retry-retreat-distance",
        type=float,
        default=None,
        help="retreat this many metres laterally before a post-failure retry approach",
    )
    parser.add_argument(
        "--approach-step",
        type=float,
        default=None,
        help="limit every MOVE_PREGRASP Cartesian step for a controlled diagnostic",
    )
    parser.add_argument(
        "--approach-contact-brake-force",
        type=float,
        default=None,
        help="enable approach contact braking at this measured force threshold",
    )
    parser.add_argument(
        "--approach-contact-brake-step",
        type=float,
        default=None,
        help="maximum Cartesian retreat step used by approach contact braking",
    )
    parser.add_argument(
        "--approach-barrier-recovery-step",
        type=float,
        default=None,
        help="allow a larger vertical-only recovery step below the approach barrier",
    )
    parser.add_argument(
        "--precontact-aabb-guard-distance",
        type=float,
        default=None,
        help="enable the Genesis finger/parcel AABB pre-contact guard at this distance",
    )
    parser.add_argument(
        "--approach-stiffness-scale",
        type=float,
        default=None,
        help="scale approach arm Kp and preserve damping ratio by scaling Kv by sqrt(scale)",
    )
    parser.add_argument(
        "--approach-velocity-control",
        action="store_true",
        help="enable Jacobian damped-least-squares velocity control during MOVE_PREGRASP",
    )
    parser.add_argument(
        "--collision-checked-reset",
        action="store_true",
        help="use the fallback reset pose only when the historical pose intersects the parcel",
    )
    parser.add_argument(
        "--surface-aware-pregrasp",
        action="store_true",
        help="enable a parcel-height-aware side-contact band for non-flat box grasp capture",
    )
    parser.add_argument(
        "--geometry-aware-grasp-planning",
        action="store_true",
        help="select a collision-free shape-aware grasp pose with Radeon IK and Jacobian scoring",
    )
    parser.add_argument(
        "--parcel-gripper-adapter",
        action="store_true",
        help="use the generated open-source parcel finger adapter",
    )
    parser.add_argument(
        "--tri-suction",
        action="store_true",
        help="use the physical three-cup suction end effector for suction profiles",
    )
    parser.add_argument(
        "--parcel-gripper-extension-m",
        type=float,
        default=None,
        help="override the parcel finger extension length in metres",
    )
    parser.add_argument(
        "--parcel-gripper-density-kg-m3",
        type=float,
        default=None,
        help="override the effective adapter density used for finger inertia",
    )
    parser.add_argument(
        "--grasp-planning-reset-fallback-gate",
        action="store_true",
        help="plan only when collision checking actually selected the fallback reset pose",
    )
    parser.add_argument(
        "--grasp-planning-disable-collision-filter",
        action="store_true",
        help="ablation only: rank candidates without rejecting non-finger collisions",
    )
    parser.add_argument(
        "--grasp-planning-disable-manipulability-ranking",
        action="store_true",
        help="ablation only: remove the Jacobian minimum-singular-value ranking term",
    )
    parser.add_argument(
        "--grasp-planning-disable-symmetric-wrist",
        action="store_true",
        help="ablation only: generate only the canonical wrist orientation",
    )
    parser.add_argument(
        "--grasp-planning-disable-retry-replan",
        action="store_true",
        help="ablation only: retain the original feasible pose across grasp retries",
    )
    parser.add_argument(
        "--grasp-planning-blacklist-failed-candidate",
        action="store_true",
        help="exclude each failed selected pose family from the next retry",
    )
    parser.add_argument(
        "--grasp-planning-waypoint-gate",
        action="store_true",
        help="diagnostic: sweep commanded IK waypoints for non-finger collisions",
    )
    parser.add_argument(
        "--grasp-planning-stability-steps",
        type=int,
        default=None,
        help="require this many consecutive dual-finger contact frames before planned lift",
    )
    parser.add_argument(
        "--grasp-planning-final-approach-step",
        type=float,
        default=None,
        help="cap final planned grasp approach in metres per control step",
    )
    parser.add_argument(
        "--grasp-planning-disable-tiered-approach",
        action="store_true",
        help="ablation only: use the regular planned approach step for tall boxes",
    )
    parser.add_argument(
        "--grasp-planning-drop-step",
        type=float,
        default=None,
        help="cap final planned placement descent in metres per control step",
    )
    parser.add_argument(
        "--grasp-planning-transport-contract",
        action="store_true",
        help="stage planned payload raise, transfer, and descent with stable handoffs",
    )
    parser.add_argument(
        "--grasp-planning-disable-transport-lookahead",
        action="store_true",
        help="ablation only: use measured-pose feedback instead of a staged lookahead reference",
    )
    parser.add_argument(
        "--grasp-planning-raise-step",
        type=float,
        default=None,
        help="cap the planned payload raise in metres per control step",
    )
    parser.add_argument(
        "--grasp-planning-transport-step",
        type=float,
        default=None,
        help="cap planned horizontal payload transport in metres per control step",
    )
    parser.add_argument(
        "--grasp-planning-transfer-settle-steps",
        type=int,
        default=None,
        help="hold this many control frames at planned transport phase boundaries",
    )
    parser.add_argument(
        "--transport-slip-recovery",
        action="store_true",
        help="enable frozen mid-transport slip detection and bounded force recovery",
    )
    parser.add_argument(
        "--transport-slip-setdown-regrasp",
        action="store_true",
        help="set down, release, and replan after the frozen transport-slip signal",
    )
    args = parser.parse_args()
    if args.episodes < 1 or args.start_episode < 0:
        parser.error("episodes must be positive and start-episode cannot be negative")
    if args.lerobot and not args.record_sensors:
        parser.error("--lerobot requires --record-sensors so RGB-D frames are available")
    if args.collection_plan and args.selected_profiles:
        parser.error("--collection-plan cannot be combined with repeated --profile")

    config = load_config(args.config)
    if args.nominal:
        config = replace(
            config,
            randomization=replace(config.randomization, enabled=False),
        )
    if args.reset_qpos is not None:
        config = replace(
            config,
            control=replace(config.control, reset_qpos=tuple(args.reset_qpos)),
        )
    if (
        args.size_aware_approach
        or args.approach_clearance_margin is not None
        or args.retry_retreat_distance is not None
        or args.approach_step is not None
        or args.approach_contact_brake_force is not None
        or args.approach_contact_brake_step is not None
        or args.approach_barrier_recovery_step is not None
        or args.precontact_aabb_guard_distance is not None
        or args.approach_stiffness_scale is not None
        or args.approach_velocity_control
        or args.collision_checked_reset
        or args.surface_aware_pregrasp
        or args.geometry_aware_grasp_planning
        or args.parcel_gripper_adapter
        or args.tri_suction
        or args.parcel_gripper_extension_m is not None
        or args.parcel_gripper_density_kg_m3 is not None
        or args.grasp_planning_reset_fallback_gate
        or args.grasp_planning_disable_collision_filter
        or args.grasp_planning_disable_manipulability_ranking
        or args.grasp_planning_disable_symmetric_wrist
        or args.grasp_planning_disable_retry_replan
        or args.grasp_planning_blacklist_failed_candidate
        or args.grasp_planning_waypoint_gate
        or args.grasp_planning_stability_steps is not None
        or args.grasp_planning_final_approach_step is not None
        or args.grasp_planning_disable_tiered_approach
        or args.grasp_planning_drop_step is not None
        or args.grasp_planning_transport_contract
        or args.grasp_planning_disable_transport_lookahead
        or args.grasp_planning_raise_step is not None
        or args.grasp_planning_transport_step is not None
        or args.grasp_planning_transfer_settle_steps is not None
        or args.transport_slip_recovery
        or args.transport_slip_setdown_regrasp
    ):
        config = replace(
            config,
            task=replace(
                config.task,
                size_aware_approach_enabled=(
                    config.task.size_aware_approach_enabled or args.size_aware_approach
                ),
                approach_clearance_margin_m=(
                    config.task.approach_clearance_margin_m
                    if args.approach_clearance_margin is None
                    else args.approach_clearance_margin
                ),
                retry_retreat_distance_m=(
                    config.task.retry_retreat_distance_m
                    if args.retry_retreat_distance is None
                    else args.retry_retreat_distance
                ),
                surface_aware_pregrasp_enabled=(
                    config.task.surface_aware_pregrasp_enabled
                    or args.surface_aware_pregrasp
                ),
                geometry_aware_grasp_planning_enabled=(
                    config.task.geometry_aware_grasp_planning_enabled
                    or args.geometry_aware_grasp_planning
                ),
                parcel_gripper_adapter_enabled=(
                    config.task.parcel_gripper_adapter_enabled
                    or args.parcel_gripper_adapter
                ),
                tri_suction_enabled=(
                    config.task.tri_suction_enabled or args.tri_suction
                ),
                parcel_gripper_adapter_extension_m=(
                    config.task.parcel_gripper_adapter_extension_m
                    if args.parcel_gripper_extension_m is None
                    else args.parcel_gripper_extension_m
                ),
                parcel_gripper_adapter_density_kg_m3=(
                    config.task.parcel_gripper_adapter_density_kg_m3
                    if args.parcel_gripper_density_kg_m3 is None
                    else args.parcel_gripper_density_kg_m3
                ),
                grasp_planning_reset_fallback_gate_enabled=(
                    config.task.grasp_planning_reset_fallback_gate_enabled
                    or args.grasp_planning_reset_fallback_gate
                ),
                grasp_planning_collision_filter_enabled=(
                    config.task.grasp_planning_collision_filter_enabled
                    and not args.grasp_planning_disable_collision_filter
                ),
                grasp_planning_manipulability_ranking_enabled=(
                    config.task.grasp_planning_manipulability_ranking_enabled
                    and not args.grasp_planning_disable_manipulability_ranking
                ),
                grasp_planning_symmetric_wrist_enabled=(
                    config.task.grasp_planning_symmetric_wrist_enabled
                    and not args.grasp_planning_disable_symmetric_wrist
                ),
                grasp_planning_retry_replan_enabled=(
                    config.task.grasp_planning_retry_replan_enabled
                    and not args.grasp_planning_disable_retry_replan
                ),
                grasp_planning_failed_candidate_blacklist_enabled=(
                    config.task.grasp_planning_failed_candidate_blacklist_enabled
                    or args.grasp_planning_blacklist_failed_candidate
                ),
                grasp_planning_waypoint_collision_gate_enabled=(
                    config.task.grasp_planning_waypoint_collision_gate_enabled
                    or args.grasp_planning_waypoint_gate
                ),
                grasp_planning_stability_steps=(
                    config.task.grasp_planning_stability_steps
                    if args.grasp_planning_stability_steps is None
                    else args.grasp_planning_stability_steps
                ),
                grasp_planning_final_approach_step_m=(
                    config.task.grasp_planning_final_approach_step_m
                    if args.grasp_planning_final_approach_step is None
                    else args.grasp_planning_final_approach_step
                ),
                grasp_planning_tall_box_final_approach_step_m=(
                    (
                        config.task.grasp_planning_final_approach_step_m
                        if args.grasp_planning_final_approach_step is None
                        else args.grasp_planning_final_approach_step
                    )
                    if args.grasp_planning_disable_tiered_approach
                    else config.task.grasp_planning_tall_box_final_approach_step_m
                ),
                grasp_planning_drop_step_m=(
                    config.task.grasp_planning_drop_step_m
                    if args.grasp_planning_drop_step is None
                    else args.grasp_planning_drop_step
                ),
                grasp_planning_transport_contract_enabled=(
                    config.task.grasp_planning_transport_contract_enabled
                    or args.grasp_planning_transport_contract
                ),
                grasp_planning_transport_lookahead_enabled=(
                    config.task.grasp_planning_transport_lookahead_enabled
                    and not args.grasp_planning_disable_transport_lookahead
                ),
                grasp_planning_raise_step_m=(
                    config.task.grasp_planning_raise_step_m
                    if args.grasp_planning_raise_step is None
                    else args.grasp_planning_raise_step
                ),
                grasp_planning_transport_step_m=(
                    config.task.grasp_planning_transport_step_m
                    if args.grasp_planning_transport_step is None
                    else args.grasp_planning_transport_step
                ),
                grasp_planning_transfer_settle_steps=(
                    config.task.grasp_planning_transfer_settle_steps
                    if args.grasp_planning_transfer_settle_steps is None
                    else args.grasp_planning_transfer_settle_steps
                ),
            ),
            control=replace(
                config.control,
                approach_contact_brake_force_n=(
                    config.control.approach_contact_brake_force_n
                    if args.approach_contact_brake_force is None
                    else args.approach_contact_brake_force
                ),
                approach_contact_brake_step_m=(
                    config.control.approach_contact_brake_step_m
                    if args.approach_contact_brake_step is None
                    else args.approach_contact_brake_step
                ),
                approach_barrier_recovery_step_m=(
                    config.control.approach_barrier_recovery_step_m
                    if args.approach_barrier_recovery_step is None
                    else args.approach_barrier_recovery_step
                ),
                precontact_aabb_guard_distance_m=(
                    config.control.precontact_aabb_guard_distance_m
                    if args.precontact_aabb_guard_distance is None
                    else args.precontact_aabb_guard_distance
                ),
                approach_stiffness_scale=(
                    config.control.approach_stiffness_scale
                    if args.approach_stiffness_scale is None
                    else args.approach_stiffness_scale
                ),
                approach_velocity_control_enabled=(
                    config.control.approach_velocity_control_enabled
                    or args.approach_velocity_control
                ),
                collision_checked_reset_enabled=(
                    config.control.collision_checked_reset_enabled
                    or args.collision_checked_reset
                ),
                transport_slip_recovery_enabled=(
                    config.control.transport_slip_recovery_enabled
                    or args.transport_slip_recovery
                ),
                transport_slip_setdown_regrasp_enabled=(
                    config.control.transport_slip_setdown_regrasp_enabled
                    or args.transport_slip_setdown_regrasp
                ),
            ),
        )
    if args.approach_step is not None:
        config = replace(
            config,
            control=replace(config.control, approach_step_m=args.approach_step),
        )
    if (
        args.grasp_planning_disable_collision_filter
        or args.grasp_planning_reset_fallback_gate
        or args.grasp_planning_disable_manipulability_ranking
        or args.grasp_planning_disable_symmetric_wrist
        or args.grasp_planning_disable_retry_replan
        or args.grasp_planning_blacklist_failed_candidate
        or args.grasp_planning_waypoint_gate
        or args.grasp_planning_stability_steps is not None
        or args.grasp_planning_final_approach_step is not None
        or args.grasp_planning_disable_tiered_approach
        or args.grasp_planning_drop_step is not None
        or args.grasp_planning_transport_contract
        or args.grasp_planning_disable_transport_lookahead
        or args.grasp_planning_raise_step is not None
        or args.grasp_planning_transport_step is not None
        or args.grasp_planning_transfer_settle_steps is not None
        or args.transport_slip_recovery
        or args.transport_slip_setdown_regrasp
    ) and not config.task.geometry_aware_grasp_planning_enabled:
        parser.error("grasp-planning options require --geometry-aware-grasp-planning")
    try:
        config.validate()
    except ValueError as exc:
        parser.error(str(exc))
    try:
        if args.collection_plan:
            requests = load_collection_requests(
                args.collection_plan,
                allow_unready=args.allow_unready_collection,
                expected_training_profile_ids=tuple(
                    profile.profile_id
                    for profile in config.parcel_profiles
                    if not profile.evaluation_only
                ),
                expected_config_path=args.config,
            )
            plan = build_profile_episode_plan(
                config.parcel_profiles,
                requests,
                allow_evaluation_only=False,
            )
        else:
            plan = build_episode_plan(
                config.parcel_profiles,
                args.episodes,
                args.start_episode,
                tuple(args.selected_profiles or ()),
                allow_evaluation_only=False,
            )
    except ValueError as exc:
        parser.error(str(exc))

    output = Path(args.output or config.output.root_dir) / "expert"
    output.mkdir(parents=True, exist_ok=True)
    jsonl_writer = JsonlTrajectoryWriter(output / "audit_dataset")
    lerobot_writer = None
    if args.lerobot:
        lerobot_writer = LeRobotTrajectoryWriter(
            root=output / "lerobot_dataset",
            fps=config.simulation.control_hz,
            image_size=(config.sensors.image_width, config.sensors.image_height),
            include_rgb=config.sensors.rgb,
            include_depth=config.sensors.depth,
        )

    metrics = MetricsAccumulator()
    randomizer = DomainRandomizer(config.randomization, config.seed, config.parcel_profiles)
    reports = []
    profile_metrics: dict[str, MetricsAccumulator] = {}
    try:
        for offset, spec in enumerate(plan):
            episode_index = spec.episode_index
            sample = (
                randomizer.sample(episode_index)
                if spec.profile_id is None
                else randomizer.sample_profile(spec.profile_id, episode_index)
            )
            jsonl_writer.assert_episode_available(episode_index)
            should_record_video = args.record_video or (
                config.output.record_first_episode and offset == 0
            )
            capture_sensors = args.record_sensors or config.output.save_sensor_frames
            video_path = (
                output / "videos" / f"episode_{episode_index:06d}.mp4"
                if should_record_video
                else None
            )
            with GenesisParcelEnv(
                config,
                sample,
                backend=args.backend,
                show_viewer=args.viewer,
                video_path=video_path,
                capture_sensors=capture_sensors,
            ) as env:
                writers = tuple(writer for writer in (jsonl_writer, lerobot_writer) if writer is not None)
                report = run_expert_episode(env, config, sample, episode_index, writers)
            save_episode_writers(report, jsonl_writer, lerobot_writer)
            reports.append(report.to_dict())
            metrics.add(report.result)
            profile_metrics.setdefault(sample.profile_id, MetricsAccumulator()).add(report.result)
            print(
                json.dumps(
                    {
                        "episode": episode_index,
                        "profile": sample.profile_id,
                        "success": report.result.success,
                        "stage": report.terminal_stage,
                        "retries": report.result.retries,
                    },
                    ensure_ascii=False,
                )
            )
    finally:
        if lerobot_writer is not None:
            lerobot_writer.finalize()

    result = {
        "runtime": runtime_report(),
        "evaluation_range": {
            "start_episode": min(spec.episode_index for spec in plan),
            "end_episode": max(spec.episode_index for spec in plan),
            "num_episodes": len(plan),
            "profile_filter": list(args.selected_profiles or ()),
            "episodes_per_profile": args.episodes if args.selected_profiles else None,
            "collection_plan": args.collection_plan,
            "profile_episode_counts": {
                profile_id: sum(spec.profile_id == profile_id for spec in plan)
                for profile_id in sorted({spec.profile_id for spec in plan if spec.profile_id})
            },
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
        json.dump(result, handle, ensure_ascii=False, indent=2)
    print(json.dumps(result["summary"], ensure_ascii=False, indent=2))
    all_successful = all(report["result"]["success"] for report in reports)
    return 2 if args.fail_on_unsuccessful and not all_successful else 0


if __name__ == "__main__":
    raise SystemExit(main())
