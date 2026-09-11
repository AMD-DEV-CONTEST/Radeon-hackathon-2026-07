from __future__ import annotations

from dataclasses import dataclass
import math
from pathlib import Path
import tomllib
from typing import Any


DEFAULT_RESET_QPOS = (-1.0124, 1.5559, 1.3662, -1.6878, -1.5799, 1.7757, 1.4602, 0.04, 0.04)

COLLISION_FREE_RESET_QPOS = (
    -1.0124,
    1.0,
    1.4,
    -1.6878,
    -1.5799,
    1.7757,
    1.4602,
    0.04,
    0.04,
)

MIN_TRANSPORT_SLIP_FORCE_MARGIN_N = 10.0


@dataclass(frozen=True)
class SimulationConfig:
    backend: str
    device: str
    num_envs: int
    physics_hz: int
    control_hz: int
    camera_hz: int
    headless: bool

    def validate(self) -> None:
        if self.backend != "rocm":
            raise ValueError("The competition baseline must use the ROCm backend")
        if self.device != "cuda:0":
            raise ValueError("PyTorch exposes ROCm devices through cuda:0")
        if self.num_envs < 1:
            raise ValueError("num_envs must be positive")
        if self.physics_hz % self.control_hz != 0:
            raise ValueError("physics_hz must be divisible by control_hz")
        if self.control_hz % self.camera_hz != 0:
            raise ValueError("control_hz must be divisible by camera_hz")


