"""Minimal batched Genesis drone environment for AMD smoke testing."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import torch

from .domain_randomization import DomainParameters
from .gate_math import gate_crossing
from .racer_asset import prepare_corrected_racer_urdf


def _resolve_delay_history_max_steps(
    action_delay_steps: torch.Tensor,
    scheduled_action_delay_steps: torch.Tensor | None,
    requested_max_steps: int | None,
) -> int:
    observed_max_steps = int(action_delay_steps.max().item())
    if scheduled_action_delay_steps is not None:
        observed_max_steps = max(
            observed_max_steps,
            int(scheduled_action_delay_steps.max().item()),
        )
    if requested_max_steps is None:
        return observed_max_steps
    if (
        isinstance(requested_max_steps, bool)
        or not isinstance(requested_max_steps, int)
        or requested_max_steps < 0
    ):
        raise ValueError("delay_history_max_steps must be a non-negative integer")
    if requested_max_steps < observed_max_steps:
        raise ValueError(
            "delay_history_max_steps is smaller than a configured action delay"
        )
    return requested_max_steps


def _build_scene_with_prebuild_hook(
    *,
    gs: Any,
    scene: Any,
    drone: Any,
    num_envs: int,
    prebuild_scene_hook: Callable[..., Any] | None,
) -> Any:
    """Run one optional attachment hook before the environment's sole build."""

    attachment = None
    if prebuild_scene_hook is not None:
        if not callable(prebuild_scene_hook):
            raise TypeError("prebuild_scene_hook must be callable or None")
        if getattr(scene, "_is_built", None) is not False:
            raise RuntimeError(
                "scene must expose _is_built=False before prebuild_scene_hook"
            )
        attachment = prebuild_scene_hook(
            gs=gs,
            scene=scene,
            drone=drone,
            num_envs=num_envs,
        )
        if getattr(scene, "_is_built", None) is not False:
            raise RuntimeError("prebuild_scene_hook must not build the scene")
    scene.build(n_envs=num_envs)
    return attachment


@dataclass(frozen=True)
class StepResult:
    observation: torch.Tensor
    reward: torch.Tensor
    done: torch.Tensor
    passed: torch.Tensor
    struck: torch.Tensor


