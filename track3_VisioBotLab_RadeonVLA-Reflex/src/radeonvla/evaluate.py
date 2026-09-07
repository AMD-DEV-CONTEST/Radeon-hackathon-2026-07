"""Closed-loop evaluation with interruptible commands and recovery retries."""

from __future__ import annotations

import argparse
import json
import time
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
import torch

from radeonvla.artifact_io import sha256_path, validate_evaluation_payload, write_evaluation_bundle
from radeonvla.grounding import check_resolved_success, resolve_task
from radeonvla.paths import EVAL_RESULTS_DIR, EVAL_VIDEOS_DIR, PROJECT_ROOT
from radeonvla.physics import forbid_rigid_pose_writes
from radeonvla.protocol import CONTROL_HZ, DATASET_FPS
from radeonvla.randomize import EnvRandomizer, RandomizationConfig
from radeonvla.safety import (
    CommandSession,
    FailureDetector,
    RecoveryPolicy,
    SafetyMonitor,
)
from radeonvla.scene import AppearanceDR, build_scene, init_genesis
from radeonvla.scene_config import FRANKA_QPOS
from radeonvla.stress import PERTURBATIONS, inject_perturbation
from radeonvla.tasks import SUITES, TaskSpec, get_task, list_task_ids

STATE_KEY = "observation.state"
# Keep the simulator running after the success predicate first becomes true.
# Besides making the evidence easier to inspect, the final report is evaluated
# again after this dwell, so a fruit that falls out of the bowl is not counted
# as a successful rollout.
POST_SUCCESS_SECONDS = 2.0
INSTRUCTION_SOURCES = ("collected", "heldout")


def _device_display_name(device: torch.device) -> str:
    """Return a result label without querying CUDA for a CPU evaluation."""
    return torch.cuda.get_device_name(device) if device.type == "cuda" else str(device)


def select_instruction(task: TaskSpec, source: str, variation: int = 0) -> str:
    """Select language without silently paraphrasing the collected commands."""
    if source == "collected":
        pool = task.training_instructions
    elif source == "heldout":
        pool = task.evaluation_instructions
    else:
        raise ValueError(f"Unknown instruction source {source!r}; expected one of {INSTRUCTION_SOURCES}")
    return pool[variation % len(pool)]


@dataclass
class PolicyBundle:
    policy: Any
    preprocessor: Any
    postprocessor: Any
    device: torch.device
    fps: int
    image_keys: list[str]
    image_hw: tuple[int, int]
    use_amp: bool = False
    policy_type: str = "unknown"

    def reset(self) -> None:
        self.policy.reset()

    def select_action(self, observation: dict[str, np.ndarray], task: str | None) -> np.ndarray:
        from lerobot.common.control_utils import predict_action

        action = predict_action(
            observation,
            self.policy,
            self.device,
            self.preprocessor,
            self.postprocessor,
            use_amp=self.use_amp,
            task=task,
            robot_type="franka",
        )
        return action.detach().cpu().numpy().reshape(-1).astype(np.float32)


def _load_rename_map(policy_path: str) -> dict:
    path = Path(policy_path) / "train_config.json"
    if path.is_file():
        try:
            return json.loads(path.read_text(encoding="utf-8")).get("rename_map") or {}
        except (json.JSONDecodeError, OSError):
            return {}
    return {}