@dataclass(frozen=True)
class TaskConfig:
    max_grasp_retries: int
    lift_height_m: float
    max_contact_force_n: float
    episode_seconds: float
    parcel_base_size_m: tuple[float, float, float]
    left_bin_center_m: tuple[float, float, float]
    right_bin_center_m: tuple[float, float, float]
    bin_half_extent_m: tuple[float, float]
    approach_clearance_m: float
    grasp_hand_clearance_m: float
    drop_hand_height_m: float
    position_tolerance_m: float
    release_settle_steps: int
    grasp_settle_steps: int
    approach_xy_tolerance_m: float = 0.010
    grasp_stability_steps: int = 1
    size_aware_approach_enabled: bool = False
    approach_clearance_margin_m: float = 0.0
    retry_retreat_distance_m: float = 0.0
    surface_aware_pregrasp_enabled: bool = False
    surface_aware_pregrasp_min_height_m: float = 0.150
    surface_aware_pregrasp_max_vertical_error_m: float = 0.055
    surface_aware_pregrasp_min_side_overlap_m: float = 0.020
    geometry_aware_grasp_planning_enabled: bool = False
    grasp_planning_reset_fallback_gate_enabled: bool = False
    grasp_planning_collision_filter_enabled: bool = True
    grasp_planning_manipulability_ranking_enabled: bool = True
    grasp_planning_symmetric_wrist_enabled: bool = True
    grasp_planning_retry_replan_enabled: bool = True
    grasp_planning_failed_candidate_blacklist_enabled: bool = False
    grasp_planning_waypoint_collision_gate_enabled: bool = False
    grasp_planning_stability_steps: int = 5
    grasp_planning_final_approach_step_m: float = 0.005
    grasp_planning_tall_box_height_m: float = 0.160
    grasp_planning_tall_box_final_approach_step_m: float = 0.0025
    grasp_planning_drop_step_m: float = 0.005
    grasp_planning_transport_contract_enabled: bool = False
    grasp_planning_transport_lookahead_enabled: bool = True
    grasp_planning_raise_step_m: float = 0.020
    grasp_planning_transport_step_m: float = 0.010
    grasp_planning_transfer_settle_steps: int = 2
    grasp_planning_joint_segment_resolution_rad: float = 0.025
    parcel_gripper_adapter_enabled: bool = False
    parcel_gripper_adapter_extension_m: float = 0.030
    parcel_gripper_adapter_density_kg_m3: float = 1240.0
    parcel_gripper_adapter_inertia_enabled: bool = True
    tri_suction_enabled: bool = False
    tri_suction_cup_radius_m: float = 0.012
    tri_suction_footprint_radius_m: float = 0.025
    tri_suction_cup_length_m: float = 0.012
    tri_suction_tip_offset_m: float = 0.100
    tri_suction_density_kg_m3: float = 1100.0
    tri_suction_min_sealed_cups: int = 2
    tri_suction_seal_distance_m: float = 0.008
    tri_suction_seal_angle_rad: float = 0.25
    tri_suction_translational_stiffness_n_m: float = 1800.0
    tri_suction_translational_damping_n_s_m: float = 45.0
    tri_suction_rotational_stiffness_nm_rad: float = 4.0
    tri_suction_rotational_damping_nm_s_rad: float = 0.12
    tri_suction_max_force_n: float = 30.0
    tri_suction_break_distance_m: float = 0.035
    tri_suction_break_angle_rad: float = 0.70

    def validate(self) -> None:
        if self.max_grasp_retries < 0:
            raise ValueError("max_grasp_retries cannot be negative")
        if self.lift_height_m <= 0:
            raise ValueError("lift_height_m must be positive")
        if self.max_contact_force_n <= 0:
            raise ValueError("max_contact_force_n must be positive")
        if self.episode_seconds <= 0:
            raise ValueError("episode_seconds must be positive")
        if len(self.parcel_base_size_m) != 3 or any(value <= 0 for value in self.parcel_base_size_m):
            raise ValueError("parcel_base_size_m must contain three positive values")
        for label, value in (
            ("left_bin_center_m", self.left_bin_center_m),
            ("right_bin_center_m", self.right_bin_center_m),
        ):
            if len(value) != 3:
                raise ValueError(f"{label} must contain three values")
        if len(self.bin_half_extent_m) != 2 or any(value <= 0 for value in self.bin_half_extent_m):
            raise ValueError("bin_half_extent_m must contain two positive values")
        if min(
            self.approach_clearance_m,
            self.grasp_hand_clearance_m,
            self.drop_hand_height_m,
        ) <= 0:
            raise ValueError("approach, grasp, and drop heights must be positive")
        if self.approach_clearance_m <= self.grasp_hand_clearance_m:
            raise ValueError("approach clearance must exceed grasp clearance")
        if (
            self.position_tolerance_m <= 0
            or self.approach_xy_tolerance_m <= 0
            or self.approach_xy_tolerance_m > self.position_tolerance_m
            or min(self.release_settle_steps, self.grasp_settle_steps) < 0
            or self.grasp_stability_steps < 1
        ):
            raise ValueError("position tolerance must be positive and stability steps must be positive")
        if not math.isfinite(self.approach_clearance_margin_m) or self.approach_clearance_margin_m < 0:
            raise ValueError("approach_clearance_margin_m must be finite and non-negative")
        if not math.isfinite(self.retry_retreat_distance_m) or self.retry_retreat_distance_m < 0:
            raise ValueError("retry_retreat_distance_m must be finite and non-negative")
        if (
            not math.isfinite(self.surface_aware_pregrasp_min_height_m)
            or self.surface_aware_pregrasp_min_height_m <= 0
        ):
            raise ValueError(
                "surface_aware_pregrasp_min_height_m must be finite and positive"
            )
        if (
            not math.isfinite(self.surface_aware_pregrasp_max_vertical_error_m)
            or self.surface_aware_pregrasp_max_vertical_error_m <= 0
        ):
            raise ValueError(
                "surface_aware_pregrasp_max_vertical_error_m must be finite and positive"
            )
        if (
            not math.isfinite(self.surface_aware_pregrasp_min_side_overlap_m)
            or self.surface_aware_pregrasp_min_side_overlap_m <= 0
        ):
            raise ValueError(
                "surface_aware_pregrasp_min_side_overlap_m must be finite and positive"
            )
        if self.grasp_planning_stability_steps < 1:
            raise ValueError("grasp_planning_stability_steps must be positive")
        if (
            self.grasp_planning_failed_candidate_blacklist_enabled
            and not self.grasp_planning_retry_replan_enabled
        ):
            raise ValueError(
                "grasp_planning_failed_candidate_blacklist_enabled requires "
                "grasp_planning_retry_replan_enabled"
            )
        if (
            not math.isfinite(self.grasp_planning_final_approach_step_m)
            or self.grasp_planning_final_approach_step_m <= 0
        ):
            raise ValueError(
                "grasp_planning_final_approach_step_m must be finite and positive"
            )
        if (
            not math.isfinite(self.grasp_planning_tall_box_height_m)
            or self.grasp_planning_tall_box_height_m <= 0
        ):
            raise ValueError(
                "grasp_planning_tall_box_height_m must be finite and positive"
            )
        if (
            not math.isfinite(
                self.grasp_planning_tall_box_final_approach_step_m
            )
            or self.grasp_planning_tall_box_final_approach_step_m <= 0
            or self.grasp_planning_tall_box_final_approach_step_m
            > self.grasp_planning_final_approach_step_m
        ):
            raise ValueError(
                "grasp_planning_tall_box_final_approach_step_m must be in "
                "(0, grasp_planning_final_approach_step_m]"
            )
        if (
            not math.isfinite(self.grasp_planning_drop_step_m)
            or self.grasp_planning_drop_step_m <= 0
        ):
            raise ValueError("grasp_planning_drop_step_m must be finite and positive")
        for name, value in (
            ("grasp_planning_raise_step_m", self.grasp_planning_raise_step_m),
            ("grasp_planning_transport_step_m", self.grasp_planning_transport_step_m),
        ):
            if not math.isfinite(value) or value <= 0:
                raise ValueError(f"{name} must be finite and positive")
        if self.grasp_planning_transfer_settle_steps < 1:
            raise ValueError(
                "grasp_planning_transfer_settle_steps must be positive"
            )
        if (
            not math.isfinite(self.grasp_planning_joint_segment_resolution_rad)
            or self.grasp_planning_joint_segment_resolution_rad <= 0
        ):
            raise ValueError(
                "grasp_planning_joint_segment_resolution_rad must be finite and positive"
            )
        if (
            not math.isfinite(self.parcel_gripper_adapter_extension_m)
            or not 0.005 <= self.parcel_gripper_adapter_extension_m <= 0.060
        ):
            raise ValueError(
                "parcel_gripper_adapter_extension_m must be in [0.005, 0.060]"
            )
        if (
            not math.isfinite(self.parcel_gripper_adapter_density_kg_m3)
            or not 100.0 <= self.parcel_gripper_adapter_density_kg_m3 <= 2500.0
        ):
            raise ValueError(
                "parcel_gripper_adapter_density_kg_m3 must be in [100, 2500]"
            )
        if self.parcel_gripper_adapter_enabled and self.tri_suction_enabled:
            raise ValueError(
                "parcel_gripper_adapter_enabled and tri_suction_enabled are "
                "mutually exclusive end-effector variants"
            )
        for name, value, lower, upper in (
            ("tri_suction_cup_radius_m", self.tri_suction_cup_radius_m, 0.004, 0.030),
            (
                "tri_suction_footprint_radius_m",
                self.tri_suction_footprint_radius_m,
                0.010,
                0.060,
            ),
            ("tri_suction_cup_length_m", self.tri_suction_cup_length_m, 0.004, 0.030),
            ("tri_suction_tip_offset_m", self.tri_suction_tip_offset_m, 0.060, 0.160),
            ("tri_suction_density_kg_m3", self.tri_suction_density_kg_m3, 100.0, 2500.0),
            (
                "tri_suction_translational_stiffness_n_m",
                self.tri_suction_translational_stiffness_n_m,
                100.0,
                10000.0,
            ),
            (
                "tri_suction_translational_damping_n_s_m",
                self.tri_suction_translational_damping_n_s_m,
                1.0,
                500.0,
            ),
            (
                "tri_suction_rotational_stiffness_nm_rad",
                self.tri_suction_rotational_stiffness_nm_rad,
                0.1,
                50.0,
            ),
            (
                "tri_suction_rotational_damping_nm_s_rad",
                self.tri_suction_rotational_damping_nm_s_rad,
                0.01,
                10.0,
            ),
            ("tri_suction_max_force_n", self.tri_suction_max_force_n, 1.0, 34.0),
            (
                "tri_suction_break_distance_m",
                self.tri_suction_break_distance_m,
                0.005,
                0.100,
            ),
            (
                "tri_suction_break_angle_rad",
                self.tri_suction_break_angle_rad,
                0.10,
                math.pi / 2,
            ),
            (
                "tri_suction_seal_distance_m",
                self.tri_suction_seal_distance_m,
                0.001,
                0.020,
            ),
            (
                "tri_suction_seal_angle_rad",
                self.tri_suction_seal_angle_rad,
                0.05,
                0.70,
            ),
        ):
            if not math.isfinite(value) or not lower <= value <= upper:
                raise ValueError(f"{name} must be in [{lower}, {upper}]")
        if self.tri_suction_min_sealed_cups not in {1, 2, 3}:
            raise ValueError("tri_suction_min_sealed_cups must be 1, 2, or 3")
        if (
            self.tri_suction_footprint_radius_m + self.tri_suction_cup_radius_m
            > 0.075
        ):
            raise ValueError("tri-suction footprint exceeds the Panda hand envelope")


