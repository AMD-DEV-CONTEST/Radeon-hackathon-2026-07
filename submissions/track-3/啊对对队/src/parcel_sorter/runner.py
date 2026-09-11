from __future__ import annotations

from dataclasses import asdict, dataclass
import time
from typing import Any, Protocol

from .config import ExperimentConfig
from .contracts import CartesianAction, Observation, PolicyContext, RobotState, TrajectoryFrame
from .dataset import JsonlTrajectoryWriter, LeRobotTrajectoryWriter
from .expert import ScriptedPickPlaceExpert
from .grasp_planning import box_requires_geometry_aware_grasp_planning
from .metrics import EpisodeResult
from .policy import ActionPolicy, ScriptedExpertPolicy
from .randomization import ParcelSample
from .state_machine import ClosedLoopSupervisor, Stage


class ParcelEnvironment(Protocol):
    control_step: int

    def state(self) -> RobotState: ...
    def observation(self, state: RobotState | None = None) -> Observation: ...
    def step(self, action: CartesianAction) -> None: ...
    def sensor_frame(self) -> tuple[Any | None, Any | None]: ...
    def parcel_dropped(self) -> bool: ...


class FrameWriter(Protocol):
    def add_frame(self, frame: TrajectoryFrame) -> None: ...


@dataclass(frozen=True)
class EpisodeReport:
    episode_index: int
    result: EpisodeResult
    terminal_stage: str
    sample: ParcelSample
    trace: tuple[dict[str, Any], ...]
    safety_summary: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "episode_index": self.episode_index,
            "result": asdict(self.result),
            "terminal_stage": self.terminal_stage,
            "sample": self.sample.to_dict(),
            "trace": list(self.trace),
            "safety_summary": self.safety_summary,
        }


def resolve_grasp_stability_steps(
    config: ExperimentConfig,
    sample: ParcelSample,
    *,
    geometry_grasp_planning_active: bool | None = None,
) -> int:
    steps = sample.grasp_stability_steps or config.task.grasp_stability_steps
    if geometry_grasp_planning_active is None:
        geometry_grasp_planning_active = (
            config.task.geometry_aware_grasp_planning_enabled
            and not config.task.grasp_planning_reset_fallback_gate_enabled
            and box_requires_geometry_aware_grasp_planning(
                sample,
                hand_clearance_m=config.task.grasp_hand_clearance_m,
            )
        )
    if geometry_grasp_planning_active:
        steps = max(steps, config.task.grasp_planning_stability_steps)
    return steps