class FlightGuardGenesisEnv:
    """Direct-RPM three-gate environment with geometric strike detection."""

    def __init__(
        self,
        num_envs: int,
        *,
        dt: float = 0.01,
        show_viewer: bool = False,
        drone_urdf: str | Path | None = None,
        domain_parameters: DomainParameters | None = None,
        delay_history_max_steps: int | None = None,
        prebuild_scene_hook: Callable[..., Any] | None = None,
    ) -> None:
        import genesis as gs

        if num_envs <= 0:
            raise ValueError("num_envs must be positive")
        if gs.backend != gs.amdgpu:
            raise RuntimeError(f"FlightGuard requires gs.amdgpu, got {gs.backend}")

        self.gs = gs
        self.num_envs = num_envs
        self.device = gs.device
        self.dt = dt
        if domain_parameters is not None and domain_parameters.count != num_envs:
            raise ValueError("domain parameter count must match num_envs")
        self.domain_parameters = domain_parameters
        self.scene = gs.Scene(
            sim_options=gs.options.SimOptions(dt=dt, substeps=2),
            rigid_options=gs.options.RigidOptions(
                dt=dt,
                constraint_solver=gs.constraint_solver.Newton,
                enable_collision=False,
                enable_joint_limit=True,
            ),
            show_viewer=show_viewer,
        )
        self.scene.add_entity(gs.morphs.Plane())
        if drone_urdf is None:
            source_urdf = (
                Path(gs.__file__).resolve().parent / "assets" / "urdf" / "drones" / "racer.urdf"
            )
            drone_urdf = prepare_corrected_racer_urdf(source_urdf)
        self.drone_urdf = Path(drone_urdf).resolve()
        self.drone = self.scene.add_entity(
            gs.morphs.Drone(
                file=str(self.drone_urdf),
                model="RACE",
                pos=(0.0, 0.0, 1.0),
            )
        )
        self.prebuild_attachment = _build_scene_with_prebuild_hook(
            gs=self.gs,
            scene=self.scene,
            drone=self.drone,
            num_envs=num_envs,
            prebuild_scene_hook=prebuild_scene_hook,
        )

        mass = torch.as_tensor(
            self.drone.get_mass(), device=self.device, dtype=torch.float32
        ).reshape(-1)[0]
        self.hover_rpm = torch.sqrt(
            mass * 9.81 / (float(self.drone.n_propellers) * float(self.drone.KF))
        )
        if domain_parameters is None:
            self.mass_scale = torch.ones(num_envs, device=self.device, dtype=torch.float32)
            self.thrust_scale = torch.ones_like(self.mass_scale)
            self.wind_acceleration_mps2 = torch.zeros(
                (num_envs, 3), device=self.device, dtype=torch.float32
            )
            self.action_delay_steps = torch.zeros(num_envs, device=self.device, dtype=torch.long)
        else:
            self.mass_scale = domain_parameters.mass_scale.to(
                device=self.device, dtype=torch.float32
            )
            self.thrust_scale = domain_parameters.thrust_scale.to(
                device=self.device, dtype=torch.float32
            )
            self.wind_acceleration_mps2 = domain_parameters.wind_acceleration_mps2.to(
                device=self.device, dtype=torch.float32
            )
            self.action_delay_steps = domain_parameters.action_delay_steps.to(
                device=self.device, dtype=torch.long
            )
            mass_shift = (mass * (self.mass_scale - 1.0))[:, None]
            self.drone.set_mass_shift(mass_shift, links_idx_local=[0])
        scheduled_thrust_scale = (
            None if domain_parameters is None else domain_parameters.scheduled_thrust_scale
        )
        scheduled_wind_acceleration_mps2 = (
            None
            if domain_parameters is None
            else domain_parameters.scheduled_wind_acceleration_mps2
        )
        scheduled_action_delay_steps = (
            None if domain_parameters is None else domain_parameters.scheduled_action_delay_steps
        )
        self._scheduled_thrust_scale = (
            None
            if scheduled_thrust_scale is None
            else scheduled_thrust_scale.to(
                device=self.device,
                dtype=torch.float32,
            )
        )
        self._scheduled_wind_acceleration_mps2 = (
            None
            if scheduled_wind_acceleration_mps2 is None
            else scheduled_wind_acceleration_mps2.to(
                device=self.device,
                dtype=torch.float32,
            )
        )
        self._scheduled_action_delay_steps = (
            None
            if scheduled_action_delay_steps is None
            else scheduled_action_delay_steps.to(
                device=self.device,
                dtype=torch.long,
            )
        )
        self._scheduled_fault_activation_attempts = 0
        self._scheduled_fault_activation_count = 0
        self.effective_mass_kg = mass * self.mass_scale
        maximum_delay_steps = _resolve_delay_history_max_steps(
            self.action_delay_steps,
            self._scheduled_action_delay_steps,
            delay_history_max_steps,
        )
        self._delay_history = torch.zeros(
            (
                maximum_delay_steps + 1,
                num_envs,
                4,
            ),
            device=self.device,
            dtype=torch.float32,
        )
        self._delay_cursor = -1
        self.last_applied_action = torch.zeros(
            (num_envs, 4), device=self.device, dtype=torch.float32
        )
        self.base_position = torch.tensor([0.0, 0.0, 1.0], device=self.device, dtype=torch.float32)
        self.base_quaternion = torch.tensor(
            [1.0, 0.0, 0.0, 0.0], device=self.device, dtype=torch.float32
        )
        gates = torch.tensor(
            [[2.0, 0.0, 1.0], [4.0, 0.5, 1.1], [6.0, 0.0, 1.0]],
            device=self.device,
            dtype=torch.float32,
        )
        yaws = torch.tensor([0.0, 0.15, -0.15], device=self.device, dtype=torch.float32)
        self.gates = gates[None, :, :].expand(num_envs, -1, -1).clone()
        self.gate_yaws = yaws[None, :].expand(num_envs, -1).clone()
        self.gate_index = torch.zeros(num_envs, device=self.device, dtype=torch.long)
        self.previous_position = self.base_position[None, :].expand(num_envs, -1).clone()
        self.previous_distance = torch.zeros(num_envs, device=self.device)
        self.reset(torch.arange(num_envs, device=self.device))

    @property
    def has_scheduled_faults(self) -> bool:
        """Whether this environment carries a frozen post-onset fault target."""

        targets = (
            self._scheduled_thrust_scale,
            self._scheduled_wind_acceleration_mps2,
            self._scheduled_action_delay_steps,
        )
        return all(target is not None for target in targets)

    @property
    def scheduled_fault_activation_attempts(self) -> int:
        return self._scheduled_fault_activation_attempts

    @property
    def scheduled_fault_activation_count(self) -> int:
        return self._scheduled_fault_activation_count

    def scheduled_fault_targets_active(self) -> bool:
        """Return exact tensor equality without exposing targets to policies."""

        if not self.has_scheduled_faults:
            return False
        return bool(
            torch.equal(
                self.thrust_scale,
                self._scheduled_thrust_scale,
            )
            and torch.equal(
                self.wind_acceleration_mps2,
                self._scheduled_wind_acceleration_mps2,
            )
            and torch.equal(
                self.action_delay_steps,
                self._scheduled_action_delay_steps,
            )
        )

    def activate_scheduled_faults(self) -> bool:
        """Apply a frozen fault target once while preserving FIFO history."""

        if not self.has_scheduled_faults:
            raise RuntimeError("no scheduled fault target is configured")
        self._scheduled_fault_activation_attempts += 1
        if self._scheduled_fault_activation_count:
            return False
        self.thrust_scale.copy_(self._scheduled_thrust_scale)
        self.wind_acceleration_mps2.copy_(self._scheduled_wind_acceleration_mps2)
        self.action_delay_steps.copy_(self._scheduled_action_delay_steps)
        self._scheduled_fault_activation_count = 1
        return True

    def _delayed_action(self, actions: torch.Tensor) -> torch.Tensor:
        self._delay_cursor = (self._delay_cursor + 1) % self._delay_history.shape[0]
        self._delay_history[self._delay_cursor].copy_(actions)
        env_index = torch.arange(self.num_envs, device=self.device)
        read_index = (self._delay_cursor - self.action_delay_steps) % self._delay_history.shape[0]
        return self._delay_history[read_index, env_index]

    def _current_gate(self) -> tuple[torch.Tensor, torch.Tensor]:
        env_index = torch.arange(self.num_envs, device=self.device)
        clamped = self.gate_index.clamp_max(self.gates.shape[1] - 1)
        return self.gates[env_index, clamped], self.gate_yaws[env_index, clamped]

    def reset(self, envs_idx: torch.Tensor) -> torch.Tensor:
        envs_idx = envs_idx.to(device=self.device, dtype=torch.long)
        if envs_idx.numel() == 0:
            return self.observe()
        positions = self.base_position.expand(envs_idx.numel(), -1).clone()
        quaternions = self.base_quaternion.expand(envs_idx.numel(), -1).clone()
        self.drone.set_pos(positions, zero_velocity=True, envs_idx=envs_idx)
        self.drone.set_quat(quaternions, zero_velocity=True, envs_idx=envs_idx)
        self.drone.zero_all_dofs_velocity(envs_idx)
        self.gate_index[envs_idx] = 0
        self._delay_history[:, envs_idx] = 0.0
        self.last_applied_action[envs_idx] = 0.0
        self.previous_position[envs_idx] = positions
        first_gate = self.gates[envs_idx, 0]
        self.previous_distance[envs_idx] = torch.linalg.vector_norm(first_gate - positions, dim=1)
        return self.observe()

    def observe(self) -> torch.Tensor:
        position = self.drone.get_pos()
        quaternion = self.drone.get_quat()
        velocity = self.drone.get_vel()
        angular_velocity = self.drone.get_ang()
        gate, _ = self._current_gate()
        relative_gate = gate - position
        distance = torch.linalg.vector_norm(relative_gate, dim=1, keepdim=True)
        return torch.cat(
            (position, quaternion, velocity, angular_velocity, relative_gate, distance),
            dim=1,
        )

    def step(self, actions: torch.Tensor) -> StepResult:
        if actions.shape != (self.num_envs, 4):
            raise ValueError(f"actions must have shape {(self.num_envs, 4)}")
        actions = actions.to(device=self.device, dtype=torch.float32).clamp(-1.0, 1.0)
        if self.domain_parameters is None:
            applied_action = actions
            rpm = (1.0 + 0.8 * applied_action) * self.hover_rpm
        else:
            applied_action = self._delayed_action(actions)
            rpm = (
                (1.0 + 0.8 * applied_action)
                * self.hover_rpm
                * torch.sqrt(self.thrust_scale[:, None])
            )
        self.last_applied_action.copy_(applied_action)
        self.drone.set_propellers_rpm(rpm)
        if self.domain_parameters is not None:
            external_force = self.effective_mass_kg[:, None] * self.wind_acceleration_mps2
            self.drone.solver.apply_links_external_force(
                external_force[:, None, :],
                links_idx=[self.drone.base_link_idx],
                ref="root_com",
            )
        self.scene.step()

        position = self.drone.get_pos()
        gate, yaw = self._current_gate()
        crossing = gate_crossing(
            self.previous_position,
            position,
            gate,
            yaw,
            half_width=0.6,
            half_height=0.5,
            proxy_radius=0.08,
        )
        distance = torch.linalg.vector_norm(gate - position, dim=1)
        progress = self.previous_distance - distance
        reward = (
            0.5 * progress + 10.0 * crossing.passed.float() - 4.0 * crossing.struck_frame.float()
        )

        self.gate_index += crossing.passed.long()
        completed = self.gate_index >= self.gates.shape[1]
        reward += 5.0 * completed.float()
        out_of_bounds = (
            (position[:, 2] < 0.1)
            | (position[:, :2].abs() > 10.0).any(dim=1)
            | (position[:, 2] > 5.0)
        )
        finite = torch.isfinite(position).all(dim=1)
        done = crossing.struck_frame | out_of_bounds | ~finite | completed

        switched = crossing.passed & ~completed
        next_gate, _ = self._current_gate()
        next_distance = torch.linalg.vector_norm(next_gate - position, dim=1)
        self.previous_distance = torch.where(switched, next_distance, distance)
        self.previous_position.copy_(position)

        observation = self.observe()
        return StepResult(
            observation,
            reward,
            done,
            crossing.passed,
            crossing.struck_frame,
        )

    @property
    def expected_observation_dim(self) -> int:
        return 17
