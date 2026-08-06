"""Reset and kinematic contracts for the Genesis ``stack_bowls_three`` port.

The reset sampler intentionally mirrors RoboTwin's legacy NumPy call order.
In particular, the fixed Z value is still sampled with ``uniform`` because
that call advances ``numpy.random.RandomState`` and changes every later pose.
Genesis is imported only by runtime tools; this module stays unit-testable.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Protocol

from .contracts import ContractError


SOURCE_QUATERNION_WXYZ = (0.5, 0.5, 0.5, 0.5)
SOURCE_TARGET_XY_M = (0.0, -0.1)
MINIMUM_SEPARATION_SQUARED_M2 = 0.0169


class UniformRng(Protocol):
    def uniform(self, low: float, high: float) -> Any:
        """Return one scalar uniform sample."""


@dataclass(frozen=True)
class BowlResetPose:
    """One accepted source sample after its post-reset Y sort."""

    name: str
    source_sample_index: int
    accepted_attempt: int
    position_xyz_m: tuple[float, float, float]
    quaternion_wxyz: tuple[float, float, float, float] = SOURCE_QUATERNION_WXYZ

    def as_dict(self) -> dict[str, object]:
        return {
            "name": self.name,
            "source_sample_index": self.source_sample_index,
            "accepted_attempt": self.accepted_attempt,
            "position_xyz_m": list(self.position_xyz_m),
            "quaternion_wxyz": list(self.quaternion_wxyz),
        }


def _numpy_random_state(seed: int) -> UniformRng:
    try:
        import numpy as np
    except ImportError as exc:  # pragma: no cover - exercised on minimal hosts
        raise RuntimeError(
            "source-compatible reset sampling requires NumPy; install the Genesis runtime extras"
        ) from exc
    return np.random.RandomState(seed)


def _sample_candidate(rng: UniformRng) -> tuple[float, float, float]:
    """Mirror RoboTwin ``rand_pose`` including its exact RNG call order."""

    x = float(rng.uniform(-0.3, 0.3))
    y = float(rng.uniform(-0.15, 0.15))
    while abs(x) < 0.15 and y > 0.0:
        y = float(rng.uniform(-0.15, 0.0))
    # The source calls uniform even though both bounds are identical.
    z = float(rng.uniform(0.741, 0.741))
    return x, y, z


def _candidate_allowed(
    candidate: tuple[float, float, float],
    accepted: list[tuple[float, float, float]],
) -> bool:
    x, y, _ = candidate
    if abs(x) < 0.09:
        return False
    if (x - SOURCE_TARGET_XY_M[0]) ** 2 + (y - SOURCE_TARGET_XY_M[1]) ** 2 < (
        MINIMUM_SEPARATION_SQUARED_M2
    ):
        return False
    return all(
        (x - prior[0]) ** 2 + (y - prior[1]) ** 2
        >= MINIMUM_SEPARATION_SQUARED_M2
        for prior in accepted
    )


def sample_source_reset_poses(
    *,
    seed: int | None = None,
    rng: UniformRng | None = None,
    max_attempts_per_bowl: int = 10_000,
) -> list[BowlResetPose]:
    """Sample and name three poses exactly like RoboTwin's source reset.

    Supply ``seed`` for the runtime path or inject ``rng`` in tests.  The two
    inputs are mutually exclusive so receipts cannot ambiguously identify the
    random stream.
    """

    if (seed is None) == (rng is None):
        raise ValueError("provide exactly one of seed or rng")
    if seed is not None and (not isinstance(seed, int) or isinstance(seed, bool)):
        raise ValueError("seed must be an integer")
    if not isinstance(max_attempts_per_bowl, int) or max_attempts_per_bowl <= 0:
        raise ValueError("max_attempts_per_bowl must be a positive integer")
    active_rng = rng if rng is not None else _numpy_random_state(seed)  # type: ignore[arg-type]

    accepted: list[tuple[float, float, float]] = []
    generated: list[tuple[int, int, tuple[float, float, float]]] = []
    for source_index in range(3):
        for attempt in range(1, max_attempts_per_bowl + 1):
            candidate = _sample_candidate(active_rng)
            if _candidate_allowed(candidate, accepted):
                accepted.append(candidate)
                generated.append((source_index, attempt, candidate))
                break
        else:
            raise RuntimeError(
                f"reset rejection sampling exceeded {max_attempts_per_bowl} attempts "
                f"for source bowl {source_index}"
            )

    generated.sort(key=lambda item: item[2][1])
    result = [
        BowlResetPose(
            name=f"bowl{sorted_index}",
            source_sample_index=source_index,
            accepted_attempt=attempt,
            position_xyz_m=position,
        )
        for sorted_index, (source_index, attempt, position) in enumerate(generated, start=1)
    ]
    validate_source_reset_poses(result)
    return result


def validate_source_reset_poses(poses: list[BowlResetPose]) -> None:
    """Reject a reset that violates any frozen source distribution invariant."""

    if len(poses) != 3:
        raise ValueError("source reset must contain exactly three bowls")
    expected_names = ["bowl1", "bowl2", "bowl3"]
    if [pose.name for pose in poses] != expected_names:
        raise ValueError("bowls must be named bowl1..bowl3 after ascending-Y sort")
    if [pose.position_xyz_m[1] for pose in poses] != sorted(
        pose.position_xyz_m[1] for pose in poses
    ):
        raise ValueError("bowls are not sorted by ascending Y")

    for index, pose in enumerate(poses):
        x, y, z = pose.position_xyz_m
        if not all(math.isfinite(value) for value in (x, y, z)):
            raise ValueError(f"{pose.name} contains a non-finite position")
        if not -0.3 <= x <= 0.3 or not -0.15 <= y <= 0.15 or z != 0.741:
            raise ValueError(f"{pose.name} is outside the source reset bounds")
        if abs(x) < 0.09:
            raise ValueError(f"{pose.name} violates the center-X rejection rule")
        if abs(x) < 0.15 and y > 0.0:
            raise ValueError(f"{pose.name} violates the source ylim_prop rule")
        if (x - SOURCE_TARGET_XY_M[0]) ** 2 + (y - SOURCE_TARGET_XY_M[1]) ** 2 < (
            MINIMUM_SEPARATION_SQUARED_M2
        ):
            raise ValueError(f"{pose.name} overlaps the target exclusion zone")
        for prior in poses[:index]:
            px, py, _ = prior.position_xyz_m
            if (x - px) ** 2 + (y - py) ** 2 < MINIMUM_SEPARATION_SQUARED_M2:
                raise ValueError(f"{pose.name} overlaps {prior.name}")
        if pose.quaternion_wxyz != SOURCE_QUATERNION_WXYZ:
            raise ValueError(f"{pose.name} has a non-source quaternion")


def arm_for_bowl_x(x_m: float) -> str:
    """Preserve the source expert's deterministic arm-selection boundary."""

    x = float(x_m)
    if not math.isfinite(x):
        raise ValueError("bowl X must be finite")
    return "left" if x < 0.0 else "right"


