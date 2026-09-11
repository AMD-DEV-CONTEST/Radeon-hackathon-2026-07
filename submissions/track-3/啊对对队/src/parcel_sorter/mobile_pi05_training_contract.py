"""Auditable data and action-semantics contract for PI0.5 checkpoints."""

from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
from typing import Any

from .mobile_dataset import infer_mobile_policy_modality, mobile_policy_visual_keys
from .mobile_stratified_sampler import SAMPLING_PROTOCOL, load_sampling_manifest
from .mobile_train_stats import (
    TRAIN_STATS_PROTOCOL,
    load_train_only_normalization_stats,
)
from .mobile_pi05_contract import (
    MOBILE_PI05_ABSOLUTE_ACTION_NAMES,
    MOBILE_PI05_ABSOLUTE_STATE_NAMES,
    MOBILE_PI05_INCREMENTAL_ACTION_NAMES,
    MOBILE_PI05_RESIDUAL_ACTION_NAMES,
    MOBILE_PI05_STATE_NAMES,
)
from .pi05_weighted_loss import (
    PI05_MODE_FLOW_LOSS_WEIGHTING_SCOPE,
    PI05_STAGE_LOSS_WEIGHTING_SCOPE,
)
from .mobile_pi05_research_protocol import validate_training_launch_audit


PI05_TRAINING_CONTRACT_FILENAME = "PI05_TRAINING_CONTRACT.json"
PI05_RESIDUAL_ACTION_SEMANTICS = "bounded_expert_relative_cartesian_residual_v1"
PI05_ABSOLUTE_ACTION_SEMANTICS = "expert_independent_absolute_mobile_action_v1"
PI05_INCREMENTAL_ACTION_SEMANTICS = "expert_independent_incremental_se3_mobile_action_v1"
PI05_ACTION_SEMANTICS = PI05_RESIDUAL_ACTION_SEMANTICS
PI05_STATE_SEMANTICS = "observable_robot_contact_geometry_history_v1"
PI05_NORMALIZATION_SEMANTICS = "lerobot_quantile_q01_q99_v1"


