"""Online LeRobot VLA plus Harness-Lite controller for the mobile parcel robot."""

from __future__ import annotations

import math
import os
from collections import deque
from dataclasses import asdict, dataclass
from pathlib import Path
import statistics
import time
from typing import Any, Iterable, Mapping

from .dataset import metric_depth_to_visual_rgb
from .mobile_depth_sidecar import depth_risk_scale_cap
from .mobile_dataset import (
    MOBILE_DEPTH_RGB_KEY,
    MOBILE_RGB_KEY,
    MOBILE_WRIST_DEPTH_RGB_KEY,
    MOBILE_WRIST_RGB_KEY,
)
from .mobile_harness import (
    MobileHarnessConfig,
    force_memory_scale_cap,
    select_mobile_harness_action,
)
from .mobile_primitive_learning import primitive_task_text
from .mobile_pi05_contract import (
    MOBILE_PI05_ABSOLUTE_ACTION_NAMES,
    MOBILE_PI05_ABSOLUTE_STATE_NAMES,
    MOBILE_PI05_RESIDUAL_ACTION_NAMES,
    MOBILE_PI05_STATE_NAMES,
    PI05ResidualContext,
    build_pi05_observable_context_task,
    decode_pi05_absolute_action,
    encode_pi05_absolute_state,
    encode_pi05_state,
    project_pi05_residual_action,
)
from .pi05_state_token_adapter import PI05_STATE_TOKEN_PROTOCOL


PI05_BASE_MODEL_ENV = "PARCEL_PI05_BASE_MODEL"


def resolve_peft_base_checkpoint(declared_path: str | None) -> str:
    """Resolve a local PEFT base model without rewriting adapter metadata."""

    override = os.environ.get(PI05_BASE_MODEL_ENV, "").strip()
    selected = override or str(declared_path or "").strip()
    if not selected:
        raise RuntimeError(
            "PEFT VLA checkpoint does not identify its base model and "
            f"{PI05_BASE_MODEL_ENV} is unset"
        )
    return selected


@dataclass(frozen=True)
class VLAGoalJudgement:
    distance_m: float
    direction_alignment: float
    direction_consistent: bool
    arrival_claimed: bool
    arrival_verified: bool
    scale_cap: float


def update_primitive_progress_peak(
    previous_peak: float,
    progress: float | None,
    *,
    stage_changed: bool,
) -> float:
    """Latch the strongest progress evidence within one primitive only."""

    if not math.isfinite(previous_peak) or not 0.0 <= previous_peak <= 1.0:
        raise ValueError("previous progress peak must be finite and in [0, 1]")
    if progress is not None and (
        not math.isfinite(progress) or not 0.0 <= progress <= 1.0
    ):
        raise ValueError("progress must be None or a finite value in [0, 1]")
    base = 0.0 if stage_changed else previous_peak
    return max(base, 0.0 if progress is None else progress)


def aggregate_pi05_residual_action_chunk(
    actions: Iterable[Iterable[float]],
    *,
    execution_steps: int,
) -> tuple[float, ...]:
    """Reduce a 30 Hz PI0.5 chunk to one command held by a slower executor.

    Continuous residuals and mode logits are averaged over the execution
    window. Suction intent and primitive progress use the final predicted
    step, matching the state reached at the end of that window.
    """

    rows = tuple(tuple(float(value) for value in row) for row in actions)
    if not rows:
        raise ValueError("PI0.5 action chunk cannot be empty")
    if not 1 <= execution_steps <= len(rows):
        raise ValueError("execution_steps must be within the PI0.5 action chunk")
    if any(len(row) != len(MOBILE_PI05_RESIDUAL_ACTION_NAMES) for row in rows):
        raise ValueError("PI0.5 residual chunk must contain 14-D actions")
    window = rows[:execution_steps]
    if any(not math.isfinite(value) for row in window for value in row):
        raise ValueError("PI0.5 action chunk contains non-finite values")
    reduced = [
        sum(row[index] for row in window) / len(window)
        for index in range(len(MOBILE_PI05_RESIDUAL_ACTION_NAMES))
    ]
    reduced[12] = window[-1][12]
    reduced[13] = window[-1][13]
    return tuple(reduced)


def prepare_pi05_open_loop_action_chunk(
    actions: Iterable[Iterable[float]],
    *,
    execution_steps: int,
    mode_logits: Iterable[float] | None = None,
) -> tuple[tuple[float, ...], ...]:
    """Prepare ordered 30 Hz residuals without averaging away their dynamics."""

    rows = tuple(tuple(float(value) for value in row) for row in actions)
    if not rows:
        raise ValueError("PI0.5 action chunk cannot be empty")
    if not 1 <= execution_steps <= len(rows):
        raise ValueError("execution_steps must be within the PI0.5 action chunk")
    if any(len(row) != len(MOBILE_PI05_RESIDUAL_ACTION_NAMES) for row in rows):
        raise ValueError("PI0.5 residual chunk must contain 14-D actions")
    window = rows[:execution_steps]
    if any(not math.isfinite(value) for row in window for value in row):
        raise ValueError("PI0.5 action chunk contains non-finite values")
    if mode_logits is None:
        return window
    logits = tuple(float(value) for value in mode_logits)
    if len(logits) != 3 or any(not math.isfinite(value) for value in logits):
        raise ValueError("mode_logits must contain three finite values")
    return tuple((*row[:9], *logits, *row[12:]) for row in window)


