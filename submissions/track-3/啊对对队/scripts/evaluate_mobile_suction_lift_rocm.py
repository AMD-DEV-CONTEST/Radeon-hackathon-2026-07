"""Verify physical tri-cup contact, compliant attachment, and parcel lift."""

from __future__ import annotations

import argparse
from collections import deque
import json
import math
from pathlib import Path
import statistics

from parcel_sorter.genesis_env import initialize_genesis
from parcel_sorter.mobile_dataset import MobileBimanualFrame, MobileBimanualLeRobotWriter
from parcel_sorter.mobile_pi05_dataset import (
    MobilePI05AbsoluteLeRobotWriter,
    MobilePI05AutonomousLeRobotWriter,
    PI05AbsoluteRolloutQualification,
    PI05AutonomousAbsoluteFrame,
    PI05AutonomousResidualFrame,
    PI05AutonomousRolloutQualification,
)
from parcel_sorter.mobile_pi05_heldout_capture import (
    write_pi05_heldout_observation,
)
from parcel_sorter.mobile_dual_arm_projection import (
    project_dual_arm_residuals,
    transport_arm_authority,
)
from parcel_sorter.mobile_harness import (
    MobileHarnessConfig,
    transport_deadline_requires_expert,
)
from parcel_sorter.mobile_cradle import (
    MobileVCradleMonitor,
    update_cradle_contact_memory_offset,
)
from parcel_sorter.mobile_bimanual import (
    ARM_JOINT_NAMES,
    BASE_JOINT_NAMES,
    END_EFFECTOR_LINK_NAMES,
    FINGER_JOINT_NAMES,
    MOBILE_TRI_SUCTION_TIP_OFFSET_M,
    build_mobile_bimanual_mjcf,
    joint_dof_indices,
)
from parcel_sorter.mobile_suction import MobileTriSuctionController
from parcel_sorter.mobile_pi05_contract import (
    PI05ResidualContext,
    encode_pi05_absolute_state,
    encode_pi05_state,
    select_pi05_mode_consensus,
)
from parcel_sorter.mobile_grasp_routing import (
    radial_side_grasp_quaternion,
    top_down_grasp_quaternion,
    top_suction_active_cup_indices,
)
from parcel_sorter.mobile_task import (
    clamp_position_residual_to_anchor,
    placement_within_release_gate,
    update_release_gate_stability,
)
from parcel_sorter.mobile_vla_controller import MobileVLAHarnessController
from parcel_sorter.mobile_vla_service import MobileVLAServiceClient
from parcel_sorter.mobile_policy_attribution import (
    summarize_mobile_policy_attribution,
)
from parcel_sorter.provenance import runtime_report
from parcel_sorter.suction import rotate_vector, tri_cup_offsets


PROFILE_COLORS = {
    "small_carton": (0.10, 0.62, 0.92),
    "flat_mailer": (0.95, 0.48, 0.10),
    "electronics_box": (0.16, 0.72, 0.34),
    "medium_carton": (0.78, 0.28, 0.72),
}
PROFILE_COLOR_NAMES = {
    "small_carton": "blue",
    "flat_mailer": "orange",
    "electronics_box": "green",
    "medium_carton": "purple",
}
PI05_POLICY_MODES = frozenset({"pi05_residual", "pi05_absolute"})
GRASP_MODE_ROUTE_MISMATCH_FAILURE = "grasp_mode_route_mismatch_before_actuation"


def grasp_mode_route_failure_stage(
    *, required: bool, matched: bool | None
) -> str | None:
    """Classify a required VLA mode-route mismatch before task actuation."""

    if required and matched is False:
        return GRASP_MODE_ROUTE_MISMATCH_FAILURE
    return None


def _flat(values: object) -> list[float]:
    if hasattr(values, "detach"):
        values = values.detach().cpu()  # type: ignore[union-attr]
    if hasattr(values, "reshape"):
        values = values.reshape(-1)  # type: ignore[union-attr]
    return [float(value) for value in values]  # type: ignore[union-attr]


def _normalized(values: object, np: object) -> object:
    vector = np.asarray(values, dtype=np.float64)
    norm = float(np.linalg.norm(vector))
    if norm <= 1e-8:
        raise RuntimeError("tool axis has zero length")
    return vector / norm


def _box_ray_extent(axis: object, box_size: object) -> float:
    """Distance from an axis-aligned box centre to the face hit by a ray."""

    intersections = [
        float(size) / (2.0 * abs(float(component)))
        for component, size in zip(axis, box_size, strict=True)  # type: ignore[arg-type]
        if abs(float(component)) > 1e-9
    ]
    if not intersections:
        raise ValueError("box approach axis has no finite component")
    return min(intersections)


def _shape_ray_extent(
    axis: object,
    parcel_size: object,
    shape: str,
    orientation_mode: str,
    yaw_rad: float,
    np: object,
) -> float:
    """Return the centre-to-surface distance along a world-space ray."""

    direction = _normalized(axis, np)
    size = np.asarray(parcel_size, dtype=np.float64)
    if shape == "box":
        cosine, sine = math.cos(yaw_rad), math.sin(yaw_rad)
        local_axis = np.asarray(
            (
                cosine * direction[0] + sine * direction[1],
                -sine * direction[0] + cosine * direction[1],
                direction[2],
            )
        )
        return _box_ray_extent(local_axis, size)

    if orientation_mode == "upright":
        cylinder_axis = np.asarray((0.0, 0.0, 1.0))
        radius = float(size[0]) / 2.0
        half_height = float(size[2]) / 2.0
    elif orientation_mode == "horizontal":
        cylinder_axis = np.asarray((math.cos(yaw_rad), math.sin(yaw_rad), 0.0))
        radius = float(size[1]) / 2.0
        half_height = float(size[0]) / 2.0
    else:
        raise ValueError(f"unsupported cylinder orientation: {orientation_mode}")
    axial = abs(float(np.dot(direction, cylinder_axis)))
    radial = math.sqrt(max(0.0, 1.0 - axial * axial))
    intersections = []
    if radial > 1e-9:
        intersections.append(radius / radial)
    if axial > 1e-9:
        intersections.append(half_height / axial)
    if not intersections:
        raise ValueError("cylinder approach axis has no finite component")
    return min(intersections)


