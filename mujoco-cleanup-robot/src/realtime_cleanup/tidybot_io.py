"""TidyBot sensor/actuator boundary with hard base-arm interlocks."""

from __future__ import annotations

import math
import time
from collections.abc import Callable
from dataclasses import dataclass

import mujoco
import numpy as np

from realtime_cleanup.integrity import assert_state_write_lock, lock_python_state_writes
from realtime_cleanup.telemetry import CommandLedger
from realtime_cleanup.types import (
    TIDYBOT_ARM_ACTION_NAMES,
    TidyBotArmPolicyOutput,
    TidyBotBaseCommand,
    TidyBotBaseVelocityCommand,
    TidyBotSensorPacket,
)
from stretch_cleanup.mobile_platforms import (
    TidyBotCameraRandomization,
    build_prototype_model,
    build_tidybot_room_model,
    camera_semantics,
    platform,
    reset_to_home,
)
from stretch_cleanup.scene import RoomSpec


TIDYBOT_ARM_JOINTS = (
    "joint_1",
    "joint_2",
    "joint_3",
    "joint_4",
    "joint_5",
    "joint_6",
    "joint_7",
    "right_driver_joint",
)


@dataclass(frozen=True)
class TidyBotLimits:
    base_delta_per_cycle: tuple[float, float, float] = (0.08, 0.08, 0.12)
    arm_delta_per_cycle: tuple[float, ...] = (0.08, 0.08, 0.08, 0.08, 0.10, 0.10, 0.10, 8.0)
    emergency_depth_m: float = 0.16


@dataclass(frozen=True)
class TidyBotSensorNoise:
    """Sensor-domain randomization disabled by default.

    These values perturb only rendered measurements.  They never alter MuJoCo
    state and can therefore be matched to measurements from a physical robot.
    """

    depth_std_m: float = 0.0
    depth_dropout_probability: float = 0.0
    rgb_gain_std: float = 0.0
    rgb_bias_std: float = 0.0
    seed: int = 20260804

    def __post_init__(self) -> None:
        if self.depth_std_m < 0.0:
            raise ValueError("depth_std_m must be non-negative")
        if not 0.0 <= self.depth_dropout_probability < 1.0:
            raise ValueError("depth_dropout_probability must be in [0, 1)")
        if self.rgb_gain_std < 0.0 or self.rgb_bias_std < 0.0:
            raise ValueError("RGB noise standard deviations must be non-negative")