def build_pi05_training_contract(
    dataset_root: str | Path,
    *,
    base_model: str,
    base_revision: str,
    chunk_size: int,
    n_action_steps: int,
    state_token_protocol: str | None = None,
    mode_head_protocol: str | None = None,
    mode_head_class_weights: list[float] | None = None,
    stage_loss_weights: list[float] | None = None,
    mode_flow_loss_weights: list[float] | None = None,
    mode_flow_loss_population_normalizer: float | None = None,
    action_projection_protocol: str | None = None,
    training_role: str | None = None,
    requested_training_steps: int | None = None,
    training_batch_size: int | None = None,
    scheduler_type: str | None = None,
    scheduler_warmup_steps: int | None = None,
    scheduler_decay_steps: int | None = None,
    training_launch_audit: dict[str, Any] | None = None,
    sampling_manifest_path: str | Path | None = None,
    normalization_stats_path: str | Path | None = None,
    train_stats_manifest_path: str | Path | None = None,
) -> dict[str, Any]:
    """Build a canonical contract tying a checkpoint to data semantics."""

    root = Path(dataset_root).resolve()
    info_path = root / "meta" / "info.json"
    global_stats_path = root / "meta" / "stats.json"
    stats_path = (
        Path(normalization_stats_path).resolve()
        if normalization_stats_path is not None
        else global_stats_path
    )
    manifest_paths = [
        path
        for path in (
            root / "PI05_RESIDUAL_DATASET_MANIFEST.json",
            root / "PI05_ABSOLUTE_DATASET_MANIFEST.json",
            root / "PI05_INCREMENTAL_DATASET_MANIFEST.json",
        )
        if path.is_file()
    ]
    if not info_path.is_file() or not stats_path.is_file() or len(manifest_paths) != 1:
        raise ValueError("PI0.5 dataset is missing info, stats, or provenance manifest")
    if not global_stats_path.is_file():
        raise ValueError("PI0.5 dataset is missing its global stats provenance")
    if bool(normalization_stats_path) != bool(train_stats_manifest_path):
        raise ValueError("custom normalization stats require their provenance manifest")
    manifest_path = manifest_paths[0]
    if chunk_size <= 0 or not 1 <= n_action_steps <= chunk_size:
        raise ValueError("invalid PI0.5 action chunk contract")
    info = json.loads(info_path.read_text(encoding="utf-8"))
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    features = info.get("features", {})
    state = features.get("observation.state", {})
    action = features.get("action", {})
    state_names = tuple(state.get("names") or ())
    action_names = tuple(action.get("names") or ())
    contracts = {
        "residual_v1": (
            MOBILE_PI05_STATE_NAMES,
            MOBILE_PI05_RESIDUAL_ACTION_NAMES,
            PI05_RESIDUAL_ACTION_SEMANTICS,
        ),
        "absolute_v1": (
            MOBILE_PI05_ABSOLUTE_STATE_NAMES,
            MOBILE_PI05_ABSOLUTE_ACTION_NAMES,
            PI05_ABSOLUTE_ACTION_SEMANTICS,
        ),
        "incremental_se3_v1": (
            MOBILE_PI05_ABSOLUTE_STATE_NAMES,
            MOBILE_PI05_INCREMENTAL_ACTION_NAMES,
            PI05_INCREMENTAL_ACTION_SEMANTICS,
        ),
    }
    matches = [
        (name, expected_state, expected_action, semantics)
        for name, (expected_state, expected_action, semantics) in contracts.items()
        if state_names == tuple(expected_state) and action_names == tuple(expected_action)
    ]
    if len(matches) != 1:
        raise ValueError("PI0.5 state/action feature names do not match a supported contract")
    action_contract, expected_state_names, expected_action_names, action_semantics = matches[0]
    if state.get("shape") != [len(expected_state_names)]:
        raise ValueError("PI0.5 state feature shape does not match its named contract")
    if action.get("shape") != [len(expected_action_names)]:
        raise ValueError("PI0.5 action feature shape does not match its named contract")
    policy_visual_modality = infer_mobile_policy_modality(features)
    policy_visual_keys = list(mobile_policy_visual_keys(policy_visual_modality))
    fps = int(info.get("fps", 0))
    if fps <= 0:
        raise ValueError("PI0.5 dataset FPS must be positive")
    dataset_storage_format = "video" if info.get("video_path") else "image_parquet"
    if dataset_storage_format == "video" and any(
        features[key].get("dtype") != "video" for key in policy_visual_keys
    ):
        raise ValueError("PI0.5 policy visual inputs are not video-backed")
    strict_training_fields = (
        training_role,
        requested_training_steps,
        training_batch_size,
        scheduler_type,
        scheduler_warmup_steps,
        scheduler_decay_steps,
        training_launch_audit,
    )
    if any(value is not None for value in strict_training_fields):
        if any(value is None for value in strict_training_fields):
            raise ValueError("strict PI0.5 scheduler/launch contract is incomplete")
        if int(requested_training_steps) < 1 or int(training_batch_size) < 1:
            raise ValueError("training steps and batch size must be positive")
        if str(scheduler_type) != "cosine_decay":
            raise ValueError("formal PI0.5 training requires cosine_decay")
        validate_training_launch_audit(
            training_launch_audit or {},
            expected_training_role=str(training_role),
            dataset_manifest_sha256=_sha256(manifest_path),
        )
        if int(scheduler_decay_steps) != int(requested_training_steps):
            raise ValueError("scheduler decay must equal requested training steps")
    total_frames = int(info.get("total_frames", 0))
    if training_role is not None and total_frames <= 0:
        raise ValueError("strict PI0.5 contract requires a positive dataset frame count")
    split_path = root / "PARCEL_SUCCESS_SPLIT.json"
    sampling_path = (
        Path(sampling_manifest_path).resolve()
        if sampling_manifest_path is not None
        else None
    )
    train_stats_manifest = (
        Path(train_stats_manifest_path).resolve()
        if train_stats_manifest_path is not None
        else None
    )
    sampling = None
    sampling_source: dict[str, Any] = {}
    if split_path.is_file() and sampling_path is None:
        raise ValueError("parcel success training requires a sampling manifest")
    if split_path.is_file() and train_stats_manifest is None:
        raise ValueError("parcel success training requires train-only normalization")
    if sampling_path is not None:
        if not split_path.is_file():
            raise ValueError("sampling manifest requires the frozen parcel split")
        sampling = load_sampling_manifest(sampling_path)
        sampling_source = sampling.get("source") or {}
        if sampling_source.get("dataset_info_sha256") != _sha256(info_path):
            raise ValueError("sampling manifest dataset metadata mismatch")
        if sampling_source.get("split_manifest_sha256") != _sha256(split_path):
            raise ValueError("sampling manifest split mismatch")
    train_stats_payload = None
    if train_stats_manifest is not None:
        if sampling_path is None:
            raise ValueError("train-only normalization requires a sampling manifest")
        load_train_only_normalization_stats(
            stats_path=stats_path,
            manifest_path=train_stats_manifest,
            sampling_manifest_path=sampling_path,
        )
        train_stats_payload = json.loads(
            train_stats_manifest.read_text(encoding="utf-8")
        )
        if train_stats_payload.get("dataset_info_sha256") != _sha256(info_path):
            raise ValueError("train-only normalization dataset metadata mismatch")
        if train_stats_payload.get("split_manifest_sha256") != _sha256(split_path):
            raise ValueError("train-only normalization split mismatch")

    effective_epoch_frames = (
        int(sampling["samples_per_epoch"]) if sampling is not None else total_frames
    )
    payload: dict[str, Any] = {
        "schema_version": 1,
        "protocol": "parcel-pi05-training-contract-v1",
        "base_model": str(base_model),
        "base_revision": str(base_revision),
        "dataset_root": str(root),
        "dataset_fps_hz": fps,
        "dataset_storage_format": dataset_storage_format,
        "dataset_video_backend": (
            "pyav" if dataset_storage_format == "video" else None
        ),
        "dataset_depth_output_unit": "m",
        "state_dimension": len(expected_state_names),
        "state_names": list(expected_state_names),
        "state_semantics": PI05_STATE_SEMANTICS,
        "action_contract": action_contract,
        "action_dimension": len(expected_action_names),
        "action_names": list(expected_action_names),
        "action_semantics": action_semantics,
        "policy_visual_modality": policy_visual_modality,
        "policy_visual_keys": policy_visual_keys,
        "action_chunk_size": int(chunk_size),
        "executed_action_steps": int(n_action_steps),
        "normalization_semantics": PI05_NORMALIZATION_SEMANTICS,
        "normalization_stats_sha256": _sha256(stats_path),
        "normalization_stats_source": (
            "balanced_train_only" if train_stats_payload is not None else "dataset_global"
        ),
        "dataset_global_stats_sha256": _sha256(global_stats_path),
        "train_stats_protocol": (
            train_stats_payload.get("protocol")
            if train_stats_payload is not None
            else None
        ),
        "train_stats_manifest_sha256": (
            train_stats_payload.get("manifest_sha256")
            if train_stats_payload is not None
            else None
        ),
        "train_stats_manifest_file_sha256": (
            _sha256(train_stats_manifest) if train_stats_manifest is not None else None
        ),
        "normalization_held_out_frame_count": (
            int(train_stats_payload["held_out_frame_count"])
            if train_stats_payload is not None
            else None
        ),
        "sampling_protocol": sampling.get("protocol") if sampling is not None else None,
        "sampling_manifest_sha256": (
            sampling.get("manifest_sha256") if sampling is not None else None
        ),
        "sampling_manifest_file_sha256": (
            _sha256(sampling_path) if sampling_path is not None else None
        ),
        "sampling_samples_per_epoch": (
            int(sampling["samples_per_epoch"]) if sampling is not None else None
        ),
        "sampling_samples_per_design_cell_per_epoch": (
            int(sampling["samples_per_design_cell_per_epoch"])
            if sampling is not None
            else None
        ),
        "sampling_probabilities": (
            sampling.get("sampling_probabilities") if sampling is not None else None
        ),
        "dataset_manifest_sha256": _sha256(manifest_path),
        "normalization_stats_policy": manifest.get("normalization_stats_policy"),
        "mode_conditioning_policy": manifest.get("mode_conditioning_policy"),
        "task_language_policy": manifest.get("task_language_policy"),
        "state_token_protocol": state_token_protocol,
        "mode_head_protocol": mode_head_protocol,
        "mode_head_class_weights": mode_head_class_weights,
        "stage_loss_weights": stage_loss_weights,
        "stage_loss_weighting_scope": (
            PI05_STAGE_LOSS_WEIGHTING_SCOPE
            if stage_loss_weights is not None
            else None
        ),
        "mode_flow_loss_weights": mode_flow_loss_weights,
        "mode_flow_loss_population_normalizer": (
            mode_flow_loss_population_normalizer
            if mode_flow_loss_weights is not None
            else None
        ),
        "mode_flow_loss_weighting_scope": (
            PI05_MODE_FLOW_LOSS_WEIGHTING_SCOPE
            if mode_flow_loss_weights is not None
            else None
        ),
        "action_projection_protocol": action_projection_protocol,
        "training_role": training_role,
        "requested_training_steps": requested_training_steps,
        "training_batch_size": training_batch_size,
        "dataset_total_frames": total_frames if training_role is not None else None,
        "planned_dataset_epochs": (
            float(requested_training_steps) * float(training_batch_size) / total_frames
            if training_role is not None
            else None
        ),
        "planned_sampling_epochs": (
            float(requested_training_steps)
            * float(training_batch_size)
            / effective_epoch_frames
            if training_role is not None
            else None
        ),
        "scheduler_type": scheduler_type,
        "scheduler_warmup_steps": scheduler_warmup_steps,
        "scheduler_decay_steps": scheduler_decay_steps,
        "scheduler_step_budget": requested_training_steps,
        "training_launch_audit_sha256": (
            training_launch_audit.get("audit_sha256")
            if training_launch_audit is not None
            else None
        ),
        "stage_panel_sha256": (
            training_launch_audit.get("stage_panel_sha256")
            if training_launch_audit is not None
            else None
        ),
        "action_thresholds_sha256": (
            training_launch_audit.get("action_thresholds_sha256")
            if training_launch_audit is not None
            else None
        ),
        "tiny_overfit_gate_sha256": (
            training_launch_audit.get("tiny_overfit_gate_sha256")
            if training_launch_audit is not None
            else None
        ),
        "absolute_delta_policy": (
            {
                "base": "velocity_residual",
                "left_contact": "expert_anchor_relative_cartesian_delta_m",
                "right_contact": "expert_anchor_relative_cartesian_delta_m",
                "orientation": "deterministic_surface_normal_lock",
                "mode": "categorical_logits",
                "release": "deterministic_interlock",
            }
            if action_contract == "residual_v1"
            else {
                "base": "absolute_velocity_command",
                "left_arm": "absolute_cartesian_pose_and_tool_command",
                "right_arm": "absolute_cartesian_pose_and_tool_command",
                "mode": "categorical_logits",
                "release": "deterministic_interlock",
                "expert_reference": "forbidden",
            }
            if action_contract == "absolute_v1"
            else {
                "base": "absolute_velocity_command",
                "left_arm": "incremental_world_frame_se3_and_tool_command",
                "right_arm": "incremental_world_frame_se3_and_tool_command",
                "rotation": "shortest_rotation_vector_target_times_current_inverse",
                "mode": "categorical_logits",
                "release": "deterministic_interlock",
                "expert_reference": "forbidden",
            }
        ),
    }
    payload["contract_sha256"] = _payload_sha256(payload)
    return payload