@dataclass(frozen=True)
class ControlConfig:
    arm_kp: tuple[float, ...]
    arm_kv: tuple[float, ...]
    finger_kp: float
    finger_kv: float
    open_width_m: float
    close_force_n: float
    close_force_ramp_n_per_step: float
    max_ee_step_m: float
    final_approach_step_m: float
    approach_step_m: float | None = None
    approach_contact_brake_force_n: float | None = None
    approach_contact_brake_step_m: float = 0.01
    approach_barrier_recovery_step_m: float | None = None
    precontact_aabb_guard_distance_m: float | None = None
    approach_stiffness_scale: float = 1.0
    approach_velocity_control_enabled: bool = False
    approach_velocity_position_gain_s: float = 8.0
    approach_velocity_orientation_gain_s: float = 6.0
    approach_velocity_orientation_weight: float = 0.20
    approach_velocity_max_linear_m_s: float = 0.30
    approach_velocity_max_angular_rad_s: float = 1.50
    approach_velocity_max_joint_rad_s: float = 1.50
    approach_velocity_damping: float = 0.05
    transport_slip_recovery_enabled: bool = False
    transport_slip_relative_delta_m: float = 0.008
    transport_slip_downward_delta_m: float = 0.006
    transport_slip_min_contact_force_n: float = 1.0
    transport_slip_min_destination_distance_m: float = 0.080
    transport_slip_force_boost_n: float = 2.0
    transport_slip_force_hold_steps: int = 15
    transport_slip_setdown_regrasp_enabled: bool = False
    transport_slip_setdown_step_m: float = 0.010
    transport_slip_setdown_max_steps: int = 20
    collision_checked_reset_enabled: bool = False
    collision_free_reset_qpos: tuple[float, ...] = COLLISION_FREE_RESET_QPOS
    reset_qpos: tuple[float, ...] = DEFAULT_RESET_QPOS

    def validate(self) -> None:
        if len(self.arm_kp) != 7 or len(self.arm_kv) != 7:
            raise ValueError("arm gains must contain seven values")
        if any(value <= 0 for value in (*self.arm_kp, *self.arm_kv)):
            raise ValueError("arm gains must be positive")
        if min(
            self.finger_kp,
            self.finger_kv,
            self.open_width_m,
            self.close_force_n,
            self.close_force_ramp_n_per_step,
        ) <= 0:
            raise ValueError("finger gains, width, force, and force ramp must be positive")
        if self.max_ee_step_m <= 0 or self.final_approach_step_m <= 0:
            raise ValueError("Cartesian step limits must be positive")
        if self.final_approach_step_m > self.max_ee_step_m:
            raise ValueError("final_approach_step_m cannot exceed max_ee_step_m")
        if self.approach_step_m is not None and (
            self.approach_step_m <= 0 or self.approach_step_m > self.max_ee_step_m
        ):
            raise ValueError("approach_step_m must be positive and cannot exceed max_ee_step_m")
        if self.approach_contact_brake_force_n is not None and (
            self.approach_contact_brake_force_n < 0
            or self.approach_contact_brake_force_n >= 35.0
        ):
            raise ValueError("approach_contact_brake_force_n must be in [0, 35)")
        if self.approach_contact_brake_step_m <= 0 or (
            self.approach_contact_brake_step_m > self.max_ee_step_m
        ):
            raise ValueError(
                "approach_contact_brake_step_m must be positive and cannot exceed max_ee_step_m"
            )
        if self.approach_barrier_recovery_step_m is not None and (
            not math.isfinite(self.approach_barrier_recovery_step_m)
            or self.approach_barrier_recovery_step_m <= 0
            or self.approach_barrier_recovery_step_m > self.max_ee_step_m * 4
        ):
            raise ValueError(
                "approach_barrier_recovery_step_m must be in (0, 4 * max_ee_step_m] when set"
            )
        if self.precontact_aabb_guard_distance_m is not None and (
            not math.isfinite(self.precontact_aabb_guard_distance_m)
            or self.precontact_aabb_guard_distance_m <= 0
            or self.precontact_aabb_guard_distance_m > self.max_ee_step_m * 4
        ):
            raise ValueError(
                "precontact_aabb_guard_distance_m must be in (0, 4 * max_ee_step_m] when set"
            )
        if (
            not math.isfinite(self.approach_stiffness_scale)
            or self.approach_stiffness_scale <= 0
            or self.approach_stiffness_scale > 1
        ):
            raise ValueError("approach_stiffness_scale must be in (0, 1]")
        velocity_parameters = (
            self.approach_velocity_position_gain_s,
            self.approach_velocity_orientation_gain_s,
            self.approach_velocity_max_linear_m_s,
            self.approach_velocity_max_angular_rad_s,
            self.approach_velocity_max_joint_rad_s,
            self.approach_velocity_damping,
        )
        if any(not math.isfinite(value) or value <= 0 for value in velocity_parameters):
            raise ValueError("approach velocity-control parameters must be positive and finite")
        if self.approach_velocity_damping > 1.0:
            raise ValueError("approach_velocity_damping must be at most 1.0")
        if not 0.0 <= self.approach_velocity_orientation_weight <= 1.0:
            raise ValueError("approach_velocity_orientation_weight must be in [0, 1]")
        slip_positive_parameters = (
            self.transport_slip_relative_delta_m,
            self.transport_slip_downward_delta_m,
            self.transport_slip_min_destination_distance_m,
            self.transport_slip_force_boost_n,
        )
        if any(
            not math.isfinite(value) or value <= 0
            for value in slip_positive_parameters
        ):
            raise ValueError(
                "transport slip thresholds, destination distance, and force boost "
                "must be positive and finite"
            )
        if (
            not math.isfinite(self.transport_slip_min_contact_force_n)
            or self.transport_slip_min_contact_force_n < 0
        ):
            raise ValueError(
                "transport_slip_min_contact_force_n must be non-negative and finite"
            )
        if self.transport_slip_force_hold_steps < 1:
            raise ValueError("transport_slip_force_hold_steps must be positive")
        if (
            not math.isfinite(self.transport_slip_setdown_step_m)
            or self.transport_slip_setdown_step_m <= 0
            or self.transport_slip_setdown_step_m > self.max_ee_step_m
        ):
            raise ValueError(
                "transport_slip_setdown_step_m must be in (0, max_ee_step_m]"
            )
        if self.transport_slip_setdown_max_steps < 1:
            raise ValueError("transport_slip_setdown_max_steps must be positive")
        if len(self.collision_free_reset_qpos) != 9 or any(
            not math.isfinite(value) for value in self.collision_free_reset_qpos
        ):
            raise ValueError(
                "collision_free_reset_qpos must contain nine finite joint positions"
            )
        if len(self.reset_qpos) != 9 or any(not math.isfinite(value) for value in self.reset_qpos):
            raise ValueError("reset_qpos must contain nine finite joint positions")