def load_policy(
    policy_path: str,
    repo_id: str,
    dataset_root: str | None,
    device_str: str,
    *,
    use_amp: bool = False,
    rename_map: dict | None = None,
) -> PolicyBundle:
    from lerobot.configs.policies import PreTrainedConfig
    from lerobot.datasets.lerobot_dataset import LeRobotDatasetMetadata
    from lerobot.policies.factory import make_policy, make_pre_post_processors
    from lerobot.utils.device_utils import get_safe_torch_device

    device = get_safe_torch_device(device_str, log=True)
    # Prefer metadata-only load; training used pyav for ROCm-friendly decoding.
    ds_meta = LeRobotDatasetMetadata(repo_id, root=dataset_root)
    cfg = PreTrainedConfig.from_pretrained(policy_path)
    cfg.pretrained_path = policy_path
    cfg.device = str(device)

    local_vlm_assets = Path(policy_path) / "vlm_assets"
    if local_vlm_assets.is_dir():
        # The checkpoint already contains all trained model tensors. Construct
        # the architecture and tokenizer from the small vendored files instead
        # of downloading the upstream ~2 GB VLM weights before overwriting them.
        cfg.vlm_model_name = str(local_vlm_assets.resolve())
        cfg.load_vlm_weights = False
        print(f"[eval] using vendored VLM config/tokenizer: {local_vlm_assets}")

    if rename_map is None:
        rename_map = _load_rename_map(policy_path)
    if rename_map:
        print(f"[eval] camera rename_map: {rename_map}")

    policy = make_policy(cfg=cfg, ds_meta=ds_meta, rename_map=rename_map)
    policy.eval()
    preprocessor_overrides: dict[str, dict[str, Any]] = {
        "device_processor": {"device": str(device)}
    }
    if local_vlm_assets.is_dir():
        preprocessor_overrides["tokenizer_processor"] = {
            "tokenizer_name": str(local_vlm_assets.resolve())
        }
    preprocessor, postprocessor = make_pre_post_processors(
        policy_cfg=cfg,
        pretrained_path=policy_path,
        preprocessor_overrides=preprocessor_overrides,
    )
    image_keys = [k for k in ds_meta.features if k.startswith("observation.images")]
    if not image_keys:
        raise RuntimeError(f"No image features in dataset {repo_id!r}")
    h, w, _ = ds_meta.features[image_keys[0]]["shape"]
    return PolicyBundle(
        policy=policy,
        preprocessor=preprocessor,
        postprocessor=postprocessor,
        device=device,
        fps=int(ds_meta.fps or DATASET_FPS),
        image_keys=image_keys,
        image_hw=(h, w),
        use_amp=use_amp,
        policy_type=getattr(cfg, "type", "unknown"),
    )


def _to_np(x) -> np.ndarray:
    if hasattr(x, "detach"):
        x = x.detach().cpu().numpy()
    return np.asarray(x)


def _render_camera(cam, size_wh: tuple[int, int]) -> np.ndarray:
    import cv2

    img = _to_np(cam.render(rgb=True)[0])
    w, h = size_wh
    if (img.shape[1], img.shape[0]) != (w, h):
        img = cv2.resize(img, (w, h), interpolation=cv2.INTER_AREA)
    return np.ascontiguousarray(img, dtype=np.uint8)


def build_observation(bundle, pb: PolicyBundle) -> dict[str, np.ndarray]:
    h, w = pb.image_hw
    obs: dict[str, np.ndarray] = {
        STATE_KEY: _to_np(bundle.franka.get_qpos()).reshape(-1).astype(np.float32),
    }
    cam_for_key = {
        "observation.images.world": bundle.world_cam,
        "observation.images.wrist": bundle.wrist_cam,
    }
    for key in pb.image_keys:
        cam = cam_for_key.get(key)
        if cam is None:
            raise RuntimeError(f"Missing camera for feature {key!r}")
        obs[key] = _render_camera(cam, (w, h))
    return obs


def apply_action(bundle, action: np.ndarray | list[float], n_sim_steps: int) -> None:
    action_arr = np.asarray(action, dtype=np.float64).reshape(-1)
    for _ in range(n_sim_steps):
        bundle.franka.control_dofs_position(action_arr)
        bundle.scene.step()
        bundle.update_wrist_cam()


def _video_frame(
    bundle,
    pb: PolicyBundle,
    observation: dict[str, np.ndarray],
    *,
    state: str,
    instruction: str,
    version: int,
    retry_count: int,
    latency_ms: float,
    scenario: str,
) -> np.ndarray:
    """Render a fixed-width multi-camera frame with Reflex telemetry."""
    import cv2

    primary = observation[pb.image_keys[0]]
    h, w = primary.shape[:2]
    panels = [primary]
    if bundle.wrist_cam is not None:
        panels.append(_render_camera(bundle.wrist_cam, (w, h)))
    if bundle.video_cam is not None:
        panels.append(_render_camera(bundle.video_cam, (w, h)))
    frame = np.ascontiguousarray(np.hstack(panels) if len(panels) > 1 else primary).copy()

    colors = {
        "RUNNING": (70, 220, 70),
        "INTERRUPTED": (0, 180, 255),
        "RECOVERING": (40, 80, 255),
        "PRECISION RECOVERY": (40, 180, 255),
        "SUCCESS": (70, 220, 70),
        "FAILED": (30, 30, 255),
    }
    cv2.rectangle(frame, (0, 0), (frame.shape[1], 78), (18, 18, 18), thickness=-1)
    cv2.putText(
        frame,
        f"REFLEX {state}",
        (12, 23),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.62,
        colors.get(state, (255, 255, 255)),
        2,
        cv2.LINE_AA,
    )
    cv2.putText(
        frame,
        f"v{version} retry={retry_count} latency={latency_ms:.1f}ms scenario={scenario}",
        (12, 47),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.45,
        (235, 235, 235),
        1,
        cv2.LINE_AA,
    )
    text = instruction if len(instruction) <= 100 else instruction[:97] + "..."
    cv2.putText(frame, text, (12, 68), cv2.FONT_HERSHEY_SIMPLEX, 0.42, (235, 235, 235), 1, cv2.LINE_AA)
    return frame