def with_pi05_architecture_protocols(
    payload: dict[str, Any],
    *,
    state_token_protocol: str | None,
    mode_head_protocol: str | None,
    action_projection_protocol: str | None = None,
) -> dict[str, Any]:
    """Re-fingerprint a contract after explicitly fixing adapter protocols."""

    result = dict(payload)
    result.pop("contract_sha256", None)
    result["state_token_protocol"] = state_token_protocol
    result["mode_head_protocol"] = mode_head_protocol
    result["action_projection_protocol"] = action_projection_protocol
    result["contract_sha256"] = _payload_sha256(result)
    return result


def validate_pi05_training_contract(
    payload: dict[str, Any],
    *,
    state_dim: int,
    action_dim: int,
    chunk_size: int,
    required_state_token_protocol: str | None = None,
    required_mode_head_protocol: str | None = None,
    required_action_projection_protocol: str | None = None,
    required_stage_loss_weights: list[float] | tuple[float, ...] | None = None,
    required_mode_flow_loss_weights: list[float] | tuple[float, ...] | None = None,
    required_mode_flow_loss_population_normalizer: float | None = None,
    required_visual_keys: list[str] | tuple[str, ...] | set[str] | None = None,
) -> str:
    """Reject a checkpoint whose stored training semantics are inconsistent."""

    claimed = str(payload.get("contract_sha256") or "")
    unsigned = {key: value for key, value in payload.items() if key != "contract_sha256"}
    if claimed != _payload_sha256(unsigned):
        raise ValueError("PI0.5 training contract fingerprint mismatch")
    action_semantics = payload.get("action_semantics")
    supported = {
        PI05_RESIDUAL_ACTION_SEMANTICS: (
            MOBILE_PI05_STATE_NAMES,
            MOBILE_PI05_RESIDUAL_ACTION_NAMES,
            "residual_v1",
        ),
        PI05_ABSOLUTE_ACTION_SEMANTICS: (
            MOBILE_PI05_ABSOLUTE_STATE_NAMES,
            MOBILE_PI05_ABSOLUTE_ACTION_NAMES,
            "absolute_v1",
        ),
        PI05_INCREMENTAL_ACTION_SEMANTICS: (
            MOBILE_PI05_ABSOLUTE_STATE_NAMES,
            MOBILE_PI05_INCREMENTAL_ACTION_NAMES,
            "incremental_se3_v1",
        ),
    }
    if action_semantics not in supported:
        raise ValueError("PI0.5 training contract mismatch: action_semantics")
    expected_state_names, expected_action_names, expected_action_contract = supported[
        action_semantics
    ]
    expected = {
        "state_dimension": state_dim,
        "action_dimension": action_dim,
        "action_chunk_size": chunk_size,
        "state_semantics": PI05_STATE_SEMANTICS,
        "action_semantics": action_semantics,
        "normalization_semantics": PI05_NORMALIZATION_SEMANTICS,
    }
    for field, value in expected.items():
        if payload.get(field) != value:
            raise ValueError(f"PI0.5 training contract mismatch: {field}")
    if payload.get("action_contract", "residual_v1") != expected_action_contract:
        raise ValueError("PI0.5 training contract action contract mismatch")
    if payload.get("state_names") != list(expected_state_names):
        raise ValueError("PI0.5 training contract state names mismatch")
    if payload.get("action_names") != list(expected_action_names):
        raise ValueError("PI0.5 training contract action names mismatch")
    if int(payload.get("state_dimension", 0)) != len(expected_state_names):
        raise ValueError("PI0.5 training contract state dimension mismatch")
    if int(payload.get("action_dimension", 0)) != len(expected_action_names):
        raise ValueError("PI0.5 training contract action dimension mismatch")
    executed_steps = int(payload.get("executed_action_steps", 0))
    if not 1 <= executed_steps <= int(payload.get("action_chunk_size", 0)):
        raise ValueError("PI0.5 training contract action chunk execution mismatch")
    if int(payload.get("dataset_fps_hz", 0)) <= 0:
        raise ValueError("PI0.5 training contract has invalid control frequency")
    if payload.get("training_role") is not None:
        role = payload.get("training_role")
        if role not in {"smoke", "tiny_overfit", "candidate"}:
            raise ValueError("PI0.5 training contract mismatch: training_role")
        steps = int(payload.get("requested_training_steps", 0))
        batch_size = int(payload.get("training_batch_size", 0))
        total_frames = int(payload.get("dataset_total_frames", 0))
        if steps < 1 or batch_size < 1 or total_frames < 1:
            raise ValueError("PI0.5 training contract has an invalid step/epoch budget")
        if payload.get("scheduler_type") != "cosine_decay":
            raise ValueError("PI0.5 training contract mismatch: scheduler_type")
        warmup = int(payload.get("scheduler_warmup_steps", -1))
        decay = int(payload.get("scheduler_decay_steps", -1))
        if not 0 <= warmup <= steps or decay != steps:
            raise ValueError("PI0.5 training contract mismatch: scheduler budget")
        expected_epochs = steps * batch_size / total_frames
        if not math.isclose(
            float(payload.get("planned_dataset_epochs", math.nan)),
            expected_epochs,
            rel_tol=0.0,
            abs_tol=1e-12,
        ):
            raise ValueError("PI0.5 training contract mismatch: planned_dataset_epochs")
        sampling_epoch_frames = payload.get("sampling_samples_per_epoch")
        effective_epoch_frames = (
            int(sampling_epoch_frames)
            if sampling_epoch_frames is not None
            else total_frames
        )
        expected_sampling_epochs = steps * batch_size / effective_epoch_frames
        planned_sampling_epochs = payload.get("planned_sampling_epochs")
        if planned_sampling_epochs is not None and not math.isclose(
            float(planned_sampling_epochs),
            expected_sampling_epochs,
            rel_tol=0.0,
            abs_tol=1e-12,
        ):
            raise ValueError("PI0.5 training contract mismatch: planned_sampling_epochs")
        launch_hash = str(payload.get("training_launch_audit_sha256") or "")
        if len(launch_hash) != 64:
            raise ValueError("PI0.5 training contract lacks a launch-audit fingerprint")
        if role == "tiny_overfit" and not payload.get("stage_panel_sha256"):
            raise ValueError("tiny-overfit contract lacks a stage panel")
        if role == "candidate" and not payload.get("tiny_overfit_gate_sha256"):
            raise ValueError("candidate contract lacks a tiny-overfit gate")
    sampling_protocol = payload.get("sampling_protocol")
    sampling_fields = (
        payload.get("sampling_manifest_sha256"),
        payload.get("sampling_manifest_file_sha256"),
        payload.get("sampling_samples_per_epoch"),
        payload.get("sampling_samples_per_design_cell_per_epoch"),
        payload.get("sampling_probabilities"),
    )
    if sampling_protocol is None and any(value is not None for value in sampling_fields):
        raise ValueError("PI0.5 training contract has partial sampling provenance")
    if sampling_protocol is not None:
        if sampling_protocol != SAMPLING_PROTOCOL:
            raise ValueError("PI0.5 training contract sampling protocol mismatch")
        if any(
            not isinstance(value, str) or len(value) != 64
            for value in sampling_fields[:2]
        ):
            raise ValueError("PI0.5 training contract sampling hash mismatch")
        if int(sampling_fields[2] or 0) < 24 or int(sampling_fields[3] or 0) < 1:
            raise ValueError("PI0.5 training contract sampling size mismatch")
        probabilities = sampling_fields[4] or {}
        mode_probabilities = probabilities.get("grasp_mode") or {}
        if sorted(float(value) for value in mode_probabilities.values()) != [
            1 / 3,
            1 / 3,
            1 / 3,
        ] or float(probabilities.get("design_cell_within_mode", 0.0)) != 1 / 8:
            raise ValueError("PI0.5 training contract sampling probabilities mismatch")
    train_stats_protocol = payload.get("train_stats_protocol")
    train_stats_fields = (
        payload.get("train_stats_manifest_sha256"),
        payload.get("train_stats_manifest_file_sha256"),
        payload.get("normalization_held_out_frame_count"),
    )
    if train_stats_protocol is None and any(
        value is not None for value in train_stats_fields
    ):
        raise ValueError("PI0.5 training contract has partial train-stats provenance")
    if train_stats_protocol is not None:
        if train_stats_protocol != TRAIN_STATS_PROTOCOL:
            raise ValueError("PI0.5 training contract train-stats protocol mismatch")
        if payload.get("normalization_stats_source") != "balanced_train_only":
            raise ValueError("PI0.5 training contract normalization source mismatch")
        if any(
            not isinstance(value, str) or len(value) != 64
            for value in train_stats_fields[:2]
        ) or int(train_stats_fields[2]) != 0:
            raise ValueError("PI0.5 training contract train-stats provenance mismatch")
    if required_visual_keys is not None:
        # Contracts written before the wrist ablation pre-registration used the
        # fixed overhead RGB-D input but did not yet serialize those two keys.
        contracted_visual_keys = payload.get("policy_visual_keys")
        if contracted_visual_keys is None:
            contracted_visual_keys = list(mobile_policy_visual_keys("rgbd"))
        if set(contracted_visual_keys) != set(required_visual_keys):
            raise ValueError("PI0.5 training contract mismatch: policy_visual_keys")
    architecture = {
        "state_token_protocol": required_state_token_protocol,
        "mode_head_protocol": required_mode_head_protocol,
        "action_projection_protocol": required_action_projection_protocol,
    }
    for field, required in architecture.items():
        if required is not None and payload.get(field) != required:
            raise ValueError(f"PI0.5 training contract mismatch: {field}")
    stage_loss_weights = payload.get("stage_loss_weights")
    if stage_loss_weights is not None and (
        not isinstance(stage_loss_weights, list)
        or len(stage_loss_weights) != 6
        or any(
            not isinstance(value, (int, float))
            or not math.isfinite(float(value))
            or float(value) <= 0.0
            for value in stage_loss_weights
        )
    ):
        raise ValueError("PI0.5 training contract mismatch: stage_loss_weights")
    if stage_loss_weights is not None and payload.get(
        "stage_loss_weighting_scope"
    ) != PI05_STAGE_LOSS_WEIGHTING_SCOPE:
        raise ValueError(
            "PI0.5 training contract mismatch: stage_loss_weighting_scope"
        )
    if required_stage_loss_weights is not None:
        required_weights = [float(value) for value in required_stage_loss_weights]
        if stage_loss_weights != required_weights:
            raise ValueError("PI0.5 training contract mismatch: stage_loss_weights")
    mode_flow_loss_weights = payload.get("mode_flow_loss_weights")
    mode_flow_loss_population_normalizer = payload.get(
        "mode_flow_loss_population_normalizer"
    )
    if mode_flow_loss_weights is not None and (
        not isinstance(mode_flow_loss_weights, list)
        or len(mode_flow_loss_weights) != 3
        or any(
            not isinstance(value, (int, float))
            or not math.isfinite(float(value))
            or float(value) <= 0.0
            for value in mode_flow_loss_weights
        )
        or not isinstance(mode_flow_loss_population_normalizer, (int, float))
        or not math.isfinite(float(mode_flow_loss_population_normalizer))
        or float(mode_flow_loss_population_normalizer) <= 0.0
    ):
        raise ValueError("PI0.5 training contract mismatch: mode_flow_loss_weights")
    if mode_flow_loss_weights is not None and payload.get(
        "mode_flow_loss_weighting_scope"
    ) != PI05_MODE_FLOW_LOSS_WEIGHTING_SCOPE:
        raise ValueError(
            "PI0.5 training contract mismatch: mode_flow_loss_weighting_scope"
        )
    if mode_flow_loss_weights is None and any(
        value is not None
        for value in (
            mode_flow_loss_population_normalizer,
            payload.get("mode_flow_loss_weighting_scope"),
        )
    ):
        raise ValueError("PI0.5 training contract mismatch: mode_flow_loss_weights")
    if required_mode_flow_loss_weights is not None:
        required_mode_weights = [
            float(value) for value in required_mode_flow_loss_weights
        ]
        if mode_flow_loss_weights != required_mode_weights:
            raise ValueError(
                "PI0.5 training contract mismatch: mode_flow_loss_weights"
            )
    if required_mode_flow_loss_population_normalizer is not None and (
        mode_flow_loss_population_normalizer
        != float(required_mode_flow_loss_population_normalizer)
    ):
        raise ValueError(
            "PI0.5 training contract mismatch: mode_flow_loss_population_normalizer"
        )
    return claimed


def find_pi05_training_contract(checkpoint: str | Path) -> Path | None:
    """Find a run-level contract from a LeRobot pretrained-model directory."""

    current = Path(checkpoint).resolve()
    for parent in (current, *current.parents[:5]):
        candidate = parent / PI05_TRAINING_CONTRACT_FILENAME
        if candidate.is_file():
            return candidate
    return None


def _payload_sha256(payload: dict[str, Any]) -> str:
    canonical = json.dumps(
        payload, ensure_ascii=True, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()