@dataclass(frozen=True)
class OutputConfig:
    root_dir: str
    task_instruction: str
    record_first_episode: bool
    save_sensor_frames: bool

    def validate(self) -> None:
        if not self.root_dir.strip():
            raise ValueError("output root_dir is required")
        if not self.task_instruction.strip():
            raise ValueError("task_instruction is required")


@dataclass(frozen=True)
class SensorsConfig:
    rgb: bool
    depth: bool
    proprioception: bool
    contact_force: bool
    image_width: int
    image_height: int

    def validate(self) -> None:
        if not any((self.rgb, self.depth, self.proprioception, self.contact_force)):
            raise ValueError("at least one observation modality must be enabled")
        if self.image_width < 32 or self.image_height < 32:
            raise ValueError("camera resolution must be at least 32x32")


@dataclass(frozen=True)
class RandomizationConfig:
    enabled: bool
    parcel_size_scale_min: float
    parcel_size_scale_max: float
    parcel_mass_kg_min: float
    parcel_mass_kg_max: float
    friction_min: float
    friction_max: float
    camera_position_noise_m: float
    action_delay_steps_max: int
    parcel_position_x_min: float
    parcel_position_x_max: float
    parcel_position_y_min: float
    parcel_position_y_max: float
    parcel_yaw_rad_min: float
    parcel_yaw_rad_max: float
    catalog_block_size: int = 20

    def validate(self) -> None:
        ranges = (
            ("parcel size", self.parcel_size_scale_min, self.parcel_size_scale_max),
            ("parcel mass", self.parcel_mass_kg_min, self.parcel_mass_kg_max),
            ("friction", self.friction_min, self.friction_max),
            ("parcel x", self.parcel_position_x_min, self.parcel_position_x_max),
            ("parcel y", self.parcel_position_y_min, self.parcel_position_y_max),
            ("parcel yaw", self.parcel_yaw_rad_min, self.parcel_yaw_rad_max),
        )
        for label, lower, upper in ranges:
            if lower > upper:
                raise ValueError(f"{label} minimum cannot exceed maximum")
        if self.parcel_size_scale_min <= 0 or self.parcel_mass_kg_min <= 0:
            raise ValueError("parcel size and mass must remain positive")
        if self.friction_min <= 0:
            raise ValueError("friction must remain positive")
        if self.camera_position_noise_m < 0 or self.action_delay_steps_max < 0:
            raise ValueError("noise and delay cannot be negative")
        if self.catalog_block_size < 1:
            raise ValueError("catalog_block_size must be positive")