@dataclass
class EpisodeResult:
    episode_id: str
    seed: int
    task_id: str
    instruction: str
    success: bool
    object_correct: bool
    target_correct: bool
    first_attempt_success: bool
    events: list[dict[str, Any]] = field(default_factory=list)
    retry_count: int = 0
    completion_time_s: float = 0.0
    inference_latency_ms: list[float] = field(default_factory=list)
    failure_reason: str | None = None
    video_uri: str | None = None
    tier: str = "L1"
    n_goals: int = 1
    partial_success_rate: float = 0.0
    resolved_goals: list[dict[str, str]] = field(default_factory=list)
    scenario: str = "normal"
    reflex_enabled: bool = True
    interrupted: bool = False
    safe_interrupt: bool = False
    interrupt_response_steps: int | None = None
    unprotected_post_interrupt_steps: int = 0
    perturbation_applied: bool = False
    recovery_success: bool = False
    precision_recovery_attempted: bool = False
    precision_recovery_success: bool = False


def _counts_as_first_attempt(*, success: bool, retry_count: int, precision_recovery_attempted: bool) -> bool:
    """Keep deterministic recovery outcomes out of learned first-attempt metrics."""
    # A failed precision pass can still leave a fruit settling into the bowl.
    # That is a final system success, but deterministic recovery already took control.
    return bool(success and retry_count == 0 and not precision_recovery_attempted)


def _release_is_verified(action: np.ndarray, measured_qpos: np.ndarray) -> bool:
    """Require both requested and measured gripper opening before accepting a video success."""
    action = np.asarray(action, dtype=np.float64).reshape(-1)
    measured_qpos = np.asarray(measured_qpos, dtype=np.float64).reshape(-1)
    return bool(
        action.size >= 9
        and measured_qpos.size >= 2
        and float(np.mean(action[7:9])) >= 0.025
        and float(np.mean(measured_qpos[-2:])) >= 0.02
    )