def _render_left_wrist_rgbd(camera: object, hand: object, np: object) -> tuple[object, object]:
    hand_position = np.asarray(_flat(hand.get_pos()), dtype=np.float64)
    hand_quaternion = tuple(_flat(hand.get_quat()))
    forward = _normalized(
        rotate_vector(hand_quaternion, (0.0, 0.0, 1.0)), np
    )
    up = _normalized(rotate_vector(hand_quaternion, (0.0, 1.0, 0.0)), np)
    camera_position = hand_position - forward * 0.045 + up * 0.020
    lookat = hand_position + forward * 0.180
    camera.set_pose(
        pos=tuple(camera_position.tolist()),
        lookat=tuple(lookat.tolist()),
        up=tuple(up.tolist()),
    )
    rgb, depth, _, _ = camera.render(rgb=True, depth=True)
    return rgb, depth


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--backend", choices=("rocm", "cuda"), default="rocm")
    parser.add_argument("--output", type=Path, default=Path("outputs/mobile-suction-lift"))
    parser.add_argument(
        "--record-dataset",
        type=Path,
        help="record the successful full task as a 30 Hz RGB-D LeRobot episode",
    )
    parser.add_argument(
        "--record-pi05-residual-dataset",
        type=Path,
        help=(
            "buffer the raw 80-D/14-D PI0.5 rollout and commit it only after "
            "verified success with zero fallback and force violations"
        ),
    )
    parser.add_argument(
        "--record-pi05-absolute-dataset",
        type=Path,
        help=(
            "buffer 80-D/23-D executed absolute-VLA targets and commit only a "
            "verified full-authority success"
        ),
    )
    parser.add_argument(
        "--record-video",
        type=Path,
        help="save the overhead camera view as an MP4 without opening a viewer",
    )
    parser.add_argument(
        "--snapshot",
        type=Path,
        help="save the final overhead RGB frame as a PNG",
    )
    parser.add_argument(
        "--record-contact-video",
        type=Path,
        help="save a fixed close-up of suction contact as an MP4",
    )
    parser.add_argument(
        "--contact-snapshot",
        type=Path,
        help="save the first frame after a physical suction latch as a PNG",
    )
    parser.add_argument("--image-size", type=int, default=224)
    parser.add_argument("--record-initial-observation", type=Path)
    parser.add_argument("--initial-observation-only", action="store_true")
    parser.add_argument("--observation-episode-id")
    parser.add_argument("--pedestal-x-m", type=float)
    parser.add_argument(
        "--wrist-rgbd",
        action="store_true",
        help="capture and provide a left-wrist RGB-D view in addition to overhead RGB-D",
    )
    parser.add_argument("--media-width", type=int, default=640)
    parser.add_argument("--media-height", type=int, default=480)
    parser.add_argument("--parcel-profile", default="carton")
    parser.add_argument("--parcel-shape", choices=("box", "cylinder"), default="box")
    parser.add_argument(
        "--parcel-orientation",
        choices=("yaw", "upright", "horizontal"),
        default="yaw",
    )
    parser.add_argument("--parcel-yaw-rad", type=float, default=0.0)
    parser.add_argument(
        "--grasp-mode",
        choices=("top_suction", "side_suction", "cooperative_cradle"),
        default="side_suction",
    )
    parser.add_argument("--minimum-sealed-cups", type=int, default=2)
    parser.add_argument(
        "--parcel-size-m", type=float, nargs=3, default=(0.20, 0.12, 0.20)
    )
    parser.add_argument("--parcel-mass-kg", type=float, default=0.40)
    parser.add_argument("--parcel-friction", type=float, default=0.80)
    parser.add_argument("--parcel-offset-m", type=float, nargs=2, default=(0.0, 0.0))
    parser.add_argument(
        "--recovery-contact-offset-m", type=float, nargs=2, default=(0.0, 0.0)
    )
    parser.add_argument(
        "--recovery-contact-penetration-delta-m", type=float, default=0.0
    )
    parser.add_argument(
        "--recovery-cradle-engagement-delta-m", type=float, default=0.0
    )
    parser.add_argument(
        "--recovery-left-lift-offset-m", type=float, nargs=3, default=(0.0, 0.0, 0.0)
    )
    parser.add_argument(
        "--recovery-right-lift-offset-m", type=float, nargs=3, default=(0.0, 0.0, 0.0)
    )
    parser.add_argument("--cradle-contact-memory", action="store_true")
    parser.add_argument("--recovery-approach-speed-scale", type=float, default=1.0)
    parser.add_argument("--recovery-vertical-speed-scale", type=float, default=1.0)
    parser.add_argument("--recovery-lift-height-delta-m", type=float, default=0.0)
    parser.add_argument("--recovery-placement-clearance-m", type=float, default=0.015)
    parser.add_argument("--retry-index", type=int, default=0)
    parser.add_argument(
        "--cooperative-cradle",
        action="store_true",
        help="synchronize the right V cradle for wide-parcel lift, transport, and place",
    )
    parser.add_argument("--task-text")
    parser.add_argument(
        "--vla-checkpoint",
        "--smolvla-checkpoint",
        dest="vla_checkpoint",
        type=Path,
        help="fine-tuned SmolVLA or PI0.5 checkpoint (old SmolVLA flag remains an alias)",
    )
    parser.add_argument(
        "--vla-policy-service-ready",
        type=Path,
        help="reuse a locally persistent PI0.5 process described by this ready file",
    )
    parser.add_argument(
        "--force-memory-harness",
        action="store_true",
        help="cap VLA residual scale using short contact-force history",
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
    parser.add_argument(
        "--depth-risk-sidecar",
        action="store_true",
        help="use metric depth as a deterministic Harness scale gate for the RGB policy",
    )
    parser.add_argument("--policy-hz", type=int, default=5)
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
        help=(
            "optional JSON object overriding the PI0.5 execution horizon per stage; "
            "for example {\"pregrasp\":1,\"grasp_approach\":2,\"transport\":10}"
        ),
    )
    parser.add_argument(
        "--require-vla-goal-verdict",
        action="store_true",
        help="require the primitive-progress VLA to confirm arrival inside the goal tolerance",
    )
    parser.add_argument(
        "--require-vla-grasp-mode",
        action="store_true",
        help=(
            "route execution with the first unconditioned PI0.5 mode prediction and "
            "require it to match the hidden evaluation label"
        ),
    )
    parser.add_argument(
        "--vla-routes-grasp-mode",
        action="store_true",
        help=(
            "let PI0.5 choose the executed grasp mode before mode-specific IK planning; "
            "--grasp-mode remains only the hidden evaluation label"
        ),
    )
    parser.add_argument(
        "--vla-mode-votes",
        type=int,
        default=3,
        help="odd number of stochastic PI0.5 samples used for grasp-mode consensus",
    )
    args = parser.parse_args()
    expected_grasp_mode = args.grasp_mode
    vla_routes_grasp_mode = bool(
        args.vla_routes_grasp_mode or args.require_vla_grasp_mode
    )
    if args.grasp_mode == "cooperative_cradle":
        args.cooperative_cradle = True
    elif args.cooperative_cradle:
        parser.error("--cooperative-cradle requires --grasp-mode cooperative_cradle")
    if args.image_size < 32:
        parser.error("image-size must be at least 32")
    dataset_recording_targets = sum(
        path is not None
        for path in (
            args.record_dataset,
            args.record_pi05_residual_dataset,
            args.record_pi05_absolute_dataset,
        )
    )
    if dataset_recording_targets > 1:
        parser.error("record only one dataset contract per rollout")
    if args.initial_observation_only and args.record_initial_observation is None:
        parser.error("initial-observation-only requires --record-initial-observation")
    if args.record_initial_observation is not None and not args.observation_episode_id:
        parser.error("initial observation capture requires --observation-episode-id")
    if args.record_initial_observation is not None and (
        args.record_dataset is not None or args.record_pi05_residual_dataset is not None
        or args.record_pi05_absolute_dataset is not None
    ):
        parser.error("initial held-out observations cannot be recorded as training data")
    if args.wrist_rgbd and not (
        args.record_dataset is not None
        or args.record_pi05_residual_dataset is not None
        or args.record_pi05_absolute_dataset is not None
        or args.vla_checkpoint is not None
    ):
        parser.error("wrist RGB-D requires dataset recording or a VLA checkpoint")
    if args.vla_policy_service_ready is not None and args.vla_checkpoint is None:
        parser.error("persistent policy service requires --vla-checkpoint for identity")
    if (
        args.vla_policy_service_ready is not None
        and not args.vla_policy_service_ready.is_file()
    ):
        parser.error("persistent policy service ready file is missing")
    max_parcel_dimension_m = 1.70 if args.cooperative_cradle else 0.60
    if any(not 0.01 <= value <= max_parcel_dimension_m for value in args.parcel_size_m):
        parser.error(
            f"parcel dimensions must be in [0.01, {max_parcel_dimension_m:.2f}] m"
        )
    max_parcel_mass_kg = 8.0 if args.cooperative_cradle else 5.0
    if not 0.05 <= args.parcel_mass_kg <= max_parcel_mass_kg:
        parser.error(f"parcel mass must be in [0.05, {max_parcel_mass_kg:.1f}] kg")
    if not 0.1 <= args.parcel_friction <= 2.0:
        parser.error("parcel friction must be in [0.1, 2.0]")
    if args.pedestal_x_m is not None and not -0.80 <= args.pedestal_x_m <= 0.10:
        parser.error("pedestal-x-m must be in [-0.80, 0.10]")
    if any(abs(value) > 0.025 for value in args.parcel_offset_m):
        parser.error("parcel XY offsets must be within 0.025 m")
    if any(abs(value) > 0.008 for value in args.recovery_contact_offset_m):
        parser.error("recovery contact offsets must remain within 0.008 m")
    if not -0.0015 <= args.recovery_contact_penetration_delta_m <= 0.0015:
        parser.error("recovery contact penetration delta must be within 0.0015 m")
    if not -0.010 <= args.recovery_cradle_engagement_delta_m <= 0.010:
        parser.error("recovery cradle engagement delta must be in [-0.010, 0.010] m")
    if args.recovery_cradle_engagement_delta_m and not args.cooperative_cradle:
        parser.error("cradle engagement recovery requires cooperative cradle mode")
    if math.sqrt(sum(value * value for value in args.recovery_left_lift_offset_m)) > 0.005:
        parser.error("left lift recovery offset norm must not exceed 0.005 m")
    if any(args.recovery_left_lift_offset_m) and not args.cooperative_cradle:
        parser.error("left lift recovery offset requires cooperative cradle mode")
    if math.sqrt(sum(value * value for value in args.recovery_right_lift_offset_m)) > 0.008:
        parser.error("right lift recovery offset norm must not exceed 0.008 m")
    if any(args.recovery_right_lift_offset_m) and not args.cooperative_cradle:
        parser.error("right lift recovery offset requires cooperative cradle mode")
    if not 0.40 <= args.recovery_approach_speed_scale <= 1.0:
        parser.error("recovery approach speed scale must be in [0.40, 1.0]")
    if not 0.60 <= args.recovery_vertical_speed_scale <= 1.0:
        parser.error("recovery vertical speed scale must be in [0.60, 1.0]")
    if not 0.0 <= args.recovery_lift_height_delta_m <= 0.020:
        parser.error("recovery lift height delta must be in [0, 0.020] m")
    if not 0.008 <= args.recovery_placement_clearance_m <= 0.020:
        parser.error("recovery placement clearance must be in [0.008, 0.020] m")
    if args.retry_index < 0 or args.retry_index > 2:
        parser.error("retry-index must be in [0, 2]")
    if args.policy_hz <= 0 or 30 % args.policy_hz != 0:
        parser.error("policy-hz must be a positive divisor of 30")
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
        and args.policy_mode != "pi05_residual"
    ):
        parser.error("multi-step chunk execution requires PI0.5 residual mode")
    if args.vla_mode_votes < 1 or args.vla_mode_votes > 9 or args.vla_mode_votes % 2 == 0:
        parser.error("vla-mode-votes must be an odd integer in [1, 9]")
    if args.policy_mode != "shadow" and args.vla_checkpoint is None:
        parser.error("learned policy modes require --vla-checkpoint")
    if args.require_vla_goal_verdict and args.vla_checkpoint is None:
        parser.error("VLA goal verdict requires --vla-checkpoint")
    if vla_routes_grasp_mode and (
        args.vla_checkpoint is None
        or args.policy_mode not in {*PI05_POLICY_MODES, "shadow"}
    ):
        parser.error("VLA grasp-mode selection requires PI0.5 or shadow mode")
    if args.record_pi05_residual_dataset is not None:
        if args.vla_checkpoint is None or args.policy_mode != "pi05_residual":
            parser.error("PI0.5 residual recording requires a PI0.5 residual policy")
        if not vla_routes_grasp_mode:
            parser.error("PI0.5 residual recording requires VLA grasp-mode routing")
        if not args.require_vla_goal_verdict:
            parser.error("PI0.5 residual recording requires the VLA goal verdict")
    if args.record_pi05_absolute_dataset is not None:
        if args.vla_checkpoint is None or args.policy_mode != "pi05_absolute":
            parser.error("PI0.5 absolute recording requires pi05_absolute mode")
        if not vla_routes_grasp_mode:
            parser.error("PI0.5 absolute recording requires VLA grasp-mode routing")
        if not args.require_vla_goal_verdict:
            parser.error("PI0.5 absolute recording requires the VLA goal verdict")
    if not 1 <= args.minimum_sealed_cups <= 3:
        parser.error("minimum-sealed-cups must be in [1, 3]")
    if args.cooperative_cradle and args.policy_mode == "base_arm_residual":
        parser.error("cooperative cradle is not compatible with left-arm residual ablation")
    if args.parcel_shape == "box" and args.parcel_orientation != "yaw":
        parser.error("box parcels require --parcel-orientation yaw")
    if args.parcel_shape == "cylinder":
        if args.parcel_orientation == "yaw":
            parser.error("cylinder parcels require upright or horizontal orientation")
        diameter_indices = (0, 1) if args.parcel_orientation == "upright" else (1, 2)
        if not math.isclose(
            args.parcel_size_m[diameter_indices[0]],
            args.parcel_size_m[diameter_indices[1]],
            rel_tol=0.0,
            abs_tol=1e-6,
        ):
            parser.error("cylinder diameter dimensions must be equal")

    gs, torch, np = initialize_genesis(args.backend)
    source = Path(gs.__file__).resolve().parent / "assets/xml/franka_sim/bi-franka_panda.xml"
    asset = build_mobile_bimanual_mjcf(
        source,
        args.output / "mobile_bi_franka.xml",
        left_tri_suction=True,
        right_v_cradle=True,
    )
    scene = gs.Scene(
        sim_options=gs.options.SimOptions(dt=1.0 / 240.0, substeps=1),
        rigid_options=gs.options.RigidOptions(enable_collision=True),
        show_viewer=False,
    )
    scene.add_entity(gs.morphs.Plane())
    default_pedestal_x = 0.0 if args.cooperative_cradle else -0.6800
    pedestal_position = np.asarray(
        (
            default_pedestal_x
            if args.pedestal_x_m is None
            else float(args.pedestal_x_m),
            0.7500,
            1.3000,
        )
    )
    transport_delta = np.asarray((0.3000, 0.0, 0.0))
    destination_pedestal_position = pedestal_position + transport_delta
    profile_color = PROFILE_COLORS.get(args.parcel_profile, (0.10, 0.62, 0.92))
    neutral_surface = gs.surfaces.Rough(
        diffuse_texture=gs.textures.ColorTexture(color=(0.38, 0.42, 0.46))
    )
    target_surface = gs.surfaces.Rough(
        diffuse_texture=gs.textures.ColorTexture(color=profile_color)
    )
    parcel_size = np.asarray(args.parcel_size_m, dtype=np.float64)
    parcel_half_height = (
        float(parcel_size[1]) / 2.0
        if args.parcel_shape == "cylinder"
        and args.parcel_orientation == "horizontal"
        else float(parcel_size[2]) / 2.0
    )
    parcel_support_z = pedestal_position[2] + 0.05 + parcel_half_height
    initial_parcel_position = np.asarray(
        (
            pedestal_position[0] + args.parcel_offset_m[0],
            pedestal_position[1] + args.parcel_offset_m[1],
            parcel_support_z + 0.002,
        )
    )
    pedestal_size_x = (
        max(0.16, float(parcel_size[0]) + 0.04)
        if args.cooperative_cradle
        else 0.16
    )
    scene.add_entity(
        gs.morphs.Box(
            size=(pedestal_size_x, 0.08, 0.10),
            pos=tuple(pedestal_position.tolist()),
            fixed=True,
        ),
        surface=neutral_surface,
    )
    scene.add_entity(
        gs.morphs.Box(
            size=(pedestal_size_x, 0.08, 0.10),
            pos=tuple(destination_pedestal_position.tolist()),
            fixed=True,
        ),
        surface=target_surface,
    )
    scene.add_entity(
        gs.morphs.Box(
            size=(max(0.24, pedestal_size_x + 0.08), 0.015, 0.22),
            pos=(
                float(destination_pedestal_position[0]),
                float(destination_pedestal_position[1] + 0.18),
                float(destination_pedestal_position[2] + 0.12),
            ),
            fixed=True,
        ),
        surface=target_surface,
    )
    parcel_euler = (0.0, 0.0, math.degrees(args.parcel_yaw_rad))
    if args.parcel_shape == "box":
        parcel_morph = gs.morphs.Box(
            size=tuple(parcel_size.tolist()),
            pos=tuple(initial_parcel_position.tolist()),
            euler=parcel_euler,
        )
    elif args.parcel_orientation == "upright":
        parcel_morph = gs.morphs.Cylinder(
            radius=float(parcel_size[0]) / 2.0,
            height=float(parcel_size[2]),
            pos=tuple(initial_parcel_position.tolist()),
            euler=parcel_euler,
        )
    else:
        parcel_morph = gs.morphs.Cylinder(
            radius=float(parcel_size[1]) / 2.0,
            height=float(parcel_size[0]),
            pos=tuple(initial_parcel_position.tolist()),
            euler=(0.0, 90.0, math.degrees(args.parcel_yaw_rad)),
        )
    parcel = scene.add_entity(
        parcel_morph,
        material=gs.materials.Rigid(friction=args.parcel_friction),
        surface=target_surface,
    )
    robot = scene.add_entity(gs.morphs.MJCF(file=str(asset)))
    camera = None
    if (
        args.record_dataset is not None
        or args.record_pi05_residual_dataset is not None
        or args.record_pi05_absolute_dataset is not None
        or args.record_initial_observation is not None
        or args.vla_checkpoint is not None
    ):
        camera = scene.add_camera(
            res=(args.image_size, args.image_size),
            pos=(0.0, -2.4, 3.1),
            lookat=(-0.45, 0.65, 1.25),
            fov=52,
            GUI=False,
        )
    media_camera = None
    if args.record_video is not None or args.snapshot is not None:
        media_camera = scene.add_camera(
            res=(args.media_width, args.media_height),
            pos=(-1.65, -1.65, 2.55),
            lookat=(-0.48, 0.75, 1.28),
            fov=52,
            GUI=False,
        )
    contact_camera = None
    if args.record_contact_video is not None or args.contact_snapshot is not None:
        contact_camera = scene.add_camera(
            res=(args.media_width, args.media_height),
            pos=(-1.42, 0.18, 1.76),
            lookat=(-0.67, 0.66, 1.46),
            fov=38,
            GUI=False,
        )
    wrist_camera = None
    if args.wrist_rgbd:
        wrist_camera = scene.add_camera(
            res=(args.image_size, args.image_size),
            pos=(-0.70, 0.55, 1.55),
            lookat=(-0.70, 0.75, 1.35),
            fov=68,
            GUI=False,
        )
    scene.build()
    if args.record_video is not None:
        if media_camera is None:
            raise RuntimeError("video recording requires a camera")
        args.record_video.parent.mkdir(parents=True, exist_ok=True)
        media_camera.start_recording()
    if args.record_contact_video is not None:
        if contact_camera is None:
            raise RuntimeError("contact video recording requires a camera")
        args.record_contact_video.parent.mkdir(parents=True, exist_ok=True)
        contact_camera.start_recording()
    parcel.set_mass(args.parcel_mass_kg)

    base_dofs = np.asarray(joint_dof_indices(robot, BASE_JOINT_NAMES))
    left_arm_dofs = np.asarray(joint_dof_indices(robot, ARM_JOINT_NAMES["left"]))
    right_arm_dofs = np.asarray(joint_dof_indices(robot, ARM_JOINT_NAMES["right"]))
    arm_dofs = np.asarray((*left_arm_dofs.tolist(), *right_arm_dofs.tolist()))
    left_finger_dofs = np.asarray(joint_dof_indices(robot, FINGER_JOINT_NAMES["left"]))
    right_finger_dofs = np.asarray(joint_dof_indices(robot, FINGER_JOINT_NAMES["right"]))
    finger_dofs = np.asarray((*left_finger_dofs.tolist(), *right_finger_dofs.tolist()))
    hand = robot.get_link(END_EFFECTOR_LINK_NAMES["left"])
    robot.set_dofs_kp(np.zeros(3), base_dofs)
    robot.set_dofs_kv(np.asarray((600.0, 600.0, 300.0)), base_dofs)
    robot.set_dofs_force_range(
        np.asarray((-2500.0, -2500.0, -1200.0)),
        np.asarray((2500.0, 2500.0, 1200.0)),
        base_dofs,
    )
    arm_kp_values = np.asarray(
        (4500.0, 4500.0, 3500.0, 3500.0, 2000.0, 2000.0, 2000.0) * 2
    )
    arm_kv_values = np.asarray(
        (450.0, 450.0, 350.0, 350.0, 200.0, 200.0, 200.0) * 2
    )
    robot.set_dofs_kp(arm_kp_values, arm_dofs)
    robot.set_dofs_kv(arm_kv_values, arm_dofs)
    robot.set_dofs_force_range(-np.ones(14) * 90.0, np.ones(14) * 90.0, arm_dofs)
    robot.set_dofs_kp(np.ones(4) * 100.0, finger_dofs)
    robot.set_dofs_kv(np.ones(4) * 10.0, finger_dofs)
    neutral = np.asarray((0.0, -0.35, 0.0, -2.10, 0.0, 1.75, 0.785))
    qpos = np.asarray(_flat(robot.get_qpos()))
    qpos[arm_dofs] = np.tile(neutral, 2)
    qpos[finger_dofs] = 0.04
    robot.set_qpos(qpos)
    robot.control_dofs_position(np.tile(neutral, 2), arm_dofs)
    robot.control_dofs_position(np.ones(4) * 0.04, finger_dofs)
    for _ in range(120):
        scene.step()

    hand_position = np.asarray(_flat(hand.get_pos()))
    hand_quaternion = tuple(_flat(hand.get_quat()))
    tool_axis = _normalized(rotate_vector(hand_quaternion, (0.0, 0.0, 1.0)), np)
    parcel_half_extent_on_axis = _shape_ray_extent(
        tool_axis,
        parcel_size,
        args.parcel_shape,
        args.parcel_orientation,
        args.parcel_yaw_rad,
        np,
    )
    cup_tip_offset_m = MOBILE_TRI_SUCTION_TIP_OFFSET_M
    cradle_tip_offset_m = 0.270
    cooperative_contact_penetration_m = (
        0.006 + args.recovery_contact_penetration_delta_m
    )
    planned_parcel_position = hand_position + tool_axis * (
        cup_tip_offset_m + parcel_half_extent_on_axis
    )
    parcel_spawn = initial_parcel_position
    settle_trace = []
    settled_parcel_position = parcel_spawn.copy()
    settled_velocity = np.zeros(6)
    for window in range(12):
        for _ in range(120):
            scene.step()
        settled_parcel_position = np.asarray(_flat(parcel.get_pos()))
        settled_velocity = np.asarray(_flat(parcel.get_dofs_velocity()))
        linear_speed = float(np.linalg.norm(settled_velocity[:3]))
        supported = bool(settled_parcel_position[2] >= parcel_support_z - 0.025)
        settle_trace.append(
            {
                "window": window + 1,
                "position_m": settled_parcel_position.tolist(),
                "linear_speed_m_s": linear_speed,
                "supported": supported,
            }
        )
        if supported and linear_speed <= 0.01:
            break
    settle_position_error_m = float(np.linalg.norm(settled_parcel_position - parcel_spawn))
    settle_linear_speed_m_s = float(np.linalg.norm(settled_velocity[:3]))
    scene_stable = bool(
        math.isfinite(settle_position_error_m)
        and math.isfinite(settle_linear_speed_m_s)
        and settled_parcel_position[2] >= parcel_support_z - 0.025
        and settle_linear_speed_m_s <= 0.01
    )

    left_hand = hand
    right_hand = robot.get_link(END_EFFECTOR_LINK_NAMES["right"])
    pregrasp_start_positions = (
        np.asarray(_flat(left_hand.get_pos())),
        np.asarray(_flat(right_hand.get_pos())),
    )
    pregrasp_quaternions = (
        np.asarray(_flat(left_hand.get_quat())),
        np.asarray(_flat(right_hand.get_quat())),
    )
    task_text = args.task_text or (
        f"Classify the {args.parcel_profile} parcel, pick it with tri-suction, "
        f"transport it to the {PROFILE_COLOR_NAMES.get(args.parcel_profile, 'blue')} "
        "sorting station marked with the same color, and place it safely."
    )
    if args.record_initial_observation is not None:
        if camera is None:
            raise RuntimeError("initial observation capture requires an RGB-D camera")
        capture_qpos = np.asarray(_flat(robot.get_qpos()))
        capture_base_velocity = _flat(robot.get_dofs_velocity(base_dofs))
        capture_left_pose = (
            *_flat(left_hand.get_pos()),
            *_flat(left_hand.get_quat()),
        )
        capture_right_pose = (
            *_flat(right_hand.get_pos()),
            *_flat(right_hand.get_quat()),
        )
        capture_goal_xy = capture_qpos[base_dofs[:2]] + transport_delta[:2]
        capture_legacy_state = (
            *capture_qpos[base_dofs].tolist(),
            *capture_base_velocity,
            *capture_qpos[left_arm_dofs].tolist(),
            *capture_qpos[left_finger_dofs].tolist(),
            *capture_qpos[right_arm_dofs].tolist(),
            *capture_qpos[right_finger_dofs].tolist(),
            *capture_left_pose,
            *capture_right_pose,
            0.0,
            0.0,
            float(capture_goal_xy[0]),
            float(capture_goal_xy[1]),
            0.0,
        )
        capture_context = PI05ResidualContext(
            sealed_cup_mask=(False, False, False),
            parcel_shape=args.parcel_shape,
            parcel_size_m=tuple(float(value) for value in args.parcel_size_m),
            parcel_mass_kg=float(args.parcel_mass_kg),
            grasp_mode=expected_grasp_mode,
            retry_index=args.retry_index,
            stage="pregrasp",
            left_force_history_n=(),
            right_force_history_n=(),
            left_contact_anchor_m=tuple(float(value) for value in capture_left_pose[:3]),
            right_contact_anchor_m=tuple(float(value) for value in capture_right_pose[:3]),
            grasp_mode_conditioned=False,
        )
        capture_rgb, capture_depth, _, _ = camera.render(rgb=True, depth=True)
        capture_payload = write_pi05_heldout_observation(
            args.record_initial_observation,
            rgb=np.asarray(capture_rgb)[..., :3],
            depth_m=np.asarray(capture_depth, dtype=np.float32),
            observation_state=encode_pi05_state(
                capture_legacy_state, capture_context
            ),
            metadata={
                "episode_id": args.observation_episode_id,
                "profile": args.parcel_profile,
                "task_text": task_text,
                "expected_grasp_mode": expected_grasp_mode,
                "shape": args.parcel_shape,
                "orientation_mode": args.parcel_orientation,
                "size_m": list(args.parcel_size_m),
                "mass_kg": args.parcel_mass_kg,
                "friction": args.parcel_friction,
                "offset_m": list(args.parcel_offset_m),
                "yaw_rad": args.parcel_yaw_rad,
                "retry_index": args.retry_index,
                "pedestal_x_m": float(pedestal_position[0]),
            },
        )
        print(json.dumps({"initial_observation": capture_payload}, indent=2))
        if args.initial_observation_only:
            return 0
    harness_config = MobileHarnessConfig(
        min_progress_ratio=0.75 if args.cooperative_cradle else 0.50
    )
    if args.vla_policy_service_ready is not None:
        assert args.vla_checkpoint is not None
        policy_controller = MobileVLAServiceClient(
            args.vla_policy_service_ready,
            expected_checkpoint=args.vla_checkpoint,
        )
        if (
            policy_controller.chunk_execution_protocol
            != args.pi05_chunk_execution_protocol
            or policy_controller.chunk_execution_steps
            != args.pi05_chunk_execution_steps
            or policy_controller.stage_chunk_execution_steps
            != args.pi05_stage_chunk_execution_steps
        ):
            raise RuntimeError("persistent policy chunk contract does not match rollout")
        policy_controller.set_harness_config(harness_config)
    else:
        policy_controller = (
            MobileVLAHarnessController(
                args.vla_checkpoint,
                harness_config=harness_config,
                force_memory_enabled=args.force_memory_harness,
                depth_sidecar_enabled=args.depth_risk_sidecar,
                chunk_execution_steps=args.pi05_chunk_execution_steps,
                chunk_execution_protocol=args.pi05_chunk_execution_protocol,
                stage_chunk_execution_steps=args.pi05_stage_chunk_execution_steps,
            )
            if args.vla_checkpoint is not None
            else None
        )
    if policy_controller is not None:
        if args.policy_mode == "pi05_absolute" and not (
            policy_controller.policy_type == "pi05"
            and policy_controller.uses_absolute_contract
        ):
            raise RuntimeError(
                "pi05_absolute requires a PI0.5 80-D to 23-D absolute_v1 checkpoint"
            )
        if args.policy_mode == "pi05_residual" and not (
            policy_controller.policy_type == "pi05"
            and policy_controller.uses_residual_contract
        ):
            raise RuntimeError(
                "pi05_residual requires a PI0.5 80-D to 14-D residual_v1 checkpoint"
            )
    policy_trace: list[dict[str, object]] = []
    vla_selected_grasp_mode: str | None = None
    vla_grasp_mode_match: bool | None = None
    grasp_mode_route_mismatch_before_actuation = False
    routing_mode_consensus = None
    if vla_routes_grasp_mode:
        if camera is None or policy_controller is None:
            raise RuntimeError("VLA grasp routing requires an RGB-D policy controller")
        routing_rgb, routing_depth, _, _ = camera.render(rgb=True, depth=True)
        routing_wrist_rgb = None
        routing_wrist_depth = None
        if args.wrist_rgbd:
            if wrist_camera is None:
                raise RuntimeError("wrist RGB-D mode requires a wrist camera")
            routing_wrist_rgb, routing_wrist_depth = _render_left_wrist_rgbd(
                wrist_camera, left_hand, np
            )
        routing_qpos = np.asarray(_flat(robot.get_qpos()))
        routing_base_velocity = _flat(robot.get_dofs_velocity(base_dofs))
        routing_left_pose = (
            *_flat(left_hand.get_pos()),
            *_flat(left_hand.get_quat()),
        )
        routing_right_pose = (
            *_flat(right_hand.get_pos()),
            *_flat(right_hand.get_quat()),
        )
        routing_goal_xy = routing_qpos[base_dofs[:2]] + transport_delta[:2]
        routing_state = (
            *routing_qpos[base_dofs].tolist(),
            *routing_base_velocity,
            *routing_qpos[left_arm_dofs].tolist(),
            *routing_qpos[left_finger_dofs].tolist(),
            *routing_qpos[right_arm_dofs].tolist(),
            *routing_qpos[right_finger_dofs].tolist(),
            *routing_left_pose,
            *routing_right_pose,
            0.0,
            0.0,
            float(routing_goal_xy[0]),
            float(routing_goal_xy[1]),
            0.0,
        )
        routing_expert_action = (
            0.0,
            0.0,
            0.0,
            *routing_left_pose,
            -1.0,
            *routing_right_pose,
            1.0,
        )
        routing_context = PI05ResidualContext(
            sealed_cup_mask=(False, False, False),
            parcel_shape=args.parcel_shape,
            parcel_size_m=tuple(float(value) for value in args.parcel_size_m),
            parcel_mass_kg=float(args.parcel_mass_kg),
            grasp_mode=expected_grasp_mode,
            retry_index=args.retry_index,
            stage="pregrasp",
            left_force_history_n=(),
            right_force_history_n=(),
            left_contact_anchor_m=tuple(float(value) for value in routing_left_pose[:3]),
            right_contact_anchor_m=tuple(float(value) for value in routing_right_pose[:3]),
            grasp_mode_conditioned=False,
        )
        routing_telemetries = []
        routing_mode_logits = []
        for sample_index in range(args.vla_mode_votes):
            _, routing_telemetry = policy_controller.select(
                rgb=np.asarray(routing_rgb)[..., :3],
                depth=np.asarray(routing_depth, dtype=np.float32),
                wrist_rgb=(
                    np.asarray(routing_wrist_rgb)[..., :3]
                    if routing_wrist_rgb is not None
                    else None
                ),
                wrist_depth=(
                    np.asarray(routing_wrist_depth, dtype=np.float32)
                    if routing_wrist_depth is not None
                    else None
                ),
                state=routing_state,
                residual_context=routing_context,
                task=task_text,
                expert_action=routing_expert_action,
                stage="pregrasp",
                force_new_chunk=True,
            )
            routing_telemetry = dict(routing_telemetry)
            routing_telemetry["routing_sample_index"] = sample_index
            routing_projection = (
                routing_telemetry.get("absolute_projection")
                or routing_telemetry.get("residual_projection")
                or {}
            )
            mode_logits = routing_projection.get("mode_logits")
            if not isinstance(mode_logits, list) or len(mode_logits) != 3:
                raise RuntimeError("PI0.5 did not produce three grasp-mode logits")
            routing_mode_logits.append(mode_logits)
            routing_telemetries.append(routing_telemetry)
        routing_mode_consensus = select_pi05_mode_consensus(routing_mode_logits)
        vla_selected_grasp_mode = routing_mode_consensus.selected_mode
        vla_grasp_mode_match = vla_selected_grasp_mode == expected_grasp_mode
        grasp_mode_route_mismatch_before_actuation = (
            grasp_mode_route_failure_stage(
                required=args.require_vla_grasp_mode,
                matched=vla_grasp_mode_match,
            )
            is not None
        )
        args.grasp_mode = vla_selected_grasp_mode
        args.cooperative_cradle = args.grasp_mode == "cooperative_cradle"
        harness_config = MobileHarnessConfig(
            min_progress_ratio=0.75 if args.cooperative_cradle else 0.50
        )
        policy_controller.set_harness_config(harness_config)
        routing_decision = {
            "mode_input_hidden": True,
            "expected_mode": expected_grasp_mode,
            "selected_mode": vla_selected_grasp_mode,
            "executed_mode": args.grasp_mode,
            "matched": vla_grasp_mode_match,
            "sample_count": args.vla_mode_votes,
            "vote_counts": dict(
                zip(
                    ("top_suction", "side_suction", "cooperative_cradle"),
                    routing_mode_consensus.vote_counts,
                    strict=True,
                )
            ),
            "mean_logits": dict(
                zip(
                    ("top_suction", "side_suction", "cooperative_cradle"),
                    routing_mode_consensus.mean_logits,
                    strict=True,
                )
            ),
            "consensus_fraction": routing_mode_consensus.consensus_fraction,
        }
        routing_telemetries[-1]["routing_decision"] = routing_decision
        policy_trace.extend(routing_telemetries)
        policy_controller.clear_action_chunk()
    if args.grasp_mode == "top_suction":
        pregrasp_quaternions = (
            np.asarray(top_down_grasp_quaternion(args.parcel_yaw_rad)),
            pregrasp_quaternions[1],
        )
        tool_axis = _normalized(
            rotate_vector(tuple(pregrasp_quaternions[0].tolist()), (0.0, 0.0, 1.0)),
            np,
        )
        parcel_half_extent_on_axis = _shape_ray_extent(
            tool_axis,
            parcel_size,
            args.parcel_shape,
            args.parcel_orientation,
            args.parcel_yaw_rad,
            np,
        )
    elif args.grasp_mode == "side_suction":
        pregrasp_quaternions = (
            np.asarray(radial_side_grasp_quaternion()),
            pregrasp_quaternions[1],
        )
        tool_axis = _normalized(
            rotate_vector(tuple(pregrasp_quaternions[0].tolist()), (0.0, 0.0, 1.0)),
            np,
        )
        parcel_half_extent_on_axis = _shape_ray_extent(
            tool_axis,
            parcel_size,
            args.parcel_shape,
            args.parcel_orientation,
            args.parcel_yaw_rad,
            np,
        )
    recovery_contact_offset = np.asarray(
        (*args.recovery_contact_offset_m, 0.0), dtype=np.float64
    )
    left_contact_lateral_offset = recovery_contact_offset.copy()
    right_cradle_contact_target = None
    left_pregrasp_tcp_target = None
    right_pregrasp_tcp_target = None
    top_active_cup_offset_world = np.zeros(3)
    side_active_cup_offset_world = np.zeros(3)
    if args.grasp_mode in {"top_suction", "side_suction"}:
        active_cup_offsets = tuple(
            tri_cup_offsets(0.035)[index]
            for index in top_suction_active_cup_indices(args.minimum_sealed_cups)
        )
        active_cup_centroid = tuple(
            sum(offset[axis] for offset in active_cup_offsets)
            / len(active_cup_offsets)
            for axis in range(3)
        )
        active_cup_offset_world = np.asarray(
            rotate_vector(
                tuple(pregrasp_quaternions[0].tolist()),
                active_cup_centroid,
            )
        )
        if args.grasp_mode == "top_suction":
            top_active_cup_offset_world = active_cup_offset_world
        else:
            side_active_cup_offset_world = active_cup_offset_world
    if args.cooperative_cradle:
        cooperative_span_m = float(parcel_size[0]) * 0.5 - 0.04
        left_contact_lateral_offset = (
            np.asarray((-cooperative_span_m, 0.0, 0.0)) + recovery_contact_offset
        )
        right_contact_lateral_offset = (
            np.asarray((cooperative_span_m, 0.0, 0.0)) + recovery_contact_offset
        )
        right_tool_axis = _normalized(
            rotate_vector(tuple(pregrasp_quaternions[1].tolist()), (0.0, 0.0, 1.0)),
            np,
        )
        right_half_extent_on_axis = _shape_ray_extent(
            right_tool_axis,
            parcel_size,
            args.parcel_shape,
            args.parcel_orientation,
            args.parcel_yaw_rad,
            np,
        )
        left_contact_surface = (
            settled_parcel_position
            + left_contact_lateral_offset
            - tool_axis
            * (parcel_half_extent_on_axis - cooperative_contact_penetration_m)
        )
        right_contact_surface = (
            settled_parcel_position
            + right_contact_lateral_offset
            - right_tool_axis
            * (right_half_extent_on_axis - cooperative_contact_penetration_m)
        )
        left_pregrasp_tcp_target = left_contact_surface - tool_axis * 0.040
        right_pregrasp_tcp_target = right_contact_surface - right_tool_axis * 0.040
        right_cradle_contact_target = (
            right_contact_surface - right_tool_axis * cradle_tip_offset_m
        )
        pregrasp_targets = (
            left_pregrasp_tcp_target - tool_axis * cup_tip_offset_m,
            right_pregrasp_tcp_target - right_tool_axis * cradle_tip_offset_m,
        )
    elif args.grasp_mode == "top_suction":
        contact_penetration_m = 0.0005 + args.recovery_contact_penetration_delta_m
        top_contact_surface = (
            settled_parcel_position
            - tool_axis * (parcel_half_extent_on_axis - contact_penetration_m)
            + recovery_contact_offset
        )
        top_contact_tcp_target = top_contact_surface - top_active_cup_offset_world
        top_contact_hand_target = top_contact_tcp_target - tool_axis * cup_tip_offset_m
        left_pregrasp_target = pregrasp_start_positions[0].copy()
        left_pregrasp_target[2] = (
            top_contact_hand_target - tool_axis * 0.040
        )[2]
        pregrasp_targets = (left_pregrasp_target, pregrasp_start_positions[1])
    else:
        contact_penetration_m = 0.0005 + args.recovery_contact_penetration_delta_m
        side_contact_surface = (
            settled_parcel_position
            - tool_axis * (parcel_half_extent_on_axis - contact_penetration_m)
            + recovery_contact_offset
        )
        side_contact_tcp_target = side_contact_surface - side_active_cup_offset_world
        side_contact_hand_target = side_contact_tcp_target - tool_axis * cup_tip_offset_m
        pregrasp_targets = (
            side_contact_hand_target - tool_axis * 0.040,
            pregrasp_start_positions[1],
        )
    pregrasp_init_qpos = np.asarray(_flat(robot.get_qpos()))
    if args.cooperative_cradle:
        pregrasp_solution = robot.inverse_kinematics_multilink(
            links=(left_hand, right_hand),
            poss=(left_pregrasp_tcp_target, right_pregrasp_tcp_target),
            quats=pregrasp_quaternions,
            local_points=(
                np.asarray((0.0, 0.0, cup_tip_offset_m)),
                np.asarray((0.0, 0.0, cradle_tip_offset_m)),
            ),
            init_qpos=pregrasp_init_qpos,
            respect_joint_limit=True,
            max_samples=12,
            max_solver_iters=80,
            damping=0.02,
            max_step_size=0.15,
            dofs_idx_local=arm_dofs,
        )
        pregrasp_values = np.asarray(_flat(pregrasp_solution))
    elif args.grasp_mode in {"top_suction", "side_suction"}:
        pregrasp_solution = robot.inverse_kinematics(
            link=left_hand,
            pos=pregrasp_targets[0],
            quat=pregrasp_quaternions[0],
            init_qpos=pregrasp_init_qpos,
            respect_joint_limit=True,
            max_samples=16,
            max_solver_iters=100,
            damping=0.02,
            max_step_size=0.15,
            dofs_idx_local=left_arm_dofs,
        )
        pregrasp_values = pregrasp_init_qpos.copy()
        pregrasp_values[left_arm_dofs] = np.asarray(_flat(pregrasp_solution))[
            left_arm_dofs
        ]
    else:
        pregrasp_solution = robot.inverse_kinematics_multilink(
            links=(left_hand, right_hand),
            poss=pregrasp_targets,
            quats=pregrasp_quaternions,
            init_qpos=pregrasp_init_qpos,
            respect_joint_limit=True,
            max_samples=12,
            max_solver_iters=50,
            damping=0.02,
            max_step_size=0.25,
            dofs_idx_local=arm_dofs,
        )
        pregrasp_values = np.asarray(_flat(pregrasp_solution))
    cradle_monitor = (
        MobileVCradleMonitor(robot=robot, parcel=parcel, torch=torch)
        if args.cooperative_cradle
        else None
    )
    cradle_lift_contact_steps = 0
    cradle_transport_contact_steps = 0
    cradle_place_contact_steps = 0
    cradle_lift_steps = 0
    cradle_transport_steps = 0
    cradle_place_steps = 0
    cooperative_lift_ik_attempts = 0
    cooperative_lift_ik_accepts = 0
    cooperative_lift_ik_rejections = 0
    cooperative_place_ik_attempts = 0
    cooperative_place_ik_accepts = 0
    cooperative_place_ik_rejections = 0
    cradle_engage_steps = 0
    cradle_engage_contact_steps = 0
    cradle_engaged_before_lift = False
    writer = None
    if args.record_dataset is not None:
        writer = MobileBimanualLeRobotWriter(
            args.record_dataset,
            fps=30,
            image_size=(args.image_size, args.image_size),
            include_depth=True,
            include_wrist_rgbd=args.wrist_rgbd,
            use_videos=True,
        )
    pi05_writer = None
    if args.record_pi05_residual_dataset is not None:
        pi05_writer = MobilePI05AutonomousLeRobotWriter(
            args.record_pi05_residual_dataset,
            fps=30,
            image_size=(args.image_size, args.image_size),
            include_wrist_rgbd=args.wrist_rgbd,
        )
    absolute_writer = None
    if args.record_pi05_absolute_dataset is not None:
        absolute_writer = MobilePI05AbsoluteLeRobotWriter(
            args.record_pi05_absolute_dataset,
            fps=30,
            image_size=(args.image_size, args.image_size),
            include_wrist_rgbd=args.wrist_rgbd,
        )
    recorded_frames = 0
    recorded_physics_steps = 0
    transport_capacity_ratio = 0.60 if args.cooperative_cradle else 0.75
    policy_stride_frames = (
        1
        if args.pi05_chunk_execution_protocol == "pi05-open-loop-queue-v1"
        else 30 // args.policy_hz
    )
    latest_policy_action: tuple[float, ...] | None = None
    latest_policy_stage: str | None = None
    policy_applied_physics_steps = 0
    latest_policy_left_arm_qpos = None
    latest_policy_dual_arm_qpos = None
    latest_policy_arm_stage: str | None = None
    latest_pi05_left_arm_delta_qpos = np.zeros(7)
    latest_pi05_dual_arm_delta_qpos = np.zeros(14)
    latest_pi05_left_residual_m = np.zeros(3)
    latest_pi05_right_residual_m = np.zeros(3)
    latest_pi05_base_residual = np.zeros(3)
    latest_pi05_raw_residual_action: tuple[float, ...] | None = None
    latest_pi05_raw_absolute_action: tuple[float, ...] | None = None
    latest_pi05_inference_call_index = 0
    latest_pi05_chunk_step_index = 0
    latest_pi05_policy_task = task_text
    transport_arm_anchor_position = None
    transport_arm_anchor_quaternion = None
    transport_right_arm_anchor_position = None
    transport_right_arm_anchor_quaternion = None
    transport_arm_anchor_base = None
    arm_policy_update_attempts = 0
    arm_policy_update_accepts = 0
    arm_policy_update_rejections = 0
    arm_policy_applied_physics_steps = 0
    latest_policy_goal_verified = False
    transport_target_base = None
    contact_snapshot_saved = False
    left_force_history_n: deque[float] = deque(maxlen=6)
    right_force_history_n: deque[float] = deque(maxlen=6)
    pending_policy_trace_index: int | None = None

    def record_control_frame(
        *,
        stage: str,
        base_action: object,
        left_position: object,
        left_quaternion: object,
        left_tool_command: float,
        right_position: object,
        right_quaternion: object,
        right_tool_command: float,
        suction_controller: object | None = None,
        policy_expert_base_action: object | None = None,
        policy_remaining_distance_m: float | None = None,
        force_policy_sample: bool = False,
    ) -> None:
        nonlocal recorded_frames, recorded_physics_steps
        nonlocal latest_policy_action, latest_policy_stage
        nonlocal latest_policy_left_arm_qpos, latest_policy_dual_arm_qpos
        nonlocal latest_policy_arm_stage
        nonlocal latest_pi05_left_arm_delta_qpos
        nonlocal latest_pi05_dual_arm_delta_qpos
        nonlocal latest_pi05_left_residual_m, latest_pi05_right_residual_m
        nonlocal latest_pi05_base_residual
        nonlocal latest_pi05_raw_residual_action
        nonlocal latest_pi05_raw_absolute_action
        nonlocal latest_pi05_inference_call_index, latest_pi05_chunk_step_index
        nonlocal latest_pi05_policy_task
        nonlocal arm_policy_update_attempts, arm_policy_update_accepts
        nonlocal arm_policy_update_rejections
        nonlocal latest_policy_goal_verified
        nonlocal vla_selected_grasp_mode, vla_grasp_mode_match
        nonlocal contact_snapshot_saved
        nonlocal pending_policy_trace_index
        if (
            writer is None
            and pi05_writer is None
            and policy_controller is None
            and args.record_video is None
            and args.record_contact_video is None
            and args.contact_snapshot is None
        ):
            return
        if not force_policy_sample:
            recorded_physics_steps += 1
            if recorded_physics_steps % 8 != 0:
                return
        if args.record_video is not None:
            assert media_camera is not None
            media_camera.render(rgb=True, depth=False)
        contact_rgb = None
        if args.record_contact_video is not None or (
            args.contact_snapshot is not None and not contact_snapshot_saved
        ):
            assert contact_camera is not None
            contact_rgb, _, _, _ = contact_camera.render(rgb=True, depth=False)
        if (
            args.contact_snapshot is not None
            and not contact_snapshot_saved
            and suction_controller is not None
            and getattr(suction_controller, "attachment", None) is not None
        ):
            from imageio.v3 import imwrite

            assert contact_rgb is not None
            args.contact_snapshot.parent.mkdir(parents=True, exist_ok=True)
            imwrite(
                args.contact_snapshot,
                np.asarray(contact_rgb)[..., :3].astype(np.uint8),
            )
            contact_snapshot_saved = args.contact_snapshot.is_file()
        if writer is None and pi05_writer is None and policy_controller is None:
            return
        if camera is None:
            raise RuntimeError("mobile observation requires an RGB-D camera")
        left_contact_force_n = 0.0
        right_contact_force_n = 0.0
        if suction_controller is not None:
            _, left_contact_force_n = suction_controller.contact_snapshot()
        if cradle_monitor is not None:
            _, right_contact_force_n = cradle_monitor.snapshot()
        left_force_history_n.append(float(left_contact_force_n))
        right_force_history_n.append(float(right_contact_force_n))
        rgb, depth, _, _ = camera.render(rgb=True, depth=True)
        wrist_rgb = None
        wrist_depth = None
        if args.wrist_rgbd:
            if wrist_camera is None:
                raise RuntimeError("wrist RGB-D mode requires a wrist camera")
            wrist_rgb, wrist_depth = _render_left_wrist_rgbd(
                wrist_camera, left_hand, np
            )
        current_qpos = np.asarray(_flat(robot.get_qpos()))
        encoded_goal_xy = (
            np.asarray(transport_target_base[:2], dtype=np.float64)
            if transport_target_base is not None
            else current_qpos[base_dofs[:2]] + transport_delta[:2]
        )
        base_velocity = _flat(robot.get_dofs_velocity(base_dofs))
        left_pose = (*_flat(left_hand.get_pos()), *_flat(left_hand.get_quat()))
        right_pose = (*_flat(right_hand.get_pos()), *_flat(right_hand.get_quat()))
        parcel_pose = (*_flat(parcel.get_pos()), *_flat(parcel.get_quat()))
        state_vector = (
            *current_qpos[base_dofs].tolist(),
            *base_velocity,
            *current_qpos[left_arm_dofs].tolist(),
            *current_qpos[left_finger_dofs].tolist(),
            *current_qpos[right_arm_dofs].tolist(),
            *current_qpos[right_finger_dofs].tolist(),
            *left_pose,
            *right_pose,
            left_contact_force_n,
            right_contact_force_n,
            float(encoded_goal_xy[0]),
            float(encoded_goal_xy[1]),
            0.0,
        )
        if pending_policy_trace_index is not None:
            pending = policy_trace[pending_policy_trace_index]
            pending["achieved_next_observation_frame"] = recorded_frames
            pending["achieved_next_physics_step"] = recorded_physics_steps
            pending["achieved_after_physics_steps"] = (
                recorded_physics_steps - int(pending["physics_step"])
            )
            pending["achieved_next_state"] = [
                float(value) for value in state_vector
            ]
            pending["achieved_next_ee_pose"] = {
                "left_position_m_quaternion_wxyz": [
                    float(value) for value in left_pose
                ],
                "right_position_m_quaternion_wxyz": [
                    float(value) for value in right_pose
                ],
            }
            pending_policy_trace_index = None
        expert_base_action = (
            base_action
            if policy_expert_base_action is None
            else policy_expert_base_action
        )
        action_vector = (
            *_flat(expert_base_action),
            *_flat(left_position),
            *_flat(left_quaternion),
            float(left_tool_command),
            *_flat(right_position),
            *_flat(right_quaternion),
            float(right_tool_command),
        )
        if policy_controller is not None:
            policy_controller.observe_contact_forces(
                left_contact_force_n,
                right_contact_force_n,
            )
        residual_context = None
        if policy_controller is not None and (
            policy_controller.uses_residual_contract
            or policy_controller.uses_absolute_contract
        ):
            sealed_cup_mask = (
                suction_controller.sealed_cup_mask()
                if suction_controller is not None
                and hasattr(suction_controller, "sealed_cup_mask")
                else (False, False, False)
            )
            residual_context = PI05ResidualContext(
                sealed_cup_mask=sealed_cup_mask,
                parcel_shape=args.parcel_shape,
                parcel_size_m=tuple(float(value) for value in args.parcel_size_m),
                parcel_mass_kg=float(args.parcel_mass_kg),
                grasp_mode=args.grasp_mode,
                retry_index=args.retry_index,
                stage=stage,
                left_force_history_n=tuple(left_force_history_n),
                right_force_history_n=tuple(right_force_history_n),
                left_contact_anchor_m=tuple(float(value) for value in _flat(left_position)),
                right_contact_anchor_m=tuple(float(value) for value in _flat(right_position)),
                grasp_mode_conditioned=False,
            )
        policy_selected_this_frame = False
        current_policy_telemetry = None
        if policy_controller is not None and (
            recorded_frames % policy_stride_frames == 0
            or latest_policy_stage != stage
            or policy_controller.has_queued_action(stage)
        ):
            latest_policy_action, telemetry = policy_controller.select(
                rgb=np.asarray(rgb)[..., :3],
                depth=np.asarray(depth, dtype=np.float32),
                wrist_rgb=(
                    np.asarray(wrist_rgb)[..., :3] if wrist_rgb is not None else None
                ),
                wrist_depth=(
                    np.asarray(wrist_depth, dtype=np.float32)
                    if wrist_depth is not None
                    else None
                ),
                state=state_vector,
                residual_context=residual_context,
                task=task_text,
                expert_action=action_vector,
                stage=stage,
                goal_xy=(
                    transport_target_base[:2]
                    if stage == "transport" and transport_target_base is not None
                    else None
                ),
            )
            policy_selected_this_frame = True
            current_policy_telemetry = telemetry
            latest_policy_goal_verified = bool(
                latest_policy_goal_verified
                or (telemetry.get("goal_judgement") or {}).get("arrival_verified")
            )
            if stage == "pregrasp" and vla_selected_grasp_mode is None:
                projection = (
                    telemetry.get("absolute_projection")
                    or telemetry.get("residual_projection")
                    or {}
                )
                predicted_mode = projection.get("predicted_mode")
                if predicted_mode is not None:
                    vla_selected_grasp_mode = str(predicted_mode)
                    vla_grasp_mode_match = vla_selected_grasp_mode == args.grasp_mode
            latest_policy_stage = stage
            if args.policy_mode == "pi05_residual":
                raw_residual_action = telemetry.get("raw_residual_action")
                if raw_residual_action is None or len(raw_residual_action) != 14:
                    raise RuntimeError("PI0.5 controller did not expose its raw 14-D residual")
                latest_pi05_raw_residual_action = tuple(
                    float(value) for value in raw_residual_action
                )
                latest_pi05_inference_call_index = int(
                    telemetry["inference_call_index"]
                )
                latest_pi05_chunk_step_index = int(telemetry["chunk_step_index"])
                latest_pi05_policy_task = str(telemetry["policy_task"])
                latest_pi05_base_residual = np.asarray(
                    latest_policy_action[:3], dtype=np.float64
                ) - np.asarray(_flat(expert_base_action), dtype=np.float64)
                latest_pi05_left_residual_m = np.asarray(
                    latest_policy_action[3:6], dtype=np.float64
                ) - np.asarray(_flat(left_position), dtype=np.float64)
                latest_pi05_right_residual_m = np.asarray(
                    latest_policy_action[11:14], dtype=np.float64
                ) - np.asarray(_flat(right_position), dtype=np.float64)
            elif args.policy_mode == "pi05_absolute":
                raw_absolute_action = telemetry.get("raw_absolute_action")
                if raw_absolute_action is None or len(raw_absolute_action) != 23:
                    raise RuntimeError(
                        "PI0.5 absolute controller did not expose its raw 23-D output"
                    )
                if telemetry.get("action_contract") != "pi05_absolute_v1":
                    raise RuntimeError("PI0.5 checkpoint does not use absolute_v1")
                latest_pi05_raw_absolute_action = tuple(
                    float(value) for value in raw_absolute_action
                )
                latest_pi05_inference_call_index = int(
                    telemetry["inference_call_index"]
                )
                latest_pi05_chunk_step_index = int(telemetry["chunk_step_index"])
                latest_pi05_policy_task = str(telemetry["policy_task"])
                latest_pi05_base_residual = np.asarray(
                    latest_policy_action[:3], dtype=np.float64
                )
                latest_pi05_left_residual_m = np.asarray(
                    latest_policy_action[3:6], dtype=np.float64
                ) - np.asarray(_flat(left_pose[:3]), dtype=np.float64)
                latest_pi05_right_residual_m = np.asarray(
                    latest_policy_action[11:14], dtype=np.float64
                ) - np.asarray(_flat(right_pose[:3]), dtype=np.float64)
            arm_residual_telemetry = {
                "enabled": args.policy_mode in {
                    "base_arm_residual",
                    "base_dual_arm_residual",
                    "pi05_residual",
                    "pi05_absolute",
                    "pi05_absolute",
                },
                "mode": args.policy_mode,
                "stage_authorized": stage
                in {"pregrasp", "grasp_approach", "lift", "transport"},
                "ik_accepted": False,
                "target_position_m": None,
                "right_target_position_m": None,
                "anchor_position_m": None,
                "right_anchor_position_m": None,
                "residual_norm_m": None,
                "right_residual_norm_m": None,
                "projection": None,
                "rejection": None,
            }
            if args.policy_mode == "base_arm_residual" and stage == "transport":
                arm_policy_update_attempts += 1
                if (
                    transport_arm_anchor_position is None
                    or transport_arm_anchor_quaternion is None
                    or transport_arm_anchor_base is None
                ):
                    arm_policy_update_rejections += 1
                    arm_residual_telemetry["rejection"] = "transport_anchor_unavailable"
                elif telemetry["emergency_stop"]:
                    arm_policy_update_rejections += 1
                    arm_residual_telemetry["rejection"] = "harness_emergency_stop"
                else:
                    current_base = np.asarray(_flat(robot.get_qpos()))[base_dofs]
                    dynamic_anchor = np.asarray(transport_arm_anchor_position).copy()
                    dynamic_anchor[:2] += current_base[:2] - np.asarray(
                        transport_arm_anchor_base
                    )[:2]
                    target_position = np.asarray(
                        clamp_position_residual_to_anchor(
                            latest_policy_action[3:6],
                            dynamic_anchor,
                            max_residual_m=0.01,
                        )
                    )
                    try:
                        arm_solution = robot.inverse_kinematics(
                            link=hand,
                            pos=target_position,
                            quat=np.asarray(transport_arm_anchor_quaternion),
                            init_qpos=np.asarray(_flat(robot.get_qpos())),
                            respect_joint_limit=True,
                            max_samples=4,
                            max_solver_iters=40,
                            damping=0.03,
                            max_step_size=0.08,
                            dofs_idx_local=left_arm_dofs,
                        )
                        candidate_qpos = np.asarray(_flat(arm_solution))[left_arm_dofs]
                        if not np.isfinite(candidate_qpos).all():
                            raise ValueError("IK returned non-finite joint targets")
                    except (RuntimeError, ValueError) as exc:
                        latest_policy_left_arm_qpos = None
                        latest_policy_arm_stage = None
                        arm_policy_update_rejections += 1
                        arm_residual_telemetry["rejection"] = str(exc)
                    else:
                        latest_policy_left_arm_qpos = candidate_qpos
                        latest_policy_arm_stage = stage
                        arm_policy_update_accepts += 1
                        arm_residual_telemetry.update(
                            {
                                "ik_accepted": True,
                                "target_position_m": target_position.tolist(),
                                "anchor_position_m": dynamic_anchor.tolist(),
                                "residual_norm_m": float(
                                    np.linalg.norm(target_position - dynamic_anchor)
                                ),
                            }
                        )
            elif args.policy_mode == "base_dual_arm_residual" and stage == "transport":
                arm_policy_update_attempts += 1
                authority = transport_arm_authority(
                    stage=stage,
                    remaining_distance_m=policy_remaining_distance_m,
                )
                if (
                    transport_arm_anchor_position is None
                    or transport_arm_anchor_quaternion is None
                    or transport_right_arm_anchor_position is None
                    or transport_right_arm_anchor_quaternion is None
                    or transport_arm_anchor_base is None
                ):
                    arm_policy_update_rejections += 1
                    arm_residual_telemetry["rejection"] = "transport_anchor_unavailable"
                elif telemetry["emergency_stop"]:
                    arm_policy_update_rejections += 1
                    arm_residual_telemetry["rejection"] = "harness_emergency_stop"
                elif telemetry["fallback_to_expert"] or float(telemetry["selected_scale"]) <= 0.0:
                    arm_policy_update_rejections += 1
                    arm_residual_telemetry["rejection"] = "no_learned_authority"
                elif authority <= 0.0:
                    arm_policy_update_rejections += 1
                    arm_residual_telemetry["rejection"] = "precision_authority_handoff"
                else:
                    current_base = np.asarray(_flat(robot.get_qpos()))[base_dofs]
                    base_delta = current_base[:2] - np.asarray(transport_arm_anchor_base)[:2]
                    dynamic_left_anchor = np.asarray(transport_arm_anchor_position).copy()
                    dynamic_right_anchor = np.asarray(transport_right_arm_anchor_position).copy()
                    dynamic_left_anchor[:2] += base_delta
                    dynamic_right_anchor[:2] += base_delta
                    projection = project_dual_arm_residuals(
                        left_proposal_m=latest_policy_action[3:6],
                        right_proposal_m=latest_policy_action[11:14],
                        left_anchor_m=dynamic_left_anchor,
                        right_anchor_m=dynamic_right_anchor,
                        authority_scale=authority,
                        cooperative_carry=args.cooperative_cradle,
                    )
                    try:
                        arm_solution = robot.inverse_kinematics_multilink(
                            links=(left_hand, right_hand),
                            poss=(
                                np.asarray(projection.left_target_m),
                                np.asarray(projection.right_target_m),
                            ),
                            quats=(
                                np.asarray(transport_arm_anchor_quaternion),
                                np.asarray(transport_right_arm_anchor_quaternion),
                            ),
                            init_qpos=np.asarray(_flat(robot.get_qpos())),
                            respect_joint_limit=True,
                            max_samples=4,
                            max_solver_iters=50,
                            damping=0.03,
                            max_step_size=0.08,
                            dofs_idx_local=arm_dofs,
                        )
                        candidate_qpos = np.asarray(_flat(arm_solution))[arm_dofs]
                        if not np.isfinite(candidate_qpos).all():
                            raise ValueError("dual-arm IK returned non-finite joint targets")
                    except (RuntimeError, ValueError) as exc:
                        latest_policy_dual_arm_qpos = None
                        latest_policy_arm_stage = None
                        arm_policy_update_rejections += 1
                        arm_residual_telemetry["rejection"] = str(exc)
                    else:
                        latest_policy_dual_arm_qpos = candidate_qpos
                        latest_policy_arm_stage = stage
                        arm_policy_update_accepts += 1
                        arm_residual_telemetry.update(
                            {
                                "ik_accepted": True,
                                "target_position_m": list(projection.left_target_m),
                                "right_target_position_m": list(projection.right_target_m),
                                "anchor_position_m": dynamic_left_anchor.tolist(),
                                "right_anchor_position_m": dynamic_right_anchor.tolist(),
                                "residual_norm_m": float(
                                    np.linalg.norm(
                                        np.asarray(projection.left_target_m)
                                        - dynamic_left_anchor
                                    )
                                ),
                                "right_residual_norm_m": float(
                                    np.linalg.norm(
                                        np.asarray(projection.right_target_m)
                                        - dynamic_right_anchor
                                    )
                                ),
                                "projection": projection.to_dict(),
                            }
                        )
            elif args.policy_mode == "pi05_absolute" and stage in {
                "pregrasp",
                "grasp_approach",
                "lift",
                "transport",
                "place",
            }:
                arm_policy_update_attempts += 1
                if telemetry["emergency_stop"]:
                    arm_policy_update_rejections += 1
                    arm_residual_telemetry["rejection"] = "harness_emergency_stop"
                elif telemetry["fallback_to_expert"]:
                    arm_policy_update_rejections += 1
                    arm_residual_telemetry["rejection"] = "expert_fallback_forbidden"
                else:
                    try:
                        current_robot_qpos = np.asarray(_flat(robot.get_qpos()))
                        arm_solution = robot.inverse_kinematics_multilink(
                            links=(left_hand, right_hand),
                            poss=(
                                np.asarray(latest_policy_action[3:6]),
                                np.asarray(latest_policy_action[11:14]),
                            ),
                            quats=(
                                np.asarray(latest_policy_action[6:10]),
                                np.asarray(latest_policy_action[14:18]),
                            ),
                            init_qpos=current_robot_qpos,
                            respect_joint_limit=True,
                            max_samples=4,
                            max_solver_iters=50,
                            damping=0.03,
                            max_step_size=0.08,
                            dofs_idx_local=arm_dofs,
                        )
                        candidate_qpos = np.asarray(_flat(arm_solution))[arm_dofs]
                        if not np.isfinite(candidate_qpos).all():
                            raise ValueError(
                                "PI0.5 absolute dual-arm IK returned non-finite targets"
                            )
                    except (RuntimeError, ValueError) as exc:
                        latest_policy_left_arm_qpos = None
                        latest_policy_dual_arm_qpos = None
                        latest_policy_arm_stage = None
                        arm_policy_update_rejections += 1
                        arm_residual_telemetry["rejection"] = str(exc)
                    else:
                        latest_policy_left_arm_qpos = None
                        latest_policy_dual_arm_qpos = candidate_qpos
                        latest_policy_arm_stage = stage
                        arm_policy_update_accepts += 1
                        absolute_projection = telemetry.get("absolute_projection") or {}
                        arm_residual_telemetry.update(
                            {
                                "ik_accepted": True,
                                "target_position_m": list(latest_policy_action[3:6]),
                                "right_target_position_m": list(
                                    latest_policy_action[11:14]
                                ),
                                "anchor_position_m": list(left_pose[:3]),
                                "right_anchor_position_m": list(right_pose[:3]),
                                "residual_norm_m": float(
                                    np.linalg.norm(latest_pi05_left_residual_m)
                                ),
                                "right_residual_norm_m": float(
                                    np.linalg.norm(latest_pi05_right_residual_m)
                                ),
                                "projection": absolute_projection,
                            }
                        )
            elif args.policy_mode == "pi05_residual" and stage in {
                "pregrasp",
                "grasp_approach",
                "lift",
                "transport",
            }:
                arm_policy_update_attempts += 1
                if telemetry["emergency_stop"]:
                    arm_policy_update_rejections += 1
                    arm_residual_telemetry["rejection"] = "harness_emergency_stop"
                elif telemetry["fallback_to_expert"]:
                    arm_policy_update_rejections += 1
                    arm_residual_telemetry["rejection"] = "no_learned_authority"
                elif stage == "grasp_approach":
                    # The contact controller already advances through sub-millimetre
                    # IK steps. PI0.5 moves that dynamic target instead of replacing
                    # the safe approach trajectory with a final absolute IK command.
                    latest_policy_left_arm_qpos = None
                    latest_policy_dual_arm_qpos = None
                    latest_policy_arm_stage = stage
                    arm_policy_update_accepts += 1
                    residual_projection = telemetry.get("residual_projection") or {}
                    arm_residual_telemetry.update(
                        {
                            "ik_accepted": True,
                            "target_position_m": list(latest_policy_action[3:6]),
                            "right_target_position_m": (
                                list(latest_policy_action[11:14])
                                if args.cooperative_cradle
                                else None
                            ),
                            "residual_norm_m": float(
                                np.linalg.norm(latest_pi05_left_residual_m)
                            ),
                            "right_residual_norm_m": float(
                                np.linalg.norm(latest_pi05_right_residual_m)
                            ),
                            "projection": residual_projection,
                        }
                    )
                elif stage == "lift":
                    # Solve the nominal and residual targets from the same seed.
                    # Their joint-space difference can be added to every point of
                    # the continuous lift trajectory without freezing it at 1 Hz.
                    try:
                        current_robot_qpos = np.asarray(_flat(robot.get_qpos()))
                        residual_below_actuation_deadband = max(
                            float(np.linalg.norm(latest_pi05_left_residual_m)),
                            float(np.linalg.norm(latest_pi05_right_residual_m)),
                        ) <= 1e-5
                        if residual_below_actuation_deadband:
                            candidate_delta_qpos = np.zeros(
                                14 if args.cooperative_cradle else 7
                            )
                        elif args.cooperative_cradle:
                            nominal_solution = robot.inverse_kinematics_multilink(
                                links=(left_hand, right_hand),
                                poss=(
                                    np.asarray(_flat(left_position)),
                                    np.asarray(_flat(right_position)),
                                ),
                                quats=(
                                    np.asarray(_flat(left_quaternion)),
                                    np.asarray(_flat(right_quaternion)),
                                ),
                                init_qpos=current_robot_qpos,
                                respect_joint_limit=True,
                                max_samples=1,
                                max_solver_iters=50,
                                damping=0.03,
                                max_step_size=0.05,
                                dofs_idx_local=arm_dofs,
                            )
                            residual_solution = robot.inverse_kinematics_multilink(
                                links=(left_hand, right_hand),
                                poss=(
                                    np.asarray(latest_policy_action[3:6]),
                                    np.asarray(latest_policy_action[11:14]),
                                ),
                                quats=(
                                    np.asarray(latest_policy_action[6:10]),
                                    np.asarray(latest_policy_action[14:18]),
                                ),
                                init_qpos=current_robot_qpos,
                                respect_joint_limit=True,
                                max_samples=1,
                                max_solver_iters=50,
                                damping=0.03,
                                max_step_size=0.05,
                                dofs_idx_local=arm_dofs,
                            )
                            nominal_qpos = np.asarray(_flat(nominal_solution))[arm_dofs]
                            residual_qpos = np.asarray(_flat(residual_solution))[arm_dofs]
                            candidate_delta_qpos = residual_qpos - nominal_qpos
                        else:
                            nominal_solution = robot.inverse_kinematics(
                                link=left_hand,
                                pos=np.asarray(_flat(left_position)),
                                quat=np.asarray(_flat(left_quaternion)),
                                init_qpos=current_robot_qpos,
                                respect_joint_limit=True,
                                max_samples=1,
                                max_solver_iters=50,
                                damping=0.03,
                                max_step_size=0.05,
                                dofs_idx_local=left_arm_dofs,
                            )
                            residual_solution = robot.inverse_kinematics(
                                link=left_hand,
                                pos=np.asarray(latest_policy_action[3:6]),
                                quat=np.asarray(latest_policy_action[6:10]),
                                init_qpos=current_robot_qpos,
                                respect_joint_limit=True,
                                max_samples=1,
                                max_solver_iters=50,
                                damping=0.03,
                                max_step_size=0.05,
                                dofs_idx_local=left_arm_dofs,
                            )
                            nominal_qpos = np.asarray(_flat(nominal_solution))[
                                left_arm_dofs
                            ]
                            residual_qpos = np.asarray(_flat(residual_solution))[
                                left_arm_dofs
                            ]
                            candidate_delta_qpos = residual_qpos - nominal_qpos
                        if not np.isfinite(candidate_delta_qpos).all():
                            raise ValueError("PI0.5 lift delta IK returned non-finite targets")
                    except (RuntimeError, ValueError) as exc:
                        latest_pi05_left_arm_delta_qpos = np.zeros(7)
                        latest_pi05_dual_arm_delta_qpos = np.zeros(14)
                        latest_policy_arm_stage = None
                        arm_policy_update_rejections += 1
                        arm_residual_telemetry["rejection"] = str(exc)
                    else:
                        latest_policy_left_arm_qpos = None
                        latest_policy_dual_arm_qpos = None
                        if args.cooperative_cradle:
                            latest_pi05_dual_arm_delta_qpos = candidate_delta_qpos
                        else:
                            latest_pi05_left_arm_delta_qpos = candidate_delta_qpos
                        latest_policy_arm_stage = stage
                        arm_policy_update_accepts += 1
                        residual_projection = telemetry.get("residual_projection") or {}
                        arm_residual_telemetry.update(
                            {
                                "ik_accepted": True,
                                "target_position_m": list(latest_policy_action[3:6]),
                                "right_target_position_m": (
                                    list(latest_policy_action[11:14])
                                    if args.cooperative_cradle
                                    else None
                                ),
                                "residual_norm_m": float(
                                    np.linalg.norm(latest_pi05_left_residual_m)
                                ),
                                "right_residual_norm_m": float(
                                    np.linalg.norm(latest_pi05_right_residual_m)
                                ),
                                "projection": residual_projection,
                            }
                        )
                else:
                    try:
                        current_robot_qpos = np.asarray(_flat(robot.get_qpos()))
                        residual_below_actuation_deadband = max(
                            float(np.linalg.norm(latest_pi05_left_residual_m)),
                            float(np.linalg.norm(latest_pi05_right_residual_m)),
                        ) <= 1e-5
                        if stage == "pregrasp" and residual_below_actuation_deadband:
                            candidate_qpos = np.asarray(pregrasp_values)[
                                arm_dofs if args.cooperative_cradle else left_arm_dofs
                            ]
                        elif stage == "transport" and residual_below_actuation_deadband:
                            candidate_qpos = np.asarray(target_arm_qpos)
                        elif args.cooperative_cradle:
                            arm_solution = robot.inverse_kinematics_multilink(
                                links=(left_hand, right_hand),
                                poss=(
                                    np.asarray(latest_policy_action[3:6]),
                                    np.asarray(latest_policy_action[11:14]),
                                ),
                                quats=(
                                    np.asarray(latest_policy_action[6:10]),
                                    np.asarray(latest_policy_action[14:18]),
                                ),
                                init_qpos=current_robot_qpos,
                                respect_joint_limit=True,
                                max_samples=1,
                                max_solver_iters=50,
                                damping=0.03,
                                max_step_size=0.05,
                                dofs_idx_local=arm_dofs,
                            )
                            candidate_qpos = np.asarray(_flat(arm_solution))[arm_dofs]
                        else:
                            arm_solution = robot.inverse_kinematics(
                                link=left_hand,
                                pos=np.asarray(latest_policy_action[3:6]),
                                quat=np.asarray(latest_policy_action[6:10]),
                                init_qpos=current_robot_qpos,
                                respect_joint_limit=True,
                                max_samples=1,
                                max_solver_iters=50,
                                damping=0.03,
                                max_step_size=0.05,
                                dofs_idx_local=left_arm_dofs,
                            )
                            candidate_qpos = np.asarray(_flat(arm_solution))[
                                left_arm_dofs
                            ]
                        if not np.isfinite(candidate_qpos).all():
                            raise ValueError("PI0.5 residual IK returned non-finite targets")
                    except (RuntimeError, ValueError) as exc:
                        latest_policy_left_arm_qpos = None
                        latest_policy_dual_arm_qpos = None
                        latest_policy_arm_stage = None
                        arm_policy_update_rejections += 1
                        arm_residual_telemetry["rejection"] = str(exc)
                    else:
                        if args.cooperative_cradle:
                            latest_policy_dual_arm_qpos = candidate_qpos
                            latest_policy_left_arm_qpos = None
                        else:
                            latest_policy_left_arm_qpos = candidate_qpos
                            latest_policy_dual_arm_qpos = None
                        latest_policy_arm_stage = stage
                        arm_policy_update_accepts += 1
                        residual_projection = telemetry.get("residual_projection") or {}
                        arm_residual_telemetry.update(
                            {
                                "ik_accepted": True,
                                "target_position_m": list(latest_policy_action[3:6]),
                                "right_target_position_m": (
                                    list(latest_policy_action[11:14])
                                    if args.cooperative_cradle
                                    else None
                                ),
                                "residual_norm_m": float(
                                    np.linalg.norm(
                                        residual_projection.get(
                                            "left_contact_residual_m", (0.0, 0.0, 0.0)
                                        )
                                    )
                                ),
                                "right_residual_norm_m": float(
                                    np.linalg.norm(
                                        residual_projection.get(
                                            "right_contact_residual_m", (0.0, 0.0, 0.0)
                                        )
                                    )
                                ),
                                "projection": residual_projection,
                            }
                        )
            elif args.policy_mode in {
                "base_arm_residual",
                "base_dual_arm_residual",
                "pi05_residual",
                "pi05_absolute",
            }:
                latest_policy_left_arm_qpos = None
                latest_policy_dual_arm_qpos = None
                latest_policy_arm_stage = None
            executor_rejected_command = bool(
                args.policy_mode == "pi05_absolute"
                and arm_residual_telemetry["stage_authorized"]
                and not arm_residual_telemetry["ik_accepted"]
            )
            telemetry["executor_rejected_command"] = executor_rejected_command
            if executor_rejected_command:
                telemetry["absolute_motion_full_authority"] = False
                telemetry["absolute_full_authority"] = False
                telemetry["pure_vla_qualified_step"] = False
            trace_index = len(policy_trace)
            policy_trace.append(
                {
                    **telemetry,
                    "trace_index": trace_index,
                    "arm_residual": arm_residual_telemetry,
                    "observation_frame": recorded_frames,
                    "physics_step": recorded_physics_steps,
                    "actuation_mode": args.policy_mode,
                    "expert_command_at_observation": [
                        float(value) for value in action_vector
                    ],
                    "executor_command": {
                        "selected_cartesian_command": [
                            float(value) for value in latest_policy_action
                        ],
                        "base_velocity_xy_yaw": [
                            float(value) for value in latest_policy_action[:3]
                        ],
                        "arm_joint_position_target": (
                            [
                                float(value)
                                for value in latest_policy_dual_arm_qpos
                            ]
                            if latest_policy_dual_arm_qpos is not None
                            else [
                                float(value)
                                for value in latest_policy_left_arm_qpos
                            ]
                            if latest_policy_left_arm_qpos is not None
                            else None
                        ),
                        "arm_projection_accepted": bool(
                            arm_residual_telemetry["ik_accepted"]
                        ),
                        "tool_commands": [
                            float(latest_policy_action[10]),
                            float(latest_policy_action[18]),
                        ],
                        "applies_from_next_control_interval": True,
                    },
                }
            )
            pending_policy_trace_index = trace_index
        if writer is not None:
            writer.add_frame(
                MobileBimanualFrame(
                    frame_index=recorded_frames,
                    timestamp_seconds=recorded_frames / 30.0,
                    stage=stage,
                    state=tuple(float(value) for value in state_vector),
                    action=tuple(float(value) for value in action_vector),
                    privileged_state=tuple(float(value) for value in parcel_pose),
                    task=task_text,
                    rgb=np.asarray(rgb)[..., :3],
                    depth=np.asarray(depth, dtype=np.float32),
                    wrist_rgb=(
                        np.asarray(wrist_rgb)[..., :3]
                        if wrist_rgb is not None
                        else None
                    ),
                    wrist_depth=(
                        np.asarray(wrist_depth, dtype=np.float32)
                        if wrist_depth is not None
                        else None
                    ),
                )
            )
        if pi05_writer is not None:
            if residual_context is None or latest_pi05_raw_residual_action is None:
                raise RuntimeError("PI0.5 replay recording requires an active residual output")
            pi05_writer.add_frame(
                PI05AutonomousResidualFrame(
                    frame_index=recorded_frames,
                    timestamp_seconds=recorded_frames / 30.0,
                    stage=stage,
                    state=encode_pi05_state(state_vector, residual_context),
                    raw_residual_action=latest_pi05_raw_residual_action,
                    privileged_state=tuple(float(value) for value in parcel_pose),
                    task=latest_pi05_policy_task,
                    inference_performed=bool(
                        policy_selected_this_frame
                        and current_policy_telemetry is not None
                        and current_policy_telemetry["inference_performed"]
                    ),
                    inference_call_index=latest_pi05_inference_call_index,
                    chunk_step_index=latest_pi05_chunk_step_index,
                    rgb=np.asarray(rgb)[..., :3],
                    depth=np.asarray(depth, dtype=np.float32),
                    wrist_rgb=(
                        np.asarray(wrist_rgb)[..., :3]
                        if wrist_rgb is not None
                        else None
                    ),
                    wrist_depth=(
                        np.asarray(wrist_depth, dtype=np.float32)
                        if wrist_depth is not None
                        else None
                    ),
                )
            )
        if absolute_writer is not None:
            if (
                residual_context is None
                or latest_pi05_raw_absolute_action is None
                or latest_policy_action is None
            ):
                raise RuntimeError(
                    "PI0.5 absolute replay requires an active 23-D policy output"
                )
            absolute_writer.add_frame(
                PI05AutonomousAbsoluteFrame(
                    frame_index=recorded_frames,
                    timestamp_seconds=recorded_frames / 30.0,
                    stage=stage,
                    state=encode_pi05_absolute_state(
                        state_vector, residual_context
                    ),
                    absolute_action_target=(
                        *tuple(float(value) for value in latest_policy_action),
                        *latest_pi05_raw_absolute_action[19:23],
                    ),
                    privileged_state=tuple(float(value) for value in parcel_pose),
                    task=latest_pi05_policy_task,
                    inference_performed=bool(
                        policy_selected_this_frame
                        and current_policy_telemetry is not None
                        and current_policy_telemetry["inference_performed"]
                    ),
                    inference_call_index=latest_pi05_inference_call_index,
                    chunk_step_index=latest_pi05_chunk_step_index,
                    rgb=np.asarray(rgb)[..., :3],
                    depth=np.asarray(depth, dtype=np.float32),
                    wrist_rgb=(
                        np.asarray(wrist_rgb)[..., :3]
                        if wrist_rgb is not None
                        else None
                    ),
                    wrist_depth=(
                        np.asarray(wrist_depth, dtype=np.float32)
                        if wrist_depth is not None
                        else None
                    ),
                )
            )
        recorded_frames += 1

    pregrasp_start_arm_qpos = np.asarray(_flat(robot.get_qpos()))[arm_dofs]
    pregrasp_target_arm_qpos = pregrasp_values[arm_dofs]
    pregrasp_physics_steps = 1200 if args.cooperative_cradle else 480
    if (
        args.policy_mode == "pi05_absolute"
        and scene_stable
        and not grasp_mode_route_mismatch_before_actuation
    ):
        record_control_frame(
            stage="pregrasp",
            base_action=np.zeros(3),
            left_position=pregrasp_targets[0],
            left_quaternion=pregrasp_quaternions[0],
            left_tool_command=-1.0,
            right_position=pregrasp_targets[1],
            right_quaternion=pregrasp_quaternions[1],
            right_tool_command=1.0,
            force_policy_sample=True,
        )
    pregrasp_iterations = pregrasp_physics_steps if scene_stable else 1
    if grasp_mode_route_mismatch_before_actuation:
        pregrasp_iterations = 0
    for pregrasp_step in range(1, pregrasp_iterations + 1):
        progress = min(pregrasp_step / 480.0, 1.0)
        smooth_progress = progress * progress * (3.0 - 2.0 * progress)
        if args.cooperative_cradle or args.grasp_mode == "top_suction":
            pregrasp_command = pregrasp_start_arm_qpos + smooth_progress * (
                pregrasp_target_arm_qpos - pregrasp_start_arm_qpos
            )
        else:
            pregrasp_command = pregrasp_target_arm_qpos
        pregrasp_base_action = np.zeros(3)
        if args.policy_mode in {"pi05_residual", "pi05_absolute"} and (
            latest_policy_stage == "pregrasp"
        ):
            pregrasp_base_action = np.asarray(latest_policy_action[:3])
            policy_applied_physics_steps += 1
            if (
                latest_policy_dual_arm_qpos is not None
                and latest_policy_arm_stage == "pregrasp"
            ):
                pregrasp_command = (
                    latest_policy_dual_arm_qpos
                    if args.policy_mode == "pi05_absolute"
                    else pregrasp_start_arm_qpos
                    + smooth_progress
                    * (latest_policy_dual_arm_qpos - pregrasp_start_arm_qpos)
                )
                arm_policy_applied_physics_steps += 1
            elif (
                latest_policy_left_arm_qpos is not None
                and latest_policy_arm_stage == "pregrasp"
            ):
                pregrasp_command = pregrasp_command.copy()
                pregrasp_command[:7] = pregrasp_start_arm_qpos[:7] + smooth_progress * (
                    latest_policy_left_arm_qpos - pregrasp_start_arm_qpos[:7]
                )
                arm_policy_applied_physics_steps += 1
        robot.control_dofs_velocity(pregrasp_base_action, base_dofs)
        robot.control_dofs_position(pregrasp_command, arm_dofs)
        scene.step()
        record_control_frame(
            stage="pregrasp",
            base_action=pregrasp_base_action,
            left_position=pregrasp_targets[0],
            left_quaternion=pregrasp_quaternions[0],
            left_tool_command=-1.0,
            right_position=pregrasp_targets[1],
            right_quaternion=pregrasp_quaternions[1],
            right_tool_command=1.0,
        )
    pregrasp_tracking_error_m = (
        math.dist(_flat(left_hand.get_pos()), pregrasp_targets[0].tolist()),
        math.dist(_flat(right_hand.get_pos()), pregrasp_targets[1].tolist()),
    )
    pregrasp_final_positions = (
        _flat(left_hand.get_pos()),
        _flat(right_hand.get_pos()),
    )

    contact_quaternion = (
        pregrasp_quaternions[0]
        if args.grasp_mode in {"top_suction", "side_suction"}
        else np.asarray(_flat(hand.get_quat()))
    )
    approach_axis = _normalized(
        rotate_vector(tuple(contact_quaternion.tolist()), (0.0, 0.0, 1.0)), np
    )
    current_parcel_position = np.asarray(_flat(parcel.get_pos()))
    current_half_extent_on_axis = _shape_ray_extent(
        approach_axis,
        parcel_size,
        args.parcel_shape,
        args.parcel_orientation,
        args.parcel_yaw_rad,
        np,
    )
    contact_penetration_m = (
        cooperative_contact_penetration_m
        if args.cooperative_cradle
        else 0.0005 + args.recovery_contact_penetration_delta_m
    )
    contact_hand_target = (
        current_parcel_position
        + left_contact_lateral_offset
        - approach_axis
        * (cup_tip_offset_m + current_half_extent_on_axis - contact_penetration_m)
    )
    if args.grasp_mode == "top_suction":
        contact_hand_target -= top_active_cup_offset_world
    elif args.grasp_mode == "side_suction":
        contact_hand_target -= side_active_cup_offset_world
    precontact_target = contact_hand_target - approach_axis * 0.040

    suction = MobileTriSuctionController(
        robot=robot,
        hand=hand,
        parcel=parcel,
        torch=torch,
        np=np,
        min_sealed_cups=args.minimum_sealed_cups,
        force_limit_n=30.0,
    )
    parcel_initial_z = _flat(parcel.get_pos())[2]
    contact_start = np.asarray(_flat(hand.get_pos()))
    approach_trace = []
    stable_seal_steps = 0
    required_stable_seal_steps = 1 if args.grasp_mode == "top_suction" else 12
    max_base_speed_m_s = 0.0
    top_approach_ik_attempts = 0
    top_approach_ik_accepts = 0
    top_approach_ik_rejections = 0
    top_approach_arm_command = np.asarray(_flat(robot.get_qpos()))[left_arm_dofs]
    top_contact_hold = False
    top_quasistatic_steps = 0
    top_quasistatic_wait_steps = 0
    top_quasistatic_max_hand_speed_m_s = 0.0
    approach_step_limit = 3600 if args.grasp_mode == "top_suction" else 2400
    if (
        args.policy_mode == "pi05_absolute"
        and scene_stable
        and not grasp_mode_route_mismatch_before_actuation
    ):
        record_control_frame(
            stage="grasp_approach",
            base_action=np.zeros(3),
            left_position=contact_hand_target,
            left_quaternion=contact_quaternion,
            left_tool_command=-1.0,
            right_position=pregrasp_targets[1],
            right_quaternion=pregrasp_quaternions[1],
            right_tool_command=1.0,
            suction_controller=suction,
            force_policy_sample=True,
        )
    for approach_step in range(
        approach_step_limit
        if scene_stable and not grasp_mode_route_mismatch_before_actuation
        else 0
    ):
        current_position = np.asarray(_flat(hand.get_pos()))
        current_hand_speed_m_s = float(np.linalg.norm(_flat(hand.get_vel())))
        current_quaternion = tuple(_flat(hand.get_quat()))
        current_axis = _normalized(
            rotate_vector(current_quaternion, (0.0, 0.0, 1.0)), np
        )
        dynamic_contact_surface = (
            np.asarray(_flat(parcel.get_pos()))
            + left_contact_lateral_offset
            - approach_axis
            * (current_half_extent_on_axis - contact_penetration_m)
        )
        dynamic_contact_target = (
            dynamic_contact_surface
            - top_active_cup_offset_world
            - approach_axis * cup_tip_offset_m
            if args.grasp_mode == "top_suction"
            else dynamic_contact_surface
            - side_active_cup_offset_world
            - approach_axis * cup_tip_offset_m
            if args.grasp_mode == "side_suction"
            else dynamic_contact_surface - approach_axis * cup_tip_offset_m
        )
        if (
            args.policy_mode == "pi05_residual"
            and latest_policy_stage == "grasp_approach"
        ):
            dynamic_contact_target = (
                dynamic_contact_target + latest_pi05_left_residual_m
            )
            dynamic_contact_surface = (
                dynamic_contact_surface + latest_pi05_left_residual_m
            )
            arm_policy_applied_physics_steps += 1
        current_tcp = current_position + current_axis * cup_tip_offset_m
        top_contact_target_distance_m = float(
            np.linalg.norm(dynamic_contact_target - current_position)
        )
        if args.cooperative_cradle:
            horizontal_error = dynamic_contact_surface[:2] - current_tcp[:2]
            if abs(float(horizontal_error[0])) > 0.010:
                horizontal_error[1] = 0.0
            else:
                horizontal_error[0] = 0.0
        elif args.grasp_mode == "top_suction":
            horizontal_error = (
                dynamic_contact_surface[:2]
                - top_active_cup_offset_world[:2]
                - current_tcp[:2]
            )
        else:
            horizontal_error = dynamic_contact_target[:2] - current_position[:2]
        base_velocity_xy = horizontal_error * 2.0 * args.recovery_approach_speed_scale
        base_speed = float(np.linalg.norm(base_velocity_xy))
        approach_speed_limit_m_s = (
            0.12 if args.grasp_mode == "top_suction" else 0.05
        ) * args.recovery_approach_speed_scale
        if base_speed > approach_speed_limit_m_s:
            base_velocity_xy *= approach_speed_limit_m_s / base_speed
            base_speed = approach_speed_limit_m_s
        expert_base_velocity_xy = base_velocity_xy.copy()
        if (
            args.policy_mode == "pi05_residual"
            and latest_policy_action is not None
            and latest_policy_stage == "grasp_approach"
        ):
            base_velocity_xy = (
                expert_base_velocity_xy + latest_pi05_base_residual[:2]
            )
            base_speed = float(np.linalg.norm(base_velocity_xy))
            if base_speed > approach_speed_limit_m_s:
                base_velocity_xy *= approach_speed_limit_m_s / base_speed
                base_speed = approach_speed_limit_m_s
            policy_applied_physics_steps += 1
        elif (
            args.policy_mode
            in {
                "base_residual",
                "base_arm_residual",
                "base_dual_arm_residual",
                "pi05_absolute",
            }
            and latest_policy_action is not None
            and latest_policy_stage == "grasp_approach"
        ):
            base_velocity_xy = np.asarray(latest_policy_action[:2], dtype=np.float64)
            base_speed = float(np.linalg.norm(base_velocity_xy))
            policy_applied_physics_steps += 1
        if args.grasp_mode == "top_suction" and float(
            np.linalg.norm(horizontal_error)
        ) <= 0.006:
            base_velocity_xy = np.zeros(2)
            base_speed = 0.0
            quasistatic_contact = top_contact_target_distance_m <= 0.015
            if quasistatic_contact:
                top_quasistatic_steps += 1
                top_quasistatic_max_hand_speed_m_s = max(
                    top_quasistatic_max_hand_speed_m_s,
                    current_hand_speed_m_s,
                )
            can_advance = not quasistatic_contact or current_hand_speed_m_s <= 0.015
            if approach_step % 8 == 0 and not top_contact_hold and can_advance:
                top_approach_ik_attempts += 1
                translation_error = dynamic_contact_target - current_position
                translation_norm = float(np.linalg.norm(translation_error))
                if translation_norm > 0.0:
                    maximum_translation_m = 0.0001 if quasistatic_contact else 0.00025
                    translation_error *= (
                        min(maximum_translation_m, translation_norm) / translation_norm
                    )
                target_hand_position = current_position + translation_error
                try:
                    approach_solution = robot.inverse_kinematics(
                        link=hand,
                        pos=target_hand_position,
                        quat=contact_quaternion,
                        init_qpos=np.asarray(_flat(robot.get_qpos())),
                        respect_joint_limit=True,
                        max_samples=4,
                        max_solver_iters=50,
                        damping=0.03,
                        max_step_size=0.08,
                        dofs_idx_local=left_arm_dofs,
                    )
                    candidate = np.asarray(_flat(approach_solution))[left_arm_dofs]
                    if not np.isfinite(candidate).all():
                        raise ValueError("top-approach IK returned non-finite values")
                except (RuntimeError, ValueError):
                    top_approach_ik_rejections += 1
                else:
                    top_approach_arm_command = candidate
                    top_approach_ik_accepts += 1
            elif approach_step % 8 == 0 and quasistatic_contact and not top_contact_hold:
                top_quasistatic_wait_steps += 1
        robot.control_dofs_velocity(
            np.asarray((base_velocity_xy[0], base_velocity_xy[1], 0.0)),
            base_dofs,
        )
        if (
            args.policy_mode in {"pi05_residual", "pi05_absolute"}
            and latest_policy_dual_arm_qpos is not None
            and latest_policy_arm_stage == "grasp_approach"
        ):
            robot.control_dofs_position(latest_policy_dual_arm_qpos, arm_dofs)
            arm_policy_applied_physics_steps += 1
        elif (
            args.policy_mode in {"pi05_residual", "pi05_absolute"}
            and latest_policy_left_arm_qpos is not None
            and latest_policy_arm_stage == "grasp_approach"
        ):
            robot.control_dofs_position(latest_policy_left_arm_qpos, left_arm_dofs)
            robot.control_dofs_position(pregrasp_values[right_arm_dofs], right_arm_dofs)
            arm_policy_applied_physics_steps += 1
        elif args.grasp_mode == "top_suction":
            robot.control_dofs_position(top_approach_arm_command, left_arm_dofs)
            robot.control_dofs_position(pregrasp_values[right_arm_dofs], right_arm_dofs)
        else:
            robot.control_dofs_position(pregrasp_values[arm_dofs], arm_dofs)
        scene.step()
        max_base_speed_m_s = max(max_base_speed_m_s, base_speed)
        sealed, force_n = suction.contact_snapshot()
        if sealed >= args.minimum_sealed_cups and force_n < 35.0:
            stable_seal_steps += 1
            if args.grasp_mode == "top_suction" and not top_contact_hold:
                top_contact_hold = True
                top_approach_arm_command = np.asarray(_flat(robot.get_qpos()))[
                    left_arm_dofs
                ]
        else:
            stable_seal_steps = 0
        record_control_frame(
            stage="grasp_approach",
            base_action=np.asarray((base_velocity_xy[0], base_velocity_xy[1], 0.0)),
            left_position=dynamic_contact_target,
            left_quaternion=current_quaternion,
            left_tool_command=-1.0,
            right_position=pregrasp_targets[1],
            right_quaternion=pregrasp_quaternions[1],
            right_tool_command=1.0,
            suction_controller=suction,
            policy_expert_base_action=np.asarray(
                (expert_base_velocity_xy[0], expert_base_velocity_xy[1], 0.0)
            ),
        )
        actual_hand_position = _flat(hand.get_pos())
        actual_tcp = np.asarray(actual_hand_position) + current_axis * cup_tip_offset_m
        distance_to_contact_m = float(
            np.linalg.norm(
                actual_tcp
                - (dynamic_contact_surface - top_active_cup_offset_world)
                if args.grasp_mode == "top_suction"
                else actual_tcp[:2] - dynamic_contact_surface[:2]
                if args.cooperative_cradle
                else np.asarray(actual_hand_position[:2]) - dynamic_contact_target[:2]
            )
        )
        axis_alignment = float(np.dot(current_axis, approach_axis))
        if approach_step % 12 == 0 or sealed or force_n >= 35.0:
            approach_trace.append(
                {
                    "physics_step": approach_step,
                    "distance_to_contact_m": distance_to_contact_m,
                    "axis_alignment": axis_alignment,
                    "dynamic_contact_target_m": dynamic_contact_target.tolist(),
                    "actual_hand_position_m": actual_hand_position,
                    "actual_hand_quaternion_wxyz": _flat(hand.get_quat()),
                    "hand_speed_m_s": current_hand_speed_m_s,
                    "parcel_position_m": _flat(parcel.get_pos()),
                    "sealed_cups": sealed,
                    "stable_seal_steps": stable_seal_steps,
                    "contact_force_n": force_n,
                }
            )
        if stable_seal_steps >= required_stable_seal_steps or force_n >= 35.0:
            break
        minimum_axis_alignment = math.cos(
            0.50 if args.grasp_mode == "top_suction" else 0.25
        )
        if axis_alignment < minimum_axis_alignment:
            break
        if math.dist(_flat(parcel.get_pos()), settled_parcel_position.tolist()) >= 0.030:
            break
    robot.control_dofs_velocity(np.zeros(3), base_dofs)

    latched = (
        suction.try_latch()
        if stable_seal_steps >= required_stable_seal_steps
        else False
    )
    if latched and args.cooperative_cradle and cradle_monitor is not None:
        engage_start_right_hand = np.asarray(_flat(right_hand.get_pos()))
        engage_left_qpos = np.asarray(_flat(robot.get_qpos()))[left_arm_dofs]
        engage_right_command = np.asarray(_flat(robot.get_qpos()))[right_arm_dofs]
        consecutive_cradle_contact_steps = 0
        for engage_step in range(1, 241):
            cradle_engage_steps += 1
            engage_progress = min(engage_step / 120.0, 1.0)
            if (engage_step - 1) % 8 == 0:
                engage_target = (
                    engage_start_right_hand
                    + np.asarray(right_tool_axis)
                    * (
                        (0.015 + args.recovery_cradle_engagement_delta_m)
                        * engage_progress
                    )
                )
                engage_solution = robot.inverse_kinematics(
                    link=right_hand,
                    pos=engage_target,
                    quat=np.asarray(_flat(right_hand.get_quat())),
                    init_qpos=np.asarray(_flat(robot.get_qpos())),
                    respect_joint_limit=True,
                    max_samples=4,
                    max_solver_iters=40,
                    damping=0.03,
                    max_step_size=0.08,
                    dofs_idx_local=right_arm_dofs,
                )
                candidate = np.asarray(_flat(engage_solution))[right_arm_dofs]
                if np.isfinite(candidate).all():
                    engage_right_command = candidate
            robot.control_dofs_position(engage_left_qpos, left_arm_dofs)
            robot.control_dofs_position(engage_right_command, right_arm_dofs)
            suction.update()
            scene.step()
            cradle_contacts, cradle_force_n = cradle_monitor.snapshot()
            if cradle_contacts > 0:
                cradle_engage_contact_steps += 1
                consecutive_cradle_contact_steps += 1
            else:
                consecutive_cradle_contact_steps = 0
            if (
                suction.attachment is None
                or cradle_force_n >= 35.0
                or consecutive_cradle_contact_steps >= 24
            ):
                break
        cradle_engaged_before_lift = bool(
            suction.attachment is not None
            and consecutive_cradle_contact_steps >= 24
            and cradle_monitor.max_contact_force_n < 35.0
        )
    lift_trace = []
    cradle_lift_contact_memory_offset_m = 0.0
    cradle_lift_contact_memory_active_steps = 0
    cradle_lift_contact_memory_max_offset_m = 0.0
    lift_target_delta_m = 0.12 + min(
        0.02, max(0.0, args.parcel_mass_kg - 0.40) * 0.08
    ) + args.recovery_lift_height_delta_m
    if latched:
        start_hand = np.asarray(_flat(hand.get_pos()))
        start_right_hand = np.asarray(_flat(right_hand.get_pos()))
        start_qpos = np.asarray(_flat(robot.get_qpos()))
        controlled_arm_dofs = arm_dofs if args.cooperative_cradle else left_arm_dofs
        start_arm_qpos = start_qpos[controlled_arm_dofs]
        left_lift_contact_residual = np.asarray(args.recovery_left_lift_offset_m)
        right_lift_contact_residual = np.asarray(args.recovery_right_lift_offset_m)
        lift_target = (
            start_hand
            + np.asarray((0.0, 0.0, lift_target_delta_m))
            + left_lift_contact_residual
        )
        right_lift_target = start_right_hand + np.asarray(
            (0.0, 0.0, lift_target_delta_m)
        ) + right_lift_contact_residual
        lift_quaternion = np.asarray(_flat(hand.get_quat()))
        right_lift_quaternion = np.asarray(_flat(right_hand.get_quat()))
        top_lift_waypoints = [start_arm_qpos.copy()]
        top_lift_waypoint_errors = []
        if args.grasp_mode == "top_suction":
            waypoint_seed = start_qpos.copy()
            top_lift_segment_count = max(
                1, int(math.ceil(lift_target_delta_m / 0.005))
            )
            for waypoint_index in range(1, top_lift_segment_count + 1):
                waypoint_position = start_hand + np.asarray(
                    (
                        0.0,
                        0.0,
                        lift_target_delta_m
                        * waypoint_index
                        / top_lift_segment_count,
                    )
                )
                waypoint_solution, waypoint_error = robot.inverse_kinematics(
                    link=hand,
                    pos=waypoint_position,
                    quat=lift_quaternion,
                    init_qpos=waypoint_seed,
                    respect_joint_limit=True,
                    max_samples=1,
                    max_solver_iters=80,
                    damping=0.02,
                    max_step_size=0.04,
                    dofs_idx_local=left_arm_dofs,
                    return_error=True,
                )
                error_values = np.asarray(_flat(waypoint_error))
                position_error_m = float(np.linalg.norm(error_values[:3]))
                rotation_error_rad = float(np.linalg.norm(error_values[3:6]))
                candidate = np.asarray(_flat(waypoint_solution))[left_arm_dofs]
                joint_delta = candidate - top_lift_waypoints[-1]
                max_abs_joint_delta_rad = float(np.max(np.abs(joint_delta)))
                joint_delta_l2_rad = float(np.linalg.norm(joint_delta))
                accepted = bool(
                    np.isfinite(candidate).all()
                    and position_error_m <= 0.008
                    and rotation_error_rad <= 0.20
                    and max_abs_joint_delta_rad <= 0.15
                    and joint_delta_l2_rad <= 0.30
                )
                top_lift_waypoint_errors.append(
                    {
                        "index": waypoint_index,
                        "target_height_delta_m": float(
                            lift_target_delta_m
                            * waypoint_index
                            / top_lift_segment_count
                        ),
                        "position_error_m": position_error_m,
                        "rotation_error_rad": rotation_error_rad,
                        "max_abs_joint_delta_rad": max_abs_joint_delta_rad,
                        "joint_delta_l2_rad": joint_delta_l2_rad,
                        "accepted": accepted,
                    }
                )
                if not accepted:
                    break
                top_lift_waypoints.append(candidate)
                waypoint_seed = waypoint_seed.copy()
                waypoint_seed[left_arm_dofs] = candidate
            target_arm_qpos = top_lift_waypoints[-1]
        elif not args.cooperative_cradle:
            solution = robot.inverse_kinematics(
                link=hand,
                pos=lift_target,
                quat=lift_quaternion,
                init_qpos=start_qpos,
                respect_joint_limit=True,
                max_samples=8,
                max_solver_iters=80,
                damping=0.02,
                max_step_size=0.15,
                dofs_idx_local=left_arm_dofs,
            )
            target_arm_qpos = np.asarray(_flat(solution))[controlled_arm_dofs]
        else:
            target_arm_qpos = start_arm_qpos.copy()
        if args.policy_mode == "pi05_absolute":
            record_control_frame(
                stage="lift",
                base_action=np.zeros(3),
                left_position=lift_target,
                left_quaternion=lift_quaternion,
                left_tool_command=1.0,
                right_position=right_lift_target,
                right_quaternion=right_lift_quaternion,
                right_tool_command=1.0,
                suction_controller=suction,
                force_policy_sample=True,
            )
        for physics_step in range(1, 721):
            progress = min(
                physics_step / (480.0 / args.recovery_vertical_speed_scale), 1.0
            )
            smooth_progress = progress * progress * (3.0 - 2.0 * progress)
            if args.cooperative_cradle and (physics_step - 1) % 8 == 0:
                cooperative_lift_ik_attempts += 1
                current_qpos = np.asarray(_flat(robot.get_qpos()))
                desired_offset = np.asarray(
                    (0.0, 0.0, lift_target_delta_m * smooth_progress)
                )
                try:
                    left_incremental_solution = robot.inverse_kinematics(
                        link=hand,
                        pos=start_hand
                        + desired_offset
                        + left_lift_contact_residual * smooth_progress,
                        quat=lift_quaternion,
                        init_qpos=current_qpos,
                        respect_joint_limit=True,
                        max_samples=4,
                        max_solver_iters=40,
                        damping=0.03,
                        max_step_size=0.08,
                        dofs_idx_local=left_arm_dofs,
                    )
                    right_incremental_solution = robot.inverse_kinematics(
                        link=right_hand,
                        pos=start_right_hand
                        + desired_offset
                        + right_lift_contact_residual * smooth_progress
                        + np.asarray(right_tool_axis)
                        * cradle_lift_contact_memory_offset_m,
                        quat=right_lift_quaternion,
                        init_qpos=current_qpos,
                        respect_joint_limit=True,
                        max_samples=4,
                        max_solver_iters=40,
                        damping=0.03,
                        max_step_size=0.08,
                        dofs_idx_local=right_arm_dofs,
                    )
                    candidate_full_qpos = current_qpos.copy()
                    candidate_full_qpos[left_arm_dofs] = np.asarray(
                        _flat(left_incremental_solution)
                    )[left_arm_dofs]
                    candidate_full_qpos[right_arm_dofs] = np.asarray(
                        _flat(right_incremental_solution)
                    )[right_arm_dofs]
                    candidate_qpos = candidate_full_qpos[arm_dofs]
                    if not np.isfinite(candidate_qpos).all():
                        raise ValueError("incremental dual-arm IK returned non-finite values")
                except (RuntimeError, ValueError):
                    cooperative_lift_ik_rejections += 1
                else:
                    target_arm_qpos = candidate_qpos
                    cooperative_lift_ik_accepts += 1
            lift_base_action = np.zeros(3)
            if (
                args.policy_mode == "pi05_absolute"
                and latest_policy_action is not None
                and latest_policy_stage == "lift"
            ):
                lift_base_action = np.asarray(latest_policy_action[:3])
                policy_applied_physics_steps += 1
            robot.control_dofs_velocity(lift_base_action, base_dofs)
            if (
                args.policy_mode == "pi05_absolute"
                and latest_policy_dual_arm_qpos is not None
                and latest_policy_arm_stage == "lift"
            ):
                robot.control_dofs_position(latest_policy_dual_arm_qpos, arm_dofs)
                arm_policy_applied_physics_steps += 1
            elif args.grasp_mode == "top_suction":
                segment_count = len(top_lift_waypoints) - 1
                if segment_count > 0:
                    waypoint_progress = smooth_progress * segment_count
                    lower = min(int(waypoint_progress), segment_count - 1)
                    blend = min(1.0, waypoint_progress - lower)
                    command = top_lift_waypoints[lower] + blend * (
                        top_lift_waypoints[lower + 1] - top_lift_waypoints[lower]
                    )
                else:
                    command = top_lift_waypoints[0]
                if (
                    args.policy_mode == "pi05_residual"
                    and latest_policy_arm_stage == "lift"
                ):
                    command = command + latest_pi05_left_arm_delta_qpos
                    arm_policy_applied_physics_steps += 1
                robot.control_dofs_position(command, left_arm_dofs)
            else:
                command = (
                    target_arm_qpos
                    if args.cooperative_cradle
                    else start_arm_qpos
                    + smooth_progress * (target_arm_qpos - start_arm_qpos)
                )
                if (
                    args.policy_mode == "pi05_residual"
                    and latest_policy_arm_stage == "lift"
                ):
                    command = command + (
                        latest_pi05_dual_arm_delta_qpos
                        if args.cooperative_cradle
                        else latest_pi05_left_arm_delta_qpos
                    )
                    arm_policy_applied_physics_steps += 1
                robot.control_dofs_position(command, controlled_arm_dofs)
            suction.update()
            scene.step()
            if cradle_monitor is not None:
                cradle_lift_steps += 1
                cradle_contacts, cradle_force_n = cradle_monitor.snapshot()
                cradle_lift_contact_steps += int(cradle_contacts > 0)
                if args.cradle_contact_memory:
                    cradle_lift_contact_memory_offset_m = (
                        update_cradle_contact_memory_offset(
                            cradle_lift_contact_memory_offset_m,
                            contact_geoms=cradle_contacts,
                            contact_force_n=cradle_force_n,
                        )
                    )
                    cradle_lift_contact_memory_active_steps += int(
                        cradle_lift_contact_memory_offset_m > 0.0
                    )
                    cradle_lift_contact_memory_max_offset_m = max(
                        cradle_lift_contact_memory_max_offset_m,
                        cradle_lift_contact_memory_offset_m,
                    )
            record_control_frame(
                stage="lift",
                base_action=lift_base_action,
                left_position=start_hand
                + np.asarray((0.0, 0.0, lift_target_delta_m * smooth_progress))
                + left_lift_contact_residual * smooth_progress,
                left_quaternion=lift_quaternion,
                left_tool_command=1.0,
                right_position=start_right_hand
                + np.asarray((0.0, 0.0, lift_target_delta_m * smooth_progress))
                + right_lift_contact_residual * smooth_progress,
                right_quaternion=right_lift_quaternion,
                right_tool_command=1.0,
                suction_controller=suction,
            )
            if physics_step % 40 == 0 or suction.attachment is None:
                lift_trace.append(
                    {
                        "physics_step": physics_step,
                        "target_hand_position_m": lift_target.tolist(),
                        "actual_hand_position_m": _flat(hand.get_pos()),
                        "actual_right_hand_position_m": _flat(right_hand.get_pos()),
                        "parcel_position_m": _flat(parcel.get_pos()),
                        "cradle": (
                            cradle_monitor.summary()
                            if cradle_monitor is not None
                            else None
                        ),
                        **suction.summary(),
                    }
                )
            if suction.attachment is None:
                break

    lift_parcel_z = _flat(parcel.get_pos())[2]
    lift_delta = lift_parcel_z - parcel_initial_z
    lift_success = bool(
        latched
        and suction.attachment is not None
        and lift_delta >= 0.08
        and suction.max_force_n < 35.0
        and suction.max_contact_force_n < 35.0
        and (
            not args.cooperative_cradle
            or (
                cradle_monitor is not None
                and cradle_engaged_before_lift
                and cradle_lift_steps > 0
                and cradle_lift_contact_steps / cradle_lift_steps >= 0.50
                and cradle_monitor.max_contact_force_n < 35.0
            )
        )
    )
    transport_trace = []
    transport_success = False
    transport_deadline_handoff = False
    transport_deadline_handoff_step = None
    transport_deadline_handoff_distance_m = None
    transport_deadline_handoff_remaining_s = None
    transport_deadline_handoff_physics_steps = 0
    if lift_success:
        transport_start_base = np.asarray(_flat(robot.get_qpos()))[base_dofs]
        transport_target_base = transport_start_base + transport_delta
        transport_arm_anchor_position = np.asarray(_flat(hand.get_pos()))
        transport_arm_anchor_quaternion = np.asarray(_flat(hand.get_quat()))
        transport_right_arm_anchor_position = np.asarray(_flat(right_hand.get_pos()))
        transport_right_arm_anchor_quaternion = np.asarray(_flat(right_hand.get_quat()))
        transport_arm_anchor_base = transport_start_base.copy()
        if args.policy_mode == "pi05_absolute":
            record_control_frame(
                stage="transport",
                base_action=np.zeros(3),
                left_position=transport_arm_anchor_position,
                left_quaternion=transport_arm_anchor_quaternion,
                left_tool_command=1.0,
                right_position=transport_right_arm_anchor_position,
                right_quaternion=transport_right_arm_anchor_quaternion,
                right_tool_command=1.0,
                suction_controller=suction,
                policy_remaining_distance_m=float(
                    np.linalg.norm(transport_delta[:2])
                ),
                force_policy_sample=True,
            )
        for physics_step in range(1, 2401):
            current_base = np.asarray(_flat(robot.get_qpos()))[base_dofs]
            error_xy = transport_target_base[:2] - current_base[:2]
            distance_m = float(np.linalg.norm(error_xy))
            velocity_xy = error_xy * 2.0
            speed_m_s = float(np.linalg.norm(velocity_xy))
            if speed_m_s > 0.05:
                velocity_xy *= 0.05 / speed_m_s
                speed_m_s = 0.05
            expert_velocity_xy = velocity_xy.copy()
            expert_forward_speed_m_s = (
                float(np.dot(expert_velocity_xy, error_xy / distance_m))
                if distance_m > 1e-9
                else 0.0
            )
            if (
                args.policy_mode
                in {
                    "base_residual",
                    "base_arm_residual",
                    "base_dual_arm_residual",
                    "pi05_residual",
                }
                and latest_policy_action is not None
                and latest_policy_stage == "transport"
            ):
                remaining_time_s = (2401 - physics_step) / 240.0
                if args.policy_mode == "pi05_absolute":
                    velocity_xy = np.asarray(
                        latest_policy_action[:2], dtype=np.float64
                    )
                    policy_applied_physics_steps += 1
                else:
                    if not transport_deadline_handoff:
                        transport_deadline_handoff = transport_deadline_requires_expert(
                            distance_m=distance_m,
                            remaining_time_s=remaining_time_s,
                            expert_forward_speed_m_s=expert_forward_speed_m_s,
                            minimum_capacity_ratio=transport_capacity_ratio,
                        )
                        if transport_deadline_handoff:
                            transport_deadline_handoff_step = physics_step
                            transport_deadline_handoff_distance_m = distance_m
                            transport_deadline_handoff_remaining_s = remaining_time_s
                if args.policy_mode != "pi05_absolute" and transport_deadline_handoff:
                    velocity_xy = expert_velocity_xy
                    transport_deadline_handoff_physics_steps += 1
                elif args.policy_mode == "pi05_residual":
                    velocity_xy = expert_velocity_xy + latest_pi05_base_residual[:2]
                    residual_speed_m_s = float(np.linalg.norm(velocity_xy))
                    if residual_speed_m_s > 0.05:
                        velocity_xy *= 0.05 / residual_speed_m_s
                    policy_applied_physics_steps += 1
                elif args.policy_mode != "pi05_absolute":
                    velocity_xy = np.asarray(
                        latest_policy_action[:2], dtype=np.float64
                    )
                    policy_applied_physics_steps += 1
                speed_m_s = float(np.linalg.norm(velocity_xy))
            robot.control_dofs_velocity(
                np.asarray((velocity_xy[0], velocity_xy[1], 0.0)), base_dofs
            )
            if (
                args.policy_mode
                in {"base_dual_arm_residual", "pi05_residual", "pi05_absolute"}
                and latest_policy_dual_arm_qpos is not None
                and latest_policy_arm_stage == "transport"
            ):
                robot.control_dofs_position(latest_policy_dual_arm_qpos, arm_dofs)
                arm_policy_applied_physics_steps += 1
            elif args.cooperative_cradle:
                robot.control_dofs_position(target_arm_qpos, arm_dofs)
            else:
                arm_command = target_arm_qpos
                if (
                    args.policy_mode in {"base_arm_residual", "pi05_residual"}
                    and latest_policy_left_arm_qpos is not None
                    and latest_policy_arm_stage == "transport"
                ):
                    arm_command = latest_policy_left_arm_qpos
                    arm_policy_applied_physics_steps += 1
                robot.control_dofs_position(arm_command, left_arm_dofs)
            suction.update()
            scene.step()
            if cradle_monitor is not None:
                cradle_transport_steps += 1
                cradle_contacts, _ = cradle_monitor.snapshot()
                cradle_transport_contact_steps += int(cradle_contacts > 0)
            record_control_frame(
                stage="transport",
                base_action=np.asarray((velocity_xy[0], velocity_xy[1], 0.0)),
                left_position=_flat(hand.get_pos()),
                left_quaternion=_flat(hand.get_quat()),
                left_tool_command=1.0,
                right_position=_flat(right_hand.get_pos()),
                right_quaternion=_flat(right_hand.get_quat()),
                right_tool_command=1.0,
                suction_controller=suction,
                policy_expert_base_action=np.asarray(
                    (expert_velocity_xy[0], expert_velocity_xy[1], 0.0)
                ),
                policy_remaining_distance_m=distance_m,
            )
            if physics_step % 120 == 0 or suction.attachment is None or distance_m <= 0.005:
                transport_trace.append(
                    {
                        "physics_step": physics_step,
                        "base_position_xy_m": _flat(robot.get_qpos())[base_dofs[0] : base_dofs[1] + 1],
                        "distance_to_destination_m": distance_m,
                        "parcel_position_m": _flat(parcel.get_pos()),
                        "cradle": (
                            cradle_monitor.summary()
                            if cradle_monitor is not None
                            else None
                        ),
                        **suction.summary(),
                    }
                )
            if suction.attachment is None or distance_m <= 0.005:
                break
        robot.control_dofs_velocity(np.zeros(3), base_dofs)
        final_base = np.asarray(_flat(robot.get_qpos()))[base_dofs]
        transport_success = bool(
            suction.attachment is not None
            and float(np.linalg.norm(transport_target_base[:2] - final_base[:2])) <= 0.010
            and math.dist(
                _flat(parcel.get_pos())[:2],
                (initial_parcel_position + transport_delta)[:2].tolist(),
            )
            <= 0.040
            and (
                not args.require_vla_goal_verdict
                or latest_policy_goal_verified
            )
            and (
                not args.cooperative_cradle
                or (
                    cradle_transport_steps > 0
                    and cradle_transport_contact_steps / cradle_transport_steps >= 0.50
                )
            )
        )

    place_trace = []
    placed_before_release = False
    released = False
    consecutive_place_target_steps = 0
    place_completed_early = False
    place_force_safety_abort = False
    if transport_success:
        place_start_hand = np.asarray(_flat(hand.get_pos()))
        place_start_right_hand = np.asarray(_flat(right_hand.get_pos()))
        place_start_qpos = np.asarray(_flat(robot.get_qpos()))
        controlled_place_dofs = arm_dofs if args.cooperative_cradle else left_arm_dofs
        place_start_arm_qpos = place_start_qpos[controlled_place_dofs]
        place_drop_m = lift_target_delta_m - args.recovery_placement_clearance_m
        place_target = place_start_hand - np.asarray((0.0, 0.0, place_drop_m))
        right_place_target = place_start_right_hand - np.asarray(
            (0.0, 0.0, place_drop_m)
        )
        place_quaternion = np.asarray(_flat(hand.get_quat()))
        right_place_quaternion = np.asarray(_flat(right_hand.get_quat()))
        expected_placed_position = initial_parcel_position + transport_delta
        if not args.cooperative_cradle:
            place_solution = robot.inverse_kinematics(
                link=hand,
                pos=place_target,
                quat=place_quaternion,
                init_qpos=place_start_qpos,
                respect_joint_limit=True,
                max_samples=8,
                max_solver_iters=80,
                damping=0.02,
                max_step_size=0.15,
                dofs_idx_local=left_arm_dofs,
            )
            place_target_arm_qpos = np.asarray(_flat(place_solution))[
                controlled_place_dofs
            ]
        else:
            place_target_arm_qpos = place_start_arm_qpos.copy()
        if args.policy_mode == "pi05_absolute":
            record_control_frame(
                stage="place",
                base_action=np.zeros(3),
                left_position=place_target,
                left_quaternion=place_quaternion,
                left_tool_command=1.0,
                right_position=right_place_target,
                right_quaternion=right_place_quaternion,
                right_tool_command=1.0,
                suction_controller=suction,
                force_policy_sample=True,
            )
        for physics_step in range(1, 721):
            progress = min(
                physics_step / (480.0 / args.recovery_vertical_speed_scale), 1.0
            )
            smooth_progress = progress * progress * (3.0 - 2.0 * progress)
            if args.cooperative_cradle and (physics_step - 1) % 8 == 0:
                cooperative_place_ik_attempts += 1
                current_qpos = np.asarray(_flat(robot.get_qpos()))
                desired_offset = np.asarray(
                    (0.0, 0.0, -place_drop_m * smooth_progress)
                )
                try:
                    left_incremental_solution = robot.inverse_kinematics(
                        link=hand,
                        pos=place_start_hand + desired_offset,
                        quat=place_quaternion,
                        init_qpos=current_qpos,
                        respect_joint_limit=True,
                        max_samples=4,
                        max_solver_iters=40,
                        damping=0.03,
                        max_step_size=0.08,
                        dofs_idx_local=left_arm_dofs,
                    )
                    right_incremental_solution = robot.inverse_kinematics(
                        link=right_hand,
                        pos=place_start_right_hand + desired_offset,
                        quat=right_place_quaternion,
                        init_qpos=current_qpos,
                        respect_joint_limit=True,
                        max_samples=4,
                        max_solver_iters=40,
                        damping=0.03,
                        max_step_size=0.08,
                        dofs_idx_local=right_arm_dofs,
                    )
                    candidate_full_qpos = current_qpos.copy()
                    candidate_full_qpos[left_arm_dofs] = np.asarray(
                        _flat(left_incremental_solution)
                    )[left_arm_dofs]
                    candidate_full_qpos[right_arm_dofs] = np.asarray(
                        _flat(right_incremental_solution)
                    )[right_arm_dofs]
                    candidate_qpos = candidate_full_qpos[arm_dofs]
                    if not np.isfinite(candidate_qpos).all():
                        raise ValueError(
                            "incremental dual-arm place IK returned non-finite values"
                        )
                except (RuntimeError, ValueError):
                    cooperative_place_ik_rejections += 1
                else:
                    place_target_arm_qpos = candidate_qpos
                    cooperative_place_ik_accepts += 1
            command = (
                place_target_arm_qpos
                if args.cooperative_cradle
                else place_start_arm_qpos
                + smooth_progress * (place_target_arm_qpos - place_start_arm_qpos)
            )
            place_base_action = np.zeros(3)
            if (
                args.policy_mode == "pi05_absolute"
                and latest_policy_action is not None
                and latest_policy_stage == "place"
            ):
                place_base_action = np.asarray(latest_policy_action[:3])
                policy_applied_physics_steps += 1
            robot.control_dofs_velocity(place_base_action, base_dofs)
            if (
                args.policy_mode == "pi05_absolute"
                and latest_policy_dual_arm_qpos is not None
                and latest_policy_arm_stage == "place"
            ):
                robot.control_dofs_position(latest_policy_dual_arm_qpos, arm_dofs)
                arm_policy_applied_physics_steps += 1
            else:
                robot.control_dofs_position(command, controlled_place_dofs)
            suction.update()
            scene.step()
            if cradle_monitor is not None:
                cradle_place_steps += 1
                cradle_contacts, _ = cradle_monitor.snapshot()
                cradle_place_contact_steps += int(cradle_contacts > 0)
            place_force_safety_abort = bool(
                suction.max_force_n >= 35.0
                or suction.max_contact_force_n >= 35.0
                or (
                    cradle_monitor is not None
                    and cradle_monitor.max_contact_force_n >= 35.0
                )
            )
            consecutive_place_target_steps, place_completed_early = (
                update_release_gate_stability(
                    attached=suction.attachment is not None,
                    inside_release_gate=placement_within_release_gate(
                        _flat(parcel.get_pos()), expected_placed_position
                    ),
                    consecutive_steps=consecutive_place_target_steps,
                )
            )
            record_control_frame(
                stage="place",
                base_action=place_base_action,
                left_position=place_start_hand
                - np.asarray((0.0, 0.0, place_drop_m * smooth_progress)),
                left_quaternion=place_quaternion,
                left_tool_command=1.0,
                right_position=place_start_right_hand
                - np.asarray((0.0, 0.0, place_drop_m * smooth_progress)),
                right_quaternion=right_place_quaternion,
                right_tool_command=1.0,
                suction_controller=suction,
            )
            if (
                physics_step % 40 == 0
                or suction.attachment is None
                or place_completed_early
                or place_force_safety_abort
            ):
                place_trace.append(
                    {
                        "physics_step": physics_step,
                        "actual_hand_position_m": _flat(hand.get_pos()),
                        "actual_right_hand_position_m": _flat(right_hand.get_pos()),
                        "parcel_position_m": _flat(parcel.get_pos()),
                        "cradle": (
                            cradle_monitor.summary()
                            if cradle_monitor is not None
                            else None
                        ),
                        **suction.summary(),
                    }
                )
            if suction.attachment is None:
                break
            if place_completed_early or place_force_safety_abort:
                break
        parcel_before_release = np.asarray(_flat(parcel.get_pos()))
        placed_before_release = bool(
            suction.attachment is not None
            and placement_within_release_gate(
                parcel_before_release, expected_placed_position
            )
        )
        if placed_before_release:
            suction.release()
            released = True
            release_start_qpos = np.asarray(_flat(robot.get_qpos()))
            release_start_hand = np.asarray(_flat(hand.get_pos()))
            release_retract_m = 0.030
            if args.cooperative_cradle:
                release_start_right_hand = np.asarray(_flat(right_hand.get_pos()))
                release_solution = robot.inverse_kinematics_multilink(
                    links=(left_hand, right_hand),
                    poss=(
                        release_start_hand
                        - np.asarray(approach_axis) * release_retract_m,
                        release_start_right_hand
                        - np.asarray(right_tool_axis) * release_retract_m,
                    ),
                    quats=(place_quaternion, right_place_quaternion),
                    init_qpos=release_start_qpos,
                    respect_joint_limit=True,
                    max_samples=4,
                    max_solver_iters=50,
                    damping=0.03,
                    max_step_size=0.08,
                    dofs_idx_local=arm_dofs,
                )
                release_start_arm_qpos = release_start_qpos[arm_dofs]
                release_target_arm_qpos = np.asarray(_flat(release_solution))[arm_dofs]
                release_controlled_dofs = arm_dofs
            else:
                release_solution = robot.inverse_kinematics(
                    link=hand,
                    pos=release_start_hand
                    - np.asarray(approach_axis) * release_retract_m,
                    quat=place_quaternion,
                    init_qpos=release_start_qpos,
                    respect_joint_limit=True,
                    max_samples=4,
                    max_solver_iters=50,
                    damping=0.03,
                    max_step_size=0.08,
                    dofs_idx_local=left_arm_dofs,
                )
                release_start_arm_qpos = release_start_qpos[left_arm_dofs]
                release_target_arm_qpos = np.asarray(_flat(release_solution))[
                    left_arm_dofs
                ]
                release_controlled_dofs = left_arm_dofs
            for release_step in range(1, 241):
                release_progress = min(release_step / 120.0, 1.0)
                release_smooth_progress = release_progress * release_progress * (
                    3.0 - 2.0 * release_progress
                )
                release_command = release_start_arm_qpos + release_smooth_progress * (
                    release_target_arm_qpos - release_start_arm_qpos
                )
                robot.control_dofs_position(release_command, release_controlled_dofs)
                scene.step()
                record_control_frame(
                    stage="release",
                    base_action=np.zeros(3),
                    left_position=release_start_hand
                    - np.asarray(approach_axis)
                    * (release_retract_m * release_smooth_progress),
                    left_quaternion=_flat(hand.get_quat()),
                    left_tool_command=-1.0,
                    right_position=(
                        release_start_right_hand
                        - np.asarray(right_tool_axis)
                        * (release_retract_m * release_smooth_progress)
                        if args.cooperative_cradle
                        else _flat(right_hand.get_pos())
                    ),
                    right_quaternion=_flat(right_hand.get_quat()),
                    right_tool_command=1.0,
                    suction_controller=suction,
                )

    parcel_final_position = np.asarray(_flat(parcel.get_pos()))
    expected_final_position = initial_parcel_position + transport_delta
    placement_error_m = float(np.linalg.norm(parcel_final_position - expected_final_position))
    success = bool(
        lift_success
        and transport_success
        and placed_before_release
        and released
        and placement_error_m <= 0.040
        and suction.max_force_n < 35.0
        and suction.max_contact_force_n < 35.0
        and (
            cradle_monitor is None or cradle_monitor.max_contact_force_n < 35.0
        )
    )
    failure_stage = (
        grasp_mode_route_failure_stage(
            required=args.require_vla_grasp_mode,
            matched=vla_grasp_mode_match,
        )
        if not success
        else None
    )
    dataset_saved = False
    if writer is not None:
        if success and recorded_frames > 0:
            writer.save_episode()
            writer.finalize()
            dataset_saved = True
        else:
            writer.clear_episode()
    pi05_qualification = None
    pi05_dataset_saved = False
    absolute_qualification = None
    absolute_dataset_saved = False
    executed_policy_trace = [
        item for item in policy_trace if "routing_sample_index" not in item
    ]
    rollout_attribution = summarize_mobile_policy_attribution(executed_policy_trace)
    expert_fallback_count = sum(
        bool(item["fallback_to_expert"]) for item in executed_policy_trace
    )
    emergency_stop_count = sum(
        bool(item["emergency_stop"]) for item in executed_policy_trace
    )
    force_violation_count = sum(
        value >= 35.0
        for value in (
            float(suction.max_force_n),
            float(suction.max_contact_force_n),
            float(cradle_monitor.max_contact_force_n)
            if cradle_monitor is not None
            else 0.0,
        )
    )
    absolute_full_authority = bool(
        args.policy_mode == "pi05_absolute"
        and executed_policy_trace
        and rollout_attribution.policy_authority == "absolute_vla_action_candidate"
        and not rollout_attribution.expert_reference_used
        and expert_fallback_count == 0
        and emergency_stop_count == 0
        and not transport_deadline_handoff
        and all(
            item.get("action_contract") == "pi05_absolute_v1"
            and item.get("pure_vla_qualified_step") is True
            for item in executed_policy_trace
        )
    )
    if pi05_writer is not None:
        pi05_qualification = PI05AutonomousRolloutQualification(
            success=success,
            policy_type=policy_controller.policy_type if policy_controller else "none",
            policy_mode=args.policy_mode,
            residual_contract=bool(
                policy_controller is not None
                and policy_controller.uses_residual_contract
            ),
            vla_routes_grasp_mode=vla_routes_grasp_mode,
            goal_verdict_required=args.require_vla_goal_verdict,
            goal_arrival_verified=latest_policy_goal_verified,
            policy_authority=rollout_attribution.policy_authority,
            expert_reference_used=rollout_attribution.expert_reference_used,
            expert_reference_semantics=(
                rollout_attribution.expert_reference_semantics
            ),
            expert_fallback_count=expert_fallback_count,
            emergency_stop_count=emergency_stop_count,
            force_violation_count=force_violation_count,
            recorded_frames=pi05_writer.frame_count,
            material_residual_frames=pi05_writer.material_residual_frames,
        )
        pi05_dataset_saved = pi05_qualification.accepted
    if absolute_writer is not None:
        absolute_qualification = PI05AbsoluteRolloutQualification(
            success=success,
            policy_type=policy_controller.policy_type if policy_controller else "none",
            policy_mode=args.policy_mode,
            absolute_contract=bool(
                policy_controller is not None
                and policy_controller.uses_absolute_contract
            ),
            grasp_mode=args.grasp_mode,
            vla_routes_grasp_mode=vla_routes_grasp_mode,
            goal_verdict_required=args.require_vla_goal_verdict,
            goal_arrival_verified=latest_policy_goal_verified,
            policy_authority=rollout_attribution.policy_authority,
            system_control_class=rollout_attribution.system_control_class,
            task_action_correction_count=(
                rollout_attribution.task_action_correction_count
            ),
            expert_reference_used=rollout_attribution.expert_reference_used,
            expert_reference_semantics=(
                rollout_attribution.expert_reference_semantics
            ),
            expert_fallback_count=expert_fallback_count,
            emergency_stop_count=emergency_stop_count,
            force_violation_count=force_violation_count,
            minimum_selected_scale=(
                min(
                    float(item["selected_scale"])
                    for item in executed_policy_trace
                )
                if executed_policy_trace
                else 0.0
            ),
            transport_deadline_handoff=transport_deadline_handoff,
            recorded_frames=absolute_writer.frame_count,
            material_action_frames=absolute_writer.material_action_frames,
            nonzero_base_command_frames=(
                absolute_writer.nonzero_base_command_frames
            ),
        )
        absolute_dataset_saved = absolute_qualification.accepted
    media = {
        "video_requested": args.record_video is not None,
        "video_path": str(args.record_video.resolve()) if args.record_video else None,
        "video_saved": False,
        "snapshot_requested": args.snapshot is not None,
        "snapshot_path": str(args.snapshot.resolve()) if args.snapshot else None,
        "snapshot_saved": False,
        "contact_video_requested": args.record_contact_video is not None,
        "contact_video_path": (
            str(args.record_contact_video.resolve()) if args.record_contact_video else None
        ),
        "contact_video_saved": False,
        "contact_snapshot_requested": args.contact_snapshot is not None,
        "contact_snapshot_path": (
            str(args.contact_snapshot.resolve()) if args.contact_snapshot else None
        ),
        "contact_snapshot_saved": contact_snapshot_saved,
    }
    if args.snapshot is not None:
        if media_camera is None:
            raise RuntimeError("snapshot recording requires a camera")
        from imageio.v3 import imwrite

        args.snapshot.parent.mkdir(parents=True, exist_ok=True)
        final_rgb, _, _, _ = media_camera.render(rgb=True, depth=False)
        imwrite(args.snapshot, np.asarray(final_rgb)[..., :3].astype(np.uint8))
        media["snapshot_saved"] = args.snapshot.is_file()
    if args.record_video is not None:
        assert media_camera is not None
        media_camera.stop_recording(save_to_filename=str(args.record_video), fps=30)
        media["video_saved"] = args.record_video.is_file()
    if args.record_contact_video is not None:
        assert contact_camera is not None
        contact_camera.stop_recording(
            save_to_filename=str(args.record_contact_video), fps=30
        )
        media["contact_video_saved"] = args.record_contact_video.is_file()
    inference_trace = [
        item for item in policy_trace if bool(item.get("inference_performed", True))
    ]
    policy_latencies = [float(item["latency_ms"]) for item in inference_trace]
    warm_policy_latencies = policy_latencies[1:]
    residual_boundary_values = [
        float(item["residual_boundary_l2"])
        for item in policy_trace
        if item.get("residual_boundary_l2") is not None
    ]
    policy_stages = sorted({str(item["stage"]) for item in policy_trace})
    accepted_dual_arm_updates = [
        item["arm_residual"]
        for item in policy_trace
        if args.policy_mode == "base_dual_arm_residual"
        and bool(item["arm_residual"]["ik_accepted"])
        and item["arm_residual"]["projection"] is not None
    ]
    depth_risk_updates = [
        item["depth_risk"]
        for item in policy_trace
        if item["depth_risk"] is not None
    ]
    policy_summary = {
        "enabled": policy_controller is not None,
        "mode": args.policy_mode if policy_controller is not None else "expert_only",
        "checkpoint": (
            str(args.vla_checkpoint.resolve())
            if args.vla_checkpoint is not None
            else None
        ),
        "policy_type": policy_controller.policy_type if policy_controller else None,
        "policy_attribution": rollout_attribution.to_dict(),
        "requested_hz": args.policy_hz if policy_controller is not None else 0,
        "control_command_hz": (
            30
            if policy_controller is not None
            and args.pi05_chunk_execution_protocol == "pi05-open-loop-queue-v1"
            else args.policy_hz if policy_controller is not None else 0
        ),
        "chunk_execution_protocol": (
            args.pi05_chunk_execution_protocol if policy_controller is not None else None
        ),
        "chunk_execution_steps": (
            args.pi05_chunk_execution_steps if policy_controller is not None else 0
        ),
        "stage_chunk_execution_steps": (
            args.pi05_stage_chunk_execution_steps
            if policy_controller is not None
            else None
        ),
        "policy_selection_count": len(policy_trace),
        "policy_inference_count": len(inference_trace),
        "persistent_policy_service": bool(args.vla_policy_service_ready),
        "policy_runtime_session_id": (
            next(
                iter(
                    {
                        str(item["policy_runtime_session_id"])
                        for item in policy_trace
                        if item.get("policy_runtime_session_id")
                    }
                ),
                None,
            )
            if policy_trace
            else None
        ),
        "policy_runtime_episode_index": (
            next(
                iter(
                    {
                        int(item["policy_runtime_episode_index"])
                        for item in policy_trace
                        if item.get("policy_runtime_episode_index") is not None
                    }
                ),
                None,
            )
            if policy_trace
            else None
        ),
        "mean_residual_boundary_l2": (
            statistics.fmean(residual_boundary_values)
            if residual_boundary_values
            else None
        ),
        "p95_residual_boundary_l2": (
            sorted(residual_boundary_values)[
                math.ceil(0.95 * len(residual_boundary_values)) - 1
            ]
            if residual_boundary_values
            else None
        ),
        "minimum_expert_progress_ratio": harness_config.min_progress_ratio,
        "force_memory_enabled": args.force_memory_harness,
        "depth_sidecar_enabled": args.depth_risk_sidecar,
        "depth_sidecar_tighten_count": sum(
            float(item["scale_cap"]) < 1.0 - 1e-9 for item in depth_risk_updates
        ),
        "depth_sidecar_fail_closed_count": sum(
            bool(item["fail_closed"]) for item in depth_risk_updates
        ),
        "mean_depth_sidecar_scale_cap": (
            statistics.fmean(float(item["scale_cap"]) for item in depth_risk_updates)
            if depth_risk_updates
            else None
        ),
        "force_memory_tighten_count": sum(
            bool(item["force_memory_enabled"])
            and float(item["force_memory"]["scale_cap"]) < 1.0 - 1e-9
            for item in policy_trace
        ),
        "force_memory_full_fallback_count": sum(
            bool(item["force_memory_enabled"])
            and float(item["force_memory"]["scale_cap"]) <= 1e-9
            for item in policy_trace
        ),
        "mean_force_memory_scale_cap": (
            statistics.fmean(
                float(item["force_memory"]["scale_cap"]) for item in policy_trace
            )
            if policy_trace
            else None
        ),
        "transport_capacity_ratio": transport_capacity_ratio,
        "transport_deadline_handoff": transport_deadline_handoff,
        "transport_deadline_handoff_step": transport_deadline_handoff_step,
        "transport_deadline_handoff_distance_m": transport_deadline_handoff_distance_m,
        "transport_deadline_handoff_remaining_s": transport_deadline_handoff_remaining_s,
        "transport_deadline_handoff_physics_steps": transport_deadline_handoff_physics_steps,
        "policy_authority": rollout_attribution.policy_authority,
        "system_control_class": rollout_attribution.system_control_class,
        "task_routing_authorities": list(
            rollout_attribution.task_routing_authorities
        ),
        "task_action_correction_count": (
            rollout_attribution.task_action_correction_count
        ),
        "expert_reference_used": rollout_attribution.expert_reference_used,
        "expert_reference_semantics": list(
            rollout_attribution.expert_reference_semantics
        ),
        "authority_internally_consistent": rollout_attribution.internally_consistent,
        "absolute_full_authority": absolute_full_authority,
        "pure_vla_complete_success": bool(success and absolute_full_authority),
        "deterministic_release_interlock_used": any(
            "deterministic_release_interlock"
            in tuple(item.get("task_action_corrections") or ())
            for item in executed_policy_trace
        ),
        "inference_calls": len(policy_trace),
        "mean_latency_ms": statistics.fmean(policy_latencies) if policy_latencies else None,
        "p95_latency_ms": (
            sorted(policy_latencies)[math.ceil(0.95 * len(policy_latencies)) - 1]
            if policy_latencies
            else None
        ),
        "cold_start_latency_ms": policy_latencies[0] if policy_latencies else None,
        "warm_mean_latency_ms": (
            statistics.fmean(warm_policy_latencies) if warm_policy_latencies else None
        ),
        "warm_p95_latency_ms": (
            sorted(warm_policy_latencies)[
                math.ceil(0.95 * len(warm_policy_latencies)) - 1
            ]
            if warm_policy_latencies
            else None
        ),
        "stages": {
            stage: sum(str(item["stage"]) == stage for item in policy_trace)
            for stage in policy_stages
        },
        "mean_selected_scale": (
            statistics.fmean(
                float(item["selected_scale"]) for item in executed_policy_trace
            )
            if executed_policy_trace
            else None
        ),
        "minimum_selected_scale": (
            min(float(item["selected_scale"]) for item in executed_policy_trace)
            if executed_policy_trace
            else None
        ),
        "expert_fallback_count": expert_fallback_count,
        "emergency_stop_count": emergency_stop_count,
        "routing_fallback_count": sum(
            bool(item["fallback_to_expert"])
            for item in policy_trace
            if "routing_sample_index" in item
        ),
        "tool_command_correction_count": sum(
            int(item["tool_command_corrections"]) for item in policy_trace
        ),
        "applied_physics_steps": policy_applied_physics_steps,
        "goal_verdict_required": args.require_vla_goal_verdict,
        "grasp_mode_verdict_required": args.require_vla_grasp_mode,
        "vla_routes_grasp_mode": vla_routes_grasp_mode,
        "vla_mode_votes": args.vla_mode_votes if vla_routes_grasp_mode else 0,
        "expected_grasp_mode": expected_grasp_mode,
        "selected_grasp_mode": vla_selected_grasp_mode,
        "executed_grasp_mode": args.grasp_mode,
        "grasp_mode_match": vla_grasp_mode_match,
        "grasp_mode_route_mismatch_before_actuation": (
            grasp_mode_route_mismatch_before_actuation
        ),
        "failure_stage": failure_stage,
        "goal_arrival_verified": latest_policy_goal_verified,
        "goal_progress_threshold": 0.90,
        "goal_arrival_tolerance_m": 0.015,
        "arm_residual": {
            "enabled": args.policy_mode
            in {
                "base_arm_residual",
                "base_dual_arm_residual",
                "pi05_residual",
                "pi05_absolute",
            },
            "authorized_stages": (
                ["pregrasp", "grasp_approach", "lift", "transport", "place"]
                if args.policy_mode == "pi05_absolute"
                else
                ["pregrasp", "grasp_approach", "lift", "transport"]
                if args.policy_mode == "pi05_residual"
                else ["transport"]
            ),
            "max_cumulative_position_residual_m": (
                {"pregrasp": 0.02, "grasp_approach": 0.01, "lift": 0.005, "transport": 0.01}
                if args.policy_mode == "pi05_residual"
                else 0.01
            ),
            "dual_arm_common_mode": args.policy_mode == "base_dual_arm_residual",
            "maximum_differential_residual_m": (
                0.0 if args.cooperative_cradle else 0.0015
            )
            if args.policy_mode == "base_dual_arm_residual"
            else None,
            "precision_fade_distance_m": (
                {"zero": 0.025, "full": 0.120}
                if args.policy_mode == "base_dual_arm_residual"
                else None
            ),
            "orientation_control": (
                "absolute_vla_with_harness_step_limit"
                if args.policy_mode == "pi05_absolute"
                else "expert_locked"
            ),
            "tool_control": (
                "vla_command_with_recorded_task_interlocks"
                if args.policy_mode == "pi05_absolute"
                else "expert_locked"
            ),
            "ik_update_attempts": arm_policy_update_attempts,
            "ik_update_accepts": arm_policy_update_accepts,
            "ik_update_rejections": arm_policy_update_rejections,
            "applied_physics_steps": arm_policy_applied_physics_steps,
            "accepted_dual_arm_updates": len(accepted_dual_arm_updates),
            "left_material_updates": sum(
                float(item["residual_norm_m"] or 0.0) > 1e-5
                for item in accepted_dual_arm_updates
            ),
            "right_material_updates": sum(
                float(item["right_residual_norm_m"] or 0.0) > 1e-5
                for item in accepted_dual_arm_updates
            ),
            "maximum_tool_separation_change_m": (
                max(
                    float(item["projection"]["separation_change_m"])
                    for item in accepted_dual_arm_updates
                )
                if accepted_dual_arm_updates
                else None
            ),
        },
        "actuation_scope": (
            "grasp-approach and transport base velocity residual only"
            if args.policy_mode == "base_residual" and policy_controller is not None
            else (
                "grasp-approach/transport base velocity plus anchored transport left-arm "
                "position residual"
            )
            if args.policy_mode == "base_arm_residual" and policy_controller is not None
            else (
                "grasp-approach/transport base velocity plus rigid-object-consistent "
                "dual-arm transport position residual"
            )
            if args.policy_mode == "base_dual_arm_residual" and policy_controller is not None
            else (
                "PI0.5 RGB-D residual control over pregrasp, grasp approach, lift, "
                "and transport; orientation, tool execution, and release are harness locked"
            )
            if args.policy_mode == "pi05_residual" and policy_controller is not None
            else (
                "PI0.5 RGB-D expert-independent absolute base and bimanual pose control "
                "over pregrasp, grasp approach, lift, transport, and place; deterministic "
                "release interlock only"
            )
            if args.policy_mode == "pi05_absolute" and policy_controller is not None
            else "none; shadow evaluation"
            if policy_controller is not None
            else "deterministic expert"
        ),
        "trace": policy_trace,
    }
    payload = {
        "runtime": runtime_report(),
        "task": (
            "mobile cooperative tri-suction and V-cradle parcel transport"
            if args.cooperative_cradle
            else "mobile tri-suction parcel pickup, transport, and place"
        ),
        "parcel_profile": args.parcel_profile,
        "parcel_shape": args.parcel_shape,
        "parcel_orientation": args.parcel_orientation,
        "grasp_mode": args.grasp_mode,
        "expected_grasp_mode": expected_grasp_mode,
        "failure_stage": failure_stage,
        "vla_grasp_mode_selection": {
            "required": args.require_vla_grasp_mode,
            "routes_execution": vla_routes_grasp_mode,
            "mode_input_hidden": vla_routes_grasp_mode,
            "expected": expected_grasp_mode,
            "selected": vla_selected_grasp_mode,
            "executed": args.grasp_mode,
            "matched": vla_grasp_mode_match,
            "mismatch_before_actuation": grasp_mode_route_mismatch_before_actuation,
            "failure_stage": failure_stage,
            "sample_count": (
                args.vla_mode_votes if routing_mode_consensus is not None else 0
            ),
            "vote_counts": (
                dict(
                    zip(
                        ("top_suction", "side_suction", "cooperative_cradle"),
                        routing_mode_consensus.vote_counts,
                        strict=True,
                    )
                )
                if routing_mode_consensus is not None
                else None
            ),
            "mean_logits": (
                dict(
                    zip(
                        ("top_suction", "side_suction", "cooperative_cradle"),
                        routing_mode_consensus.mean_logits,
                        strict=True,
                    )
                )
                if routing_mode_consensus is not None
                else None
            ),
            "consensus_fraction": (
                routing_mode_consensus.consensus_fraction
                if routing_mode_consensus is not None
                else None
            ),
        },
        "minimum_sealed_cups": args.minimum_sealed_cups,
        "top_active_cup_offset_world_m": top_active_cup_offset_world.tolist(),
        "side_active_cup_offset_world_m": side_active_cup_offset_world.tolist(),
        "parcel_yaw_rad": args.parcel_yaw_rad,
        "cooperative_cradle": args.cooperative_cradle,
        "parcel_mass_kg": args.parcel_mass_kg,
        "parcel_size_m": parcel_size.tolist(),
        "parcel_friction": args.parcel_friction,
        "parcel_offset_m": list(args.parcel_offset_m),
        "recovery_parameters": {
            "contact_offset_m": list(args.recovery_contact_offset_m),
            "contact_penetration_delta_m": args.recovery_contact_penetration_delta_m,
            "cradle_engagement_delta_m": args.recovery_cradle_engagement_delta_m,
            "left_lift_offset_m": list(args.recovery_left_lift_offset_m),
            "right_lift_offset_m": list(args.recovery_right_lift_offset_m),
            "right_lift_offset_application": "smooth_stage_progress_v2",
            "approach_speed_scale": args.recovery_approach_speed_scale,
            "vertical_speed_scale": args.recovery_vertical_speed_scale,
            "lift_height_delta_m": args.recovery_lift_height_delta_m,
            "placement_clearance_m": args.recovery_placement_clearance_m,
        },
        "task_text": task_text,
        "target_marker": {
            "color_name": PROFILE_COLOR_NAMES.get(args.parcel_profile, "blue"),
            "rgb": list(profile_color),
            "destination_pedestal_position_m": destination_pedestal_position.tolist(),
            "policy_goal_frame": "mobile_base_world_xy",
        },
        "policy": policy_summary,
        "tool_axis_world": tool_axis.tolist(),
        "approach_axis_world": approach_axis.tolist(),
        "right_tool_axis_world": (
            right_tool_axis.tolist() if args.cooperative_cradle else None
        ),
        "precontact_target_m": precontact_target.tolist(),
        "contact_hand_target_m": contact_hand_target.tolist(),
        "right_cradle_contact_target_m": (
            right_cradle_contact_target.tolist()
            if right_cradle_contact_target is not None
            else None
        ),
        "contact_penetration_m": contact_penetration_m,
        "stable_seal_steps": stable_seal_steps,
        "required_stable_seal_steps": required_stable_seal_steps,
        "top_approach_ik": {
            "attempts": top_approach_ik_attempts,
            "accepts": top_approach_ik_accepts,
            "rejections": top_approach_ik_rejections,
        },
        "top_quasistatic_contact": {
            "active_steps": top_quasistatic_steps,
            "wait_steps": top_quasistatic_wait_steps,
            "max_hand_speed_m_s": top_quasistatic_max_hand_speed_m_s,
            "advance_speed_limit_m_s": 0.015,
            "advance_step_m": 0.0001,
        },
        "top_lift_waypoint_errors": top_lift_waypoint_errors if latched else [],
        "max_approach_base_speed_m_s": max_base_speed_m_s,
        "pregrasp_tracking_error_m": list(pregrasp_tracking_error_m),
        "pregrasp_targets_m": [target.tolist() for target in pregrasp_targets],
        "pregrasp_final_positions_m": list(pregrasp_final_positions),
        "planned_parcel_position_m": planned_parcel_position.tolist(),
        "parcel_spawn_position_m": parcel_spawn.tolist(),
        "pedestal_position_m": pedestal_position.tolist(),
        "destination_pedestal_position_m": destination_pedestal_position.tolist(),
        "scene_stable": scene_stable,
        "settle_position_error_m": settle_position_error_m,
        "settle_linear_speed_m_s": settle_linear_speed_m_s,
        "settle_trace": settle_trace,
        "parcel_initial_z_m": parcel_initial_z,
        "parcel_lift_z_m": lift_parcel_z,
        "parcel_final_position_m": parcel_final_position.tolist(),
        "lift_delta_m": lift_delta,
        "lift_target_delta_m": lift_target_delta_m,
        "lift_success": lift_success,
        "transport_success": transport_success,
        "placed_before_release": placed_before_release,
        "place_release_gate_required_steps": 24,
        "place_release_gate_consecutive_steps": consecutive_place_target_steps,
        "place_completed_early": place_completed_early,
        "place_force_safety_abort": place_force_safety_abort,
        "released": released,
        "placement_error_m": placement_error_m,
        "latched": latched,
        "approach_trace": approach_trace,
        "lift_trace": lift_trace,
        "transport_trace": transport_trace,
        "place_trace": place_trace,
        "dataset": {
            "requested": args.record_dataset is not None,
            "saved": dataset_saved,
            "root": str(args.record_dataset) if args.record_dataset is not None else None,
            "frames": recorded_frames if writer is not None else 0,
            "fps": 30,
            "storage_format": writer.storage_format if writer is not None else None,
            "bytes": writer.dataset_bytes if dataset_saved and writer is not None else 0,
            "state_dim": 43,
            "action_dim": 19,
            "rgb_shape": [args.image_size, args.image_size, 3],
            "depth_shape": [args.image_size, args.image_size, 1],
            "privileged_state_in_policy": False,
        },
        "pi05_residual_dataset": {
            "requested": args.record_pi05_residual_dataset is not None,
            "accepted_for_behavior_cloning": pi05_dataset_saved,
            "accepted_as_pure_vla_experience": (
                pi05_qualification.accepted_as_pure_vla_experience
                if pi05_qualification is not None
                else False
            ),
            "root": (
                str(args.record_pi05_residual_dataset)
                if args.record_pi05_residual_dataset is not None
                else None
            ),
            "frames": pi05_writer.frame_count if pi05_writer is not None else 0,
            "state_dim": 80,
            "action_dim": 14,
            "action_semantics": "raw_pi05_residual_before_harness",
            "qualification": (
                {
                    **pi05_qualification.__dict__,
                    "rejection_reasons": list(pi05_qualification.rejection_reasons()),
                }
                if pi05_qualification is not None
                else None
            ),
            "failed_attempts_are_bc_labels": False,
            "privileged_state_in_policy": False,
        },
        "pi05_absolute_dataset": {
            "requested": args.record_pi05_absolute_dataset is not None,
            "accepted_for_behavior_cloning": absolute_dataset_saved,
            "accepted_as_pure_vla_experience": (
                absolute_qualification.accepted_as_pure_vla_experience
                if absolute_qualification is not None
                else False
            ),
            "root": (
                str(args.record_pi05_absolute_dataset)
                if args.record_pi05_absolute_dataset is not None
                else None
            ),
            "frames": (
                absolute_writer.frame_count if absolute_writer is not None else 0
            ),
            "state_dim": 80,
            "action_dim": 23,
            "action_semantics": (
                "verified_executed_absolute_vla_action_plus_mode_progress"
            ),
            "qualification": (
                {
                    **absolute_qualification.__dict__,
                    "rejection_reasons": list(
                        absolute_qualification.rejection_reasons()
                    ),
                }
                if absolute_qualification is not None
                else None
            ),
            "failed_attempts_are_bc_labels": False,
            "privileged_state_in_policy": False,
        },
        "media": media,
        "suction": suction.summary(),
        "cradle": {
            "enabled": args.cooperative_cradle,
            "lift_contact_steps": cradle_lift_contact_steps,
            "lift_steps": cradle_lift_steps,
            "lift_contact_ratio": (
                cradle_lift_contact_steps / cradle_lift_steps
                if cradle_lift_steps
                else 0.0
            ),
            "transport_contact_steps": cradle_transport_contact_steps,
            "transport_steps": cradle_transport_steps,
            "transport_contact_ratio": (
                cradle_transport_contact_steps / cradle_transport_steps
                if cradle_transport_steps
                else 0.0
            ),
            "place_contact_steps": cradle_place_contact_steps,
            "place_steps": cradle_place_steps,
            "place_contact_ratio": (
                cradle_place_contact_steps / cradle_place_steps
                if cradle_place_steps
                else 0.0
            ),
            "minimum_required_lift_transport_contact_ratio": (
                0.50 if args.cooperative_cradle else None
            ),
            "engage_steps": cradle_engage_steps,
            "engage_contact_steps": cradle_engage_contact_steps,
            "engaged_before_lift": cradle_engaged_before_lift,
            "incremental_lift_ik_attempts": cooperative_lift_ik_attempts,
            "incremental_lift_ik_accepts": cooperative_lift_ik_accepts,
            "incremental_lift_ik_rejections": cooperative_lift_ik_rejections,
            "contact_memory": {
                "enabled": args.cradle_contact_memory,
                "active_steps": cradle_lift_contact_memory_active_steps,
                "max_normal_offset_m": cradle_lift_contact_memory_max_offset_m,
                "maximum_allowed_offset_m": 0.005,
                "force_release_threshold_n": 20.0,
            },
            "incremental_place_ik_attempts": cooperative_place_ik_attempts,
            "incremental_place_ik_accepts": cooperative_place_ik_accepts,
            "incremental_place_ik_rejections": cooperative_place_ik_rejections,
            "physical": (
                cradle_monitor.summary() if cradle_monitor is not None else None
            ),
        },
        "success": success,
    }
    args.output.mkdir(parents=True, exist_ok=True)
    summary_path = args.output / "summary.json"
    summary_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    if pi05_writer is not None:
        assert pi05_qualification is not None
        assert args.vla_checkpoint is not None
        pi05_writer.commit_or_reject(
            pi05_qualification,
            checkpoint=args.vla_checkpoint,
            training_contract_sha256=(
                policy_controller.training_contract_sha256
                if policy_controller is not None
                else None
            ),
            chunk_execution_protocol=args.pi05_chunk_execution_protocol,
            source_summary=summary_path,
        )
    if absolute_writer is not None:
        assert absolute_qualification is not None
        assert args.vla_checkpoint is not None
        absolute_writer.commit_or_reject(
            absolute_qualification,
            checkpoint=args.vla_checkpoint,
            training_contract_sha256=(
                policy_controller.training_contract_sha256
                if policy_controller is not None
                else None
            ),
            chunk_execution_protocol=args.pi05_chunk_execution_protocol,
            source_summary=summary_path,
        )
    print(json.dumps(payload))
    return 0 if success else 2


if __name__ == "__main__":
    raise SystemExit(main())
