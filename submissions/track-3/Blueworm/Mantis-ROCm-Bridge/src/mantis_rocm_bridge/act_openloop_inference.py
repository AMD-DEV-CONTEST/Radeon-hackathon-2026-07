"""Deterministic, fail-closed ACT open-loop inference gate.

This module implements the dependency-isolated core of the ACT open-loop
inference phase contract (``docs/AMD_ACT_OPENLOOP_INFERENCE_GATE.md``).  It
selects the first, midpoint, and last frame of every dataset episode, validates
the 16D state / 16D action / three CHW camera observation contract, applies the
frozen checkpoint pre/post processors, expands the 16D policy action to the 18D
simulation target through gripper contract v2, and enforces every fixed-base
physical joint limit.

The heavy runtime dependencies (``torch`` / ``numpy`` / ``lerobot`` / ``PIL`` /
``torchvision`` / ``Genesis``) live entirely behind the
:class:`InferenceRuntime` protocol, so :func:`run_open_loop_inference` is pure
Python and runs under the CPU-only unit tests against a tiny in-memory double.
Nothing in this module imports those packages at module import time.

A passing receipt proves only local open-loop gate logic and - on the official
AMD run - checkpoint / processor / observation / action / ROCm interoperability.
It never proves closed-loop control or task performance (see ``claim_boundary``).
"""

from __future__ import annotations

import hashlib
import json
import math
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Protocol, Sequence, runtime_checkable

from .contracts import ContractError
from .gripper import virtual_to_physical

#: The LeRobot version the frozen checkpoint and saved processors were produced
#: with, and the version this gate runs under on the official AMD worker.  This
#: is a *compatibility expectation* about the official runtime, not a local claim.
EXPECTED_LEROBOT_VERSION = "0.4.4"

#: Environment variables that must be set *before* LeRobot / transformers /
#: huggingface_hub are imported so a missing local file can never fall through to
#: a network download.  Mirrors ``sample_decode_gate.OFFLINE_ENV_FLAGS``.
OFFLINE_ENV_FLAGS: dict[str, str] = {
    "HF_HUB_OFFLINE": "1",
    "HF_DATASETS_OFFLINE": "1",
    "TRANSFORMERS_OFFLINE": "1",
}

#: The exact artifact files the CLI must publish with exclusive no-overwrite.
OUTPUT_ARTIFACTS = (
    "started.json",
    "actions.jsonl",
    "receipt.json",
    "status",
    "SHA256SUMS",
)


# ---------------------------------------------------------------------------
# Pure data containers shared by the runtime adapter and the audit core.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class TensorSummary:
    """Channel-first image summary sufficient for the open-loop contract."""

    shape: tuple[int, int, int]
    finite: bool
    min_value: float = 0.0
    max_value: float = 1.0


@dataclass(frozen=True)
class Observation:
    """One audited observation handed to the core by an :class:`InferenceRuntime`."""

    global_index: int
    episode_index: int
    offset: int
    state: list[float]
    images: dict[str, TensorSummary]


@dataclass(frozen=True)
class SampleResult:
    """Per-sample outcome for the receipt."""

    global_index: int
    episode_index: int
    offset: int
    action: list[float]
    projected_action: list[float]
    saturated_action_indices: list[int]
    saturation_max_abs_delta: float
    raw_physical: list[float]
    physical: list[float]
    saturated_physical_joint_names: list[str]
    physical_saturation_max_abs_delta: float
    preprojection_joint_limit_issues: list[str]
    observation_valid: bool
    action_finite: bool
    safety_pass: bool
    joint_limit_issues: list[str]
    issues: list[str]
    latency_ms: float | None


@runtime_checkable
class InferenceRuntime(Protocol):
    """Minimal, decode + infer view of the local LeRobot + ACT runtime.

    Implementations hold the torch / lerobot dependencies; the core only consumes
    the values below, so a test double satisfies the protocol without any of
    those packages installed.  ``reset_policy_state`` must be called between
    independent samples so episodic policy buffers do not leak across samples.
    """

    lerobot_version: str
    policy_device: str
    policy_device_index: str
    hip_device_count: int
    policy_config: dict[str, Any]
    processor_artifact_hashes: dict[str, str]
    environment_identity: dict[str, Any]
    input_hashes: dict[str, str]

    def episode_bounds(self) -> dict[int, tuple[int, int]]:
        """Return ``episode_index -> (first_global_index, frame_length)``."""

    def observe(self, global_index: int) -> Observation:
        """Decode and preprocess one observation by its global dataset index."""

    def reset_policy_state(self) -> None:
        """Reset ACT policy episodic state between independent samples."""

    def infer(self, observation: Observation) -> tuple[list[float], float | None]:
        """Run ACT under ``torch.inference_mode`` on ``cuda:0`` and return one
        finite 16D postprocessed action plus a descriptive latency in
        milliseconds (or raise :class:`ContractError``)."""


# ---------------------------------------------------------------------------
# Deterministic sampling.
# ---------------------------------------------------------------------------