def run_episode(
    bundle,
    pb: PolicyBundle,
    *,
    task_id: str,
    seed: int,
    instruction: str | None = None,
    max_steps: int | None = None,
    max_retries: int = 1,
    interrupt_at_step: int | None = None,
    interrupt_task_id: str | None = None,
    instruction_source: str = "collected",
    perturbation: str = "none",
    perturb_at_step: int | None = None,
    perturb_distance: float = 0.06,
    reflex_enabled: bool = True,
    precision_recovery: bool = False,
    save_video: bool = False,
    video_path: Path | None = None,
) -> EpisodeResult:
    task = get_task(task_id)
    max_steps = max_steps or task.max_steps
    instruction = instruction or select_instruction(task, instruction_source)
    session = CommandSession(instruction=instruction, task_id=task_id)
    safety = SafetyMonitor()
    recovery = RecoveryPolicy(max_retries=max_retries if reflex_enabled else 0)

    randomizer = EnvRandomizer(bundle, RandomizationConfig(seed=seed))
    randomizer.reset(seed=seed, task_id=task_id)
    resolved = resolve_task(bundle, task, instruction=instruction, train=False)
    # Failure detector tracks the *current* subgoal fruit (first incomplete goal).
    detector = FailureDetector(task, max_steps=max_steps)
    events: list[dict[str, Any]] = [
        {
            "type": "resolved_goals",
            "tier": resolved.tier,
            "goals": [{"object": g.object_name, "container": g.container} for g in resolved.goals],
        }
    ]

    pb.reset()
    safety.reset()

    n_sim = max(1, int(round(CONTROL_HZ / pb.fps)))
    latencies: list[float] = []
    frames: list[np.ndarray] = []
    retry_count = 0
    first_attempt_success = False
    t0 = time.perf_counter()
    policy_step = 0
    attempt_step = 0
    step_budget = max_steps * ((max_retries + 1) if reflex_enabled else 1)
    active = True
    last_action = list(FRANKA_QPOS)
    interrupt_step: int | None = None
    invalidation_step: int | None = None
    perturbation_applied = False
    precision_recovery_attempted = False
    precision_recovery_success = False
    display_state = "RUNNING"
    scenario_parts: list[str] = []
    if interrupt_at_step is not None:
        scenario_parts.append("interrupt")
    if perturbation != "none":
        scenario_parts.append(perturbation)
    scenario = "+".join(scenario_parts) or "normal"

    while active and policy_step < step_budget:
        if (
            perturb_at_step is not None
            and policy_step == perturb_at_step
            and not perturbation_applied
            and perturbation != "none"
        ):
            event = inject_perturbation(
                bundle,
                resolved,
                kind=perturbation,
                distance=perturb_distance,
                seed=seed + policy_step,
                step=policy_step,
            )
            if event is not None:
                events.append(event)
                perturbation_applied = True

        if interrupt_at_step is not None and policy_step == interrupt_at_step and interrupt_task_id:
            new_task = get_task(interrupt_task_id)
            new_instruction = select_instruction(new_task, instruction_source)
            session.set_command(instruction=new_instruction, task_id=interrupt_task_id, step=policy_step)
            task = new_task
            max_steps = max(max_steps, task.max_steps)
            remaining_attempts = (max_retries - retry_count + 1) if reflex_enabled else 1
            step_budget = max(step_budget, policy_step + max_steps * max(1, remaining_attempts))
            resolved = resolve_task(bundle, task, instruction=new_instruction, train=False)
            detector = FailureDetector(task, max_steps=max_steps)
            attempt_step = 0
            interrupt_step = policy_step
            display_state = "INTERRUPTED"
            if reflex_enabled:
                pb.reset()
            events.append(
                {
                    "type": "interrupt_inject",
                    "step": policy_step,
                    "new_task": interrupt_task_id,
                    "version": session.version,
                    "new_goals": [
                        {"object": g.object_name, "container": g.container} for g in resolved.goals
                    ],
                }
            )

        obs = build_observation(bundle, pb)
        t_inf0 = time.perf_counter()
        raw_action = pb.select_action(obs, session.instruction)
        latencies.append((time.perf_counter() - t_inf0) * 1000.0)

        safety_version = session.version if reflex_enabled else 0
        decision = safety.process(raw_action, command_version=safety_version)
        if decision.invalidate_chunk:
            pb.reset()
            events.append({"type": "chunk_invalidated", "step": policy_step, "reason": decision.reason})
            if interrupt_step is not None and invalidation_step is None:
                invalidation_step = policy_step

        action = np.asarray(decision.action, dtype=np.float64)
        apply_action(bundle, action, n_sim)
        last_action = action.tolist()

        if save_video:
            frames.append(
                _video_frame(
                    bundle,
                    pb,
                    obs,
                    state=display_state,
                    instruction=session.instruction,
                    version=session.version,
                    retry_count=retry_count,
                    latency_ms=latencies[-1],
                    scenario=scenario,
                )
            )
        if display_state in {"INTERRUPTED", "RECOVERING"}:
            display_state = "RUNNING"

        fail = detector.observe_step(bundle, step=attempt_step, action=action, unsafe=not decision.accepted)
        report_now = check_resolved_success(bundle, resolved)
        measured_qpos = _to_np(bundle.franka.get_qpos()).reshape(-1)
        release_verified = _release_is_verified(action, measured_qpos)
        if report_now["success"] and release_verified:
            if retry_count == 0:
                first_attempt_success = True
            events.append(
                {
                    "type": "release_verified",
                    "step": policy_step,
                    "commanded_gripper": float(np.mean(action[7:9])),
                    "measured_gripper": float(np.mean(measured_qpos[-2:])),
                    "post_success_seconds": POST_SUCCESS_SECONDS,
                }
            )
            hold_steps = int(POST_SUCCESS_SECONDS * pb.fps)
            for _ in range(hold_steps):
                apply_action(bundle, last_action, n_sim)
                if save_video:
                    obs_hold = build_observation(bundle, pb)
                    frames.append(
                        _video_frame(
                            bundle,
                            pb,
                            obs_hold,
                            state="SUCCESS",
                            instruction=session.instruction,
                            version=session.version,
                            retry_count=retry_count,
                            latency_ms=latencies[-1],
                            scenario=scenario,
                        )
                    )
            active = False
            break

        did_recover = False
        if fail is not None and recovery.should_retry(retry_count, fail):
            retry_count += 1
            did_recover = True
            display_state = "RECOVERING"
            events.append({"type": "recovery", "step": policy_step, "reason": fail.value, "retry": retry_count})
            recover = np.asarray(recovery.recovery_action(), dtype=np.float64)
            for _ in range(recovery.retreat_steps):
                apply_action(bundle, recover, n_sim)
            pb.reset()
            safety.reset()
            detector = FailureDetector(task, max_steps=max_steps)
            attempt_step = 0
            fail = None
        elif fail is not None:
            if precision_recovery and reflex_enabled:
                # The learned policy remains the first attempt.  After its normal
                # retry budget is exhausted, the Reflex layer may execute the
                # same strict-physics controller used to collect demonstrations.
                # Rigid pose writes stay forbidden so this cannot teleport or
                # kinematically attach the fruit.
                from radeonvla.expert import run_resolved_task

                precision_recovery_attempted = True
                display_state = "PRECISION RECOVERY"
                events.append(
                    {
                        "type": "precision_recovery_start",
                        "step": policy_step,
                        "reason": fail.value,
                        "strict_physics": True,
                    }
                )
                recover = np.asarray(recovery.recovery_action(), dtype=np.float64)
                for _ in range(recovery.retreat_steps):
                    apply_action(bundle, recover, n_sim)

                recovery_frame = 0

                def record_precision_frame(_action, _retry_count=retry_count) -> None:
                    nonlocal recovery_frame
                    recovery_frame += 1
                    if not save_video or recovery_frame % n_sim != 0:
                        return
                    recovery_obs = build_observation(bundle, pb)
                    frames.append(
                        _video_frame(
                            bundle,
                            pb,
                            recovery_obs,
                            state="PRECISION RECOVERY",
                            instruction=session.instruction,
                            version=session.version,
                            retry_count=_retry_count,
                            latency_ms=latencies[-1] if latencies else 0.0,
                            scenario=scenario,
                        )
                    )

                with forbid_rigid_pose_writes():
                    precision_recovery_success, _, precision_report = run_resolved_task(
                        bundle,
                        resolved,
                        recorder=record_precision_frame if save_video else None,
                        allow_kinematic_assist=False,
                    )
                events.append(
                    {
                        "type": "precision_recovery_complete",
                        "step": policy_step,
                        "success": precision_recovery_success,
                        "strict_physics": True,
                        "report": precision_report,
                    }
                )
                if precision_recovery_success:
                    active = False
                    break

            events.append({"type": "terminal_failure", "step": policy_step, "reason": fail.value})
            active = False
            break

        policy_step += 1
        if not did_recover:
            attempt_step += 1

    final_report = check_resolved_success(bundle, resolved)
    diag = detector.finalize(bundle)
    elapsed = time.perf_counter() - t0
    video_uri = None
    if save_video and frames and video_path is not None:
        import imageio.v2 as imageio

        video_path.parent.mkdir(parents=True, exist_ok=True)
        imageio.mimsave(video_path, frames, fps=pb.fps)
        video_uri = str(video_path)

    success = bool(final_report["success"])
    if _counts_as_first_attempt(
        success=success,
        retry_count=retry_count,
        precision_recovery_attempted=precision_recovery_attempted,
    ):
        first_attempt_success = True

    failure_reason = None
    if not success:
        if diag.failure_reason.value != "none":
            failure_reason = diag.failure_reason.value
        elif final_report["n_success"] == 0:
            failure_reason = "no_subgoal_completed"
        else:
            failure_reason = "partial_multi_goal"

    interrupt_response_steps = None
    unprotected_steps = 0
    if interrupt_step is not None:
        if invalidation_step is not None:
            interrupt_response_steps = max(0, invalidation_step - interrupt_step)
            unprotected_steps = interrupt_response_steps
        else:
            unprotected_steps = max(0, policy_step - interrupt_step + 1)
    safe_interrupt = bool(
        interrupt_step is not None
        and invalidation_step is not None
        and interrupt_response_steps is not None
        and interrupt_response_steps <= 1
    )

    return EpisodeResult(
        episode_id=f"{task_id}_{seed}",
        seed=seed,
        task_id=session.task_id,
        instruction=session.instruction,
        success=success,
        object_correct=bool(final_report["object_correct"]),
        target_correct=bool(final_report["target_correct"]),
        first_attempt_success=first_attempt_success and success,
        events=events + list(session.events) + list(diag.events) + [{"type": "goal_report", **final_report}],
        retry_count=retry_count,
        completion_time_s=elapsed,
        inference_latency_ms=latencies,
        failure_reason=failure_reason,
        video_uri=video_uri,
        tier=resolved.tier,
        n_goals=int(final_report["n_goals"]),
        partial_success_rate=float(final_report["partial_success_rate"]),
        resolved_goals=[{"object": g.object_name, "container": g.container} for g in resolved.goals],
        scenario=scenario,
        reflex_enabled=reflex_enabled,
        interrupted=interrupt_step is not None,
        safe_interrupt=safe_interrupt,
        interrupt_response_steps=interrupt_response_steps,
        unprotected_post_interrupt_steps=unprotected_steps,
        perturbation_applied=perturbation_applied,
        recovery_success=bool(success and (retry_count > 0 or precision_recovery_success)),
        precision_recovery_attempted=precision_recovery_attempted,
        precision_recovery_success=precision_recovery_success,
    )


