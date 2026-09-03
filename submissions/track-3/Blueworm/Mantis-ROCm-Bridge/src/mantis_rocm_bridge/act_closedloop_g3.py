"""Deterministic, fail-closed ACT learned-policy closed-loop G3 gate.

This module implements the dependency-isolated core of the G3 closed-loop phase
contract (``docs/AMD_ACT_CLOSEDLOOP_G3_GATE.md``).  It validates the frozen G3
JSON contract and its exact invariants, selects the exact seed set and the
seed-101 smoke admission, maps each 30 Hz policy tick to the first non-early
250 Hz physics step using the frozen ceiling rule, validates the observation
schema, projects every policy action through the admitted open-loop v3
finite-action / virtual-gripper / 16D-to-18D / physical-joint / limit adapter,
tracks strict consecutive-frame success without changing
:mod:`mantis_rocm_bridge.stack_bowls`, classifies failures, and builds the
per-episode and aggregate receipts.

The heavy runtime dependencies (``torch`` / ``numpy`` / ``lerobot`` /
``PIL`` / ``torchvision`` / ``Genesis``) live entirely behind the
:class:`ClosedLoopRuntime` protocol, so :func:`run_closed_loop_episode` is pure
Python and runs under the CPU-only unit tests against a tiny in-memory double.
Nothing in this module imports those packages at module import time.

A passing G3 receipt proves only exact-distribution learned-policy closed-loop
performance for the frozen checkpoint, simulator, task, evaluator, seeds, and
official AMD ROCm runtime.  It never proves optimization convergence, G4
confirmation, domain-randomization robustness, generalization, real-robot
safety, or an AMD performance advantage (see ``claim_boundary``).
"""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol, Sequence, runtime_checkable

from .contracts import ContractError
from .gripper import virtual_to_physical  # noqa: F401  (re-exported helper surface)
from .stack_bowls import (
    StackStabilityTracker,
    evaluate_strict_target_frame,
)

#: Re-exported so callers and tests share one observation/action contract with
#: the accepted open-loop inference gate without duplicating its dataclasses.
from .act_openloop_inference import (  # noqa: F401
    Observation,
    TensorSummary,
    enforce_joint_limits,
    expand_virtual_to_physical,
    physical_joint_limits,
    project_physical_joint_target,
    project_virtual_gripper_action,
    sha256_bytes,
    sha256_file,
    validate_action_vector,
    validate_observation,
)

#: The LeRobot version the frozen checkpoint and saved processors were produced
#: with, and the version this gate runs under on the official AMD worker.
EXPECTED_LEROBOT_VERSION = "0.4.4"

#: The frozen Genesis version pinned by the phase contract.
EXPECTED_GENESIS_VERSION = "1.2.3"

#: The exact per-episode artifact files the CLI must publish, exclusive
#: no-overwrite, inside a fresh per-seed output directory.
PER_EPISODE_ARTIFACTS = (
    "started.json",
    "command.txt",
    "environment.json",
    "policy_steps.jsonl",
    "strict_evaluator.jsonl",
    "receipt.json",
    "status",
    "stdout.log",
    "stderr.log",
    "exit_code.txt",
    "finished_at_utc.txt",
    "gpu_before.txt",
    "gpu_during.txt",
    "gpu_after.txt",
    "SHA256SUMS",
)

#: The exact aggregate artifact files published for the full frozen ten-seed
#: batch.  ``final_evidence.SHA256SUMS`` is the independent hash manifest.
AGGREGATE_ARTIFACTS = (
    "g3_summary.json",
    "failure_taxonomy.json",
    "episode_inventory.txt",
    "checkpoint_files.txt",
    "source_files.txt",
    "final_evidence.SHA256SUMS",
)

#: The frozen forbidden-assistance set.  The learned-policy runner may neither
#: invoke nor reproduce any of these.  Pinned by exact equality.
FORBIDDEN_ASSISTANCE = (
    "scripted_planner",
    "inverse_kinematics_oracle",
    "privileged_object_pose_policy_input",
    "weld_or_attachment_assistance",
    "trajectory_replay",
    "feedback_correction_oracle",
    "demonstration_action_fallback",
    "action_substitution_after_policy_inference",
    "success_predicate_relaxation",
    "seed_dependent_controller_parameters",
)

#: The exact frozen G3 seed comparison set (101-110).  Seed 101 is also the
#: infrastructure smoke and is part of this set; it is never replaced.
G3_SEEDS = (101, 102, 103, 104, 105, 106, 107, 108, 109, 110)
SMOKE_SEED = 101

#: The frozen open-loop v3 virtual-gripper projection contract.  The closed
#: loop reuses this exact projection (``actuator_admission.reuse_openloop_v3_
#: projection``).  These literals mirror
#: ``configs/act-openloop-inference-v3.json`` so the closed loop cannot drift
#: from the admitted open-loop actuator domain.
V3_GRIPPER_PROJECTION = {
    "mode": "componentwise_saturation",
    "domain": [0.0, 1.0],
    "indices": [7, 15],
    "index_source": "target.joint_order entries ending in _gripper_joint",
    "arm_channels_projected": False,
    "non_finite_policy": "reject",
    "saturation_is_failure": False,
    "record_raw_and_projected": True,
    "selection_not_data_dependent": True,
}

#: The frozen open-loop v3 physical-joint projection contract, mirroring the v3
#: gate.  Postprojection violations are safety failures; preprojection
#: violations are diagnostic only.
V3_PHYSICAL_PROJECTION = {
    "mode": "componentwise_saturation",
    "domain_source": "configs/fixed-base-plan.json joint_limits",
    "applies_to_all_physical_joints": True,
    "physical_joint_count": 18,
    "non_finite_policy": "reject",
    "preprojection_violations_are_diagnostic": True,
    "postprojection_violations_are_failure": True,
    "record_raw_and_projected": True,
    "selection_not_data_dependent": True,
}


# ---------------------------------------------------------------------------
# Pure data containers shared by the runtime adapter and the audit core.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SafetySignals:
    """Privileged per-tick safety state sampled *after* the action is applied.

    The runtime owns the contact / divergence probes; the core only consumes
    these booleans and classifies them.  Privileged state is never handed to
    the policy.
    """

    physics_step: int
    finite: bool
    robot_table_contact: bool
    robot_self_contact: bool
    forbidden_collision_pairs: tuple[str, ...] = ()
    workspace_violations: tuple[str, ...] = ()


@dataclass(frozen=True)
class EvaluatorFrame:
    """Privileged evaluator state for one 30 Hz frame, sampled after the hold.

    The runtime resolves bowl poses, linear/angular velocities, and gripper
    open fractions; the core passes them straight to the frozen strict
    evaluator.  No field of this struct is visible to the policy.
    """

    positions_xyz_m: tuple[tuple[float, float, float], ...]
    linear_velocities_m_s: tuple[tuple[float, float, float], ...]
    angular_velocities_rad_s: tuple[tuple[float, float, float], ...]
    left_gripper_open_fraction: float
    right_gripper_open_fraction: float


@dataclass(frozen=True)
class TickTelemetry:
    """Per-policy-tick actuator + timing telemetry retained for the receipt."""

    policy_step: int
    physics_step: int
    physics_steps_held: int
    policy_timestamp_s: float
    physics_timestamp_s: float
    sampling_skew_s: float
    raw_action_16d: list[float]
    projected_action_16d: list[float]
    raw_physical_target_18d: list[float]
    projected_physical_target_18d: list[float]
    saturated_action_indices: list[int]
    saturated_physical_joint_names: list[str]
    saturation_max_abs_delta: float
    physical_saturation_max_abs_delta: float
    preprojection_joint_limit_issues: list[str]
    postprojection_joint_limit_issues: list[str]
    action_finite: bool
    observation_valid: bool
    safety_pass: bool
    safety_signals: SafetySignals
    latency_ms: float | None


@runtime_checkable
class ClosedLoopRuntime(Protocol):
    """Minimal learned-policy view of the local Genesis + ACT runtime.

    Implementations hold the torch / lerobot / genesis dependencies; the core
    only consumes the values below, so a test double satisfies the protocol
    without any of those packages installed.  The runtime never selects,
    substitutes, or corrects an action; it only renders observations, infers
    under ``torch.inference_mode``, applies the projected target, and samples
    privileged safety/evaluator state.
    """

    lerobot_version: str
    genesis_version: str
    policy_device: str
    policy_device_index: str
    hip_device_count: int
    policy_config: dict[str, Any]
    processor_artifact_hashes: dict[str, str]
    environment_identity: dict[str, Any]
    input_hashes: dict[str, str]

    def reset_policy_state(self) -> None:
        """Reset ACT episodic state exactly once at the start of the episode."""

    def observe(self, policy_step: int) -> Observation:
        """Render the current 16D state + three cameras at one policy tick."""

    def infer(
        self, observation: Observation, policy_step: int
    ) -> tuple[list[float], float | None]:
        """Run ACT under ``torch.inference_mode`` and return one finite 16D
        postprocessed action plus a descriptive latency in milliseconds."""

    def apply_target(
        self,
        physical_target_18d: Sequence[float],
        *,
        policy_step: int,
        physics_step: int,
        physics_steps_to_hold: int,
    ) -> None:
        """Apply the projected 18D absolute joint-position target and hold it
        on the 250 Hz physics clock until the next causal policy tick."""

    def sample_safety(self, policy_step: int) -> SafetySignals:
        """Sample privileged safety state after the held target settles."""

    def sample_evaluator(self, policy_step: int) -> EvaluatorFrame:
        """Sample privileged evaluator state for the frozen strict frame."""


# ---------------------------------------------------------------------------
# Static contract validation.
# ---------------------------------------------------------------------------


