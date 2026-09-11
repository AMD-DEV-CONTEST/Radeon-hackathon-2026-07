from __future__ import annotations

import math

from .config import ExperimentConfig
from .contracts import CartesianAction, ControlDecision, RobotState
from .randomization import ParcelSample
from .state_machine import Command


DOWNWARD_QUATERNION = (0.0, 1.0, 0.0, 0.0)
SAFE_WRIST_ALIGNMENT_HEIGHT_TOLERANCE_M = 0.010
SAFE_WRIST_ALIGNMENT_ORIENTATION_TOLERANCE_RAD = 0.05


def canonical_grasp_yaw(yaw_rad: float, max_abs_yaw_rad: float = math.pi / 3) -> float:
    """Exploit parallel-jaw symmetry while avoiding uncomfortable wrist rotations."""
    wrapped = (yaw_rad + math.pi / 2) % math.pi - math.pi / 2
    return wrapped if abs(wrapped) <= max_abs_yaw_rad else 0.0


def profile_grasp_yaw(sample: ParcelSample) -> float:
    """Choose a geometry-aware wrist yaw without changing the legacy baseline."""
    if sample.handling_class == "suction_required":
        return 0.0
    if sample.profile_id == "legacy_box":
        return canonical_grasp_yaw(sample.yaw_rad)
    if sample.shape == "cylinder" and sample.orientation_mode == "upright":
        return 0.0
    if sample.shape == "cylinder" and sample.orientation_mode == "horizontal":
        # Keep the fingers parallel to the tube axis so jaw closure crosses its diameter.
        return canonical_grasp_yaw(sample.yaw_rad, max_abs_yaw_rad=math.pi / 2)
    return canonical_grasp_yaw(sample.yaw_rad, max_abs_yaw_rad=math.pi / 2)