def summarize(episodes: list[EpisodeResult]) -> dict[str, Any]:
    n = max(1, len(episodes))
    by_tier: dict[str, list[EpisodeResult]] = {}
    for e in episodes:
        by_tier.setdefault(e.tier, []).append(e)
    tier_rates = {
        tier: sum(e.success for e in eps) / max(1, len(eps)) for tier, eps in sorted(by_tier.items())
    }
    by_task: dict[str, list[EpisodeResult]] = {}
    by_scenario: dict[str, list[EpisodeResult]] = {}
    for episode in episodes:
        by_task.setdefault(episode.task_id, []).append(episode)
        by_scenario.setdefault(episode.scenario, []).append(episode)
    task_rates = {
        task_id: sum(e.success for e in eps) / max(1, len(eps)) for task_id, eps in sorted(by_task.items())
    }
    scenario_rates = {
        scenario: sum(e.success for e in eps) / max(1, len(eps))
        for scenario, eps in sorted(by_scenario.items())
    }
    interrupted = [episode for episode in episodes if episode.interrupted]
    recovered = [
        episode
        for episode in episodes
        if episode.retry_count > 0 or episode.precision_recovery_attempted
    ]
    precision_recovered = [episode for episode in episodes if episode.precision_recovery_attempted]
    all_latencies = [x for episode in episodes for x in episode.inference_latency_ms] or [0.0]
    return {
        "num_episodes": len(episodes),
        "task_success_rate": sum(e.success for e in episodes) / n,
        "object_accuracy": sum(e.object_correct for e in episodes) / n,
        "target_accuracy": sum(e.target_correct for e in episodes) / n,
        "first_attempt_success": sum(e.first_attempt_success for e in episodes) / n,
        "final_success": sum(e.success for e in episodes) / n,
        "mean_partial_success_rate": float(np.mean([e.partial_success_rate for e in episodes])),
        "success_by_tier": tier_rates,
        "success_by_task": task_rates,
        "success_by_scenario": scenario_rates,
        "recovery_success": (
            sum(e.success for e in recovered) / max(1, len(recovered))
        ),
        "recovery_attempts": len(recovered),
        "precision_recovery_attempts": len(precision_recovered),
        "precision_recovery_success": (
            sum(e.precision_recovery_success for e in precision_recovered)
            / max(1, len(precision_recovered))
        ),
        "precision_recovery_contribution": sum(e.precision_recovery_success for e in episodes) / n,
        "safe_interrupt_rate": sum(e.safe_interrupt for e in interrupted) / max(1, len(interrupted)),
        "interrupt_episodes": len(interrupted),
        "mean_interrupt_response_steps": float(
            np.mean([e.interrupt_response_steps for e in interrupted if e.interrupt_response_steps is not None])
        )
        if any(e.interrupt_response_steps is not None for e in interrupted)
        else None,
        "unprotected_post_interrupt_steps": sum(e.unprotected_post_interrupt_steps for e in interrupted),
        "mean_completion_time_s": float(np.mean([e.completion_time_s for e in episodes])),
        "p95_completion_time_s": float(np.percentile([e.completion_time_s for e in episodes], 95)),
        "mean_inference_latency_ms": float(
            np.mean(all_latencies)
        ),
        "p50_inference_latency_ms": float(np.percentile(all_latencies, 50)),
        "p95_inference_latency_ms": float(
            np.percentile(all_latencies, 95)
        ),
    }


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=PROJECT_ROOT / "configs" / "eval.yaml")
    parser.add_argument("--policy-path", required=True)
    parser.add_argument("--repo-id", default="visiobot/radeonvla_reflex")
    parser.add_argument("--dataset-root", default=None)
    parser.add_argument("--episodes", type=int, default=None, help="Total episodes (overrides per-task).")
    parser.add_argument("--episodes-per-task", type=int, default=2)
    parser.add_argument("--tasks", nargs="*", default=None)
    parser.add_argument(
        "--suite",
        default="basic",
        choices=sorted(SUITES),
        help="Task suite when --tasks is omitted (default: 20-task basic benchmark).",
    )
    parser.add_argument("--seed-start", type=int, default=50000)
    parser.add_argument("--max-retries", type=int, default=1)
    parser.add_argument(
        "--instruction-source",
        choices=INSTRUCTION_SOURCES,
        default="collected",
        help=(
            "Language used by the policy. 'collected' (default) uses the exact commands stored in "
            "the training dataset; 'heldout' is a separate paraphrase/generalization test."
        ),
    )
    parser.add_argument("--max-steps", type=int, default=None, help="Optional per-episode cap for smoke tests.")
    parser.add_argument("--device", default="cuda")
    parser.add_argument("--cpu", action="store_true")
    parser.add_argument("--backend", choices=("cpu", "gpu", "amdgpu"), default=None)
    parser.add_argument("--save-video", action="store_true")
    parser.add_argument("--interrupt-demo", action="store_true", help="Inject a mid-episode command change.")
    parser.add_argument("--disable-reflex", action="store_true", help="Ablation: no chunk invalidation or retry.")
    parser.add_argument(
        "--precision-recovery",
        action="store_true",
        help=(
            "After the learned policy exhausts its retry budget, run the strict-physics "
            "demonstration controller as a transparent Reflex fallback."
        ),
    )
    parser.add_argument("--perturbation", choices=PERTURBATIONS, default="none")
    parser.add_argument("--perturb-at-step", type=int, default=30)
    parser.add_argument("--perturb-distance", type=float, default=0.06)
    parser.add_argument("--checkpoint-sha256", default=None, help="Precomputed checkpoint tree SHA256.")
    parser.add_argument(
        "--git-commit",
        default=None,
        help="40-character source commit used for this run (for source-only remote copies without .git).",
    )
    parser.add_argument("--output", type=Path, default=None)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    import subprocess

    args = parse_args(argv)
    backend = args.backend or ("cpu" if args.cpu else "gpu")
    device = "cpu" if args.cpu else args.device
    tasks = args.tasks or list_task_ids(args.suite)

    init_genesis(backend=backend, seed=args.seed_start)
    bundle = build_scene(
        show_viewer=False,
        add_world_cam=True,
        add_wrist_cam=True,
        add_video_cam=args.save_video,
        appearance=AppearanceDR(seed=args.seed_start),
    )
    pb = load_policy(args.policy_path, args.repo_id, args.dataset_root, device)
    checkpoint_sha256 = args.checkpoint_sha256 or sha256_path(args.policy_path)
    if len(checkpoint_sha256) != 64 or any(c not in "0123456789abcdef" for c in checkpoint_sha256.lower()):
        raise ValueError("--checkpoint-sha256 must be 64 hexadecimal characters")
    checkpoint_sha256 = checkpoint_sha256.lower()

    results: list[EpisodeResult] = []
    ep_index = 0
    per_task = args.episodes_per_task
    if args.episodes is not None:
        # Distribute total episodes across tasks.
        per_task = max(1, args.episodes // max(1, len(tasks)))

    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    run_dir = EVAL_RESULTS_DIR / f"eval_{stamp}"
    run_dir.mkdir(parents=True, exist_ok=True)
    video_dir = EVAL_VIDEOS_DIR / f"eval_{stamp}"

    for task_id in tasks:
        for task_episode_index in range(per_task):
            seed = args.seed_start + ep_index
            video_path = video_dir / f"{task_id}_{seed}.mp4" if args.save_video else None
            interrupt_at = 40 if args.interrupt_demo and ep_index == 0 else None
            interrupt_task = None
            if interrupt_at is not None:
                # Prefer flipping a basic L1 side; fall back to a multi-step task.
                # Flip white/blue side when possible for interrupt demos.
                if "white_left" in task_id:
                    interrupt_task = task_id.replace("white_left", "blue_right")
                elif "blue_left" in task_id:
                    interrupt_task = task_id.replace("blue_left", "white_right")
                elif "white_right" in task_id:
                    interrupt_task = task_id.replace("white_right", "blue_left")
                elif "blue_right" in task_id:
                    interrupt_task = task_id.replace("blue_right", "white_left")
                else:
                    interrupt_task = "banana_blue_right"
                try:
                    get_task(interrupt_task)
                except ValueError:
                    interrupt_task = "banana_white_left"
            result = run_episode(
                bundle,
                pb,
                task_id=task_id,
                seed=seed,
                instruction=select_instruction(
                    get_task(task_id), args.instruction_source, task_episode_index
                ),
                max_retries=args.max_retries,
                max_steps=args.max_steps,
                interrupt_at_step=interrupt_at,
                interrupt_task_id=interrupt_task,
                instruction_source=args.instruction_source,
                perturbation=args.perturbation,
                perturb_at_step=args.perturb_at_step,
                perturb_distance=args.perturb_distance,
                reflex_enabled=not args.disable_reflex,
                precision_recovery=args.precision_recovery,
                save_video=args.save_video,
                video_path=video_path,
            )
            results.append(result)
            print(
                f"[eval] {result.episode_id} success={result.success} "
                f"first={result.first_attempt_success} retries={result.retry_count} "
                f"reason={result.failure_reason}"
            )
            ep_index += 1

    summary = summarize(results)
    commit = args.git_commit
    if commit is None:
        try:
            commit = subprocess.check_output(
                ["git", "rev-parse", "HEAD"], text=True, stderr=subprocess.DEVNULL
            ).strip()
        except Exception:
            commit = "0" * 40
    if len(commit) != 40 or any(c not in "0123456789abcdef" for c in commit.lower()):
        raise ValueError("--git-commit must be 40 hexadecimal characters")
    commit = commit.lower()

    # A CUDA-capable host may deliberately run evaluation on CPU so training can
    # keep exclusive use of the GPU.
    gpu_name = _device_display_name(pb.device)
    payload = {
        "experiment_id": f"eval_{stamp}",
        "git_commit": commit,
        "environment": {
            "gpu": gpu_name,
            "rocm": str(torch.version.hip or "none"),
            "torch": torch.__version__,
            "genesis": "1.1.2",
            "lerobot": "0.6.0",
        },
        "checkpoint": {
            "uri": args.policy_path,
            "sha256": checkpoint_sha256,
        },
        "config": {
            "tasks": tasks,
            "instruction_source": args.instruction_source,
            "seed_start": args.seed_start,
            "max_retries": args.max_retries,
            "backend": backend,
            "reflex_enabled": not args.disable_reflex,
            "precision_recovery": args.precision_recovery,
            "perturbation": args.perturbation,
            "perturb_at_step": args.perturb_at_step,
            "perturb_distance": args.perturb_distance,
        },
        "summary": summary,
        "episodes": [asdict(e) for e in results],
    }

    out = args.output or (run_dir / "results.json")
    validate_evaluation_payload(payload, PROJECT_ROOT / "artifacts" / "evaluation.schema.json")
    written = write_evaluation_bundle(payload, out)
    print(json.dumps(summary, indent=2))
    print(f"[eval] wrote {written['json']}, {written['csv']}, {written['summary']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