def _require_str(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value:
        raise ContractError(f"G3 contract {name} must be a non-empty string")
    return value


def validate_config(gate: dict[str, Any]) -> None:
    """Validate the static G3 closed-loop phase contract and its invariants.

    Every contract-bearing scalar is pinned by exact equality so the checked-in
    JSON cannot drift: seeds, clock rule, observation/action dimensions,
    forbidden assistance, evidence artifacts, promotion thresholds, and the
    claim boundary.
    """

    if gate.get("schema_version") != 1:
        raise ContractError("G3 contract schema_version must be 1")
    if gate.get("gate_id") != "mantis_act_closedloop_g3_v1":
        raise ContractError("G3 contract gate_id must be mantis_act_closedloop_g3_v1")
    _require_str(gate.get("task_id"), "task_id")
    if gate["task_id"] != "stack_bowls_three":
        raise ContractError("G3 contract task_id must be stack_bowls_three")
    _require_str(gate.get("protocol"), "protocol")
    if gate["protocol"] != "competition_strict_v1_learned_policy_closed_loop":
        raise ContractError("G3 contract protocol changed")
    if gate.get("phase") != "closed_loop_learned_policy_evaluation":
        raise ContractError("G3 contract phase changed")
    _require_str(gate.get("training_id"), "training_id")

    for field_name, expected in (
        ("training_contract", "configs/act-rocm-baseline-v2.json"),
        ("openloop_admission_contract", "configs/act-openloop-inference-v3.json"),
        ("task_contract", "configs/task-pack-v1.json"),
        ("scene_contract", "configs/stack-bowls-genesis-v1.json"),
        ("source_reset_contract", "configs/source-task-stack-bowls-three.json"),
        ("interface_contract", "configs/mantis-lerobot-interface-v1.json"),
        ("port_config", "configs/mantis-port-config.json"),
        ("fixed_joint_limit_source", "configs/fixed-base-plan.json"),
        ("camera_contract", "configs/camera-extrinsics-v1.json"),
    ):
        if gate.get(field_name) != expected:
            raise ContractError(f"G3 contract {field_name} changed")

    checkpoint = gate.get("checkpoint")
    if not isinstance(checkpoint, dict):
        raise ContractError("G3 contract checkpoint must be an object")
    if checkpoint.get("training_step") != 60000:
        raise ContractError("G3 contract checkpoint.training_step must be 60000")
    if checkpoint.get("relative_path") != "checkpoints/060000/pretrained_model":
        raise ContractError("G3 contract checkpoint.relative_path changed")
    if checkpoint.get("frozen") is not True:
        raise ContractError("G3 contract checkpoint must be frozen")
    if checkpoint.get("must_use_saved_processors") is not True:
        raise ContractError("G3 contract must use the saved checkpoint processors")
    if checkpoint.get("must_not_recompute_normalization_statistics") is not True:
        raise ContractError(
            "G3 contract must not recompute dataset normalization statistics"
        )

    runtime = gate.get("runtime")
    if not isinstance(runtime, dict):
        raise ContractError("G3 contract runtime must be an object")
    for field_name, expected in (
        ("simulator", "Genesis"),
        ("framework", "LeRobot"),
        ("policy_type", "act"),
        ("device", "cuda:0"),
    ):
        if runtime.get(field_name) != expected:
            raise ContractError(f"G3 contract runtime.{field_name} changed")
    if runtime.get("genesis_version") != EXPECTED_GENESIS_VERSION:
        raise ContractError(
            f"G3 contract runtime.genesis_version must be {EXPECTED_GENESIS_VERSION}"
        )
    if runtime.get("lerobot_version") != EXPECTED_LEROBOT_VERSION:
        raise ContractError(
            f"G3 contract runtime.lerobot_version must be {EXPECTED_LEROBOT_VERSION}"
        )
    if runtime.get("required_hip_device_count") != 1:
        raise ContractError("G3 contract must require exactly one HIP device")
    if runtime.get("single_gpu_only") is not True:
        raise ContractError("G3 contract must be single-GPU only")
    if runtime.get("offline_model_loading") is not True:
        raise ContractError("G3 contract must load the model offline")
    if not isinstance(runtime.get("device_semantics"), str) or not runtime["device_semantics"]:
        raise ContractError("G3 contract runtime.device_semantics must be present")

    protocol = gate.get("episode_protocol")
    if not isinstance(protocol, dict):
        raise ContractError("G3 contract episode_protocol must be an object")
    if protocol.get("smoke_seed") != SMOKE_SEED:
        raise ContractError(f"G3 contract smoke_seed must be {SMOKE_SEED}")
    if tuple(protocol.get("g3_seeds", [])) != G3_SEEDS:
        raise ContractError(f"G3 contract g3_seeds must be exactly {list(G3_SEEDS)}")
    if protocol.get("smoke_is_part_of_frozen_g3_seed_set") is not True:
        raise ContractError("G3 contract smoke seed must be part of the frozen G3 set")
    if protocol.get("reset_distribution") != "exact_source_reset_distribution":
        raise ContractError("G3 contract reset_distribution changed")
    if protocol.get("domain_randomization_enabled") is not False:
        raise ContractError("G3 contract must disable domain randomization")
    if protocol.get("maximum_policy_steps") != 1200:
        raise ContractError("G3 contract maximum_policy_steps must be 1200")
    if protocol.get("policy_hz") != 30.0:
        raise ContractError("G3 contract policy_hz must be 30.0")
    if protocol.get("physics_hz") != 250.0:
        raise ContractError("G3 contract physics_hz must be 250.0")
    if protocol.get("physics_dt_s") != 0.004:
        raise ContractError("G3 contract physics_dt_s must be 0.004")
    if protocol.get("policy_reset_frequency") != "once_at_episode_start_only":
        raise ContractError(
            "G3 contract must reset ACT once at episode start only"
        )
    if protocol.get("policy_chunk_size") != 30 or protocol.get("n_action_steps") != 30:
        raise ContractError("G3 contract chunk/n_action steps must be 30")
    if protocol.get("n_observation_steps") != 1:
        raise ContractError("G3 contract n_observation_steps must be 1")

    schedule = gate.get("control_schedule")
    if not isinstance(schedule, dict):
        raise ContractError("G3 contract control_schedule must be an object")
    if schedule.get("mode") != "zero_order_hold_absolute_joint_position_target":
        raise ContractError("G3 contract control mode changed")
    if schedule.get("policy_tick_to_physics_step") != (
        "ceil((policy_step / 30) / 0.004 - 1e-12)"
    ):
        raise ContractError("G3 contract tick-to-physics rule changed")
    if tuple(schedule.get("first_policy_physics_steps", [])) != (0, 9, 17, 25, 34):
        raise ContractError(
            "G3 contract first_policy_physics_steps must be [0, 9, 17, 25, 34]"
        )
    if schedule.get("maximum_timing_skew_s_exclusive") != 0.004:
        raise ContractError("G3 contract timing skew bound changed")
    if schedule.get("observe_then_infer_then_project_then_apply") is not True:
        raise ContractError("G3 contract must observe-infer-project-apply")
    if schedule.get("hold_projected_18d_target_until_next_policy_tick") is not True:
        raise ContractError("G3 contract must zero-order-hold the 18D target")
    if schedule.get("no_topp_resampling_applied_to_policy_outputs") is not True:
        raise ContractError("G3 contract must not apply TOPP resampling to ACT outputs")
    if not isinstance(schedule.get("rationale"), str) or not schedule["rationale"]:
        raise ContractError("G3 contract control_schedule.rationale must be present")

    observation = gate.get("observation_contract")
    if not isinstance(observation, dict):
        raise ContractError("G3 contract observation_contract must be an object")
    if observation.get("state_dimension") != 16:
        raise ContractError("G3 contract state_dimension must be 16")
    if observation.get("action_dimension") != 16:
        raise ContractError("G3 contract action_dimension must be 16")
    if observation.get("physical_joint_count") != 18:
        raise ContractError("G3 contract physical_joint_count must be 18")
    expected_images = {
        "observation.images.env_cam": [3, 240, 320],
        "observation.images.left_wrist_cam": [3, 240, 424],
        "observation.images.right_wrist_cam": [3, 240, 424],
    }
    if observation.get("image_features_chw") != expected_images:
        raise ContractError("G3 contract image_features_chw shapes changed")
    if observation.get("image_value_range") != [0.0, 1.0]:
        raise ContractError("G3 contract image_value_range must be [0.0, 1.0]")
    if observation.get("evaluator_privileged_state_not_visible_to_policy") is not True:
        raise ContractError(
            "G3 contract must keep evaluator privileged state off the policy input"
        )

    _validate_actuator_admission(gate.get("actuator_admission"))

    evaluator = gate.get("strict_evaluator")
    if not isinstance(evaluator, dict):
        raise ContractError("G3 contract strict_evaluator must be an object")
    if evaluator.get("source") != "mantis_rocm_bridge.stack_bowls.evaluate_strict_target_frame":
        raise ContractError("G3 contract strict evaluator source changed")
    if evaluator.get("stable_frame_tracker") != (
        "mantis_rocm_bridge.stack_bowls.StackStabilityTracker"
    ):
        raise ContractError("G3 contract stability tracker source changed")
    if evaluator.get("required_consecutive_success_frames") != 12:
        raise ContractError("G3 contract requires 12 consecutive success frames")
    if evaluator.get("evaluate_at_policy_rate") is not True:
        raise ContractError("G3 contract must evaluate at the 30 Hz policy rate")
    if evaluator.get("task_success_requires_no_safety_failure") is not True:
        raise ContractError("G3 contract task success must require no safety failure")
    if evaluator.get("failure_taxonomy_source") != (
        "configs/task-pack-v1.json evaluation.failure_taxonomy"
    ):
        raise ContractError("G3 contract failure taxonomy source changed")

    if tuple(gate.get("forbidden_assistance", [])) != FORBIDDEN_ASSISTANCE:
        raise ContractError("G3 contract forbidden_assistance set changed")

    promotion = gate.get("promotion")
    if not isinstance(promotion, dict):
        raise ContractError("G3 contract promotion must be an object")
    expected_promotion = {
        "seed_101_smoke_requires_terminal_receipt": True,
        "seed_101_smoke_requires_zero_safety_failures": True,
        "seed_101_infrastructure_failure_blocks_batch": True,
        "seed_101_task_failure_without_safety_failure_does_not_block_batch": True,
        "required_g3_episodes": 10,
        "minimum_g3_successes": 6,
        "minimum_g3_success_rate": 0.6,
        "maximum_g3_safety_failures": 0,
    }
    if promotion != expected_promotion:
        raise ContractError("G3 contract promotion thresholds changed")

    if tuple(gate.get("required_per_episode_artifacts", [])) != PER_EPISODE_ARTIFACTS:
        raise ContractError("G3 contract per-episode artifact set changed")
    if tuple(gate.get("required_aggregate_artifacts", [])) != AGGREGATE_ARTIFACTS:
        raise ContractError("G3 contract aggregate artifact set changed")

    output_policy = gate.get("output_policy")
    if not isinstance(output_policy, dict):
        raise ContractError("G3 contract output_policy must be an object")
    expected_output_policy = {
        "fresh_directory_only": True,
        "exclusive_no_overwrite": True,
        "failed_receipts_are_immutable": True,
        "video_is_desirable_not_a_success_predicate": True,
    }
    if output_policy != expected_output_policy:
        raise ContractError("G3 contract output_policy changed")

    boundary = gate.get("claim_boundary")
    if not isinstance(boundary, dict):
        raise ContractError("G3 contract claim_boundary must be an object")
    expected_boundary_flags = {
        "seed_101_smoke_proves_g3": False,
        "passing_g3_proves_exact_distribution_closed_loop_only": True,
        "proves_training_convergence": False,
        "proves_g4_confirmation": False,
        "proves_domain_randomization_robustness": False,
        "proves_generalization": False,
        "proves_real_robot_safety": False,
        "proves_amd_performance_advantage": False,
    }
    for flag, expected in expected_boundary_flags.items():
        if boundary.get(flag) is not expected:
            raise ContractError(f"G3 contract claim_boundary.{flag} changed")
    if not isinstance(boundary.get("statement"), str) or not boundary["statement"]:
        raise ContractError("G3 contract claim_boundary.statement must be present")


def _validate_actuator_admission(admission: Any) -> None:
    if not isinstance(admission, dict):
        raise ContractError("G3 contract actuator_admission must be an object")
    if admission.get("reuse_openloop_v3_projection") is not True:
        raise ContractError(
            "G3 contract must reuse the admitted open-loop v3 actuator projection"
        )
    if admission.get("virtual_gripper_projection_indices") != [7, 15]:
        raise ContractError("G3 contract virtual gripper projection indices changed")
    if admission.get("virtual_gripper_domain") != [0.0, 1.0]:
        raise ContractError("G3 contract virtual gripper domain changed")
    gripper_readback_tolerance = admission.get(
        "gripper_readback_range_tolerance_normalized"
    )
    if (
        isinstance(gripper_readback_tolerance, bool)
        or not isinstance(gripper_readback_tolerance, (int, float))
        or not math.isfinite(float(gripper_readback_tolerance))
        or float(gripper_readback_tolerance) != 0.003
    ):
        raise ContractError(
            "G3 contract gripper readback range tolerance must be exactly 0.003"
        )
    if admission.get("physical_joint_projection_domain") != (
        "configs/fixed-base-plan.json joint_limits"
    ):
        raise ContractError("G3 contract physical projection domain changed")
    if admission.get("non_finite_target_is_failure") is not True:
        raise ContractError("G3 contract must treat non-finite targets as failure")
    for flag in (
        "record_raw_and_projected_16d",
        "record_raw_and_projected_18d",
        "record_saturated_channels_and_projection_magnitude",
    ):
        if admission.get(flag) is not True:
            raise ContractError(f"G3 contract actuator_admission.{flag} must be true")
    if admission.get("postprojection_limit_violation_is_safety_failure") is not True:
        raise ContractError(
            "G3 contract must treat postprojection limit violations as safety failures"
        )
    if admission.get("simulation_only_gripper_mapping") is not True:
        raise ContractError("G3 contract gripper mapping must be simulation only")


def validate_policy_config(policy_config: Any, gate: dict[str, Any]) -> None:
    """Validate the loaded ACT checkpoint ``config.json`` against the frozen G3 loop.

    The saved checkpoint config must agree with the frozen episode protocol
    (``chunk_size``/``n_action_steps`` of 30, ``n_obs_steps`` of 1) and the
    frozen observation contract (16D state/action, the exact three CHW image
    shapes).  A drift here means the checkpoint is not the frozen one and the
    loop must fail closed rather than execute it.
    """

    if not isinstance(policy_config, dict):
        raise ContractError("loaded policy config must be an object")
    protocol = gate["episode_protocol"]
    observation = gate["observation_contract"]
    expected_scalars = {
        "chunk_size": int(protocol["policy_chunk_size"]),
        "n_action_steps": int(protocol["n_action_steps"]),
        "n_obs_steps": int(protocol["n_observation_steps"]),
    }
    for key, expected in expected_scalars.items():
        observed = policy_config.get(key)
        if not isinstance(observed, int) or int(observed) != expected:
            raise ContractError(
                f"loaded policy config {key} must be {expected}, got {observed!r}"
            )
    input_features = policy_config.get("input_features")
    output_features = policy_config.get("output_features")
    if not isinstance(input_features, dict) or not isinstance(output_features, dict):
        raise ContractError(
            "loaded policy config must carry input_features and output_features objects"
        )
    state_dimension = int(observation["state_dimension"])
    action_dimension = int(observation["action_dimension"])
    state_feature = input_features.get("observation.state")
    if not isinstance(state_feature, dict) or list(state_feature.get("shape")) != [state_dimension]:
        raise ContractError(
            f"loaded policy config observation.state shape must be [{state_dimension}]"
        )
    action_feature = output_features.get("action")
    if not isinstance(action_feature, dict) or list(action_feature.get("shape")) != [action_dimension]:
        raise ContractError(
            f"loaded policy config action shape must be [{action_dimension}]"
        )
    for feature, shape in observation["image_features_chw"].items():
        expected_shape = [int(part) for part in shape]
        feature_config = input_features.get(feature)
        if (
            not isinstance(feature_config, dict)
            or [int(part) for part in feature_config.get("shape", [])] != expected_shape
        ):
            raise ContractError(
                f"loaded policy config {feature} shape must be {expected_shape}"
            )


# ---------------------------------------------------------------------------
# Seed selection and smoke / batch admission semantics.
# ---------------------------------------------------------------------------


def select_g3_seeds(gate: dict[str, Any]) -> list[int]:
    """Return the exact frozen G3 seed comparison set (101-110)."""

    validate_config(gate)
    seeds = gate["episode_protocol"]["g3_seeds"]
    if [int(seed) for seed in seeds] != list(G3_SEEDS):
        raise ContractError("G3 seed set drifted after validation")
    return [int(seed) for seed in seeds]


def is_smoke_seed(seed: int, gate: dict[str, Any]) -> bool:
    """True only for the frozen seed-101 infrastructure smoke."""

    validate_config(gate)
    return int(seed) == int(gate["episode_protocol"]["smoke_seed"])


def is_frozen_g3_seed(seed: int, gate: dict[str, Any]) -> bool:
    """True only for seeds in the exact frozen G3 comparison set."""

    return int(seed) in select_g3_seeds(gate)


def smoke_seed_admission(receipt: dict[str, Any], gate: dict[str, Any]) -> dict[str, Any]:
    """Decide whether the seed-101 smoke admits the rest of the batch.

    The smoke blocks the batch when it lacks a terminal receipt, carries a
    safety defect, terminates with a runtime error, or shows any runtime-
    identity drift.  An ordinary strict task failure (e.g. a terminal timeout)
    with valid safety evidence and a matching runtime identity is admissible
    and does not block.
    """

    promotion = gate["promotion"]
    terminal = bool(receipt.get("terminal"))
    terminal_reason = str(receipt.get("terminal_reason", ""))
    safety_failures = int(receipt.get("safety_failure_count", 0))
    has_safety_failure = safety_failures > 0 or bool(receipt.get("has_safety_failure"))
    identity_block = receipt.get("runtime_identity") or {}
    identity_issues = (
        identity_block.get("identity_issues", [])
        if isinstance(identity_block, dict)
        else []
    )
    has_identity_issue = bool(identity_issues)
    is_runtime_error = terminal_reason == RUNTIME_ERROR
    infrastructure_block = is_runtime_error or has_identity_issue

    admitted = (
        terminal
        and not has_safety_failure
        and not infrastructure_block
    )
    blocking = (
        (not terminal and promotion["seed_101_infrastructure_failure_blocks_batch"])
        or (has_safety_failure and promotion["seed_101_smoke_requires_zero_safety_failures"])
        or infrastructure_block
    )
    return {
        "seed": int(receipt.get("seed", SMOKE_SEED)),
        "terminal_receipt": terminal,
        "terminal_reason": terminal_reason,
        "safety_failures": safety_failures,
        "has_safety_failure": has_safety_failure,
        "runtime_identity_issues": list(identity_issues),
        "has_runtime_identity_issue": has_identity_issue,
        "is_runtime_error": is_runtime_error,
        "task_failure_without_safety_failure": (
            terminal
            and not has_safety_failure
            and not infrastructure_block
            and not bool(receipt.get("task_success"))
        ),
        "admitted_to_batch": admitted,
        "blocks_batch": blocking,
        "seed_replaced": False,
    }


def evaluate_g3_promotion(
    receipts: Sequence[dict[str, Any]],
    gate: dict[str, Any],
) -> dict[str, Any]:
    """Compute the frozen G3 promotion decision from immutable episode receipts.

    Exactly ten frozen receipts are required (no replacement, no omission).  The
    batch passes only with at least six strict successes and zero safety
    failures.  Seed 101 is never replaced: if it is missing or duplicated the
    batch is incomplete and therefore blocked.
    """

    promotion = gate["promotion"]
    expected = select_g3_seeds(gate)
    observed = [int(receipt.get("seed")) for receipt in receipts]
    complete = observed == expected
    success_count = sum(1 for receipt in receipts if receipt.get("task_success"))
    safety_failure_count = sum(
        1 for receipt in receipts if receipt.get("has_safety_failure")
    )
    episode_count = len(receipts)
    success_rate = (success_count / episode_count) if episode_count else 0.0

    seeds_unique = len(set(observed)) == len(observed)
    no_replacement = complete and seeds_unique
    meets_success = (
        no_replacement
        and success_count >= promotion["minimum_g3_successes"]
        and success_rate >= promotion["minimum_g3_success_rate"]
    )
    meets_safety = safety_failure_count <= promotion["maximum_g3_safety_failures"]
    g3_pass = bool(no_replacement and meets_success and meets_safety)
    blocked = not complete or (complete and not seeds_unique)
    return {
        "required_g3_episodes": promotion["required_g3_episodes"],
        "observed_episodes": episode_count,
        "expected_seeds": list(expected),
        "observed_seeds": observed,
        "batch_complete": complete,
        "seeds_unique": seeds_unique,
        "no_seed_replacement": no_replacement,
        "strict_successes": success_count,
        "minimum_g3_successes": promotion["minimum_g3_successes"],
        "minimum_g3_success_rate": promotion["minimum_g3_success_rate"],
        "observed_success_rate": success_rate,
        "safety_failures": safety_failure_count,
        "maximum_g3_safety_failures": promotion["maximum_g3_safety_failures"],
        "g3_pass": g3_pass,
        "blocked": blocked,
        "claim_boundary": gate["claim_boundary"],
    }


# ---------------------------------------------------------------------------
# 30 Hz policy tick to 250 Hz first-non-early physics-step mapping.
# ---------------------------------------------------------------------------


def policy_tick_to_physics_step(
    policy_step: int,
    *,
    policy_hz: float = 30.0,
    physics_dt_s: float = 0.004,
) -> int:
    """Frozen ceiling rule: ``ceil((k / 30) / 0.004 - 1e-12)``.

    The epsilon pulls the policy timestamp slightly below the matching physics
    step boundary so the ceiling selects the first physics step that is *not
    early* relative to the policy tick.  Returns the first non-early physics
    step index.
    """

    _validate_rates(policy_hz=policy_hz, physics_dt_s=physics_dt_s)
    if not isinstance(policy_step, int) or isinstance(policy_step, bool):
        raise ContractError("policy_step must be an integer")
    if policy_step < 0:
        raise ContractError("policy_step must be non-negative")
    policy_timestamp = policy_step / policy_hz
    return int(math.ceil(policy_timestamp / physics_dt_s - 1e-12))


def _validate_rates(*, policy_hz: float, physics_dt_s: float) -> None:
    if not math.isfinite(policy_hz) or policy_hz <= 0:
        raise ContractError("policy_hz must be finite and positive")
    if not math.isfinite(physics_dt_s) or physics_dt_s <= 0:
        raise ContractError("physics_dt_s must be finite and positive")


def tick_schedule(
    *,
    count: int,
    policy_hz: float = 30.0,
    physics_dt_s: float = 0.004,
    maximum_skew_s: float = 0.004,
) -> list[dict[str, Any]]:
    """Return the first ``count`` policy-tick -> physics-step mappings.

    Each row records the policy timestamp, the first non-early physics step, the
    physics timestamp, the sampling skew, and how many physics steps the target
    is held before the next tick.  Skew must stay below one physics step.
    """

    _validate_rates(policy_hz=policy_hz, physics_dt_s=physics_dt_s)
    if not isinstance(count, int) or isinstance(count, bool) or count <= 0:
        raise ContractError("count must be a positive integer")
    rows: list[dict[str, Any]] = []
    for index in range(count + 1):
        policy_timestamp = index / policy_hz
        physics_step = int(math.ceil(policy_timestamp / physics_dt_s - 1e-12))
        physics_timestamp = physics_step * physics_dt_s
        skew = physics_timestamp - policy_timestamp
        skew = max(0.0, skew)
        if skew >= maximum_skew_s + 1e-12:
            raise ContractError(
                f"timing skew {skew} at policy step {index} exceeds one physics step"
            )
        if index == 0:
            held = physics_step
        else:
            previous = rows[-1]["physics_step"]
            held = physics_step - previous
        rows.append(
            {
                "policy_step": index,
                "policy_timestamp_s": policy_timestamp,
                "physics_step": physics_step,
                "physics_timestamp_s": physics_timestamp,
                "sampling_skew_s": skew,
                "physics_steps_held": held,
            }
        )
    # ``count`` rows carry a defined hold interval; the trailing row is dropped
    # because its hold extends into the unobserved next tick.
    return rows[:count]


def first_policy_physics_steps(count: int = 5) -> list[int]:
    """Return the first ``count`` physics steps for policy ticks 0, 1, 2, ..."""

    schedule = tick_schedule(count=count)
    return [row["physics_step"] for row in schedule]


# ---------------------------------------------------------------------------
# Open-loop v3 actuator projection wrapper (finite action admission).
# ---------------------------------------------------------------------------


def _v3_projection_view() -> dict[str, Any]:
    """Build the synthetic v3 gate view used to reuse the open-loop projection.

    The closed-loop gate does not carry the v2/v3 projection blocks itself; it
    declares ``actuator_admission.reuse_openloop_v3_projection`` instead.  We
    therefore reconstruct the exact frozen v3 projection literals and hand them
    to the accepted open-loop projection helpers so the closed loop can never
    drift from the admitted open-loop actuator domain.
    """

    return {
        "gate_id": "mantis_act_openloop_inference_v3",
        "gripper_output_projection": dict(V3_GRIPPER_PROJECTION),
        "physical_joint_output_projection": dict(V3_PHYSICAL_PROJECTION),
    }


def admit_policy_action(
    action: Sequence[float],
    *,
    port: dict[str, Any],
    fixed_plan: dict[str, Any],
    action_dimension: int = 16,
) -> tuple[
    list[float],
    list[float],
    list[float],
    list[int],
    list[str],
    float,
    float,
    list[str],
    list[str],
]:
    """Project one finite 16D policy action through the admitted v3 adapter.

    Returns a tuple of:

    ``(projected_action_16d, raw_physical_18d, projected_physical_18d,
       saturated_action_indices, saturated_physical_joint_names,
       saturation_max_abs_delta, physical_saturation_max_abs_delta,
       preprojection_joint_limit_issues, postprojection_joint_limit_issues)``.

    Non-finite actions are rejected (the empty projection signals the caller to
    treat the tick as a non-finite-target safety failure).  Preprojection
    violations are diagnostic; postprojection violations are safety failures
    because the projected target must satisfy every fixed-base limit.
    """

    finite, validated = validate_action_vector(action, action_dimension=action_dimension)
    if not finite:
        empty = []  # type: ignore[var-annotated]
        return ([], [], [], [], [], 0.0, 0.0, [], ["non_finite_policy_action"])

    view = _v3_projection_view()
    physical_order = port["target"]["physical_joint_order"]
    limits = physical_joint_limits(fixed_plan, physical_order)

    projected_action, saturated_indices, sat_delta = project_virtual_gripper_action(
        validated, gate=view, port=port
    )
    raw_physical = expand_virtual_to_physical(projected_action, port=port)
    preprojection_issues = enforce_joint_limits(
        raw_physical, physical_order=physical_order, limits=limits
    )
    physical, saturated_names, physical_sat_delta = project_physical_joint_target(
        raw_physical, gate=view, physical_order=physical_order, limits=limits
    )
    postprojection_issues = enforce_joint_limits(
        physical, physical_order=physical_order, limits=limits
    )
    return (
        projected_action,
        raw_physical,
        physical,
        saturated_indices,
        saturated_names,
        sat_delta,
        physical_sat_delta,
        preprojection_issues,
        postprojection_issues,
    )


# ---------------------------------------------------------------------------
# Failure taxonomy.
# ---------------------------------------------------------------------------


#: Terminal outcome reasons emitted by the closed loop.
TASK_SUCCESS = "task_success"
TIMEOUT = "timeout"
COLLISION_SAFETY = "collision_safety"
JOINT_LIMIT_SAFETY = "joint_limit_safety"
WORKSPACE_SAFETY = "workspace_safety"
PHYSICS_DIVERGENCE = "physics_divergence"
NON_FINITE_ACTION = "non_finite_action"
RUNTIME_ERROR = "runtime_error"

#: Reasons that count as safety failures (block the batch; require zero).
SAFETY_FAILURE_REASONS = frozenset(
    {
        COLLISION_SAFETY,
        JOINT_LIMIT_SAFETY,
        WORKSPACE_SAFETY,
        PHYSICS_DIVERGENCE,
        NON_FINITE_ACTION,
    }
)

#: Reasons that block the batch as infrastructure defects even outside the
#: safety taxonomy (runtime crash, missing receipt).
INFRASTRUCTURE_REASONS = frozenset({RUNTIME_ERROR})


def classify_failure_reason(
    *,
    collision: bool,
    joint_limit: bool,
    workspace: bool,
    physics_divergence: bool,
    non_finite: bool,
    runtime_error: bool,
    timeout: bool,
) -> str:
    """Reduce one set of terminal signals to a single failure reason."""

    if runtime_error:
        return RUNTIME_ERROR
    if non_finite:
        return NON_FINITE_ACTION
    if physics_divergence:
        return PHYSICS_DIVERGENCE
    if collision:
        return COLLISION_SAFETY
    if joint_limit:
        return JOINT_LIMIT_SAFETY
    if workspace:
        return WORKSPACE_SAFETY
    return TIMEOUT


def taxonomy_label(reason: str) -> str:
    """Map a closed-loop reason onto the frozen task-pack failure taxonomy.

    ``task_success`` has no failure label; the caller records it separately.
    ``non_finite_action`` and ``runtime_error`` map to ``runtime_error`` because
    the frozen taxonomy has no dedicated inference-defect entry.
    """

    if reason == TASK_SUCCESS:
        return "task_success"
    if reason in (NON_FINITE_ACTION, RUNTIME_ERROR):
        return "runtime_error"
    if reason == TIMEOUT:
        return "timeout"
    if reason == COLLISION_SAFETY:
        return "collision_safety"
    if reason == JOINT_LIMIT_SAFETY:
        return "joint_limit_safety"
    if reason == WORKSPACE_SAFETY:
        return "workspace_safety"
    if reason == PHYSICS_DIVERGENCE:
        return "physics_divergence"
    return "runtime_error"


def is_safety_failure_reason(reason: str) -> bool:
    return reason in SAFETY_FAILURE_REASONS


# ---------------------------------------------------------------------------
# Closed-loop orchestration.
# ---------------------------------------------------------------------------


def _audit_runtime_identity(runtime: ClosedLoopRuntime, gate: dict[str, Any]) -> list[str]:
    issues: list[str] = []
    runtime_cfg = gate["runtime"]
    if runtime.lerobot_version != runtime_cfg["lerobot_version"]:
        issues.append(
            f"lerobot_version_mismatch:{runtime.lerobot_version}:{runtime_cfg['lerobot_version']}"
        )
    if runtime.genesis_version != runtime_cfg["genesis_version"]:
        issues.append(
            f"genesis_version_mismatch:{runtime.genesis_version}:{runtime_cfg['genesis_version']}"
        )
    if runtime.policy_device != "cuda":
        issues.append(f"policy_device_mismatch:{runtime.policy_device}:cuda")
    if runtime.policy_device_index != runtime_cfg["device"]:
        issues.append(
            f"policy_device_index_mismatch:{runtime.policy_device_index}:{runtime_cfg['device']}"
        )
    if runtime.hip_device_count != runtime_cfg["required_hip_device_count"]:
        issues.append(
            f"hip_device_count_mismatch:{runtime.hip_device_count}:"
            f"{runtime_cfg['required_hip_device_count']}"
        )
    return issues


def run_closed_loop_episode(
    runtime: ClosedLoopRuntime,
    *,
    gate: dict[str, Any],
    gate_sha256: str | None,
    task: dict[str, Any],
    port: dict[str, Any],
    fixed_plan: dict[str, Any],
    seed: int,
    source_hashes: dict[str, str] | None = None,
    checkpoint_hashes: dict[str, str] | None = None,
    maximum_timing_skew_s: float = 0.004,
    reset_count_target: int = 1,
) -> dict[str, Any]:
    """Drive one frozen G3 closed-loop episode and return its receipt.

    The receipt is ``task_success`` only when the runtime identity matches the
    contract, every observation validates, every action is finite and projects
    inside every fixed-base limit, no safety failure occurs, and the frozen
    strict evaluator records twelve consecutive success frames.  Any safety
    failure overrides task success.
    """

    validate_config(gate)
    runtime_issues = _audit_runtime_identity(runtime, gate)
    # The loaded checkpoint config must match the frozen loop exactly.  A drift
    # is a runtime-identity defect: fail closed before any action is applied.
    try:
        validate_policy_config(runtime.policy_config, gate)
    except ContractError as exc:
        runtime_issues.append(f"policy_config_invalid:{exc}")
    episode_protocol = gate["episode_protocol"]
    policy_hz = float(episode_protocol["policy_hz"])
    physics_dt_s = float(episode_protocol["physics_dt_s"])
    maximum_steps = int(episode_protocol["maximum_policy_steps"])
    action_dimension = int(gate["observation_contract"]["action_dimension"])
    state_dimension = int(gate["observation_contract"]["state_dimension"])
    image_features = {
        str(name): tuple(int(part) for part in shape)
        for name, shape in gate["observation_contract"]["image_features_chw"].items()
    }
    image_value_range = gate["observation_contract"]["image_value_range"]
    required_frames = int(gate["strict_evaluator"]["required_consecutive_success_frames"])

    physical_order = port["target"]["physical_joint_order"]
    limits = physical_joint_limits(fixed_plan, physical_order)

    schedule = tick_schedule(
        count=maximum_steps + 1,
        policy_hz=policy_hz,
        physics_dt_s=physics_dt_s,
        maximum_skew_s=maximum_timing_skew_s,
    )

    resets_observed = 0
    reset_policy = getattr(runtime, "reset_policy_state", None)
    if callable(reset_policy):
        reset_policy()
        resets_observed += 1

    tracker = StackStabilityTracker(required_frames=required_frames)
    telemetry: list[TickTelemetry] = []
    evaluator_rows: list[dict[str, Any]] = []
    terminal_reason: str | None = None
    terminal_step = -1
    safety_failure_reasons: list[str] = []
    task_success = False
    loop_error: str | None = None
    observation_invalid = False

    if runtime_issues:
        # Any runtime-identity drift (LeRobot/Genesis version, device, HIP count,
        # or a checkpoint config that does not match the frozen loop) is an
        # infrastructure defect.  Fail closed as a runtime error before a single
        # action is observed, inferred, projected, or applied.  The loop below
        # breaks on its first iteration without touching the runtime so no
        # observation is rendered and no action is applied.
        terminal_reason = RUNTIME_ERROR
        terminal_step = -1

    try:
        for step in range(maximum_steps):
            if runtime_issues:
                break
            row = schedule[step]
            next_row = schedule[step + 1]
            physics_steps_to_hold = max(1, next_row["physics_step"] - row["physics_step"])

            observation = runtime.observe(step)
            obs_issues = validate_observation(
                observation,
                image_features=image_features,
                state_dimension=state_dimension,
                image_value_range=image_value_range,
            )
            observation_valid = not obs_issues
            if not observation_valid:
                observation_invalid = True
                terminal_reason = RUNTIME_ERROR
                terminal_step = step
                safety_failure_reasons.append("invalid_observation")
                break

            action, latency = runtime.infer(observation, step)
            (
                projected_action,
                raw_physical,
                physical,
                saturated_indices,
                saturated_names,
                sat_delta,
                physical_sat_delta,
                preprojection_issues,
                postprojection_issues,
            ) = admit_policy_action(
                action,
                port=port,
                fixed_plan=fixed_plan,
                action_dimension=action_dimension,
            )

            action_finite = bool(projected_action)
            if not action_finite:
                safety_signals = SafetySignals(
                    physics_step=row["physics_step"],
                    finite=False,
                    robot_table_contact=False,
                    robot_self_contact=False,
                )
                telemetry.append(_record_tick(
                    row=row,
                    physics_steps_held=physics_steps_to_hold,
                    action=[],
                    projected_action=[],
                    raw_physical=[],
                    physical=[],
                    saturated_indices=[],
                    saturated_names=[],
                    sat_delta=0.0,
                    physical_sat_delta=0.0,
                    preprojection_issues=preprojection_issues,
                    postprojection_issues=postprojection_issues,
                    action_finite=False,
                    observation_valid=observation_valid,
                    safety_pass=False,
                    safety_signals=safety_signals,
                    latency_ms=latency,
                ))
                terminal_reason = NON_FINITE_ACTION
                terminal_step = step
                safety_failure_reasons.append(NON_FINITE_ACTION)
                break

            # Apply the projected 18D absolute target and hold it.
            runtime.apply_target(
                physical,
                policy_step=step,
                physics_step=row["physics_step"],
                physics_steps_to_hold=physics_steps_to_hold,
            )

            safety_signals = runtime.sample_safety(step)
            postprojection_safety = (
                not postprojection_issues
                and safety_signals.finite
                and not safety_signals.robot_table_contact
                and not safety_signals.robot_self_contact
                and not safety_signals.workspace_violations
            )

            evaluator_frame = runtime.sample_evaluator(step)
            strict = evaluate_strict_target_frame(
                list(evaluator_frame.positions_xyz_m),
                list(evaluator_frame.linear_velocities_m_s),
                list(evaluator_frame.angular_velocities_rad_s),
                left_gripper_open_fraction=evaluator_frame.left_gripper_open_fraction,
                right_gripper_open_fraction=evaluator_frame.right_gripper_open_fraction,
                xy_axis_tolerance_m=float(
                    task["success_predicate"]["xy_axis_alignment_tolerance_m"]
                ),
                height_absolute_tolerance_m=float(
                    task["success_predicate"]["height_absolute_tolerance_m"]
                ),
                maximum_linear_speed_m_s=float(
                    task["success_predicate"]["maximum_linear_speed_m_s"]
                ),
                maximum_angular_speed_rad_s=float(
                    task["success_predicate"]["maximum_angular_speed_rad_s"]
                ),
                minimum_gripper_open_fraction=float(
                    task["success_predicate"]["minimum_gripper_open_fraction"]
                ),
                no_safety_failure=postprojection_safety,
                no_physics_divergence=safety_signals.finite,
            )
            stable = tracker.update(bool(strict["frame_success"]))

            safety_pass = postprojection_safety and not safety_signals.forbidden_collision_pairs
            telemetry.append(_record_tick(
                row, physics_steps_to_hold, action, projected_action, raw_physical,
                physical, saturated_indices, saturated_names, sat_delta,
                physical_sat_delta, preprojection_issues, postprojection_issues,
                True, observation_valid, safety_pass, safety_signals, latency,
            ))
            evaluator_rows.append(
                {
                    "policy_step": step,
                    "physics_step": row["physics_step"],
                    "frame_success": bool(strict["frame_success"]),
                    "consecutive_success_frames": tracker.consecutive_frames,
                    "checks": strict["checks"],
                    "ordered_positions_xyz_m": [
                        list(position) for position in strict["ordered_positions"]
                    ],
                    "left_gripper_open_fraction": evaluator_frame.left_gripper_open_fraction,
                    "right_gripper_open_fraction": evaluator_frame.right_gripper_open_fraction,
                    "safety_pass": safety_pass,
                }
            )

            # Safety overrides task success: classify and terminate immediately.
            if not postprojection_safety:
                terminal_reason = classify_failure_reason(
                    collision=bool(
                        safety_signals.robot_table_contact
                        or safety_signals.robot_self_contact
                        or safety_signals.forbidden_collision_pairs
                    ),
                    joint_limit=bool(postprojection_issues),
                    workspace=bool(safety_signals.workspace_violations),
                    physics_divergence=not safety_signals.finite,
                    non_finite=False,
                    runtime_error=False,
                    timeout=False,
                )
                safety_failure_reasons.append(terminal_reason)
                terminal_step = step
                break
            if safety_signals.forbidden_collision_pairs:
                terminal_reason = COLLISION_SAFETY
                safety_failure_reasons.append(COLLISION_SAFETY)
                terminal_step = step
                break

            if stable:
                task_success = True
                terminal_reason = TASK_SUCCESS
                terminal_step = step
                break
        else:
            terminal_reason = TIMEOUT
            terminal_step = maximum_steps - 1
    except Exception as exc:  # noqa: BLE001 - auditable runtime failure
        loop_error = f"{type(exc).__name__}:{exc}"
        terminal_reason = RUNTIME_ERROR
        terminal_step = max(0, len(telemetry) - 1)
        safety_failure_reasons.append(RUNTIME_ERROR)

    if task_success and safety_failure_reasons:
        # Safety overrides task success even if a late safety signal arrived.
        task_success = False

    has_safety_failure = any(is_safety_failure_reason(r) for r in safety_failure_reasons)
    final_reason = terminal_reason or TIMEOUT
    # task_success is only true when no safety failure occurred.
    effective_success = task_success and not has_safety_failure
    if effective_success:
        final_reason = TASK_SUCCESS

    receipt: dict[str, Any] = {
        "schema_version": 1,
        "gate_id": gate["gate_id"],
        "task_id": gate["task_id"],
        "protocol": gate["protocol"],
        "training_id": gate["training_id"],
        "phase": gate["phase"],
        "seed": int(seed),
        "smoke_seed": is_smoke_seed(seed, gate),
        "frozen_g3_seed": is_frozen_g3_seed(seed, gate),
        "checkpoint_training_step": gate["checkpoint"]["training_step"],
        "task_success": bool(effective_success),
        "terminal": True,
        "terminal_reason": final_reason,
        "terminal_policy_step": int(terminal_step),
        "maximum_policy_steps": maximum_steps,
        "consecutive_success_frames": tracker.consecutive_frames,
        "required_consecutive_success_frames": required_frames,
        "has_safety_failure": has_safety_failure,
        "safety_failure_count": sum(
            1 for r in safety_failure_reasons if is_safety_failure_reason(r)
        ),
        "safety_failure_reasons": sorted(set(safety_failure_reasons)),
        "failure_taxonomy_label": taxonomy_label(final_reason),
        "runtime_identity": {
            "lerobot_version": runtime.lerobot_version,
            "genesis_version": runtime.genesis_version,
            "policy_device": runtime.policy_device,
            "policy_device_index": runtime.policy_device_index,
            "hip_device_count": runtime.hip_device_count,
            "identity_issues": runtime_issues,
        },
        "environment_identity": runtime.environment_identity,
        "input_hashes": runtime.input_hashes,
        "processor_artifact_hashes": runtime.processor_artifact_hashes,
        "policy_config": runtime.policy_config,
        "source_hashes": dict(source_hashes or {}),
        "checkpoint_hashes": dict(checkpoint_hashes or {}),
        "gate_sha256": gate_sha256,
        "control_schedule": {
            "policy_hz": policy_hz,
            "physics_hz": float(episode_protocol["physics_hz"]),
            "physics_dt_s": physics_dt_s,
            "first_policy_physics_steps": [row["physics_step"] for row in schedule[:5]],
            "maximum_timing_skew_s_exclusive": maximum_timing_skew_s,
            "maximum_observed_skew_s": max(
                (row["sampling_skew_s"] for row in schedule[: max(1, len(telemetry))]),
                default=0.0,
            ),
        },
        "policy_state": {
            "policy_reset_frequency": episode_protocol["policy_reset_frequency"],
            "reset_calls_observed": resets_observed,
            "reset_count_target": reset_count_target,
            "one_reset_per_episode": resets_observed == reset_count_target,
            "chunk_queue_preserved_across_ticks": True,
            "n_observation_steps": episode_protocol["n_observation_steps"],
            "policy_chunk_size": episode_protocol["policy_chunk_size"],
        },
        "actuator_admission": {
            "reuse_openloop_v3_projection": True,
            "saturated_action_channel_count": sum(
                len(row.saturated_action_indices) for row in telemetry
            ),
            "saturated_physical_joint_count": sum(
                len(row.saturated_physical_joint_names) for row in telemetry
            ),
            "max_abs_saturation_delta": max(
                (row.saturation_max_abs_delta for row in telemetry), default=0.0
            ),
            "max_abs_physical_saturation_delta": max(
                (row.physical_saturation_max_abs_delta for row in telemetry), default=0.0
            ),
            "postprojection_limit_violations": sum(
                len(row.postprojection_joint_limit_issues) for row in telemetry
            ),
        },
        "policy_steps": _telemetry_records(telemetry),
        "strict_evaluator_rows": evaluator_rows,
        "runtime_error": loop_error,
        "gripper_state_diagnostics": _gripper_diagnostics_view(runtime),
        "no_scripted_assistance": True,
        "forbidden_assistance": list(FORBIDDEN_ASSISTANCE),
        "claim_boundary": gate["claim_boundary"],
        "descriptive": {
            "latency_ms": _latency_summary(telemetry),
            "note": (
                "Policy latency, saturation magnitude, and skew are descriptive "
                "only. They are never a pass threshold and never a comparative "
                "performance claim."
            ),
        },
    }
    return receipt


def _record_tick(
    row: dict[str, Any],
    physics_steps_held: int,
    action: list[float],
    projected_action: list[float],
    raw_physical: list[float],
    physical: list[float],
    saturated_indices: list[int],
    saturated_names: list[str],
    sat_delta: float,
    physical_sat_delta: float,
    preprojection_issues: list[str],
    postprojection_issues: list[str],
    action_finite: bool,
    observation_valid: bool,
    safety_pass: bool,
    safety_signals: SafetySignals,
    latency_ms: float | None,
) -> TickTelemetry:
    return TickTelemetry(
        policy_step=int(row["policy_step"]),
        physics_step=int(row["physics_step"]),
        physics_steps_held=int(physics_steps_held),
        policy_timestamp_s=float(row["policy_timestamp_s"]),
        physics_timestamp_s=float(row["physics_timestamp_s"]),
        sampling_skew_s=float(row["sampling_skew_s"]),
        raw_action_16d=list(action),
        projected_action_16d=list(projected_action),
        raw_physical_target_18d=list(raw_physical),
        projected_physical_target_18d=list(physical),
        saturated_action_indices=list(saturated_indices),
        saturated_physical_joint_names=list(saturated_names),
        saturation_max_abs_delta=float(sat_delta),
        physical_saturation_max_abs_delta=float(physical_sat_delta),
        preprojection_joint_limit_issues=list(preprojection_issues),
        postprojection_joint_limit_issues=list(postprojection_issues),
        action_finite=bool(action_finite),
        observation_valid=bool(observation_valid),
        safety_pass=bool(safety_pass),
        safety_signals=safety_signals,
        latency_ms=latency_ms,
    )


def _telemetry_records(telemetry: Sequence[TickTelemetry]) -> list[dict[str, Any]]:
    return [
        {
            "policy_step": row.policy_step,
            "physics_step": row.physics_step,
            "physics_steps_held": row.physics_steps_held,
            "policy_timestamp_s": row.policy_timestamp_s,
            "physics_timestamp_s": row.physics_timestamp_s,
            "sampling_skew_s": row.sampling_skew_s,
            "raw_action_16d": row.raw_action_16d,
            "projected_action_16d": row.projected_action_16d,
            "raw_physical_target_18d": row.raw_physical_target_18d,
            "projected_physical_target_18d": row.projected_physical_target_18d,
            "saturated_action_indices": row.saturated_action_indices,
            "saturated_action_channel_count": len(row.saturated_action_indices),
            "saturated_physical_joint_names": row.saturated_physical_joint_names,
            "saturated_physical_joint_count": len(row.saturated_physical_joint_names),
            "saturation_max_abs_delta": row.saturation_max_abs_delta,
            "physical_saturation_max_abs_delta": row.physical_saturation_max_abs_delta,
            "preprojection_joint_limit_issues": row.preprojection_joint_limit_issues,
            "postprojection_joint_limit_issues": row.postprojection_joint_limit_issues,
            "action_finite": row.action_finite,
            "observation_valid": row.observation_valid,
            "safety_pass": row.safety_pass,
            "robot_table_contact": row.safety_signals.robot_table_contact,
            "robot_self_contact": row.safety_signals.robot_self_contact,
            "forbidden_collision_pairs": list(row.safety_signals.forbidden_collision_pairs),
            "workspace_violations": list(row.safety_signals.workspace_violations),
            "physics_finite": row.safety_signals.finite,
            "latency_ms": row.latency_ms,
        }
        for row in telemetry
    ]


def _latency_summary(telemetry: Sequence[TickTelemetry]) -> dict[str, float | None]:
    values = [row.latency_ms for row in telemetry if row.latency_ms is not None]
    if not values:
        return {"min": None, "max": None, "mean": None}
    return {
        "min": min(values),
        "max": max(values),
        "mean": sum(values) / len(values),
    }


def _gripper_diagnostics_view(runtime: ClosedLoopRuntime) -> dict[str, Any]:
    """Read retained gripper readback diagnostics from the runtime, if any.

    The real adapter records the bounded v2 projection diagnostics (per-tick
    left/right finger estimates, projected mean, and asymmetry spread) on every
    observation readback.  A dependency-injected test double does not expose
    them, in which case the receipt records their absence rather than claiming
    gripper-state evidence that was never captured.
    """

    history = getattr(runtime, "gripper_state_diagnostics", None)
    if history is None:
        return {
            "available": False,
            "history": [],
            "note": (
                "runtime did not expose gripper readback diagnostics; no "
                "gripper-state evidence is claimed"
            ),
        }
    return {
        "available": True,
        "history": list(history),
        "note": (
            "Per-tick left/right finger estimates, projected mean, and spread "
            "from the bounded v2 physical-to-virtual projection. The spread "
            "(residual) is reported, not used to reject; non-finite or "
            "out-of-domain fingers still fail closed."
        ),
    }


# ---------------------------------------------------------------------------
# Aggregate receipt construction.
# ---------------------------------------------------------------------------


def build_failure_taxonomy(
    receipts: Sequence[dict[str, Any]],
    *,
    taxonomy: Sequence[str],
) -> dict[str, Any]:
    """Aggregate per-episode failure labels into the frozen taxonomy buckets."""

    counts = {label: 0 for label in taxonomy}
    counts["task_success"] = 0
    for receipt in receipts:
        label = receipt.get("failure_taxonomy_label", "runtime_error")
        key = label if label in counts else "runtime_error"
        counts[key] += 1
    return {
        "taxonomy": list(taxonomy),
        "counts": counts,
        "safety_failure_episodes": [
            int(receipt.get("seed"))
            for receipt in receipts
            if receipt.get("has_safety_failure")
        ],
        "task_success_count": counts.get("task_success", 0),
        "total_episodes": len(receipts),
    }


def aggregate_receipt_claim_boundary(gate: dict[str, Any], g3_pass: bool) -> str:
    """Return the precise claim-boundary statement for an aggregate receipt.

    Smoke and incomplete-batch receipts always use the no-claim boundary; only a
    passing G3 batch references the exact-distribution closed-loop boundary.
    """

    boundary = gate["claim_boundary"]
    if g3_pass:
        return boundary["statement"]
    return (
        "Aggregate closed-loop receipt only. It does not prove G3 promotion, "
        "optimization convergence, G4 confirmation, domain-randomization "
        "robustness, unseen-scene generalization, real-robot safety, or an AMD "
        "performance advantage."
    )


def build_sha256sums(entries: Sequence[tuple[str, str]]) -> str:
    """Build a deterministic ``SHA256SUMS`` manifest from ``(digest, name)``.

    Entries are sorted by filename so identical contents produce an identical
    manifest (and therefore an identical manifest hash).
    """

    ordered = sorted(entries, key=lambda entry: entry[1])
    return "".join(f"{digest}  {name}\n" for digest, name in ordered)


def build_directory_manifest(directory: Any) -> str:
    """Hash every real file in ``directory`` (except the manifest itself)."""

    base = Path(directory)
    names = sorted(path.name for path in base.iterdir() if path.is_file())
    entries = [
        (sha256_file(base / name), name)
        for name in names
        if name != "SHA256SUMS" and name != "final_evidence.SHA256SUMS"
    ]
    return build_sha256sums(entries)


def write_text_exclusive(path: Any, content: str) -> None:
    """Create ``path`` with exclusive no-overwrite semantics."""

    with Path(path).open("x", encoding="utf-8") as stream:
        stream.write(content)


# ---------------------------------------------------------------------------
# Lazy Genesis + LeRobot 0.4.4 runtime adapter (torch / lerobot / genesis
# imported here only, inside __init__ and methods).  The module remains
# importable without any of those packages installed.
# ---------------------------------------------------------------------------


#: Environment variables asserted *before* LeRobot / transformers import so a
#: missing local file can never fall through to a network download.
OFFLINE_ENV_FLAGS: dict[str, str] = {
    "HF_HUB_OFFLINE": "1",
    "HF_DATASETS_OFFLINE": "1",
    "TRANSFORMERS_OFFLINE": "1",
}

#: The proximal Mantis mesh pair whose persistent sub-millimetre penetration is
#: explicitly allowed by the accepted Genesis task's collision filter.  Every
#: other self, inter-arm, object, and table pair remains an active collision.
ALLOWED_PROXIMAL_COLLISION_LINKS = ("pelvis_link", "right_shoulder_yaw_link")


def enforce_offline_env() -> dict[str, str]:
    """Assert the Hugging Face offline flags *before* LeRobot is imported."""

    import os

    asserted: dict[str, str] = {}
    for key, value in OFFLINE_ENV_FLAGS.items():
        os.environ[key] = value
        asserted[key] = os.environ.get(key, value)
    return asserted


class GenesisClosedLoopRuntime:
    """Real runtime adapter: Genesis scene + frozen ACT checkpoint.

    The scene construction reuses the accepted Genesis task's constants: the
    same table plane, fixed-base Mantis URDF pose, three-bowl source reset
    distribution, three camera mounts, actuator gains/limits, allowed proximal
    collision filter, and friction coefficients -- read entirely from the frozen
    contracts.  No scripted candidate search, IK, weld, replay, correction,
    oracle, or demonstration action is invoked: this adapter only renders
    observations, infers under ``torch.inference_mode`` while preserving the ACT
    chunk queue across ticks, projects through the v3 adapter (done by the
    core), applies the projected 18D target, and samples privileged safety and
    evaluator state.
    """

    def __init__(
        self,
        *,
        checkpoint_root: Any,
        pretrained_model: Any,
        mantis_urdf: Any,
        bowl_urdf: Any,
        gate: dict[str, Any],
        task: dict[str, Any],
        port: dict[str, Any],
        fixed_plan: dict[str, Any],
        scene_contract: dict[str, Any],
        camera_contract: dict[str, Any],
        source_task: dict[str, Any],
        interface: dict[str, Any],
        seed: int,
        backend: str,
        port_sha256: str,
        interface_sha256: str,
        fixed_plan_sha256: str,
        openloop_admission_gate: dict[str, Any],
        openloop_admission_gate_sha256: str,
        stdout: Any = None,
        stderr: Any = None,
    ) -> None:
        from .act_openloop_inference import validate_required_checkpoint_files

        self._gate = gate
        self._task = task
        self._port = port
        self._fixed_plan = fixed_plan
        self._scene_contract = scene_contract
        self._camera_contract = camera_contract
        self._source_task = source_task
        self._interface = interface
        self._seed = int(seed)
        self._backend = str(backend)
        self._stdout = stdout
        self._stderr = stderr

        self._checkpoint_root = Path(checkpoint_root).resolve()
        self._pretrained = Path(pretrained_model).resolve()
        self._mantis_urdf = Path(mantis_urdf).resolve()
        self._bowl_urdf = Path(bowl_urdf).resolve()
        # The frozen path named by gate["openloop_admission_contract"] is loaded
        # by the CLI and passed in here as the admitted v3 gate; it is the single
        # source of truth for the required checkpoint files and processor-artifact
        # hashes.  It must be exactly the admitted v3 gate -- never inferred.
        if not isinstance(openloop_admission_gate, dict):
            raise ContractError("openloop admission contract must be loaded and passed in")
        if openloop_admission_gate.get("gate_id") != "mantis_act_openloop_inference_v3":
            raise ContractError(
                "openloop admission contract must be the admitted v3 gate "
                "(gate_id=mantis_act_openloop_inference_v3)"
            )
        self._openloop_admission_gate = openloop_admission_gate
        self.openloop_admission_gate_sha256 = str(openloop_admission_gate_sha256)
        self._v3_gate = gate.get("openloop_admission_contract")
        self._gripper_readback_range_tolerance = float(
            gate["actuator_admission"][
                "gripper_readback_range_tolerance_normalized"
            ]
        )

        # Per-tick gripper readback diagnostics (bounded v2 projection); retained
        # for the receipt.  Privileged, never policy-visible.
        self._gripper_diagnostics_history: list[dict[str, Any]] = []
        # Causal observation cache: each camera rendered once per policy step and
        # consumed by inference for that same step.
        self._observation_cache: dict[str, Any] = {}

        # Offline flags FIRST, before any LeRobot / torch import.
        self._offline_env = enforce_offline_env()
        # Prevalidate checkpoint processor files so a missing artifact never
        # falls through to network resolution.  The required-file list comes
        # only from the admitted v3 gate's saved_processor_requirements.
        self._required_processor_files = validate_required_checkpoint_files(
            self._checkpoint_root, openloop_admission_gate
        )

        import torch  # noqa: WPS433 - lazy, runtime-only

        self._torch = torch
        self._device = torch.device("cuda:0")
        self._assert_rocm_identity(torch)

        from lerobot.policies.factory import (  # noqa: WPS433 - lazy
            make_pre_post_processors,
        )
        import lerobot  # noqa: WPS433 - lazy

        # Resolve and validate LeRobot 0.4.4 and Genesis 1.2.3 *before* the
        # environment identity is captured, so identity never reads a stale or
        # unresolved Genesis version.
        self.lerobot_version = self._resolve_lerobot_version(lerobot)
        self._genesis_version = self._resolve_genesis_version()
        self.genesis_version = self._genesis_version
        self._validate_expected_identity_versions()
        self._policy = self._load_policy(torch)
        self._processors = self._load_processors(make_pre_post_processors)
        self.policy_config = self._load_policy_config()
        # Validate the loaded checkpoint config against the frozen loop.
        validate_policy_config(self.policy_config, gate)
        self.policy_device = "cuda"
        self.policy_device_index = "cuda:0"
        self.hip_device_count = int(torch.cuda.device_count())
        self.processor_artifact_hashes = self._hash_processor_artifacts()
        self.environment_identity = self._capture_environment_identity(torch)
        self.input_hashes = {
            "port_config_sha256": port_sha256,
            "interface_contract_sha256": interface_sha256,
            "fixed_base_plan_sha256": fixed_plan_sha256,
            "openloop_admission_contract_sha256": self.openloop_admission_gate_sha256,
            "lerobot_version": self.lerobot_version,
            "genesis_version": self.genesis_version,
        }

        self._build_scene()

        # Evaluator velocity bookkeeping (privileged, never policy-visible).
        self._previous_positions = None
        self._previous_quaternions = None
        self._previous_physics_step = 0

    @property
    def gripper_state_diagnostics(self) -> list[dict[str, Any]]:
        """Retained per-tick gripper readback diagnostics for the receipt."""

        return list(self._gripper_diagnostics_history)

    def _validate_expected_identity_versions(self) -> None:
        if self.lerobot_version != EXPECTED_LEROBOT_VERSION:
            raise ContractError(
                f"LeRobot version must be {EXPECTED_LEROBOT_VERSION}, "
                f"got {self.lerobot_version!r}"
            )
        if self.genesis_version != EXPECTED_GENESIS_VERSION:
            raise ContractError(
                f"Genesis version must be {EXPECTED_GENESIS_VERSION}, "
                f"got {self.genesis_version!r}"
            )

    # -- identity -----------------------------------------------------------

    def _assert_rocm_identity(self, torch: Any) -> None:
        hip_version = getattr(getattr(torch, "version", None), "hip", None)
        if not hip_version:
            raise ContractError(
                "torch.version.hip is null; a ROCm-enabled PyTorch build is required"
            )
        if not torch.cuda.is_available():
            raise ContractError(
                "torch.cuda is not available; the official AMD Radeon HIP device is required"
            )
        if int(torch.cuda.device_count()) != 1:
            raise ContractError(
                f"expected exactly one HIP device, observed {torch.cuda.device_count()}"
            )
        name = str(torch.cuda.get_device_name(0)).lower()
        if "amd" not in name and "radeon" not in name and "gfx" not in name:
            raise ContractError(
                f"cuda:0 is not an AMD Radeon device: {torch.cuda.get_device_name(0)!r}"
            )

    def _resolve_lerobot_version(self, lerobot: Any) -> str:
        version = getattr(lerobot, "__version__", None)
        if version and version != "unknown":
            return str(version)
        try:
            from importlib.metadata import version as dist_version

            return str(dist_version("lerobot"))
        except Exception as exc:  # noqa: BLE001 - provenance only
            raise ContractError(f"cannot resolve LeRobot version: {exc!r}") from exc

    def _resolve_genesis_version(self) -> str:
        try:
            from importlib.metadata import version as dist_version

            return str(dist_version("genesis-world"))
        except Exception as exc:  # noqa: BLE001 - provenance only
            raise ContractError(f"cannot resolve Genesis version: {exc!r}") from exc

    # -- checkpoint / processors -------------------------------------------

    def _load_policy(self, torch: Any) -> Any:
        from lerobot.policies.act.modeling_act import (  # noqa: WPS433 - lazy
            ACTPolicy,
        )

        try:
            policy = ACTPolicy.from_pretrained(
                str(self._pretrained), local_files_only=True
            )
        except Exception as exc:  # noqa: BLE001 - fail closed
            raise ContractError(
                f"ACTPolicy.from_pretrained failed for {self._pretrained}: {exc!r}"
            ) from exc
        policy.to(self._device)
        policy.eval()
        try:
            parameter_device = str(next(policy.parameters()).device)
        except (StopIteration, AttributeError) as exc:
            raise ContractError("loaded ACT policy exposes no parameter device") from exc
        if parameter_device != "cuda:0":
            raise ContractError(
                f"loaded ACT policy parameters are on {parameter_device}, expected cuda:0"
            )
        return policy

    def _load_processors(self, make_pre_post_processors: Any) -> Any:
        try:
            return make_pre_post_processors(
                policy_cfg=self._policy.config,
                pretrained_path=str(self._pretrained),
            )
        except Exception as exc:  # noqa: BLE001 - fail closed, never recompute stats
            raise ContractError(
                "failed to load the saved checkpoint pre/post processors from "
                f"{self._pretrained}; normalization statistics were not recomputed "
                f"and no fallback was attempted: {exc!r}"
            ) from exc

    def _load_policy_config(self) -> dict[str, Any]:
        import json as _json

        config_path = self._pretrained / "config.json"
        try:
            return _json.loads(config_path.read_text(encoding="utf-8"))
        except (OSError, _json.JSONDecodeError) as exc:
            raise ContractError(f"cannot read policy config {config_path}: {exc!r}") from exc

    def _hash_processor_artifacts(self) -> dict[str, str]:
        hashes: dict[str, str] = {}
        for name in self._required_processor_files:
            path = self._checkpoint_root / name
            hashes[name] = sha256_file(path)
        return hashes

    def _capture_environment_identity(self, torch: Any) -> dict[str, Any]:
        import platform

        return {
            "torch_version": str(torch.__version__),
            "torch_hip_version": str(torch.version.hip),
            "torch_cuda_is_available": bool(torch.cuda.is_available()),
            "torch_cuda_device_count": int(torch.cuda.device_count()),
            "torch_cuda_device_name_0": str(torch.cuda.get_device_name(0)),
            "lerobot_version": self.lerobot_version,
            "genesis_version": self._genesis_version,
            "openloop_admission_contract_sha256": self.openloop_admission_gate_sha256,
            "python_version": platform.python_version(),
            "platform": platform.platform(),
            "offline_env": dict(self._offline_env),
            "backend": self._backend,
        }

    # -- scene construction -------------------------------------------------

    def _build_scene(self) -> None:
        import genesis as gs  # noqa: WPS433 - lazy
        import numpy as np  # noqa: WPS433 - lazy

        from .genesis_smoke import resolve_backend  # noqa: WPS433 - lazy
        from .stack_bowls_env import (  # noqa: WPS433 - lazy
            sample_source_reset_poses,
            validate_genesis_scene_contract,
        )
        from .camera_mounts import genesis_wrist_mounts  # noqa: WPS433 - lazy

        validate_genesis_scene_contract(
            self._scene_contract, self._source_task, self._port
        )
        # The frozen rim-hook probe carries the actuator gains/limits/friction
        # used by the accepted task; the closed loop reuses those constants.
        contract = self._scene_contract["bimanual_rim_hook_probe"]

        dt = float(self._scene_contract["control"]["physics_dt_s"])
        self._dt = dt
        gs.init(
            backend=resolve_backend(gs, self._backend),
            seed=self._seed,
            logging_level="warning",
        )
        self._scene = gs.Scene(
            sim_options=gs.options.SimOptions(dt=dt),
            show_viewer=False,
        )
        self._table = self._scene.add_entity(
            gs.morphs.Plane(
                pos=(0.0, 0.0, float(self._scene_contract["world"]["table_plane_z_m"])),
                fixed=True,
            )
        )
        base = self._scene_contract["world"]["mantis_base"]
        self._robot = self._scene.add_entity(
            gs.morphs.URDF(
                file=str(self._mantis_urdf),
                pos=tuple(base["position_xyz_m"]),
                quat=tuple(base["quaternion_wxyz"]),
                fixed=True,
            )
        )
        reset_poses = sample_source_reset_poses(seed=self._seed)
        self._reset_poses = reset_poses
        self._bowls = {
            pose.name: self._scene.add_entity(
                gs.morphs.URDF(
                    file=str(self._bowl_urdf),
                    pos=pose.position_xyz_m,
                    quat=pose.quaternion_wxyz,
                    fixed=False,
                    merge_fixed_links=False,
                    recompute_inertia=False,
                    file_meshes_are_zup=True,
                ),
                name=pose.name,
            )
            for pose in reset_poses
        }
        # Three cameras: env + two wrist-mounted, sharing the accepted mounts.
        env_mount = self._camera_contract["mounts"]["env_cam"]
        env_pos = np.asarray(env_mount["position_xyz_m"], dtype=float)
        env_forward = np.asarray(env_mount["forward_xyz"], dtype=float)
        self._cameras: dict[str, Any] = {
            "env_cam": self._scene.add_camera(
                res=(320, 240),
                pos=tuple(env_pos),
                lookat=tuple(env_pos + env_forward),
                fov=37.0,
                near=0.1,
                far=100.0,
                GUI=False,
            )
        }
        mounts = genesis_wrist_mounts(self._camera_contract)
        for name in ("left_wrist_cam", "right_wrist_cam"):
            camera = self._scene.add_camera(
                res=(424, 240),
                pos=(0.0, 0.0, 1.0),
                lookat=(0.0, 0.0, 0.0),
                fov=37.0,
                near=0.1,
                far=100.0,
                GUI=False,
            )
            camera.attach(
                self._robot.get_link(mounts[name]["parent"]),
                np.asarray(mounts[name]["offset_T"], dtype=float),
            )
            self._cameras[name] = camera
        self._scene.build()

        # Geom labels for contact diagnostics.
        self._labels: dict[int, str] = {
            int(geom.idx): f"mantis:{geom.link.name}:{_geom_suffix(geom)}"
            for geom in self._robot.geoms
        }
        self._labels.update(
            {int(geom.idx): f"table:{geom.link.name}" for geom in self._table.geoms}
        )
        for pose in reset_poses:
            self._labels.update(
                {
                    int(geom.idx): f"{pose.name}:{geom.link.name}"
                    for geom in self._bowls[pose.name].geoms
                }
            )

        # Allowed proximal collision filter (pelvis/right_shoulder_yaw only).
        self._apply_allowed_collision_filter()

        # Friction and actuator gains/limits from the frozen probe contract.
        for bowl in self._bowls.values():
            bowl.set_friction(float(contract["bowl_friction_coefficient"]))
        for geom in self._robot.geoms:
            if any(
                geom.link.name.startswith(f"{side}_clamp")
                for side in ("left", "right")
            ):
                geom.set_friction(float(contract["finger_friction_coefficient"]))

        self._physical_names = list(self._port["target"]["physical_joint_order"])
        self._virtual_names = list(self._port["target"]["joint_order"])
        self._all_indices = _dof_indices(self._robot, self._physical_names)
        arm_index_set = {
            index
            for side in ("left", "right")
            for index in _dof_indices(
                self._robot,
                [
                    f"{side}_shoulder_pitch_joint",
                    f"{side}_shoulder_roll_joint",
                    f"{side}_shoulder_yaw_joint",
                    f"{side}_elbow_joint",
                    f"{side}_wrist_roll_joint",
                    f"{side}_wrist_pitch_joint",
                    f"{side}_wrist_yaw_joint",
                ],
            )
        }
        self._arm_index_set = arm_index_set
        self._robot.set_dofs_kp(
            [
                float(
                    contract["arm_kp"]
                    if index in arm_index_set
                    else contract["gripper_kp"]
                )
                for index in self._all_indices
            ],
            dofs_idx_local=self._all_indices,
        )
        self._robot.set_dofs_kv(
            [
                float(
                    contract["arm_kv"]
                    if index in arm_index_set
                    else contract["gripper_kv"]
                )
                for index in self._all_indices
            ],
            dofs_idx_local=self._all_indices,
        )
        lower_force = [
            -float(
                contract["arm_force_limit"]
                if index in arm_index_set
                else contract["gripper_force_limit"]
            )
            for index in self._all_indices
        ]
        self._robot.set_dofs_force_range(
            lower_force,
            [-value for value in lower_force],
            dofs_idx_local=self._all_indices,
        )

        # Settle the scene at the open-gripper home pose before the first tick.
        from .genesis_smoke import physical_pose  # noqa: WPS433 - lazy

        open_qpos = np.asarray(physical_pose(self._port, 1.0), dtype=float)
        self._robot.set_qpos(open_qpos)
        self._robot.control_dofs_position(open_qpos, dofs_idx_local=self._all_indices)
        self._sim_step = 0
        for _ in range(25):
            self._scene.step()
            self._sim_step += 1

    def _apply_allowed_collision_filter(self) -> None:
        import numpy as np  # noqa: WPS433 - lazy

        link_a, link_b = ALLOWED_PROXIMAL_COLLISION_LINKS
        geom_ids = {
            link: [int(geom.idx) for geom in self._robot.get_link(link).geoms]
            for link in (link_a, link_b)
        }
        collider = self._scene.rigid_solver.collider
        collision_pair_idx = collider._collider_info.collision_pair_idx.to_numpy()
        filtered: list[dict[str, int]] = []
        for geom_a in geom_ids[link_a]:
            for geom_b in geom_ids[link_b]:
                lower, upper = sorted((geom_a, geom_b))
                original = int(collision_pair_idx[lower, upper])
                if original >= 0:
                    collision_pair_idx[lower, upper] = -1
                    filtered.append(
                        {"geom_a": lower, "geom_b": upper, "original_pair_index": original}
                    )
        collider._collider_info.collision_pair_idx.from_numpy(collision_pair_idx)
        if not filtered:
            raise ContractError(
                "expected pelvis/right-shoulder-yaw collision pair was not active "
                "in the allowed-collision matrix; the proximal filter cannot be "
                "applied and the loop must fail closed rather than silently run "
                "with an unfiltered matrix"
            )
        readback = collider._collider_info.collision_pair_idx.to_numpy()
        for row in filtered:
            if int(readback[row["geom_a"], row["geom_b"]]) != -1:
                raise ContractError("proximal allowed-collision filter readback failed")
        self._allowed_collision_filter = {
            "links": list(ALLOWED_PROXIMAL_COLLISION_LINKS),
            "filtered_pair_entries": filtered,
        }

    # -- protocol surface ---------------------------------------------------

    def reset_policy_state(self) -> None:
        reset = getattr(self._policy, "reset", None)
        if callable(reset):
            reset()

    def observe(self, policy_step: int) -> Observation:
        from .gripper import project_physical_to_virtual  # noqa: WPS433 - lazy

        physical = _read_dofs(self._robot, self._all_indices)
        # Gripper state contract v2: live readback uses the bounded symmetric
        # projection (mean of clamped per-finger estimates with the residual
        # reported), not the strict physical_to_virtual that rejects on
        # asymmetry, because contact asymmetry is expected and audited.  The
        # strict per-finger [0, 1] domain gate still fails closed on
        # non-finite or out-of-domain fingers; the spread is recorded, not
        # hidden.
        projection = project_physical_to_virtual(
            physical,
            self._port,
            allow_unverified=True,
            range_tolerance=self._gripper_readback_range_tolerance,
        )
        state = [float(value) for value in projection.vector]
        self._gripper_diagnostics_history.append(
            {
                "policy_step": int(policy_step),
                "range_tolerance_normalized": (
                    self._gripper_readback_range_tolerance
                ),
                "grippers": [
                    {
                        "virtual_name": gripper.virtual_name,
                        "physical_names": list(gripper.physical_names),
                        "estimates": [float(value) for value in gripper.estimates],
                        "projected_mean": float(gripper.projected_mean),
                        "spread": float(gripper.spread),
                    }
                    for gripper in projection.grippers
                ],
            }
        )
        # Render each camera exactly once for this policy step and cache the
        # arrays; inference consumes exactly these arrays (no re-render).
        arrays = render_observation_arrays(
            self._cameras,
            policy_step=policy_step,
            cache=self._observation_cache,
        )
        images = {
            feature: hwc_to_chw_summary(array) for feature, array in arrays.items()
        }
        return Observation(
            global_index=int(policy_step),
            episode_index=0,
            offset=int(policy_step),
            state=state,
            images=images,
        )

    def infer(
        self, observation: Observation, policy_step: int
    ) -> tuple[list[float], float | None]:
        import time as _time  # noqa: WPS433 - lazy

        torch = self._torch
        # Consume exactly the arrays rendered by observe() for this policy step.
        # Inference never re-renders: a second render would sample the cameras at
        # a different physics state than the observation the policy is replying
        # to, breaking the causal observe->infer contract.
        arrays = consume_cached_arrays(
            self._observation_cache, policy_step=policy_step
        )
        tensors = {
            feature: (
                torch.from_numpy(array.transpose(2, 0, 1).astype("float32") / 255.0)
                .to(self._device)
                .unsqueeze(0)
            )
            for feature, array in arrays.items()
        }
        state_tensor = torch.tensor(
            [float(value) for value in observation.state],
            dtype=torch.float32,
            device=self._device,
        ).unsqueeze(0)
        preprocessed = self._processors[0](
            {"observation.state": state_tensor, **tensors}
        )
        postprocessor = self._processors[1]
        with torch.inference_mode():
            if torch.cuda.is_available():
                torch.cuda.synchronize()
            start = _time.perf_counter()
            action = self._policy.select_action(preprocessed)
            if torch.cuda.is_available():
                torch.cuda.synchronize()
            elapsed = _time.perf_counter() - start
        postprocessed = postprocessor(action)
        shape = tuple(int(dim) for dim in postprocessed.shape)
        expected = int(self._gate["observation_contract"]["action_dimension"])
        if shape != (1, expected):
            raise ContractError(
                f"postprocessed ACT action shape is {shape}, expected (1, {expected})"
            )
        vector = postprocessed[0].detach().to("cpu").tolist()
        return [float(component) for component in vector], elapsed * 1000.0

    def apply_target(
        self,
        physical_target_18d: Sequence[float],
        *,
        policy_step: int,
        physics_step: int,
        physics_steps_to_hold: int,
    ) -> None:
        import numpy as np  # noqa: WPS433 - lazy

        target = np.asarray(
            [float(value) for value in physical_target_18d], dtype=float
        )
        self._robot.control_dofs_position(target, dofs_idx_local=self._all_indices)
        for _ in range(max(1, int(physics_steps_to_hold))):
            self._scene.step()
            self._sim_step += 1

    def sample_safety(self, policy_step: int) -> SafetySignals:
        physics_step = int(self._sim_step)
        # Robot-table contact is always forbidden.
        table_contacts = _contact_pairs(
            self._robot.get_contacts(with_entity=self._table), self._labels
        )
        # Self contacts are forbidden except the single allowed proximal pair
        # (pelvis/right_shoulder_yaw) and same-side clamp-to-clamp finger
        # contact, matching the accepted scripted runner's _self_contact_pairs.
        self_contacts = [
            pair
            for pair in _contact_pairs(self._robot.get_contacts(), self._labels)
            if all(_is_robot_label(label) for label in _pair_labels(pair))
            and not _is_allowed_proximal_pair(pair)
            and not _is_same_side_clamp_pair(pair)
        ]
        # Robot-bowl contact is allowed only when every robot geometry in the
        # contact pair is a left/right clamp link (grasping).  Any non-clamp
        # robot link touching a bowl is a forbidden collision.  This uses only
        # the contact-pair geometry labels -- never stage, object pose, action,
        # or any policy-visible privileged state.
        bowl_contacts: list[str] = []
        for bowl in self._bowls.values():
            for pair in _contact_pairs(
                self._robot.get_contacts(with_entity=bowl), self._labels
            ):
                if _is_clamp_robot_bowl_pair(pair):
                    continue
                bowl_contacts.append(pair)
        positions = self._bowl_positions()
        finite = all(
            math.isfinite(component)
            for position in positions
            for component in position
        )
        return SafetySignals(
            physics_step=physics_step,
            finite=finite,
            robot_table_contact=bool(table_contacts),
            robot_self_contact=bool(self_contacts),
            forbidden_collision_pairs=tuple(
                table_contacts + self_contacts + bowl_contacts
            ),
            workspace_violations=(),
        )

    def sample_evaluator(self, policy_step: int) -> EvaluatorFrame:
        import numpy as np  # noqa: WPS433 - lazy

        positions = [np.asarray(pos, dtype=float) for pos in self._bowl_positions()]
        quaternions = [np.asarray(q, dtype=float) for q in self._bowl_quaternions()]
        elapsed_steps = max(1, self._sim_step - self._previous_physics_step)
        elapsed_s = elapsed_steps * self._dt
        if self._previous_positions is None:
            linear = [[0.0, 0.0, 0.0] for _ in positions]
            angular = [[0.0, 0.0, 0.0] for _ in positions]
        else:
            linear = [
                ((positions[i] - self._previous_positions[i]) / elapsed_s).tolist()
                for i in range(len(positions))
            ]
            angular = [
                _angular_velocity(self._previous_quaternions[i], quaternions[i], elapsed_s)
                for i in range(len(positions))
            ]
        self._previous_positions = positions
        self._previous_quaternions = quaternions
        self._previous_physics_step = self._sim_step
        return EvaluatorFrame(
            positions_xyz_m=tuple(tuple(float(c) for c in pos) for pos in positions),
            linear_velocities_m_s=tuple(tuple(float(c) for c in v) for v in linear),
            angular_velocities_rad_s=tuple(tuple(float(c) for c in v) for v in angular),
            left_gripper_open_fraction=self._gripper_open_fraction("left"),
            right_gripper_open_fraction=self._gripper_open_fraction("right"),
        )

    # -- small privileged helpers ------------------------------------------

    def _bowl_positions(self) -> list[list[float]]:
        return [_vector(bowl.get_pos()) for bowl in self._bowls.values()]

    def _bowl_quaternions(self) -> list[list[float]]:
        return [_vector(bowl.get_quat()) for bowl in self._bowls.values()]

    def _gripper_open_fraction(self, side: str) -> float:
        qpos = dict(zip(self._physical_names, _read_dofs(self._robot, self._all_indices)))
        mapping = self._port["assets"]["virtual_gripper_mapping"]
        virtual_name = f"{side}_gripper_joint"
        values: list[float] = []
        for joint_name, coefficient in mapping["coefficients"][virtual_name].items():
            offset = float(mapping["offsets"][virtual_name][joint_name])
            values.append((float(qpos[joint_name]) - offset) / float(coefficient))
        return float(sum(values) / len(values))


# ---------------------------------------------------------------------------
# Local Genesis/torch helpers (numpy imported lazily where used).
# ---------------------------------------------------------------------------


def _geom_suffix(geom: Any) -> str:
    metadata = getattr(geom, "metadata", {})
    metadata = metadata if isinstance(metadata, dict) else {}
    suffix = metadata.get("name")
    if suffix:
        return str(suffix)
    if metadata.get("mesh_path"):
        return "source_mesh_collision"
    return f"anonymous_{getattr(getattr(geom, 'type', None), 'name', 'geom')}"


def _vector(value: Any) -> list[float]:
    import numpy as np  # noqa: WPS433 - lazy

    if hasattr(value, "detach"):
        value = value.detach()
    if hasattr(value, "cpu"):
        value = value.cpu()
    if hasattr(value, "numpy"):
        value = value.numpy()
    return np.asarray(value, dtype=float).reshape(-1).tolist()


def _rgb_array(rendered: Any) -> Any:
    import numpy as np  # noqa: WPS433 - lazy

    if isinstance(rendered, dict):
        rendered = rendered.get("rgb")
    elif isinstance(rendered, (tuple, list)):
        rendered = rendered[0]
    if hasattr(rendered, "detach"):
        rendered = rendered.detach()
    if hasattr(rendered, "cpu"):
        rendered = rendered.cpu()
    if hasattr(rendered, "numpy"):
        rendered = rendered.numpy()
    array = np.asarray(rendered)
    if array.ndim == 4 and array.shape[0] == 1:
        array = array[0]
    if array.ndim != 3 or array.shape[2] not in (3, 4):
        raise ContractError(f"unexpected Genesis RGB shape: {array.shape}")
    if array.dtype.kind == "f":
        array = np.clip(array, 0.0, 1.0) * 255.0
    return array[:, :, :3].astype(np.uint8)


#: The exact frozen three-camera observation features, in declared order.  Each
#: feature maps to one Genesis camera named by its trailing segment.
OBSERVATION_IMAGE_FEATURES = (
    "observation.images.env_cam",
    "observation.images.left_wrist_cam",
    "observation.images.right_wrist_cam",
)


def _camera_name(feature: str) -> str:
    return str(feature).split(".")[-1]


def render_observation_arrays(
    cameras: Any,
    *,
    policy_step: int,
    cache: dict[str, Any],
    feature_names: Sequence[str] = OBSERVATION_IMAGE_FEATURES,
) -> dict[str, Any]:
    """Render each camera exactly once and cache the arrays for one policy step.

    The returned dict maps each feature name to its HWC ``uint8`` array.  The
    same arrays are stashed in ``cache`` (keyed by ``policy_step``) so
    :func:`consume_cached_arrays` can hand them to inference without a second
    render.  A causal loop renders each camera exactly once per policy tick.
    """

    arrays: dict[str, Any] = {}
    for feature in feature_names:
        camera = cameras[_camera_name(feature)]
        arrays[str(feature)] = _rgb_array(camera.render(rgb=True, force_render=True))
    cache["policy_step"] = int(policy_step)
    cache["arrays"] = arrays
    return arrays


def hwc_to_chw_summary(array: Any) -> TensorSummary:
    """Build a channel-first ``TensorSummary`` from an HWC ``uint8`` array.

    Genesis hands back HWC imagery; the frozen observation contract is CHW, so
    the summary shape is reported as ``(C, H, W)``.  Values are normalised to
    ``[0, 1]`` for the range check.
    """

    import numpy as np  # noqa: WPS433 - lazy

    ndarray = np.asarray(array)
    if ndarray.ndim != 3 or ndarray.shape[2] not in (3, 4):
        raise ContractError(f"unexpected HWC image shape: {ndarray.shape}")
    channels, height, width = int(ndarray.shape[2]), int(ndarray.shape[0]), int(ndarray.shape[1])
    return TensorSummary(
        shape=(channels, height, width),
        finite=bool(np.isfinite(ndarray).all()),
        min_value=float(ndarray.min()) / 255.0,
        max_value=float(ndarray.max()) / 255.0,
    )


def consume_cached_arrays(
    cache: dict[str, Any],
    *,
    policy_step: int,
    feature_names: Sequence[str] = OBSERVATION_IMAGE_FEATURES,
) -> dict[str, Any]:
    """Return the arrays cached for ``policy_step``, rejecting stale/missing cache.

    Inference must consume exactly the arrays rendered for the same policy step.
    A missing cache (observe never ran) or a stale cache (a different step) is a
    causal-loop contract violation and fails closed; this routine never renders.
    """

    arrays = cache.get("arrays")
    cached_step = cache.get("policy_step")
    if arrays is None or cached_step != int(policy_step):
        raise ContractError(
            f"stale or missing observation cache for policy step {policy_step} "
            f"(cached_step={cached_step!r}); inference must consume the arrays "
            f"rendered by observe() for the same policy step"
        )
    missing = [str(name) for name in feature_names if name not in arrays]
    if missing:
        raise ContractError(f"observation cache is missing arrays: {missing}")
    return {str(name): arrays[name] for name in feature_names}


def _dof_indices(robot: Any, names: Sequence[str]) -> list[int]:
    indices: list[int] = []
    for name in names:
        values = _vector(robot.get_joint(name).dofs_idx_local)
        if len(values) != 1:
            raise ContractError(f"expected one DOF for {name}, got {values}")
        indices.append(int(values[0]))
    return indices


def _read_dofs(robot: Any, indices: Sequence[int]) -> list[float]:
    try:
        return _vector(robot.get_dofs_position(dofs_idx_local=list(indices)))
    except TypeError:
        return _vector(robot.get_dofs_position(list(indices)))


def _contact_pairs(contact_info: Any, labels: dict[int, str]) -> list[str]:
    if not isinstance(contact_info, dict) or "geom_a" not in contact_info:
        raise ContractError(
            "Genesis get_contacts returned an unexpected structure; refusing to "
            "treat an unknown contact payload as zero contacts"
        )
    pairs: list[str] = []
    for geom_a, geom_b in zip(
        _vector(contact_info["geom_a"]), _vector(contact_info["geom_b"])
    ):
        pair = sorted(
            (
                labels.get(int(geom_a), f"geom:{int(geom_a)}"),
                labels.get(int(geom_b), f"geom:{int(geom_b)}"),
            )
        )
        pairs.append(" <> ".join(pair))
    return pairs


def _pair_labels(pair: str) -> list[str]:
    return pair.split(" <> ")


def _is_allowed_proximal_pair(pair: str) -> bool:
    """True only for exactly one pelvis_link plus one right_shoulder_yaw_link.

    Token order is irrelevant (the contact pair is sorted into label order
    elsewhere); what matters is that one geometry carries ``pelvis_link`` and
    the other carries ``right_shoulder_yaw_link``.  Any other combination --
    both the same link, neither, or an unrecognised token -- is not the single
    filtered proximal pair and stays an active collision.
    """

    tokens = _pair_labels(pair)
    if len(tokens) != 2:
        return False
    matched: set[str] = set()
    for token in tokens:
        carriers = [link for link in ALLOWED_PROXIMAL_COLLISION_LINKS if link in token]
        if len(carriers) != 1:
            return False
        matched.add(carriers[0])
    return matched == set(ALLOWED_PROXIMAL_COLLISION_LINKS)


def _is_robot_label(label: str) -> bool:
    return label.startswith("mantis:")


def _is_table_label(label: str) -> bool:
    return label.startswith("table:")


def _is_clamp_label(label: str) -> bool:
    """True for left/right clamp robot geometries (the grasping fingers)."""

    return any(label.startswith(f"mantis:{side}_clamp") for side in ("left", "right"))


def _is_same_side_clamp_pair(pair: str) -> bool:
    """True for a same-side left/left or right/right clamp-to-clamp self contact.

    Mirrors the accepted scripted runner's ``_self_contact_pairs`` exclusion:
    a pair of clamp geometries on the same hand is expected finger-on-finger
    contact and is not a forbidden self collision.
    """

    labels = _pair_labels(pair)
    if not all(_is_robot_label(label) for label in labels):
        return False
    return any(
        all(label.startswith(f"mantis:{side}_clamp") for label in labels)
        for side in ("left", "right")
    )


def _is_clamp_robot_bowl_pair(pair: str) -> bool:
    """True when every robot geometry in a robot-bowl contact is a clamp link.

    Grasping is performed by the clamp fingers, so a clamp-to-bowl contact is
    allowed.  Any other robot link (arm, wrist, base) touching a bowl is a
    forbidden collision.  This classification uses only the contact-pair
    geometry labels -- never stage, object pose, action, or any policy-visible
    privileged state.
    """

    labels = _pair_labels(pair)
    robot_labels = [label for label in labels if _is_robot_label(label)]
    other_labels = [
        label for label in labels if not _is_robot_label(label) and not _is_table_label(label)
    ]
    if not robot_labels or not other_labels:
        return False
    return all(_is_clamp_label(label) for label in robot_labels)


def _angular_velocity(
    previous_quaternion: Any,
    quaternion: Any,
    elapsed_s: float,
) -> list[float]:
    import numpy as np  # noqa: WPS433 - lazy

    q0 = np.asarray(previous_quaternion, dtype=float)
    q1 = np.asarray(quaternion, dtype=float)
    q0 /= np.linalg.norm(q0)
    q1 /= np.linalg.norm(q1)
    relative = np.asarray(
        [
            q1[0] * q0[0] + np.dot(q1[1:], q0[1:]),
            -q1[0] * q0[1] + q0[0] * q1[1] - q1[2] * q0[3] + q1[3] * q0[2],
            -q1[0] * q0[2] + q0[0] * q1[2] - q1[3] * q0[1] + q1[1] * q0[3],
            -q1[0] * q0[3] + q0[0] * q1[3] - q1[1] * q0[2] + q1[2] * q0[1],
        ],
        dtype=float,
    )
    if relative[0] < 0.0:
        relative *= -1.0
    vector_norm = float(np.linalg.norm(relative[1:]))
    if vector_norm < 1e-12:
        return [0.0, 0.0, 0.0]
    angle = 2.0 * math.atan2(vector_norm, min(1.0, max(-1.0, relative[0])))
    axis = relative[1:] / vector_norm
    return (axis * (angle / elapsed_s)).tolist()