def arm_dof_names(side: str) -> list[str]:
    if side not in ("left", "right"):
        raise ValueError("side must be left or right")
    return [
        f"{side}_shoulder_pitch_joint",
        f"{side}_shoulder_roll_joint",
        f"{side}_shoulder_yaw_joint",
        f"{side}_elbow_joint",
        f"{side}_wrist_roll_joint",
        f"{side}_wrist_pitch_joint",
        f"{side}_wrist_yaw_joint",
    ]


def validate_genesis_scene_contract(
    contract: dict[str, Any],
    source_task: dict[str, Any],
    port: dict[str, Any],
) -> None:
    """Bind the Genesis workcell frame to the frozen source task and port."""

    if contract.get("schema_version") != 1:
        raise ContractError("Genesis scene schema_version must be 1")
    if contract.get("scene_id") != "mantis_stack_bowls_three_genesis_v1":
        raise ContractError("unexpected Genesis scene_id")
    if contract.get("source_task_contract") != "configs/source-task-stack-bowls-three.json":
        raise ContractError("Genesis scene must reference the frozen source task")
    if port["target"].get("genesis_scene_contract") != "configs/stack-bowls-genesis-v1.json":
        raise ContractError("port does not reference the Genesis scene contract")

    reset = contract.get("reset", {})
    if reset.get("rng") != "numpy.random.RandomState":
        raise ContractError("Genesis reset must preserve NumPy RandomState semantics")
    if reset.get("reference_seeds") != [0, 1, 42, 20260722]:
        raise ContractError("Genesis reset reference seeds changed")

    world = contract.get("world", {})
    source_reset = source_task["reset_distribution"]
    source_target = source_task["expert_and_control"]["target_xyz_m"]
    if world.get("table_plane_z_m") != source_reset.get("table_height_m"):
        raise ContractError("Genesis table height disagrees with the source task")
    if world.get("target_xy_m") != source_target[:2]:
        raise ContractError("Genesis stack target disagrees with the source task")
    base = world.get("mantis_base", {})
    if base.get("root_link") != "pelvis_link":
        raise ContractError("Genesis fixed-base root must be pelvis_link")
    position = base.get("position_xyz_m")
    quaternion = base.get("quaternion_wxyz")
    if not isinstance(position, list) or len(position) != 3:
        raise ContractError("Genesis Mantis base position must be a 3-vector")
    if not isinstance(quaternion, list) or len(quaternion) != 4:
        raise ContractError("Genesis Mantis base quaternion must be a 4-vector")
    if not all(
        isinstance(value, (int, float)) and math.isfinite(value)
        for value in position + quaternion
    ):
        raise ContractError("Genesis Mantis base pose contains a non-finite value")
    if position != [0.0, -0.35, 1.18]:
        raise ContractError("Genesis Mantis base position changed from the frozen IK-coverage candidate")
    if abs(math.sqrt(sum(float(value) ** 2 for value in quaternion)) - 1.0) > 1e-12:
        raise ContractError("Genesis Mantis base quaternion is not normalized")
    if base.get("hardware_claim") is not False:
        raise ContractError("simulation workcell base pose cannot claim hardware calibration")
    adaptation = base.get("adaptation_evidence", {})
    if adaptation.get("run_id") != "mantis-base-y-minus035-cpu-20260722-v1":
        raise ContractError("Genesis Mantis base adaptation is missing its diagnostic run")
    if adaptation.get("ik_probes_passed") != 30 or adaptation.get("ik_probes_total") != 30:
        raise ContractError("Genesis Mantis base adaptation must retain 30/30 IK coverage")
    if adaptation.get("claim_boundary") != (
        "diagnostic IK coverage only; no trajectory, contact, or task-success claim"
    ):
        raise ContractError("Genesis Mantis base adaptation claim boundary changed")

    tcp = contract.get("tcp", {})
    for side in ("left", "right"):
        expected_link = f"{side}_wrist_yaw_link"
        if tcp.get(side, {}).get("link") != expected_link:
            raise ContractError(f"Genesis {side} TCP must use {expected_link}")
        if tcp[side].get("local_point_xyz_m") != [0.1158, 0.0, 0.0]:
            raise ContractError(f"Genesis {side} TCP offset changed")
    orientation = tcp.get("orientation_wxyz")
    if not isinstance(orientation, list) or len(orientation) != 4:
        raise ContractError("Genesis TCP orientation must be a 4-vector")
    if abs(math.sqrt(sum(float(value) ** 2 for value in orientation)) - 1.0) > 1e-12:
        raise ContractError("Genesis TCP orientation is not normalized")

    control = contract.get("control", {})
    if control.get("physics_dt_s") != 1.0 / 250.0:
        raise ContractError("Genesis physics step must preserve the 250 Hz source clock")
    if control.get("policy_hz") != port["target"].get("control_hz"):
        raise ContractError("Genesis policy clock disagrees with the port")
    if control.get("resampling_contract") != "configs/control-resampling-v1.json":
        raise ContractError("Genesis scene does not reference the frozen resampler")

    ik_gate = contract.get("ik_gate", {})
    for field in (
        "max_samples",
        "max_solver_iters",
        "position_tolerance_m",
        "rotation_tolerance_rad",
    ):
        value = ik_gate.get(field)
        if not isinstance(value, (int, float)) or isinstance(value, bool) or value <= 0:
            raise ContractError(f"Genesis IK field {field} must be positive")
    boundary = contract.get("evidence_boundary", {})
    if boundary.get("ik_pass_is_task_success") is not False:
        raise ContractError("IK preflight cannot be promoted to task success")
    if boundary.get("teleporting_bowls_is_not_a_valid_task_rollout") is not True:
        raise ContractError("Genesis scene must reject teleporting as rollout evidence")

    contact = contract.get("contact_probe", {})
    if contact.get("protocol_version") != "single_bowl_contact_v15":
        raise ContractError("Genesis contact probe protocol changed")
    for field in (
        "arm_kp",
        "arm_kv",
        "gripper_kp",
        "gripper_kv",
        "arm_force_limit",
        "gripper_force_limit",
        "bowl_friction_coefficient",
        "finger_friction_coefficient",
        "minimum_segment_duration_s",
        "gripper_close_duration_s",
        "post_close_hold_s",
        "grasp_center_y_offset_m",
        "grasp_tcp_z_m",
        "pregrasp_retreat_z_m",
        "finger_forward_extent_m",
        "transit_clearance_z_m",
        "waypoint_settle_timeout_s",
        "lift_distance_m",
        "vertical_lift_distance_m",
        "vertical_lift_duration_s",
        "lift_tilt_duration_s",
        "lift_segment_duration_s",
        "minimum_lift_delta_m",
        "maximum_arm_tracking_error_rad",
        "maximum_gripper_tracking_error_m",
    ):
        value = contact.get(field)
        if not isinstance(value, (int, float)) or isinstance(value, bool) or (
            value <= 0 and field != "grasp_center_y_offset_m"
        ):
            raise ContractError(f"Genesis contact probe field {field} must be positive")
    if not -0.1 < float(contact["grasp_center_y_offset_m"]) < -0.05:
        raise ContractError("Genesis top-down grasp Y offset must select the near rim")
    if float(contact["grasp_tcp_z_m"]) <= float(contract["world"]["table_plane_z_m"]):
        raise ContractError("Genesis contact TCP must remain above the table")
    if float(contact["vertical_lift_distance_m"]) >= float(contact["lift_distance_m"]):
        raise ContractError("Genesis vertical lift must precede and remain below final lift")
    transit_front_y = contact.get("transit_front_y_m")
    if (
        not isinstance(transit_front_y, (int, float))
        or isinstance(transit_front_y, bool)
        or not -0.1 < float(transit_front_y) < 0.2
    ):
        raise ContractError("Genesis front transit Y must stay on the robot's initial side")
    if contact.get("required_contact_link_substring") != "clamp":
        raise ContractError("Genesis contact probe must distinguish finger from wrist contact")
    if contact.get("grasp_mode") != "top_down_near_rim_pinch":
        raise ContractError("Genesis contact grasp mode changed")
    contact_orientation = contact.get("orientation_wxyz")
    if not isinstance(contact_orientation, list) or len(contact_orientation) != 4:
        raise ContractError("Genesis contact orientation must be a quaternion")
    if abs(sum(float(value) ** 2 for value in contact_orientation) - 1.0) > 1e-9:
        raise ContractError("Genesis contact orientation must be unit length")
    if contact.get("orientation_semantics") != (
        "local +x points world -z for top-down insertion; local +y jaw axis follows world +y across the near rim"
    ):
        raise ContractError("Genesis contact orientation semantics changed")
    for field in ("transit_orientation_wxyz", "pregrasp_orientation_wxyz"):
        staged_orientation = contact.get(field)
        if not isinstance(staged_orientation, list) or len(staged_orientation) != 4:
            raise ContractError(f"Genesis {field} must be a quaternion")
        if abs(sum(float(value) ** 2 for value in staged_orientation) - 1.0) > 1e-9:
            raise ContractError(f"Genesis {field} must be unit length")
    if contact.get("staged_orientation_semantics") != (
        "60 degree transit at z 0.90 m, 80 degree pregrasp at z 0.875 m, then 90 degree rim insertion at z 0.84 m"
    ):
        raise ContractError("Genesis staged orientation semantics changed")
    lift_orientation = contact.get("lift_orientation_wxyz")
    if not isinstance(lift_orientation, list) or len(lift_orientation) != 4:
        raise ContractError("Genesis lift orientation must be a quaternion")
    if abs(sum(float(value) ** 2 for value in lift_orientation) - 1.0) > 1e-9:
        raise ContractError("Genesis lift orientation must be unit length")
    if contact.get("lift_orientation_semantics") != (
        "60 degree world-y pitch preserves the radial jaw axis while entering the verified upper workspace"
    ):
        raise ContractError("Genesis lift orientation semantics changed")
    for field in ("bowl_friction_coefficient", "finger_friction_coefficient"):
        if not 0.01 <= float(contact[field]) <= 5.0:
            raise ContractError(f"Genesis contact field {field} is outside the stable range")
    if contact.get("friction_semantics") != (
        "Genesis 1.2.3 pair coefficient is the maximum of the two geom coefficients"
    ):
        raise ContractError("Genesis contact friction semantics changed")
    if contact.get("gripper_tracking_scope") != (
        "contact-free open navigation stages only; blocked closure against the bowl is expected"
    ):
        raise ContractError("Genesis gripper tracking scope changed")
    settle_count = contact.get("waypoint_settle_consecutive_steps")
    if not isinstance(settle_count, int) or isinstance(settle_count, bool) or settle_count <= 0:
        raise ContractError("Genesis contact settle count must be a positive integer")
    if contact.get("claim_boundary") != (
        "single-bowl contact smoke only; not a complete episode or G1"
    ):
        raise ContractError("Genesis contact probe claim boundary changed")

    bimanual = contract.get("bimanual_contact_probe", {})
    if bimanual.get("protocol_version") != "bimanual_whole_bowl_contact_v7":
        raise ContractError("Genesis bimanual contact probe protocol changed")
    for field in (
        "arm_kp",
        "arm_kv",
        "gripper_kp",
        "gripper_kv",
        "arm_force_limit",
        "gripper_force_limit",
        "bowl_friction_coefficient",
        "finger_friction_coefficient",
        "separation_z_m",
        "rotate_high_z_m",
        "clearance_half_span_m",
        "clearance_z_m",
        "grasp_half_span_m",
        "grasp_z_m",
        "lift_distance_m",
        "minimum_segment_duration_s",
        "approach_duration_s",
        "post_approach_hold_s",
        "lift_duration_s",
        "slide_duration_s",
        "slide_retreat_duration_s",
        "waypoint_settle_timeout_s",
        "minimum_lift_delta_m",
        "maximum_arm_tracking_error_rad",
        "maximum_gripper_tracking_error_m",
    ):
        value = bimanual.get(field)
        if not isinstance(value, (int, float)) or isinstance(value, bool) or value <= 0:
            raise ContractError(f"Genesis bimanual contact field {field} must be positive")
    for field in ("separation_y_m", "rotate_high_y_m"):
        if not -0.1 < float(bimanual.get(field, math.inf)) < 0.2:
            raise ContractError(f"Genesis bimanual {field} is invalid")
    if float(bimanual["clearance_half_span_m"]) <= float(bimanual["grasp_half_span_m"]):
        raise ContractError("Genesis bimanual clearance must be wider than the grasp")
    if float(bimanual["grasp_half_span_m"]) != 0.12:
        raise ContractError("Genesis bimanual opposed-pad grasp half-span changed")
    if float(bimanual["clearance_z_m"]) <= float(bimanual["grasp_z_m"]):
        raise ContractError("Genesis bimanual clearance must be above the grasp")
    if float(bimanual["minimum_lift_delta_m"]) > float(bimanual["lift_distance_m"]):
        raise ContractError("Genesis bimanual minimum lift exceeds the commanded lift")
    if bimanual.get("slide_target_xy_m") != [0.0, -0.1]:
        raise ContractError("Genesis bimanual slide target changed")
    if bimanual.get("slide_stability_policy_frames") != 12:
        raise ContractError("Genesis bimanual slide stability frame count changed")
    if bimanual.get("grasp_mode") != "opposed_closed_gripper_pads":
        raise ContractError("Genesis bimanual grasp mode changed")
    if bimanual.get("required_contact_link_substring") != "clamp":
        raise ContractError("Genesis bimanual probe must require clamp contact")
    orientations = bimanual.get("orientations_wxyz", {})
    expected_orientations = {
        "left": [0.9961946980917455, 0.0, 0.08715574274765817, 0.0],
        "right": [0.0, -0.08715574274765817, 0.0, 0.9961946980917455],
    }
    if orientations != expected_orientations:
        raise ContractError("Genesis bimanual opposed-pad orientations changed")
    if bimanual.get("slide_orientations_wxyz") != {
        "left": [1.0, 0.0, 0.0, 0.0],
        "right": [0.0, 0.0, 0.0, 1.0],
    }:
        raise ContractError("Genesis bimanual slide orientations changed")
    for orientation in orientations.values():
        if abs(sum(float(value) ** 2 for value in orientation) - 1.0) > 1e-9:
            raise ContractError("Genesis bimanual orientation must be unit length")
    expected_separation = [0.7071067811865476, 0.0, 0.0, 0.7071067811865475]
    if bimanual.get("separation_orientations_wxyz") != {
        "left": expected_separation,
        "right": expected_separation,
    }:
        raise ContractError("Genesis bimanual high-separation orientations changed")
    settle_count = bimanual.get("waypoint_settle_consecutive_steps")
    sample_interval = bimanual.get("contact_sample_interval_steps")
    for label, value in (
        ("settle count", settle_count),
        ("sample interval", sample_interval),
    ):
        if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
            raise ContractError(f"Genesis bimanual {label} must be a positive integer")
    for field in ("bowl_friction_coefficient", "finger_friction_coefficient"):
        if not 0.01 <= float(bimanual[field]) <= 5.0:
            raise ContractError(f"Genesis bimanual field {field} is outside the stable range")
    if bimanual.get("friction_semantics") != (
        "Genesis 1.2.3 pair coefficient is the maximum of the two geom coefficients"
    ):
        raise ContractError("Genesis bimanual friction semantics changed")
    if bimanual.get("claim_boundary") != (
        "bimanual single-bowl contact smoke only; not a complete episode or G1"
    ):
        raise ContractError("Genesis bimanual claim boundary changed")

    rim_hook = contract.get("bimanual_rim_hook_probe", {})
    if rim_hook.get("protocol_version") != "bimanual_shelf_vertical_lift_under_rim_hook_v22":
        raise ContractError("Genesis bimanual rim-hook protocol changed")
    for field in (
        "arm_kp",
        "arm_kv",
        "gripper_kp",
        "gripper_kv",
        "arm_force_limit",
        "gripper_force_limit",
        "bowl_friction_coefficient",
        "finger_friction_coefficient",
        "separation_z_m",
        "rotate_high_z_m",
        "clearance_half_span_m",
        "clearance_z_m",
        "grasp_half_span_m",
        "lift_half_span_m",
        "grasp_z_m",
        "lift_distance_m",
        "minimum_segment_duration_s",
        "approach_duration_s",
        "gripper_close_duration_s",
        "post_close_hold_s",
        "lift_duration_s",
        "transport_tcp_z_m",
        "transport_duration_s",
        "place_tcp_z_m",
        "place_duration_s",
        "release_duration_s",
        "retreat_duration_s",
        "waypoint_settle_timeout_s",
        "minimum_lift_delta_m",
        "maximum_arm_tracking_error_rad",
        "maximum_gripper_tracking_error_m",
    ):
        value = rim_hook.get(field)
        if not isinstance(value, (int, float)) or isinstance(value, bool) or value <= 0:
            raise ContractError(f"Genesis bimanual rim-hook field {field} must be positive")
    for field in ("separation_y_m", "rotate_high_y_m"):
        if not -0.1 < float(rim_hook.get(field, math.inf)) < 0.2:
            raise ContractError(f"Genesis bimanual rim-hook {field} is invalid")
    if float(rim_hook["clearance_half_span_m"]) <= float(rim_hook["grasp_half_span_m"]):
        raise ContractError("Genesis bimanual rim-hook clearance must be wider than grasp")
    if float(rim_hook["clearance_half_span_m"]) != 0.150:
        raise ContractError("Genesis bimanual rim-hook clearance half-span changed")
    if float(rim_hook["grasp_half_span_m"]) != 0.115:
        raise ContractError("Genesis bimanual rim-hook grasp half-span changed")
    if float(rim_hook["lift_half_span_m"]) != 0.115:
        raise ContractError("Genesis bimanual rim-hook lift half-span changed")
    if float(rim_hook["lift_half_span_m"]) != float(rim_hook["grasp_half_span_m"]):
        raise ContractError("Genesis bimanual rim-hook lift must preserve grasp span")
    if float(rim_hook["grasp_z_m"]) != 0.81:
        raise ContractError("Genesis bimanual rim-hook grasp height changed")
    if float(rim_hook["clearance_z_m"]) <= float(rim_hook["grasp_z_m"]):
        raise ContractError("Genesis bimanual rim-hook clearance must be above grasp")
    if float(rim_hook["minimum_lift_delta_m"]) > float(rim_hook["lift_distance_m"]):
        raise ContractError("Genesis bimanual rim-hook minimum lift exceeds command")
    if float(rim_hook["lift_distance_m"]) != 0.03:
        raise ContractError("Genesis bimanual rim-hook lift distance changed")
    if float(rim_hook["lift_duration_s"]) != 0.25:
        raise ContractError("Genesis bimanual rim-hook lift duration changed")
    if float(rim_hook["minimum_lift_delta_m"]) != 0.01:
        raise ContractError("Genesis bimanual rim-hook lift threshold changed")
    if rim_hook.get("transport_target_xy_m") != [0.0, -0.1]:
        raise ContractError("Genesis bimanual rim-hook transport target changed")
    if float(rim_hook["transport_tcp_z_m"]) != 0.9:
        raise ContractError("Genesis bimanual rim-hook transport height changed")
    if float(rim_hook["place_tcp_z_m"]) != 0.84:
        raise ContractError("Genesis bimanual rim-hook placement height changed")
    if rim_hook.get("stability_policy_frames") != 12:
        raise ContractError("Genesis bimanual rim-hook stability frame count changed")
    hold_open_fraction = rim_hook.get("gripper_hold_open_fraction")
    if (
        not isinstance(hold_open_fraction, (int, float))
        or isinstance(hold_open_fraction, bool)
        or float(hold_open_fraction) != 0.85
    ):
        raise ContractError("Genesis bimanual rim-hook hold-open fraction changed")
    lift_open_fraction = rim_hook.get("lift_gripper_open_fraction")
    if (
        not isinstance(lift_open_fraction, (int, float))
        or isinstance(lift_open_fraction, bool)
        or float(lift_open_fraction) != 0.65
        or float(lift_open_fraction) >= float(hold_open_fraction)
    ):
        raise ContractError("Genesis bimanual rim-hook lift-open fraction changed")
    if rim_hook.get("grasp_mode") != "opposed_horizontal_approach_signed_under_rim_hook":
        raise ContractError("Genesis bimanual rim-hook grasp mode changed")
    if rim_hook.get("required_contact_link_substring") != "clamp":
        raise ContractError("Genesis bimanual rim-hook must require clamp contact")
    expected_rim_hook_orientations = {
        "left": [0.9537169507482269, -0.3007057995042732, 0.0, 0.0],
        "right": [0.0, 0.0, -0.3007057995042732, 0.9537169507482269],
    }
    if rim_hook.get("orientations_wxyz") != expected_rim_hook_orientations:
        raise ContractError("Genesis bimanual rim-hook orientations changed")
    for orientation in expected_rim_hook_orientations.values():
        if abs(sum(float(value) ** 2 for value in orientation) - 1.0) > 1e-9:
            raise ContractError("Genesis bimanual rim-hook orientation must be unit length")
    if rim_hook.get("separation_orientations_wxyz") != {
        "left": expected_separation,
        "right": expected_separation,
    }:
        raise ContractError("Genesis bimanual rim-hook separation orientations changed")
    if rim_hook.get("orientation_semantics") != (
        "each wrist local +x points horizontally inward; the left local +y points world +y "
        "and 35 degrees downward while the right local +y mirrors it toward world -y and "
        "35 degrees downward, selecting the corresponding hook finger on both arms"
    ):
        raise ContractError("Genesis bimanual rim-hook orientation semantics changed")
    for label, value in (
        ("settle count", rim_hook.get("waypoint_settle_consecutive_steps")),
        ("sample interval", rim_hook.get("contact_sample_interval_steps")),
        ("minimum contacted fingers", rim_hook.get("minimum_contacted_fingers_per_arm")),
    ):
        if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
            raise ContractError(f"Genesis bimanual rim-hook {label} must be a positive integer")
    if int(rim_hook["minimum_contacted_fingers_per_arm"]) != 1:
        raise ContractError("Genesis bimanual rim-hook must require one hook finger per arm")
    for field in ("bowl_friction_coefficient", "finger_friction_coefficient"):
        if not 0.01 <= float(rim_hook[field]) <= 5.0:
            raise ContractError(f"Genesis bimanual rim-hook {field} is outside stable range")
    if rim_hook.get("friction_semantics") != (
        "Genesis 1.2.3 pair coefficient is the maximum of the two geom coefficients"
    ):
        raise ContractError("Genesis bimanual rim-hook friction semantics changed")
    if rim_hook.get("diagnostic_receipt_sha256") != (
        "69591965344f5b074681ca5bfa4aa1763190c6329e1ae6e19c0e442fb4dfa086"
    ):
        raise ContractError("Genesis bimanual rim-hook diagnostic receipt changed")
    if rim_hook.get("gripper_tracking_scope") != (
        "contact-free open navigation stages only; blocked symmetric closure against the rim is expected"
    ):
        raise ContractError("Genesis bimanual rim-hook tracking scope changed")
    if rim_hook.get("claim_boundary") != (
        "bimanual rim-hook single-bowl contact smoke only; not a complete episode or G1"
    ):
        raise ContractError("Genesis bimanual rim-hook claim boundary changed")