def run_policy_episode(
    env: ParcelEnvironment,
    config: ExperimentConfig,
    sample: ParcelSample,
    episode_index: int,
    policy: ActionPolicy,
    writers: tuple[FrameWriter, ...] = (),
    task_instruction: str | None = None,
) -> EpisodeReport:
    task_instruction = task_instruction or config.output.task_instruction
    supervisor = ClosedLoopSupervisor(
        config.task.max_grasp_retries,
        grasp_settle_steps=config.task.grasp_settle_steps,
        release_settle_steps=config.task.release_settle_steps,
        grasp_stability_steps=resolve_grasp_stability_steps(
            config,
            sample,
            geometry_grasp_planning_active=getattr(
                env, "geometry_grasp_planning_active", None
            ),
        ),
        transport_slip_setdown_regrasp_enabled=(
            config.control.transport_slip_setdown_regrasp_enabled
        ),
        recovery_setdown_max_steps=(
            config.control.transport_slip_setdown_max_steps
        ),
    )
    trace: list[dict[str, Any]] = []
    latencies_ms: list[float] = []
    max_force = 0.0
    max_steps = int(config.task.episode_seconds * config.simulation.control_hz)

    for frame_index in range(max_steps):
        state = env.state()
        observation = env.observation(state)
        max_force = max(max_force, state.gripper_contact_force_n)
        rgb, depth = env.sensor_frame()
        started = time.perf_counter_ns()
        decision = supervisor.step(observation)
        prepare_action = getattr(env, "prepare_action", None)
        if callable(prepare_action):
            prepare_action(decision, state)
        action = policy.predict(
            PolicyContext(
                decision=decision,
                state=state,
                task=task_instruction,
                rgb=rgb,
                depth=depth,
            )
        )
        latencies_ms.append((time.perf_counter_ns() - started) / 1_000_000)
        frame = TrajectoryFrame(
            frame_index=frame_index,
            timestamp_seconds=frame_index / config.simulation.control_hz,
            stage=decision.stage,
            state=state,
            action=action,
            task=task_instruction,
            rgb=rgb,
            depth=depth,
        )
        for writer in writers:
            writer.add_frame(frame)
        trace.append(
            {
                "frame": frame_index,
                "stage": decision.stage,
                "command": decision.command,
                "reason": decision.reason,
                "retry_count": decision.retry_count,
                "contact_force_n": state.gripper_contact_force_n,
                "ee_position_m": list(state.end_effector_pose[:3]),
                "ee_quaternion_wxyz": list(state.end_effector_pose[3:7]),
                "parcel_position_m": list(state.parcel_pose[:3]),
                "parcel_quaternion_wxyz": list(state.parcel_pose[3:7]),
                "ee_parcel_relative_position_m": [
                    float(ee - parcel)
                    for ee, parcel in zip(
                        state.end_effector_pose[:3],
                        state.parcel_pose[:3],
                        strict=True,
                    )
                ],
                "action_target_position_m": list(action.target_position),
                "at_pregrasp": observation.at_pregrasp,
                "grasp_contact": observation.grasp_contact,
                "parcel_lifted": observation.parcel_lifted,
                "transport_slip": observation.transport_slip,
                "at_recovery_setdown": observation.at_recovery_setdown,
                "excessive_contact_force": observation.excessive_contact_force,
            }
        )

        if supervisor.stage in {Stage.COMPLETE, Stage.ABORT}:
            break
        env.step(action)
        safety_snapshot = getattr(env, "safety_snapshot", None)
        if callable(safety_snapshot):
            trace[-1]["safety"] = safety_snapshot()

    elapsed_sim = max((len(trace) - 1) / config.simulation.control_hz, 1 / config.simulation.control_hz)
    result = EpisodeResult(
        success=supervisor.stage == Stage.COMPLETE,
        retries=supervisor.retry_count,
        duration_seconds=elapsed_sim,
        inference_latency_ms=tuple(latencies_ms),
        dropped=env.parcel_dropped(),
        max_contact_force_n=max_force,
    )
    return EpisodeReport(
        episode_index=episode_index,
        result=result,
        terminal_stage=supervisor.stage.value,
        sample=sample,
        trace=tuple(trace),
        safety_summary=(
            env.safety_summary()
            if callable(getattr(env, "safety_summary", None))
            else {}
        ),
    )


def run_expert_episode(
    env: ParcelEnvironment,
    config: ExperimentConfig,
    sample: ParcelSample,
    episode_index: int,
    writers: tuple[FrameWriter, ...] = (),
) -> EpisodeReport:
    environment_expert = getattr(env, "expert", None)
    expert = (
        environment_expert
        if isinstance(environment_expert, ScriptedPickPlaceExpert)
        else ScriptedPickPlaceExpert(config, sample)
    )
    policy = ScriptedExpertPolicy(expert)
    return run_policy_episode(env, config, sample, episode_index, policy, writers)


def save_episode_writers(
    report: EpisodeReport,
    jsonl_writer: JsonlTrajectoryWriter | None,
    lerobot_writer: LeRobotTrajectoryWriter | None,
) -> None:
    if jsonl_writer is not None:
        jsonl_writer.save_episode(
            report.episode_index,
            {
                "success": report.result.success,
                "terminal_stage": report.terminal_stage,
                "retries": report.result.retries,
                "sample": report.sample.to_dict(),
            },
        )
    if lerobot_writer is not None:
        if report.result.success:
            lerobot_writer.save_episode()
        else:
            lerobot_writer.clear_episode()
