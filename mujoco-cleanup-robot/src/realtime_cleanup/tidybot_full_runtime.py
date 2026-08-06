"""Learned fixed-room mission: one lap, then clean all four objects."""

from __future__ import annotations

import json
import math
import time
from collections import Counter
from dataclasses import asdict
from pathlib import Path
from typing import Any

import imageio.v2 as imageio
import numpy as np
import torch

from realtime_cleanup.telemetry import TimingSummary, TraceWriter, gpu_identity
from realtime_cleanup.tidybot_fixed_arm_policy import (
    TidyBotFixedArmPolicy,
    phase_schedule,
)
from realtime_cleanup.tidybot_full_task import (
    ARM_RETRACT_POSITION,
    OBJECT_ORDER,
    fixed_task_room,
    object_approach_spawn_routes,
)
from realtime_cleanup.tidybot_io import TidyBotSimulationIO
from realtime_cleanup.tidybot_perception import YOLO11DepthPerception
from realtime_cleanup.tidybot_route_policy import (
    FixedRouteConfig,
    RouteTracker,
    TidyBotRoutePolicy,
    route_policy_features,
    sha256_file,
)
from realtime_cleanup.types import (
    TidyBotArmPolicyOutput,
    TidyBotBaseVelocityCommand,
)
from stretch_cleanup.integrity import IntegrityMonitor
from stretch_cleanup.tidybot_success import (
    DepositStabilityTracker,
    object_height_m,
    sample_success,
)


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUTPUT = PROJECT_ROOT / "outputs" / "realtime" / "tidybot_full_learned"
DEFAULT_ROUTE_CHECKPOINT = (
    PROJECT_ROOT / "outputs" / "realtime" / "tidybot_route_policy" / "policy.pt"
)
DEFAULT_ARM_DIRECTORY = PROJECT_ROOT / "outputs" / "realtime" / "tidybot_fixed_arm"
DEFAULT_OBJECT_ROUTE_DIRECTORY = (
    PROJECT_ROOT / "outputs" / "realtime" / "tidybot_object_routes_v1"
)
DEFAULT_DETECTOR = (
    PROJECT_ROOT
    / "runs"
    / "detect"
    / "outputs"
    / "detector"
    / "tidybot_fixed_v1_w0"
    / "weights"
    / "best.pt"
)


def basket_occupancy_score(reference: np.ndarray, current: np.ndarray) -> float:
    if reference.shape != current.shape:
        raise ValueError("basket images must have matching shapes")
    return float(
        np.mean(np.abs(current.astype(np.int16) - reference.astype(np.int16)))
        / 255.0
    )


def _blocking_contacts(simulation: TidyBotSimulationIO) -> list[tuple[str, str]]:
    base_id = int(simulation.model.body("base_link").id)
    robot_bodies: set[int] = set()
    for body_id in range(int(simulation.model.nbody)):
        ancestor = body_id
        while ancestor > 0:
            if ancestor == base_id:
                robot_bodies.add(body_id)
                break
            ancestor = int(simulation.model.body_parentid[ancestor])
    pairs = []
    ignored = {"floor", "prototype_floor", "area_rug_0"}
    for index in range(int(simulation.data.ncon)):
        contact = simulation.data.contact[index]
        geom_a, geom_b = int(contact.geom1), int(contact.geom2)
        body_a = int(simulation.model.geom_bodyid[geom_a])
        body_b = int(simulation.model.geom_bodyid[geom_b])
        if (body_a in robot_bodies) == (body_b in robot_bodies):
            continue
        name_a = simulation.model.geom(geom_a).name or ""
        name_b = simulation.model.geom(geom_b).name or ""
        environment = name_b if body_a in robot_bodies else name_a
        if environment in ignored or environment.startswith("cargo_trailer_wheel"):
            continue
        pairs.append(tuple(sorted((name_a, name_b))))
    return sorted(set(pairs))