def aggregate_pi05_absolute_action_chunk(
    actions: Iterable[Iterable[float]],
    *,
    execution_steps: int,
) -> tuple[float, ...]:
    """Aggregate a short 23-D absolute-action window for low-rate execution."""

    rows = tuple(tuple(float(value) for value in row) for row in actions)
    action_dim = len(MOBILE_PI05_ABSOLUTE_ACTION_NAMES)
    if not rows:
        raise ValueError("PI0.5 absolute action chunk cannot be empty")
    if not 1 <= execution_steps <= len(rows):
        raise ValueError("execution_steps must be within the PI0.5 action chunk")
    if any(len(row) != action_dim for row in rows):
        raise ValueError(f"PI0.5 absolute chunk must contain {action_dim}-D actions")
    window = rows[:execution_steps]
    if any(not math.isfinite(value) for row in window for value in row):
        raise ValueError("PI0.5 absolute action chunk contains non-finite values")
    reduced = [
        statistics.fmean(row[index] for row in window)
        for index in range(action_dim)
    ]
    reduced[-1] = window[-1][-1]
    return tuple(reduced)


def prepare_pi05_absolute_open_loop_action_chunk(
    actions: Iterable[Iterable[float]],
    *,
    execution_steps: int,
    mode_logits: Iterable[float] | None = None,
) -> tuple[tuple[float, ...], ...]:
    """Prepare ordered full-authority 23-D actions without expert blending."""

    rows = tuple(tuple(float(value) for value in row) for row in actions)
    action_dim = len(MOBILE_PI05_ABSOLUTE_ACTION_NAMES)
    if not rows:
        raise ValueError("PI0.5 absolute action chunk cannot be empty")
    if not 1 <= execution_steps <= len(rows):
        raise ValueError("execution_steps must be within the PI0.5 action chunk")
    if any(len(row) != action_dim for row in rows):
        raise ValueError(f"PI0.5 absolute chunk must contain {action_dim}-D actions")
    window = rows[:execution_steps]
    if any(not math.isfinite(value) for row in window for value in row):
        raise ValueError("PI0.5 absolute action chunk contains non-finite values")
    if mode_logits is None:
        return window
    logits = tuple(float(value) for value in mode_logits)
    if len(logits) != 3 or any(not math.isfinite(value) for value in logits):
        raise ValueError("mode_logits must contain three finite values")
    return tuple((*row[:19], *logits, row[22]) for row in window)


def resolve_pi05_chunk_execution_steps(
    stage: str,
    default_steps: int,
    stage_steps: Mapping[str, int] | None,
    *,
    chunk_size: int,
) -> int:
    """Resolve an optional stage-aware execution horizon.

    Contact stages benefit from short horizons because a stale residual can
    push a parcel after a seal is lost.  Transport can use a longer horizon to
    amortize PI0.5 inference latency.  The resolver is deliberately pure so
    the policy contract and every ablation can record the exact horizon.
    """

    if not isinstance(stage, str) or not stage:
        raise ValueError("stage must be a non-empty string")
    if not 1 <= int(default_steps) <= int(chunk_size):
        raise ValueError("default_steps must be within the policy chunk")
    if stage_steps is None:
        return int(default_steps)
    unknown = set(stage_steps) - {
        "pregrasp",
        "grasp_approach",
        "lift",
        "transport",
        "place",
        "release",
    }
    if unknown:
        raise ValueError(f"stage_steps contains unsupported stages: {sorted(unknown)}")
    for name, value in stage_steps.items():
        if not 1 <= int(value) <= int(chunk_size):
            raise ValueError(f"stage_steps[{name!r}] must be within the policy chunk")
    return int(stage_steps.get(stage, default_steps))


def select_vla_policy_task(
    task: str,
    stage: str,
    *,
    uses_progress_channel: bool,
    uses_residual_contract: bool,
    residual_context: PI05ResidualContext | None = None,
) -> str:
    """Match inference language to the checkpoint's training contract."""

    if uses_residual_contract:
        if residual_context is None:
            raise ValueError("residual task selection requires observable context")
        return build_pi05_observable_context_task(task, residual_context)
    return primitive_task_text(task, stage) if uses_progress_channel else task


def evaluate_vla_goal_judgement(
    state: Iterable[float],
    vla_action: Iterable[float],
    *,
    stage: str,
    primitive_complete: bool,
    goal_xy: Iterable[float] | None = None,
    arrival_tolerance_m: float = 0.015,
) -> VLAGoalJudgement:
    """Check the VLA route proposal and arrival claim against the encoded goal."""

    state_values = tuple(float(value) for value in state)
    action_values = tuple(float(value) for value in vla_action)
    if len(state_values) != 43 or len(action_values) < 2:
        raise ValueError("goal judgement requires 43-D state and a base action")
    if any(not math.isfinite(value) for value in (*state_values, *action_values[:2])):
        raise ValueError("goal judgement inputs must be finite")
    if arrival_tolerance_m <= 0.0 or not math.isfinite(arrival_tolerance_m):
        raise ValueError("arrival tolerance must be finite and positive")
    goal_values = (
        tuple(float(value) for value in goal_xy)
        if goal_xy is not None
        else state_values[40:42]
    )
    if len(goal_values) != 2 or any(not math.isfinite(value) for value in goal_values):
        raise ValueError("goal_xy must contain two finite values")
    goal = (
        goal_values[0] - state_values[0],
        goal_values[1] - state_values[1],
    )
    distance_m = math.hypot(*goal)
    proposed = action_values[:2]
    proposed_speed = math.hypot(*proposed)
    if distance_m <= 1e-9:
        alignment = 1.0
    elif proposed_speed <= 1e-9:
        alignment = 0.0
    else:
        alignment = max(
            -1.0,
            min(
                1.0,
                (goal[0] * proposed[0] + goal[1] * proposed[1])
                / (distance_m * proposed_speed),
            ),
        )
    direction_consistent = stage != "transport" or alignment >= -0.05
    arrival_claimed = bool(primitive_complete and stage == "transport")
    arrival_verified = bool(arrival_claimed and distance_m <= arrival_tolerance_m)
    return VLAGoalJudgement(
        distance_m=distance_m,
        direction_alignment=alignment,
        direction_consistent=direction_consistent,
        arrival_claimed=arrival_claimed,
        arrival_verified=arrival_verified,
        scale_cap=1.0 if direction_consistent else 0.0,
    )


