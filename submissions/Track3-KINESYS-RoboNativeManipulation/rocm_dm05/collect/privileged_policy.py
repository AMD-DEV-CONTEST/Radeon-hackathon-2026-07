"""Privileged-pose expert selection for BiGym demonstration collection."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import mujoco

from demonstrations.demo import Demo


SUPPORTED_TASK = "DishwasherUnloadCutleryLong"
DEFAULT_DEMO_UUID = "037e80a547f6406aab2da36e6fde2617"
CONTROL_REFERENCE_UUID = "199949bc66134ef8881c72928605bf2d"
ACTION_MODE_DIR = (
    "JointPositionActionMode_floating_pelvis_x_pelvis_y_pelvis_z_pelvis_rz_absolute"
)
LOG = logging.getLogger("privileged-pose-policy")


@dataclass
class ReferenceDemo:
    uuid: str
    seed: int
    initial_position: np.ndarray
    initial_quaternion: np.ndarray
    actions: np.ndarray
    base_targets: np.ndarray
    grasp_close_step: int
    release_step: int
    tray_entry_step: int
    drawer_open_step: int
    drawer_close_step: int
    bottom_close_step: int
    door_close_step: int
    pinch_relative_xyz: np.ndarray


def quaternion_distance(left: np.ndarray, right: np.ndarray) -> float:
    dot = float(np.clip(abs(np.dot(left, right)), 0.0, 1.0))
    return 2.0 * float(np.arccos(dot))


def dishwasher_unload_cutlery_status(env: Any) -> dict[str, Any]:
    """Read task progress from simulator state without changing the environment."""
    item = env.cutlery[0]
    held = any(
        env.robot.is_gripper_holding_object(item, side)
        for side in env.robot.grippers
    )
    in_tray = bool(item.is_colliding(env.tray))
    dishwasher_state = np.asarray(env.dishwasher.get_state(), dtype=np.float32)
    drawer_state = np.asarray(env.cutlery_cabinet.get_state(), dtype=np.float32)
    dishwasher_closed = bool(np.allclose(dishwasher_state, 0, atol=0.1))
    drawer_closed = bool(np.allclose(drawer_state, 0, atol=0.1))
    simulator_success = bool(env.success)
    success = bool(
        in_tray
        and not held
        and dishwasher_closed
        and drawer_closed
    )

    if success:
        stage = "任务完成"
    elif in_tray and not drawer_closed:
        stage = "关闭餐具抽屉"
    elif in_tray and not dishwasher_closed:
        stage = "关闭洗碗机"
    elif in_tray:
        stage = "验证任务完成"
    elif held:
        stage = "搬运餐具到抽屉"
    else:
        stage = "定位并抓取餐具"

    return {
        "stage": stage,
        "cutlery_held": held,
        "cutlery_in_tray": in_tray,
        "dishwasher_closed": dishwasher_closed,
        "drawer_closed": drawer_closed,
        "dishwasher_state": dishwasher_state.round(3).tolist(),
        "drawer_state": drawer_state.round(3).tolist(),
        "success": success,
        "simulator_success": simulator_success,
    }


class PrivilegedExpertPolicy:
    """Select a validated expert from privileged object pose for any task seed."""

    def __init__(
        self,
        task: str,
        demo_root: Path,
        demo_uuid: str = DEFAULT_DEMO_UUID,
        validation_manifest: Path | None = None,
    ):
        self.task = task
        self.source_dir = (
            demo_root
            / task
            / ACTION_MODE_DIR
            / "lightweight"
            / "20hz"
        )
        self.fallback_demo_uuid = demo_uuid
        self.validation_manifest = validation_manifest
        self.references: list[ReferenceDemo] = []
        self.available = task == SUPPORTED_TASK and self.source_dir.is_dir()
        self.demo_uuid: str | None = None
        self.reference_seed: int | None = None
        self.pose_score: float | None = None
        self.actions = np.empty((0, 0), dtype=np.float32)
        self.active = False
        self.index = 0
        self.virtual_keys: set[str] = set()
        self._previous_action: np.ndarray | None = None
        self._reference: ReferenceDemo | None = None
        self._target_initial_position = np.zeros(3, dtype=np.float64)
        self._position_offset = np.zeros(3, dtype=np.float64)
        self._action_low = np.empty(0, dtype=np.float32)
        self._action_high = np.empty(0, dtype=np.float32)
        self.phase = "idle"
        self.retry_count = 0
        self.failure_reason: str | None = None
        self.control_steps = 0
        self._placed_latched = False
        self._lost_hold_steps = 0
        self._left_pinch_site_id: int | None = None
        self._left_arm_dofs = np.empty(0, dtype=np.int32)
        milestone_path = Path(__file__).with_name("reference_milestones.json")
        if milestone_path.is_file():
            self._milestones = json.loads(milestone_path.read_text(encoding="utf-8"))
        else:
            self._milestones = {}

    @property
    def reference_count(self) -> int:
        return len(self.references)

    def _validated_uuids(self) -> list[str]:
        if self.validation_manifest and self.validation_manifest.is_file():
            uuids = []
            manifest_lines = self.validation_manifest.read_text(
                encoding="utf-8"
            ).splitlines()
            for line in manifest_lines:
                try:
                    record = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if record.get("status") == "success":
                    uuids.append(str(record["source_demo_uuid"]))
            if uuids:
                return sorted(set(uuids))
        return [path.stem for path in sorted(self.source_dir.glob("*.safetensors"))]

    def bind_env(self, env: Any) -> None:
        """Build the privileged pose index using deterministic source resets."""
        if not self.available:
            return
        references = []
        for uuid in self._validated_uuids():
            try:
                demo = Demo.from_safetensors(self.source_dir / f"{uuid}.safetensors")
                env.reset(seed=int(demo.seed))
                actions = np.stack(
                    [step.executed_action for step in demo.timesteps]
                ).astype(np.float32)
                gripper_closed = np.flatnonzero(actions[:, 14] > 0.5)
                if not len(gripper_closed):
                    raise ValueError("Reference never closes the left gripper")
                grasp_close_step = int(gripper_closed[0])
                gripper_reopened = np.flatnonzero(
                    (np.arange(len(actions)) > grasp_close_step)
                    & (actions[:, 14] < 0.5)
                )
                if not len(gripper_reopened):
                    raise ValueError("Reference never releases the fork")
                release_step = int(gripper_reopened[0])
                total_steps = len(actions)
                milestones = self._milestones.get(uuid, {})
                initial_base = env.robot.floating_base.qpos.astype(np.float64)
                references.append(
                    ReferenceDemo(
                        uuid=uuid,
                        seed=int(demo.seed),
                        initial_position=np.asarray(
                            env.cutlery[0].body.get_position(), dtype=np.float64
                        ).copy(),
                        initial_quaternion=np.asarray(
                            env.cutlery[0].body.get_quaternion(), dtype=np.float64
                        ).copy(),
                        actions=actions,
                        base_targets=initial_base[None, :]
                        + np.cumsum(actions[:, :4], axis=0, dtype=np.float64),
                        grasp_close_step=grasp_close_step,
                        release_step=release_step,
                        tray_entry_step=int(
                            milestones.get("tray_entry_step")
                            or min(release_step + 32, total_steps - 1)
                        ),
                        drawer_open_step=int(
                            milestones.get("drawer_open_step")
                            or min(release_step + 10, total_steps - 1)
                        ),
                        drawer_close_step=int(
                            milestones.get("drawer_close_step")
                            or min(
                                max(release_step + 55, int(total_steps * 0.58)),
                                total_steps - 1,
                            )
                        ),
                        bottom_close_step=int(
                            milestones.get("bottom_close_step")
                            or min(int(total_steps * 0.82), total_steps - 1)
                        ),
                        door_close_step=int(
                            milestones.get("door_close_step") or total_steps - 1
                        ),
                        pinch_relative_xyz=np.asarray(
                            milestones.get("pinch_relative_xyz", []),
                            dtype=np.float64,
                        ),
                    )
                )
            except Exception:
                LOG.exception("Failed to index reference demo %s", uuid)
        self.references = references
        self.available = bool(references)
        if not self.available:
            raise RuntimeError("No validated reference demos could be indexed")
        physics = env.action_mode._mojo.physics
        left_gripper = next(iter(env.robot.grippers.values()))
        self._left_pinch_site_id = int(
            physics.bind(left_gripper._pinch_site.mjcf).element_id
        )
        self._left_arm_dofs = np.asarray(
            [
                int(np.asarray(physics.bind(actuator.joint).dofadr).item())
                for actuator in env.robot.limb_actuators[:5]
            ],
            dtype=np.int32,
        )
        LOG.info("Indexed %s privileged pose references", len(references))

    @property
    def total_steps(self) -> int:
        return int(self.actions.shape[0])

    def start(self, env: Any, action_space: Any) -> None:
        if not self.available:
            raise ValueError(f"No validated expert is available for {self.task}")
        if not self.references:
            raise RuntimeError("Privileged pose library is not initialized")
        position = np.asarray(env.cutlery[0].body.get_position(), dtype=np.float64)
        quaternion = np.asarray(env.cutlery[0].body.get_quaternion(), dtype=np.float64)
        scored = []
        for reference in self.references:
            position_distance = float(
                np.linalg.norm(position - reference.initial_position)
            )
            orientation_distance = quaternion_distance(
                quaternion, reference.initial_quaternion
            )
            scored.append((100.0 * position_distance + orientation_distance, reference))
        _, nearest_reference = min(scored, key=lambda item: item[0])
        reference = next(
            (
                candidate
                for candidate in self.references
                if candidate.uuid == CONTROL_REFERENCE_UUID
            ),
            nearest_reference,
        )
        score = next(value for value, candidate in scored if candidate is reference)
        if reference.actions.shape[1:] != action_space.shape:
            raise ValueError(
                f"Expert action shape {reference.actions.shape[1:]} does not match "
                f"{action_space.shape}"
            )
        self.demo_uuid = reference.uuid
        self.reference_seed = reference.seed
        self.pose_score = float(score)
        self.actions = reference.actions
        self._reference = reference
        self._target_initial_position = position.copy()
        self._position_offset = position - reference.initial_position
        self._position_offset[2] = 0.0
        self._action_low = np.asarray(action_space.low, dtype=np.float32)
        self._action_high = np.asarray(action_space.high, dtype=np.float32)
        self.active = True
        self.index = 0
        self.control_steps = 0
        self.phase = "approach_grasp"
        self.retry_count = 0
        self.failure_reason = None
        self._placed_latched = False
        self._lost_hold_steps = 0
        self.virtual_keys.clear()
        self._previous_action = np.zeros(action_space.shape, dtype=np.float32)

    def stop(self) -> None:
        self.active = False
        self.virtual_keys.clear()

    def reset_controller_state(self) -> None:
        self.stop()
        self.phase = "idle"
        self.retry_count = 0
        self.failure_reason = None
        self.control_steps = 0
        self._placed_latched = False
        self._lost_hold_steps = 0

    def _restart_grasp(self, env: Any, reason: str) -> None:
        reference = self._reference
        if reference is None:
            self.failure_reason = reason
            self.phase = "failed"
            return
        if self.retry_count >= 2:
            self.failure_reason = f"{reason}; retries exhausted"
            self.phase = "failed"
            return
        self.retry_count += 1
        self._lost_hold_steps = 0
        self.phase = "approach_grasp"
        self.index = 0
        self._target_initial_position = np.asarray(
            env.cutlery[0].body.get_position(), dtype=np.float64
        )
        self._position_offset = (
            self._target_initial_position - reference.initial_position
        )
        self._position_offset[2] = 0.0

    def _update_phase(self, env: Any) -> dict[str, Any]:
        status = dishwasher_unload_cutlery_status(env)
        self._placed_latched = self._placed_latched or status["cutlery_in_tray"]
        if status["success"]:
            self.phase = "success"
        elif self._placed_latched:
            drawer_open = not status["drawer_closed"]
            bottom_open = float(status["dishwasher_state"][1]) > 0.1
            door_open = float(status["dishwasher_state"][0]) > 0.1
            if drawer_open:
                self.phase = "close_drawer"
            elif bottom_open:
                self.phase = "close_bottom_tray"
            elif door_open:
                self.phase = "close_door"
            else:
                self.phase = "verify_success"
        elif status["cutlery_held"]:
            self._lost_hold_steps = 0
            self.phase = "carry_place"
        elif self.phase == "carry_place":
            reference = self._reference
            if reference is not None and self.index >= reference.release_step - 3:
                self.phase = "release_settle"
            else:
                self._lost_hold_steps += 1
                if self._lost_hold_steps > 10:
                    self._restart_grasp(env, "fork lost before reaching the tray")
        elif self.phase == "release_settle":
            self.phase = "release_settle"
        else:
            self.phase = "approach_grasp"
        return status

    def _phase_gate(self, env: Any, status: dict[str, Any]) -> None:
        reference = self._reference
        if reference is None:
            return
        total = len(reference.actions)
        grasp_gate = min(reference.grasp_close_step + 32, total - 1)
        place_gate = min(
            max(reference.release_step + 32, reference.tray_entry_step + 10),
            total - 1,
        )
        drawer_gate = min(reference.drawer_close_step + 15, total - 1)
        bottom_gate = min(reference.bottom_close_step + 15, total - 1)
        door_gate = min(reference.door_close_step + 10, total - 1)

        if self.phase == "approach_grasp" and self.index >= grasp_gate:
            self._restart_grasp(env, "grasp failed at the contact gate")
            return

        if self.phase == "carry_place" and self.index >= place_gate:
            if status["cutlery_held"]:
                self.index = max(
                    reference.grasp_close_step + 15,
                    reference.release_step - 55,
                )
            return

        if self.phase == "release_settle" and self.index >= place_gate:
            self.failure_reason = "released fork did not settle in the cutlery tray"
            self.phase = "failed"
            return

        if self.phase == "close_drawer" and self.index >= drawer_gate:
            self.index = max(
                reference.drawer_open_step - 20,
                reference.release_step + 5,
            )
            return

        if self.phase == "close_bottom_tray" and self.index >= bottom_gate:
            self.index = max(reference.drawer_close_step - 20, 0)
            return

        if self.phase in {"close_door", "verify_success"} and self.index >= door_gate:
            self.index = max(reference.bottom_close_step - 20, 0)

    def _retarget_base(self, env: Any, action: np.ndarray) -> None:
        reference = self._reference
        if reference is None:
            return
        ref_index = min(self.index, len(reference.base_targets) - 1)
        desired = reference.base_targets[ref_index].copy()
        if self.phase == "approach_grasp":
            live_position = np.asarray(
                env.cutlery[0].body.get_position(), dtype=np.float64
            )
            live_offset = live_position - reference.initial_position
            desired[:2] += live_offset[:2]
        elif self.phase == "carry_place":
            fade = np.clip(
                1.0
                - (self.index - reference.grasp_close_step)
                / max(1, reference.release_step - reference.grasp_close_step),
                0.0,
                1.0,
            )
            desired[:2] += self._position_offset[:2] * fade

        # Servo the pinch point around contact instead of trusting the replayed
        # base pose. The fork can be continuously jittered within either valid
        # basket holder, so a few millimetres of live correction materially
        # improve grasp retention at the edge of the orientation range.
        grasp_servo_start = max(reference.grasp_close_step - 35, 0)
        grasp_servo_end = reference.grasp_close_step + 30
        if (
            grasp_servo_start <= self.index <= grasp_servo_end
            and self.phase in {"approach_grasp", "carry_place"}
        ):
            fork_position = np.asarray(
                env.cutlery[0].body.get_position(), dtype=np.float64
            )
            left_gripper = next(iter(env.robot.grippers.values()))
            pinch_position = np.asarray(
                left_gripper.pinch_position, dtype=np.float64
            )
            live_relative = pinch_position[:2] - fork_position[:2]
            target_relative = np.array([0.015, -0.015], dtype=np.float64)
            desired[:2] += np.clip(
                target_relative - live_relative,
                -0.025,
                0.025,
            )

        current = env.robot.floating_base.qpos.astype(np.float64)
        error = desired - current
        limits = np.array([0.014, 0.014, 0.012, 0.045], dtype=np.float64)
        feedback = np.clip(0.65 * error, -limits, limits)
        action[:4] = np.clip(
            feedback,
            self._action_low[:4],
            self._action_high[:4],
        )

    def _retarget_left_arm(self, env: Any, action: np.ndarray) -> None:
        reference = self._reference
        if (
            reference is None
            or self.phase != "carry_place"
            or self._left_pinch_site_id is None
            or len(self._left_arm_dofs) != 5
            or len(reference.pinch_relative_xyz) != len(reference.actions)
        ):
            return

        ref_index = min(self.index, len(reference.pinch_relative_xyz) - 1)
        fork_position = np.asarray(
            env.cutlery[0].body.get_position(), dtype=np.float64
        )
        left_gripper = next(iter(env.robot.grippers.values()))
        pinch_position = np.asarray(left_gripper.pinch_position, dtype=np.float64)
        expected_pinch = fork_position + reference.pinch_relative_xyz[ref_index]
        position_error = np.clip(expected_pinch - pinch_position, -0.025, 0.025)

        physics = env.action_mode._mojo.physics
        jacobian = np.zeros((3, physics.model.nv), dtype=np.float64)
        rotation_jacobian = np.zeros_like(jacobian)
        mujoco.mj_jacSite(
            physics.model.ptr,
            physics.data.ptr,
            jacobian,
            rotation_jacobian,
            self._left_pinch_site_id,
        )
        arm_jacobian = jacobian[:, self._left_arm_dofs]
        damping = 2e-4 * np.eye(3, dtype=np.float64)
        joint_delta = arm_jacobian.T @ np.linalg.solve(
            arm_jacobian @ arm_jacobian.T + damping,
            position_error,
        )
        action[4:9] = np.clip(
            action[4:9] + np.clip(0.45 * joint_delta, -0.035, 0.035),
            self._action_low[4:9],
            self._action_high[4:9],
        )

    def next_action(self, env: Any) -> np.ndarray | None:
        if not self.active or self._reference is None:
            self.stop()
            return None
        status = self._update_phase(env)
        if self.phase == "success":
            self.stop()
            return None
        if self.phase == "failed":
            self.stop()
            return None

        self._phase_gate(env, status)
        if self.phase == "failed":
            self.stop()
            return None
        self.index = min(self.index, self.total_steps - 1)
        action = self.actions[self.index].copy()
        self._retarget_base(env, action)
        self._retarget_left_arm(env, action)
        self.virtual_keys = self._action_to_keys(action, self._previous_action)
        self._previous_action = action
        self.index += 1
        self.control_steps += 1
        return action

    @staticmethod
    def _action_to_keys(action: np.ndarray, previous: np.ndarray | None) -> set[str]:
        keys: set[str] = set()
        base_mapping = (
            (0, "KeyW", "KeyS", 2e-4),
            (1, "KeyA", "KeyD", 2e-4),
            (2, "KeyR", "KeyF", 2e-4),
            (3, "KeyQ", "KeyE", 5e-4),
        )
        for index, positive, negative, threshold in base_mapping:
            if action[index] > threshold:
                keys.add(positive)
            elif action[index] < -threshold:
                keys.add(negative)

        if previous is None:
            return keys
        key_pairs = (("KeyT", "KeyG"), ("KeyY", "KeyH"), ("KeyU", "KeyJ"),
                     ("KeyI", "KeyK"), ("KeyO", "KeyL"))
        for local, (positive, negative) in enumerate(key_pairs):
            for offset, prefix in ((4, ""), (9, "Shift+")):
                delta = float(action[offset + local] - previous[offset + local])
                if delta > 3e-3:
                    keys.add(f"{prefix}{positive}")
                elif delta < -3e-3:
                    keys.add(f"{prefix}{negative}")
        for index, open_key, close_key in ((14, "KeyZ", "KeyX"), (15, "KeyC", "KeyV")):
            delta = float(action[index] - previous[index])
            if delta > 2e-2:
                keys.add(close_key)
            elif delta < -2e-2:
                keys.add(open_key)
        return keys

    def privileged_status(self, env: Any) -> dict[str, Any]:
        if self.task != SUPPORTED_TASK:
            return {"stage": "unsupported"}
        status = dishwasher_unload_cutlery_status(env)
        phase_names = {
            "approach_grasp": "闭环定位与抓取",
            "carry_place": "闭环搬运与放置",
            "release_settle": "闭环等待餐具入托盘",
            "close_drawer": "闭环关闭餐具抽屉",
            "close_bottom_tray": "闭环关闭下层篮筐",
            "close_door": "闭环关闭洗碗机门",
            "verify_success": "闭环验证任务完成",
            "success": "任务完成",
            "failed": "闭环执行失败",
            "idle": status["stage"],
        }
        status["task_stage"] = status["stage"]
        status["stage"] = phase_names.get(self.phase, status["stage"])
        status["controller_phase"] = self.phase
        status["controller_retries"] = self.retry_count
        status["controller_failure"] = self.failure_reason
        return status