def sample_offsets(length: int) -> list[int]:
    """Return the deduplicated first / midpoint / last intra-episode offsets.

    ``midpoint = length // 2`` is the lower median index; for length 1 it
    collapses to ``[0]`` and for length 2 to ``[0, 1]``.  Ordering and
    deduplication are preserved so a short episode samples exactly once or twice.
    """

    if length <= 0:
        return []
    offsets: list[int] = []
    for value in (0, length // 2, length - 1):
        if value not in offsets:
            offsets.append(value)
    return offsets


def select_samples(
    bounds: dict[int, tuple[int, int]],
    *,
    expected_episodes: int,
    expected_distinct_samples: int,
) -> list[tuple[int, int, int]]:
    """Deterministically select first / midpoint / last of every episode.

    Returns a list of ``(episode_index, global_index, offset)`` tuples in episode
    then offset order.  Fails closed on a non-contiguous 0-based episode range,
    a duplicate global index, or any mismatch with the configured episode /
    distinct-sample counts.  The current four-episode dataset yields exactly
    twelve distinct samples.
    """

    episodes = sorted(bounds)
    if not episodes:
        raise ContractError("open-loop inference gate observed no episodes")
    if episodes != list(range(0, len(episodes))):
        raise ContractError(
            f"episode indices must be contiguous from 0; got {episodes}"
        )
    if len(episodes) != expected_episodes:
        raise ContractError(
            f"expected {expected_episodes} episodes, observed {len(episodes)}"
        )

    selected: list[tuple[int, int, int]] = []
    seen: set[int] = set()
    for episode in episodes:
        first_global, length = bounds[episode]
        if length <= 0:
            raise ContractError(f"episode {episode} has non-positive length {length}")
        for offset in sample_offsets(length):
            global_index = first_global + offset
            if global_index in seen:
                raise ContractError(
                    f"duplicate global index {global_index} selected "
                    f"(episode {episode}, offset {offset})"
                )
            seen.add(global_index)
            selected.append((episode, global_index, offset))

    if len(selected) != expected_distinct_samples:
        raise ContractError(
            f"expected {expected_distinct_samples} distinct samples, "
            f"selected {len(selected)}"
        )
    if len(seen) != expected_distinct_samples:
        raise ContractError(
            f"expected {expected_distinct_samples} distinct global indices, "
            f"got {len(seen)}"
        )
    return selected


# ---------------------------------------------------------------------------
# Contract validation.
# ---------------------------------------------------------------------------


def _is_chw_shape(shape: Any, expected: Sequence[int]) -> bool:
    return (
        isinstance(shape, (list, tuple))
        and len(shape) == len(expected)
        and all(int(part) == int(expected_part) for part, expected_part in zip(shape, expected))
    )


def validate_config(gate: dict[str, Any]) -> None:
    """Validate the static open-loop inference gate contract."""

    if gate.get("schema_version") != 1:
        raise ContractError("open-loop inference gate schema_version must be 1")
    for required in ("gate_id", "task_id", "protocol", "training_id"):
        if not isinstance(gate.get(required), str) or not gate[required]:
            raise ContractError(f"open-loop inference gate {required} must be a non-empty string")

    sampling = gate.get("sampling")
    if not isinstance(sampling, dict):
        raise ContractError("open-loop inference gate sampling must be an object")
    if sampling.get("episodes") != 4:
        raise ContractError("open-loop inference gate sampling.episodes must be 4")
    if sampling.get("samples_per_episode") != 3:
        raise ContractError(
            "open-loop inference gate sampling.samples_per_episode must be 3"
        )
    if sampling.get("expected_distinct_samples") != 12:
        raise ContractError(
            "open-loop inference gate sampling.expected_distinct_samples must be 12"
        )
    if sampling.get("offset_rule") != (
        "first (0), midpoint (length // 2), last (length - 1), deduplicated within an episode"
    ):
        raise ContractError("open-loop inference gate sampling.offset_rule changed")
    if gate.get("sample_phase") != "first_mid_last":
        raise ContractError("open-loop inference gate sample_phase must be first_mid_last")

    dimensions = gate.get("dimensions")
    if not isinstance(dimensions, dict):
        raise ContractError("open-loop inference gate dimensions must be an object")
    if dimensions.get("state_dimension") != 16:
        raise ContractError("open-loop inference gate state_dimension must be 16")
    if dimensions.get("action_dimension") != 16:
        raise ContractError("open-loop inference gate action_dimension must be 16")
    if dimensions.get("physical_joint_count") != 18:
        raise ContractError("open-loop inference gate physical_joint_count must be 18")

    policy = gate.get("policy")
    if not isinstance(policy, dict):
        raise ContractError("open-loop inference gate policy must be an object")
    if policy.get("chunk_size") != 30 or policy.get("n_action_steps") != 30:
        raise ContractError("open-loop inference gate chunk_size and n_action_steps must be 30")

    policy_output = gate.get("policy_output")
    if not isinstance(policy_output, dict) or policy_output.get("kind") != (
        "absolute_joint_position_target"
    ) or policy_output.get("control_hz") != 30 or policy_output.get("not_delta_action") is not True:
        raise ContractError(
            "open-loop inference gate policy_output must be an absolute 30 Hz joint-position target"
        )

    image_features = gate.get("image_features")
    expected_image_features = {
        "observation.images.env_cam": [3, 240, 320],
        "observation.images.left_wrist_cam": [3, 240, 424],
        "observation.images.right_wrist_cam": [3, 240, 424],
    }
    if image_features != expected_image_features:
        raise ContractError("open-loop inference gate image_features shapes changed")

    gripper = gate.get("gripper_contract")
    if not isinstance(gripper, dict):
        raise ContractError("open-loop inference gate gripper_contract must be an object")
    if gripper.get("version") != "v2":
        raise ContractError("open-loop inference gate gripper_contract.version must be v2")
    if gripper.get("virtual_convention") != {"0": "closed", "1": "open"}:
        raise ContractError("open-loop inference gate virtual gripper convention changed")
    if gripper.get("hardware_mapping_status") != "sim_verified_hardware_unverified":
        raise ContractError("open-loop inference gate hardware gripper mapping status changed")
    if gripper.get("allow_unverified_only_for") != "genesis_simulation_projection":
        raise ContractError(
            "open-loop inference gate allow_unverified is restricted to the Genesis simulation projection"
        )
    if gripper.get("simulation_only") is not True:
        raise ContractError("open-loop inference gate gripper projection must be simulation only")
    if gripper.get("no_action_sent_to_genesis_or_hardware") is not True:
        raise ContractError("open-loop inference gate must not send actions to Genesis or hardware")

    projection = gate.get("gripper_output_projection")
    if projection is not None:
        if gate.get("gate_id") not in {
            "mantis_act_openloop_inference_v2",
            "mantis_act_openloop_inference_v3",
        }:
            raise ContractError(
                "gripper output projection is restricted to versioned v2/v3 gates"
            )
        expected_projection = {
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
        if projection != expected_projection:
            raise ContractError(
                "open-loop inference gate gripper_output_projection changed"
            )

    physical_projection = gate.get("physical_joint_output_projection")
    if physical_projection is not None:
        if gate.get("gate_id") != "mantis_act_openloop_inference_v3":
            raise ContractError(
                "physical joint output projection is restricted to the versioned v3 gate"
            )
        expected_physical_projection = {
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
        if physical_projection != expected_physical_projection:
            raise ContractError(
                "open-loop inference gate physical_joint_output_projection changed"
            )

    processors = gate.get("saved_processor_requirements")
    if not isinstance(processors, dict):
        raise ContractError("open-loop inference gate saved_processor_requirements must be an object")
    required_files = processors.get("required_files")
    if not isinstance(required_files, list) or not required_files:
        raise ContractError(
            "open-loop inference gate saved_processor_requirements.required_files must be a non-empty list"
        )
    # The official 60000-step checkpoint stores its saved LeRobot 0.4.4 processor
    # state under step-indexed safetensors files; the generic
    # policy_preprocessor.safetensors / policy_postprocessor.safetensors names
    # do not exist and must never be required.
    expected_processor_files = {
        "pretrained_model/config.json",
        "pretrained_model/model.safetensors",
        "pretrained_model/policy_preprocessor.json",
        "pretrained_model/policy_preprocessor_step_3_normalizer_processor.safetensors",
        "pretrained_model/policy_postprocessor.json",
        "pretrained_model/policy_postprocessor_step_0_unnormalizer_processor.safetensors",
    }
    if set(str(name) for name in required_files) != expected_processor_files:
        raise ContractError(
            "open-loop inference gate saved_processor_requirements.required_files must be exactly "
            f"{sorted(expected_processor_files)}"
        )
    for forbidden in (
        "pretrained_model/policy_preprocessor.safetensors",
        "pretrained_model/policy_postprocessor.safetensors",
    ):
        if forbidden in required_files:
            raise ContractError(
                f"open-loop inference gate must not require the nonexistent generic {forbidden}"
            )
    if processors.get("must_use_saved_processors") is not True:
        raise ContractError("open-loop inference gate must use the saved processors")
    if processors.get("must_not_recompute_normalization_statistics") is not True:
        raise ContractError(
            "open-loop inference gate must not recompute dataset normalization statistics"
        )
    processor_loader = processors.get("processor_loader")
    if not isinstance(processor_loader, str) or not processor_loader:
        raise ContractError(
            "open-loop inference gate saved_processor_requirements.processor_loader must be a string"
        )
    if "lerobot.policies.factory.make_pre_post_processors" not in processor_loader:
        raise ContractError(
            "open-loop inference gate processor_loader must use "
            "lerobot.policies.factory.make_pre_post_processors"
        )
    if "policy_cfg=policy.config" not in processor_loader:
        raise ContractError(
            "open-loop inference gate processor_loader must pass policy_cfg=policy.config"
        )
    if "pretrained_path" not in processor_loader:
        raise ContractError(
            "open-loop inference gate processor_loader must point pretrained_path at the local pretrained_model"
        )
    if "no fallback" not in processor_loader.lower() and "never recomputed" not in processor_loader.lower():
        raise ContractError(
            "open-loop inference gate processor_loader must forbid stat recomputation and fallback"
        )

    if gate.get("offline_flags") != OFFLINE_ENV_FLAGS:
        raise ContractError("open-loop inference gate offline_flags changed")

    identity = gate.get("required_runtime_identity")
    if not isinstance(identity, dict):
        raise ContractError("open-loop inference gate required_runtime_identity must be an object")
    if identity.get("lerobot_version") != EXPECTED_LEROBOT_VERSION:
        raise ContractError(
            f"open-loop inference gate required_runtime_identity.lerobot_version must be "
            f"{EXPECTED_LEROBOT_VERSION}"
        )
    if identity.get("policy_device") != "cuda" or identity.get("policy_device_index") != "cuda:0":
        raise ContractError("open-loop inference gate policy device must be cuda:0")
    if identity.get("hip_device_count") != 1:
        raise ContractError("open-loop inference gate must require exactly one HIP device")

    if gate.get("fixed_joint_limit_source") != "configs/fixed-base-plan.json":
        raise ContractError("open-loop inference gate fixed_joint_limit_source changed")

    if sorted(gate.get("output_artifacts", [])) != sorted(OUTPUT_ARTIFACTS):
        raise ContractError("open-loop inference gate output_artifacts changed")

    descriptive = gate.get("descriptive_only_measurements")
    if (
        not isinstance(descriptive, dict)
        or descriptive.get("never_a_pass_threshold") is not True
        or descriptive.get("never_a_comparative_performance_claim") is not True
    ):
        raise ContractError(
            "open-loop inference gate latency / utilization / error / loss must be descriptive only"
        )

    boundary = gate.get("claim_boundary")
    if not isinstance(boundary, dict):
        raise ContractError("open-loop inference gate claim_boundary must be an object")
    for flag in (
        "open_loop_interoperability_only",
        "proves_policy_convergence",
        "proves_closed_loop_control",
        "proves_task_success",
        "proves_generalization",
        "proves_robustness",
        "proves_real_robot_safety",
        "proves_amd_performance_advantage",
    ):
        if flag not in boundary:
            raise ContractError(f"open-loop inference gate claim_boundary missing {flag}")
    if boundary["open_loop_interoperability_only"] is not True:
        raise ContractError("open-loop inference gate claim_boundary must be interoperability only")
    for negative in (
        "proves_policy_convergence",
        "proves_closed_loop_control",
        "proves_task_success",
        "proves_generalization",
        "proves_robustness",
        "proves_real_robot_safety",
        "proves_amd_performance_advantage",
    ):
        if boundary[negative] is not False:
            raise ContractError(
                f"open-loop inference gate claim_boundary {negative} must be false"
            )
    if not isinstance(boundary.get("statement"), str) or not boundary["statement"]:
        raise ContractError("open-loop inference gate claim_boundary.statement must be present")


# ---------------------------------------------------------------------------
# Observation / action / safety validation (pure).
# ---------------------------------------------------------------------------


def _finite_vector(value: Any, dimension: int) -> list[float] | None:
    if hasattr(value, "tolist"):
        value = value.tolist()
    if not isinstance(value, (list, tuple)) or len(value) != dimension:
        return None
    try:
        result = [float(component) for component in value]
    except (TypeError, ValueError):
        return None
    return result if all(math.isfinite(component) for component in result) else None


def validate_observation(
    observation: Observation,
    *,
    image_features: dict[str, Sequence[int]],
    state_dimension: int,
    image_value_range: Sequence[float] = (0.0, 1.0),
) -> list[str]:
    """Return a list of issues for one observation (empty when valid)."""

    issues: list[str] = []
    state = _finite_vector(observation.state, state_dimension)
    if state is None:
        issues.append(
            f"invalid_state:{observation.episode_index}:{observation.offset}"
        )
    for feature, expected_shape in image_features.items():
        image = observation.images.get(feature)
        if image is None:
            issues.append(
                f"image_missing:{feature}:{observation.episode_index}:{observation.offset}"
            )
            continue
        if not _is_chw_shape(image.shape, expected_shape):
            issues.append(
                f"image_shape_mismatch:{feature}:{observation.episode_index}:{observation.offset}"
            )
        if not image.finite:
            issues.append(
                f"image_not_finite:{feature}:{observation.episode_index}:{observation.offset}"
            )
        lower, upper = (float(part) for part in image_value_range)
        if image.min_value < lower or image.max_value > upper:
            issues.append(
                f"image_value_out_of_range:{feature}:{observation.episode_index}:"
                f"{observation.offset}:{image.min_value}:{image.max_value}"
            )
    return issues


def validate_interface_contract(
    interface: dict[str, Any] | None,
    *,
    gate: dict[str, Any],
) -> None:
    """Fail closed unless the frozen Mantis interface matches the gate."""

    if not isinstance(interface, dict):
        raise ContractError("Mantis LeRobot interface contract is required")
    state_names = interface.get("state_names")
    action_names = interface.get("action_names")
    expected_dimension = int(gate["dimensions"]["state_dimension"])
    if (
        not isinstance(state_names, list)
        or not isinstance(action_names, list)
        or len(state_names) != expected_dimension
        or len(action_names) != int(gate["dimensions"]["action_dimension"])
        or state_names != action_names
    ):
        raise ContractError(
            "Mantis interface must define identical ordered 16D state/action names"
        )
    if interface.get("fps") != gate["policy_output"]["control_hz"]:
        raise ContractError("Mantis interface fps must match the 30 Hz policy output")
    expected_hwc = {
        name: [shape[1], shape[2], shape[0]]
        for name, shape in gate["image_features"].items()
    }
    if interface.get("camera_features") != expected_hwc:
        raise ContractError(
            "Mantis interface camera HWC shapes do not match the gate CHW shapes"
        )


def validate_action_vector(
    action: Any, *, action_dimension: int
) -> tuple[bool, list[float]]:
    """Validate one finite 16D action.  Returns ``(finite, components)``."""

    components = _finite_vector(action, action_dimension)
    return (components is not None, components or [])


def physical_joint_limits(
    fixed_plan: dict[str, Any], physical_order: Sequence[str]
) -> dict[str, tuple[float, float]]:
    """Return ``physical_joint -> (lower, upper)`` from the fixed-base plan.

    Fails closed unless the 18 fixed-base joint limits exactly cover the physical
    joint order declared by the port contract.
    """

    limits = fixed_plan.get("joint_limits")
    if not isinstance(limits, dict):
        raise ContractError("fixed-base plan joint_limits must be an object")
    if set(limits) != set(physical_order):
        raise ContractError(
            "fixed-base joint limits must exactly cover the port physical_joint_order"
        )
    parsed: dict[str, tuple[float, float]] = {}
    for name in physical_order:
        entry = limits[name]
        if not isinstance(entry, dict):
            raise ContractError(f"fixed-base joint limit for {name} must be an object")
        lower = entry.get("lower")
        upper = entry.get("upper")
        if not isinstance(lower, (int, float)) or not isinstance(upper, (int, float)):
            raise ContractError(f"fixed-base joint {name} must have numeric limits")
        if lower >= upper:
            raise ContractError(f"fixed-base joint {name} has a non-positive range")
        parsed[name] = (float(lower), float(upper))
    return parsed


def enforce_joint_limits(
    physical: Sequence[float],
    *,
    physical_order: Sequence[str],
    limits: dict[str, tuple[float, float]],
    range_tolerance: float = 1e-6,
) -> list[str]:
    """Return one issue string per physical joint outside its fixed-base limit."""

    if len(physical) != len(physical_order):
        return [
            f"physical_dimension_mismatch:{len(physical)}:{len(physical_order)}"
        ]
    issues: list[str] = []
    for name, value in zip(physical_order, physical):
        lower, upper = limits[name]
        if not math.isfinite(value):
            issues.append(f"joint_not_finite:{name}")
        elif value < lower - range_tolerance or value > upper + range_tolerance:
            issues.append(
                f"joint_limit_violation:{name}:{value}:{lower}:{upper}"
            )
    return issues


def expand_virtual_to_physical(
    action: Sequence[float],
    *,
    port: dict[str, Any],
) -> list[float]:
    """Expand a finite 16D action to the 18D simulation target.

    ``allow_unverified=True`` is set explicitly because the gripper mapping is
    hardware-unverified; this projection is simulation-only and no action is sent
    to Genesis or hardware by this work package.  Gripper values outside ``[0, 1]``
    raise :class:`ContractError` (handled by the caller as an action-safety issue).
    """

    return virtual_to_physical(action, port, allow_unverified=True)


def project_virtual_gripper_action(
    action: Sequence[float],
    *,
    gate: dict[str, Any],
    port: dict[str, Any],
) -> tuple[list[float], list[int], float]:
    """Apply the optional versioned virtual-gripper actuator projection.

    The v1 gate has no projection and therefore preserves its strict rejection
    semantics.  The v2 gate applies a deterministic componentwise saturation to
    only the two normalized virtual-gripper channels.  The 14 arm channels are
    never changed, non-finite values are rejected earlier, and both raw and
    projected actions are retained in the receipt.

    This is a categorical actuator-domain constraint, not a tolerance selected
    from observed model outputs.  Saturation itself is diagnostic rather than a
    pass failure; the resulting 18D target must still satisfy every fixed-base
    physical joint limit.
    """

    projection = gate.get("gripper_output_projection")
    projected = [float(value) for value in action]
    if projection is None:
        return projected, [], 0.0

    target_order = port.get("target", {}).get("joint_order")
    if not isinstance(target_order, list) or len(target_order) != len(projected):
        raise ContractError(
            "target joint order must match the virtual action dimension"
        )
    derived_indices = [
        index
        for index, name in enumerate(target_order)
        if isinstance(name, str) and name.endswith("_gripper_joint")
    ]
    configured_indices = [int(index) for index in projection["indices"]]
    if derived_indices != configured_indices:
        raise ContractError(
            "configured gripper projection indices do not match target joint order: "
            f"{configured_indices} != {derived_indices}"
        )

    lower, upper = (float(value) for value in projection["domain"])
    saturated_indices: list[int] = []
    max_abs_delta = 0.0
    for index in configured_indices:
        raw = projected[index]
        bounded = min(upper, max(lower, raw))
        delta = abs(bounded - raw)
        if delta > 0.0:
            saturated_indices.append(index)
            max_abs_delta = max(max_abs_delta, delta)
        projected[index] = bounded
    return projected, saturated_indices, max_abs_delta


def project_physical_joint_target(
    physical: Sequence[float],
    *,
    gate: dict[str, Any],
    physical_order: Sequence[str],
    limits: dict[str, tuple[float, float]],
) -> tuple[list[float], list[str], float]:
    """Apply the optional versioned 18D physical actuator-limit projection."""

    projected = [float(value) for value in physical]
    projection = gate.get("physical_joint_output_projection")
    if projection is None:
        return projected, [], 0.0
    if len(projected) != len(physical_order) or len(projected) != 18:
        raise ContractError(
            "physical projection requires the frozen 18D physical joint order"
        )
    if set(physical_order) != set(limits):
        raise ContractError(
            "physical projection limits must exactly cover the physical joint order"
        )

    saturated_names: list[str] = []
    max_abs_delta = 0.0
    for index, name in enumerate(physical_order):
        raw = projected[index]
        if not math.isfinite(raw):
            raise ContractError(f"physical joint target is not finite: {name}")
        lower, upper = limits[name]
        bounded = min(upper, max(lower, raw))
        delta = abs(bounded - raw)
        if delta > 0.0:
            saturated_names.append(name)
            max_abs_delta = max(max_abs_delta, delta)
        projected[index] = bounded
    return projected, saturated_names, max_abs_delta


# ---------------------------------------------------------------------------
# Orchestration.
# ---------------------------------------------------------------------------


def run_open_loop_inference(
    runtime: InferenceRuntime,
    *,
    gate: dict[str, Any],
    gate_sha256: str | None,
    port: dict[str, Any],
    fixed_plan: dict[str, Any],
    interface: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Run the deterministic open-loop gate and return an immutable-ready receipt.

    The receipt's ``open_loop_inference_pass`` is true only when the runtime
    identity matches the contract, every selected observation validated, every
    sample produced a finite 16D action, and every expansion satisfied all 18
    fixed-base physical joint limits.  Failures never claim inference success.
    """

    validate_config(gate)
    validate_interface_contract(interface, gate=gate)
    expected_episodes = int(gate["sampling"]["episodes"])
    expected_distinct = int(gate["sampling"]["expected_distinct_samples"])
    state_dimension = int(gate["dimensions"]["state_dimension"])
    action_dimension = int(gate["dimensions"]["action_dimension"])
    image_features = {
        str(name): tuple(int(part) for part in shape)
        for name, shape in gate["image_features"].items()
    }

    identity_issues = _audit_runtime_identity(runtime, gate)
    bounds = runtime.episode_bounds()
    selected = select_samples(
        bounds,
        expected_episodes=expected_episodes,
        expected_distinct_samples=expected_distinct,
    )

    physical_order = port["target"]["physical_joint_order"]
    limits = physical_joint_limits(fixed_plan, physical_order)

    samples: list[SampleResult] = []
    terminal_issues: list[str] = []
    terminal_issues.extend(identity_issues)

    for episode, global_index, offset in selected:
        runtime.reset_policy_state()
        observation = runtime.observe(global_index)
        observation_issues = validate_observation(
            observation,
            image_features=image_features,
            state_dimension=state_dimension,
            image_value_range=gate["expected_image_value_range"],
        )
        observation_valid = not observation_issues

        action: list[float] = []
        action_finite = False
        latency_ms: float | None = None
        if observation_valid:
            try:
                action, latency_ms = runtime.infer(observation)
            except Exception as exc:  # noqa: BLE001 - auditable inference failure
                observation_issues.append(
                    f"inference_error:{episode}:{offset}:{type(exc).__name__}"
                )
            else:
                action_finite, validated = validate_action_vector(
                    action, action_dimension=action_dimension
                )
                if action_finite:
                    action = validated
                else:
                    observation_issues.append(
                        f"action_not_finite_or_wrong_dim:{episode}:{offset}"
                    )

        safety_pass = False
        projected_action: list[float] = []
        saturated_action_indices: list[int] = []
        saturation_max_abs_delta = 0.0
        raw_physical: list[float] = []
        physical: list[float] = []
        saturated_physical_joint_names: list[str] = []
        physical_saturation_max_abs_delta = 0.0
        preprojection_joint_limit_issues: list[str] = []
        joint_limit_issues: list[str] = []
        if action_finite:
            try:
                (
                    projected_action,
                    saturated_action_indices,
                    saturation_max_abs_delta,
                ) = project_virtual_gripper_action(action, gate=gate, port=port)
                raw_physical = expand_virtual_to_physical(
                    projected_action, port=port
                )
                preprojection_joint_limit_issues = enforce_joint_limits(
                    raw_physical,
                    physical_order=physical_order,
                    limits=limits,
                )
                (
                    physical,
                    saturated_physical_joint_names,
                    physical_saturation_max_abs_delta,
                ) = project_physical_joint_target(
                    raw_physical,
                    gate=gate,
                    physical_order=physical_order,
                    limits=limits,
                )
            except ContractError as exc:
                observation_issues.append(
                    f"gripper_expansion_failed:{episode}:{offset}:{exc}"
                )
            else:
                joint_limit_issues = enforce_joint_limits(
                    physical,
                    physical_order=physical_order,
                    limits=limits,
                )
                safety_pass = not joint_limit_issues
        terminal_issues.extend(observation_issues)
        terminal_issues.extend(joint_limit_issues)

        samples.append(
            SampleResult(
                global_index=global_index,
                episode_index=episode,
                offset=offset,
                action=action,
                projected_action=projected_action,
                saturated_action_indices=saturated_action_indices,
                saturation_max_abs_delta=saturation_max_abs_delta,
                raw_physical=raw_physical,
                physical=physical,
                saturated_physical_joint_names=saturated_physical_joint_names,
                physical_saturation_max_abs_delta=physical_saturation_max_abs_delta,
                preprojection_joint_limit_issues=preprojection_joint_limit_issues,
                observation_valid=observation_valid,
                action_finite=action_finite,
                safety_pass=safety_pass,
                joint_limit_issues=joint_limit_issues,
                issues=observation_issues,
                latency_ms=latency_ms,
            )
        )

    unique_issues = sorted(set(terminal_issues))
    open_loop_pass = not unique_issues

    selected_indices = [entry[1] for entry in selected]
    samples_per_episode: dict[str, list[int]] = {}
    for episode, _global, offset in selected:
        samples_per_episode.setdefault(str(episode), []).append(offset)

    receipt: dict[str, Any] = {
        "schema_version": 1,
        "gate_id": gate["gate_id"],
        "task_id": gate["task_id"],
        "protocol": gate["protocol"],
        "training_id": gate["training_id"],
        "phase": gate["phase"],
        "sample_phase": gate["sample_phase"],
        "open_loop_inference_pass": open_loop_pass,
        "issues": unique_issues,
        "runtime_identity": {
            "lerobot_version": runtime.lerobot_version,
            "policy_device": runtime.policy_device,
            "policy_device_index": runtime.policy_device_index,
            "hip_device_count": runtime.hip_device_count,
            "lerobot_version_match": runtime.lerobot_version == EXPECTED_LEROBOT_VERSION,
            "policy_device_match": runtime.policy_device == gate["required_runtime_identity"]["policy_device"],
            "hip_device_count_match": (
                runtime.hip_device_count == gate["required_runtime_identity"]["hip_device_count"]
            ),
        },
        "environment_identity": runtime.environment_identity,
        "input_hashes": runtime.input_hashes,
        "processor_artifact_hashes": runtime.processor_artifact_hashes,
        "policy_config": runtime.policy_config,
        "selected_episodes": sorted({entry[0] for entry in selected}),
        "selected_global_indices": selected_indices,
        "samples_per_episode": samples_per_episode,
        "decoded_samples": len(samples),
        "distinct_selected_samples": len(set(selected_indices)),
        "expected_episodes": expected_episodes,
        "expected_distinct_samples": expected_distinct,
        "dimensions": gate["dimensions"],
        "image_features": {
            name: list(shape) for name, shape in gate["image_features"].items()
        },
        "gripper_contract": {
            "version": gate["gripper_contract"]["version"],
            "simulation_only": True,
            "allow_unverified": True,
            "allow_unverified_only_for": (
                gate["gripper_contract"]["allow_unverified_only_for"]
            ),
            "expansion_function": gate["gripper_contract"]["expansion_function"],
            "no_action_sent_to_genesis_or_hardware": True,
            "output_projection": gate.get("gripper_output_projection"),
            "saturated_sample_count": sum(
                bool(sample.saturated_action_indices) for sample in samples
            ),
            "saturated_channel_count": sum(
                len(sample.saturated_action_indices) for sample in samples
            ),
            "max_abs_saturation_delta": max(
                (sample.saturation_max_abs_delta for sample in samples),
                default=0.0,
            ),
        },
        "fixed_joint_limit_source": gate["fixed_joint_limit_source"],
        "physical_joint_output_projection": {
            "contract": gate.get("physical_joint_output_projection"),
            "saturated_sample_count": sum(
                bool(sample.saturated_physical_joint_names) for sample in samples
            ),
            "saturated_joint_count": sum(
                len(sample.saturated_physical_joint_names) for sample in samples
            ),
            "max_abs_saturation_delta": max(
                (sample.physical_saturation_max_abs_delta for sample in samples),
                default=0.0,
            ),
        },
        "per_sample": [_sample_record(sample) for sample in samples],
        "descriptive": {
            "latency_ms": {
                "min": _min_latency(samples),
                "max": _max_latency(samples),
                "mean": _mean_latency(samples),
            },
            "note": (
                "Latency is descriptive only. It is never a pass threshold and "
                "never a comparative performance claim."
            ),
        },
        "gate_sha256": gate_sha256,
        "claim_boundary": gate["claim_boundary"],
    }
    return receipt


def _audit_runtime_identity(runtime: InferenceRuntime, gate: dict[str, Any]) -> list[str]:
    issues: list[str] = []
    identity = gate["required_runtime_identity"]
    if runtime.lerobot_version != identity["lerobot_version"]:
        issues.append(
            f"lerobot_version_mismatch:{runtime.lerobot_version}:{identity['lerobot_version']}"
        )
    if runtime.policy_device != identity["policy_device"]:
        issues.append(
            f"policy_device_mismatch:{runtime.policy_device}:{identity['policy_device']}"
        )
    if runtime.policy_device_index != identity["policy_device_index"]:
        issues.append(
            f"policy_device_index_mismatch:{runtime.policy_device_index}:{identity['policy_device_index']}"
        )
    if runtime.hip_device_count != identity["hip_device_count"]:
        issues.append(
            f"hip_device_count_mismatch:{runtime.hip_device_count}:{identity['hip_device_count']}"
        )
    return issues


def _sample_record(sample: SampleResult) -> dict[str, Any]:
    return {
        "global_index": sample.global_index,
        "episode_index": sample.episode_index,
        "offset": sample.offset,
        "action": sample.action,
        "raw_action_16d": sample.action,
        "projected_action_16d": sample.projected_action,
        "saturated_action_indices": sample.saturated_action_indices,
        "saturated_action_channel_count": len(sample.saturated_action_indices),
        "saturation_max_abs_delta": sample.saturation_max_abs_delta,
        "raw_physical_target_18d": sample.raw_physical,
        "physical_target_18d": sample.physical,
        "projected_physical_target_18d": sample.physical,
        "saturated_physical_joint_names": sample.saturated_physical_joint_names,
        "saturated_physical_joint_count": len(sample.saturated_physical_joint_names),
        "physical_saturation_max_abs_delta": sample.physical_saturation_max_abs_delta,
        "preprojection_joint_limit_issues": sample.preprojection_joint_limit_issues,
        "observation_valid": sample.observation_valid,
        "action_finite": sample.action_finite,
        "safety_pass": sample.safety_pass,
        "joint_limit_issues": sample.joint_limit_issues,
        "issues": sample.issues,
        "latency_ms": sample.latency_ms,
    }


def _min_latency(samples: Sequence[SampleResult]) -> float | None:
    values = [s.latency_ms for s in samples if s.latency_ms is not None]
    return min(values) if values else None


def _max_latency(samples: Sequence[SampleResult]) -> float | None:
    values = [s.latency_ms for s in samples if s.latency_ms is not None]
    return max(values) if values else None


def _mean_latency(samples: Sequence[SampleResult]) -> float | None:
    values = [s.latency_ms for s in samples if s.latency_ms is not None]
    return (sum(values) / len(values)) if values else None


# ---------------------------------------------------------------------------
# Standard-library helpers shared with the CLI.
# ---------------------------------------------------------------------------


def sha256_file(path: Any) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def sha256_bytes(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def enforce_offline_env() -> dict[str, str]:
    """Assert the Hugging Face offline flags *before* LeRobot is imported."""

    asserted: dict[str, str] = {}
    for key, value in OFFLINE_ENV_FLAGS.items():
        os.environ[key] = value
        asserted[key] = os.environ.get(key, value)
    return asserted


def required_pretrained_files(gate: dict[str, Any]) -> list[str]:
    files = gate.get("saved_processor_requirements", {}).get("required_files")
    if not isinstance(files, list):
        raise ContractError("gate saved_processor_requirements.required_files missing")
    return [str(name) for name in files]


def validate_required_checkpoint_files(
    checkpoint_dir: Any, gate: dict[str, Any]
) -> list[str]:
    """Return the required pretrained_model files; fail closed if any is missing."""

    base = Path(checkpoint_dir)
    if not base.is_dir():
        raise ContractError(f"checkpoint_dir is not a directory: {base}")
    required = required_pretrained_files(gate)
    missing = [name for name in required if not (base / name).is_file()]
    if missing:
        raise ContractError(
            f"checkpoint pretrained_model is missing required files {missing} under {base}"
        )
    return required


# ---------------------------------------------------------------------------
# Lazy LeRobot 0.4.4 runtime adapter (torch / lerobot imported here only).
# ---------------------------------------------------------------------------


class LeRobotOpenLoopRuntime:
    """Real runtime adapter: local LeRobot 0.4.4 dataset + frozen ACT checkpoint.

    Network is fenced off three ways, mirroring the sample-decode gate: the
    required local meta/data and pretrained_model files are prevalidated, the
    Hugging Face offline environment flags are asserted *before* LeRobot or torch
    is imported, and any local-load failure is raised as a :class:`ContractError`
    rather than triggering a download.  The saved checkpoint pre/post processors
    are loaded from the exact local pretrained_model directory via
    ``make_pre_post_processors(policy_cfg=policy.config, pretrained_path=...)``
    (defined by ``lerobot.policies.factory`` in LeRobot 0.4.4); dataset
    normalization statistics are never recomputed and there is no fallback.
    """

    def __init__(
        self,
        *,
        dataset_root: Any,
        repo_id: str,
        pretrained_model: Any,
        gate: dict[str, Any],
        port_sha256: str,
        interface_sha256: str,
        fixed_plan_sha256: str,
    ) -> None:
        self._root = Path(dataset_root).resolve()
        self._repo_id = str(repo_id)
        self._pretrained = Path(pretrained_model).resolve()
        self._gate = gate
        # Offline flags FIRST, before any LeRobot / torch import.
        self._offline_env = enforce_offline_env()
        # Prevalidate the checkpoint files so a missing artifact never falls
        # through to a network resolution.
        validate_required_checkpoint_files(self._pretrained.parent, gate)

        import torch  # noqa: WPS433 - lazy, runtime-only

        self._torch = torch
        self._device = torch.device("cuda:0")
        self._assert_rocm_identity(torch)

        from lerobot.datasets.lerobot_dataset import (  # noqa: WPS433 - lazy
            LeRobotDataset,
        )
        from lerobot.policies.factory import (  # noqa: WPS433 - lazy
            make_pre_post_processors,
        )
        import lerobot  # noqa: WPS433 - lazy

        self.lerobot_version = self._resolve_lerobot_version(lerobot)
        self._dataset = self._load_dataset(LeRobotDataset)
        self._policy = self._load_policy(torch)
        self._processors = self._load_processors(make_pre_post_processors)
        self.policy_config = self._load_policy_config()
        self.policy_device = "cuda"
        self.policy_device_index = "cuda:0"
        self.hip_device_count = int(torch.cuda.device_count())
        self.processor_artifact_hashes = self._hash_processor_artifacts()
        self.environment_identity = self._capture_environment_identity()
        self.input_hashes = {
            "dataset_root": sha256_file(self._root / "meta" / "info.json"),
            "port_config_sha256": port_sha256,
            "interface_contract_sha256": interface_sha256,
            "fixed_base_plan_sha256": fixed_plan_sha256,
        }
        self._bounds = self._load_episode_bounds()

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

    # -- dataset / policy / processors -------------------------------------

    def _load_dataset(self, LeRobotDataset: Any) -> Any:
        try:
            return LeRobotDataset(
                self._repo_id,
                root=self._root,
                download_videos=False,
                force_cache_sync=False,
            )
        except Exception as exc:  # noqa: BLE001 - any local-load failure fails closed
            raise ContractError(
                "local LeRobotDataset load failed and no download was attempted "
                f"(offline_env={self._offline_env}, root={self._root}): {exc!r}"
            ) from exc

    def _load_policy(self, torch: Any) -> Any:
        from lerobot.policies.act.modeling_act import (  # noqa: WPS433 - lazy
            ACTPolicy,
        )

        try:
            policy = ACTPolicy.from_pretrained(str(self._pretrained), local_files_only=True)
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
        # LeRobot 0.4.4 defines make_pre_post_processors in
        # lerobot.policies.factory; its package __init__ does not re-export it.
        # The saved checkpoint processors are loaded from the exact local
        # pretrained_model directory via pretrained_path; policy_cfg is the
        # loaded policy's config.  Dataset normalization statistics are never
        # recomputed and there is no fallback path.
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
        for name in self._gate["saved_processor_requirements"]["required_files"]:
            path = self._pretrained.parent / name
            hashes[name] = sha256_file(path)
        return hashes

    def _capture_environment_identity(self) -> dict[str, Any]:
        import platform

        torch = self._torch
        return {
            "torch_version": str(torch.__version__),
            "torch_hip_version": str(torch.version.hip),
            "torch_cuda_is_available": bool(torch.cuda.is_available()),
            "torch_cuda_device_count": int(torch.cuda.device_count()),
            "torch_cuda_device_name_0": str(torch.cuda.get_device_name(0)),
            "python_version": platform.python_version(),
            "platform": platform.platform(),
            "offline_env": dict(self._offline_env),
        }

    def _load_episode_bounds(self) -> dict[int, tuple[int, int]]:
        episodes = self._dataset.meta.episodes
        episode_index = list(episodes["episode_index"])
        from_index = list(episodes["dataset_from_index"])
        to_index = list(episodes["dataset_to_index"])
        bounds: dict[int, tuple[int, int]] = {}
        for episode, start, end in zip(episode_index, from_index, to_index):
            bounds[int(episode)] = (int(start), int(end) - int(start))
        if not bounds:
            raise ContractError(
                f"dataset.meta.episodes carried no episode bounds for {self._root}"
            )
        return bounds

    # -- protocol surface ---------------------------------------------------

    def episode_bounds(self) -> dict[int, tuple[int, int]]:
        return dict(self._bounds)

    def reset_policy_state(self) -> None:
        # Reset any episodic buffers (e.g. observation/action queues) so
        # independent open-loop samples do not leak state into each other.
        reset = getattr(self._policy, "reset", None)
        if callable(reset):
            reset()

    def observe(self, global_index: int) -> Observation:
        torch = self._torch
        try:
            item = self._dataset[int(global_index)]
        except Exception as exc:  # noqa: BLE001 - auditable decode failure
            raise ContractError(
                f"LeRobot dataset decode failed for index {global_index}: {exc!r}"
            ) from exc
        state = [float(component) for component in item["observation.state"].tolist()]
        episode_index = int(item["episode_index"].item())
        first_global, _length = self._bounds[episode_index]
        offset = int(global_index) - first_global
        preprocessor = self._processors[0]
        images = {
            "observation.images.env_cam": item["observation.images.env_cam"],
            "observation.images.left_wrist_cam": item["observation.images.left_wrist_cam"],
            "observation.images.right_wrist_cam": item["observation.images.right_wrist_cam"],
        }
        preprocessed = preprocessor({"observation.state": item["observation.state"], **images})
        self._last_preprocessed = {key: self._to_cuda(value) for key, value in preprocessed.items()}
        summaries = {
            feature: self._image_summary(images[feature]) for feature in images
        }
        return Observation(
            global_index=int(global_index),
            episode_index=episode_index,
            offset=offset,
            state=state,
            images=summaries,
        )

    def infer(self, observation: Observation) -> tuple[list[float], float | None]:
        import time as _time

        torch = self._torch
        postprocessor = self._processors[1]
        with torch.inference_mode():
            if torch.cuda.is_available():
                torch.cuda.synchronize()
            start = _time.perf_counter()
            action = self._policy.select_action(self._last_preprocessed)
            if torch.cuda.is_available():
                torch.cuda.synchronize()
            elapsed = _time.perf_counter() - start
        # LeRobot 0.4.4 ACTPolicy.select_action returns (batch, action_dim),
        # not the full action chunk.  The saved postprocessor accepts that
        # tensor directly and preserves the batch dimension.
        postprocessed = postprocessor(action)
        shape = tuple(int(dim) for dim in postprocessed.shape)
        expected = int(self._gate["dimensions"]["action_dimension"])
        if shape != (1, expected):
            raise ContractError(
                f"postprocessed ACT action shape is {shape}, expected (1, {expected})"
            )
        vector = postprocessed[0].detach().to("cpu").tolist()
        return [float(component) for component in vector], elapsed * 1000.0

    # -- small torch helpers -----------------------------------------------

    def _to_cuda(self, value: Any) -> Any:
        if hasattr(value, "to"):
            return value.to(self._device)
        return value

    def _image_summary(self, tensor: Any) -> TensorSummary:
        torch = self._torch
        shape = tuple(int(dim) for dim in tensor.shape)
        finite = bool(torch.isfinite(tensor).all())
        return TensorSummary(
            shape=shape,
            finite=finite,
            min_value=float(tensor.min()),
            max_value=float(tensor.max()),
        )