class FullMissionRunner:
    def __init__(
        self,
        *,
        route_checkpoint: Path,
        arm_directory: Path,
        object_route_directory: Path | None,
        detector_weights: Path,
        output: Path,
        device_index: int,
        control_hz: float,
        basket_threshold: float,
    ) -> None:
        self.output = Path(output)
        if self.output.exists():
            raise FileExistsError(self.output)
        self.output.mkdir(parents=True)
        self.device_index = device_index
        self.device = torch.device(f"cuda:{device_index}")
        self.control_hz = float(control_hz)
        self.basket_threshold = float(basket_threshold)
        if self.control_hz <= 0.0 or self.basket_threshold <= 0.0:
            raise ValueError("control_hz and basket_threshold must be positive")
        self.gpu = gpu_identity(device_index)
        self.trace = TraceWriter(self.output / "traces")
        self.route_policy = TidyBotRoutePolicy.load(
            Path(route_checkpoint),
            device=str(self.device),
        )
        self.route_checkpoint = Path(route_checkpoint)
        self.object_route_policies = (
            {
                name: TidyBotRoutePolicy.load(
                    Path(object_route_directory) / f"{name}.pt",
                    device=str(self.device),
                )
                for name in OBJECT_ORDER
            }
            if object_route_directory is not None
            else {}
        )
        self.arm_policies = {
            name: TidyBotFixedArmPolicy(
                Path(arm_directory) / f"{name}.pt",
                device=self.device,
            )
            for name in OBJECT_ORDER
        }
        self.detector = YOLO11DepthPerception(
            self.trace,
            weights=Path(detector_weights),
            device_index=device_index,
            confidence=0.25,
        )
        self.room = fixed_task_room()
        self.simulation = TidyBotSimulationIO(
            width=320,
            height=240,
            room=self.room,
        )
        self.monitor = IntegrityMonitor(
            self.simulation.model,
            self.simulation.data,
            list(OBJECT_ORDER),
            base_body="base_link",
        )
        self.video_path = self.output / "room_corner.mp4"
        self.video = imageio.get_writer(
            self.video_path,
            fps=self.control_hz,
            codec="libx264",
            quality=7,
        )
        self.control_steps = 0
        self.video_frames = 0
        self.events: list[dict[str, Any]] = []
        self.route_inference_ms: list[float] = []
        self.arm_inference_ms: list[float] = []
        self.detector_inference_ms: list[float] = []
        self.contact_counts: Counter[tuple[str, str]] = Counter()

    def _event(self, kind: str, **payload: object) -> None:
        self.events.append(
            {
                "kind": kind,
                "control_step": self.control_steps,
                "simulation_time": float(self.simulation.data.time),
                **payload,
            }
        )

    def _step(self) -> None:
        self.simulation.step_control_period(self.control_hz, on_step=self.monitor)
        self.video.append_data(self.simulation.render_room_corner())
        self.video_frames += 1
        self.control_steps += 1
        self.contact_counts.update(_blocking_contacts(self.simulation))

    def _route_action(
        self,
        policy: TidyBotRoutePolicy,
        packet: Any,
        tracker: RouteTracker,
    ) -> TidyBotBaseVelocityCommand:
        features = route_policy_features(
            packet.base_position,
            packet.base_velocity,
            tracker.config,
            tracker,
        )
        tensor = torch.from_numpy(features).to(self.device)
        normalized = (
            tensor - policy.feature_mean
        ) / policy.feature_std
        torch.cuda.synchronize(self.device_index)
        started = time.perf_counter_ns()
        with torch.inference_mode():
            action = (
                policy.model(normalized.unsqueeze(0))
                .squeeze(0)
                .cpu()
                .numpy()
                .astype(np.float32)
            )
        torch.cuda.synchronize(self.device_index)
        elapsed_ms = (time.perf_counter_ns() - started) / 1_000_000.0
        self.route_inference_ms.append(elapsed_ms)
        trace_id = self.trace.write(
            kind="tidybot_fixed_route_policy",
            model={
                "architecture": "RoutePolicyMLP",
                "path": str(policy.checkpoint_path),
                "sha256": policy.checkpoint_sha256,
                "device": self.gpu,
            },
            inputs={
                "frame_id": int(packet.frame_id),
                "base_position": packet.base_position.astype(float).tolist(),
                "base_velocity": packet.base_velocity.astype(float).tolist(),
                "route_sha256": tracker.config.sha256,
                "waypoint_index": tracker.target_index,
                "route_progress": tracker.progress(packet.base_position),
            },
            outputs={"body_twist": action.astype(float).tolist()},
            timing={"inference_ms": elapsed_ms},
            raw_arrays={"features": features, "body_twist": action},
        )
        return TidyBotBaseVelocityCommand(body_twist=action, trace_id=trace_id)

    def _safety_base_stop(self, cycles: int = 15) -> None:
        for index in range(cycles):
            packet = self.simulation.observe(task_phase="pick")
            trace_id = self.trace.write(
                kind="tidybot_sensor_safety_stop",
                model={"architecture": "zero-velocity-safety-gate"},
                inputs={"frame_id": int(packet.frame_id)},
                outputs={"body_twist": [0.0, 0.0, 0.0]},
                timing={"inference_ms": 0.0},
            )
            self.simulation.apply_base_velocity(
                TidyBotBaseVelocityCommand(
                    body_twist=np.zeros(3, dtype=np.float32),
                    trace_id=trace_id,
                ),
                packet,
                hz=self.control_hz,
            )
            self._step()

    def _run_route(
        self,
        config: FixedRouteConfig,
        *,
        name: str,
        maximum_steps: int,
        maximum_final_error_m: float,
        tolerance_margin_m: float = 0.0,
        heading_tolerance_rad: float | None = None,
        confirm_object_at_pre_dock: str | None = None,
        policy: TidyBotRoutePolicy | None = None,
    ) -> dict[str, object]:
        selected_policy = policy or self.route_policy
        tracker = RouteTracker(
            config,
            tolerance_margin_m=tolerance_margin_m,
            heading_tolerance_rad=heading_tolerance_rad,
        )
        self._event("route_start", route=name, route_sha256=config.sha256)
        packet = self.simulation.observe(task_phase="pick")
        steps = 0
        detector_confirmation = None
        while steps < maximum_steps:
            tracker.update(packet.base_position)
            if (
                confirm_object_at_pre_dock is not None
                and detector_confirmation is None
                and tracker.reached_waypoints
                >= len(config.waypoints_spawn) - 1
            ):
                self._safety_base_stop()
                detector_confirmation = self._confirm_target(
                    confirm_object_at_pre_dock
                )
                packet = self.simulation.observe(task_phase="pick")
            if tracker.completed:
                break
            command = self._route_action(selected_policy, packet, tracker)
            self.simulation.apply_base_velocity(command, packet, hz=self.control_hz)
            self._step()
            packet = self.simulation.observe(task_phase="pick")
            steps += 1
        self._safety_base_stop()
        packet = self.simulation.observe(task_phase="pick")
        final_goal = np.asarray(config.waypoints_spawn[-1], dtype=np.float32)
        final_error = float(np.linalg.norm(packet.base_position[:2] - final_goal))
        final_heading_error = abs(
            math.atan2(
                math.sin(
                    config.segment_heading(len(config.waypoints_spawn) - 1)
                    - float(packet.base_position[2])
                ),
                math.cos(
                    config.segment_heading(len(config.waypoints_spawn) - 1)
                    - float(packet.base_position[2])
                ),
            )
        )
        result = {
            "route": name,
            "completed": tracker.completed,
            "steps": steps,
            "coverage": tracker.progress(packet.base_position),
            "waypoints_reached": tracker.reached_waypoints,
            "waypoint_count": len(config.waypoints_spawn),
            "final_position_error_m": final_error,
            "final_heading_error_rad": final_heading_error,
            "final_speed": float(np.linalg.norm(packet.base_velocity)),
            "detector_confirmation": detector_confirmation,
        }
        self._event("route_end", **result)
        if not tracker.completed or final_error > maximum_final_error_m:
            raise RuntimeError(f"learned route failed: {result}")
        return result

    def _align_arm_retract(self, *, phase: str) -> dict[str, object]:
        aligned = 0
        error_value = math.inf
        for index in range(240):
            packet = self.simulation.observe(task_phase=phase)
            error = ARM_RETRACT_POSITION - packet.arm_position
            error_value = float(np.max(np.abs(error)))
            aligned = aligned + 1 if error_value < 0.002 else 0
            if aligned >= 10:
                break
            requested = np.clip(
                error * 0.6,
                -np.asarray(self.simulation.limits.arm_delta_per_cycle),
                np.asarray(self.simulation.limits.arm_delta_per_cycle),
            ).astype(np.float32)
            if abs(float(error[7])) >= 0.01:
                requested[7] = math.copysign(
                    self.simulation.limits.arm_delta_per_cycle[7],
                    float(error[7]),
                )
            trace_id = self.trace.write(
                kind="tidybot_sensor_safety_stow",
                model={"architecture": "joint-encoder-retract-safety-controller"},
                inputs={
                    "frame_id": int(packet.frame_id),
                    "arm_position": packet.arm_position.astype(float).tolist(),
                    "retract_target": ARM_RETRACT_POSITION.astype(float).tolist(),
                },
                outputs={"requested_delta": requested.astype(float).tolist()},
                timing={"inference_ms": 0.0},
            )
            self.simulation.apply_arm(
                TidyBotArmPolicyOutput(
                    action_chunk=requested[None],
                    phase=phase,
                    trace_id=trace_id,
                )
            )
            self._step()
        if aligned < 10:
            raise RuntimeError(f"arm safety stow failed, max error={error_value:.5f}")
        return {"max_error": error_value, "stable_cycles": aligned}

    def _confirm_target(self, object_name: str, attempts: int = 20) -> dict[str, object]:
        best = None
        for _ in range(attempts):
            packet = self.simulation.observe(task_phase="pick")
            matches = [
                item
                for item in self.detector.infer(packet)
                if item.label == object_name and not item.unknown
            ]
            self.detector_inference_ms.append(
                float(self.detector.last_inference_ms)
            )
            if matches:
                best = max(matches, key=lambda item: item.confidence)
                break
            self._safety_base_stop(cycles=1)
        if best is None:
            raise RuntimeError(f"learned detector did not confirm {object_name}")
        return {
            "label": best.label,
            "confidence": float(best.confidence),
            "center_camera_m": best.center_camera_m.astype(float).tolist(),
            "bbox_xyxy": list(best.bbox_xyxy),
        }

    def _run_arm_policy(self, object_name: str) -> dict[str, object]:
        policy = self.arm_policies[object_name]
        policy.reset()
        basket_reference = self.simulation.observe(
            task_phase="pick"
        ).basket_rgb.copy()
        initial_height = object_height_m(
            self.simulation.model,
            self.simulation.data,
            object_name,
        )
        truth_tracker = DepositStabilityTracker(required_seconds=0.5)
        truth_lifted = False
        truth_deposited = False
        episode_step = 0
        phase_counts = Counter()
        self._event("arm_policy_start", object_name=object_name)
        for phase, phase_step in phase_schedule(policy.phase_lengths):
            packet = self.simulation.observe(task_phase=phase)
            torch.cuda.synchronize(self.device_index)
            started = time.perf_counter_ns()
            output = policy.infer(
                packet.arm_position,
                phase=phase,
                phase_step=phase_step,
                episode_step=episode_step,
            )
            torch.cuda.synchronize(self.device_index)
            elapsed_ms = (time.perf_counter_ns() - started) / 1_000_000.0
            self.arm_inference_ms.append(elapsed_ms)
            action = output.action_chunk[0].copy()
            trace_id = self.trace.write(
                kind="tidybot_fixed_arm_policy",
                model={
                    "architecture": str(policy.metadata["architecture"]),
                    "path": str(policy.checkpoint),
                    "sha256": sha256_file(policy.checkpoint),
                    "device": self.gpu,
                    "object_name": object_name,
                },
                inputs={
                    "frame_id": int(packet.frame_id),
                    "arm_position": packet.arm_position.astype(float).tolist(),
                    "phase": phase,
                    "phase_step": phase_step,
                    "episode_step": episode_step,
                },
                outputs={"action_delta": action.astype(float).tolist()},
                timing={"inference_ms": elapsed_ms},
                raw_arrays={"action_delta": action},
            )
            self.simulation.apply_arm(
                TidyBotArmPolicyOutput(
                    action_chunk=action[None],
                    phase=phase,
                    trace_id=trace_id,
                )
            )
            self._step()
            # Evaluation-only truth is measured but never branches runtime.
            truth = sample_success(
                self.simulation.model,
                self.simulation.data,
                object_name,
                initial_height_m=initial_height,
            )
            truth_lifted |= truth.grasped_and_lifted
            if phase == "deposit":
                truth_deposited |= truth_tracker.update(
                    truth,
                    1.0 / self.control_hz,
                )
            else:
                truth_tracker.reset()
            phase_counts[phase] += 1
            episode_step += 1
        basket_current = self.simulation.observe(
            task_phase="deposit"
        ).basket_rgb.copy()
        basket_score = basket_occupancy_score(basket_reference, basket_current)
        result = {
            "object_name": object_name,
            "model_calls": policy.model_calls,
            "phase_steps": dict(phase_counts),
            "basket_score": basket_score,
            "sensor_verified": basket_score >= self.basket_threshold,
            "evaluation_truth_grasped_and_lifted": truth_lifted,
            "evaluation_truth_stable_deposit": truth_deposited,
        }
        self._event("arm_policy_end", **result)
        return result

    def close(self) -> None:
        self.video.close()
        self.trace.close()
        self.simulation.close()

    def run(self) -> dict[str, object]:
        route_results = []
        object_results = []
        failure = None
        try:
            route_results.append(
                self._run_route(
                    self.route_policy.route,
                    name="one_lap",
                    maximum_steps=2600,
                    maximum_final_error_m=0.25,
                    tolerance_margin_m=0.01,
                )
            )
            approach_routes = object_approach_spawn_routes(self.room)
            for object_name in OBJECT_ORDER:
                selected_route_policy = self.object_route_policies.get(
                    object_name,
                    self.route_policy,
                )
                if object_name in self.object_route_policies:
                    object_route = selected_route_policy.route
                else:
                    points = approach_routes[object_name]
                    object_route = FixedRouteConfig(
                        waypoints_spawn=points,
                        waypoint_tolerance_m=0.002,
                        name=f"fixed_approach_{object_name}",
                    )
                route_result = self._run_route(
                    object_route,
                    name=f"approach_{object_name}",
                    maximum_steps=max(
                        1200,
                        360 * len(object_route.waypoints_spawn),
                    ),
                    maximum_final_error_m=0.004,
                    heading_tolerance_rad=0.02,
                    confirm_object_at_pre_dock=object_name,
                    policy=selected_route_policy,
                )
                route_results.append(route_result)
                detector = route_result["detector_confirmation"]
                if not isinstance(detector, dict):
                    raise RuntimeError(
                        f"route completed without detecting {object_name}"
                    )
                self.simulation.lock_base()
                self.simulation.mark_arm_active()
                pre_align = self._align_arm_retract(phase="pick")
                manipulation = self._run_arm_policy(object_name)
                post_align = self._align_arm_retract(phase="deposit")
                self.simulation.mark_arm_stowed()
                self.simulation.unlock_base()
                result = {
                    "object_name": object_name,
                    "detector": detector,
                    "pre_arm_alignment": pre_align,
                    "manipulation": manipulation,
                    "post_arm_alignment": post_align,
                }
                object_results.append(result)
                if not manipulation["sensor_verified"]:
                    raise RuntimeError(
                        f"basket RGB did not verify {object_name}: "
                        f"{manipulation['basket_score']:.5f}"
                    )
        except Exception as error:
            failure = f"{type(error).__name__}: {error}"
            self._event("mission_failure", error=failure)
        finally:
            integrity = self.monitor.verdict()
            self.close()

        result = {
            "claim": (
                "fixed-scene learned hierarchical run; no teacher, action replay, "
                "IK, object truth, qpos, or qvel used for runtime control"
            ),
            "success": bool(
                failure is None
                and len(object_results) == len(OBJECT_ORDER)
                and all(
                    item["manipulation"]["sensor_verified"]
                    for item in object_results
                )
                and integrity.clean
            ),
            "failure": failure,
            "object_order": list(OBJECT_ORDER),
            "route_results": route_results,
            "object_results": object_results,
            "control_steps": self.control_steps,
            "video_frames": self.video_frames,
            "continuous_video_complete": self.video_frames == self.control_steps,
            "video": str(self.video_path),
            "events": self.events,
            "route_inference_ms": self.route_inference_ms,
            "arm_inference_ms": self.arm_inference_ms,
            "detector_inference_ms": self.detector_inference_ms,
            "inference_timing_ms": {
                "route": (
                    asdict(TimingSummary.from_values(self.route_inference_ms))
                    if self.route_inference_ms
                    else None
                ),
                "arm": (
                    asdict(TimingSummary.from_values(self.arm_inference_ms))
                    if self.arm_inference_ms
                    else None
                ),
                "detector": (
                    asdict(TimingSummary.from_values(self.detector_inference_ms))
                    if self.detector_inference_ms
                    else None
                ),
            },
            "collision_contact_counts": [
                {"pair": list(pair), "control_steps": count}
                for pair, count in sorted(self.contact_counts.items())
            ],
            "integrity": integrity.as_dict(),
            "commands": self.simulation.ledger.commands,
        }
        (self.output / "result.json").write_text(
            json.dumps(result, indent=2, allow_nan=False),
            encoding="utf-8",
        )
        return result


def run_full_mission(
    *,
    route_checkpoint: Path = DEFAULT_ROUTE_CHECKPOINT,
    arm_directory: Path = DEFAULT_ARM_DIRECTORY,
    object_route_directory: Path | None = DEFAULT_OBJECT_ROUTE_DIRECTORY,
    detector_weights: Path = DEFAULT_DETECTOR,
    output: Path = DEFAULT_OUTPUT,
    device_index: int = 0,
    control_hz: float = 20.0,
    basket_threshold: float = 0.008,
) -> dict[str, object]:
    runner = FullMissionRunner(
        route_checkpoint=route_checkpoint,
        arm_directory=arm_directory,
        object_route_directory=object_route_directory,
        detector_weights=detector_weights,
        output=output,
        device_index=device_index,
        control_hz=control_hz,
        basket_threshold=basket_threshold,
    )
    return runner.run()