class ScriptedPickPlaceExpert:
    """Ground-truth Cartesian expert used before a visual policy is trained."""

    def __init__(self, config: ExperimentConfig, sample: ParcelSample) -> None:
        self.config = config
        self.sample = sample
        size_z = (
            sample.dimensions_m[2]
            if sample.dimensions_m is not None
            else config.task.parcel_base_size_m[2] * sample.size_scale_xyz[2]
        )
        self._initial_parcel_z = size_z / 2
        self._grasp_origin_xyz: tuple[float, float, float] | None = None
        self._planned_grasp_position: tuple[float, float, float] | None = None
        self._descent_committed = False
        self._wrist_alignment_position: tuple[float, float, float] | None = None
        self._wrist_alignment_complete = False
        self._drop_descent_committed = False
        self._transport_phase = "inactive"
        self._transport_reference_position: tuple[float, float, float] | None = None
        self._transfer_raise_stable_steps = 0
        self._transfer_position_stable_steps = 0
        self._retry_retreat_pending = False
        self._last_retry_count = 0
        half_yaw = profile_grasp_yaw(sample) / 2
        self._grasp_quaternion = (0.0, math.cos(half_yaw), math.sin(half_yaw), 0.0)

    @property
    def destination_position(self) -> tuple[float, float, float]:
        if self.sample.destination == "left":
            return self.config.task.left_bin_center_m
        return self.config.task.right_bin_center_m

    def action(self, decision: ControlDecision, state: RobotState) -> CartesianAction:
        if decision.retry_count != self._last_retry_count:
            self._descent_committed = False
            self._reset_wrist_alignment()
            self._drop_descent_committed = False
            self._reset_transport_contract(
                planned=self._planned_grasp_position is not None
            )
            self._grasp_origin_xyz = None
            self._retry_retreat_pending = (
                decision.retry_count > 0
                and self.config.task.retry_retreat_distance_m > 0
            )
            self._last_retry_count = decision.retry_count
        command = Command(decision.command)
        current = state.end_effector_pose[:3]
        parcel = state.parcel_pose[:3]

        if command == Command.MOVE_PREGRASP:
            desired = self._retry_or_safe_approach_position(current, parcel)
        elif command == Command.MOVE_LIFT:
            grasp_origin = self._grasp_origin_xyz or self.pregrasp_position(
                state.parcel_pose
            )
            desired = (
                grasp_origin[0],
                grasp_origin[1],
                grasp_origin[2] + self.config.task.lift_height_m,
            )
        elif command == Command.MOVE_DROP:
            desired = self._safe_drop_position(current)
        elif command == Command.MOVE_RECOVERY_SETDOWN:
            desired = self.recovery_setdown_position(current)
        else:
            desired = tuple(float(value) for value in current)
        if command == Command.CLOSE_GRIPPER:
            self._grasp_origin_xyz = self.pregrasp_position(state.parcel_pose)

        step_limit = self.config.control.max_ee_step_m
        if command == Command.MOVE_PREGRASP:
            if self.config.control.approach_step_m is not None:
                step_limit = min(step_limit, self.config.control.approach_step_m)
            brake_threshold = self.config.control.approach_contact_brake_force_n
            if (
                brake_threshold is not None
                and state.gripper_contact_force_n >= brake_threshold
            ):
                desired = self._contact_brake_position(current, parcel)
                step_limit = min(step_limit, self.config.control.approach_contact_brake_step_m)
            if self._is_final_approach(current, parcel):
                step_limit = min(step_limit, self.config.control.final_approach_step_m)
                if self.sample.final_approach_step_m is not None:
                    step_limit = min(step_limit, self.sample.final_approach_step_m)
                if self._planned_grasp_position is not None:
                    step_limit = min(
                        step_limit,
                        self.planned_final_approach_step_m(),
                    )
            barrier_step = self.config.control.approach_barrier_recovery_step_m
            if barrier_step is not None and not self._retry_retreat_pending:
                target = self.pregrasp_position(state.parcel_pose)
                transit_z = self._transit_height(target)
                horizontal_distance = math.hypot(
                    current[0] - target[0], current[1] - target[1]
                )
                vertical_deficit = transit_z - current[2]
                if (
                    horizontal_distance > self.config.task.position_tolerance_m
                    and vertical_deficit > self.config.task.position_tolerance_m
                ):
                    # The nominal target is already the transit height. Increase
                    # only this vertical recovery step so lag cannot preserve a
                    # low, collision-prone end-effector state while translating.
                    step_limit = max(step_limit, min(barrier_step, vertical_deficit))
        elif command == Command.MOVE_LIFT and self.sample.lift_step_m is not None:
            step_limit = min(step_limit, self.sample.lift_step_m)
        elif command == Command.MOVE_RECOVERY_SETDOWN:
            step_limit = min(
                step_limit,
                self.config.control.transport_slip_setdown_step_m,
            )
        elif command == Command.MOVE_DROP and self._planned_grasp_position is not None:
            if self._drop_descent_committed:
                step_limit = min(
                    step_limit,
                    self.config.task.grasp_planning_drop_step_m,
                )
            elif self.config.task.grasp_planning_transport_contract_enabled:
                planned_step = (
                    self.config.task.grasp_planning_raise_step_m
                    if self._transport_phase in {"raise", "raise_settle"}
                    else self.config.task.grasp_planning_transport_step_m
                )
                step_limit = min(step_limit, planned_step)
        target_quaternion = self._grasp_quaternion
        if command == Command.MOVE_PREGRASP:
            desired, target_quaternion = self._staged_pregrasp_target(
                current,
                state.end_effector_pose[3:7],
                state.parcel_pose,
                desired,
            )
        if (
            command == Command.MOVE_DROP
            and self._planned_transport_contract_active()
            and not self._drop_descent_committed
            and self.config.task.grasp_planning_transport_lookahead_enabled
        ):
            target = self._bounded_transport_reference(current, desired, step_limit)
        else:
            target = self._bounded_step(current, desired, step_limit)
        gripper = 1.0 if command in {
            Command.SEARCH,
            Command.MOVE_PREGRASP,
            Command.OPEN_GRIPPER,
        } else -1.0
        return CartesianAction(
            target_position=target,
            target_quaternion=target_quaternion,
            gripper=gripper,
            command=command.value,
        )

    def _staged_pregrasp_target(
        self,
        current: tuple[float, ...],
        current_quaternion: tuple[float, ...],
        parcel_pose: tuple[float, ...],
        desired: tuple[float, float, float],
    ) -> tuple[
        tuple[float, float, float],
        tuple[float, float, float, float],
    ]:
        """Separate raise, wrist alignment, and translation for side grasps."""
        pregrasp = self.pregrasp_position(parcel_pose)
        transit_z = self._transit_height(pregrasp)
        horizontal_distance = math.hypot(
            current[0] - pregrasp[0], current[1] - pregrasp[1]
        )
        if horizontal_distance <= self.config.task.position_tolerance_m:
            return desired, self._grasp_quaternion

        planned_side_grasp = (
            self._planned_grasp_position is not None
            and self.sample.shape == "cylinder"
            and self.sample.orientation_mode == "horizontal"
        )
        if not planned_side_grasp or self._descent_committed:
            if current[2] < transit_z - self.config.task.position_tolerance_m:
                return desired, DOWNWARD_QUATERNION
            return desired, self._grasp_quaternion

        if (
            self._wrist_alignment_position is None
            and current[2] < transit_z - SAFE_WRIST_ALIGNMENT_HEIGHT_TOLERANCE_M
        ):
            return (current[0], current[1], transit_z), DOWNWARD_QUATERNION

        if self._wrist_alignment_position is None:
            self._wrist_alignment_position = tuple(float(value) for value in current)

        if not self._wrist_alignment_complete and self._quaternion_error_rad(
            current_quaternion,
            self._grasp_quaternion,
        ) > SAFE_WRIST_ALIGNMENT_ORIENTATION_TOLERANCE_RAD:
            return self._wrist_alignment_position, self._grasp_quaternion

        self._wrist_alignment_complete = True
        return (pregrasp[0], pregrasp[1], transit_z), self._grasp_quaternion

    def _reset_wrist_alignment(self) -> None:
        self._wrist_alignment_position = None
        self._wrist_alignment_complete = False

    @staticmethod
    def _quaternion_error_rad(
        current: tuple[float, ...],
        target: tuple[float, ...],
    ) -> float:
        current_norm = math.sqrt(sum(float(value) ** 2 for value in current))
        target_norm = math.sqrt(sum(float(value) ** 2 for value in target))
        if current_norm <= 1e-12 or target_norm <= 1e-12:
            return math.inf
        dot = abs(
            sum(
                float(left) * float(right)
                for left, right in zip(current, target, strict=True)
            )
            / (current_norm * target_norm)
        )
        return 2.0 * math.acos(min(1.0, max(-1.0, dot)))

    def pregrasp_position(self, parcel_pose: tuple[float, ...]) -> tuple[float, float, float]:
        if self._planned_grasp_position is not None:
            return self._planned_grasp_position
        return (
            parcel_pose[0],
            parcel_pose[1],
            parcel_pose[2] + self.grasp_hand_clearance_m(),
        )

    def recovery_setdown_position(
        self,
        current_position: tuple[float, ...],
    ) -> tuple[float, float, float]:
        """Lower vertically to the original table-height grasp envelope."""
        return (
            float(current_position[0]),
            float(current_position[1]),
            self._initial_parcel_z + self.grasp_hand_clearance_m(),
        )

    def set_planned_grasp_pose(
        self,
        position: tuple[float, float, float],
        quaternion: tuple[float, float, float, float],
    ) -> None:
        if not all(math.isfinite(value) for value in (*position, *quaternion)):
            raise ValueError("planned grasp pose must be finite")
        quaternion_norm = math.sqrt(sum(value * value for value in quaternion))
        if not math.isclose(quaternion_norm, 1.0, rel_tol=0.0, abs_tol=1e-5):
            raise ValueError("planned grasp quaternion must be normalized")
        self._planned_grasp_position = tuple(float(value) for value in position)
        self._grasp_quaternion = tuple(float(value) for value in quaternion)
        self._descent_committed = False
        self._reset_wrist_alignment()
        self._reset_transport_contract(planned=True)

    def clear_planned_grasp_pose(self) -> None:
        self._planned_grasp_position = None
        half_yaw = profile_grasp_yaw(self.sample) / 2
        self._grasp_quaternion = (
            0.0,
            math.cos(half_yaw),
            math.sin(half_yaw),
            0.0,
        )
        self._descent_committed = False
        self._reset_wrist_alignment()
        self._reset_transport_contract()

    @property
    def transport_phase(self) -> str:
        """Expose the planned payload phase for trace attribution."""
        return self._transport_phase

    def grasp_hand_clearance_m(self) -> float:
        if self.sample.handling_class == "suction_required":
            dimensions = self.sample.dimensions_m or tuple(
                base * scale
                for base, scale in zip(
                    self.config.task.parcel_base_size_m,
                    self.sample.size_scale_xyz,
                    strict=True,
                )
            )
            vertical_extent = dimensions[2] / 2.0
            return (
                vertical_extent
                + self.config.task.tri_suction_tip_offset_m
                + self.config.task.tri_suction_cup_length_m
            )
        clearance = self.config.task.grasp_hand_clearance_m
        if self.sample.shape == "cylinder" and self.sample.orientation_mode == "upright":
            return clearance + 0.008
        return clearance

    def planned_final_approach_step_m(self) -> float:
        """Reduce pre-contact travel again for boxes in the tallest risk band."""
        dimensions = self.sample.dimensions_m
        if (
            self.sample.shape == "box"
            and dimensions is not None
            and dimensions[2] >= self.config.task.grasp_planning_tall_box_height_m
        ):
            return self.config.task.grasp_planning_tall_box_final_approach_step_m
        return self.config.task.grasp_planning_final_approach_step_m

    def approach_clearance_m(self) -> float:
        """Return the horizontal-transit clearance for the current parcel.

        The legacy value is retained by default.  When enabled, only the
        parcel's vertical envelope above the baseline parcel is added, plus a
        separately audited margin.  This keeps the candidate causal: it changes
        the transit height without changing reset pose, physics, or the final
        grasp target.
        """
        base_clearance = self.config.task.approach_clearance_m
        if not self.config.task.size_aware_approach_enabled:
            return base_clearance
        dimensions = self.sample.dimensions_m or tuple(
            base * scale
            for base, scale in zip(
                self.config.task.parcel_base_size_m,
                self.sample.size_scale_xyz,
                strict=True,
            )
        )
        if self.sample.shape == "cylinder" and self.sample.orientation_mode == "horizontal":
            vertical_extent = dimensions[1]
        else:
            vertical_extent = dimensions[2] / 2.0
        baseline_extent = self.config.task.parcel_base_size_m[2] / 2.0
        return (
            base_clearance
            + max(0.0, vertical_extent - baseline_extent)
            + self.config.task.approach_clearance_margin_m
        )

    def pregrasp_tolerance_m(self) -> float:
        """Scale the close-pose window by grasp surface size and shape."""
        if self.sample.pregrasp_tolerance_m is not None:
            return self.sample.pregrasp_tolerance_m
        dimensions = self.sample.dimensions_m or tuple(
            base * scale
            for base, scale in zip(
                self.config.task.parcel_base_size_m,
                self.sample.size_scale_xyz,
                strict=True,
            )
        )
        if self.sample.shape == "cylinder":
            return max(self.config.task.position_tolerance_m, 0.035)
        is_flat_parcel = max(dimensions[:2]) > 0.12 and dimensions[2] <= 0.04
        if is_flat_parcel:
            return min(self.config.task.position_tolerance_m, 0.010)
        has_large_grasp_surface = max(dimensions[:2]) > 0.12 and dimensions[2] > 0.04
        if has_large_grasp_surface:
            return max(self.config.task.position_tolerance_m, 0.035)
        return self.config.task.position_tolerance_m

    def at_pregrasp(
        self,
        end_effector_position: tuple[float, ...],
        parcel_pose: tuple[float, ...],
    ) -> bool:
        """Test grasp capture while preserving the historical spherical default."""
        target = self.pregrasp_position(parcel_pose)
        tolerance = self.pregrasp_tolerance_m()
        if self._planned_grasp_position is not None:
            planned_tolerance = min(
                tolerance,
                self.config.task.approach_xy_tolerance_m,
            )
            return math.dist(end_effector_position, target) <= planned_tolerance
        if not self.config.task.surface_aware_pregrasp_enabled:
            return math.dist(end_effector_position, target) <= tolerance

        dimensions = self.sample.dimensions_m or tuple(
            base * scale
            for base, scale in zip(
                self.config.task.parcel_base_size_m,
                self.sample.size_scale_xyz,
                strict=True,
            )
        )
        is_nonflat_box = (
            self.sample.shape == "box"
            and max(dimensions[:2]) > 0.12
            and dimensions[2]
            >= self.config.task.surface_aware_pregrasp_min_height_m
            and self.sample.pregrasp_tolerance_m is None
        )
        if not is_nonflat_box:
            return math.dist(end_effector_position, target) <= tolerance

        horizontal_error = math.hypot(
            end_effector_position[0] - target[0],
            end_effector_position[1] - target[1],
        )
        vertical_error = end_effector_position[2] - target[2]
        usable_upper_band = max(
            tolerance,
            min(
                self.config.task.surface_aware_pregrasp_max_vertical_error_m,
                dimensions[2] / 2
                - self.config.task.surface_aware_pregrasp_min_side_overlap_m,
            ),
        )
        return (
            horizontal_error <= self.config.task.approach_xy_tolerance_m
            and -tolerance <= vertical_error <= usable_upper_band
        )

    def _safe_approach_position(
        self,
        current: tuple[float, ...],
        parcel_pose: tuple[float, ...],
    ) -> tuple[float, float, float]:
        tolerance = self.config.task.approach_xy_tolerance_m
        target = self.pregrasp_position(parcel_pose)
        transit_z = self._transit_height(target)
        horizontal_distance = math.hypot(
            current[0] - target[0],
            current[1] - target[1],
        )

        if self._descent_committed:
            return target
        if horizontal_distance > tolerance and current[2] < transit_z - tolerance:
            return (current[0], current[1], transit_z)
        if horizontal_distance > tolerance:
            return (target[0], target[1], transit_z)
        self._descent_committed = True
        return target

    def _transit_height(
        self,
        grasp_position: tuple[float, float, float],
    ) -> float:
        return (
            grasp_position[2]
            + self.approach_clearance_m()
            - self.grasp_hand_clearance_m()
        )

    def _retry_or_safe_approach_position(
        self,
        current: tuple[float, ...],
        parcel_pose: tuple[float, ...],
    ) -> tuple[float, float, float]:
        """Create separation before re-approaching a parcel that moved on retry."""
        if not self._retry_retreat_pending:
            return self._safe_approach_position(current, parcel_pose)

        retreat_distance = self.config.task.retry_retreat_distance_m
        horizontal_distance = math.hypot(
            current[0] - parcel_pose[0],
            current[1] - parcel_pose[1],
        )
        if horizontal_distance >= retreat_distance:
            self._retry_retreat_pending = False
            return self._safe_approach_position(current, parcel_pose)

        if horizontal_distance > 1e-6:
            direction_x = (current[0] - parcel_pose[0]) / horizontal_distance
            direction_y = (current[1] - parcel_pose[1]) / horizontal_distance
        else:
            direction_x, direction_y = 1.0, 0.0
        retreat_z = max(
            current[2],
            parcel_pose[2] + self.grasp_hand_clearance_m() + 0.03,
        )
        return (
            parcel_pose[0] + direction_x * retreat_distance,
            parcel_pose[1] + direction_y * retreat_distance,
            retreat_z,
        )

    def _contact_brake_position(
        self,
        current: tuple[float, ...],
        parcel_pose: tuple[float, ...],
    ) -> tuple[float, float, float]:
        """Leave an incipient approach contact before issuing another transit move."""
        transit_z = self._transit_height(self.pregrasp_position(parcel_pose))
        if current[2] < transit_z - self.config.task.position_tolerance_m:
            return current[0], current[1], transit_z
        dx = current[0] - parcel_pose[0]
        dy = current[1] - parcel_pose[1]
        distance = math.hypot(dx, dy)
        if distance > 1e-6:
            retreat = self.config.control.approach_contact_brake_step_m
            return (
                current[0] + retreat * dx / distance,
                current[1] + retreat * dy / distance,
                current[2],
            )
        return (
            current[0],
            current[1],
            current[2] + self.config.control.approach_contact_brake_step_m,
        )

    def _is_final_approach(
        self,
        current: tuple[float, ...],
        parcel_pose: tuple[float, ...],
    ) -> bool:
        target = self.pregrasp_position(parcel_pose)
        return math.hypot(
            current[0] - target[0],
            current[1] - target[1],
        ) <= self.config.task.approach_xy_tolerance_m

    def lift_position(self) -> tuple[float, float, float]:
        grasp_position = self._planned_grasp_position or (
            self.sample.position_xy[0],
            self.sample.position_xy[1],
            self._initial_parcel_z + self.grasp_hand_clearance_m(),
        )
        return (
            grasp_position[0],
            grasp_position[1],
            grasp_position[2] + self.config.task.lift_height_m,
        )

    def drop_position(self) -> tuple[float, float, float]:
        destination = self.destination_position
        return (destination[0], destination[1], self.config.task.drop_hand_height_m)

    def _safe_drop_position(
        self,
        current: tuple[float, ...],
    ) -> tuple[float, float, float]:
        destination = self.destination_position
        tolerance = self.config.task.position_tolerance_m
        transfer_z = max(
            self.config.task.drop_hand_height_m + 0.10,
            self.lift_position()[2] + 0.05,
        )
        horizontal_distance = math.hypot(
            current[0] - destination[0],
            current[1] - destination[1],
        )
        if self._drop_descent_committed:
            if self._planned_transport_contract_active():
                self._transport_phase = "descend"
            return self.drop_position()
        if self._planned_transport_contract_active():
            return self._contract_drop_position(
                current,
                destination=destination,
                transfer_z=transfer_z,
                horizontal_distance=horizontal_distance,
                tolerance=tolerance,
            )
        if current[2] < transfer_z - tolerance:
            return (current[0], current[1], transfer_z)
        if horizontal_distance > tolerance:
            return (destination[0], destination[1], transfer_z)
        self._drop_descent_committed = True
        return self.drop_position()

    def _contract_drop_position(
        self,
        current: tuple[float, ...],
        *,
        destination: tuple[float, ...],
        transfer_z: float,
        horizontal_distance: float,
        tolerance: float,
    ) -> tuple[float, float, float]:
        """Stage payload transport so queued IK targets cannot blend transitions."""
        settle_steps = self.config.task.grasp_planning_transfer_settle_steps
        if self._transport_phase == "raise":
            if current[2] < transfer_z - tolerance:
                self._transfer_position_stable_steps = 0
                return (current[0], current[1], transfer_z)
            self._transport_phase = "raise_settle"
        if self._transport_phase == "raise_settle":
            if self._transfer_raise_stable_steps < settle_steps:
                self._transfer_raise_stable_steps += 1
                return tuple(float(value) for value in current)
            self._transport_phase = "transfer"

        transfer_target = (destination[0], destination[1], transfer_z)
        if self._transport_phase == "transfer":
            if horizontal_distance > tolerance or abs(current[2] - transfer_z) > tolerance:
                return transfer_target
            self._transport_phase = "transfer_settle"
        if self._transport_phase == "transfer_settle":
            if self._transfer_position_stable_steps < settle_steps:
                self._transfer_position_stable_steps += 1
                return tuple(float(value) for value in current)

        self._drop_descent_committed = True
        self._transport_phase = "descend"
        return self.drop_position()

    def _planned_transport_contract_active(self) -> bool:
        return (
            self._planned_grasp_position is not None
            and self.config.task.grasp_planning_transport_contract_enabled
        )

    def _reset_transport_contract(self, *, planned: bool = False) -> None:
        self._transport_phase = "raise" if planned else "inactive"
        self._transport_reference_position = None
        self._transfer_raise_stable_steps = 0
        self._transfer_position_stable_steps = 0

    def _bounded_transport_reference(
        self,
        current: tuple[float, ...],
        desired: tuple[float, float, float],
        reference_step_m: float,
    ) -> tuple[float, float, float]:
        """Advance a smooth reference without allowing unbounded tracking error."""
        if math.dist(current, desired) <= 1e-12:
            target = tuple(float(value) for value in current)
            self._transport_reference_position = target
            return target
        reference = self._transport_reference_position or tuple(
            float(value) for value in current
        )
        reference = self._bounded_step(reference, desired, reference_step_m)
        self._transport_reference_position = reference
        return self._bounded_step(
            current,
            reference,
            self.config.control.max_ee_step_m,
        )

    def _bounded_step(
        self,
        current: tuple[float, ...],
        desired: tuple[float, float, float],
        limit: float,
    ) -> tuple[float, float, float]:
        delta = tuple(float(target - value) for value, target in zip(current, desired, strict=True))
        distance = math.sqrt(sum(value * value for value in delta))
        if distance <= limit or distance == 0:
            return desired
        scale = limit / distance
        return tuple(float(value + offset * scale) for value, offset in zip(current, delta, strict=True))
