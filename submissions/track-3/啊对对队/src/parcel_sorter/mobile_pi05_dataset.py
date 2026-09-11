"""Verified replay dataset for autonomous PI0.5 residual rollouts."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import json
import math
from pathlib import Path
from typing import Any, Callable

from .dataset import metric_depth_to_visual_rgb
from .mobile_dataset import (
    MOBILE_DEPTH_KEY,
    MOBILE_DEPTH_RGB_KEY,
    MOBILE_PRIVILEGED_STATE_NAMES,
    MOBILE_RGB_KEY,
    MOBILE_STAGE_NAMES,
    MOBILE_WRIST_DEPTH_KEY,
    MOBILE_WRIST_DEPTH_RGB_KEY,
    MOBILE_WRIST_RGB_KEY,
    mobile_policy_visual_keys,
)
from .mobile_pi05_contract import (
    MOBILE_PI05_ABSOLUTE_ACTION_NAMES,
    MOBILE_PI05_ABSOLUTE_STATE_NAMES,
    MOBILE_PI05_RESIDUAL_ACTION_NAMES,
    MOBILE_PI05_STATE_NAMES,
)
from .mobile_policy_attribution import (
    ABSOLUTE_VLA_AUTHORITY,
    HYBRID_VLA_AUTHORITY,
    PURE_VLA_CONTROL_CLASS,
)


PI05_AUTONOMOUS_REPLAY_PROTOCOL = "pi05-autonomous-verified-replay-v1"
PI05_ABSOLUTE_REPLAY_PROTOCOL = "pi05-absolute-vla-verified-replay-v1"


@dataclass(frozen=True)
class PI05AutonomousResidualFrame:
    frame_index: int
    timestamp_seconds: float
    stage: str
    state: tuple[float, ...]
    raw_residual_action: tuple[float, ...]
    privileged_state: tuple[float, ...]
    task: str
    inference_performed: bool
    inference_call_index: int
    chunk_step_index: int
    rgb: Any | None = None
    depth: Any | None = None
    wrist_rgb: Any | None = None
    wrist_depth: Any | None = None

    def __post_init__(self) -> None:
        if self.stage not in MOBILE_STAGE_NAMES:
            raise ValueError(f"unknown mobile task stage: {self.stage}")
        if len(self.state) != len(MOBILE_PI05_STATE_NAMES):
            raise ValueError(
                f"PI0.5 state must have {len(MOBILE_PI05_STATE_NAMES)} values, "
                f"got {len(self.state)}"
            )
        if len(self.raw_residual_action) != len(MOBILE_PI05_RESIDUAL_ACTION_NAMES):
            raise ValueError(
                "PI0.5 residual action must have "
                f"{len(MOBILE_PI05_RESIDUAL_ACTION_NAMES)} values, "
                f"got {len(self.raw_residual_action)}"
            )
        if len(self.privileged_state) != len(MOBILE_PRIVILEGED_STATE_NAMES):
            raise ValueError(
                "mobile privileged state must have "
                f"{len(MOBILE_PRIVILEGED_STATE_NAMES)} values"
            )
        numeric = (
            *self.state,
            *self.raw_residual_action,
            *self.privileged_state,
            self.timestamp_seconds,
        )
        if any(not math.isfinite(float(value)) for value in numeric):
            raise ValueError("PI0.5 replay frame contains non-finite values")
        if self.frame_index < 0 or self.inference_call_index < 0 or self.chunk_step_index < 0:
            raise ValueError("PI0.5 replay indices must be non-negative")


@dataclass(frozen=True)
class PI05AutonomousAbsoluteFrame:
    frame_index: int
    timestamp_seconds: float
    stage: str
    state: tuple[float, ...]
    absolute_action_target: tuple[float, ...]
    privileged_state: tuple[float, ...]
    task: str
    inference_performed: bool
    inference_call_index: int
    chunk_step_index: int
    rgb: Any | None = None
    depth: Any | None = None
    wrist_rgb: Any | None = None
    wrist_depth: Any | None = None

    def __post_init__(self) -> None:
        if self.stage not in MOBILE_STAGE_NAMES:
            raise ValueError(f"unknown mobile task stage: {self.stage}")
        if len(self.state) != len(MOBILE_PI05_ABSOLUTE_STATE_NAMES):
            raise ValueError("PI0.5 absolute state must contain 80 values")
        if len(self.absolute_action_target) != len(MOBILE_PI05_ABSOLUTE_ACTION_NAMES):
            raise ValueError("PI0.5 absolute action target must contain 23 values")
        if len(self.privileged_state) != len(MOBILE_PRIVILEGED_STATE_NAMES):
            raise ValueError("mobile privileged state must contain seven values")
        numeric = (
            *self.state,
            *self.absolute_action_target,
            *self.privileged_state,
            self.timestamp_seconds,
        )
        if any(not math.isfinite(float(value)) for value in numeric):
            raise ValueError("PI0.5 absolute replay frame contains non-finite values")
        if self.frame_index < 0 or self.inference_call_index < 0 or self.chunk_step_index < 0:
            raise ValueError("PI0.5 replay indices must be non-negative")


@dataclass(frozen=True)
class PI05AutonomousRolloutQualification:
    success: bool
    policy_type: str
    policy_mode: str
    residual_contract: bool
    vla_routes_grasp_mode: bool
    goal_verdict_required: bool
    goal_arrival_verified: bool
    policy_authority: str
    expert_reference_used: bool
    expert_reference_semantics: tuple[str, ...]
    expert_fallback_count: int
    emergency_stop_count: int
    force_violation_count: int
    recorded_frames: int
    material_residual_frames: int

    def rejection_reasons(self) -> tuple[str, ...]:
        reasons: list[str] = []
        checks = (
            (self.success, "task_failed"),
            (self.policy_type == "pi05", "policy_is_not_pi05"),
            (self.policy_mode == "pi05_residual", "policy_mode_is_not_pi05_residual"),
            (self.residual_contract, "checkpoint_contract_is_not_residual"),
            (self.vla_routes_grasp_mode, "vla_did_not_route_grasp_mode"),
            (self.goal_verdict_required, "vla_goal_verdict_not_required"),
            (self.goal_arrival_verified, "vla_goal_arrival_not_verified"),
            (
                self.policy_authority == HYBRID_VLA_AUTHORITY,
                "residual_policy_authority_is_not_hybrid",
            ),
            (self.expert_reference_used, "residual_expert_reference_not_disclosed"),
            (self.expert_fallback_count == 0, "expert_fallback_used"),
            (self.emergency_stop_count == 0, "emergency_stop_used"),
            (self.force_violation_count == 0, "force_limit_violated"),
            (self.recorded_frames > 0, "no_policy_frames"),
            (self.material_residual_frames > 0, "no_material_residual_action"),
        )
        reasons.extend(reason for passed, reason in checks if not passed)
        return tuple(reasons)

    @property
    def accepted(self) -> bool:
        return not self.rejection_reasons()

    @property
    def accepted_as_pure_vla_experience(self) -> bool:
        return False


@dataclass(frozen=True)
class PI05AbsoluteRolloutQualification:
    success: bool
    policy_type: str
    policy_mode: str
    absolute_contract: bool
    grasp_mode: str
    vla_routes_grasp_mode: bool
    goal_verdict_required: bool
    goal_arrival_verified: bool
    policy_authority: str
    system_control_class: str
    task_action_correction_count: int
    expert_reference_used: bool
    expert_reference_semantics: tuple[str, ...]
    expert_fallback_count: int
    emergency_stop_count: int
    force_violation_count: int
    minimum_selected_scale: float
    transport_deadline_handoff: bool
    recorded_frames: int
    material_action_frames: int
    nonzero_base_command_frames: int

    def rejection_reasons(self) -> tuple[str, ...]:
        checks = (
            (self.success, "task_failed"),
            (self.policy_type == "pi05", "policy_is_not_pi05"),
            (self.policy_mode == "pi05_absolute", "policy_mode_is_not_pi05_absolute"),
            (self.absolute_contract, "checkpoint_contract_is_not_absolute"),
            (self.grasp_mode in {"top_suction", "side_suction", "cooperative_cradle"}, "invalid_grasp_mode"),
            (self.vla_routes_grasp_mode, "vla_did_not_route_grasp_mode"),
            (self.goal_verdict_required, "vla_goal_verdict_not_required"),
            (self.goal_arrival_verified, "vla_goal_arrival_not_verified"),
            (
                self.policy_authority == ABSOLUTE_VLA_AUTHORITY,
                "policy_authority_is_not_absolute_vla",
            ),
            (
                self.system_control_class == PURE_VLA_CONTROL_CLASS,
                "system_control_is_not_pure_vla",
            ),
            (
                self.task_action_correction_count == 0,
                "task_action_correction_used",
            ),
            (not self.expert_reference_used, "absolute_vla_used_expert_reference"),
            (self.expert_fallback_count == 0, "expert_fallback_used"),
            (self.emergency_stop_count == 0, "emergency_stop_used"),
            (self.force_violation_count == 0, "force_limit_violated"),
            (
                math.isclose(self.minimum_selected_scale, 1.0, abs_tol=1e-9),
                "absolute_vla_not_full_authority",
            ),
            (not self.transport_deadline_handoff, "transport_deadline_expert_handoff"),
            (self.recorded_frames > 0, "no_policy_frames"),
            (self.material_action_frames > 0, "no_material_absolute_action"),
            (self.nonzero_base_command_frames > 0, "no_nonzero_base_command"),
        )
        return tuple(reason for passed, reason in checks if not passed)

    @property
    def accepted(self) -> bool:
        return not self.rejection_reasons()

    @property
    def accepted_as_pure_vla_experience(self) -> bool:
        return self.accepted


class MobilePI05AutonomousLeRobotWriter:
    """Write raw PI0.5 residuals; admission is decided after the rollout."""

    def __init__(
        self,
        root: str | Path,
        *,
        fps: int = 30,
        image_size: tuple[int, int] = (224, 224),
        repo_id: str = "local/mobile-pi05-autonomous-verified-replay",
        dataset_factory: Callable[..., Any] | None = None,
        include_wrist_rgbd: bool = False,
    ) -> None:
        if dataset_factory is None:
            try:
                from lerobot.datasets.lerobot_dataset import LeRobotDataset
            except ImportError as exc:
                raise RuntimeError("LeRobot is required to record PI0.5 replay") from exc
            dataset_factory = LeRobotDataset.create

        self.root = Path(root)
        width, height = image_size
        audit_info = {"policy_input": False}
        features: dict[str, dict[str, Any]] = {
            "observation.state": {
                "dtype": "float32",
                "shape": (len(MOBILE_PI05_STATE_NAMES),),
                "names": list(MOBILE_PI05_STATE_NAMES),
            },
            "action": {
                "dtype": "float32",
                "shape": (len(MOBILE_PI05_RESIDUAL_ACTION_NAMES),),
                "names": list(MOBILE_PI05_RESIDUAL_ACTION_NAMES),
                "info": {"semantics": "raw_pi05_residual_before_harness"},
            },
            "observation.privileged_state": {
                "dtype": "float32",
                "shape": (len(MOBILE_PRIVILEGED_STATE_NAMES),),
                "names": list(MOBILE_PRIVILEGED_STATE_NAMES),
                "info": audit_info,
            },
            "observation.stage_id": {
                "dtype": "int64",
                "shape": (1,),
                "names": ["stage_id"],
                "info": {"stages": list(MOBILE_STAGE_NAMES), **audit_info},
            },
            "observation.policy_inference_performed": {
                "dtype": "int64",
                "shape": (1,),
                "names": ["policy_inference_performed"],
                "info": audit_info,
            },
            "observation.policy_inference_call_index": {
                "dtype": "int64",
                "shape": (1,),
                "names": ["policy_inference_call_index"],
                "info": audit_info,
            },
            "observation.policy_chunk_step_index": {
                "dtype": "int64",
                "shape": (1,),
                "names": ["policy_chunk_step_index"],
                "info": audit_info,
            },
            MOBILE_RGB_KEY: {
                "dtype": "image",
                "shape": (height, width, 3),
                "names": ["height", "width", "channels"],
            },
            MOBILE_DEPTH_KEY: {
                "dtype": "image",
                "shape": (height, width, 1),
                "names": ["height", "width", "channels"],
                "info": {"is_depth_map": True, "depth_unit": "m"},
            },
            MOBILE_DEPTH_RGB_KEY: {
                "dtype": "image",
                "shape": (height, width, 3),
                "names": ["height", "width", "channels"],
                "info": {"derived_from": MOBILE_DEPTH_KEY},
            },
        }
        if include_wrist_rgbd:
            features[MOBILE_WRIST_RGB_KEY] = {
                "dtype": "image",
                "shape": (height, width, 3),
                "names": ["height", "width", "channels"],
            }
            features[MOBILE_WRIST_DEPTH_KEY] = {
                "dtype": "image",
                "shape": (height, width, 1),
                "names": ["height", "width", "channels"],
                "info": {"is_depth_map": True, "depth_unit": "m"},
            }
            features[MOBILE_WRIST_DEPTH_RGB_KEY] = {
                "dtype": "image",
                "shape": (height, width, 3),
                "names": ["height", "width", "channels"],
                "info": {"derived_from": MOBILE_WRIST_DEPTH_KEY},
            }
        self._include_wrist_rgbd = include_wrist_rgbd
        self._dataset = dataset_factory(
            repo_id=repo_id,
            root=self.root,
            fps=fps,
            features=features,
            robot_type="mobile_bi_franka_sim",
            use_videos=False,
            image_writer_threads=4,
        )
        self.frame_count = 0
        self.material_residual_frames = 0

    def add_frame(self, frame: PI05AutonomousResidualFrame) -> None:
        import numpy as np

        if frame.rgb is None or frame.depth is None:
            raise ValueError("PI0.5 autonomous replay requires overhead RGB-D")
        depth = np.asarray(frame.depth, dtype=np.float32)
        payload: dict[str, Any] = {
            "observation.state": np.asarray(frame.state, dtype=np.float32),
            "action": np.asarray(frame.raw_residual_action, dtype=np.float32),
            "observation.privileged_state": np.asarray(
                frame.privileged_state, dtype=np.float32
            ),
            "observation.stage_id": np.asarray(
                [MOBILE_STAGE_NAMES.index(frame.stage)], dtype=np.int64
            ),
            "observation.policy_inference_performed": np.asarray(
                [int(frame.inference_performed)], dtype=np.int64
            ),
            "observation.policy_inference_call_index": np.asarray(
                [frame.inference_call_index], dtype=np.int64
            ),
            "observation.policy_chunk_step_index": np.asarray(
                [frame.chunk_step_index], dtype=np.int64
            ),
            MOBILE_RGB_KEY: np.asarray(frame.rgb, dtype=np.uint8)[..., :3],
            MOBILE_DEPTH_KEY: depth[..., None] if depth.ndim == 2 else depth,
            MOBILE_DEPTH_RGB_KEY: metric_depth_to_visual_rgb(depth, np),
            "task": frame.task,
        }
        if self._include_wrist_rgbd:
            if frame.wrist_rgb is None or frame.wrist_depth is None:
                raise ValueError("PI0.5 wrist replay requires wrist RGB-D")
            wrist_depth = np.asarray(frame.wrist_depth, dtype=np.float32)
            payload[MOBILE_WRIST_RGB_KEY] = np.asarray(
                frame.wrist_rgb, dtype=np.uint8
            )[..., :3]
            payload[MOBILE_WRIST_DEPTH_KEY] = (
                wrist_depth[..., None] if wrist_depth.ndim == 2 else wrist_depth
            )
            payload[MOBILE_WRIST_DEPTH_RGB_KEY] = metric_depth_to_visual_rgb(
                wrist_depth, np
            )
        self._dataset.add_frame(payload)
        self.frame_count += 1
        self.material_residual_frames += int(
            max(abs(value) for value in frame.raw_residual_action[:9]) > 1e-5
        )

    def commit_or_reject(
        self,
        qualification: PI05AutonomousRolloutQualification,
        *,
        checkpoint: str | Path,
        training_contract_sha256: str | None,
        chunk_execution_protocol: str,
        source_summary: str | Path,
    ) -> dict[str, Any]:
        if qualification.recorded_frames != self.frame_count:
            raise ValueError("qualification frame count does not match buffered replay")
        if qualification.material_residual_frames != self.material_residual_frames:
            raise ValueError("qualification material residual count does not match buffer")
        reasons = qualification.rejection_reasons()
        if qualification.accepted:
            self._dataset.save_episode()
            self._dataset.finalize()
        else:
            self._dataset.clear_episode_buffer()
        checkpoint_path = Path(checkpoint).resolve()
        source_summary_path = Path(source_summary).resolve()
        artifact = _checkpoint_artifact(checkpoint_path)
        manifest = {
            "schema_version": 1,
            "protocol": PI05_AUTONOMOUS_REPLAY_PROTOCOL,
            "accepted_for_behavior_cloning": qualification.accepted,
            "accepted_as_pure_vla_experience": (
                qualification.accepted_as_pure_vla_experience
            ),
            "replay_authority_scope": qualification.policy_authority,
            "rejection_reasons": list(reasons),
            "qualification": asdict(qualification),
            "checkpoint": str(checkpoint_path),
            "checkpoint_artifact": str(artifact) if artifact is not None else None,
            "checkpoint_artifact_sha256": _sha256(artifact) if artifact is not None else None,
            "training_contract_sha256": training_contract_sha256,
            "source_summary": str(source_summary_path),
            "source_summary_sha256": (
                _sha256(source_summary_path) if source_summary_path.is_file() else None
            ),
            "action_semantics": "raw_pi05_residual_before_harness",
            "state_semantics": "observable_pi05_state_80d",
            "privileged_state_in_policy": False,
            "failed_attempts_are_bc_labels": False,
            "chunk_execution_protocol": chunk_execution_protocol,
            "held_actions_are_explicitly_tagged": True,
        }
        self.root.mkdir(parents=True, exist_ok=True)
        manifest_path = self.root / "PI05_AUTONOMOUS_REPLAY_MANIFEST.json"
        manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        return manifest


class MobilePI05AbsoluteLeRobotWriter:
    """Buffer 23-D absolute targets and admit only verified pure-VLA success."""

    def __init__(
        self,
        root: str | Path,
        *,
        fps: int = 30,
        image_size: tuple[int, int] = (224, 224),
        repo_id: str = "local/mobile-pi05-absolute-verified-replay",
        dataset_factory: Callable[..., Any] | None = None,
        include_wrist_rgbd: bool = False,
    ) -> None:
        if dataset_factory is None:
            try:
                from lerobot.datasets.lerobot_dataset import LeRobotDataset
            except ImportError as exc:
                raise RuntimeError("LeRobot is required to record PI0.5 replay") from exc
            dataset_factory = LeRobotDataset.create
        self.root = Path(root)
        width, height = image_size
        audit_info = {"policy_input": False}
        features: dict[str, dict[str, Any]] = {
            "observation.state": {
                "dtype": "float32",
                "shape": (len(MOBILE_PI05_ABSOLUTE_STATE_NAMES),),
                "names": list(MOBILE_PI05_ABSOLUTE_STATE_NAMES),
            },
            "action": {
                "dtype": "float32",
                "shape": (len(MOBILE_PI05_ABSOLUTE_ACTION_NAMES),),
                "names": list(MOBILE_PI05_ABSOLUTE_ACTION_NAMES),
                "info": {
                    "semantics": "verified_executed_absolute_vla_action_plus_mode_progress"
                },
            },
            "observation.privileged_state": {
                "dtype": "float32",
                "shape": (len(MOBILE_PRIVILEGED_STATE_NAMES),),
                "names": list(MOBILE_PRIVILEGED_STATE_NAMES),
                "info": audit_info,
            },
            "observation.stage_id": {
                "dtype": "int64",
                "shape": (1,),
                "names": ["stage_id"],
                "info": {"stages": list(MOBILE_STAGE_NAMES), **audit_info},
            },
            "observation.policy_inference_performed": {
                "dtype": "int64",
                "shape": (1,),
                "names": ["policy_inference_performed"],
                "info": audit_info,
            },
            "observation.policy_inference_call_index": {
                "dtype": "int64",
                "shape": (1,),
                "names": ["policy_inference_call_index"],
                "info": audit_info,
            },
            "observation.policy_chunk_step_index": {
                "dtype": "int64",
                "shape": (1,),
                "names": ["policy_chunk_step_index"],
                "info": audit_info,
            },
            MOBILE_RGB_KEY: {
                "dtype": "image",
                "shape": (height, width, 3),
                "names": ["height", "width", "channels"],
            },
            MOBILE_DEPTH_KEY: {
                "dtype": "image",
                "shape": (height, width, 1),
                "names": ["height", "width", "channels"],
                "info": {"is_depth_map": True, "depth_unit": "m"},
            },
            MOBILE_DEPTH_RGB_KEY: {
                "dtype": "image",
                "shape": (height, width, 3),
                "names": ["height", "width", "channels"],
                "info": {"derived_from": MOBILE_DEPTH_KEY},
            },
        }
        if include_wrist_rgbd:
            features.update(
                {
                    MOBILE_WRIST_RGB_KEY: {
                        "dtype": "image",
                        "shape": (height, width, 3),
                        "names": ["height", "width", "channels"],
                    },
                    MOBILE_WRIST_DEPTH_KEY: {
                        "dtype": "image",
                        "shape": (height, width, 1),
                        "names": ["height", "width", "channels"],
                        "info": {"is_depth_map": True, "depth_unit": "m"},
                    },
                    MOBILE_WRIST_DEPTH_RGB_KEY: {
                        "dtype": "image",
                        "shape": (height, width, 3),
                        "names": ["height", "width", "channels"],
                        "info": {"derived_from": MOBILE_WRIST_DEPTH_KEY},
                    },
                }
            )
        self._include_wrist_rgbd = include_wrist_rgbd
        self._dataset = dataset_factory(
            repo_id=repo_id,
            root=self.root,
            fps=fps,
            features=features,
            robot_type="mobile_bi_franka_sim",
            use_videos=False,
            image_writer_threads=4,
        )
        self.frame_count = 0
        self.material_action_frames = 0
        self.nonzero_base_command_frames = 0

    def add_frame(self, frame: PI05AutonomousAbsoluteFrame) -> None:
        import numpy as np

        if frame.rgb is None or frame.depth is None:
            raise ValueError("PI0.5 absolute replay requires overhead RGB-D")
        depth = np.asarray(frame.depth, dtype=np.float32)
        payload: dict[str, Any] = {
            "observation.state": np.asarray(frame.state, dtype=np.float32),
            "action": np.asarray(frame.absolute_action_target, dtype=np.float32),
            "observation.privileged_state": np.asarray(
                frame.privileged_state, dtype=np.float32
            ),
            "observation.stage_id": np.asarray(
                [MOBILE_STAGE_NAMES.index(frame.stage)], dtype=np.int64
            ),
            "observation.policy_inference_performed": np.asarray(
                [int(frame.inference_performed)], dtype=np.int64
            ),
            "observation.policy_inference_call_index": np.asarray(
                [frame.inference_call_index], dtype=np.int64
            ),
            "observation.policy_chunk_step_index": np.asarray(
                [frame.chunk_step_index], dtype=np.int64
            ),
            MOBILE_RGB_KEY: np.asarray(frame.rgb, dtype=np.uint8)[..., :3],
            MOBILE_DEPTH_KEY: depth[..., None] if depth.ndim == 2 else depth,
            MOBILE_DEPTH_RGB_KEY: metric_depth_to_visual_rgb(depth, np),
            "task": frame.task,
        }
        if self._include_wrist_rgbd:
            if frame.wrist_rgb is None or frame.wrist_depth is None:
                raise ValueError("PI0.5 wrist replay requires wrist RGB-D")
            wrist_depth = np.asarray(frame.wrist_depth, dtype=np.float32)
            payload[MOBILE_WRIST_RGB_KEY] = np.asarray(
                frame.wrist_rgb, dtype=np.uint8
            )[..., :3]
            payload[MOBILE_WRIST_DEPTH_KEY] = (
                wrist_depth[..., None] if wrist_depth.ndim == 2 else wrist_depth
            )
            payload[MOBILE_WRIST_DEPTH_RGB_KEY] = metric_depth_to_visual_rgb(
                wrist_depth, np
            )
        self._dataset.add_frame(payload)
        self.frame_count += 1
        base_norm = math.sqrt(
            sum(value * value for value in frame.absolute_action_target[:3])
        )
        arm_motion = max(
            math.dist(frame.absolute_action_target[3:6], frame.state[74:77]),
            math.dist(frame.absolute_action_target[11:14], frame.state[77:80]),
        )
        self.material_action_frames += int(max(base_norm, arm_motion) > 1e-5)
        self.nonzero_base_command_frames += int(base_norm > 1e-7)

    def commit_or_reject(
        self,
        qualification: PI05AbsoluteRolloutQualification,
        *,
        checkpoint: str | Path,
        training_contract_sha256: str | None,
        chunk_execution_protocol: str,
        source_summary: str | Path,
    ) -> dict[str, Any]:
        expected = (
            qualification.recorded_frames,
            qualification.material_action_frames,
            qualification.nonzero_base_command_frames,
        )
        observed = (
            self.frame_count,
            self.material_action_frames,
            self.nonzero_base_command_frames,
        )
        if expected != observed:
            raise ValueError("absolute qualification counters do not match replay buffer")
        reasons = qualification.rejection_reasons()
        if qualification.accepted:
            self._dataset.save_episode()
            self._dataset.finalize()
        else:
            self._dataset.clear_episode_buffer()
        checkpoint_path = Path(checkpoint).resolve()
        source_summary_path = Path(source_summary).resolve()
        artifact = _checkpoint_artifact(checkpoint_path)
        manifest = {
            "schema_version": 1,
            "protocol": PI05_ABSOLUTE_REPLAY_PROTOCOL,
            "accepted_for_behavior_cloning": qualification.accepted,
            "accepted_as_pure_vla_experience": (
                qualification.accepted_as_pure_vla_experience
            ),
            "replay_authority_scope": qualification.policy_authority,
            "rejection_reasons": list(reasons),
            "qualification": asdict(qualification),
            "checkpoint": str(checkpoint_path),
            "checkpoint_artifact": str(artifact) if artifact is not None else None,
            "checkpoint_artifact_sha256": (
                _sha256(artifact) if artifact is not None else None
            ),
            "training_contract_sha256": training_contract_sha256,
            "source_summary": str(source_summary_path),
            "source_summary_sha256": (
                _sha256(source_summary_path) if source_summary_path.is_file() else None
            ),
            "action_semantics": (
                "verified_executed_absolute_vla_action_plus_mode_progress"
            ),
            "state_semantics": "observable_pi05_absolute_state_80d",
            "privileged_state_in_policy": False,
            "failed_attempts_are_bc_labels": False,
            "chunk_execution_protocol": chunk_execution_protocol,
            "held_actions_are_explicitly_tagged": True,
        }
        self.root.mkdir(parents=True, exist_ok=True)
        (self.root / "PI05_ABSOLUTE_REPLAY_MANIFEST.json").write_text(
            json.dumps(manifest, indent=2), encoding="utf-8"
        )
        if qualification.accepted:
            modality = "rgbd_wrist" if self._include_wrist_rgbd else "rgbd"
            training_manifest = {
                "schema_version": 1,
                "protocol": "pash-pi05-absolute-self-replay-v1",
                "source_dataset": str(self.root.resolve()),
                "output_dataset": str(self.root.resolve()),
                "episodes": 1,
                "frames": self.frame_count,
                "state_dimension": len(MOBILE_PI05_ABSOLUTE_STATE_NAMES),
                "state_names": list(MOBILE_PI05_ABSOLUTE_STATE_NAMES),
                "action_contract": "absolute_v1",
                "action_dimension": len(MOBILE_PI05_ABSOLUTE_ACTION_NAMES),
                "action_names": list(MOBILE_PI05_ABSOLUTE_ACTION_NAMES),
                "policy_visual_modality": modality,
                "policy_visual_keys": list(mobile_policy_visual_keys(modality)),
                "mode_conditioning_policy": "hidden_all_stages",
                "task_language_policy": "mode_neutral_shared_instruction_v1",
                "lift_residual_supervision": "smooth_stage_progress_v2",
                "episode_manifests": [
                    {
                        "episode_index": 0,
                        "frames": self.frame_count,
                        "grasp_modes": [qualification.grasp_mode],
                        "source_episode_id": source_summary_path.stem,
                        "source_kind": "verified_pure_vla_self_replay",
                        "seed_role": "verified_successful_absolute_action_supervision",
                        "nonzero_contact_residual_frames": 0,
                        "nonzero_base_command_frames": self.nonzero_base_command_frames,
                    }
                ],
                "mode_episode_counts": {
                    mode: int(mode == qualification.grasp_mode)
                    for mode in (
                        "top_suction",
                        "side_suction",
                        "cooperative_cradle",
                    )
                },
                "verified_recovery_summary": str(source_summary_path),
                "nonzero_contact_residual_frames": 0,
                "nonzero_base_command_frames": self.nonzero_base_command_frames,
                "expert_reference_used": False,
                "target_leakage_audit": {
                    "action_derived_state_fields": 0,
                    "tool_position_state_source": (
                        "observation.state current end-effector pose"
                    ),
                    "mode_input_hidden": True,
                },
                "normalization_stats_policy": "lerobot_writer_generated_quantiles_v1",
                "claim_boundary": (
                    "pure absolute-VLA successful self-replay only; failed rollouts "
                    "are excluded and deterministic release remains disclosed"
                ),
            }
            (self.root / "PI05_ABSOLUTE_DATASET_MANIFEST.json").write_text(
                json.dumps(training_manifest, indent=2), encoding="utf-8"
            )
        return manifest


def _checkpoint_artifact(checkpoint: Path) -> Path | None:
    if checkpoint.is_file():
        return checkpoint
    for name in ("adapter_model.safetensors", "model.safetensors"):
        candidate = checkpoint / name
        if candidate.is_file():
            return candidate
    candidates = sorted(checkpoint.glob("*.safetensors"))
    return candidates[0] if candidates else None


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()
