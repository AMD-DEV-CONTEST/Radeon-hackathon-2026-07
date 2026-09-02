#!/usr/bin/env python3
"""Evaluate the sealed development-only v6 observer observability audit."""

from __future__ import annotations

import argparse
import dataclasses
import hashlib
import json
import math
import os
import re
import stat
import struct
import sys
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any

import numpy as np
import numpy.typing as npt
import torch

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent
SRC_ROOT = PROJECT_ROOT / "src"
for import_root in (PROJECT_ROOT, SRC_ROOT):
    if str(import_root) not in sys.path:
        sys.path.insert(0, str(import_root))

import flightguard.exact_native_observer_capture as capture_module
import flightguard.frozen_vio_imu_observer as observer_module
from scripts import evaluate_causal_imu_repair_batch_amd as batch_module
from tools import build_v6_observer_baseline_seal as baseline_module
from tools import build_v6_observer_capture_governance as governance_module
from tools import build_v6_observer_capture_protocol as protocol_module

CHECKPOINT_AUDIT_SCHEMA_VERSION = (
    "flightguard.v6.observer_observability.checkpoint_audit.v1"
)
AGGREGATE_AUDIT_SCHEMA_VERSION = (
    "flightguard.v6.observer_observability.aggregate_audit.v1"
)
FORENSIC_SCHEMA_VERSION = (
    "flightguard.v6.observer_observability.integrity_forensic.v1"
)
FULL_LEGACY_RUNTIME_STEPS = 800
CAPTURE_PREFIX_STEPS = 300
POST_CAPTURE_DROPOUT_STEPS = 500
_CHECKPOINT_TEXT = re.compile(r"(?:0|[1-9][0-9]*)\Z")
_RUNTIME_SOURCE_PATHS: Mapping[str, Callable[[], Path]] = {
    "observer_core": lambda: Path(observer_module.__file__).resolve(),
    "capture_module": lambda: Path(capture_module.__file__).resolve(),
    "batch_evaluator": lambda: Path(batch_module.__file__).resolve(),
    "audit_evaluator": lambda: Path(__file__).resolve(),
    "baseline_builder": lambda: Path(baseline_module.__file__).resolve(),
    "protocol_builder": lambda: Path(protocol_module.__file__).resolve(),
}


class ObserverObservabilityIntegrityError(RuntimeError):
    """Raised when immutable inputs or recomputed evidence fail integrity."""