@dataclass(frozen=True)
class ParcelProfileConfig:
    profile_id: str
    shape: str
    orientation_mode: str
    handling_class: str
    material: str
    selection_weight: float
    evaluation_only: bool
    dimensions_min_m: tuple[float, float, float]
    dimensions_max_m: tuple[float, float, float]
    mass_kg_min: float
    mass_kg_max: float
    friction_min: float
    friction_max: float
    provenance: str
    source_url: str = ""
    rolling_friction: float = 0.0
    final_approach_step_m: float | None = None
    lift_step_m: float | None = None
    finger_friction: float | None = None
    close_force_n: float | None = None
    pregrasp_tolerance_m: float | None = None
    grasp_stability_steps: int | None = None

    def validate(self) -> None:
        if not self.profile_id.strip() or not self.material.strip() or not self.provenance.strip():
            raise ValueError("parcel profile id, material, and provenance are required")
        if self.source_url and not self.source_url.startswith(("https://", "http://")):
            raise ValueError("parcel profile source_url must be an http(s) URL")
        if self.rolling_friction < 0:
            raise ValueError("parcel profile rolling_friction cannot be negative")
        if self.final_approach_step_m is not None and self.final_approach_step_m <= 0:
            raise ValueError("parcel profile final_approach_step_m must be positive when set")
        if self.lift_step_m is not None and self.lift_step_m <= 0:
            raise ValueError("parcel profile lift_step_m must be positive when set")
        if self.finger_friction is not None and not 0 < self.finger_friction <= 5:
            raise ValueError("parcel profile finger_friction must be in (0, 5] when set")
        if self.close_force_n is not None and not 0 < self.close_force_n <= 100:
            raise ValueError("parcel profile close_force_n must be in (0, 100] when set")
        if self.pregrasp_tolerance_m is not None and self.pregrasp_tolerance_m <= 0:
            raise ValueError("parcel profile pregrasp_tolerance_m must be positive when set")
        if self.grasp_stability_steps is not None and self.grasp_stability_steps < 1:
            raise ValueError("parcel profile grasp_stability_steps must be positive when set")
        if self.shape not in {"box", "cylinder"}:
            raise ValueError(f"unsupported parcel shape: {self.shape}")
        if self.orientation_mode not in {"yaw", "upright", "horizontal"}:
            raise ValueError(f"unsupported parcel orientation: {self.orientation_mode}")
        if self.shape == "box" and self.orientation_mode != "yaw":
            raise ValueError("box profiles must use yaw orientation")
        if self.shape == "cylinder" and self.orientation_mode == "yaw":
            raise ValueError("cylinder profiles must be upright or horizontal")
        if self.handling_class not in {"parallel_jaw", "suction_required", "cradle_required"}:
            raise ValueError(f"unsupported handling class: {self.handling_class}")
        if self.selection_weight < 0:
            raise ValueError("parcel profile selection weight cannot be negative")
        if self.evaluation_only and self.selection_weight != 0:
            raise ValueError("evaluation-only parcel profiles must have zero training weight")
        if len(self.dimensions_min_m) != 3 or len(self.dimensions_max_m) != 3:
            raise ValueError("parcel profile dimensions must contain three values")
        for lower, upper in zip(self.dimensions_min_m, self.dimensions_max_m, strict=True):
            if lower <= 0 or lower > upper:
                raise ValueError("parcel profile dimensions must be positive ordered ranges")
        for label, lower, upper in (
            ("mass", self.mass_kg_min, self.mass_kg_max),
            ("friction", self.friction_min, self.friction_max),
        ):
            if lower <= 0 or lower > upper:
                raise ValueError(f"parcel profile {label} must be a positive ordered range")