class MobileVLAHarnessController:
    """Run low-rate SmolVLA or PI0.5 inference behind the same safety harness."""

    def __init__(
        self,
        checkpoint: str | Path,
        *,
        seed: int = 20260727,
        harness_config: MobileHarnessConfig = MobileHarnessConfig(),
        force_memory_enabled: bool = False,
        depth_sidecar_enabled: bool = False,
        primitive_progress_threshold: float = 0.90,
        chunk_execution_steps: int = 1,
        chunk_execution_protocol: str | None = None,
        stage_chunk_execution_steps: Mapping[str, int] | None = None,
    ) -> None:
        import torch
        from lerobot.configs.policies import PreTrainedConfig
        from lerobot.policies import make_pre_post_processors
        from lerobot.policies.factory import get_policy_class

        checkpoint = Path(checkpoint)
        config = PreTrainedConfig.from_pretrained(checkpoint, local_files_only=True)
        if config.type not in {"smolvla", "pi05"}:
            raise RuntimeError(
                f"mobile VLA checkpoint must be SmolVLA or PI0.5, got {config.type!r}"
            )
        state_shape = config.input_features["observation.state"].shape
        output_shape = config.output_features["action"].shape
        legacy_contract = state_shape == (43,) and output_shape in {(19,), (20,)}
        residual_contract = state_shape == (len(MOBILE_PI05_STATE_NAMES),) and output_shape == (
            len(MOBILE_PI05_RESIDUAL_ACTION_NAMES),
        )
        absolute_contract = state_shape == (
            len(MOBILE_PI05_ABSOLUTE_STATE_NAMES),
        ) and output_shape == (len(MOBILE_PI05_ABSOLUTE_ACTION_NAMES),)
        if not (legacy_contract or residual_contract or absolute_contract):
            raise RuntimeError(
                "VLA checkpoint must use legacy 43-D to 19/20-D actions or the "
                f"PI0.5 residual {len(MOBILE_PI05_STATE_NAMES)}-D to "
                f"{len(MOBILE_PI05_RESIDUAL_ACTION_NAMES)}-D contract, or the "
                f"expert-independent {len(MOBILE_PI05_ABSOLUTE_STATE_NAMES)}-D to "
                f"{len(MOBILE_PI05_ABSOLUTE_ACTION_NAMES)}-D absolute contract"
            )
        visual_keys = {
            key for key in config.input_features if key.startswith("observation.images.")
        }
        supported_visual_keys = {
            MOBILE_RGB_KEY,
            MOBILE_DEPTH_RGB_KEY,
            MOBILE_WRIST_RGB_KEY,
            MOBILE_WRIST_DEPTH_RGB_KEY,
        }
        if MOBILE_RGB_KEY not in visual_keys or not visual_keys <= supported_visual_keys:
            raise RuntimeError(
                f"unsupported mobile VLA visual contract: {sorted(visual_keys)}"
            )
        config.device = "cuda"
        config.n_action_steps = 1
        self._torch = torch
        self._config = config
        self.state_dim = int(state_shape[0])
        self.action_dim = int(output_shape[0])
        self.uses_residual_contract = residual_contract
        self.uses_absolute_contract = absolute_contract
        self._mode_slice = slice(19, 22) if absolute_contract else slice(9, 12)
        self.policy_type = str(config.type)
        if not 1 <= chunk_execution_steps <= int(config.chunk_size):
            raise ValueError("chunk_execution_steps must be within the policy chunk")
        if chunk_execution_protocol is None:
            chunk_execution_protocol = (
                "pi05-window-aggregate-v1"
                if chunk_execution_steps > 1
                else "first-action-hold-v1"
            )
        supported_chunk_protocols = {
            "first-action-hold-v1",
            "pi05-window-aggregate-v1",
            "pi05-open-loop-queue-v1",
        }
        if chunk_execution_protocol not in supported_chunk_protocols:
            raise ValueError(
                f"unsupported chunk execution protocol: {chunk_execution_protocol!r}"
            )
        if chunk_execution_protocol == "first-action-hold-v1" and chunk_execution_steps != 1:
            raise ValueError("first-action hold requires chunk_execution_steps=1")
        if chunk_execution_protocol != "first-action-hold-v1" and not (
            config.type == "pi05" and (residual_contract or absolute_contract)
        ):
            raise ValueError(
                "multi-step chunk execution is supported only for PI0.5 residual "
                "or full-authority absolute contracts"
            )
        if stage_chunk_execution_steps is not None:
            # Validate eagerly so an invalid experiment cannot start inference.
            resolve_pi05_chunk_execution_steps(
                "pregrasp",
                int(chunk_execution_steps),
                stage_chunk_execution_steps,
                chunk_size=int(config.chunk_size),
            )
            if chunk_execution_protocol == "first-action-hold-v1" and any(
                int(value) != 1 for value in stage_chunk_execution_steps.values()
            ):
                raise ValueError(
                    "first-action hold requires every stage chunk horizon to be 1"
                )
        self._chunk_execution_steps = int(chunk_execution_steps)
        self._chunk_execution_protocol = str(chunk_execution_protocol)
        self._stage_chunk_execution_steps = (
            {str(stage): int(value) for stage, value in stage_chunk_execution_steps.items()}
            if stage_chunk_execution_steps is not None
            else None
        )
        self._action_chunk_queue: deque[tuple[float, ...]] = deque()
        self._raw_action_chunk_queue: deque[tuple[float, ...]] = deque()
        self._queued_chunk_stage: str | None = None
        self._queued_chunk_seed: int | None = None
        self._queued_mode_head_output: tuple[float, ...] | None = None
        self._queued_chunk_total = 0
        self._last_policy_output: tuple[float, ...] | None = None
        self.uses_state_token_adapter = False
        self.uses_mode_head_adapter = False
        self.mode_head_protocol: str | None = None
        self.training_contract_sha256: str | None = None
        training_contract_path = None
        training_contract_payload = None
        policy_class = get_policy_class(config.type)
        if config.use_peft:
            from peft import PeftConfig, PeftModel

            peft_config = PeftConfig.from_pretrained(checkpoint)
            from .pi05_state_token_adapter import (
                PI05_STATE_TOKEN_PROTOCOL,
                checkpoint_uses_pi05_state_token,
                install_pi05_state_token_adapter,
            )

            if checkpoint_uses_pi05_state_token(peft_config):
                if config.type != "pi05":
                    raise RuntimeError("state-token adapter is only supported for PI0.5")
                install_pi05_state_token_adapter()
                self.uses_state_token_adapter = True
            from .pi05_mode_head_adapter import (
                checkpoint_uses_pi05_mode_head,
                install_pi05_mode_head_adapter,
                pi05_mode_head_pooling_from_protocol,
            )

            if checkpoint_uses_pi05_mode_head(peft_config):
                if config.type != "pi05" or not (
                    residual_contract or absolute_contract
                ):
                    raise RuntimeError(
                        "fused mode head requires a residual PI0.5 checkpoint"
                    )
                import json

                from .mobile_pi05_training_contract import (
                    find_pi05_training_contract,
                )

                training_contract_path = find_pi05_training_contract(checkpoint)
                if training_contract_path is None:
                    raise RuntimeError(
                        "augmented PI0.5 checkpoint is missing "
                        "PI05_TRAINING_CONTRACT.json"
                    )
                training_contract_payload = json.loads(
                    training_contract_path.read_text(encoding="utf-8")
                )
                self.mode_head_protocol = str(
                    training_contract_payload.get("mode_head_protocol") or ""
                )
                mode_head_pooling = pi05_mode_head_pooling_from_protocol(
                    self.mode_head_protocol
                )
                install_pi05_mode_head_adapter(pooling=mode_head_pooling)
                self.uses_mode_head_adapter = True
            base_checkpoint = resolve_peft_base_checkpoint(
                peft_config.base_model_name_or_path
            )
            base_policy = policy_class.from_pretrained(
                base_checkpoint,
                config=config,
                local_files_only=True,
            )
            self._policy = PeftModel.from_pretrained(
                base_policy,
                checkpoint,
                config=peft_config,
                is_trainable=False,
            ).eval()
        else:
            self._policy = policy_class.from_pretrained(
                checkpoint, config=config, local_files_only=True
            ).eval()
        if self.uses_state_token_adapter or self.uses_mode_head_adapter:
            import json

            from .mobile_pi05_training_contract import (
                find_pi05_training_contract,
                validate_pi05_training_contract,
            )

            if training_contract_path is None:
                training_contract_path = find_pi05_training_contract(checkpoint)
            if training_contract_path is None:
                raise RuntimeError(
                    "augmented PI0.5 checkpoint is missing PI05_TRAINING_CONTRACT.json"
                )
            if training_contract_payload is None:
                training_contract_payload = json.loads(
                    training_contract_path.read_text(encoding="utf-8")
                )
            self.training_contract_sha256 = validate_pi05_training_contract(
                training_contract_payload,
                state_dim=self.state_dim,
                action_dim=self.action_dim,
                chunk_size=int(config.chunk_size),
                required_state_token_protocol=(
                    PI05_STATE_TOKEN_PROTOCOL if self.uses_state_token_adapter else None
                ),
                required_mode_head_protocol=(
                    self.mode_head_protocol if self.uses_mode_head_adapter else None
                ),
                required_visual_keys=visual_keys,
            )
        self._preprocessor, self._postprocessor = make_pre_post_processors(
            config, pretrained_path=str(checkpoint)
        )
        self._harness_config = harness_config
        self._force_memory_enabled = bool(force_memory_enabled)
        self._depth_sidecar_enabled = bool(depth_sidecar_enabled)
        self._force_history_n: deque[float] = deque(
            maxlen=harness_config.force_memory_window
        )
        self._external_force_observation_pending = False
        self._uses_depth_rgb = MOBILE_DEPTH_RGB_KEY in visual_keys
        self._uses_wrist_rgb = MOBILE_WRIST_RGB_KEY in visual_keys
        self._uses_wrist_depth_rgb = MOBILE_WRIST_DEPTH_RGB_KEY in visual_keys
        if not 0.0 < primitive_progress_threshold <= 1.0:
            raise ValueError("primitive_progress_threshold must be in (0, 1]")
        self._uses_progress_channel = (
            output_shape == (20,) or residual_contract or absolute_contract
        )
        self._primitive_progress_threshold = float(primitive_progress_threshold)
        self._primitive_progress_peak = 0.0
        self._progress_stage: str | None = None
        self._seed = int(seed)
        self._calls = 0
        self._inference_calls = 0
        self._reset()

    def set_harness_config(self, config: MobileHarnessConfig) -> None:
        """Update safety limits after a VLA-selected manipulation mode is known."""

        history = tuple(self._force_history_n)
        self._harness_config = config
        self._force_history_n = deque(
            history[-config.force_memory_window :],
            maxlen=config.force_memory_window,
        )

    def observe_contact_forces(self, left_force_n: float, right_force_n: float) -> None:
        """Sample force memory at control rate, independently of inference rate."""

        values = (float(left_force_n), float(right_force_n))
        if any(not math.isfinite(value) for value in values):
            raise ValueError("contact-force observations must be finite")
        self._force_history_n.append(max(abs(value) for value in values))
        self._external_force_observation_pending = True

    def has_queued_action(self, stage: str) -> bool:
        """Return whether the next control frame can avoid a new inference."""

        return bool(
            self._chunk_execution_protocol == "pi05-open-loop-queue-v1"
            and self._action_chunk_queue
            and self._queued_chunk_stage == stage
        )

    def _effective_chunk_execution_steps(self, stage: str) -> int:
        return resolve_pi05_chunk_execution_steps(
            stage,
            self._chunk_execution_steps,
            self._stage_chunk_execution_steps,
            chunk_size=int(self._config.chunk_size),
        )

    def select(
        self,
        *,
        rgb: Any,
        depth: Any | None = None,
        wrist_rgb: Any | None = None,
        wrist_depth: Any | None = None,
        state: Iterable[float],
        residual_context: PI05ResidualContext | None = None,
        task: str,
        expert_action: Iterable[float],
        stage: str,
        goal_xy: Iterable[float] | None = None,
        force_new_chunk: bool = False,
    ) -> tuple[tuple[float, ...], dict[str, Any]]:
        import numpy as np

        torch = self._torch
        legacy_state_values = tuple(float(value) for value in state)
        if len(legacy_state_values) != 43:
            raise ValueError("mobile controller requires the observable 43-D base state")
        if self.uses_residual_contract:
            if residual_context is None:
                raise ValueError("PI0.5 residual checkpoint requires residual_context")
            state_values = encode_pi05_state(legacy_state_values, residual_context)
        elif self.uses_absolute_contract:
            if residual_context is None:
                raise ValueError("PI0.5 absolute checkpoint requires observable context")
            state_values = encode_pi05_absolute_state(
                legacy_state_values, residual_context
            )
        else:
            state_values = legacy_state_values
        expert_values = tuple(float(value) for value in expert_action)
        image = np.asarray(rgb, dtype=np.uint8)[..., :3]
        image_tensor = (
            torch.from_numpy(image.copy()).permute(2, 0, 1).float().div_(255.0)
        )
        policy_task = select_vla_policy_task(
            task,
            stage,
            uses_progress_channel=self._uses_progress_channel,
            uses_residual_contract=(
                self.uses_residual_contract or self.uses_absolute_contract
            ),
            residual_context=residual_context,
        )
        batch: dict[str, Any] = {
            "observation.state": torch.tensor(state_values, dtype=torch.float32).unsqueeze(0).cuda(),
            MOBILE_RGB_KEY: image_tensor.unsqueeze(0).cuda(),
            "task": [policy_task],
        }
        if self._uses_depth_rgb:
            if depth is None:
                raise ValueError("RGB-D VLA checkpoint requires metric depth")
            depth_rgb = metric_depth_to_visual_rgb(depth, np)
            depth_tensor = (
                torch.from_numpy(depth_rgb.copy()).permute(2, 0, 1).float().div_(255.0)
            )
            batch[MOBILE_DEPTH_RGB_KEY] = depth_tensor.unsqueeze(0).cuda()
        if self._uses_wrist_rgb:
            if wrist_rgb is None:
                raise ValueError("wrist-RGB VLA checkpoint requires a wrist RGB image")
            wrist_image = np.asarray(wrist_rgb, dtype=np.uint8)[..., :3]
            wrist_tensor = (
                torch.from_numpy(wrist_image.copy()).permute(2, 0, 1).float().div_(255.0)
            )
            batch[MOBILE_WRIST_RGB_KEY] = wrist_tensor.unsqueeze(0).cuda()
        if self._uses_wrist_depth_rgb:
            if wrist_depth is None:
                raise ValueError("wrist RGB-D VLA checkpoint requires metric wrist depth")
            wrist_depth_rgb = metric_depth_to_visual_rgb(wrist_depth, np)
            wrist_depth_tensor = (
                torch.from_numpy(wrist_depth_rgb.copy()).permute(2, 0, 1).float().div_(255.0)
            )
            batch[MOBILE_WRIST_DEPTH_RGB_KEY] = wrist_depth_tensor.unsqueeze(0).cuda()
        use_queued_action = bool(
            self._chunk_execution_protocol == "pi05-open-loop-queue-v1"
            and not force_new_chunk
            and self._action_chunk_queue
            and self._queued_chunk_stage == stage
        )
        if force_new_chunk or (
            self._queued_chunk_stage is not None
            and self._queued_chunk_stage != stage
        ):
            self.clear_action_chunk()

        mode_head_output: tuple[float, ...] | None = None
        raw_policy_output: tuple[float, ...] | None = None
        chunk_step_index = 0
        inference_performed = not use_queued_action
        if use_queued_action:
            call_seed = int(self._queued_chunk_seed)
            chunk_step_index = self._queued_chunk_total - len(self._action_chunk_queue)
            policy_output_values = list(self._action_chunk_queue.popleft())
            raw_policy_output = (
                self._raw_action_chunk_queue.popleft()
                if self._raw_action_chunk_queue
                else None
            )
            mode_head_output = self._queued_mode_head_output
            latency_ms = 0.0
        else:
            call_seed = self._seed + self._inference_calls
            self._reset()
            # Genesis and PI0.5 share PyTorch's ROCm RNG. Forking the state keeps
            # diffusion sampling reproducible without perturbing contact dynamics.
            with torch.random.fork_rng(devices=[torch.cuda.current_device()]):
                torch.manual_seed(call_seed)
                torch.cuda.manual_seed_all(call_seed)
                with torch.inference_mode():
                    torch.cuda.synchronize()
                    started = time.perf_counter()
                    processed_batch = self._preprocessor(batch)
                    mode_head_logits = None
                    if self.uses_mode_head_adapter:
                        from .pi05_mode_head_adapter import predict_pi05_mode_head

                        mode_head_logits = predict_pi05_mode_head(
                            self._policy, processed_batch
                        )
                    if mode_head_logits is not None:
                        mode_head_output = tuple(
                            float(value)
                            for value in mode_head_logits.detach().cpu().reshape(-1)
                        )
                        if len(mode_head_output) != 3:
                            raise RuntimeError(
                                "PI0.5 fused mode head did not produce three logits"
                            )
                    if self._chunk_execution_protocol == "first-action-hold-v1":
                        raw_action = self._policy.select_action(processed_batch)
                        raw_policy_output = tuple(
                            float(value)
                            for value in raw_action.detach().cpu().reshape(-1)
                        )
                        action = self._postprocessor(raw_action)
                        policy_output_values = [
                            float(value)
                            for value in action.detach().cpu().reshape(-1)
                        ]
                    else:
                        raw_action_chunk = self._policy.predict_action_chunk(
                            processed_batch
                        )
                        raw_chunk_rows = [
                            tuple(float(value) for value in row)
                            for row in raw_action_chunk.detach()
                            .cpu()
                            .reshape(-1, self.action_dim)
                            .tolist()
                        ]
                        action_chunk = self._postprocessor(raw_action_chunk)
                        chunk_rows = [
                            tuple(float(value) for value in row)
                            for row in action_chunk.detach()
                            .cpu()
                            .reshape(-1, self.action_dim)
                            .tolist()
                        ]
                        if self._chunk_execution_protocol == "pi05-window-aggregate-v1":
                            if self.uses_absolute_contract:
                                raw_policy_output = aggregate_pi05_absolute_action_chunk(
                                    raw_chunk_rows,
                                    execution_steps=self._effective_chunk_execution_steps(
                                        stage
                                    ),
                                )
                                policy_output_values = list(
                                    aggregate_pi05_absolute_action_chunk(
                                        chunk_rows,
                                        execution_steps=self._effective_chunk_execution_steps(
                                            stage
                                        ),
                                    )
                                )
                            else:
                                raw_policy_output = aggregate_pi05_residual_action_chunk(
                                    raw_chunk_rows,
                                    execution_steps=self._effective_chunk_execution_steps(
                                        stage
                                    ),
                                )
                                policy_output_values = list(
                                    aggregate_pi05_residual_action_chunk(
                                        chunk_rows,
                                        execution_steps=self._effective_chunk_execution_steps(
                                            stage
                                        ),
                                    )
                                )
                        else:
                            if self.uses_absolute_contract:
                                raw_execution_window = (
                                    prepare_pi05_absolute_open_loop_action_chunk(
                                        raw_chunk_rows,
                                        execution_steps=self._effective_chunk_execution_steps(
                                            stage
                                        ),
                                    )
                                )
                                execution_window = (
                                    prepare_pi05_absolute_open_loop_action_chunk(
                                        chunk_rows,
                                        execution_steps=self._effective_chunk_execution_steps(
                                            stage
                                        ),
                                        mode_logits=mode_head_output,
                                    )
                                )
                            else:
                                raw_execution_window = prepare_pi05_open_loop_action_chunk(
                                    raw_chunk_rows,
                                    execution_steps=self._effective_chunk_execution_steps(
                                        stage
                                    ),
                                )
                                execution_window = prepare_pi05_open_loop_action_chunk(
                                    chunk_rows,
                                    execution_steps=self._effective_chunk_execution_steps(
                                        stage
                                    ),
                                    mode_logits=mode_head_output,
                                )
                            policy_output_values = list(execution_window[0])
                            raw_policy_output = raw_execution_window[0]
                            self._action_chunk_queue.extend(execution_window[1:])
                            self._raw_action_chunk_queue.extend(
                                raw_execution_window[1:]
                            )
                            self._queued_chunk_stage = stage
                            self._queued_chunk_seed = call_seed
                            self._queued_mode_head_output = mode_head_output
                            self._queued_chunk_total = len(execution_window)
                    torch.cuda.synchronize()
                    latency_ms = (time.perf_counter() - started) * 1000.0
            self._inference_calls += 1
        if mode_head_output is not None:
            policy_output_values[self._mode_slice] = mode_head_output
        policy_output = tuple(policy_output_values)
        residual_boundary_l2 = (
            math.sqrt(
                sum(
                    (current - previous) ** 2
                    for current, previous in zip(
                        policy_output[:9], self._last_policy_output[:9], strict=True
                    )
                )
            )
            if self._last_policy_output is not None
            else None
        )
        self._last_policy_output = policy_output
        residual_projection = None
        absolute_projection = None
        if self.uses_residual_contract:
            assert residual_context is not None
            residual_projection = project_pi05_residual_action(
                policy_output,
                expert_values,
                stage=stage,
                grasp_mode=residual_context.grasp_mode,
            )
            predicted = residual_projection.absolute_action
            progress_raw = policy_output[13]
        elif self.uses_absolute_contract:
            absolute_projection = decode_pi05_absolute_action(policy_output)
            predicted = absolute_projection.absolute_action
            progress_raw = absolute_projection.progress
        else:
            predicted = policy_output[:19]
            progress_raw = policy_output[19] if self._uses_progress_channel else None
        progress = (
            min(1.0, max(0.0, progress_raw)) if progress_raw is not None and math.isfinite(progress_raw) else None
        )
        instantaneous_complete = bool(
            progress is not None and progress >= self._primitive_progress_threshold
        )
        self._primitive_progress_peak = update_primitive_progress_peak(
            self._primitive_progress_peak,
            progress,
            stage_changed=self._progress_stage != stage,
        )
        self._progress_stage = stage
        primitive_complete = bool(
            self._primitive_progress_peak >= self._primitive_progress_threshold
        )
        goal_judgement = evaluate_vla_goal_judgement(
            legacy_state_values,
            predicted,
            stage=stage,
            primitive_complete=primitive_complete,
            goal_xy=goal_xy,
        )
        if self._external_force_observation_pending:
            self._external_force_observation_pending = False
        else:
            self._force_history_n.append(
                max(abs(legacy_state_values[38]), abs(legacy_state_values[39]))
            )
        force_memory = force_memory_scale_cap(
            self._force_history_n,
            config=self._harness_config,
        )
        depth_risk = depth_risk_scale_cap(depth) if self._depth_sidecar_enabled else None
        force_scale_cap = force_memory.scale_cap if self._force_memory_enabled else 1.0
        depth_scale_cap = depth_risk.scale_cap if depth_risk is not None else 1.0
        maximum_vla_scale = min(
            force_scale_cap, depth_scale_cap, goal_judgement.scale_cap
        )
        if goal_judgement.scale_cap < min(force_scale_cap, depth_scale_cap):
            maximum_vla_scale_reason = "goal_direction_mismatch"
        elif depth_scale_cap < force_scale_cap:
            maximum_vla_scale_reason = "depth_geometry_scale_gate"
        else:
            maximum_vla_scale_reason = "force_memory_scale_gate"
        decision = select_mobile_harness_action(
            state=legacy_state_values,
            expert_action=expert_values,
            vla_action=predicted,
            stage=stage,
            config=self._harness_config,
            maximum_vla_scale=maximum_vla_scale,
            maximum_vla_scale_reason=maximum_vla_scale_reason,
            arm_reference_is_expert_target=self.uses_residual_contract,
            absolute_vla_action=self.uses_absolute_contract,
        )
        self._calls += 1
        task_action_corrections = [
            reason
            for reason in decision.selected.reasons
            if reason in {"deterministic_release_interlock", "stage_tool_interlock"}
        ]
        safety_action_corrections = [
            reason
            for reason in decision.selected.reasons
            if reason in {"cartesian_step_clipped", "base_speed_clipped"}
            or reason.endswith("_scale_gate")
            or reason.startswith("force_gate_stop:")
        ]
        absolute_motion_full_authority = bool(
            self.uses_absolute_contract
            and decision.selected.scale == 1.0
            and not decision.fallback_to_expert
            and not decision.emergency_stop
            and not decision.rejected_vla
            and not task_action_corrections
        )
        task_routing_authority = "external_stage_machine"
        pure_vla_qualified_step = bool(
            absolute_motion_full_authority
            and task_routing_authority == "vla_policy"
        )
        telemetry = {
            "policy_type": self.policy_type,
            "call_index": self._calls - 1,
            "seed": call_seed,
            "stage": stage,
            "observation_modality": "rgbd" if self._uses_depth_rgb else "rgb",
            "state_token_adapter": self.uses_state_token_adapter,
            "state_token_protocol": (
                PI05_STATE_TOKEN_PROTOCOL if self.uses_state_token_adapter else None
            ),
            "mode_head_adapter": self.uses_mode_head_adapter,
            "grasp_mode_decoder": (
                self.mode_head_protocol
                if self.uses_mode_head_adapter
                else "pi05_flow_action_channels_v1"
            ),
            "mode_head_logits": (
                list(mode_head_output) if mode_head_output is not None else None
            ),
            "training_contract_sha256": self.training_contract_sha256,
            "latency_ms": latency_ms,
            "inference_performed": inference_performed,
            "inference_call_index": self._inference_calls - 1,
            "chunk_execution_protocol": self._chunk_execution_protocol,
            "chunk_execution_steps": self._chunk_execution_steps,
            "stage_chunk_execution_steps": (
                dict(self._stage_chunk_execution_steps)
                if self._stage_chunk_execution_steps is not None
                else None
            ),
            "effective_chunk_execution_steps": self._effective_chunk_execution_steps(
                stage
            ),
            "chunk_step_index": chunk_step_index,
            "chunk_steps_remaining": len(self._action_chunk_queue),
            "residual_boundary_l2": residual_boundary_l2,
            "finite": len(policy_output) == self.action_dim
            and all(math.isfinite(value) for value in policy_output),
            "action_contract": (
                "pi05_residual_v1"
                if self.uses_residual_contract
                else (
                    "pi05_absolute_v1"
                    if self.uses_absolute_contract
                    else "legacy_absolute"
                )
            ),
            "policy_authority": (
                "hybrid_expert_reference_plus_vla_residual"
                if self.uses_residual_contract
                else "absolute_vla_action_candidate"
            ),
            "expert_reference_used": bool(self.uses_residual_contract),
            "expert_reference_semantics": (
                "residuals_are_added_to_expert_action_before_harness"
                if self.uses_residual_contract
                else (
                    "expert_action_is_not_used_by_absolute_vla_safety_projection"
                    if self.uses_absolute_contract
                    else "expert_action_is_harness_fallback_only"
                )
            ),
            "encoded_pi05_state": (
                list(state_values)
                if self.uses_residual_contract or self.uses_absolute_contract
                else None
            ),
            "current_observable_state": list(legacy_state_values),
            "current_ee_pose": {
                "left_position_m_quaternion_wxyz": list(legacy_state_values[24:31]),
                "right_position_m_quaternion_wxyz": list(legacy_state_values[31:38]),
            },
            "raw_policy_action": (
                list(raw_policy_output) if raw_policy_output is not None else None
            ),
            "postprocessed_action": list(policy_output),
            "raw_residual_action": (
                list(policy_output) if self.uses_residual_contract else None
            ),
            "raw_absolute_action": (
                list(policy_output) if self.uses_absolute_contract else None
            ),
            "policy_task": policy_task,
            "primitive_progress_enabled": self._uses_progress_channel,
            "primitive_progress_raw": progress_raw,
            "primitive_progress": progress,
            "primitive_progress_peak": self._primitive_progress_peak,
            "primitive_complete_instantaneous": instantaneous_complete,
            "primitive_complete": primitive_complete,
            "goal_judgement": asdict(goal_judgement),
            "selected_scale": decision.selected.scale,
            "absolute_motion_full_authority": absolute_motion_full_authority,
            "absolute_full_authority": pure_vla_qualified_step,
            "pure_vla_qualified_step": pure_vla_qualified_step,
            "system_control_class": (
                "shielded_vla" if self.uses_absolute_contract else "hybrid_vla"
            ),
            "task_routing_authority": task_routing_authority,
            "fallback_to_expert": decision.fallback_to_expert,
            "emergency_stop": decision.emergency_stop,
            "rejected_vla": decision.rejected_vla,
            "tool_command_corrections": decision.selected.tool_command_corrections,
            "task_action_corrections": task_action_corrections,
            "safety_action_corrections": safety_action_corrections,
            "candidate_count": len(decision.candidates),
            "selected_reasons": list(decision.selected.reasons),
            "raw_base_action": list(predicted[:3]),
            "decoded_vla_action": list(predicted),
            "full_expert_action": list(expert_values),
            "selected_command": list(decision.selected.action),
            "command_contract": {
                "frame": "world_cartesian_ee_and_robot_base_velocity",
                "base_units": ["m/s", "m/s", "rad/s"],
                "arm_position_units": "m",
                "arm_orientation": "unit_quaternion_wxyz",
                "tool_units": "binary_sign_command",
            },
            "expert_base_action": list(expert_values[:3]),
            "selected_base_action": list(decision.selected.action[:3]),
            "force_memory_enabled": self._force_memory_enabled,
            "force_memory": force_memory.to_dict(),
            "depth_sidecar_enabled": self._depth_sidecar_enabled,
            "depth_risk": depth_risk.to_dict() if depth_risk is not None else None,
            "combined_scale_cap": maximum_vla_scale,
            "combined_scale_cap_reason": maximum_vla_scale_reason,
            "residual_projection": (
                {
                    "predicted_mode": residual_projection.predicted_mode,
                    "mode_logits": list(residual_projection.mode_logits),
                    "requested_suction": residual_projection.requested_suction,
                    "progress": residual_projection.progress,
                    "base_residual": list(residual_projection.base_residual),
                    "left_contact_residual_m": list(
                        residual_projection.left_contact_residual_m
                    ),
                    "right_contact_residual_m": list(
                        residual_projection.right_contact_residual_m
                    ),
                    "arm_authority_m": residual_projection.arm_authority_m,
                }
                if residual_projection is not None
                else None
            ),
            "absolute_projection": (
                {
                    "predicted_mode": absolute_projection.predicted_mode,
                    "mode_logits": list(absolute_projection.mode_logits),
                    "requested_suction": absolute_projection.requested_suction,
                    "progress": absolute_projection.progress,
                }
                if absolute_projection is not None
                else None
            ),
        }
        return decision.selected.action, telemetry
    def warmup(
        self,
        *,
        rgb: Any,
        depth: Any | None = None,
        wrist_rgb: Any | None = None,
        wrist_depth: Any | None = None,
        state: Iterable[float],
        residual_context: PI05ResidualContext | None = None,
        task: str,
        expert_action: Iterable[float],
    ) -> None:
        self.select(
            rgb=rgb,
            depth=depth,
            wrist_rgb=wrist_rgb,
            wrist_depth=wrist_depth,
            state=state,
            residual_context=residual_context,
            task=task,
            expert_action=expert_action,
            stage="pregrasp",
        )
        self.reset_runtime_state()

    def reset_runtime_state(self) -> None:
        """Reset episode-local inference, force-memory, and chunk state."""

        self._calls = 0
        self._inference_calls = 0
        self._force_history_n.clear()
        self._external_force_observation_pending = False
        self._primitive_progress_peak = 0.0
        self._progress_stage = None
        self.clear_action_chunk()
        self._reset()

    def clear_action_chunk(self) -> None:
        """Discard stale open-loop actions after a stage or routing boundary."""

        self._action_chunk_queue.clear()
        raw_queue = getattr(self, "_raw_action_chunk_queue", None)
        if raw_queue is not None:
            raw_queue.clear()
        self._queued_chunk_stage = None
        self._queued_chunk_seed = None
        self._queued_mode_head_output = None
        self._queued_chunk_total = 0
        self._last_policy_output = None

    def _reset(self) -> None:
        for name in ("_policy", "_preprocessor", "_postprocessor"):
            component = getattr(self, name, None)
            reset = getattr(component, "reset", None)
            if callable(reset):
                reset()


# Compatibility for existing experiment scripts and stored ablation commands.
MobileSmolVLAHarnessController = MobileVLAHarnessController