def _exact_checkpoint(value: str) -> str:
    if value == "aggregate":
        return value
    if not isinstance(value, str) or _CHECKPOINT_TEXT.fullmatch(value) is None:
        raise argparse.ArgumentTypeError(
            "--checkpoint must be an exact nonnegative integer or aggregate"
        )
    return value


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(allow_abbrev=False)
    parser.add_argument("--protocol", type=Path, required=True)
    parser.add_argument("--checkpoint", type=_exact_checkpoint, required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args(argv)


def _require_exact_keys(
    value: Mapping[str, Any],
    expected: set[str],
    *,
    name: str,
) -> None:
    actual = set(value)
    if actual != expected:
        raise ObserverObservabilityIntegrityError(
            f"{name} keys mismatch: missing={sorted(expected - actual)}, "
            f"unknown={sorted(actual - expected)}"
        )


def _validated_binding(value: Any, *, name: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ObserverObservabilityIntegrityError(f"{name} must be an object")
    try:
        return governance_module.validate_binding(value, name=name)
    except (OSError, TypeError, ValueError, governance_module.ObserverCaptureGovernanceError) as error:
        raise ObserverObservabilityIntegrityError(
            f"{name} binding validation failed"
        ) from error


def _validate_runtime_sources(protocol: Mapping[str, Any]) -> None:
    implementation = protocol.get("implementation_bindings")
    if not isinstance(implementation, dict):
        raise ObserverObservabilityIntegrityError(
            "protocol implementation_bindings must be an object"
        )
    sources = implementation.get("sources")
    if not isinstance(sources, dict):
        raise ObserverObservabilityIntegrityError(
            "protocol implementation sources must be an object"
        )
    for role, path_factory in _RUNTIME_SOURCE_PATHS.items():
        if role not in sources:
            raise ObserverObservabilityIntegrityError(
                f"protocol implementation source {role} is missing"
            )
        record = _validated_binding(
            sources[role],
            name=f"protocol implementation source {role}",
        )
        expected_path = path_factory()
        if Path(record["path"]) != expected_path:
            raise ObserverObservabilityIntegrityError(
                f"runtime source path mismatch for {role}"
            )


def _load_validated_protocol(path: Path) -> dict[str, Any]:
    try:
        protocol_path = governance_module.normalized_absolute_path(
            path.expanduser(),
            name="observer audit protocol",
        )
        protocol = governance_module.load_strict_json(protocol_path)
        protocol_module.validate_audit_protocol(
            protocol,
            protocol_path=protocol_path,
        )
    except (
        OSError,
        TypeError,
        ValueError,
        baseline_module.ObserverBaselineSealError,
        governance_module.ObserverCaptureGovernanceError,
        protocol_module.ObserverCaptureProtocolError,
    ) as error:
        raise ObserverObservabilityIntegrityError(
            "observer audit protocol strict validation failed"
        ) from error
    _validate_runtime_sources(protocol)
    return protocol


def _registered_output_path(
    protocol: Mapping[str, Any],
    *,
    checkpoint: str,
    requested: Path,
) -> Path:
    outputs = protocol.get("registered_outputs")
    if not isinstance(outputs, dict):
        raise ObserverObservabilityIntegrityError(
            "protocol registered_outputs must be an object"
        )
    if checkpoint == "aggregate":
        expected_value = outputs.get("observer_audit_aggregate")
    else:
        by_checkpoint = outputs.get("observer_audit_by_checkpoint")
        if not isinstance(by_checkpoint, dict) or checkpoint not in by_checkpoint:
            raise ObserverObservabilityIntegrityError(
                "requested checkpoint is not registered"
            )
        expected_value = by_checkpoint[checkpoint]
    if not isinstance(expected_value, str):
        raise ObserverObservabilityIntegrityError(
            "registered observer audit output must be a path string"
        )
    try:
        expected = governance_module.normalized_absolute_path(
            Path(expected_value),
            name="registered observer audit output",
        )
        actual = governance_module.normalized_absolute_path(
            requested.expanduser(),
            name="requested observer audit output",
        )
    except governance_module.ObserverCaptureGovernanceError as error:
        raise ObserverObservabilityIntegrityError(
            "observer audit output path validation failed"
        ) from error
    if actual != expected:
        raise ObserverObservabilityIntegrityError(
            "requested output differs from the registered slot"
        )
    if os.path.lexists(actual):
        raise ObserverObservabilityIntegrityError(
            "registered observer audit output is not fresh"
        )
    return actual


def _observer_config(protocol: Mapping[str, Any]) -> observer_module.FrozenVIOIMUObserverConfig:
    frozen = protocol.get("frozen_config")
    if not isinstance(frozen, dict):
        raise ObserverObservabilityIntegrityError(
            "protocol frozen_config must be an object"
        )
    record = frozen.get("observer")
    if not isinstance(record, dict):
        raise ObserverObservabilityIntegrityError(
            "protocol observer config must be an object"
        )
    canonical = governance_module.FROZEN_OBSERVER_CONFIG
    _require_exact_keys(
        record,
        set(canonical),
        name="protocol observer config",
    )
    if (
        governance_module.canonical_json_bytes(record)
        != governance_module.canonical_json_bytes(canonical)
    ):
        raise ObserverObservabilityIntegrityError(
            "protocol observer config differs from preregistered exact values"
        )
    constructor = dict(record)
    gravity = constructor.get("gravity_world_mps2")
    if not isinstance(gravity, list):
        raise ObserverObservabilityIntegrityError(
            "protocol observer gravity must be a list"
        )
    constructor["gravity_world_mps2"] = tuple(gravity)
    try:
        return observer_module.FrozenVIOIMUObserverConfig(**constructor)
    except (TypeError, ValueError) as error:
        raise ObserverObservabilityIntegrityError(
            "protocol observer config cannot be constructed exactly"
        ) from error


def _audit_gates(protocol: Mapping[str, Any]) -> dict[str, int | float]:
    frozen = protocol.get("frozen_config")
    gates = frozen.get("audit_gates") if isinstance(frozen, dict) else None
    if not isinstance(gates, dict):
        raise ObserverObservabilityIntegrityError(
            "protocol audit_gates must be an object"
        )
    expected = set(governance_module.AUDIT_GATES)
    _require_exact_keys(gates, expected, name="protocol audit_gates")
    canonical = governance_module.AUDIT_GATES
    if any(type(gates[key]) is not type(canonical[key]) or gates[key] != canonical[key] for key in expected):
        raise ObserverObservabilityIntegrityError(
            "protocol audit gates differ from the frozen constants"
        )
    return dict(gates)


def _capture_inputs(capture: Any) -> dict[str, Any]:
    """Read only exact registered observation fields from a strict capture."""

    return {
        "specific_force_body_history": capture.observer_specific_force_body,
        "angular_velocity_body_history": capture.observer_angular_velocity_body,
        "exact_raw_native_specific_force_body_history": (
            capture.raw_specific_force_body
        ),
        "exact_raw_native_angular_velocity_body_history": (
            capture.raw_angular_velocity_body
        ),
        "vio_velocity_world_history": capture.vio_velocity_world,
        "vio_quaternion_body_to_world_history": (
            capture.vio_quaternion_body_to_world_wxyz
        ),
        "valid_transition_mask": capture.valid_transition_mask,
        "dt": capture.dt_seconds,
    }


def _raw_tensor_equal_array(
    tensor: torch.Tensor,
    array: npt.ArrayLike,
) -> bool:
    expected = np.asarray(array)
    if (
        not isinstance(tensor, torch.Tensor)
        or tensor.device.type != "cpu"
        or tensor.dtype != torch.float32
        or tensor.requires_grad
        or expected.dtype != np.dtype("<f4")
        or tuple(tensor.shape) != expected.shape
    ):
        return False
    actual = tensor.detach().contiguous().numpy()
    return actual.tobytes(order="C") == expected.tobytes(order="C")


def _sealed_legacy_sensor_runtime(
    protocol: Mapping[str, Any],
    *,
    capture: Any,
    checkpoint: str,
) -> tuple[int, dict[str, Any], dict[str, Any]]:
    legacy = protocol.get("legacy_execution")
    if not isinstance(legacy, dict):
        raise ObserverObservabilityIntegrityError(
            "sealed legacy execution contract is unavailable"
        )
    protocol_record = _validated_binding(
        legacy.get("protocol"),
        name="sealed legacy execution protocol",
    )
    try:
        payload = governance_module.load_strict_json(
            Path(protocol_record["path"])
        )
    except (
        OSError,
        TypeError,
        ValueError,
        governance_module.ObserverCaptureGovernanceError,
    ) as error:
        raise ObserverObservabilityIntegrityError(
            "sealed legacy execution protocol cannot be loaded"
        ) from error
    header = legacy.get("protocol_header")
    expected_header = {
        key: payload.get(key)
        for key in ("schema_version", "protocol_version", "status")
    }
    runtime = payload.get("runtime")
    sensor = payload.get("sensor_contract")
    if (
        header != expected_header
        or not isinstance(runtime, dict)
        or not isinstance(sensor, dict)
    ):
        raise ObserverObservabilityIntegrityError(
            "sealed legacy execution header/runtime/sensor mismatch"
        )
    full_steps = runtime.get("steps")
    runtime_dt = runtime.get("dt_s")
    dropout_start_step = runtime.get("dropout_start_step")
    dropout_steps = runtime.get("dropout_steps")
    if (
        type(full_steps) is not int
        or full_steps != FULL_LEGACY_RUNTIME_STEPS
        or type(dropout_start_step) is not int
        or dropout_start_step != CAPTURE_PREFIX_STEPS
        or "dropout_steps" not in runtime
        or type(dropout_steps) is not int
        or dropout_steps != POST_CAPTURE_DROPOUT_STEPS
        or dropout_start_step + dropout_steps != full_steps
        or type(runtime_dt) is bool
        or not isinstance(runtime_dt, (int, float))
        or not math.isfinite(float(runtime_dt))
        or float(runtime_dt) != capture.dt_seconds
    ):
        raise ObserverObservabilityIntegrityError(
            f"checkpoint {checkpoint} sealed full runtime is invalid"
        )
    profile = sensor.get("formal_error_profile")
    live_profile = batch_module.FORMAL_REALISTIC_SENSOR_PROFILE
    expected_profile = {
        "name": live_profile.name,
        "sha256": live_profile.canonical_sha256(),
        "values": dataclasses.asdict(live_profile),
    }
    if profile != expected_profile:
        raise ObserverObservabilityIntegrityError(
            "sealed legacy formal sensor profile record mismatch"
        )
    profile_sha256 = expected_profile["sha256"]
    generator_sha256 = batch_module.sensor_error_bank_generator_code_sha256()
    if (
        sensor.get("genesis_native_noise_matching_claimed") is not False
        or sensor.get("formal_error_bank_raw_bit_match_required") is not True
        or sensor.get("zero_error_bank_must_raw_exact_reproduce_native_sample")
        is not True
        or sensor.get(
            "registered_error_bank_must_change_estimator_input_and_estimate"
        )
        is not True
        or sensor.get("post_read_error_bank_generator_code_sha256")
        != generator_sha256
    ):
        raise ObserverObservabilityIntegrityError(
            "sealed legacy sensor fail-closed contract mismatch"
        )
    return full_steps, protocol_record, {
        "runtime_steps": full_steps,
        "dropout_start_step": dropout_start_step,
        "dropout_steps": dropout_steps,
        "capture_is_exact_pre_dropout_prefix": True,
        "dt_seconds": float(runtime_dt),
        "formal_error_profile_sha256": profile_sha256,
        "post_read_error_bank_generator_code_sha256": generator_sha256,
        "genesis_native_noise_matching_claimed": False,
        "formal_error_bank_raw_bit_match_required": True,
        "zero_error_bank_must_raw_exact_reproduce_native_sample": True,
        "registered_error_bank_must_change_estimator_input_and_estimate": True,
    }


def _validated_capture_seed_map(
    protocol: Mapping[str, Any],
    *,
    capture: Any,
    checkpoint: str,
) -> tuple[dict[str, int], dict[str, Any]]:
    governance_record = protocol.get("governance")
    if not isinstance(governance_record, dict):
        raise ObserverObservabilityIntegrityError(
            "observer protocol governance record is unavailable"
        )
    try:
        frozen_governance, base_binding = governance_module.validate_governance(
            Path(str(governance_record.get("path"))),
            str(governance_record.get("sha256")),
        )
    except (
        OSError,
        TypeError,
        ValueError,
        governance_module.ObserverCaptureGovernanceError,
    ) as error:
        raise ObserverObservabilityIntegrityError(
            "observer protocol governance cannot be revalidated"
        ) from error
    expected_record = {
        **base_binding,
        "schema_version": frozen_governance["schema_version"],
        "status": frozen_governance["status"],
    }
    if governance_record != expected_record:
        raise ObserverObservabilityIntegrityError(
            "observer protocol governance binding mismatch"
        )
    try:
        expected = frozen_governance["capture_contract"][
            "frozen_seed_identity_by_checkpoint"
        ][checkpoint]
    except (KeyError, TypeError) as error:
        raise ObserverObservabilityIntegrityError(
            f"checkpoint {checkpoint} frozen governance seeds are missing"
        ) from error
    actual = dict(capture.frozen_seeds)
    if (
        not isinstance(expected, dict)
        or any(type(key) is not str or type(value) is not int for key, value in expected.items())
        or actual != expected
    ):
        raise ObserverObservabilityIntegrityError(
            f"checkpoint {checkpoint} capture seeds differ from frozen governance"
        )
    return actual, expected_record


def _validate_full_sensor_bank(
    bank: Any,
    *,
    context_seeds: Sequence[int],
    full_steps: int,
    lane_count: int,
    dt: float,
    registered_sensor_seed: int,
    expected_sha256: str,
    checkpoint: str,
) -> tuple[torch.Tensor, torch.Tensor, str]:
    if not isinstance(bank, dict):
        raise ObserverObservabilityIntegrityError(
            f"checkpoint {checkpoint} sensor bank must be an object"
        )
    acceleration = bank.get("acceleration_error")
    gyro = bank.get("gyro_error")
    expected_shape = (full_steps, lane_count, 3)
    tensors = (acceleration, gyro)
    if any(
        not isinstance(value, torch.Tensor)
        or value.device.type != "cpu"
        or value.dtype != torch.float32
        or tuple(value.shape) != expected_shape
        or not value.is_contiguous()
        or value.requires_grad
        or not bool(torch.isfinite(value).all().item())
        for value in tensors
    ):
        raise ObserverObservabilityIntegrityError(
            f"checkpoint {checkpoint} full sensor bank tensor integrity failed"
        )
    raw_digest = hashlib.sha256()
    raw_digest.update(acceleration.numpy().tobytes(order="C"))
    raw_digest.update(gyro.numpy().tobytes(order="C"))
    raw_sha256 = raw_digest.hexdigest()
    full_digest = hashlib.sha256()
    full_digest.update(b"flightguard-deterministic-sensor-error-bank-v1\0")
    full_digest.update(
        batch_module.canonical_json_bytes(
            {
                "context_seeds": list(context_seeds),
                "dt_s": float(dt),
                "registered_noise_seed": int(registered_sensor_seed),
                "steps": int(full_steps),
            }
        )
    )
    full_digest.update(
        batch_module.canonical_json_bytes(
            dataclasses.asdict(batch_module.FORMAL_REALISTIC_SENSOR_PROFILE)
        )
    )
    full_digest.update(acceleration.numpy().tobytes(order="C"))
    full_digest.update(gyro.numpy().tobytes(order="C"))
    recomputed_sha256 = full_digest.hexdigest()
    if (
        bank.get("sha256") != expected_sha256
        or recomputed_sha256 != expected_sha256
        or bank.get("raw_bytes_sha256") != raw_sha256
        or bank.get("shape") != list(expected_shape)
        or bank.get("dtype") != "torch.float32"
        or bank.get("device") != "cpu"
        or bank.get("registered_noise_seed") != registered_sensor_seed
    ):
        raise ObserverObservabilityIntegrityError(
            f"checkpoint {checkpoint} frozen sensor error bank mismatch"
        )
    return acceleration, gyro, raw_sha256


def _replay_frozen_sensor_transform(
    capture: Any,
    *,
    protocol: Mapping[str, Any],
    checkpoint: str,
) -> dict[str, Any]:
    """Rebuild and replay the frozen raw-to-delivered sensor transform."""

    sources = protocol.get("implementation_bindings", {}).get("sources")
    if not isinstance(sources, dict):
        raise ObserverObservabilityIntegrityError(
            "sensor recurrence source registry is unavailable"
        )
    batch_binding = _validated_binding(
        sources.get("batch_evaluator"),
        name="sensor recurrence batch evaluator",
    )
    metadata = capture.frozen_transform
    expected_profile_sha256 = (
        batch_module.FORMAL_REALISTIC_SENSOR_PROFILE.canonical_sha256()
    )
    full_steps, legacy_protocol_binding, legacy_runtime = (
        _sealed_legacy_sensor_runtime(
            protocol,
            capture=capture,
            checkpoint=checkpoint,
        )
    )
    if (
        metadata.name != "apply_sensor_error"
        or metadata.enabled is not True
        or metadata.implementation_sha256 != batch_binding["sha256"]
        or metadata.config_sha256 != expected_profile_sha256
        or metadata.error_bank_schema_version
        != batch_module.V6_OBSERVER_CAPTURE_ERROR_BANK_SCHEMA_VERSION
    ):
        raise ObserverObservabilityIntegrityError(
            f"checkpoint {checkpoint} frozen sensor transform identity mismatch"
        )
    seeds, governance_binding = _validated_capture_seed_map(
        protocol,
        capture=capture,
        checkpoint=checkpoint,
    )
    context_keys = [f"context.{index:02d}" for index in range(capture.lane_count)]
    if (
        set(context_keys).difference(seeds)
        or type(seeds.get("sensor")) is not int
        or type(seeds.get("checkpoint")) is not int
        or seeds["checkpoint"] != int(checkpoint)
    ):
        raise ObserverObservabilityIntegrityError(
            f"checkpoint {checkpoint} frozen sensor seeds are incomplete"
        )
    context_seeds = [seeds[key] for key in context_keys]
    if any(type(value) is not int for value in context_seeds):
        raise ObserverObservabilityIntegrityError(
            f"checkpoint {checkpoint} context seed types are invalid"
        )
    try:
        bank = batch_module.build_sensor_error_bank(
            context_seeds=context_seeds,
            steps=full_steps,
            dt=capture.dt_seconds,
            registered_noise_seed=seeds["sensor"],
        )
    except (ArithmeticError, RuntimeError, TypeError, ValueError) as error:
        raise ObserverObservabilityIntegrityError(
            f"checkpoint {checkpoint} sensor error bank replay failed"
        ) from error
    acceleration_bank, gyro_bank, raw_bank_sha256 = (
        _validate_full_sensor_bank(
            bank,
            context_seeds=context_seeds,
            full_steps=full_steps,
            lane_count=capture.lane_count,
            dt=capture.dt_seconds,
            registered_sensor_seed=seeds["sensor"],
            expected_sha256=metadata.error_bank_sha256,
            checkpoint=checkpoint,
        )
    )

    raw_force = np.asarray(capture.raw_specific_force_body)
    raw_gyro = np.asarray(capture.raw_angular_velocity_body)
    delivered_force = np.asarray(capture.delivered_specific_force_body)
    delivered_gyro = np.asarray(capture.delivered_angular_velocity_body)
    if any(
        array.dtype != np.dtype("<f4")
        or array.shape != (300, capture.lane_count, 3)
        for array in (raw_force, raw_gyro, delivered_force, delivered_gyro)
    ):
        raise ObserverObservabilityIntegrityError(
            f"checkpoint {checkpoint} sensor recurrence array metadata mismatch"
        )
    if (
        not torch.cuda.is_available()
        or torch.cuda.device_count() != 1
        or not torch.version.hip
    ):
        raise ObserverObservabilityIntegrityError(
            "sensor recurrence replay requires exactly one Radeon/ROCm GPU"
        )
    replay_device = torch.device("cuda", 0)
    no_op_force_exact = True
    no_op_gyro_exact = True
    try:
        raw_force_tensor = torch.from_numpy(
            np.array(raw_force, copy=True)
        ).to(device=replay_device)
        raw_gyro_tensor = torch.from_numpy(
            np.array(raw_gyro, copy=True)
        ).to(device=replay_device)
        acceleration_bank_device = acceleration_bank.to(device=replay_device)
        gyro_bank_device = gyro_bank.to(device=replay_device)
        replay_force_device = torch.empty_like(raw_force_tensor)
        replay_gyro_device = torch.empty_like(raw_gyro_tensor)
        for step in range(300):
            sample = batch_module.NativeIMUSample(
                specific_force_body=raw_force_tensor[step],
                angular_velocity_body=raw_gyro_tensor[step],
            )
            no_op = batch_module.apply_sensor_error(
                sample,
                acceleration_error=acceleration_bank_device[step],
                gyro_error=gyro_bank_device[step],
                enabled=False,
            )
            no_op_force_exact &= torch.equal(
                no_op.specific_force_body.contiguous().view(torch.int32),
                raw_force_tensor[step].contiguous().view(torch.int32),
            )
            no_op_gyro_exact &= torch.equal(
                no_op.angular_velocity_body.contiguous().view(torch.int32),
                raw_gyro_tensor[step].contiguous().view(torch.int32),
            )
            replayed = batch_module.apply_sensor_error(
                sample,
                acceleration_error=acceleration_bank_device[step],
                gyro_error=gyro_bank_device[step],
                enabled=True,
            )
            replay_force_device[step].copy_(replayed.specific_force_body)
            replay_gyro_device[step].copy_(replayed.angular_velocity_body)
        torch.cuda.synchronize(replay_device)
        replay_force = replay_force_device.detach().cpu().contiguous()
        replay_gyro = replay_gyro_device.detach().cpu().contiguous()
    except (ArithmeticError, RuntimeError, TypeError, ValueError) as error:
        raise ObserverObservabilityIntegrityError(
            f"checkpoint {checkpoint} raw-to-delivered replay failed"
        ) from error
    force_exact = _raw_tensor_equal_array(replay_force, delivered_force)
    gyro_exact = _raw_tensor_equal_array(replay_gyro, delivered_gyro)
    transform_changes_force = (
        replay_force.contiguous().numpy().tobytes(order="C")
        != raw_force.tobytes(order="C")
    )
    transform_changes_gyro = (
        replay_gyro.contiguous().numpy().tobytes(order="C")
        != raw_gyro.tobytes(order="C")
    )
    if (
        not no_op_force_exact
        or not no_op_gyro_exact
        or not force_exact
        or not gyro_exact
        or not transform_changes_force
        or not transform_changes_gyro
    ):
        raise ObserverObservabilityIntegrityError(
            f"checkpoint {checkpoint} raw-to-delivered sensor recurrence mismatch"
        )
    return {
        "status": "PASS",
        "implementation_source": batch_binding,
        "governance": governance_binding,
        "sealed_legacy_protocol": legacy_protocol_binding,
        "sealed_legacy_runtime": legacy_runtime,
        "transform_name": metadata.name,
        "transform_enabled": metadata.enabled,
        "profile_config_sha256": metadata.config_sha256,
        "error_bank_schema_version": metadata.error_bank_schema_version,
        "error_bank_sha256": metadata.error_bank_sha256,
        "error_bank_raw_bytes_sha256": raw_bank_sha256,
        "registered_sensor_seed": seeds["sensor"],
        "context_seeds": context_seeds,
        "transition_count": 300,
        "full_sensor_bank_step_count": full_steps,
        "captured_prefix_step_count": 300,
        "lane_count": capture.lane_count,
        "disabled_no_op_force_raw_bit_exact": no_op_force_exact,
        "disabled_no_op_gyro_raw_bit_exact": no_op_gyro_exact,
        "enabled_kill_gate_changes_force": transform_changes_force,
        "enabled_kill_gate_changes_gyro": transform_changes_gyro,
        "replayed_delivered_force_raw_bit_exact": force_exact,
        "replayed_delivered_gyro_raw_bit_exact": gyro_exact,
    }


def _load_checkpoint_inputs(
    protocol: Mapping[str, Any],
    *,
    checkpoint: str,
) -> tuple[Any, baseline_module.LoadedObserverBaselines, dict[str, Any], dict[str, Any]]:
    capture_records = protocol.get("capture_artifact_by_checkpoint")
    baseline_records = protocol.get("baseline_artifact_by_checkpoint")
    if not isinstance(capture_records, dict) or not isinstance(
        baseline_records,
        dict,
    ):
        raise ObserverObservabilityIntegrityError(
            "checkpoint capture/baseline registries must be objects"
        )
    if checkpoint not in capture_records or checkpoint not in baseline_records:
        raise ObserverObservabilityIntegrityError(
            f"checkpoint {checkpoint} is not fully registered"
        )
    capture_record = _validated_binding(
        capture_records[checkpoint],
        name=f"checkpoint {checkpoint} capture",
    )
    baseline_record = _validated_binding(
        baseline_records[checkpoint],
        name=f"checkpoint {checkpoint} baseline",
    )
    try:
        capture = capture_module.load_exact_native_observer_capture(
            capture_record["path"],
            expected_sha256=capture_record["sha256"],
        )
        baselines = baseline_module.load_baseline_artifact(
            baseline_record["path"],
            expected_sha256=baseline_record["sha256"],
        )
    except (
        OSError,
        TypeError,
        ValueError,
        capture_module.CaptureArtifactError,
        baseline_module.ObserverBaselineSealError,
    ) as error:
        raise ObserverObservabilityIntegrityError(
            f"checkpoint {checkpoint} strict input loading failed"
        ) from error
    if (
        capture.lane_count != 12
        or baselines.fit_only_bias_body_mps2.shape != (12, 3)
        or baselines.operational_bias_body_mps2.shape != (12, 3)
        or baselines.valid_transition_mask.shape != (300, 12)
        or capture.valid_transition_mask.dtype != np.bool_
        or baselines.valid_transition_mask.dtype != np.bool_
        or capture.valid_transition_mask.tobytes(order="C")
        != baselines.valid_transition_mask.tobytes(order="C")
        or baselines.baseline_provenance.capture_artifact_sha256
        != capture_record["sha256"]
        or baselines.input_provenance.capture_artifact_sha256
        != capture_record["sha256"]
    ):
        raise ObserverObservabilityIntegrityError(
            f"checkpoint {checkpoint} capture/baseline identity mismatch"
        )
    return capture, baselines, capture_record, baseline_record


def _fit_loaded(
    capture: Any,
    baselines: baseline_module.LoadedObserverBaselines,
    *,
    config: observer_module.FrozenVIOIMUObserverConfig,
) -> observer_module.FrozenVIOIMUObserverResult:
    arguments = _capture_inputs(capture)
    arguments.update(
        {
            "fit_only_calibrated_accelerometer_bias_body_mps2": (
                baselines.fit_only_bias_body_mps2
            ),
            "operational_calibrated_accelerometer_bias_body_mps2": (
                baselines.operational_bias_body_mps2
            ),
            "provenance": baselines.input_provenance,
            "baseline_provenance": baselines.baseline_provenance,
            "config": config,
        }
    )
    try:
        return observer_module.fit_frozen_vio_imu_observer(**arguments)
    except (ArithmeticError, TypeError, ValueError) as error:
        raise ObserverObservabilityIntegrityError(
            "frozen observer recomputation failed"
        ) from error


def _raw_fingerprint(value: Any) -> str:
    digest = hashlib.sha256()

    def update(item: Any) -> None:
        if dataclasses.is_dataclass(item) and not isinstance(item, type):
            digest.update(b"D")
            digest.update(type(item).__qualname__.encode("utf-8"))
            digest.update(b"\0")
            for field in dataclasses.fields(item):
                digest.update(field.name.encode("utf-8"))
                digest.update(b"\0")
                update(getattr(item, field.name))
            return
        if item is None:
            digest.update(b"N")
            return
        if type(item) is bool:
            digest.update(b"B1" if item else b"B0")
            return
        if type(item) is int:
            payload = str(item).encode("ascii")
            digest.update(b"I")
            digest.update(struct.pack("<Q", len(payload)))
            digest.update(payload)
            return
        if type(item) is float:
            digest.update(b"F")
            digest.update(struct.pack("<d", item))
            return
        if type(item) is str:
            payload = item.encode("utf-8")
            digest.update(b"S")
            digest.update(struct.pack("<Q", len(payload)))
            digest.update(payload)
            return
        if type(item) is tuple:
            digest.update(b"T")
            digest.update(struct.pack("<Q", len(item)))
            for member in item:
                update(member)
            return
        raise ObserverObservabilityIntegrityError(
            f"observer result contains unsupported type {type(item).__qualname__}"
        )

    update(value)
    return digest.hexdigest()


def _finite_float(value: Any, *, name: str) -> float | None:
    if type(value) is bool or not isinstance(value, (int, float)):
        raise ObserverObservabilityIntegrityError(f"{name} is not numeric")
    number = float(value)
    return number if math.isfinite(number) else None


def _state_record(state: observer_module.FrozenObserverState | None) -> dict[str, Any] | None:
    if state is None:
        return None
    return {
        "accelerometer_bias_body_mps2": [
            _finite_float(value, name="accelerometer bias")
            for value in state.accelerometer_bias_body_mps2
        ],
        "gyroscope_bias_body_rad_s": [
            _finite_float(value, name="gyroscope bias")
            for value in state.gyroscope_bias_body_rad_s
        ],
        "delta_roll_pitch_rad": [
            _finite_float(value, name="tilt")
            for value in state.delta_roll_pitch_rad
        ],
        "raw_fingerprint_sha256": _raw_fingerprint(state),
    }


def _certificate_record(
    certificate: observer_module.NormalizedJacobianCertificate | None,
) -> dict[str, Any] | None:
    if certificate is None:
        return None
    return {
        "state_order": list(certificate.state_order),
        "residual_row_count": certificate.residual_row_count,
        "state_dimension": certificate.state_dimension,
        "column_l2_norms": [
            _finite_float(value, name="certificate column norm")
            for value in certificate.column_l2_norms
        ],
        "normalized_singular_values_descending": [
            _finite_float(value, name="certificate singular value")
            for value in certificate.normalized_singular_values_descending
        ],
        "numerical_rank": certificate.numerical_rank,
        "required_rank": certificate.required_rank,
        "rank_tolerance": _finite_float(
            certificate.rank_tolerance,
            name="certificate rank tolerance",
        ),
        "normalized_sigma_ratio": _finite_float(
            certificate.normalized_sigma_ratio,
            name="certificate normalized sigma ratio",
        ),
        "minimum_normalized_sigma_ratio": _finite_float(
            certificate.minimum_normalized_sigma_ratio,
            name="certificate minimum sigma ratio",
        ),
        "normalized_condition_number": _finite_float(
            certificate.normalized_condition_number,
            name="certificate condition number",
        ),
        "maximum_normalized_condition_number": _finite_float(
            certificate.maximum_normalized_condition_number,
            name="certificate maximum condition number",
        ),
        "passed": certificate.passed,
    }


def _metric_record(metric: observer_module.CalRelativeMetric) -> dict[str, Any]:
    return {
        "candidate_rmse": _finite_float(
            metric.candidate_rmse,
            name="candidate RMSE",
        ),
        "calibrated_rmse": _finite_float(
            metric.calibrated_rmse,
            name="calibrated RMSE",
        ),
        "candidate_q95": _finite_float(
            metric.candidate_q95,
            name="candidate q95",
        ),
        "calibrated_q95": _finite_float(
            metric.calibrated_q95,
            name="calibrated q95",
        ),
        "rmse_ratio_to_fit_only_calibrated": _finite_float(
            metric.rmse_ratio_to_calibrated,
            name="RMSE ratio",
        ),
        "q95_ratio_to_fit_only_calibrated": _finite_float(
            metric.q95_ratio_to_calibrated,
            name="q95 ratio",
        ),
        "all_finite": metric.all_finite,
        "rmse_passed_by_core": metric.rmse_passed,
        "q95_passed_by_core": metric.q95_passed,
    }


def _raw_equal_float64(left: npt.ArrayLike, right: npt.ArrayLike) -> bool:
    left_array = np.asarray(left, dtype="<f8")
    right_array = np.asarray(right, dtype="<f8")
    return (
        left_array.shape == right_array.shape
        and left_array.tobytes(order="C") == right_array.tobytes(order="C")
    )


def _fallback_integrity(
    lane: observer_module.FrozenObserverLaneResult,
    *,
    operational_bias: npt.ArrayLike,
) -> dict[str, bool]:
    fallback = lane.exact_cal_fallback_state
    checks = {
        "accelerometer_bias_raw_bit_exact_operational_cal": _raw_equal_float64(
            fallback.accelerometer_bias_body_mps2,
            operational_bias,
        ),
        "gyroscope_bias_raw_bit_exact_positive_zero": _raw_equal_float64(
            fallback.gyroscope_bias_body_rad_s,
            np.zeros(3, dtype="<f8"),
        ),
        "tilt_raw_bit_exact_positive_zero": _raw_equal_float64(
            fallback.delta_roll_pitch_rad,
            np.zeros(2, dtype="<f8"),
        ),
    }
    if lane.qualified:
        if (
            lane.diagnostic_candidate_state is None
            or lane.deployment_state is not lane.diagnostic_candidate_state
        ):
            raise ObserverObservabilityIntegrityError(
                "qualified lane does not deploy its frozen candidate by identity"
            )
        candidate = object()
        calibrated = object()
        calls = 0

        def candidate_factory() -> object:
            nonlocal calls
            calls += 1
            return candidate

        selected = observer_module.select_qualified_or_exact_cal(
            lane_result=lane,
            candidate_factory=candidate_factory,
            calibrated=calibrated,
        )
        checks["qualified_dispatch_calls_candidate_once"] = (
            selected is candidate and calls == 1
        )
    else:
        if lane.deployment_state is not fallback:
            raise ObserverObservabilityIntegrityError(
                "rejected lane does not deploy exact Cal fallback by identity"
            )
        calibrated = object()

        def forbidden_candidate_factory() -> object:
            raise AssertionError(
                "rejected-lane candidate factory crossed the Cal fallback boundary"
            )

        try:
            selected = observer_module.select_qualified_or_exact_cal(
                lane_result=lane,
                candidate_factory=forbidden_candidate_factory,
                calibrated=calibrated,
            )
        except BaseException as error:
            raise ObserverObservabilityIntegrityError(
                "rejected lane evaluated candidate before exact Cal fallback"
            ) from error
        checks["rejected_dispatch_returns_calibrated_by_identity_without_candidate"] = (
            selected is calibrated
        )
        checks["deployment_state_raw_bit_exact_fallback"] = (
            _raw_fingerprint(lane.deployment_state)
            == _raw_fingerprint(fallback)
        )
    if not all(checks.values()):
        raise ObserverObservabilityIntegrityError(
            "exact Cal fallback or deployment dispatch integrity failed"
        )
    return checks


def _lane_audit(
    lane: observer_module.FrozenObserverLaneResult,
    *,
    operational_bias: npt.ArrayLike,
    gates: Mapping[str, int | float],
) -> dict[str, Any]:
    fallback_checks = _fallback_integrity(
        lane,
        operational_bias=operational_bias,
    )
    certificate = lane.full_fit_certificate
    split = lane.split_half_stability
    holdout = lane.holdout_qualification
    delta = holdout.delta_velocity_error_mps if holdout is not None else None
    rotation = holdout.rotation_geodesic_error_rad if holdout is not None else None
    rank_pass = (
        certificate is not None
        and certificate.numerical_rank == gates["required_state_rank"]
    )
    sigma_pass = (
        certificate is not None
        and math.isfinite(certificate.normalized_sigma_ratio)
        and certificate.normalized_sigma_ratio
        >= gates["minimum_normalized_sigma_ratio"]
    )
    delta_rmse_pass = (
        delta is not None
        and delta.all_finite
        and math.isfinite(delta.rmse_ratio_to_calibrated)
        and delta.rmse_ratio_to_calibrated
        <= gates["maximum_delta_v_rmse_ratio_vs_fit_only_cal"]
    )
    rotation_rmse_pass = (
        rotation is not None
        and rotation.all_finite
        and math.isfinite(rotation.rmse_ratio_to_calibrated)
        and rotation.rmse_ratio_to_calibrated
        <= gates["maximum_rotation_rmse_ratio_vs_fit_only_cal"]
    )
    delta_q95_pass = (
        delta is not None
        and delta.all_finite
        and math.isfinite(delta.q95_ratio_to_calibrated)
        and delta.q95_ratio_to_calibrated
        <= gates["maximum_q95_ratio_vs_fit_only_cal"]
    )
    rotation_q95_pass = (
        rotation is not None
        and rotation.all_finite
        and math.isfinite(rotation.q95_ratio_to_calibrated)
        and rotation.q95_ratio_to_calibrated
        <= gates["maximum_q95_ratio_vs_fit_only_cal"]
    )
    scientific_checks = {
        "provenance_eligible": lane.provenance_eligible,
        "full_fit_certificate_present_and_passed": (
            certificate is not None and certificate.passed
        ),
        "full_fit_rank_is_8": rank_pass,
        "full_fit_normalized_sigma_ratio_at_least_1e-3": sigma_pass,
        "split_half_stability_passed": split is not None and split.passed,
        "holdout_qualification_present": holdout is not None,
        "delta_velocity_rmse_ratio_at_most_0_90": delta_rmse_pass,
        "rotation_rmse_ratio_at_most_0_90": rotation_rmse_pass,
        "delta_velocity_q95_ratio_at_most_1_0": delta_q95_pass,
        "rotation_q95_ratio_at_most_1_0": rotation_q95_pass,
    }
    admitted = lane.qualified and all(scientific_checks.values())
    return {
        "lane_index": lane.lane_index,
        "admitted": admitted,
        "core_qualified": lane.qualified,
        "deployment_mode": lane.deployment_mode,
        "fit_sample_count": lane.fit_sample_count,
        "holdout_sample_count": lane.holdout_sample_count,
        "provenance_eligible": lane.provenance_eligible,
        "reject_reasons": list(lane.reject_reasons),
        "scientific_checks": scientific_checks,
        "fallback_integrity_checks": fallback_checks,
        "full_fit_certificate": _certificate_record(certificate),
        "split_half_stability": (
            None
            if split is None
            else {
                "passed": split.passed,
                "reject_reasons": list(split.reject_reasons),
                "accelerometer_bias_l2_mps2": _finite_float(
                    split.accelerometer_bias_l2_mps2,
                    name="split accelerometer bias difference",
                ),
                "gyroscope_bias_l2_rad_s": _finite_float(
                    split.gyroscope_bias_l2_rad_s,
                    name="split gyroscope bias difference",
                ),
                "tilt_geodesic_rad": _finite_float(
                    split.tilt_geodesic_rad,
                    name="split tilt difference",
                ),
                "first_half_certificate": _certificate_record(
                    split.first_half_certificate
                ),
                "second_half_certificate": _certificate_record(
                    split.second_half_certificate
                ),
            }
        ),
        "holdout_qualification": (
            None
            if holdout is None
            else {
                "sample_count": holdout.sample_count,
                "passed_by_core": holdout.passed,
                "reject_reasons": list(holdout.reject_reasons),
                "delta_velocity_error_mps": _metric_record(delta),
                "rotation_geodesic_error_rad": _metric_record(rotation),
            }
        ),
        "diagnostic_candidate_state": _state_record(
            lane.diagnostic_candidate_state
        ),
        "exact_cal_fallback_state": _state_record(
            lane.exact_cal_fallback_state
        ),
        "deployment_state": _state_record(lane.deployment_state),
    }


def _checkpoint_order(protocol: Mapping[str, Any]) -> list[str]:
    capture_contract = protocol.get("legacy_execution")
    frozen = protocol.get("frozen_config")
    capture_records = protocol.get("capture_artifact_by_checkpoint")
    baseline_records = protocol.get("baseline_artifact_by_checkpoint")
    if not isinstance(capture_records, dict) or not isinstance(
        baseline_records,
        dict,
    ):
        raise ObserverObservabilityIntegrityError(
            "protocol checkpoint registries must be objects"
        )
    governance_record = protocol.get("governance")
    if not isinstance(governance_record, dict):
        raise ObserverObservabilityIntegrityError(
            "protocol governance record must be an object"
        )
    try:
        governance = governance_module.load_strict_json(
            Path(governance_record["path"])
        )
    except (KeyError, OSError, TypeError, ValueError, governance_module.ObserverCaptureGovernanceError) as error:
        raise ObserverObservabilityIntegrityError(
            "cannot recover checkpoint order from frozen governance"
        ) from error
    order = governance.get("capture_contract", {}).get("checkpoint_order")
    if (
        not isinstance(order, list)
        or any(type(item) is not int for item in order)
        or len(order) != len(set(order))
    ):
        raise ObserverObservabilityIntegrityError(
            "frozen checkpoint order is invalid"
        )
    keys = [str(item) for item in order]
    if (
        set(keys) != set(capture_records)
        or set(keys) != set(baseline_records)
        or not isinstance(frozen, dict)
        or not isinstance(capture_contract, dict)
    ):
        raise ObserverObservabilityIntegrityError(
            "frozen checkpoint registries disagree"
        )
    return keys


def _protocol_record(path: Path) -> dict[str, Any]:
    return _validated_binding(
        governance_module.binding(path, name="validated audit protocol"),
        name="validated audit protocol",
    )


def evaluate_checkpoint(
    *,
    protocol_path: Path,
    protocol: Mapping[str, Any],
    checkpoint: str,
) -> dict[str, Any]:
    order = _checkpoint_order(protocol)
    if checkpoint not in order:
        raise ObserverObservabilityIntegrityError(
            f"checkpoint {checkpoint} is not in the frozen order"
        )
    config = _observer_config(protocol)
    gates = _audit_gates(protocol)
    capture, baselines, capture_record, baseline_record = (
        _load_checkpoint_inputs(protocol, checkpoint=checkpoint)
    )
    sensor_recurrence = _replay_frozen_sensor_transform(
        capture,
        protocol=protocol,
        checkpoint=checkpoint,
    )
    result = _fit_loaded(capture, baselines, config=config)

    # A second strict read and fit proves deterministic recurrence and catches
    # mutation of any loader-returned array between the two evaluations.
    repeat_capture, repeat_baselines, _, _ = _load_checkpoint_inputs(
        protocol,
        checkpoint=checkpoint,
    )
    repeat_result = _fit_loaded(
        repeat_capture,
        repeat_baselines,
        config=config,
    )
    result_fingerprint = _raw_fingerprint(result)
    repeat_fingerprint = _raw_fingerprint(repeat_result)
    if result_fingerprint != repeat_fingerprint:
        raise ObserverObservabilityIntegrityError(
            f"checkpoint {checkpoint} observer recurrence is not raw-bit exact"
        )
    if (
        not result.provenance_eligible
        or not result.baseline_provenance_eligible
        or result.provenance_reject_reasons
        or result.baseline_provenance_reject_reasons
        or len(result.lanes) != 12
    ):
        raise ObserverObservabilityIntegrityError(
            f"checkpoint {checkpoint} strict provenance/result identity failed"
        )
    lanes = [
        _lane_audit(
            lane,
            operational_bias=baselines.operational_bias_body_mps2[index],
            gates=gates,
        )
        for index, lane in enumerate(result.lanes)
    ]
    if any(lane["lane_index"] != index for index, lane in enumerate(lanes)):
        raise ObserverObservabilityIntegrityError(
            f"checkpoint {checkpoint} lane order mismatch"
        )
    admitted = sum(bool(lane["admitted"]) for lane in lanes)
    minimum = int(gates["minimum_admitted_lanes_per_checkpoint"])
    status = "PASS" if admitted >= minimum else "FAIL"
    return {
        "schema_version": CHECKPOINT_AUDIT_SCHEMA_VERSION,
        "status": status,
        "development_verdict": status,
        "simulation_only": True,
        "development_only": True,
        "formal_claim_eligible": False,
        "award_evidence_eligible": False,
        "formal_extension_permitted": False,
        "scientific_failure_process_return_code": 0,
        "checkpoint_seed": int(checkpoint),
        "protocol": _protocol_record(protocol_path),
        "capture_artifact": capture_record,
        "baseline_artifact": baseline_record,
        "strict_recomputation": {
            "strict_capture_loader_only": True,
            "strict_baseline_loader_only": True,
            "runtime_bind_or_rebind_used": False,
            "raw_to_delivered_sensor_transform_replayed": True,
            "fit_only_and_operational_baselines_separate": (
                baselines.fit_only_bias_body_mps2 is not baselines.operational_bias_body_mps2
            ),
            "capture_baseline_mask_raw_bit_exact": True,
            "observer_recurrence_raw_bit_exact": True,
            "first_result_raw_fingerprint_sha256": result_fingerprint,
            "repeat_result_raw_fingerprint_sha256": repeat_fingerprint,
        },
        "raw_to_delivered_sensor_recurrence": sensor_recurrence,
        "gates": gates,
        "admitted_lane_count": admitted,
        "lane_count": len(lanes),
        "minimum_admitted_lane_count": minimum,
        "all_lanes_admitted": admitted == len(lanes),
        "lanes": lanes,
        "recommendation": (
            "CHECKPOINT_OBSERVABILITY_GATE_PASS"
            if status == "PASS"
            else "STOP_CANDIDATE_A"
        ),
    }


def evaluate_aggregate(
    *,
    protocol_path: Path,
    protocol: Mapping[str, Any],
) -> dict[str, Any]:
    gates = _audit_gates(protocol)
    order = _checkpoint_order(protocol)
    expected_count = int(gates["checkpoint_count"])
    if len(order) != expected_count:
        raise ObserverObservabilityIntegrityError(
            "aggregate checkpoint count differs from the frozen gate"
        )

    # Deliberately ignore checkpoint JSON outputs. Each checkpoint is rebuilt
    # from its sealed capture and baseline artifact in this process.
    checkpoints = [
        evaluate_checkpoint(
            protocol_path=protocol_path,
            protocol=protocol,
            checkpoint=checkpoint,
        )
        for checkpoint in order
    ]
    admitted_by_checkpoint = {
        str(item["checkpoint_seed"]): int(item["admitted_lane_count"])
        for item in checkpoints
    }
    minimum_checkpoint = int(
        gates["minimum_admitted_lanes_per_checkpoint"]
    )
    total = sum(admitted_by_checkpoint.values())
    minimum_total = int(
        gates["minimum_admitted_lanes_across_three_checkpoints"]
    )
    checks = {
        "all_three_checkpoints_recomputed_from_sealed_inputs": (
            len(checkpoints) == expected_count
        ),
        "every_checkpoint_admits_at_least_9_of_12": all(
            count >= minimum_checkpoint
            for count in admitted_by_checkpoint.values()
        ),
        "aggregate_admits_at_least_30_of_36": total >= minimum_total,
    }
    status = "PASS" if all(checks.values()) else "FAIL"
    return {
        "schema_version": AGGREGATE_AUDIT_SCHEMA_VERSION,
        "status": status,
        "development_verdict": status,
        "simulation_only": True,
        "development_only": True,
        "formal_claim_eligible": False,
        "award_evidence_eligible": False,
        "formal_extension_permitted": False,
        "scientific_failure_process_return_code": 0,
        "protocol": _protocol_record(protocol_path),
        "checkpoint_order": [int(value) for value in order],
        "aggregate_recomputed_from_sealed_inputs": True,
        "checkpoint_output_json_was_not_trusted_or_read": True,
        "gates": gates,
        "checks": checks,
        "admitted_lane_count_by_checkpoint": admitted_by_checkpoint,
        "admitted_lane_count": total,
        "lane_count": sum(int(item["lane_count"]) for item in checkpoints),
        "minimum_admitted_lane_count": minimum_total,
        "checkpoint_audits": checkpoints,
        "recommendation": (
            "GO_TO_CAL_VS_OBSERVER_FRESH_TINY_SCOUT"
            if status == "PASS"
            else "STOP_CANDIDATE_A"
        ),
    }


def evaluate(
    *,
    protocol_path: Path,
    checkpoint: str,
    output_path: Path,
) -> dict[str, Any]:
    protocol_path = protocol_path.expanduser()
    protocol = _load_validated_protocol(protocol_path)
    _registered_output_path(
        protocol,
        checkpoint=checkpoint,
        requested=output_path,
    )
    if checkpoint == "aggregate":
        return evaluate_aggregate(
            protocol_path=protocol_path,
            protocol=protocol,
        )
    return evaluate_checkpoint(
        protocol_path=protocol_path,
        protocol=protocol,
        checkpoint=checkpoint,
    )


def _canonical_json_bytes(value: Mapping[str, Any]) -> bytes:
    try:
        return (
            json.dumps(
                value,
                allow_nan=False,
                ensure_ascii=False,
                separators=(",", ":"),
                sort_keys=True,
            ).encode("utf-8")
            + b"\n"
        )
    except (TypeError, ValueError) as error:
        raise ObserverObservabilityIntegrityError(
            "observer audit output is not canonical finite JSON"
        ) from error


def write_json_exclusive_readonly(
    path: Path,
    payload: Mapping[str, Any],
) -> dict[str, Any]:
    """Write one fresh regular file through O_EXCL|O_NOFOLLOW, then chmod 0444."""

    try:
        output_path = governance_module.normalized_absolute_path(
            path.expanduser(),
            name="observer audit output",
        )
    except governance_module.ObserverCaptureGovernanceError as error:
        raise ObserverObservabilityIntegrityError(
            "observer audit output path is invalid"
        ) from error
    data = _canonical_json_bytes(payload)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        governance_module.normalized_absolute_path(
            output_path,
            name="observer audit output",
        )
    except governance_module.ObserverCaptureGovernanceError as error:
        raise ObserverObservabilityIntegrityError(
            "observer audit output parent became unsafe"
        ) from error
    flags = (
        os.O_WRONLY
        | os.O_CREAT
        | os.O_EXCL
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_NOFOLLOW", 0)
    )
    try:
        descriptor = os.open(output_path, flags, 0o600)
    except OSError as error:
        raise ObserverObservabilityIntegrityError(
            "observer audit output slot cannot be created fresh"
        ) from error
    created = os.fstat(descriptor)
    try:
        if not stat.S_ISREG(created.st_mode) or created.st_nlink != 1:
            raise ObserverObservabilityIntegrityError(
                "observer audit output is not a single-link regular file"
            )
        view = memoryview(data)
        while view:
            written = os.write(descriptor, view)
            if written <= 0:
                raise OSError("exclusive observer audit write made no progress")
            view = view[written:]
        os.fsync(descriptor)
        os.fchmod(descriptor, 0o444)
        os.fsync(descriptor)
        after = os.fstat(descriptor)
        pathname = os.lstat(output_path)
        if (
            pathname.st_dev != after.st_dev
            or pathname.st_ino != after.st_ino
            or pathname.st_nlink != 1
            or stat.S_ISLNK(pathname.st_mode)
            or stat.S_IMODE(after.st_mode) != 0o444
        ):
            raise ObserverObservabilityIntegrityError(
                "observer audit output identity or mode changed while writing"
            )
    except BaseException:
        try:
            pathname = os.lstat(output_path)
        except OSError:
            pathname = None
        os.close(descriptor)
        if (
            pathname is not None
            and pathname.st_dev == created.st_dev
            and pathname.st_ino == created.st_ino
        ):
            try:
                output_path.unlink()
            except OSError:
                pass
        raise
    else:
        os.close(descriptor)
    return {
        "path": str(output_path),
        "sha256": hashlib.sha256(data).hexdigest(),
        "size_bytes": len(data),
        "mode": "0444",
    }


def _forensic_payload(
    error: BaseException,
    *,
    protocol_path: Path,
    checkpoint: str,
    output_path: Path,
) -> dict[str, Any]:
    return {
        "schema_version": FORENSIC_SCHEMA_VERSION,
        "status": "INTEGRITY_FAIL",
        "development_verdict": "INTEGRITY_FAIL",
        "simulation_only": True,
        "development_only": True,
        "formal_claim_eligible": False,
        "award_evidence_eligible": False,
        "formal_extension_permitted": False,
        "process_return_code": 2,
        "requested_protocol": str(protocol_path),
        "requested_checkpoint": checkpoint,
        "requested_output": str(output_path),
        "error": {
            "type": type(error).__name__,
            "message": str(error),
        },
        "recommendation": "PRESERVE_INPUTS_AND_DIAGNOSE",
    }


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        payload = evaluate(
            protocol_path=args.protocol,
            checkpoint=args.checkpoint,
            output_path=args.output,
        )
    except BaseException as error:
        if isinstance(error, (KeyboardInterrupt, SystemExit)):
            raise
        payload = _forensic_payload(
            error,
            protocol_path=args.protocol,
            checkpoint=args.checkpoint,
            output_path=args.output,
        )
        try:
            written = write_json_exclusive_readonly(args.output, payload)
        except (OSError, ObserverObservabilityIntegrityError):
            return 2
        print(
            json.dumps(
                {
                    "output": written["path"],
                    "sha256": written["sha256"],
                    "status": payload["status"],
                    "process_return_code": 2,
                },
                sort_keys=True,
            ),
            flush=True,
        )
        return 2
    try:
        written = write_json_exclusive_readonly(args.output, payload)
    except (OSError, ObserverObservabilityIntegrityError):
        return 2
    print(
        json.dumps(
            {
                "output": written["path"],
                "sha256": written["sha256"],
                "status": payload["status"],
                "process_return_code": 0,
            },
            sort_keys=True,
        ),
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