@dataclass(frozen=True)
class ExperimentConfig:
    name: str
    seed: int
    simulation: SimulationConfig
    sensors: SensorsConfig
    task: TaskConfig
    control: ControlConfig
    output: OutputConfig
    randomization: RandomizationConfig
    parcel_profiles: tuple[ParcelProfileConfig, ...]

    def validate(self) -> None:
        if not self.name:
            raise ValueError("project name is required")
        self.simulation.validate()
        self.sensors.validate()
        self.task.validate()
        self.control.validate()
        if (
            self.control.transport_slip_recovery_enabled
            and not self.task.grasp_planning_transport_contract_enabled
        ):
            raise ValueError(
                "transport_slip_recovery_enabled requires "
                "grasp_planning_transport_contract_enabled"
            )
        if (
            self.control.transport_slip_setdown_regrasp_enabled
            and not self.task.grasp_planning_transport_contract_enabled
        ):
            raise ValueError(
                "transport_slip_setdown_regrasp_enabled requires "
                "grasp_planning_transport_contract_enabled"
            )
        if (
            not self.task.grasp_planning_transport_lookahead_enabled
            and not self.task.grasp_planning_transport_contract_enabled
        ):
            raise ValueError(
                "disabling grasp_planning_transport_lookahead_enabled requires "
                "grasp_planning_transport_contract_enabled"
            )
        if self.control.transport_slip_recovery_enabled and (
            self.control.close_force_n + self.control.transport_slip_force_boost_n
            > self.task.max_contact_force_n - MIN_TRANSPORT_SLIP_FORCE_MARGIN_N
        ):
            raise ValueError(
                "transport slip close-force target must remain at least "
                f"{MIN_TRANSPORT_SLIP_FORCE_MARGIN_N:.0f} N below max_contact_force_n"
            )
        if (
            self.task.grasp_planning_final_approach_step_m
            > self.control.max_ee_step_m
        ):
            raise ValueError(
                "grasp_planning_final_approach_step_m cannot exceed max_ee_step_m"
            )
        for name, value in (
            (
                "grasp_planning_raise_step_m",
                self.task.grasp_planning_raise_step_m,
            ),
            (
                "grasp_planning_transport_step_m",
                self.task.grasp_planning_transport_step_m,
            ),
        ):
            if value > self.control.max_ee_step_m:
                raise ValueError(f"{name} cannot exceed max_ee_step_m")
        if (
            self.task.grasp_planning_reset_fallback_gate_enabled
            and not self.task.geometry_aware_grasp_planning_enabled
        ):
            raise ValueError(
                "grasp_planning_reset_fallback_gate_enabled requires "
                "geometry_aware_grasp_planning_enabled"
            )
        if (
            self.task.grasp_planning_reset_fallback_gate_enabled
            and not self.control.collision_checked_reset_enabled
        ):
            raise ValueError(
                "grasp_planning_reset_fallback_gate_enabled requires "
                "collision_checked_reset_enabled"
            )
        self.output.validate()
        self.randomization.validate()
        profile_ids = [profile.profile_id for profile in self.parcel_profiles]
        if len(profile_ids) != len(set(profile_ids)):
            raise ValueError("parcel profile ids must be unique")
        for profile in self.parcel_profiles:
            profile.validate()
        training_profiles = [profile for profile in self.parcel_profiles if not profile.evaluation_only]
        if self.parcel_profiles:
            if not training_profiles:
                raise ValueError("a parcel catalog requires at least one training profile")
            total_weight = sum(profile.selection_weight for profile in training_profiles)
            if abs(total_weight - 1.0) > 1e-9:
                raise ValueError("training parcel profile weights must sum to 1")
            allocated = [
                profile.selection_weight * self.randomization.catalog_block_size
                for profile in training_profiles
            ]
            if any(abs(value - round(value)) > 1e-9 for value in allocated):
                raise ValueError("catalog block size must allocate an integer count to every profile")