class TidyBotSimulationIO:
    """Standalone TidyBot prototype; execution writes actuator controls only."""

    def __init__(
        self,
        *,
        width: int = 320,
        height: int = 240,
        limits: TidyBotLimits | None = None,
        sensor_noise: TidyBotSensorNoise | None = None,
        camera_randomization: TidyBotCameraRandomization | None = None,
        room: RoomSpec | None = None,
    ) -> None:
        self.prototype = platform("tidybot")
        self.room = room
        self.model = (
            build_prototype_model(
                "tidybot",
                camera_randomization=camera_randomization,
            )
            if room is None
            else build_tidybot_room_model(
                room,
                camera_randomization=camera_randomization,
            )
        )
        self.data = mujoco.MjData(self.model)
        reset_to_home(self.model, self.data, key_name=self.prototype.preview_key)
        self.renderer = mujoco.Renderer(self.model, width=width, height=height)
        self.width = width
        self.height = height
        self.limits = limits or TidyBotLimits()
        self.sensor_noise = sensor_noise or TidyBotSensorNoise()
        self.rng = np.random.default_rng(self.sensor_noise.seed)
        self._rgb_gain = max(
            0.1,
            1.0 + float(self.rng.normal(0.0, self.sensor_noise.rgb_gain_std)),
        )
        self._rgb_bias = float(self.rng.normal(0.0, self.sensor_noise.rgb_bias_std))
        self.frame_id = 0
        self.ledger = CommandLedger()
        self.base_locked = False
        self.arm_stowed = True
        self.cameras = camera_semantics(self.prototype)
        self.arm_actuator = {
            name: self.model.actuator(name).id for name in self.prototype.schema.arm_actuators
        }
        self.base_actuator = {
            name: self.model.actuator(name).id for name in self.prototype.schema.base_actuators
        }
        self.arm_joint = {name: self.model.joint(name).id for name in TIDYBOT_ARM_JOINTS}
        self.base_joint = {
            name: self.model.joint(name).id for name in self.prototype.schema.base_actuators
        }
        self._settle()
        lock_python_state_writes(self.data)

    def _settle(self, seconds: float = 0.5) -> None:
        for _ in range(round(seconds / self.model.opt.timestep)):
            mujoco.mj_step(self.model, self.data)
        mujoco.mj_forward(self.model, self.data)

    def close(self) -> None:
        self.renderer.close()

    def sensor_manifest(self) -> dict[str, object]:
        """Serializable camera/control metadata recorded with every dataset."""

        cameras: dict[str, object] = {}
        for semantic, name in self.cameras.items():
            camera_id = self.model.camera(name).id
            cameras[semantic] = {
                "model_name": name,
                "position_m": self.model.cam_pos[camera_id].astype(float).tolist(),
                "quaternion_wxyz": self.model.cam_quat[camera_id].astype(float).tolist(),
                "fovy_degrees": float(self.model.cam_fovy[camera_id]),
                "render_width": self.width,
                "render_height": self.height,
            }
        return {
            "domain": "sim",
            "control_hz": 20.0,
            "depth_unit": "metre",
            "rgb_order": "RGB",
            "cameras": cameras,
        }

    def _render_rgb(self, camera: str | mujoco.MjvCamera) -> np.ndarray:
        self.renderer.disable_depth_rendering()
        self.renderer.disable_segmentation_rendering()
        self.renderer.update_scene(self.data, camera=camera)
        image = self.renderer.render().copy()
        if self.sensor_noise.rgb_gain_std or self.sensor_noise.rgb_bias_std:
            image = np.clip(
                image.astype(np.float32) * self._rgb_gain + self._rgb_bias,
                0.0,
                255.0,
            ).astype(np.uint8)
        return image

    def render_teleop_overview(self) -> np.ndarray:
        """Render the original third-person view following the full arm and base."""

        base_id = self.model.body(self.prototype.base_body).id
        base_rotation = self.data.xmat[base_id].reshape(3, 3)
        heading_degrees = math.degrees(
            math.atan2(float(base_rotation[1, 0]), float(base_rotation[0, 0]))
        )
        camera = mujoco.MjvCamera()
        camera.type = mujoco.mjtCamera.mjCAMERA_FREE
        camera.lookat[:] = self.data.xpos[base_id] + base_rotation @ np.asarray(
            [0.15, 0.0, 0.55],
            dtype=float,
        )
        camera.distance = 2.1
        camera.azimuth = 135.0 + heading_degrees
        camera.elevation = -25.0
        return self._render_rgb(camera)

    def render_room_corner(self) -> np.ndarray:
        """Render the fixed room-corner review camera."""

        if self.room is None:
            raise RuntimeError("room-corner rendering requires a room scene")
        return self._render_rgb("corner")

    def _render_depth(self, camera: str) -> np.ndarray:
        self.renderer.disable_segmentation_rendering()
        self.renderer.enable_depth_rendering()
        self.renderer.update_scene(self.data, camera=camera)
        depth = self.renderer.render().copy().astype(np.float32)
        self.renderer.disable_depth_rendering()
        if self.sensor_noise.depth_std_m:
            valid = np.isfinite(depth) & (depth > 0.0)
            noise = self.rng.normal(
                0.0,
                self.sensor_noise.depth_std_m,
                size=depth.shape,
            ).astype(np.float32)
            depth[valid] = np.maximum(0.0, depth[valid] + noise[valid])
        if self.sensor_noise.depth_dropout_probability:
            dropped = self.rng.random(depth.shape) < self.sensor_noise.depth_dropout_probability
            depth[dropped] = 0.0
        return depth

    def _joint_state(self, joint_id: int) -> tuple[float, float]:
        qpos = int(self.model.jnt_qposadr[joint_id])
        qvel = int(self.model.jnt_dofadr[joint_id])
        return float(self.data.qpos[qpos]), float(self.data.qvel[qvel])

    def _arm_state(self) -> tuple[np.ndarray, np.ndarray]:
        values = [self._joint_state(self.arm_joint[name]) for name in TIDYBOT_ARM_JOINTS]
        return (
            np.asarray([value[0] for value in values], dtype=np.float32),
            np.asarray([value[1] for value in values], dtype=np.float32),
        )

    def _base_state(self) -> tuple[np.ndarray, np.ndarray]:
        values = [
            self._joint_state(self.base_joint[name])
            for name in self.prototype.schema.base_actuators
        ]
        return (
            np.asarray([value[0] for value in values], dtype=np.float32),
            np.asarray([value[1] for value in values], dtype=np.float32),
        )

    def _workspace_optical_to_base(self) -> np.ndarray:
        """Return base_from_camera-optical for measured RGB-D projection."""

        base_id = self.model.body(self.prototype.base_body).id
        camera_id = self.model.camera(self.cameras["workspace_rgbd"]).id
        base_rotation = self.data.xmat[base_id].reshape(3, 3)
        camera_rotation = self.data.cam_xmat[camera_id].reshape(3, 3)
        # MuJoCo camera local axes are right/up/back; pinhole coordinates used
        # by perception are right/down/forward.
        optical_axes_in_camera = np.diag((1.0, -1.0, -1.0))
        transform = np.eye(4, dtype=np.float32)
        transform[:3, :3] = (
            base_rotation.T @ camera_rotation @ optical_axes_in_camera
        ).astype(np.float32)
        transform[:3, 3] = (
            base_rotation.T
            @ (self.data.cam_xpos[camera_id] - self.data.xpos[base_id])
        ).astype(np.float32)
        return transform

    def arm_setpoint(self) -> np.ndarray:
        """Return the eight actuator targets, in dataset action order."""

        return np.asarray(
            [
                self.data.ctrl[self.arm_actuator[name]]
                for name in self.prototype.schema.arm_actuators
            ],
            dtype=np.float32,
        )

    def base_setpoint(self) -> np.ndarray:
        """Return the x/y/theta actuator targets."""

        return np.asarray(
            [
                self.data.ctrl[self.base_actuator[name]]
                for name in self.prototype.schema.base_actuators
            ],
            dtype=np.float32,
        )

    def reset_episode(self) -> None:
        """Reset this compiled room between episodes and restore interlocks."""

        reset_to_home(self.model, self.data, key_name=self.prototype.preview_key)
        self._settle()
        self.frame_id = 0
        self.ledger = CommandLedger()
        self.base_locked = False
        self.arm_stowed = True
        lock_python_state_writes(self.data)

    def observe(self, *, task_phase: str = "pick") -> TidyBotSensorPacket:
        assert_state_write_lock(self.data)
        arm_position, arm_velocity = self._arm_state()
        base_position, base_velocity_in_spawn = self._base_state()
        heading = float(base_position[2])
        cosine = math.cos(heading)
        sine = math.sin(heading)
        base_velocity = np.asarray(
            [
                cosine * float(base_velocity_in_spawn[0])
                + sine * float(base_velocity_in_spawn[1]),
                -sine * float(base_velocity_in_spawn[0])
                + cosine * float(base_velocity_in_spawn[1]),
                float(base_velocity_in_spawn[2]),
            ],
            dtype=np.float32,
        )
        packet = TidyBotSensorPacket(
            frame_id=self.frame_id,
            monotonic_ns=time.monotonic_ns(),
            simulation_time=float(self.data.time),
            nav_rgb=self._render_rgb(self.cameras["navigation_rgb"]),
            workspace_rgb=self._render_rgb(self.cameras["workspace_rgbd"]),
            workspace_depth_m=self._render_depth(self.cameras["workspace_rgbd"]),
            wrist_rgb=self._render_rgb(self.cameras["wrist_rgbd"]),
            wrist_depth_m=self._render_depth(self.cameras["wrist_rgbd"]),
            basket_rgb=self._render_rgb(self.cameras["basket_rgb"]),
            overview_rgb=self.render_teleop_overview(),
            arm_position=arm_position,
            arm_velocity=arm_velocity,
            base_position=base_position,
            base_velocity=base_velocity,
            workspace_fovy_degrees=float(
                self.model.cam_fovy[self.model.camera(self.cameras["workspace_rgbd"]).id]
            ),
            task_phase=task_phase,
            workspace_camera_to_base=self._workspace_optical_to_base(),
        )
        self.frame_id += 1
        return packet

    def lock_base(self) -> None:
        position, _ = self._base_state()
        for index, name in enumerate(self.prototype.schema.base_actuators):
            self.data.ctrl[self.base_actuator[name]] = position[index]
        self.base_locked = True

    def mark_arm_active(self) -> None:
        if not self.base_locked:
            raise RuntimeError("arm motion requires BASE_LOCKED")
        self.arm_stowed = False

    def mark_arm_stowed(self) -> None:
        self.arm_stowed = True

    def unlock_base(self) -> None:
        if not self.arm_stowed:
            raise RuntimeError("base unlock requires ARM_STOWED")
        self.base_locked = False

    def apply_base(
        self,
        command: TidyBotBaseCommand,
        packet: TidyBotSensorPacket,
    ) -> np.ndarray:
        if self.base_locked or not self.arm_stowed:
            raise RuntimeError("base command rejected by arm/base interlock")
        self.ledger.register(command.trace_id)
        current, _ = self._base_state()
        requested_delta = np.asarray(command.target_pose, dtype=float) - current
        maximum = np.asarray(self.limits.base_delta_per_cycle)
        limited_delta = np.clip(requested_delta, -maximum, maximum)
        center = packet.workspace_depth_m[
            packet.workspace_depth_m.shape[0] // 3 : 2
            * packet.workspace_depth_m.shape[0]
            // 3,
            packet.workspace_depth_m.shape[1] // 3 : 2
            * packet.workspace_depth_m.shape[1]
            // 3,
        ]
        valid = center[np.isfinite(center) & (center > 0.02)]
        emergency = bool(valid.size and float(np.percentile(valid, 5)) < self.limits.emergency_depth_m)
        if emergency:
            limited_delta[:] = 0.0
        applied = current + limited_delta
        for index, name in enumerate(self.prototype.schema.base_actuators):
            self.data.ctrl[self.base_actuator[name]] = applied[index]
        safety_limited = emergency or not np.allclose(requested_delta, limited_delta)
        self.ledger.record_command(
            command.trace_id,
            applied,
            safety_limited=safety_limited,
            kind="tidybot_base",
        )
        return applied.astype(np.float32)

    def apply_base_velocity(
        self,
        command: TidyBotBaseVelocityCommand,
        packet: TidyBotSensorPacket,
        *,
        hz: float = 20.0,
    ) -> np.ndarray:
        """Apply a base-frame twist and return the twist actually commanded.

        The Menagerie TidyBot exposes world x/y/theta position actuators.  This
        adapter keeps that simulation detail out of datasets by converting a
        real-transferable body twist to one control-period position increment.
        """

        if hz <= 0.0:
            raise ValueError("hz must be positive")
        before = self.base_setpoint()
        current, _ = self._base_state()
        vx, vy, wz = (float(value) for value in command.body_twist)
        dt = 1.0 / hz
        heading = float(current[2])
        world_dx = (math.cos(heading) * vx - math.sin(heading) * vy) * dt
        world_dy = (math.sin(heading) * vx + math.cos(heading) * vy) * dt
        target = current + np.asarray([world_dx, world_dy, wz * dt], dtype=np.float32)
        self.apply_base(
            TidyBotBaseCommand(target_pose=target, trace_id=command.trace_id),
            packet,
        )
        applied_world = self.base_setpoint() - before
        applied_vx = (
            math.cos(heading) * float(applied_world[0])
            + math.sin(heading) * float(applied_world[1])
        ) / dt
        applied_vy = (
            -math.sin(heading) * float(applied_world[0])
            + math.cos(heading) * float(applied_world[1])
        ) / dt
        return np.asarray(
            [applied_vx, applied_vy, float(applied_world[2]) / dt],
            dtype=np.float32,
        )

    def apply_arm(self, output: TidyBotArmPolicyOutput) -> np.ndarray:
        if not self.base_locked:
            raise RuntimeError("arm command rejected until BASE_LOCKED")
        if output.phase not in ("pick", "carry", "deposit"):
            raise ValueError(output.phase)
        self.ledger.register(output.trace_id)
        requested_delta = np.asarray(output.action_chunk[0], dtype=float)
        maximum = np.asarray(self.limits.arm_delta_per_cycle)
        limited_delta = np.clip(requested_delta, -maximum, maximum)
        command = np.empty(len(TIDYBOT_ARM_ACTION_NAMES), dtype=np.float32)
        for index, name in enumerate(self.prototype.schema.arm_actuators):
            actuator_id = self.arm_actuator[name]
            target = float(self.data.ctrl[actuator_id] + limited_delta[index])
            if self.model.actuator_ctrllimited[actuator_id]:
                low, high = self.model.actuator_ctrlrange[actuator_id]
                target = float(np.clip(target, low, high))
            command[index] = target
            self.data.ctrl[actuator_id] = command[index]
        self.arm_stowed = False
        self.ledger.record_command(
            output.trace_id,
            command,
            safety_limited=not np.allclose(requested_delta, limited_delta),
            kind=f"tidybot_arm_{output.phase}",
        )
        return command

    def apply_arm_delta(self, output: TidyBotArmPolicyOutput) -> np.ndarray:
        """Apply an arm request and return the setpoint delta after all limits."""

        before = self.arm_setpoint()
        self.apply_arm(output)
        return (self.arm_setpoint() - before).astype(np.float32)

    def step_control_period(
        self,
        hz: float = 20.0,
        *,
        on_step: Callable[[mujoco.MjData], None] | None = None,
    ) -> None:
        assert_state_write_lock(self.data)
        deadline = self.data.time + 1.0 / hz
        while self.data.time < deadline:
            mujoco.mj_step(self.model, self.data)
            if on_step is not None:
                on_step(self.data)