def _tuple_values(raw: dict[str, Any], *keys: str) -> dict[str, Any]:
    converted = dict(raw)
    for key in keys:
        if key in converted:
            converted[key] = tuple(float(value) for value in converted[key])
    return converted


def load_config(path: str | Path) -> ExperimentConfig:
    with Path(path).open("rb") as handle:
        raw = tomllib.load(handle)

    parcel_profiles = tuple(
        ParcelProfileConfig(
            **_tuple_values(
                profile,
                "dimensions_min_m",
                "dimensions_max_m",
            )
        )
        for profile in raw.get("parcel_profiles", ())
    )
    config = ExperimentConfig(
        name=str(raw["project"]["name"]),
        seed=int(raw["project"]["seed"]),
        simulation=SimulationConfig(**raw["simulation"]),
        sensors=SensorsConfig(**raw["sensors"]),
        task=TaskConfig(
            **_tuple_values(
                raw["task"],
                "parcel_base_size_m",
                "left_bin_center_m",
                "right_bin_center_m",
                "bin_half_extent_m",
            )
        ),
        control=ControlConfig(
            **_tuple_values(
                raw["control"],
                "arm_kp",
                "arm_kv",
                "collision_free_reset_qpos",
                "reset_qpos",
            )
        ),
        output=OutputConfig(**raw["output"]),
        randomization=RandomizationConfig(**raw["randomization"]),
        parcel_profiles=parcel_profiles,
    )
    config.validate()
    return config
