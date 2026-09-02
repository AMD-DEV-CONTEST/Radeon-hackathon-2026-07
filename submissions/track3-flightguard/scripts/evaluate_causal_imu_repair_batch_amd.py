#!/usr/bin/env python3
"""Run and merge the formal native-IMU FlightGuard repair re-attack.

Each ``run`` invocation owns one arm/checkpoint/lane-role pass.  GPU passes are
therefore externally serializable.  ``merge`` validates all 24 immutable pass
files and is the only path that may emit ``repair_claim_eligible=true``.
"""

from __future__ import annotations

import argparse
import ast
import copy
import hashlib
import inspect
import io
import json
import math
import os
import sys
import tarfile
import tempfile
import time
import zipfile
from collections.abc import Mapping, Sequence
from dataclasses import asdict, replace
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Protocol

import numpy as np
import torch

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent
for import_root in (SCRIPT_DIR, PROJECT_ROOT, PROJECT_ROOT / "src"):
    if str(import_root) not in sys.path:
        sys.path.insert(0, str(import_root))

GENESIS_SOURCE_ROOT = Path("/workspace/genesis-v1.2.3-src-b")
GENESIS_RUNTIME_HOME = "/root"

from evaluate_causal_falsifier_batch_amd import (
    context_gate_offsets as r5_context_gate_offsets,
)
from evaluate_causal_falsifier_batch_amd import (
    context_noise as r5_context_noise,
)
from evaluate_causal_imu_hardening_amd import (
    FORMAL_REALISTIC_SENSOR_PROFILE,
    NOISE_FREE_API_FRAME_PROFILE,
    ControllerVisibleState,
    FrozenAccelerometerCalibration,
    HardeningArm,
    NativeIMUBinding,
    NativeIMUSample,
    apply_dead_mask_to_outcome,
    attach_native_imu_prebuild,
    calibrate_visible_accelerometer_bias,
    clone_native_imu_reading,
    commit_post_dropout_transition,
    dispatch_post_dropout_controller,
    exact_patch_off_noop_gate,
    extract_controller_visible_state,
    hardening_arm_spec,
    make_frozen_arm_estimator,
    prior_quarantine_step_evidence,
    sensor_on_kill_magnitude_gate,
)

from flightguard.falsifier import LATENT_NAMES, canonical_fault_candidate
from flightguard.imu import perturb_imu
from flightguard.online_context import (
    FrozenAffineDelayConfig,
    FrozenAffineDelayContext,
)
from tools.build_causal_imu_repair_protocol import (
    CLAIM_BOUNDARY,
    RepairProtocolError,
    validate_physical_dropout_replay_contract,
)
from tools.build_v6_observer_capture_protocol import (
    CAPTURE_PROTOCOL_SCHEMA_VERSION as V6_OBSERVER_CAPTURE_PROTOCOL_SCHEMA_VERSION,
    CAPTURE_PROTOCOL_STATUS as V6_OBSERVER_CAPTURE_PROTOCOL_STATUS,
)


class PassiveObserverCaptureHook(Protocol):
    """Receive detached pre-dropout observations without owning simulator state."""

    def record_initial_vio(
        self,
        *,
        quaternion_body_to_world: torch.Tensor,
        velocity_world: torch.Tensor,
    ) -> None: ...

    def append_transition(
        self,
        *,
        step_index: int,
        logical_transition_end_time_ns: int,
        raw_specific_force_body: torch.Tensor,
        raw_angular_velocity_body: torch.Tensor,
        delivered_specific_force_body: torch.Tensor,
        delivered_angular_velocity_body: torch.Tensor,
        next_quaternion_body_to_world: torch.Tensor,
        next_velocity_world: torch.Tensor,
        valid_transition_mask: torch.Tensor,
    ) -> None: ...


def _capture_initial_vio(
    hook: PassiveObserverCaptureHook | None,
    *,
    quaternion_body_to_world: torch.Tensor,
    velocity_world: torch.Tensor,
) -> None:
    if hook is None:
        return
    hook.record_initial_vio(
        quaternion_body_to_world=quaternion_body_to_world.detach().clone(),
        velocity_world=velocity_world.detach().clone(),
    )


def _capture_observer_transition(
    hook: PassiveObserverCaptureHook | None,
    *,
    step_index: int,
    dt_s: float,
    raw_sample: NativeIMUSample,
    delivered_sample: NativeIMUSample,
    next_quaternion_body_to_world: torch.Tensor,
    next_velocity_world: torch.Tensor,
    valid_transition_mask: torch.Tensor,
) -> None:
    if hook is None:
        return
    hook.append_transition(
        step_index=step_index,
        logical_transition_end_time_ns=round(
            (step_index + 1) * dt_s * 1_000_000_000
        ),
        raw_specific_force_body=raw_sample.specific_force_body.detach().clone(),
        raw_angular_velocity_body=raw_sample.angular_velocity_body.detach().clone(),
        delivered_specific_force_body=(
            delivered_sample.specific_force_body.detach().clone()
        ),
        delivered_angular_velocity_body=(
            delivered_sample.angular_velocity_body.detach().clone()
        ),
        next_quaternion_body_to_world=(
            next_quaternion_body_to_world.detach().clone()
        ),
        next_velocity_world=next_velocity_world.detach().clone(),
        valid_transition_mask=valid_transition_mask.detach().clone(),
    )


SCHEMA_VERSION = "flightguard-causal-imu-repair-pass-v1"
SUMMARY_SCHEMA_VERSION = "flightguard-causal-imu-repair-summary-v1"
PROTOCOL_SCHEMA_VERSION = "flightguard-causal-imu-repair-protocol-v1"
RAW_EVIDENCE_SCHEMA_VERSION = "flightguard-causal-imu-raw-evidence-v1"
OBSERVER_CAPTURE_STOP_SCHEMA_VERSION = (
    "flightguard-causal-imu-observer-capture-stop-v1"
)
OBSERVER_CAPTURE_TRANSITION_COUNT = 300
V6_OBSERVER_CAPTURE_LEGACY_EXECUTION_KEYS = frozenset(
    {
        "protocol",
        "protocol_header",
        "by_checkpoint",
        "runtime_contract",
    }
)
V6_OBSERVER_CAPTURE_CHECKPOINT_EXECUTION_KEYS = frozenset(
    {
        "lane_role",
        "dummy_pass_output",
        "frozen_sensor_transform",
    }
)
V6_OBSERVER_CAPTURE_SOURCE_ROLE = "batch_evaluator"
V6_OBSERVER_CAPTURE_ERROR_BANK_SCHEMA_VERSION = (
    "flightguard-deterministic-sensor-error-bank-v1"
)
PRIOR_QUARANTINE_RAW_EVIDENCE_SCHEMA_VERSION = (
    "flightguard-causal-imu-prior-quarantine-raw-evidence-v2"
)
RAW_EVIDENCE_DESCRIPTOR_SCHEMA_VERSION = "flightguard-causal-imu-raw-evidence-descriptor-v1"
FROZEN_STATUS = "PRE_REGISTERED_AFTER_HIDDEN_SELECTION_BEFORE_FIRST_NATIVE_IMU_REPAIR_GPU_RUN"
PROTOCOL_VERSION = "causal-imu-repair-v1"
RECOVERY_PROTOCOL_SCHEMA_VERSION = (
    "flightguard-causal-imu-repair-zero-output-recovery-protocol-v1"
)
RECOVERY_PROTOCOL_VERSION = "causal-imu-repair-v1-zero-output-code-recovery-v1"
RECOVERY_FROZEN_STATUS = (
    "PRE_REGISTERED_TRANSPARENT_ZERO_OUTPUT_CODE_ONLY_RECOVERY_BEFORE_RERUN"
)
PARTIAL_RECOVERY_PROTOCOL_SCHEMA_VERSION = (
    "flightguard-causal-imu-repair-partial-observation-recovery-protocol-v1"
)
PARTIAL_RECOVERY_PROTOCOL_VERSION = (
    "causal-imu-repair-v1-partial-observation-fresh-rng-recovery-v1"
)
PARTIAL_RECOVERY_FROZEN_STATUS = (
    "PRE_REGISTERED_TRANSPARENT_FRESH_RNG_RECOVERY_AFTER_PARTIAL_"
    "SCIENTIFIC_OBSERVATION_BEFORE_RERUN"
)
PROTOCOL_TOP_LEVEL_FIELDS = frozenset(
    {
        "schema_version",
        "protocol_version",
        "protocol_filename",
        "status",
        "simulation_only",
        "claim_boundary",
        "selection",
        "selection_rule_semantics",
        "r5_baseline_contract",
        "native_imu_runtime_preflight",
        "runtime",
        "physical_dropout_replay_contract",
        "arms",
        "lane_roles",
        "repair_evaluation_rng",
        "sensor_contract",
        "causal_integrity",
        "acceptance_gates",
        "fixed_budget",
        "execution_environment",
        "implementation_contract",
        "registered_outputs",
    }
)
R5_SOURCE_EVALUATOR_SHA256 = "69362970fdbbfc36b893eb5bbc1a29ee9fcfdd58e4160f92433f599c475a8d89"
R5_SOURCE_ARCHIVE_NAME = "flightguard-causal-falsifier-v1-r5-formal-clean2.tar.gz"
R5_SOURCE_ARCHIVE_SHA256 = "e647401b93e0f2b79edcbae6f1d40bf61e8c8d70248072e50c3cc5c5d894cfbc"
R5_SOURCE_EVALUATOR_MEMBER = "scripts/evaluate_causal_falsifier_batch_amd.py"
R5_CONTEXT_NOISE_SOURCE_SHA256 = "8fbc79ca72a256d3353ab6b62cde64d6ff2d4ecc513f266509a659ebdc011e2e"
R5_CONTEXT_GATE_OFFSETS_SOURCE_SHA256 = (
    "3c4d4f1c6bf66388b77ab67fedf271d608e5b19a14a61a7b20d04185731fd6fd"
)
R5_BASELINE_RUNTIME = {
    "angular_velocity_bias_rad_s": [0.01, -0.01, 0.005],
    "angular_velocity_noise_std_rad_s": 0.02,
    "attitude_bias_deg": [0.2, -0.1, 0.15],
    "attitude_noise_std_deg": 0.5,
    "context_bias_limit_mps2": 1.5,
    "context_delay_score_tolerance": 0.0001,
    "context_fit_steps": 200,
    "context_gamma_limit": 0.6,
    "context_max_delay_steps": 6,
    "context_min_excitation": 0.05,
    "context_min_fit_samples": 100,
    "context_min_score_improvement_absolute": 0.0001,
    "context_min_score_improvement_relative": 0.05,
    "context_min_score_samples": 50,
    "context_ridge": 0.05,
    "context_score_residual_quantile": 0.95,
    "controller_profile": "robust_z",
    "delay_history_max_steps": 6,
    "dropout_start_step": 300,
    "dropout_steps": 500,
    "dt_s": 0.01,
    "gate_lookthrough_m": 0.5,
    "gate_y_jitter_m": 0.25,
    "gate_z_jitter_m": 0.1,
    "max_downward_vertical_acceleration_mps2": 3.0,
    "max_upward_vertical_acceleration_mps2": 5.0,
    "online_context_mode": "frozen_affine_delay",
    "safety_supervisor": "off",
    "steps": 800,
}
ARMS = tuple(arm.value for arm in HardeningArm)
LANE_ROLES = ("fault", "nominal")
TRACE_FIELDS = (
    "truth_position",
    "truth_velocity",
    "truth_quaternion",
    "truth_angular_velocity",
    "estimated_position",
    "estimated_velocity",
    "estimated_quaternion",
    "estimated_angular_velocity",
    "issued_action",
    "applied_action_before_step",
    "active_before_step",
)
REPLAY_FIELDS = (
    "step",
    "fault_onset",
    "truth_position",
    "truth_quaternion",
    "estimated_position",
    "issued_action",
    "applied_action",
    "terminal",
    "gate_index",
)
RAW_EVIDENCE_FIELDS = (
    "schema_version",
    "arm",
    "checkpoint_seed",
    "lane_role",
    "candidate_id",
    "context_seeds",
    "step_index",
    "gate_count",
    "truth_position",
    "truth_velocity",
    "truth_quaternion",
    "truth_angular_velocity",
    "estimated_position",
    "estimated_velocity",
    "estimated_quaternion",
    "estimated_angular_velocity",
    "issued_action",
    "applied_action",
    "active_before_step",
    "terminal",
    "failed",
    "success",
    "gates_passed",
    "gate_index",
    "position_error_squared_m2",
    "scored_position_error_squared_m2",
    "applied_action_saturated",
)
PRIOR_QUARANTINE_RAW_EVIDENCE_FIELDS = (
    *RAW_EVIDENCE_FIELDS,
    "innovation_norm",
    "quarantine_bound",
    "newly_quarantined",
    "prior_quarantined",
    "prior_quarantine_count",
)
PASS_INTEGRITY_CHECKS = (
    "backend_is_amdgpu",
    "visible_gpu_count_is_one",
    "torch_hip_nonempty",
    "all_outputs_finite",
    "all_contexts_active_at_freeze",
    "all_contexts_qualified_at_freeze",
    "frozen_r5_baseline_structural_parity_pass",
    "frozen_context_has_zero_post_freeze_observation_updates",
    "calibration_gate_pass",
    "post_step_native_calibration_frame_alignment_raw_bit_exact",
    "fault_activated_exactly_once_after_first_onset_action",
    "scheduled_targets_persist_to_end",
    "native_sensor_attached_prebuild",
    "noise_free_native_profile_exact",
    "deterministic_formal_error_bank_available",
    "sensor_error_bank_generator_code_bound",
    "sensor_error_bank_consumed_once_per_step",
    "native_sensor_read_once_per_step",
    "policy_sensor_commit_schedule_exact",
    "pre_dropout_trace_available",
    "action_only_exact_frozen_r5_shadow_parity",
    "sensor_on_kill_magnitude_pass",
    "zero_bank_exact_and_active_bank_kill_pass",
    "patch_off_structural_noop_pass",
    "demo_replay_records_every_step",
    "applied_action_saturation_within_gate",
)
PRIOR_QUARANTINE_PASS_INTEGRITY_CHECKS = (
    "prior_quarantine_threshold_has_zero_post_freeze_updates",
    "prior_quarantine_mechanism_matches_runtime_and_arm",
    "prior_quarantine_raw_state_recurrence_pass",
)
REQUIRED_REPAIR_IMPLEMENTATION_FILES = frozenset(
    {
        "scripts/evaluate_causal_imu_repair_batch_amd.py",
        "scripts/evaluate_causal_imu_hardening_amd.py",
        "scripts/evaluate_causal_falsifier_batch_amd.py",
        "tools/build_causal_imu_repair_selection.py",
        "tools/build_causal_imu_repair_protocol.py",
        "tools/build_formal_discovery_seal.py",
        "tools/run_lane_aligned_falsifier_campaign.py",
        "tools/run_lane_aligned_falsifier_hidden.py",
        "src/flightguard/causal_imu.py",
        "src/flightguard/genesis_env.py",
        "src/flightguard/falsifier.py",
        "src/flightguard/racer_asset.py",
        "src/flightguard/dynamics.py",
        "src/flightguard/controller.py",
        "src/flightguard/domain_randomization.py",
        "src/flightguard/gate_math.py",
        "src/flightguard/imu.py",
        "src/flightguard/online_context.py",
    }
)


class RepairEvaluationError(RuntimeError):
    """Raised when a formal repair artifact is not trustworthy."""


def _bootstrap_genesis_runtime() -> None:
    """Bind the frozen Genesis tree for the isolated capture child."""

    genesis_init = GENESIS_SOURCE_ROOT / "genesis" / "__init__.py"
    if not genesis_init.is_file():
        raise RepairEvaluationError(
            f"frozen Genesis source root is unavailable: {GENESIS_SOURCE_ROOT}"
        )
    os.environ["HOME"] = GENESIS_RUNTIME_HOME
    genesis_root = str(GENESIS_SOURCE_ROOT)
    sys.path[:] = [entry for entry in sys.path if entry != genesis_root]
    sys.path.insert(0, genesis_root)


def prior_quarantine_protocol_enabled(runtime: Mapping[str, Any]) -> bool:
    """Resolve the explicit opt-in while keeping every legacy runtime disabled."""

    value = runtime.get("causal_prior_quarantine_enabled", False)
    if type(value) is not bool:
        raise RepairEvaluationError("causal_prior_quarantine_enabled must be bool when present")
    return value


def prior_quarantine_enabled_for_arm(
    runtime: Mapping[str, Any],
    arm: HardeningArm | str,
) -> bool:
    """Enable the optional mechanism only in the preregistered patch arm."""

    resolved_arm = HardeningArm(arm)
    return (
        prior_quarantine_protocol_enabled(runtime)
        and resolved_arm is HardeningArm.CAUSAL_IMU_PATCH
    )


def registered_sensor_seed(
    sensor_contract: Mapping[str, Any],
    *,
    checkpoint_seed: int,
) -> int:
    """Resolve either the legacy scalar or strict per-checkpoint sensor seed."""

    seed_map = sensor_contract.get("registered_noise_seed_by_checkpoint")
    value = (
        seed_map.get(str(checkpoint_seed))
        if isinstance(seed_map, dict)
        else sensor_contract.get("registered_noise_seed")
    )
    if type(value) is not int or value < 0:
        raise RepairEvaluationError("registered sensor seed is invalid")
    return value


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    run = subparsers.add_parser("run")
    run.add_argument("--protocol", type=Path, required=True)
    run.add_argument("--arm", choices=ARMS, required=True)
    run.add_argument("--checkpoint-seed", type=int, required=True)
    run.add_argument("--lane-role", choices=LANE_ROLES, required=True)
    run.add_argument("--output", type=Path, required=True)
    merge = subparsers.add_parser("merge")
    merge.add_argument("--protocol", type=Path, required=True)
    merge.add_argument("--output", type=Path, required=True)
    return parser.parse_args()


def reject_nonfinite(value: str) -> None:
    raise ValueError(f"non-finite JSON constant is forbidden: {value}")


def reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key is forbidden: {key}")
        result[key] = value
    return result


def load_strict_json(path: Path) -> dict[str, Any]:
    value = json.loads(
        path.read_text(encoding="utf-8"),
        parse_constant=reject_nonfinite,
        object_pairs_hook=reject_duplicate_keys,
    )
    if not isinstance(value, dict):
        raise TypeError(f"JSON root must be an object: {path}")
    return value


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _deterministic_npz_bytes(arrays: Mapping[str, np.ndarray]) -> bytes:
    """Return a byte-stable, pickle-free NPZ archive."""

    output = io.BytesIO()
    with zipfile.ZipFile(
        output,
        mode="w",
        compression=zipfile.ZIP_DEFLATED,
        compresslevel=6,
        strict_timestamps=True,
    ) as archive:
        for name in sorted(arrays):
            value = np.asarray(arrays[name])
            if value.ndim:
                value = np.ascontiguousarray(value)
            if value.dtype.hasobject:
                raise RepairEvaluationError(f"raw evidence object dtype is forbidden: {name}")
            payload = io.BytesIO()
            np.lib.format.write_array(
                payload,
                value,
                allow_pickle=False,
            )
            member = zipfile.ZipInfo(
                filename=f"{name}.npy",
                date_time=(1980, 1, 1, 0, 0, 0),
            )
            member.compress_type = zipfile.ZIP_DEFLATED
            member.external_attr = 0o100444 << 16
            archive.writestr(
                member,
                payload.getvalue(),
                compress_type=zipfile.ZIP_DEFLATED,
                compresslevel=6,
            )
    return output.getvalue()


def _write_exclusive_or_verify_identical(path: Path, payload: bytes) -> None:
    """Atomically publish bytes without ever replacing an existing artifact."""

    path = path.expanduser().resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    expected_sha256 = hashlib.sha256(payload).hexdigest()
    if path.exists():
        if path.is_file() and sha256_file(path) == expected_sha256:
            return
        raise FileExistsError(f"refusing to overwrite non-identical output: {path}")
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.",
        suffix=".tmp",
        dir=path.parent,
    )
    temporary_path = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        try:
            os.link(temporary_path, path)
        except FileExistsError:
            if not path.is_file() or sha256_file(path) != expected_sha256:
                raise
    finally:
        temporary_path.unlink(missing_ok=True)


def _array_manifest(arrays: Mapping[str, np.ndarray]) -> dict[str, dict[str, Any]]:
    return {
        name: {
            "dtype": str(np.asarray(value).dtype),
            "shape": list(np.asarray(value).shape),
        }
        for name, value in sorted(arrays.items())
    }


def write_raw_evidence_npz(
    path: Path,
    *,
    output_root: Path,
    arrays: Mapping[str, np.ndarray],
) -> dict[str, Any]:
    """Publish one immutable pass evidence archive and return its JSON binding."""

    path = path.expanduser().resolve()
    output_root = output_root.expanduser().resolve()
    field_set = set(arrays)
    legacy_field_set = set(RAW_EVIDENCE_FIELDS)
    quarantine_field_set = set(PRIOR_QUARANTINE_RAW_EVIDENCE_FIELDS)
    if field_set != legacy_field_set and field_set != quarantine_field_set:
        raise RepairEvaluationError("raw evidence array field set mismatch")
    raw_schema = np.asarray(arrays["schema_version"])
    expected_schema = (
        PRIOR_QUARANTINE_RAW_EVIDENCE_SCHEMA_VERSION
        if field_set == quarantine_field_set
        else RAW_EVIDENCE_SCHEMA_VERSION
    )
    if (
        raw_schema.shape != ()
        or raw_schema.dtype.kind != "U"
        or raw_schema.item() != expected_schema
    ):
        raise RepairEvaluationError("raw evidence schema does not match its field set")
    if not path.is_relative_to(output_root):
        raise RepairEvaluationError("raw evidence path escapes registered output root")
    payload = _deterministic_npz_bytes(arrays)
    _write_exclusive_or_verify_identical(path, payload)
    return {
        "schema_version": RAW_EVIDENCE_DESCRIPTOR_SCHEMA_VERSION,
        "relative_path": path.relative_to(output_root).as_posix(),
        "sha256": hashlib.sha256(payload).hexdigest(),
        "archive_format": "deterministic-pickle-free-npz-v1",
        "raw_evidence_schema_version": expected_schema,
        "context_count": int(np.asarray(arrays["context_seeds"]).shape[0]),
        "step_count": int(np.asarray(arrays["step_index"]).shape[0]),
        "context_seeds": np.asarray(arrays["context_seeds"]).tolist(),
        "arrays": _array_manifest(arrays),
    }


def canonical_json_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def _is_sha256(value: Any) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


def callable_source_sha256(function: Any) -> str:
    source = inspect.getsource(function)
    return hashlib.sha256(source.encode("utf-8")).hexdigest()


def _top_level_function_source_sha256(
    source_bytes: bytes,
    *,
    function_name: str,
) -> str:
    """Hash exact UTF-8 source lines, including the terminal newline."""

    source = source_bytes.decode("utf-8")
    module = ast.parse(source)
    matches = [
        node
        for node in module.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == function_name
    ]
    if len(matches) != 1:
        raise RepairEvaluationError(f"frozen R5 helper {function_name!r} is not unique")
    node = matches[0]
    if node.end_lineno is None:
        raise RepairEvaluationError(f"frozen R5 helper {function_name!r} has no end line")
    lines = source.splitlines(keepends=True)
    exact_source = "".join(lines[node.lineno - 1 : node.end_lineno])
    return hashlib.sha256(exact_source.encode("utf-8")).hexdigest()


def r5_baseline_reference_code_contract() -> dict[str, Any]:
    """Bind current helpers to independently extracted frozen R5 source."""

    project_root = Path(__file__).resolve().parent.parent
    archive_path = project_root / R5_SOURCE_ARCHIVE_NAME
    if not archive_path.is_file():
        raise RepairEvaluationError(f"frozen R5 source archive is missing: {archive_path}")
    archive_sha256 = sha256_file(archive_path)
    with tarfile.open(archive_path, mode="r:gz") as archive:
        member = archive.getmember(R5_SOURCE_EVALUATOR_MEMBER)
        stream = archive.extractfile(member)
        if stream is None:
            raise RepairEvaluationError("frozen R5 evaluator member is unreadable")
        evaluator_bytes = stream.read()
    evaluator_sha256 = hashlib.sha256(evaluator_bytes).hexdigest()
    archive_hashes = {
        "context_noise": _top_level_function_source_sha256(
            evaluator_bytes,
            function_name="context_noise",
        ),
        "context_gate_offsets": _top_level_function_source_sha256(
            evaluator_bytes,
            function_name="context_gate_offsets",
        ),
    }
    current_hashes = {
        "context_noise": callable_source_sha256(r5_context_noise),
        "context_gate_offsets": callable_source_sha256(r5_context_gate_offsets),
    }
    checks = {
        "source_archive_sha256_matches_frozen_r5": (archive_sha256 == R5_SOURCE_ARCHIVE_SHA256),
        "archive_evaluator_sha256_matches_frozen_r5": (
            evaluator_sha256 == R5_SOURCE_EVALUATOR_SHA256
        ),
        "archive_context_noise_source_matches_frozen_r5": (
            archive_hashes["context_noise"] == R5_CONTEXT_NOISE_SOURCE_SHA256
        ),
        "archive_context_gate_offsets_source_matches_frozen_r5": (
            archive_hashes["context_gate_offsets"] == R5_CONTEXT_GATE_OFFSETS_SOURCE_SHA256
        ),
        "current_context_noise_raw_matches_archive": (
            current_hashes["context_noise"] == archive_hashes["context_noise"]
        ),
        "current_context_gate_offsets_raw_matches_archive": (
            current_hashes["context_gate_offsets"] == archive_hashes["context_gate_offsets"]
        ),
    }
    return {
        "status": "PASS" if all(checks.values()) else "FAIL",
        "source_evaluator_sha256": R5_SOURCE_EVALUATOR_SHA256,
        "source_archive": {
            "relative_path": R5_SOURCE_ARCHIVE_NAME,
            "sha256": archive_sha256,
            "evaluator_member": R5_SOURCE_EVALUATOR_MEMBER,
            "evaluator_member_sha256": evaluator_sha256,
        },
        "hash_mode": "exact UTF-8 top-level function lines including terminal newline",
        "expected_function_source_sha256": {
            "context_noise": R5_CONTEXT_NOISE_SOURCE_SHA256,
            "context_gate_offsets": R5_CONTEXT_GATE_OFFSETS_SOURCE_SHA256,
        },
        "archive_function_source_sha256": archive_hashes,
        "current_function_source_sha256": current_hashes,
        "checks": checks,
    }


def sha256_source_tree(root: Path) -> dict[str, Any]:
    resolved = root.resolve()
    files = []
    for path in resolved.rglob("*"):
        relative = path.relative_to(resolved)
        if any(part in {".git", "__pycache__", ".pytest_cache"} for part in relative.parts):
            continue
        if path.is_file() and path.suffix not in {".pyc", ".pyo"}:
            files.append((relative.as_posix(), path))
    digest = hashlib.sha256()
    total_bytes = 0
    for name, path in sorted(files):
        digest.update(name.encode("utf-8"))
        digest.update(b"\0")
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                total_bytes += len(chunk)
                digest.update(chunk)
        digest.update(b"\0")
    return {
        "sha256": digest.hexdigest(),
        "file_count": len(files),
        "total_bytes": total_bytes,
    }


def _raw_tensor_equal(left: torch.Tensor, right: torch.Tensor) -> bool:
    if left.shape != right.shape or left.dtype != right.dtype or left.device != right.device:
        return False
    if not torch.equal(left, right):
        return False
    return not left.is_floating_point() or torch.equal(
        torch.signbit(left),
        torch.signbit(right),
    )


def _raw_float32_mismatch_count(
    left: torch.Tensor,
    right: torch.Tensor,
) -> int:
    if (
        left.shape != right.shape
        or left.dtype != torch.float32
        or right.dtype != torch.float32
        or left.device != right.device
    ):
        return max(left.numel(), right.numel(), 1)
    return int(
        (
            left.detach().contiguous().view(torch.int32)
            != right.detach().contiguous().view(torch.int32)
        )
        .sum()
        .item()
    )


def verify_implementation_contract(
    protocol: Mapping[str, Any],
    *,
    project_root: Path,
) -> dict[str, str]:
    contract = protocol.get("implementation_contract")
    if not isinstance(contract, dict) or contract.get("project_root") != str(
        project_root.resolve()
    ):
        raise RepairEvaluationError("implementation project-root binding mismatch")
    files = contract.get("files")
    if (
        not isinstance(files, dict)
        or not files
        or not REQUIRED_REPAIR_IMPLEMENTATION_FILES.issubset(files)
    ):
        raise RepairEvaluationError(
            "implementation file hashes omit a transitive repair dependency"
        )
    verified = {}
    for relative_name, expected in sorted(files.items()):
        if not isinstance(relative_name, str) or not isinstance(expected, str):
            raise RepairEvaluationError("invalid implementation hash entry")
        relative = Path(relative_name)
        path = (project_root / relative).resolve()
        if (
            relative.is_absolute()
            or ".." in relative.parts
            or not path.is_relative_to(project_root)
            or not path.is_file()
            or sha256_file(path) != expected
        ):
            raise RepairEvaluationError(f"implementation SHA256 mismatch: {relative_name}")
        verified[relative_name] = expected
    return verified


def verify_seed_separation_contract(
    rng: Mapping[str, Any],
) -> dict[str, Any]:
    """Recompute repair-vs-recovery RNG separation from bound protocol bytes."""

    separation = rng.get("seed_separation")
    if not isinstance(separation, dict):
        raise RepairEvaluationError("repair seed-separation proof is missing")
    binding = separation.get("bound_hidden_recovery_protocol")
    if not isinstance(binding, dict) or set(binding) != {
        "path",
        "sha256",
        "version",
        "status",
    }:
        raise RepairEvaluationError("hidden recovery seed binding is malformed")
    hidden_path = Path(str(binding.get("path"))).expanduser().resolve()
    if (
        binding.get("version") != "flightguard-causal-falsifier-v1-r6-hidden-recovery-v1-20260729"
        or binding.get("status")
        != "PRE_REGISTERED_TRANSPARENT_CODE_ONLY_RECOVERY_AFTER_PARTIAL_R6_EXECUTION"
        or not hidden_path.is_file()
        or not _is_sha256(binding.get("sha256"))
        or sha256_file(hidden_path) != binding["sha256"]
    ):
        raise RepairEvaluationError("hidden recovery seed binding mismatch")
    hidden_protocol = load_strict_json(hidden_path)
    hidden_execution = hidden_protocol.get("hidden_execution")
    if (
        hidden_protocol.get("schema_version") != "flightguard-causal-hidden-recovery-protocol-v1"
        or hidden_protocol.get("protocol_version") != binding["version"]
        or hidden_protocol.get("status") != binding["status"]
        or not isinstance(hidden_execution, dict)
    ):
        raise RepairEvaluationError("bound hidden recovery protocol identity mismatch")
    context_banks = hidden_execution.get("context_seed_banks")
    genesis_matrix = hidden_execution.get("genesis_seed_matrix")
    replay_context = hidden_execution.get("replay_context_seeds")
    replay_genesis = hidden_execution.get("replay_genesis_seeds")
    sign_flip = hidden_execution.get("sign_flip_seed")
    bootstrap = hidden_execution.get("bootstrap_seed")
    if (
        not isinstance(context_banks, list)
        or any(not isinstance(bank, list) for bank in context_banks)
        or not isinstance(genesis_matrix, list)
        or any(not isinstance(row, list) for row in genesis_matrix)
        or not isinstance(replay_context, list)
        or not isinstance(replay_genesis, list)
        or type(sign_flip) is not int
        or type(bootstrap) is not int
    ):
        raise RepairEvaluationError("bound hidden recovery seed roles are incomplete")
    hidden_roles = {
        "context": [seed for bank in context_banks for seed in bank],
        "genesis": [seed for row in genesis_matrix for seed in row],
        "replay_context": list(replay_context),
        "replay_genesis": list(replay_genesis),
        "sign_flip": [sign_flip],
        "bootstrap": [bootstrap],
    }
    context_seed_banks = rng.get("checkpoint_context_seed_banks")
    genesis_seeds = rng.get("checkpoint_genesis_seeds")
    if not isinstance(context_seed_banks, dict) or not isinstance(genesis_seeds, dict):
        raise RepairEvaluationError("repair seed roles are missing")
    repair_roles = {
        "evaluation_context": [
            seed
            for checkpoint_seed in (30, 31, 32)
            for seed in context_seed_banks.get(str(checkpoint_seed), [])
        ],
        "genesis": [genesis_seeds.get(str(seed)) for seed in (30, 31, 32)],
        "sensor_noise": [FORMAL_REALISTIC_SENSOR_PROFILE.matched_noise_seed],
    }
    if any(
        type(seed) is not int or seed < 0
        for roles in (hidden_roles, repair_roles)
        for values in roles.values()
        for seed in values
    ):
        raise RepairEvaluationError("repair or hidden seed role contains an invalid seed")
    hidden_values = [seed for values in hidden_roles.values() for seed in values]
    repair_values = [seed for values in repair_roles.values() for seed in values]
    intersection = sorted(set(hidden_values).intersection(repair_values))
    checks = {
        "repair_seed_roles_pairwise_disjoint": (len(repair_values) == len(set(repair_values))),
        "all_bound_hidden_seed_roles_pairwise_disjoint": (
            len(hidden_values) == len(set(hidden_values))
        ),
        "repair_vs_all_bound_hidden_seed_roles_zero_intersection": (not intersection),
    }
    expected = {
        "status": "PASS",
        "checks": checks,
        "bound_hidden_recovery_protocol": binding,
        "repair_seed_roles": repair_roles,
        "bound_hidden_seed_roles": hidden_roles,
        "repair_seed_count": len(repair_values),
        "bound_hidden_seed_count": len(hidden_values),
        "intersection": intersection,
        "checkpoint_model_seeds_excluded_from_rng_comparison": [30, 31, 32],
        "checkpoint_model_seed_exclusion_reason": (
            "30/31/32 identify frozen model checkpoints reused by design; "
            "they are not repair evaluation RNG streams"
        ),
    }
    if separation != expected or not all(checks.values()):
        raise RepairEvaluationError(
            "repair seed-separation proof does not match bound recovery seeds"
        )
    return expected


def verify_partial_attempt_seed_separation_contract(
    protocol: Mapping[str, Any],
) -> dict[str, Any]:
    """Recompute the fresh repair RNG contract from the superseded v3 protocol."""

    from tools.build_causal_imu_repair_partial_recovery import (
        NEW_CONTEXT_SEEDS,
        NEW_GENESIS_SEEDS,
        NEW_SENSOR_NOISE_SEED,
    )
    from tools.build_causal_imu_repair_partial_recovery import (
        load_strict_json as load_partial_recovery_json,
    )

    technical = protocol.get("technical_recovery")
    rng = protocol.get("repair_evaluation_rng")
    sensor = protocol.get("sensor_contract")
    if not all(isinstance(value, dict) for value in (technical, rng, sensor)):
        raise RepairEvaluationError("partial-attempt RNG sections are missing")
    governance_path = Path(str(technical.get("path"))).expanduser().resolve()
    governance = load_partial_recovery_json(governance_path)
    failed_protocol_path = Path(
        str(governance.get("failed_attempt", {}).get("protocol", {}).get("path"))
    ).expanduser().resolve()
    failed_protocol = load_strict_json(failed_protocol_path)
    failed_rng = failed_protocol.get("repair_evaluation_rng")
    if not isinstance(failed_rng, dict):
        raise RepairEvaluationError("superseded v3 RNG section is missing")
    old_separation = verify_seed_separation_contract(failed_rng)
    hidden_roles = old_separation["bound_hidden_seed_roles"]
    fresh_roles = {
        "evaluation_context": [
            seed for values in NEW_CONTEXT_SEEDS.values() for seed in values
        ],
        "genesis": list(NEW_GENESIS_SEEDS.values()),
        "sensor_noise": [NEW_SENSOR_NOISE_SEED],
    }
    fresh_values = [seed for values in fresh_roles.values() for seed in values]
    hidden_values = [
        seed for values in hidden_roles.values() for seed in values
    ]
    intersection = sorted(set(fresh_values).intersection(hidden_values))
    checks = {
        "repair_seed_roles_pairwise_disjoint": (
            len(fresh_values) == len(set(fresh_values))
        ),
        "all_bound_hidden_seed_roles_pairwise_disjoint": (
            len(hidden_values) == len(set(hidden_values))
        ),
        "repair_vs_all_bound_hidden_seed_roles_zero_intersection": (
            not intersection
        ),
    }
    expected = {
        "status": "PASS",
        "checks": checks,
        "bound_hidden_recovery_protocol": old_separation[
            "bound_hidden_recovery_protocol"
        ],
        "repair_seed_roles": fresh_roles,
        "bound_hidden_seed_roles": hidden_roles,
        "repair_seed_count": len(fresh_values),
        "bound_hidden_seed_count": len(hidden_values),
        "intersection": intersection,
        "checkpoint_model_seeds_excluded_from_rng_comparison": [30, 31, 32],
        "checkpoint_model_seed_exclusion_reason": (
            "30/31/32 identify frozen model checkpoints reused by design; "
            "they are not repair evaluation RNG streams"
        ),
    }
    fresh_governance = governance.get("fresh_rng_recovery")
    if (
        rng.get("fresh_after_hidden_selection") is not True
        or rng.get("checkpoint_context_seed_banks") != NEW_CONTEXT_SEEDS
        or rng.get("checkpoint_genesis_seeds") != NEW_GENESIS_SEEDS
        or sensor.get("registered_noise_seed") != NEW_SENSOR_NOISE_SEED
        or rng.get("seed_separation") != expected
        or not all(checks.values())
        or not isinstance(fresh_governance, dict)
        or fresh_governance.get("status") != "PASS"
        or fresh_governance.get("fresh_seed_roles") != fresh_roles
        or not isinstance(fresh_governance.get("checks"), dict)
        or not all(fresh_governance["checks"].values())
    ):
        raise RepairEvaluationError(
            "partial-attempt fresh RNG differs from frozen governance"
        )
    return expected


def validate_zero_output_recovery_governance(
    protocol: Mapping[str, Any],
) -> dict[str, Any]:
    technical = protocol.get("technical_recovery")
    expected_fields = {
        "path",
        "sha256",
        "size_bytes",
        "schema_version",
        "status",
        "pristine_first_look_claimed",
        "scientific_results_observed",
        "failed_protocol_sha256",
        "failed_queue_sha256",
        "failed_queue_fingerprint",
        "scientific_payload_sha256",
    }
    if not isinstance(technical, dict) or set(technical) != expected_fields:
        raise RepairEvaluationError("recovery governance binding field set mismatch")
    path_value = technical.get("path")
    if not isinstance(path_value, str):
        raise RepairEvaluationError("recovery governance path is invalid")
    unresolved_path = Path(path_value).expanduser()
    if unresolved_path.is_symlink():
        raise RepairEvaluationError("recovery governance must not be a symlink")
    governance_path = unresolved_path.resolve()
    if (
        not governance_path.is_file()
        or sha256_file(governance_path) != technical.get("sha256")
        or governance_path.stat().st_size != technical.get("size_bytes")
    ):
        raise RepairEvaluationError("recovery governance file binding mismatch")
    from tools.build_causal_imu_repair_recovery import (
        RECOVERY_STATUS,
        build_recovery_governance,
        scientific_payload_sha256,
    )
    from tools.build_causal_imu_repair_recovery import (
        SCHEMA_VERSION as RECOVERY_GOVERNANCE_SCHEMA,
    )
    from tools.build_causal_imu_repair_recovery import (
        canonical_json_bytes as recovery_canonical_json_bytes,
    )
    from tools.build_causal_imu_repair_recovery import (
        load_strict_json as load_recovery_json,
    )

    governance = load_recovery_json(governance_path)
    failed = governance.get("failed_attempt")
    recovery = governance.get("recovery")
    checks = governance.get("checks")
    if (
        governance.get("schema_version") != RECOVERY_GOVERNANCE_SCHEMA
        or governance.get("status") != RECOVERY_STATUS
        or governance.get("simulation_only") is not True
        or governance.get("pristine_first_look_claimed") is not False
        or governance.get("scientific_results_observed") is not False
        or not isinstance(failed, dict)
        or not isinstance(recovery, dict)
        or not isinstance(checks, dict)
        or not checks
        or not all(value is True for value in checks.values())
    ):
        raise RepairEvaluationError("recovery governance payload mismatch")
    rebuilt = build_recovery_governance(
        failed_protocol_path=Path(failed["protocol"]["path"]),
        failed_queue_path=Path(failed["queue"]["path"]),
        failed_state_path=Path(failed["state"]["path"]),
        failed_attempt_ledger_path=Path(failed["attempt_ledger"]["path"]),
        failed_job_log_path=Path(failed["job_log"]["path"]),
        failed_runner_log_path=Path(failed["runner_log"]["path"]),
        failed_project_root=Path(failed["project_root"]),
        recovery_project_root=Path(recovery["project_root"]),
    )
    if recovery_canonical_json_bytes(rebuilt) != recovery_canonical_json_bytes(governance):
        raise RepairEvaluationError("recovery governance does not recompute exactly")
    expected_binding = {
        "path": str(governance_path),
        "sha256": sha256_file(governance_path),
        "size_bytes": governance_path.stat().st_size,
        "schema_version": governance["schema_version"],
        "status": governance["status"],
        "pristine_first_look_claimed": False,
        "scientific_results_observed": False,
        "failed_protocol_sha256": failed["protocol"]["sha256"],
        "failed_queue_sha256": failed["queue"]["sha256"],
        "failed_queue_fingerprint": failed["queue"]["fingerprint"],
        "scientific_payload_sha256": governance["scientific_payload_binding"]["sha256"],
    }
    if (
        technical != expected_binding
        or Path(recovery["project_root"]).resolve()
        != Path(__file__).resolve().parent.parent
        or scientific_payload_sha256(protocol)
        != governance["scientific_payload_binding"]["sha256"]
    ):
        raise RepairEvaluationError("recovery governance/scientific payload binding mismatch")
    return expected_binding


def validate_partial_attempt_recovery_governance(
    protocol: Mapping[str, Any],
) -> dict[str, Any]:
    """Recompute the transparent partial-attempt governance without GPU work."""

    from tools.build_causal_imu_repair_partial_recovery import (
        scientific_invariant_sha256,
    )
    from tools.build_causal_imu_repair_partial_recovery_protocol import (
        technical_recovery_binding,
        validate_partial_recovery_governance,
    )

    technical = protocol.get("technical_recovery")
    if not isinstance(technical, dict):
        raise RepairEvaluationError(
            "partial-attempt recovery governance binding is missing"
        )
    path_value = technical.get("path")
    if not isinstance(path_value, str):
        raise RepairEvaluationError(
            "partial-attempt recovery governance path is invalid"
        )
    unresolved_path = Path(path_value).expanduser()
    if unresolved_path.is_symlink():
        raise RepairEvaluationError(
            "partial-attempt recovery governance must not be a symlink"
        )
    governance_path = unresolved_path.resolve()
    output_root = Path(
        str(protocol.get("registered_outputs", {}).get("output_root"))
    ).expanduser().resolve()
    try:
        governance, binding = validate_partial_recovery_governance(
            governance_path,
            project_root=PROJECT_ROOT,
            output_root=output_root,
        )
    except (OSError, TypeError, ValueError, RuntimeError) as error:
        raise RepairEvaluationError(
            "partial-attempt recovery governance failed validation"
        ) from error
    expected = technical_recovery_binding(governance, binding)
    if (
        technical != expected
        or scientific_invariant_sha256(protocol)
        != governance["scientific_invariant_binding"]["failed_v3_sha256"]
    ):
        raise RepairEvaluationError(
            "partial-attempt governance/scientific invariant binding mismatch"
        )
    return expected


def validate_protocol(
    protocol: Mapping[str, Any],
    *,
    protocol_path: Path,
) -> dict[str, Any]:
    header = (
        protocol.get("schema_version"),
        protocol.get("protocol_version"),
        protocol.get("status"),
    )
    from tools.build_causal_imu_repair_v5_scout_protocol import (
        FROZEN_STATUS as V5_SCOUT_STATUS,
    )
    from tools.build_causal_imu_repair_v5_scout_protocol import (
        PROTOCOL_SCHEMA_VERSION as V5_SCOUT_SCHEMA,
    )
    from tools.build_causal_imu_repair_v5_scout_protocol import (
        PROTOCOL_VERSION as V5_SCOUT_VERSION,
    )
    from tools.build_causal_imu_repair_v5_scout_protocol import (
        validate_scout_protocol,
    )

    if header == (V5_SCOUT_SCHEMA, V5_SCOUT_VERSION, V5_SCOUT_STATUS):
        return validate_scout_protocol(protocol, protocol_path=protocol_path)
    primary_header = (PROTOCOL_SCHEMA_VERSION, PROTOCOL_VERSION, FROZEN_STATUS)
    recovery_header = (
        RECOVERY_PROTOCOL_SCHEMA_VERSION,
        RECOVERY_PROTOCOL_VERSION,
        RECOVERY_FROZEN_STATUS,
    )
    partial_recovery_header = (
        PARTIAL_RECOVERY_PROTOCOL_SCHEMA_VERSION,
        PARTIAL_RECOVERY_PROTOCOL_VERSION,
        PARTIAL_RECOVERY_FROZEN_STATUS,
    )
    if header not in {
        primary_header,
        recovery_header,
        partial_recovery_header,
    }:
        raise RepairEvaluationError("repair protocol header mismatch")
    expected_fields = set(PROTOCOL_TOP_LEVEL_FIELDS)
    if header in {recovery_header, partial_recovery_header}:
        expected_fields.add("technical_recovery")
    if (
        set(protocol) != expected_fields
        or protocol.get("simulation_only") is not True
        or protocol.get("claim_boundary") != CLAIM_BOUNDARY
        or protocol.get("arms") != list(ARMS)
        or protocol.get("lane_roles") != list(LANE_ROLES)
    ):
        raise RepairEvaluationError("repair protocol header mismatch")
    legacy_runtime = protocol.get("runtime")
    if isinstance(legacy_runtime, dict) and prior_quarantine_protocol_enabled(
        legacy_runtime
    ):
        raise RepairEvaluationError(
            "legacy repair protocol header does not authorize causal prior quarantine"
        )
    if header == partial_recovery_header:
        validate_partial_attempt_recovery_governance(protocol)
    elif header == recovery_header:
        validate_zero_output_recovery_governance(protocol)
    elif "technical_recovery" in protocol:
        raise RepairEvaluationError("primary repair protocol carries recovery governance")
    runtime = protocol.get("runtime")
    selection = protocol.get("selection")
    rng = protocol.get("repair_evaluation_rng")
    sensor = protocol.get("sensor_contract")
    outputs = protocol.get("registered_outputs")
    r5_baseline = protocol.get("r5_baseline_contract")
    checkpoints = None if not isinstance(selection, dict) else selection.get("checkpoints")
    if not all(
        isinstance(value, dict) for value in (runtime, selection, rng, sensor, outputs, r5_baseline)
    ) or not isinstance(checkpoints, list):
        raise RepairEvaluationError("repair protocol sections are missing")
    checkpoint_seeds = [record.get("seed") for record in checkpoints]
    if checkpoint_seeds != [30, 31, 32]:
        raise RepairEvaluationError("repair checkpoint set must be 30/31/32")
    candidate = canonical_candidate(selection)
    if candidate.get("algorithm") != "cem":
        raise RepairEvaluationError("repair candidate must be the selected CEM rank-0 record")
    for name, binding in (
        ("selection", selection),
        ("discovery seal", selection.get("discovery_seal")),
        ("hidden summary", selection.get("hidden_summary")),
        ("native preflight", protocol.get("native_imu_runtime_preflight")),
    ):
        if not isinstance(binding, dict):
            raise RepairEvaluationError(f"{name} binding is missing")
        path = Path(str(binding.get("path"))).expanduser().resolve()
        if (
            not path.is_file()
            or not _is_sha256(binding.get("sha256"))
            or sha256_file(path) != binding["sha256"]
        ):
            raise RepairEvaluationError(f"{name} file or SHA256 mismatch")
    native_preflight_path = (
        Path(str(protocol["native_imu_runtime_preflight"]["path"])).expanduser().resolve()
    )
    native_preflight = load_strict_json(native_preflight_path)
    native_runtime = native_preflight.get("native_imu_runtime_preflight")
    outer_checks = native_preflight.get("checks")
    runtime_checks = None if not isinstance(native_runtime, dict) else native_runtime.get("checks")
    attachment = None if not isinstance(native_runtime, dict) else native_runtime.get("attachment")
    preflight_environment = (
        None
        if not isinstance(native_runtime, dict)
        else native_runtime.get("execution_environment")
    )
    preflight_genesis = (
        None
        if not isinstance(preflight_environment, dict)
        else preflight_environment.get("genesis")
    )
    preflight_tree = (
        None if not isinstance(preflight_genesis, dict) else preflight_genesis.get("source_tree")
    )
    preflight_racer = (
        None
        if not isinstance(preflight_environment, dict)
        else preflight_environment.get("racer_asset")
    )
    if (
        native_preflight.get("status") != "PASS"
        or native_preflight.get("simulation_only") is not True
        or not isinstance(outer_checks, dict)
        or not outer_checks
        or not all(value is True for value in outer_checks.values())
        or not isinstance(native_runtime, dict)
        or native_runtime.get("status") != "PASS"
        or native_runtime.get("simulation_only") is not True
        or native_runtime.get("repair_score_eligible") is not False
        or native_runtime.get("backend") != "amdgpu"
        or native_runtime.get("schema_version")
        != protocol["native_imu_runtime_preflight"].get("runtime_schema_version")
        or not isinstance(runtime_checks, dict)
        or not runtime_checks
        or not all(value is True for value in runtime_checks.values())
        or not isinstance(attachment, dict)
        or attachment.get("sensor_profile_sha256")
        != NOISE_FREE_API_FRAME_PROFILE.canonical_sha256()
        or attachment.get("sensor_attached_before_scene_build") is not True
        or attachment.get("scene_built_exactly_by_helper") is not True
        or not isinstance(preflight_genesis, dict)
        or not isinstance(preflight_tree, dict)
        or preflight_tree.get("sha256")
        != protocol.get("execution_environment", {}).get("genesis_source_tree_sha256")
        or preflight_genesis.get("version")
        != protocol.get("execution_environment", {}).get("genesis_version")
        or not isinstance(preflight_racer, dict)
        or preflight_racer.get("flightguard_correction_applied") is not True
        or preflight_racer.get("corrected_sha256")
        != protocol.get("execution_environment", {}).get("corrected_racer_urdf_sha256")
        or protocol["native_imu_runtime_preflight"].get("genesis_version")
        != preflight_genesis.get("version")
        or protocol["native_imu_runtime_preflight"].get("genesis_source_tree_sha256")
        != preflight_tree.get("sha256")
        or protocol["native_imu_runtime_preflight"].get("corrected_racer_urdf_sha256")
        != preflight_racer.get("corrected_sha256")
    ):
        raise RepairEvaluationError("bound native IMU preflight is not PASS")
    for checkpoint_seed in checkpoint_seeds:
        checkpoint_record(selection, checkpoint_seed=checkpoint_seed)
    if (
        any(runtime.get(key) != value for key, value in R5_BASELINE_RUNTIME.items())
        or runtime.get("minimum_calibration_samples") != 128
        or runtime.get("maximum_action_delay_steps") != 6
    ):
        raise RepairEvaluationError("repair runtime differs from frozen semantics")
    physical_dropout = protocol.get("physical_dropout_replay_contract")
    schedule_npz = (
        None if not isinstance(physical_dropout, dict) else physical_dropout.get("schedule_npz")
    )
    schedule_metadata = (
        None
        if not isinstance(physical_dropout, dict)
        else physical_dropout.get("schedule_metadata")
    )
    source_provenance = (
        None
        if not isinstance(physical_dropout, dict)
        else physical_dropout.get("source_provenance")
    )
    physical_eligibility = (
        None
        if not isinstance(physical_dropout, dict)
        else physical_dropout.get("physical_provenance_eligibility")
    )
    physical_ros_bag = (
        None
        if not isinstance(source_provenance, dict)
        else source_provenance.get("physical_ros_bag")
    )
    raw_trace_npz = (
        None if not isinstance(source_provenance, dict) else source_provenance.get("raw_trace_npz")
    )
    raw_trace_metadata = (
        None
        if not isinstance(source_provenance, dict)
        else source_provenance.get("raw_trace_metadata")
    )
    exact_reextraction = (
        None
        if not isinstance(source_provenance, dict)
        else source_provenance.get("exact_reextraction")
    )
    if (
        not isinstance(schedule_npz, dict)
        or not isinstance(schedule_metadata, dict)
        or not isinstance(physical_ros_bag, dict)
        or not isinstance(raw_trace_npz, dict)
        or not isinstance(raw_trace_metadata, dict)
        or not isinstance(exact_reextraction, dict)
        or not isinstance(physical_eligibility, dict)
        or physical_dropout.get("status") != "PASS"
    ):
        raise RepairEvaluationError("physical dropout replay binding is missing")
    try:
        recomputed_physical_dropout = validate_physical_dropout_replay_contract(
            Path(str(schedule_npz.get("path"))),
            Path(str(schedule_metadata.get("path"))),
            Path(str(physical_ros_bag.get("path"))),
            Path(str(raw_trace_npz.get("path"))),
            Path(str(raw_trace_metadata.get("path"))),
            Path(str(exact_reextraction.get("raw_trace_npz_path"))),
            Path(str(exact_reextraction.get("raw_trace_metadata_path"))),
            physical_eligibility.get("exact_raw_reextraction_performed_onsite_attested"),
            runtime=runtime,
        )
    except (RepairProtocolError, OSError, ValueError) as error:
        raise RepairEvaluationError("physical dropout replay binding failed validation") from error
    if physical_dropout != recomputed_physical_dropout:
        raise RepairEvaluationError("physical dropout replay binding differs from source artifacts")
    source_binding = r5_baseline.get("source_protocol")
    reference_code = r5_baseline.get("reference_helper_code")
    source_files = r5_baseline.get("source_implementation_files_sha256")
    unchanged_shared = r5_baseline.get("unchanged_shared_files_sha256")
    if (
        not isinstance(source_binding, dict)
        or not isinstance(reference_code, dict)
        or not isinstance(source_files, dict)
        or not isinstance(unchanged_shared, dict)
        or r5_baseline.get("source_evaluator_sha256") != R5_SOURCE_EVALUATOR_SHA256
        or r5_baseline.get("source_archive") != reference_code.get("source_archive")
        or source_files.get("scripts/evaluate_causal_falsifier_batch_amd.py")
        != R5_SOURCE_EVALUATOR_SHA256
        or unchanged_shared
        != {
            name: source_files.get(name)
            for name in (
                "src/flightguard/online_context.py",
                "src/flightguard/imu.py",
                "src/flightguard/controller.py",
                "src/flightguard/dynamics.py",
            )
        }
        or r5_baseline.get("runtime") != R5_BASELINE_RUNTIME
        or reference_code != r5_baseline_reference_code_contract()
        or reference_code.get("status") != "PASS"
    ):
        raise RepairEvaluationError("frozen R5 baseline contract mismatch")
    source_path = Path(str(source_binding.get("path"))).expanduser().resolve()
    if (
        source_binding.get("protocol_version")
        != "flightguard-causal-falsifier-v1-r5-formal-20260729"
        or not source_path.is_file()
        or not _is_sha256(source_binding.get("sha256"))
        or sha256_file(source_path) != source_binding["sha256"]
    ):
        raise RepairEvaluationError("frozen R5 source protocol binding mismatch")
    source_protocol = load_strict_json(source_path)
    if (
        source_protocol.get("status")
        != "PRE_REGISTERED_AFTER_R4_STRUCTURAL_PASS_BEFORE_FIRST_R5_SEARCH_GPU_RUN"
        or source_protocol.get("protocol_version") != source_binding["protocol_version"]
        or source_protocol.get("runtime", {}).get("steps") != 800
    ):
        raise RepairEvaluationError("bound R5 source protocol is invalid")
    if (
        sensor.get("formal_error_profile", {}).get("sha256")
        != FORMAL_REALISTIC_SENSOR_PROFILE.canonical_sha256()
    ):
        raise RepairEvaluationError("formal sensor error profile SHA256 mismatch")
    if (
        sensor.get("native_api_profile", {}).get("sha256")
        != NOISE_FREE_API_FRAME_PROFILE.canonical_sha256()
    ):
        raise RepairEvaluationError("native API profile SHA256 mismatch")
    if header == partial_recovery_header:
        from tools.build_causal_imu_repair_partial_recovery import (
            NEW_CONTEXT_SEEDS,
            NEW_GENESIS_SEEDS,
            NEW_SENSOR_NOISE_SEED,
        )

        expected_registered_noise_seed = NEW_SENSOR_NOISE_SEED
        expected_context_seed_banks = NEW_CONTEXT_SEEDS
        expected_genesis_seeds = NEW_GENESIS_SEEDS
    else:
        expected_registered_noise_seed = (
            FORMAL_REALISTIC_SENSOR_PROFILE.matched_noise_seed
        )
        expected_context_seed_banks = {
            str(checkpoint_seed): list(
                range(161_000 + 100 * index, 161_012 + 100 * index)
            )
            for index, checkpoint_seed in enumerate((30, 31, 32))
        }
        expected_genesis_seeds = {
            str(checkpoint_seed): 162_000 + index
            for index, checkpoint_seed in enumerate((30, 31, 32))
        }
    if (
        sensor.get("genesis_native_noise_matching_claimed") is not False
        or sensor.get("formal_error_bank_raw_bit_match_required") is not True
        or sensor.get("registered_noise_seed")
        != expected_registered_noise_seed
        or sensor.get("zero_error_bank_must_raw_exact_reproduce_native_sample") is not True
        or sensor.get("registered_error_bank_must_change_estimator_input_and_estimate") is not True
        or sensor.get("post_read_error_bank_generator_code_sha256")
        != sensor_error_bank_generator_code_sha256()
    ):
        raise RepairEvaluationError("sensor-noise matching contract is not fail-closed")
    if (
        rng.get("fresh_after_hidden_selection") is not True
        or rng.get("checkpoint_context_seed_banks") != expected_context_seed_banks
        or rng.get("checkpoint_genesis_seeds") != expected_genesis_seeds
    ):
        raise RepairEvaluationError("repair evaluation RNG differs from frozen semantics")
    if header == partial_recovery_header:
        seed_separation = verify_partial_attempt_seed_separation_contract(
            protocol
        )
    else:
        seed_separation = verify_seed_separation_contract(rng)
    transparent_recovery = selection.get("transparent_recovery")
    if (
        selection.get("hidden_recovery_protocol")
        != seed_separation["bound_hidden_recovery_protocol"]
        or not isinstance(transparent_recovery, dict)
        or transparent_recovery.get("pristine_first_look_claimed") is not False
        or transparent_recovery.get("protocol") != seed_separation["bound_hidden_recovery_protocol"]
    ):
        raise RepairEvaluationError("repair selection and hidden recovery seed binding differ")
    protocol_hash = sha256_file(protocol_path)
    expected_budget = 4 * 2 * 3 * 1 * 12 * 800
    budget = protocol.get("fixed_budget")
    if (
        not isinstance(budget, dict)
        or budget.get("total_transitions") != expected_budget
        or budget.get("pass_count") != 24
        or budget.get("transitions_per_pass") != 9_600
    ):
        raise RepairEvaluationError("fixed repair budget mismatch")
    acceptance = protocol.get("acceptance_gates")
    expected_comparators = [
        "mission_success_rate",
        "mission_failure_rate",
        "trajectory_ate_rmse_m",
        "endpoint_p95_m",
        "maximum_applied_action_saturation_fraction",
    ]
    if (
        not isinstance(acceptance, dict)
        or acceptance.get("all_outputs_finite") is not True
        or acceptance.get("maximum_applied_action_saturation_fraction") != 0.05
        or acceptance.get("minimum_patch_fresh_repair_success_improvement_percentage_points")
        != 20.0
        or acceptance.get("minimum_patch_failure_reduction_fraction") != 0.50
        or acceptance.get("maximum_patch_id_nominal_success_degradation_fraction") != 0.10
        or acceptance.get("repair_claim_only_if_every_gate_passes") is not True
        or acceptance.get("patch_must_not_be_worse_than_raw_or_calibrated_on")
        != expected_comparators
    ):
        raise RepairEvaluationError("repair acceptance gates differ from frozen semantics")
    causal_contract = protocol.get("causal_integrity")
    if causal_contract != {
        "pre_dropout_raw_bit_trace_required": True,
        "same_candidate_checkpoint_context_genesis_seed_required": True,
        "physical_dropout_schedule_binding_required": True,
        "fault_activation_order": (
            "begin_scoring -> freeze -> measured_imu -> issued_action -> "
            "context_push -> frozen_context_prior -> fault_activation -> "
            "env.step -> cloned_native_imu -> estimator_commit"
        ),
        "last_applied_action_available_to_policy": False,
        "fault_parameters_available_to_policy": False,
        "domain_labels_available_to_policy": False,
        "patch_off_structural_model_step_noop_gate_required": True,
        "action_only_frozen_r5_same_process_shadow_raw_bit_exact_required": True,
        "native_imu_may_affect_policy_only_at_or_after_freeze": True,
        "native_calibration_alignment": {
            "sensor_sample_time": "post_step_t_plus_1",
            "quaternion_time": "post_step_t_plus_1",
            "velocity_transition": "pre_step_t_to_post_step_t_plus_1",
            "next_visible_quaternion_raw_bit_equivalence_required": True,
        },
        "demo_replay_trace": {
            "registered_lane_index": 0,
            "score_affected": False,
            "record_every_step": True,
            "required_fields": [
                "truth_position",
                "truth_quaternion",
                "estimated_position",
                "issued_action",
                "applied_action",
                "terminal",
                "gate_index",
                "fault_onset",
            ],
            "raw_content_sha256_required": True,
        },
    }:
        raise RepairEvaluationError("repair causal-integrity contract mismatch")
    output_root = Path(str(outputs.get("output_root"))).expanduser().resolve()
    registered = []
    registered_raw_evidence = []
    for arm in ARMS:
        for checkpoint_seed in checkpoint_seeds:
            for lane_role in LANE_ROLES:
                path = registered_pass_path(
                    protocol,
                    arm=arm,
                    checkpoint_seed=checkpoint_seed,
                    lane_role=lane_role,
                )
                if not path.is_relative_to(output_root):
                    raise RepairEvaluationError("registered pass escapes output root")
                registered.append(path)
                evidence_path = registered_raw_evidence_path(
                    protocol,
                    arm=arm,
                    checkpoint_seed=checkpoint_seed,
                    lane_role=lane_role,
                )
                if not evidence_path.is_relative_to(output_root):
                    raise RepairEvaluationError("registered raw evidence escapes output root")
                registered_raw_evidence.append(evidence_path)
    summary_path = registered_summary_path(protocol)
    if (
        len(set(registered)) != 24
        or len(set(registered_raw_evidence)) != 24
        or not summary_path.is_relative_to(output_root)
        or summary_path in registered
        or summary_path in registered_raw_evidence
        or set(registered).intersection(registered_raw_evidence)
    ):
        raise RepairEvaluationError("registered output paths collide or escape output root")
    execution_environment = protocol.get("execution_environment")
    implementation_contract = protocol.get("implementation_contract")
    if (
        not isinstance(execution_environment, dict)
        or execution_environment.get("backend") != "amdgpu"
        or execution_environment.get("visible_gpu_count") != 1
        or execution_environment.get("torch_hip_required") is not True
        or not _is_sha256(execution_environment.get("genesis_source_tree_sha256"))
        or not isinstance(execution_environment.get("genesis_version"), str)
        or not execution_environment["genesis_version"]
        or not _is_sha256(execution_environment.get("corrected_racer_urdf_sha256"))
        or execution_environment.get("maximum_concurrent_gpu_processes") != 1
        or not isinstance(implementation_contract, dict)
    ):
        raise RepairEvaluationError("execution environment differs from frozen semantics")
    return {
        "sha256": protocol_hash,
        "runtime": runtime,
        "selection": selection,
        "rng": rng,
        "sensor": sensor,
        "r5_baseline": r5_baseline,
        "outputs": outputs,
        "checkpoint_seeds": checkpoint_seeds,
        "fixed_budget": budget,
        "execution_environment": execution_environment,
        "implementation_contract": implementation_contract,
        "physical_dropout_replay": physical_dropout,
    }


def registered_pass_path(
    protocol: Mapping[str, Any],
    *,
    arm: str,
    checkpoint_seed: int,
    lane_role: str,
) -> Path:
    try:
        value = protocol["registered_outputs"]["passes"][arm][str(checkpoint_seed)][lane_role]
    except (KeyError, TypeError) as error:
        raise RepairEvaluationError("registered pass path is missing") from error
    if not isinstance(value, str):
        raise RepairEvaluationError("registered pass path must be a string")
    return Path(value).expanduser().resolve()


def registered_summary_path(protocol: Mapping[str, Any]) -> Path:
    try:
        value = protocol["registered_outputs"]["summary"]
    except (KeyError, TypeError) as error:
        raise RepairEvaluationError("registered summary path is missing") from error
    if not isinstance(value, str):
        raise RepairEvaluationError("registered summary path must be a string")
    return Path(value).expanduser().resolve()


def registered_raw_evidence_path(
    protocol: Mapping[str, Any],
    *,
    arm: str,
    checkpoint_seed: int,
    lane_role: str,
) -> Path:
    try:
        value = protocol["registered_outputs"]["raw_evidence_npz"][arm][str(checkpoint_seed)][
            lane_role
        ]
    except (KeyError, TypeError) as error:
        raise RepairEvaluationError("registered raw evidence path is missing") from error
    if not isinstance(value, str):
        raise RepairEvaluationError("registered raw evidence path must be a string")
    return Path(value).expanduser().resolve()


def checkpoint_record(
    selection: Mapping[str, Any],
    *,
    checkpoint_seed: int,
) -> dict[str, Any]:
    records = selection.get("checkpoints")
    if not isinstance(records, list):
        raise RepairEvaluationError("selected checkpoints are missing")
    matches = [
        record
        for record in records
        if isinstance(record, dict) and record.get("seed") == checkpoint_seed
    ]
    if len(matches) != 1:
        raise RepairEvaluationError("selected checkpoint is not unique")
    record = matches[0]
    path = Path(str(record.get("path"))).expanduser().resolve()
    if not path.is_file() or sha256_file(path) != record.get("sha256"):
        raise RepairEvaluationError("selected checkpoint file or SHA256 mismatch")
    return record


def load_model(checkpoint_path: Path, device: torch.device) -> torch.nn.Module:
    from torch.torch_version import TorchVersion

    from flightguard.dynamics import DynamicsConfig, FlightDynamicsModel

    with torch.serialization.safe_globals([TorchVersion]):
        payload = torch.load(
            checkpoint_path,
            map_location=device,
            weights_only=True,
        )
    if not isinstance(payload, dict):
        raise TypeError("checkpoint must contain a dictionary")
    config = dict(payload["model_config"])
    if "hidden_sizes" in config:
        config["hidden_sizes"] = tuple(config["hidden_sizes"])
    model = FlightDynamicsModel(DynamicsConfig(**config)).to(device)
    model.load_state_dict(payload["model_state_dict"], strict=True)
    model.eval()
    return model


def indexed_gate(
    gates: torch.Tensor,
    yaws: torch.Tensor,
    gate_index: torch.Tensor,
) -> tuple[torch.Tensor, torch.Tensor]:
    if gates.ndim != 3 or yaws.shape != gates.shape[:2] or gate_index.shape != (gates.shape[0],):
        raise ValueError("gate tensor shapes are invalid")
    env_index = torch.arange(gates.shape[0], device=gates.device)
    clamped = gate_index.clamp(0, gates.shape[1] - 1)
    return gates[env_index, clamped], yaws[env_index, clamped]


def canonical_candidate(selection: Mapping[str, Any]) -> dict[str, Any]:
    candidate = selection.get("candidate")
    if not isinstance(candidate, dict):
        raise RepairEvaluationError("selected candidate is missing")
    latent = candidate.get("latent")
    if not isinstance(latent, dict) or set(latent) != set(LATENT_NAMES):
        raise RepairEvaluationError("selected candidate latent is invalid")
    reconstructed = canonical_fault_candidate(tuple(float(latent[name]) for name in LATENT_NAMES))
    if reconstructed.candidate_id != candidate.get("candidate_id"):
        raise RepairEvaluationError("selected candidate ID differs from latent")
    scheduled = candidate.get("scheduled")
    expected_scheduled = {
        "thrust_scale": reconstructed.thrust_scale,
        "wind_acceleration_mps2": list(reconstructed.wind_acceleration_mps2),
        "action_delay_steps": reconstructed.action_delay_steps,
    }
    if canonical_json_bytes(scheduled) != canonical_json_bytes(expected_scheduled):
        raise RepairEvaluationError("selected candidate scheduled fault mismatch")
    return candidate


def build_sensor_error_bank(
    *,
    context_seeds: Sequence[int],
    steps: int,
    dt: float,
    registered_noise_seed: int,
) -> dict[str, Any]:
    profile = FORMAL_REALISTIC_SENSOR_PROFILE
    acceleration_error = torch.empty(
        (steps, len(context_seeds), 3),
        dtype=torch.float32,
        device="cpu",
    )
    gyro_error = torch.empty_like(acceleration_error)
    for context_index, context_seed in enumerate(context_seeds):
        generator = torch.Generator(device="cpu")
        generator.manual_seed(registered_noise_seed + int(context_seed))
        acceleration_white = torch.randn(
            (steps, 3),
            device="cpu",
            generator=generator,
        )
        gyro_white = torch.randn(
            (steps, 3),
            device="cpu",
            generator=generator,
        )
        acceleration_walk = torch.randn(
            (steps, 3),
            device="cpu",
            generator=generator,
        ).cumsum(dim=0)
        gyro_walk = torch.randn(
            (steps, 3),
            device="cpu",
            generator=generator,
        ).cumsum(dim=0)
        acceleration_error[:, context_index] = (
            profile.acc_bias
            + profile.acc_noise * acceleration_white
            + profile.acc_random_walk * math.sqrt(dt) * acceleration_walk
        )
        gyro_error[:, context_index] = (
            profile.gyro_bias
            + profile.gyro_noise * gyro_white
            + profile.gyro_random_walk * math.sqrt(dt) * gyro_walk
        )
    digest = hashlib.sha256()
    digest.update(b"flightguard-deterministic-sensor-error-bank-v1\0")
    digest.update(
        canonical_json_bytes(
            {
                "context_seeds": list(context_seeds),
                "dt_s": float(dt),
                "registered_noise_seed": int(registered_noise_seed),
                "steps": int(steps),
            }
        )
    )
    digest.update(canonical_json_bytes(asdict(profile)))
    digest.update(acceleration_error.contiguous().numpy().tobytes())
    digest.update(gyro_error.contiguous().numpy().tobytes())
    raw_digest = hashlib.sha256()
    raw_digest.update(acceleration_error.contiguous().numpy().tobytes())
    raw_digest.update(gyro_error.contiguous().numpy().tobytes())
    return {
        "acceleration_error": acceleration_error,
        "gyro_error": gyro_error,
        "sha256": digest.hexdigest(),
        "raw_bytes_sha256": raw_digest.hexdigest(),
        "shape": [steps, len(context_seeds), 3],
        "dtype": "torch.float32",
        "device": "cpu",
        "registered_noise_seed": registered_noise_seed,
    }


def build_r5_context_measurement_bank(
    *,
    context_seeds: Sequence[int],
    steps: int,
    runtime: Mapping[str, Any],
) -> dict[str, Any]:
    """Reproduce the frozen R5 attitude/rate perturbation bank exactly."""

    attitude_noise, angular_velocity_noise = r5_context_noise(
        list(context_seeds),
        steps=steps,
        attitude_std_rad=math.radians(float(runtime["attitude_noise_std_deg"])),
        angular_velocity_std_rad_s=float(runtime["angular_velocity_noise_std_rad_s"]),
    )
    if (
        attitude_noise.shape != (steps, len(context_seeds), 3)
        or angular_velocity_noise.shape != attitude_noise.shape
        or attitude_noise.dtype != torch.float32
        or angular_velocity_noise.dtype != torch.float32
        or attitude_noise.device.type != "cpu"
        or angular_velocity_noise.device.type != "cpu"
        or not bool(torch.isfinite(attitude_noise).all())
        or not bool(torch.isfinite(angular_velocity_noise).all())
    ):
        raise RepairEvaluationError("R5 context measurement bank metadata is invalid")
    raw_digest = hashlib.sha256()
    raw_digest.update(attitude_noise.contiguous().numpy().tobytes())
    raw_digest.update(angular_velocity_noise.contiguous().numpy().tobytes())
    digest = hashlib.sha256()
    digest.update(b"flightguard-r5-context-measurement-bank-v1\0")
    digest.update(
        canonical_json_bytes(
            {
                "angular_velocity_bias_rad_s": runtime["angular_velocity_bias_rad_s"],
                "angular_velocity_noise_std_rad_s": runtime["angular_velocity_noise_std_rad_s"],
                "attitude_bias_deg": runtime["attitude_bias_deg"],
                "attitude_noise_std_deg": runtime["attitude_noise_std_deg"],
                "context_seeds": list(context_seeds),
                "steps": steps,
            }
        )
    )
    digest.update(raw_digest.digest())
    return {
        "attitude_noise": attitude_noise,
        "angular_velocity_noise": angular_velocity_noise,
        "sha256": digest.hexdigest(),
        "raw_bytes_sha256": raw_digest.hexdigest(),
        "shape": [steps, len(context_seeds), 3],
        "dtype": "torch.float32",
        "device": "cpu",
        "source_function_sha256": callable_source_sha256(r5_context_noise),
    }


def make_r5_online_context(
    *,
    batch_size: int,
    device: torch.device | str,
    runtime: Mapping[str, Any],
) -> FrozenAffineDelayContext:
    config = FrozenAffineDelayConfig(
        max_delay_steps=int(runtime["context_max_delay_steps"]),
        ridge=float(runtime["context_ridge"]),
        gamma_min=-float(runtime["context_gamma_limit"]),
        gamma_max=float(runtime["context_gamma_limit"]),
        bias_abs_max_mps2=float(runtime["context_bias_limit_mps2"]),
        min_fit_samples=int(runtime["context_min_fit_samples"]),
        min_score_samples=int(runtime["context_min_score_samples"]),
        min_excitation=float(runtime["context_min_excitation"]),
        delay_score_tolerance=float(runtime["context_delay_score_tolerance"]),
        min_score_improvement_absolute=float(runtime["context_min_score_improvement_absolute"]),
        min_score_improvement_relative=float(runtime["context_min_score_improvement_relative"]),
        score_residual_quantile=float(runtime["context_score_residual_quantile"]),
        max_score_samples=(int(runtime["dropout_start_step"]) - int(runtime["context_fit_steps"])),
    )
    return FrozenAffineDelayContext(
        batch_size,
        device=device,
        dtype=torch.float32,
        config=config,
    )


def r5_baseline_integrate(
    position: torch.Tensor,
    velocity: torch.Tensor,
    acceleration: torch.Tensor,
    *,
    dt: float,
) -> tuple[torch.Tensor, torch.Tensor]:
    """Use the exact operation order from the frozen R5 evaluator."""

    proposed_position = position + velocity * dt + 0.5 * acceleration * dt * dt
    proposed_velocity = velocity + acceleration * dt
    return proposed_position, proposed_velocity


def module_state_raw_exact(
    left: torch.nn.Module,
    right: torch.nn.Module,
) -> dict[str, Any]:
    left_state = left.state_dict()
    right_state = right.state_dict()
    names_match = list(left_state) == list(right_state)
    mismatched = []
    if names_match:
        mismatched = [
            name
            for name in left_state
            if not _raw_tensor_equal(left_state[name], right_state[name])
        ]
    return {
        "names_match": names_match,
        "tensor_count": len(left_state),
        "mismatched_tensor_names": mismatched,
        "exact": names_match and not mismatched,
    }


def r5_baseline_structural_parity_gate() -> dict[str, Any]:
    """CPU-only gate for the exact frozen R5 helper/config/integration surface."""

    from flightguard.controller import (
        BatchedWaypointController,
        controller_config_for_profile,
    )

    device = torch.device("cpu")
    reference = r5_baseline_reference_code_contract()
    runtime = {
        "angular_velocity_bias_rad_s": [0.01, -0.01, 0.005],
        "angular_velocity_noise_std_rad_s": 0.02,
        "attitude_bias_deg": [0.2, -0.1, 0.15],
        "attitude_noise_std_deg": 0.5,
        "context_bias_limit_mps2": 1.5,
        "context_delay_score_tolerance": 0.0001,
        "context_fit_steps": 200,
        "context_gamma_limit": 0.6,
        "context_max_delay_steps": 6,
        "context_min_excitation": 0.05,
        "context_min_fit_samples": 100,
        "context_min_score_improvement_absolute": 0.0001,
        "context_min_score_improvement_relative": 0.05,
        "context_min_score_samples": 50,
        "context_ridge": 0.05,
        "context_score_residual_quantile": 0.95,
        "dropout_start_step": 300,
    }
    first_context = make_r5_online_context(
        batch_size=2,
        device=device,
        runtime=runtime,
    )
    second_context = make_r5_online_context(
        batch_size=2,
        device=device,
        runtime=runtime,
    )
    context_exact = module_state_raw_exact(first_context, second_context)
    position = torch.tensor(
        [[0.25, -0.5, 1.0], [-1.0, 2.0, 0.75]],
        dtype=torch.float32,
        device=device,
    )
    velocity = torch.tensor(
        [[0.1, 0.2, -0.3], [-0.4, 0.5, 0.6]],
        dtype=torch.float32,
        device=device,
    )
    acceleration = torch.tensor(
        [[1.0, -2.0, 3.0], [0.25, -0.5, 0.75]],
        dtype=torch.float32,
        device=device,
    )
    actual_position, actual_velocity = r5_baseline_integrate(
        position,
        velocity,
        acceleration,
        dt=0.01,
    )
    reference_position = position + velocity * 0.01 + 0.5 * acceleration * 0.01 * 0.01
    reference_velocity = velocity + acceleration * 0.01
    bank_a = build_r5_context_measurement_bank(
        context_seeds=[131_000, 131_001],
        steps=2,
        runtime=runtime,
    )
    bank_b = build_r5_context_measurement_bank(
        context_seeds=[131_000, 131_001],
        steps=2,
        runtime=runtime,
    )

    class DeterministicAcceleration(torch.nn.Module):
        def acceleration(
            self,
            velocity: torch.Tensor,
            quaternion: torch.Tensor,
            angular_velocity: torch.Tensor,
            action: torch.Tensor,
        ) -> torch.Tensor:
            return (
                0.1 * velocity + 0.01 * quaternion[:, 1:] - 0.02 * angular_velocity + action[:, :3]
            )

    controller_config = replace(
        controller_config_for_profile("robust_z"),
        max_upward_vertical_acceleration=5.0,
        max_downward_vertical_acceleration=3.0,
    )
    controller = BatchedWaypointController(controller_config)
    quaternion = torch.tensor(
        [[1.0, 0.0, 0.0, 0.0], [0.999, 0.01, -0.02, 0.03]],
        dtype=torch.float32,
        device=device,
    )
    angular_velocity = torch.tensor(
        [[0.01, -0.02, 0.03], [-0.04, 0.05, -0.06]],
        dtype=torch.float32,
        device=device,
    )
    target = torch.tensor(
        [[1.0, 0.5, 1.2], [0.25, 1.5, 1.0]],
        dtype=torch.float32,
        device=device,
    )
    visible = ControllerVisibleState(
        position=position,
        quaternion=quaternion,
        velocity=velocity,
        angular_velocity_world=angular_velocity,
        target=target,
        dead=torch.zeros(2, dtype=torch.bool, device=device),
    )
    actual_action = dispatch_post_dropout_controller(controller, visible)
    shadow_action = controller(
        position,
        quaternion,
        velocity,
        angular_velocity,
        target,
    )
    first_context.begin_scoring()
    first_context.freeze()
    second_context.begin_scoring()
    second_context.freeze()
    first_context.push_issued(actual_action)
    second_context.push_issued(shadow_action)
    deterministic_model = DeterministicAcceleration()
    actual_prior = first_context.predict_acceleration(
        deterministic_model,
        velocity,
        quaternion,
        angular_velocity,
    )
    shadow_prior = second_context.predict_acceleration(
        deterministic_model,
        velocity,
        quaternion,
        angular_velocity,
    )
    actual_visible, _ = commit_post_dropout_transition(
        HardeningArm.ACTION_ONLY,
        visible=visible,
        prior_acceleration_world_mps2=actual_prior,
        active_mask=torch.ones(2, dtype=torch.bool, device=device),
        dt=0.01,
        estimator=None,
        native_imu_sensor=None,
    )
    shadow_position, shadow_velocity = r5_baseline_integrate(
        position,
        velocity,
        shadow_prior,
        dt=0.01,
    )
    context_after_push_exact = module_state_raw_exact(
        first_context,
        second_context,
    )
    checks = {
        "frozen_r5_reference_helper_source_hashes_match": (reference["status"] == "PASS"),
        "independent_context_initial_state_raw_exact": context_exact["exact"],
        "r5_position_integration_raw_exact": _raw_tensor_equal(
            actual_position,
            reference_position,
        ),
        "r5_velocity_integration_raw_exact": _raw_tensor_equal(
            actual_velocity,
            reference_velocity,
        ),
        "r5_measurement_bank_repeat_raw_exact": (
            bank_a["sha256"] == bank_b["sha256"]
            and bank_a["raw_bytes_sha256"] == bank_b["raw_bytes_sha256"]
        ),
        "r5_action_only_controller_raw_exact": _raw_tensor_equal(
            actual_action,
            shadow_action,
        ),
        "r5_action_only_context_after_push_raw_exact": (context_after_push_exact["exact"]),
        "r5_action_only_prior_raw_exact": _raw_tensor_equal(
            actual_prior,
            shadow_prior,
        ),
        "r5_action_only_position_commit_raw_exact": _raw_tensor_equal(
            actual_visible.position,
            shadow_position,
        ),
        "r5_action_only_velocity_commit_raw_exact": _raw_tensor_equal(
            actual_visible.velocity,
            shadow_velocity,
        ),
    }
    return {
        "name": "frozen_r5_baseline_structural_parity",
        "status": "PASS" if all(checks.values()) else "FAIL",
        "checks": checks,
        "reference_code": reference,
        "context_initial_state": context_exact,
        "context_after_action_push": context_after_push_exact,
        "measurement_bank_sha256": bank_a["sha256"],
        "measurement_bank_raw_bytes_sha256": bank_a["raw_bytes_sha256"],
    }


def apply_sensor_error(
    sample: NativeIMUSample,
    *,
    acceleration_error: torch.Tensor,
    gyro_error: torch.Tensor,
    enabled: bool = True,
) -> NativeIMUSample:
    if not enabled:
        return NativeIMUSample(
            specific_force_body=sample.specific_force_body.detach().clone(),
            angular_velocity_body=sample.angular_velocity_body.detach().clone(),
        )
    profile = FORMAL_REALISTIC_SENSOR_PROFILE

    def transform(
        value: torch.Tensor,
        error: torch.Tensor,
        *,
        coupling: float,
        resolution: float,
    ) -> torch.Tensor:
        coupled = value + coupling * (torch.roll(value, 1, dims=1) + torch.roll(value, -1, dims=1))
        corrupted = coupled + error.to(device=value.device, dtype=value.dtype)
        if resolution > 0.0:
            corrupted = torch.round(corrupted / resolution) * resolution
        return corrupted.detach().clone()

    return NativeIMUSample(
        specific_force_body=transform(
            sample.specific_force_body,
            acceleration_error,
            coupling=profile.acc_cross_axis_coupling,
            resolution=profile.acc_resolution,
        ),
        angular_velocity_body=transform(
            sample.angular_velocity_body,
            gyro_error,
            coupling=profile.gyro_cross_axis_coupling,
            resolution=profile.gyro_resolution,
        ),
    )


def sensor_error_bank_generator_code_sha256() -> str:
    """Bind both bank generation and post-read application implementation."""

    source = (
        inspect.getsource(build_sensor_error_bank) + "\n" + inspect.getsource(apply_sensor_error)
    )
    return hashlib.sha256(source.encode("utf-8")).hexdigest()


def measurement_error_intervention_gates() -> dict[str, Any]:
    """Prove zero intervention is exact and the registered bank changes an estimate."""

    device = torch.device("cpu")
    raw = NativeIMUSample(
        specific_force_body=torch.tensor(
            [[0.25, -0.5, 9.81]],
            dtype=torch.float32,
            device=device,
        ),
        angular_velocity_body=torch.tensor(
            [[0.01, -0.02, 0.03]],
            dtype=torch.float32,
            device=device,
        ),
    )
    zeros = torch.zeros((1, 3), dtype=torch.float32, device=device)
    zero = apply_sensor_error(
        raw,
        acceleration_error=zeros,
        gyro_error=zeros,
        enabled=False,
    )
    bank = build_sensor_error_bank(
        context_seeds=[131_000],
        steps=1,
        dt=0.01,
        registered_noise_seed=133_000,
    )
    active = apply_sensor_error(
        raw,
        acceleration_error=bank["acceleration_error"][0],
        gyro_error=bank["gyro_error"][0],
        enabled=True,
    )
    acceleration_change = float(
        torch.linalg.vector_norm(
            active.specific_force_body - raw.specific_force_body,
            dim=1,
        ).item()
    )
    gyro_change = float(
        torch.linalg.vector_norm(
            active.angular_velocity_body - raw.angular_velocity_body,
            dim=1,
        ).item()
    )
    visible = ControllerVisibleState(
        position=torch.zeros((1, 3), dtype=torch.float32, device=device),
        quaternion=torch.tensor(
            [[1.0, 0.0, 0.0, 0.0]],
            dtype=torch.float32,
            device=device,
        ),
        velocity=torch.zeros((1, 3), dtype=torch.float32, device=device),
        angular_velocity_world=torch.zeros(
            (1, 3),
            dtype=torch.float32,
            device=device,
        ),
        target=torch.tensor(
            [[1.0, 0.0, 0.0]],
            dtype=torch.float32,
            device=device,
        ),
        dead=torch.zeros(1, dtype=torch.bool, device=device),
    )
    zero_estimator = make_frozen_arm_estimator(
        HardeningArm.RAW_STRAPDOWN,
        visible=visible,
        last_native_sample=raw,
    )
    active_estimator = make_frozen_arm_estimator(
        HardeningArm.RAW_STRAPDOWN,
        visible=visible,
        last_native_sample=raw,
    )
    prior = torch.zeros((1, 3), dtype=torch.float32, device=device)

    def sensor_from(sample: NativeIMUSample) -> SimpleNamespace:
        return SimpleNamespace(
            read=lambda: SimpleNamespace(
                lin_acc=sample.specific_force_body,
                ang_vel=sample.angular_velocity_body,
            )
        )

    zero_visible, zero_acceleration = commit_post_dropout_transition(
        HardeningArm.RAW_STRAPDOWN,
        visible=visible,
        prior_acceleration_world_mps2=prior,
        active_mask=torch.ones(1, dtype=torch.bool, device=device),
        dt=0.01,
        estimator=zero_estimator,
        native_imu_sensor=sensor_from(zero),
    )
    active_visible, active_acceleration = commit_post_dropout_transition(
        HardeningArm.RAW_STRAPDOWN,
        visible=visible,
        prior_acceleration_world_mps2=prior,
        active_mask=torch.ones(1, dtype=torch.bool, device=device),
        dt=0.01,
        estimator=active_estimator,
        native_imu_sensor=sensor_from(active),
    )
    estimated_acceleration_change = float(
        torch.linalg.vector_norm(active_acceleration - zero_acceleration, dim=1).item()
    )
    estimated_velocity_change = float(
        torch.linalg.vector_norm(active_visible.velocity - zero_visible.velocity, dim=1).item()
    )
    estimated_position_change = float(
        torch.linalg.vector_norm(active_visible.position - zero_visible.position, dim=1).item()
    )
    checks = {
        "zero_intervention_specific_force_raw_exact": _raw_tensor_equal(
            zero.specific_force_body,
            raw.specific_force_body,
        ),
        "zero_intervention_angular_velocity_raw_exact": _raw_tensor_equal(
            zero.angular_velocity_body,
            raw.angular_velocity_body,
        ),
        "registered_bank_changes_specific_force": acceleration_change >= 0.05,
        "registered_bank_changes_angular_velocity": gyro_change >= 0.001,
        "registered_bank_changes_estimated_acceleration": (estimated_acceleration_change >= 0.025),
        "registered_bank_changes_estimated_velocity": estimated_velocity_change >= 0.00025,
        "registered_bank_changes_estimated_position": estimated_position_change >= 1.0e-6,
        "registered_bank_estimator_lanes_remain_live": (
            zero_visible.dead.tolist() == [False] and active_visible.dead.tolist() == [False]
        ),
    }
    return {
        "name": "post_read_measurement_error_intervention",
        "status": "PASS" if all(checks.values()) else "FAIL",
        "checks": checks,
        "specific_force_change_mps2": acceleration_change,
        "angular_velocity_change_rad_s": gyro_change,
        "estimated_acceleration_change_mps2": estimated_acceleration_change,
        "estimated_velocity_change_mps": estimated_velocity_change,
        "estimated_position_change_m": estimated_position_change,
        "bank_generator_code_sha256": sensor_error_bank_generator_code_sha256(),
    }


def raw_trace_digest(trace: Mapping[str, Sequence[torch.Tensor]]) -> dict[str, Any]:
    if set(trace) != set(TRACE_FIELDS):
        raise ValueError("pre-dropout trace field set mismatch")
    steps = len(trace[TRACE_FIELDS[0]])
    if steps <= 0 or any(len(trace[field]) != steps for field in TRACE_FIELDS):
        raise ValueError("pre-dropout trace lengths differ")
    stacked = {
        field: torch.stack(list(values), dim=0).detach().contiguous().cpu()
        for field, values in trace.items()
    }
    lanes = stacked[TRACE_FIELDS[0]].shape[1]
    aggregate = hashlib.sha256()
    per_lane = [hashlib.sha256() for _ in range(lanes)]
    value_count = 0
    for field in TRACE_FIELDS:
        value = stacked[field]
        if value.shape[1] != lanes:
            raise ValueError("pre-dropout trace lane count differs")
        header = canonical_json_bytes(
            {
                "field": field,
                "dtype": str(value.dtype),
                "shape": list(value.shape),
            }
        )
        payload = value.numpy().tobytes()
        aggregate.update(header)
        aggregate.update(payload)
        value_count += value.numel()
        for lane in range(lanes):
            lane_value = value[:, lane].contiguous()
            per_lane[lane].update(header)
            per_lane[lane].update(lane_value.numpy().tobytes())
    return {
        "schema_version": "flightguard-pre-dropout-raw-bit-trace-v1",
        "steps": steps,
        "lanes": lanes,
        "value_count": value_count,
        "sha256": aggregate.hexdigest(),
        "lane_sha256": [digest.hexdigest() for digest in per_lane],
    }


def _visible_from_truth(
    *,
    position: torch.Tensor,
    quaternion: torch.Tensor,
    velocity: torch.Tensor,
    angular_velocity: torch.Tensor,
    target: torch.Tensor,
    dead: torch.Tensor,
) -> ControllerVisibleState:
    return extract_controller_visible_state(
        SimpleNamespace(
            position=position,
            quaternion=quaternion,
            velocity=velocity,
            angular_velocity_world=angular_velocity,
            target=target,
            dead=dead,
        )
    )


def summarize_metrics(
    *,
    success: torch.Tensor,
    terminal: torch.Tensor,
    gates_passed: torch.Tensor,
    dropout_squared_error_sum: torch.Tensor,
    endpoint_error: torch.Tensor,
    saturation_steps: torch.Tensor,
    active_control_steps: torch.Tensor,
    dropout_steps: int,
    gate_count: int,
) -> dict[str, Any]:
    count = success.numel()
    saturation = saturation_steps.float() / active_control_steps.clamp_min(1).float()
    ate = torch.sqrt(dropout_squared_error_sum.sum() / (count * dropout_steps))
    return {
        "episode_count": count,
        "mission_success_count": int(success.sum().item()),
        "mission_success_rate": float(success.float().mean().item()),
        "mission_failure_count": int((~success).sum().item()),
        "mission_failure_rate": float((~success).float().mean().item()),
        "terminal_failure_count": int((terminal & ~success).sum().item()),
        "trajectory_ate_rmse_m": float(ate.item()),
        "dropout_squared_error_sum_m2": float(dropout_squared_error_sum.sum().item()),
        "dropout_error_sample_count": count * dropout_steps,
        "endpoint_rmse_m": float(torch.sqrt(endpoint_error.square().mean()).item()),
        "endpoint_p95_m": float(torch.quantile(endpoint_error, 0.95).item()),
        "endpoint_error_m": endpoint_error.detach().cpu().tolist(),
        "mission_progress_fraction": float(
            gates_passed.float().sum().item() / (count * gate_count)
        ),
        "maximum_applied_action_saturation_fraction": float(saturation.max().item()),
        "mean_applied_action_saturation_fraction": float(saturation.mean().item()),
        "per_episode_applied_action_saturation_fraction": saturation.detach().cpu().tolist(),
    }


def _strict_bound_file(
    record: Any,
    *,
    name: str,
    expected_path: Path | None = None,
) -> Path:
    if not isinstance(record, dict) or set(record) != {
        "path",
        "sha256",
        "size_bytes",
    }:
        raise RepairEvaluationError(f"{name} binding field set mismatch")
    unresolved = Path(str(record["path"])).expanduser()
    from tools.build_v6_observer_capture_governance import (
        ObserverCaptureGovernanceError,
        normalized_absolute_path,
    )

    try:
        path = normalized_absolute_path(unresolved, name=name)
    except (OSError, TypeError, ValueError, ObserverCaptureGovernanceError) as error:
        raise RepairEvaluationError(f"{name} binding path mismatch") from error
    if (
        not path.is_file()
        or path.is_symlink()
        or str(path) != record["path"]
        or not _is_sha256(record["sha256"])
        or sha256_file(path) != record["sha256"]
        or type(record["size_bytes"]) is not int
        or path.stat().st_size != record["size_bytes"]
        or (expected_path is not None and path != expected_path.resolve())
    ):
        raise RepairEvaluationError(f"{name} binding mismatch")
    return path


def _strict_fresh_absolute_slot(value: Any, *, name: str) -> Path:
    if not isinstance(value, str):
        raise RepairEvaluationError(f"{name} must be a string")
    path = Path(value).expanduser()
    from tools.build_v6_observer_capture_governance import (
        ObserverCaptureGovernanceError,
        assert_fresh_slot,
    )

    try:
        assert_fresh_slot(path, name=name)
    except (OSError, TypeError, ValueError, ObserverCaptureGovernanceError) as error:
        raise RepairEvaluationError(
            f"{name} is not a fresh normalized slot"
        ) from error
    return path


def _strict_normalized_absolute_slot(value: Any, *, name: str) -> Path:
    if not isinstance(value, str):
        raise RepairEvaluationError(f"{name} must be a string")
    from tools.build_v6_observer_capture_governance import (
        ObserverCaptureGovernanceError,
        normalized_absolute_path,
    )

    try:
        return normalized_absolute_path(Path(value).expanduser(), name=name)
    except (OSError, TypeError, ValueError, ObserverCaptureGovernanceError) as error:
        raise RepairEvaluationError(
            f"{name} is not a normalized absolute slot"
        ) from error


def _mapping_leaf_diff_paths(
    left: Any,
    right: Any,
    *,
    prefix: tuple[str, ...] = (),
) -> set[tuple[str, ...]]:
    if isinstance(left, Mapping) and isinstance(right, Mapping):
        paths: set[tuple[str, ...]] = set()
        for key in sorted(set(left) | set(right)):
            child = (*prefix, str(key))
            if key not in left or key not in right:
                paths.add(child)
            else:
                paths.update(
                    _mapping_leaf_diff_paths(
                        left[key],
                        right[key],
                        prefix=child,
                    )
                )
        return paths
    return set() if left == right else {prefix}


def _require_stage_a_protocol_sha256(
    value: Any,
    *,
    argument: str,
) -> str:
    if (
        type(value) is not str
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise RepairEvaluationError(
            f"Stage-A capture requires exact lowercase {argument}"
        )
    return value


def _v6_stage_a_header(protocol: Mapping[str, Any]) -> bool:
    return (
        protocol.get("schema_version")
        == V6_OBSERVER_CAPTURE_PROTOCOL_SCHEMA_VERSION
        and protocol.get("status") == V6_OBSERVER_CAPTURE_PROTOCOL_STATUS
        and protocol.get("stage") == "capture"
    )


def load_v6_observer_capture_execution_adapter(
    *,
    protocol_path: Path,
    protocol_sha256: str,
    checkpoint_seed: int,
    capture_output_path: Path | None = None,
) -> dict[str, Any]:
    """Resolve one frozen Stage-A protocol into a narrowly adapted legacy pass."""

    protocol_sha256 = _require_stage_a_protocol_sha256(
        protocol_sha256,
        argument="protocol_sha256",
    )
    protocol_path = protocol_path.expanduser().resolve()
    from tools.build_v6_observer_capture_protocol import (
        validate_capture_protocol,
    )

    try:
        stage_protocol, stage_protocol_binding = validate_capture_protocol(
            protocol_path,
            protocol_sha256,
        )
    except (OSError, TypeError, ValueError, RuntimeError) as error:
        raise RepairEvaluationError(
            "v6 observer capture Stage-A protocol validation failed"
        ) from error
    if stage_protocol_binding.get("sha256") != protocol_sha256:
        raise RepairEvaluationError(
            "v6 observer capture Stage-A protocol binding mismatch"
        )
    if not _v6_stage_a_header(stage_protocol):
        raise RepairEvaluationError("v6 observer capture Stage-A header mismatch")
    legacy = stage_protocol.get("legacy_execution")
    if (
        not isinstance(legacy, dict)
        or set(legacy) != V6_OBSERVER_CAPTURE_LEGACY_EXECUTION_KEYS
    ):
        raise RepairEvaluationError(
            "v6 observer capture legacy execution binding is missing"
        )
    arm_name = stage_protocol.get("capture_contract", {}).get("arm_name")
    if arm_name != HardeningArm.CALIBRATED_STRAPDOWN.value:
        raise RepairEvaluationError(
            "v6 observer capture arm binding mismatch"
        )
    sources = stage_protocol.get("implementation_bindings", {}).get("sources")
    if not isinstance(sources, dict):
        raise RepairEvaluationError(
            "v6 observer capture implementation bindings are missing"
        )
    _strict_bound_file(
        sources.get(V6_OBSERVER_CAPTURE_SOURCE_ROLE),
        name="v6 batch evaluator source",
        expected_path=Path(__file__),
    )
    base_protocol_path = _strict_bound_file(
        legacy["protocol"],
        name="v6 legacy base protocol",
    )
    base_protocol = load_strict_json(base_protocol_path)
    expected_base_header = {
        key: base_protocol.get(key)
        for key in ("schema_version", "protocol_version", "status")
    }
    if legacy["protocol_header"] != expected_base_header:
        raise RepairEvaluationError(
            "v6 legacy base protocol header binding mismatch"
        )
    base_contract = validate_protocol(
        base_protocol,
        protocol_path=base_protocol_path,
    )
    checkpoints = list(base_contract["checkpoint_seeds"])
    seed_bank = stage_protocol.get("rng_contract", {}).get("seed_bank", {}).get(
        "payload"
    )
    if not isinstance(seed_bank, dict):
        raise RepairEvaluationError("v6 Stage-A seed-bank payload is missing")
    checkpoint_order = seed_bank.get("checkpoint_order")
    if checkpoint_order != checkpoints or checkpoint_seed not in checkpoints:
        raise RepairEvaluationError(
            "v6 Stage-A checkpoint set differs from the bound base protocol"
        )
    direct = seed_bank.get("direct")
    if not isinstance(direct, dict):
        raise RepairEvaluationError("v6 Stage-A direct seed map is missing")
    context_by_checkpoint = direct.get("context_by_checkpoint")
    genesis_by_checkpoint = direct.get("genesis_by_checkpoint")
    sensor_by_checkpoint = direct.get("sensor_by_checkpoint")
    if not all(
        isinstance(value, dict)
        for value in (
            context_by_checkpoint,
            genesis_by_checkpoint,
            sensor_by_checkpoint,
        )
    ):
        raise RepairEvaluationError("v6 Stage-A direct seed maps are malformed")
    expected_checkpoint_keys = {str(seed) for seed in checkpoints}
    if (
        set(context_by_checkpoint) != expected_checkpoint_keys
        or set(genesis_by_checkpoint) != expected_checkpoint_keys
        or set(sensor_by_checkpoint) != expected_checkpoint_keys
    ):
        raise RepairEvaluationError("v6 Stage-A direct seed keys are incomplete")

    by_checkpoint = legacy.get("by_checkpoint")
    if (
        not isinstance(by_checkpoint, dict)
        or set(by_checkpoint) != expected_checkpoint_keys
    ):
        raise RepairEvaluationError(
            "v6 observer capture checkpoint execution map is incomplete"
        )
    registered_dummy_map = stage_protocol.get("registered_outputs", {}).get(
        "legacy_dummy_pass_output_by_checkpoint"
    )
    if (
        not isinstance(registered_dummy_map, dict)
        or set(registered_dummy_map) != expected_checkpoint_keys
    ):
        raise RepairEvaluationError(
            "v6 observer capture registered dummy slots are incomplete"
        )
    artifact_map = stage_protocol.get("registered_outputs", {}).get(
        "capture_artifact_by_checkpoint"
    )
    if (
        not isinstance(artifact_map, dict)
        or set(artifact_map) != expected_checkpoint_keys
    ):
        raise RepairEvaluationError(
            "v6 observer capture artifact slots are incomplete"
        )
    active_checkpoint_key = str(checkpoint_seed)
    artifact_slots = {
        key: (
            _strict_fresh_absolute_slot(
                value,
                name=f"capture artifact slot {key}",
            )
            if key == active_checkpoint_key
            else _strict_normalized_absolute_slot(
                value,
                name=f"capture artifact slot {key}",
            )
        )
        for key, value in artifact_map.items()
    }
    if len(set(artifact_slots.values())) != len(artifact_slots):
        raise RepairEvaluationError("v6 observer capture artifact slots collide")
    expected_capture_output = artifact_slots[str(checkpoint_seed)]
    if (
        capture_output_path is not None
        and capture_output_path.expanduser().resolve() != expected_capture_output
    ):
        raise RepairEvaluationError(
            "capture output differs from its registered checkpoint slot"
        )

    adapted_protocol = copy.deepcopy(base_protocol)
    adapted_rng = adapted_protocol["repair_evaluation_rng"]
    adapted_sensor = adapted_protocol["sensor_contract"]
    base_rng = base_protocol["repair_evaluation_rng"]
    base_sensor = base_protocol["sensor_contract"]
    base_context = base_rng["checkpoint_context_seed_banks"]
    base_genesis = base_rng["checkpoint_genesis_seeds"]
    base_sensor_by_checkpoint = {
        str(seed): registered_sensor_seed(
            base_sensor,
            checkpoint_seed=seed,
        )
        for seed in checkpoints
    }
    adapted_rng["checkpoint_context_seed_banks"] = copy.deepcopy(
        context_by_checkpoint
    )
    adapted_rng["checkpoint_genesis_seeds"] = copy.deepcopy(
        genesis_by_checkpoint
    )
    adapted_sensor["registered_noise_seed_by_checkpoint"] = copy.deepcopy(
        sensor_by_checkpoint
    )
    dummy_slots: dict[str, dict[str, Any]] = {}
    for seed in checkpoints:
        key = str(seed)
        record = by_checkpoint[key]
        if (
            not isinstance(record, dict)
            or set(record)
            != V6_OBSERVER_CAPTURE_CHECKPOINT_EXECUTION_KEYS
            or record.get("lane_role") not in LANE_ROLES
        ):
            raise RepairEvaluationError(
                f"v6 observer capture checkpoint execution {key} is malformed"
            )
        lane_role = record["lane_role"]
        pass_output = _strict_fresh_absolute_slot(
            record["dummy_pass_output"],
            name=f"dummy pass output {key}",
        )
        expected_pass_output = registered_pass_path(
            base_protocol,
            arm=arm_name,
            checkpoint_seed=seed,
            lane_role=lane_role,
        )
        if (
            pass_output != expected_pass_output
            or registered_dummy_map[key] != str(expected_pass_output)
        ):
            raise RepairEvaluationError(
                f"v6 observer capture dummy pass {key} differs from the bound base slot"
            )
        raw_output = registered_raw_evidence_path(
            base_protocol,
            arm=arm_name,
            checkpoint_seed=seed,
            lane_role=lane_role,
        )
        raw_output = _strict_fresh_absolute_slot(
            str(raw_output),
            name=f"derived dummy raw evidence output {key}",
        )
        if pass_output == raw_output or pass_output in artifact_slots.values():
            raise RepairEvaluationError(
                f"v6 observer capture dummy slot {key} collides"
            )
        dummy_slots[key] = {
            "pass_output": pass_output,
            "raw_evidence_output": raw_output,
            "lane_role": lane_role,
            "frozen_sensor_transform": record[
                "frozen_sensor_transform"
            ],
        }
    all_slots = [
        *(
            record[name]
            for record in dummy_slots.values()
            for name in ("pass_output", "raw_evidence_output")
        ),
        *artifact_slots.values(),
    ]
    if len(all_slots) != len(set(all_slots)):
        raise RepairEvaluationError("v6 observer capture registered slots collide")

    if any(
        context_by_checkpoint[str(seed)] == base_context[str(seed)]
        or genesis_by_checkpoint[str(seed)] == base_genesis[str(seed)]
        or sensor_by_checkpoint[str(seed)] == base_sensor_by_checkpoint[str(seed)]
        for seed in checkpoints
    ):
        raise RepairEvaluationError(
            "v6 observer capture override kill gate did not change every RNG role"
        )
    expected_diffs = {
        *{
            ("repair_evaluation_rng", "checkpoint_context_seed_banks", str(seed))
            for seed in checkpoints
        },
        *{
            ("repair_evaluation_rng", "checkpoint_genesis_seeds", str(seed))
            for seed in checkpoints
        },
        ("sensor_contract", "registered_noise_seed_by_checkpoint"),
    }
    actual_diffs = _mapping_leaf_diff_paths(base_protocol, adapted_protocol)
    if actual_diffs != expected_diffs:
        raise RepairEvaluationError(
            "v6 observer capture adapter changed fields outside its exact allowlist"
        )

    key = str(checkpoint_seed)
    runtime = base_contract["runtime"]
    new_bank = build_sensor_error_bank(
        context_seeds=context_by_checkpoint[key],
        steps=int(runtime["steps"]),
        dt=float(runtime["dt_s"]),
        registered_noise_seed=sensor_by_checkpoint[key],
    )
    old_bank = build_sensor_error_bank(
        context_seeds=base_context[key],
        steps=int(runtime["steps"]),
        dt=float(runtime["dt_s"]),
        registered_noise_seed=base_sensor_by_checkpoint[key],
    )
    if new_bank["sha256"] == old_bank["sha256"]:
        raise RepairEvaluationError(
            "v6 observer capture sensor-bank override kill gate failed"
        )
    frozen_transform = dummy_slots[key]["frozen_sensor_transform"]
    expected_transform_keys = {
        "name",
        "enabled",
        "implementation_sha256",
        "config_sha256",
        "error_bank_schema_version",
        "error_bank_sha256",
    }
    if (
        not isinstance(frozen_transform, dict)
        or set(frozen_transform) != expected_transform_keys
        or frozen_transform.get("enabled") is not True
        or frozen_transform.get("implementation_sha256")
        != sources[V6_OBSERVER_CAPTURE_SOURCE_ROLE]["sha256"]
        or frozen_transform.get("config_sha256")
        != base_sensor["formal_error_profile"]["sha256"]
        or frozen_transform.get("error_bank_schema_version")
        != V6_OBSERVER_CAPTURE_ERROR_BANK_SCHEMA_VERSION
        or frozen_transform.get("error_bank_sha256") != new_bank["sha256"]
    ):
        raise RepairEvaluationError(
            "v6 observer capture frozen sensor transform did not recompute exactly"
        )
    adapted_contract = copy.deepcopy(base_contract)
    adapted_contract["rng"] = adapted_protocol["repair_evaluation_rng"]
    adapted_contract["sensor"] = adapted_protocol["sensor_contract"]
    adapted_contract["outputs"] = adapted_protocol["registered_outputs"]
    expected_frozen_seeds = {
        "checkpoint": checkpoint_seed,
        "genesis": genesis_by_checkpoint[key],
        "sensor": sensor_by_checkpoint[key],
        **{
            f"context.{index:02d}": value
            for index, value in enumerate(context_by_checkpoint[key])
        },
    }
    frozen_seed_map = stage_protocol.get("capture_contract", {}).get(
        "frozen_seed_identity_by_checkpoint"
    )
    if (
        not isinstance(frozen_seed_map, dict)
        or set(frozen_seed_map) != expected_checkpoint_keys
        or frozen_seed_map[key] != expected_frozen_seeds
    ):
        raise RepairEvaluationError(
            "v6 observer capture frozen seed identity mismatch"
        )
    frozen_dt = (
        stage_protocol.get("frozen_config", {})
        .get("capture", {})
        .get("dt_seconds")
    )
    if (
        type(frozen_dt) is bool
        or not isinstance(frozen_dt, (int, float))
        or float(frozen_dt) != float(runtime["dt_s"])
    ):
        raise RepairEvaluationError(
            "v6 observer capture frozen dt differs from the base runtime"
        )
    return {
        "stage_protocol": stage_protocol,
        "stage_protocol_sha256": stage_protocol_binding["sha256"],
        "base_protocol": adapted_protocol,
        "base_contract": adapted_contract,
        "arm_name": arm_name,
        "lane_role": dummy_slots[key]["lane_role"],
        "dummy_pass_output": dummy_slots[key]["pass_output"],
        "dummy_raw_evidence_output": dummy_slots[key][
            "raw_evidence_output"
        ],
        "capture_output": expected_capture_output,
        "dt_seconds": float(frozen_dt),
        "frozen_seeds": expected_frozen_seeds,
        "frozen_transform": frozen_transform,
        "adapter_diff_paths": sorted(".".join(path) for path in actual_diffs),
        "base_sensor_error_bank_sha256": old_bank["sha256"],
        "adapted_sensor_error_bank_sha256": new_bank["sha256"],
    }


def run_pass(
    *,
    protocol_path: Path,
    arm_name: str,
    checkpoint_seed: int,
    lane_role: str,
    output_path: Path,
    observer_capture_hook: PassiveObserverCaptureHook | None = None,
    stop_after_observer_capture: bool = False,
    capture_protocol_sha256: str | None = None,
) -> dict[str, Any]:
    if type(stop_after_observer_capture) is not bool:
        raise TypeError("stop_after_observer_capture must be exact bool")
    if stop_after_observer_capture and observer_capture_hook is None:
        raise RepairEvaluationError(
            "observer capture stop requires a capture hook"
        )
    if stop_after_observer_capture:
        capture_protocol_sha256 = _require_stage_a_protocol_sha256(
            capture_protocol_sha256,
            argument="capture_protocol_sha256",
        )
    elif capture_protocol_sha256 is not None:
        raise RepairEvaluationError(
            "legacy run_pass forbids capture_protocol_sha256"
        )
    protocol_path = protocol_path.expanduser().resolve()
    output_path = output_path.expanduser().resolve()
    if output_path.exists():
        raise FileExistsError(f"refusing to overwrite pass output: {output_path}")
    if stop_after_observer_capture:
        capture_adapter = load_v6_observer_capture_execution_adapter(
            protocol_path=protocol_path,
            protocol_sha256=capture_protocol_sha256,
            checkpoint_seed=checkpoint_seed,
        )
        if (
            arm_name != capture_adapter["arm_name"]
            or lane_role != capture_adapter["lane_role"]
        ):
            raise RepairEvaluationError(
                "v6 observer capture arm/lane differs from its frozen adapter"
            )
        protocol = capture_adapter["base_protocol"]
        contract = capture_adapter["base_contract"]
        expected_output = capture_adapter["dummy_pass_output"]
        raw_evidence_path = capture_adapter["dummy_raw_evidence_output"]
    else:
        requested_protocol = load_strict_json(protocol_path)
        if _v6_stage_a_header(requested_protocol):
            raise RepairEvaluationError(
                "v6 Stage-A protocol is capture-stop-only"
            )
        protocol = requested_protocol
        contract = validate_protocol(protocol, protocol_path=protocol_path)
        expected_output = registered_pass_path(
            protocol,
            arm=arm_name,
            checkpoint_seed=checkpoint_seed,
            lane_role=lane_role,
        )
        raw_evidence_path = registered_raw_evidence_path(
            protocol,
            arm=arm_name,
            checkpoint_seed=checkpoint_seed,
            lane_role=lane_role,
        )
    if output_path != expected_output:
        raise RepairEvaluationError("pass output differs from registered slot")
    if checkpoint_seed not in contract["checkpoint_seeds"]:
        raise RepairEvaluationError("checkpoint seed is not registered")
    project_root = Path(__file__).resolve().parent.parent
    implementation_hashes = verify_implementation_contract(
        protocol,
        project_root=project_root,
    )
    selection = contract["selection"]
    candidate = canonical_candidate(selection)
    checkpoint = checkpoint_record(selection, checkpoint_seed=checkpoint_seed)
    context_seed_bank = (
        contract["rng"].get("checkpoint_context_seed_banks", {}).get(str(checkpoint_seed))
    )
    genesis_seed = contract["rng"].get("checkpoint_genesis_seeds", {}).get(str(checkpoint_seed))
    expected_contexts = int(contract["fixed_budget"]["contexts"])
    if (
        not isinstance(context_seed_bank, list)
        or len(context_seed_bank) != expected_contexts
        or len(set(context_seed_bank)) != expected_contexts
        or any(type(value) is not int or value < 0 for value in context_seed_bank)
        or type(genesis_seed) is not int
        or genesis_seed < 0
    ):
        raise RepairEvaluationError("repair evaluation seeds are invalid")
    runtime = contract["runtime"]
    steps = int(runtime["steps"])
    dropout_start = int(runtime["dropout_start_step"])
    dropout_steps = int(runtime["dropout_steps"])
    quarantine_protocol_enabled = prior_quarantine_protocol_enabled(runtime)
    quarantine_enabled = prior_quarantine_enabled_for_arm(runtime, arm_name)
    if dropout_start + dropout_steps != steps:
        raise RepairEvaluationError("dropout window must end at the evaluation horizon")
    if (
        stop_after_observer_capture
        and dropout_start != OBSERVER_CAPTURE_TRANSITION_COUNT
    ):
        raise RepairEvaluationError(
            "observer capture stop requires an exact 300-transition pre-dropout window"
        )

    _bootstrap_genesis_runtime()
    import genesis as gs

    genesis_source = Path(gs.__file__).resolve().parents[1]
    genesis_source_tree = sha256_source_tree(genesis_source)
    expected_genesis_sha = protocol["execution_environment"]["genesis_source_tree_sha256"]
    if (
        genesis_source_tree["sha256"] != expected_genesis_sha
        or str(getattr(gs, "__version__", ""))
        != protocol["execution_environment"]["genesis_version"]
    ):
        raise RepairEvaluationError("Genesis source-tree SHA256 or version mismatch")
    gs.init(
        backend=gs.amdgpu,
        precision="32",
        seed=genesis_seed,
        performance_mode=False,
        logging_level="warning",
    )
    visible_gpu_count = torch.cuda.device_count()
    if (
        gs.backend != gs.amdgpu
        or not torch.cuda.is_available()
        or visible_gpu_count != 1
        or not torch.version.hip
    ):
        raise RepairEvaluationError("exactly one Radeon/ROCm GPU is required")

    from flightguard.controller import (
        BatchedWaypointController,
        controller_config_for_profile,
    )
    from flightguard.domain_randomization import DomainParameters
    from flightguard.gate_math import gate_crossing, gate_lookthrough_target
    from flightguard.genesis_env import FlightGuardGenesisEnv

    device = gs.device
    contexts = len(context_seed_bank)
    scheduled = candidate["scheduled"]
    if lane_role == "fault":
        thrust = float(scheduled["thrust_scale"])
        wind = list(scheduled["wind_acceleration_mps2"])
        delay = int(scheduled["action_delay_steps"])
    else:
        thrust = 1.0
        wind = [0.0, 0.0, 0.0]
        delay = 0
    domain = DomainParameters(
        mass_scale=torch.ones(contexts),
        thrust_scale=torch.ones(contexts),
        wind_acceleration_mps2=torch.zeros((contexts, 3)),
        action_delay_steps=torch.zeros(contexts, dtype=torch.long),
        stratum=torch.full((contexts,), -1, dtype=torch.long),
        profile="adversarial_v3",
        seed=genesis_seed,
        scheduled_thrust_scale=torch.full((contexts,), thrust),
        scheduled_wind_acceleration_mps2=torch.tensor(
            [wind] * contexts,
            dtype=torch.float32,
        ),
        scheduled_action_delay_steps=torch.full(
            (contexts,),
            delay,
            dtype=torch.long,
        ),
    )

    def prebuild_hook(**kwargs: Any) -> NativeIMUBinding:
        return attach_native_imu_prebuild(
            **kwargs,
            sensor_profile=NOISE_FREE_API_FRAME_PROFILE,
        )

    env = FlightGuardGenesisEnv(
        contexts,
        domain_parameters=domain,
        delay_history_max_steps=int(runtime["maximum_action_delay_steps"]),
        prebuild_scene_hook=prebuild_hook,
    )
    if env.dt != float(runtime["dt_s"]):
        raise RepairEvaluationError("Genesis dt differs from repair protocol")
    binding = env.prebuild_attachment
    if (
        not isinstance(binding, NativeIMUBinding)
        or binding.evidence.get("sensor_profile_sha256")
        != NOISE_FREE_API_FRAME_PROFILE.canonical_sha256()
        or binding.evidence.get("scene_was_unbuilt_on_prebuild_return") is not True
    ):
        raise RepairEvaluationError("native IMU prebuild attachment is unproven")
    runtime_asset_sha = sha256_file(env.drone_urdf)
    if runtime_asset_sha != protocol["execution_environment"]["corrected_racer_urdf_sha256"]:
        raise RepairEvaluationError(
            "runtime RACE asset differs from preflight-bound corrected URDF"
        )
    model = load_model(Path(checkpoint["path"]), device)
    controller_config = controller_config_for_profile(str(runtime["controller_profile"]))
    controller_config = replace(
        controller_config,
        max_upward_vertical_acceleration=float(runtime["max_upward_vertical_acceleration_mps2"]),
        max_downward_vertical_acceleration=float(
            runtime["max_downward_vertical_acceleration_mps2"]
        ),
    )
    controller = BatchedWaypointController(controller_config)
    gate_offsets = r5_context_gate_offsets(
        list(context_seed_bank),
        y_jitter_m=float(runtime["gate_y_jitter_m"]),
        z_jitter_m=float(runtime["gate_z_jitter_m"]),
    )
    env.gates += gate_offsets.to(device=device)[:, None, :]
    env.reset(torch.arange(contexts, device=device))
    sensor_bank = build_sensor_error_bank(
        context_seeds=context_seed_bank,
        steps=steps,
        dt=env.dt,
        registered_noise_seed=registered_sensor_seed(
            contract["sensor"],
            checkpoint_seed=checkpoint_seed,
        ),
    )
    r5_measurement_bank = build_r5_context_measurement_bank(
        context_seeds=context_seed_bank,
        steps=steps,
        runtime=runtime,
    )
    attitude_bias = torch.tensor(
        runtime["attitude_bias_deg"],
        device=device,
        dtype=torch.float32,
    ) * (math.pi / 180.0)
    angular_velocity_bias = torch.tensor(
        runtime["angular_velocity_bias_rad_s"],
        device=device,
        dtype=torch.float32,
    )
    online_context = make_r5_online_context(
        batch_size=contexts,
        device=device,
        runtime=runtime,
    )
    action_only_shadow_context = (
        make_r5_online_context(
            batch_size=contexts,
            device=device,
            runtime=runtime,
        )
        if arm_name == HardeningArm.ACTION_ONLY.value
        else None
    )

    active = torch.ones(contexts, dtype=torch.bool, device=device)
    terminal = torch.zeros_like(active)
    success = torch.zeros_like(active)
    failed = torch.zeros_like(active)
    gates_passed = torch.zeros(contexts, dtype=torch.long, device=device)
    control_gate_index = torch.zeros_like(gates_passed)
    terminal_step = torch.full((contexts,), -1, dtype=torch.long, device=device)
    saturation_steps = torch.zeros_like(gates_passed)
    active_control_steps = torch.zeros_like(gates_passed)
    dropout_squared_error_sum = torch.zeros(contexts, dtype=torch.float32, device=device)
    endpoint_error = torch.zeros_like(dropout_squared_error_sum)
    visible: ControllerVisibleState | None = None
    shadow_position = (
        env.drone.get_pos().detach().clone() if arm_name == HardeningArm.ACTION_ONLY.value else None
    )
    shadow_velocity = (
        env.drone.get_vel().detach().clone() if arm_name == HardeningArm.ACTION_ONLY.value else None
    )
    estimator = None
    calibration: FrozenAccelerometerCalibration | None = None
    last_profiled_sample: NativeIMUSample | None = None
    force_history: list[torch.Tensor] = []
    quaternion_history: list[torch.Tensor] = []
    velocity_history: list[torch.Tensor] = []
    calibration_valid_history: list[torch.Tensor] = []
    pending_post_step_calibration_quaternion: torch.Tensor | None = None
    calibration_alignment_compared_values = 0
    calibration_alignment_raw_bit_mismatched_values = 0
    trace: dict[str, list[torch.Tensor]] = {field: [] for field in TRACE_FIELDS}
    all_finite = True
    all_active_at_freeze = False
    activation_order_pass = False
    scheduled_targets_persist = True
    sensor_bank_steps_consumed = 0
    native_sensor_read_count = 0
    policy_sensor_commit_count = 0
    baseline_action_raw_bit_mismatched_values = 0
    baseline_action_compared_values = 0
    baseline_prior_raw_bit_mismatched_values = 0
    baseline_prior_compared_values = 0
    baseline_state_raw_bit_mismatched_values = 0
    baseline_state_compared_values = 0
    baseline_context_state_mismatched_tensors = 0
    baseline_context_state_compared_tensors = 0
    r5_context_state_parity_at_freeze: dict[str, Any] | None = None
    r5_context_summary: dict[str, Any] | None = None
    frozen_residual_quantile_mps2: torch.Tensor | None = None
    context_qualified_at_freeze = False
    demo_replay_records: list[dict[str, Any]] = []
    raw_evidence_trace: dict[str, list[torch.Tensor]] = {
        field: []
        for field in (
            "truth_position",
            "truth_velocity",
            "truth_quaternion",
            "truth_angular_velocity",
            "estimated_position",
            "estimated_velocity",
            "estimated_quaternion",
            "estimated_angular_velocity",
            "issued_action",
            "applied_action",
            "active_before_step",
            "terminal",
            "failed",
            "success",
            "gates_passed",
            "gate_index",
            "position_error_squared_m2",
            "scored_position_error_squared_m2",
            "applied_action_saturated",
            *(
                (
                    "innovation_norm",
                    "quarantine_bound",
                    "newly_quarantined",
                    "prior_quarantined",
                    "prior_quarantine_count",
                )
                if quarantine_protocol_enabled
                else ()
            ),
        )
    }
    started = time.perf_counter()

    print(
        json.dumps(
            {
                "event": "causal_imu_repair_pass_start",
                "arm": arm_name,
                "checkpoint_seed": checkpoint_seed,
                "lane_role": lane_role,
                "contexts": contexts,
                "steps": steps,
            },
            sort_keys=True,
        ),
        flush=True,
    )

    with torch.inference_mode():
        for step in range(steps):
            if step == int(runtime["context_fit_steps"]):
                online_context.begin_scoring()
                if action_only_shadow_context is not None:
                    action_only_shadow_context.begin_scoring()
            if step == dropout_start:
                online_context.freeze()
                r5_context_summary = online_context.summary()
                frozen_residual_quantile_mps2 = (
                    online_context.selected_residual_quantile_mps2.detach().clone()
                )
                context_qualified = (
                    online_context.selected_valid
                    & torch.isfinite(online_context.selected_residual_quantile_mps2)
                    & (online_context.selected_residual_quantile_mps2 >= 0.0)
                )
                context_qualified_at_freeze = bool(context_qualified.all())
                if action_only_shadow_context is not None:
                    action_only_shadow_context.freeze()
                    r5_context_state_parity_at_freeze = module_state_raw_exact(
                        online_context,
                        action_only_shadow_context,
                    )

            active_before = active.clone()
            position = env.drone.get_pos()
            quaternion = env.drone.get_quat()
            velocity = env.drone.get_vel()
            angular_velocity = env.drone.get_ang()
            measured_quaternion, measured_angular_velocity = perturb_imu(
                quaternion,
                angular_velocity,
                r5_measurement_bank["attitude_noise"][step].to(device=device) + attitude_bias,
                r5_measurement_bank["angular_velocity_noise"][step].to(device=device)
                + angular_velocity_bias,
            )
            if step == 0:
                _capture_initial_vio(
                    observer_capture_hook,
                    quaternion_body_to_world=measured_quaternion,
                    velocity_world=velocity,
                )
            if pending_post_step_calibration_quaternion is not None:
                calibration_alignment_compared_values += measured_quaternion.numel()
                calibration_alignment_raw_bit_mismatched_values += _raw_float32_mismatch_count(
                    measured_quaternion,
                    pending_post_step_calibration_quaternion,
                )
                pending_post_step_calibration_quaternion = None
            gate_center, target_yaw = indexed_gate(
                env.gates,
                env.gate_yaws,
                control_gate_index,
            )
            target = gate_lookthrough_target(
                gate_center,
                target_yaw,
                float(runtime["gate_lookthrough_m"]),
            )
            if step < dropout_start:
                visible = _visible_from_truth(
                    position=position,
                    quaternion=measured_quaternion,
                    velocity=velocity,
                    angular_velocity=measured_angular_velocity,
                    target=target,
                    dead=~active_before,
                )
                if not velocity_history:
                    velocity_history.append(velocity.detach().clone())
                if shadow_position is not None and shadow_velocity is not None:
                    shadow_position = position.detach().clone()
                    shadow_velocity = velocity.detach().clone()
            else:
                if visible is None:
                    raise RepairEvaluationError("dropout visible state was not frozen")
                visible = replace(
                    visible,
                    quaternion=(
                        measured_quaternion.detach().clone()
                        if arm_name == HardeningArm.ACTION_ONLY.value or step == dropout_start
                        else visible.quaternion
                    ),
                    angular_velocity_world=(
                        measured_angular_velocity.detach().clone()
                        if arm_name == HardeningArm.ACTION_ONLY.value or step == dropout_start
                        else visible.angular_velocity_world
                    ),
                    target=target.detach().clone(),
                    dead=(visible.dead | ~active_before).detach().clone(),
                )
            if step == dropout_start:
                all_active_at_freeze = bool(active_before.all())
                if last_profiled_sample is None:
                    raise RepairEvaluationError("last pre-dropout native sample is missing")
                calibration = calibrate_visible_accelerometer_bias(
                    specific_force_body_history=torch.stack(force_history),
                    quaternion_body_to_world_history=torch.stack(quaternion_history),
                    velocity_world_history=torch.stack(velocity_history),
                    valid_transition_mask=torch.stack(calibration_valid_history),
                    dt=env.dt,
                    minimum_samples=int(runtime["minimum_calibration_samples"]),
                )
                arm = HardeningArm(arm_name)
                estimator = make_frozen_arm_estimator(
                    arm,
                    visible=visible,
                    last_native_sample=(
                        None if arm is HardeningArm.ACTION_ONLY else last_profiled_sample
                    ),
                    accelerometer_calibration=(
                        calibration
                        if hardening_arm_spec(arm).requires_accelerometer_calibration
                        else None
                    ),
                    frozen_residual_quantile_mps2=(
                        frozen_residual_quantile_mps2 if quarantine_enabled else None
                    ),
                    enable_prior_quarantine=quarantine_enabled,
                )

            action = dispatch_post_dropout_controller(controller, visible)
            action = torch.where(
                active_before[:, None],
                action,
                torch.zeros_like(action),
            )
            shadow_action: torch.Tensor | None = None
            if action_only_shadow_context is not None:
                if shadow_position is None or shadow_velocity is None:
                    raise RepairEvaluationError("ActionOnly shadow state is missing")
                shadow_action = controller(
                    shadow_position,
                    measured_quaternion,
                    shadow_velocity,
                    measured_angular_velocity,
                    target,
                )
                shadow_action = torch.where(
                    active_before[:, None],
                    shadow_action,
                    torch.zeros_like(shadow_action),
                )
                baseline_action_compared_values += action.numel()
                baseline_action_raw_bit_mismatched_values += _raw_float32_mismatch_count(
                    action, shadow_action
                )

            online_context.push_issued(action)
            if action_only_shadow_context is not None and shadow_action is not None:
                action_only_shadow_context.push_issued(shadow_action)
                context_parity = module_state_raw_exact(
                    online_context,
                    action_only_shadow_context,
                )
                baseline_context_state_compared_tensors += context_parity["tensor_count"]
                baseline_context_state_mismatched_tensors += len(
                    context_parity["mismatched_tensor_names"]
                )

            prior = (
                online_context.predict_acceleration(
                    model,
                    visible.velocity,
                    visible.quaternion,
                    visible.angular_velocity_world,
                )
                if step >= dropout_start
                else None
            )
            shadow_prior: torch.Tensor | None = None
            if (
                step >= dropout_start
                and action_only_shadow_context is not None
                and shadow_velocity is not None
            ):
                shadow_prior = action_only_shadow_context.predict_acceleration(
                    model,
                    shadow_velocity,
                    measured_quaternion,
                    measured_angular_velocity,
                )
                if prior is None:
                    raise RepairEvaluationError("ActionOnly R5 prior is missing")
                baseline_prior_compared_values += prior.numel()
                baseline_prior_raw_bit_mismatched_values += _raw_float32_mismatch_count(
                    prior, shadow_prior
                )
            if step <= dropout_start:
                trace_values = {
                    "truth_position": position,
                    "truth_velocity": velocity,
                    "truth_quaternion": quaternion,
                    "truth_angular_velocity": angular_velocity,
                    "estimated_position": visible.position,
                    "estimated_velocity": visible.velocity,
                    "estimated_quaternion": visible.quaternion,
                    "estimated_angular_velocity": visible.angular_velocity_world,
                    "issued_action": action,
                    "applied_action_before_step": env.last_applied_action,
                    "active_before_step": active_before,
                }
                for field, value in trace_values.items():
                    trace[field].append(value.detach().clone())

            if step == dropout_start:
                if prior is None:
                    raise RepairEvaluationError("onset model prior is missing")
                activation_order_pass = env.activate_scheduled_faults()
            result = env.step(action)
            raw_sample = clone_native_imu_reading(binding.sensor)
            native_sensor_read_count += 1
            profiled_sample = apply_sensor_error(
                raw_sample,
                acceleration_error=sensor_bank["acceleration_error"][step],
                gyro_error=sensor_bank["gyro_error"][step],
            )
            sensor_bank_steps_consumed += 1
            last_profiled_sample = profiled_sample
            next_position = env.drone.get_pos()
            next_quaternion = env.drone.get_quat()
            next_velocity = env.drone.get_vel()
            next_angular_velocity = env.drone.get_ang()
            next_calibration_quaternion: torch.Tensor | None = None
            if step < dropout_start:
                next_calibration_quaternion, _ = perturb_imu(
                    next_quaternion,
                    next_angular_velocity,
                    r5_measurement_bank["attitude_noise"][step + 1].to(device=device)
                    + attitude_bias,
                    r5_measurement_bank["angular_velocity_noise"][step + 1].to(device=device)
                    + angular_velocity_bias,
                )
                pending_post_step_calibration_quaternion = (
                    next_calibration_quaternion.detach().clone()
                )
                _capture_observer_transition(
                    observer_capture_hook,
                    step_index=step,
                    dt_s=env.dt,
                    raw_sample=raw_sample,
                    delivered_sample=profiled_sample,
                    next_quaternion_body_to_world=next_calibration_quaternion,
                    next_velocity_world=next_velocity,
                    valid_transition_mask=active_before,
                )
                if (
                    stop_after_observer_capture
                    and step + 1 == OBSERVER_CAPTURE_TRANSITION_COUNT
                ):
                    transition_count = getattr(
                        observer_capture_hook,
                        "transition_count",
                        None,
                    )
                    complete = getattr(observer_capture_hook, "complete", None)
                    if (
                        type(transition_count) is not int
                        or transition_count != OBSERVER_CAPTURE_TRANSITION_COUNT
                        or complete is not True
                        or native_sensor_read_count
                        != OBSERVER_CAPTURE_TRANSITION_COUNT
                        or sensor_bank_steps_consumed
                        != OBSERVER_CAPTURE_TRANSITION_COUNT
                        or activation_order_pass
                    ):
                        raise RepairEvaluationError(
                            "observer capture did not stop at the exact pre-dropout boundary"
                        )
                    return {
                        "schema_version": OBSERVER_CAPTURE_STOP_SCHEMA_VERSION,
                        "status": "CAPTURE_COMPLETE",
                        "simulation_only": True,
                        "contains_observer_metrics": False,
                        "identity": {
                            "arm": arm_name,
                            "checkpoint_seed": checkpoint_seed,
                            "lane_role": lane_role,
                        },
                        "captured_transition_count": transition_count,
                        "native_sensor_read_count": native_sensor_read_count,
                        "sensor_bank_steps_consumed": sensor_bank_steps_consumed,
                        "dropout_step_executed": False,
                        "dropout_action_dispatched": False,
                        "scheduled_fault_activated": False,
                        "legacy_pass_output_written": False,
                    }
            applied_action = env.last_applied_action
            all_finite &= bool(
                torch.isfinite(position).all()
                and torch.isfinite(quaternion).all()
                and torch.isfinite(velocity).all()
                and torch.isfinite(angular_velocity).all()
                and torch.isfinite(measured_quaternion).all()
                and torch.isfinite(measured_angular_velocity).all()
                and torch.isfinite(action).all()
                and torch.isfinite(raw_sample.specific_force_body).all()
                and torch.isfinite(raw_sample.angular_velocity_body).all()
                and torch.isfinite(profiled_sample.specific_force_body).all()
                and torch.isfinite(profiled_sample.angular_velocity_body).all()
                and torch.isfinite(next_position).all()
                and torch.isfinite(next_quaternion).all()
                and torch.isfinite(next_velocity).all()
                and torch.isfinite(next_angular_velocity).all()
                and torch.isfinite(applied_action).all()
            )

            if step < dropout_start:
                online_context.observe_transition(
                    model,
                    velocity,
                    measured_quaternion,
                    measured_angular_velocity,
                    next_velocity,
                    dt=env.dt,
                    phase=("fit" if step < int(runtime["context_fit_steps"]) else "score"),
                    mask=active_before,
                )
                if action_only_shadow_context is not None:
                    action_only_shadow_context.observe_transition(
                        model,
                        velocity,
                        measured_quaternion,
                        measured_angular_velocity,
                        next_velocity,
                        dt=env.dt,
                        phase=("fit" if step < int(runtime["context_fit_steps"]) else "score"),
                        mask=active_before,
                    )
                force_history.append(profiled_sample.specific_force_body.detach().clone())
                if next_calibration_quaternion is None:
                    raise RepairEvaluationError("post-step calibration quaternion is missing")
                quaternion_history.append(next_calibration_quaternion.detach().clone())
                velocity_history.append(next_velocity.detach().clone())
                calibration_valid_history.append(active_before.detach().clone())
                next_visible = _visible_from_truth(
                    position=next_position,
                    quaternion=measured_quaternion,
                    velocity=next_velocity,
                    angular_velocity=measured_angular_velocity,
                    target=target,
                    dead=~active_before,
                )
                if shadow_position is not None and shadow_velocity is not None:
                    shadow_position = next_position.detach().clone()
                    shadow_velocity = next_velocity.detach().clone()
            else:
                if prior is None or visible is None:
                    raise RepairEvaluationError("post-dropout transition state is missing")
                next_visible, _corrected_acceleration = commit_post_dropout_transition(
                    arm_name,
                    visible=visible,
                    prior_acceleration_world_mps2=prior,
                    active_mask=active_before,
                    dt=env.dt,
                    estimator=estimator,
                    native_imu_sensor=(
                        None
                        if arm_name == HardeningArm.ACTION_ONLY.value
                        else SimpleNamespace(
                            read=lambda sample=profiled_sample: SimpleNamespace(
                                lin_acc=sample.specific_force_body,
                                ang_vel=sample.angular_velocity_body,
                            )
                        )
                    ),
                )
                if arm_name != HardeningArm.ACTION_ONLY.value:
                    policy_sensor_commit_count += 1
                if arm_name == HardeningArm.ACTION_ONLY.value:
                    if shadow_position is None or shadow_velocity is None or shadow_prior is None:
                        raise RepairEvaluationError(
                            "ActionOnly frozen R5 shadow transition is missing"
                        )
                    proposed_shadow_position, proposed_shadow_velocity = r5_baseline_integrate(
                        shadow_position,
                        shadow_velocity,
                        shadow_prior,
                        dt=env.dt,
                    )
                    next_shadow_position = torch.where(
                        active_before[:, None],
                        proposed_shadow_position,
                        shadow_position,
                    )
                    next_shadow_velocity = torch.where(
                        active_before[:, None],
                        proposed_shadow_velocity,
                        shadow_velocity,
                    )
                    for actual, expected in (
                        (next_visible.position, next_shadow_position),
                        (next_visible.velocity, next_shadow_velocity),
                    ):
                        baseline_state_compared_values += actual.numel()
                        baseline_state_raw_bit_mismatched_values += _raw_float32_mismatch_count(
                            actual, expected
                        )
                    shadow_position = next_shadow_position.detach().clone()
                    shadow_velocity = next_shadow_velocity.detach().clone()

            estimated_crossing = gate_crossing(
                visible.position,
                next_visible.position,
                gate_center,
                target_yaw,
                half_width=0.6,
                half_height=0.5,
                proxy_radius=0.08,
            )
            control_passed = (
                estimated_crossing.passed
                & active_before
                & (control_gate_index < env.gates.shape[1])
            )
            control_gate_index += control_passed.long()
            visible = next_visible
            gates_passed += (result.passed & active_before).long()
            completed = result.done & (env.gate_index >= env.gates.shape[1])
            simulator_failed = result.done & ~completed
            outcome = apply_dead_mask_to_outcome(
                simulator_terminal=result.done,
                simulator_failed=simulator_failed,
                estimator_dead=visible.dead,
            )
            newly_done = active_before & outcome.terminal
            newly_successful = active_before & result.done & completed & ~outcome.failed
            success |= newly_successful
            failed |= active_before & outcome.failed
            terminal |= newly_done
            terminal_step[newly_done] = step + 1
            active = active_before & ~newly_done
            visible = replace(
                visible,
                dead=(visible.dead | ~active).detach().clone(),
            )
            demo_lane = 0
            demo_replay_records.append(
                {
                    "step": step,
                    "fault_onset": step == dropout_start,
                    "truth_position": (next_position[demo_lane].detach().cpu().tolist()),
                    "truth_quaternion": (next_quaternion[demo_lane].detach().cpu().tolist()),
                    "estimated_position": (visible.position[demo_lane].detach().cpu().tolist()),
                    "issued_action": action[demo_lane].detach().cpu().tolist(),
                    "applied_action": (applied_action[demo_lane].detach().cpu().tolist()),
                    "terminal": bool(terminal[demo_lane].item()),
                    "gate_index": int(env.gate_index[demo_lane].item()),
                }
            )

            if step >= dropout_start:
                scheduled_targets_persist &= env.scheduled_fault_targets_active()
                active_control_steps += active_before.long()
                applied_action_saturated = active_before & (
                    applied_action.abs() >= 1.0 - 1.0e-6
                ).any(dim=1)
                saturation_steps += applied_action_saturated.long()
                current_error = torch.linalg.vector_norm(
                    visible.position - next_position,
                    dim=1,
                )
                endpoint_error = torch.where(
                    active_before,
                    current_error,
                    endpoint_error,
                )
                dropout_squared_error_sum += torch.where(
                    active_before,
                    current_error.square(),
                    endpoint_error.square(),
                )
                scored_squared_error = torch.where(
                    active_before,
                    current_error.square(),
                    endpoint_error.square(),
                )
            else:
                applied_action_saturated = active_before & (
                    applied_action.abs() >= 1.0 - 1.0e-6
                ).any(dim=1)
                current_error = torch.linalg.vector_norm(
                    visible.position - next_position,
                    dim=1,
                )
                scored_squared_error = torch.zeros_like(current_error)

            quarantine_step = prior_quarantine_step_evidence(
                estimator,
                enabled=quarantine_enabled and step >= dropout_start,
                batch=contexts,
                device=device,
                dtype=visible.position.dtype,
            )
            raw_step_values = {
                "truth_position": next_position,
                "truth_velocity": next_velocity,
                "truth_quaternion": next_quaternion,
                "truth_angular_velocity": next_angular_velocity,
                "estimated_position": visible.position,
                "estimated_velocity": visible.velocity,
                "estimated_quaternion": visible.quaternion,
                "estimated_angular_velocity": visible.angular_velocity_world,
                "issued_action": action,
                "applied_action": applied_action,
                "active_before_step": active_before,
                "terminal": terminal,
                "failed": failed,
                "success": success,
                "gates_passed": gates_passed,
                "gate_index": env.gate_index,
                "position_error_squared_m2": current_error.square(),
                "scored_position_error_squared_m2": scored_squared_error,
                "applied_action_saturated": applied_action_saturated,
            }
            if quarantine_protocol_enabled:
                quarantine_count = (
                    estimator.prior_quarantine_count.detach().clone()
                    if quarantine_enabled
                    and estimator is not None
                    and step >= dropout_start
                    else torch.zeros(contexts, device=device, dtype=torch.long)
                )
                raw_step_values.update(
                    {
                        "innovation_norm": quarantine_step.innovation_norm,
                        "quarantine_bound": quarantine_step.quarantine_bound,
                        "newly_quarantined": quarantine_step.newly_quarantined,
                        "prior_quarantined": quarantine_step.prior_quarantined,
                        "prior_quarantine_count": quarantine_count,
                    }
                )
            for field, value in raw_step_values.items():
                raw_evidence_trace[field].append(value.detach().contiguous().cpu().clone())

            done_index = torch.nonzero(newly_done, as_tuple=False).reshape(-1)
            if done_index.numel():
                env.reset(done_index)
            if (step + 1) % 200 == 0:
                print(
                    json.dumps(
                        {
                            "event": "causal_imu_repair_pass_progress",
                            "step": step + 1,
                            "active": int(active.sum().item()),
                            "success": int(success.sum().item()),
                        },
                        sort_keys=True,
                    ),
                    flush=True,
                )

    torch.cuda.synchronize()
    elapsed = time.perf_counter() - started
    r5_context_summary = online_context.summary()
    trace_digest = raw_trace_digest(trace)
    metrics = summarize_metrics(
        success=success,
        terminal=terminal,
        gates_passed=gates_passed,
        dropout_squared_error_sum=dropout_squared_error_sum,
        endpoint_error=endpoint_error,
        saturation_steps=saturation_steps,
        active_control_steps=active_control_steps,
        dropout_steps=dropout_steps,
        gate_count=int(env.gates.shape[1]),
    )
    noop = exact_patch_off_noop_gate()
    kill = sensor_on_kill_magnitude_gate()
    intervention = measurement_error_intervention_gates()
    r5_structural_parity = r5_baseline_structural_parity_gate()
    action_only_shadow_exact = bool(
        arm_name != HardeningArm.ACTION_ONLY.value
        or (
            baseline_action_compared_values > 0
            and baseline_action_raw_bit_mismatched_values == 0
            and baseline_prior_compared_values > 0
            and baseline_prior_raw_bit_mismatched_values == 0
            and baseline_state_compared_values > 0
            and baseline_state_raw_bit_mismatched_values == 0
            and baseline_context_state_compared_tensors > 0
            and baseline_context_state_mismatched_tensors == 0
            and isinstance(r5_context_state_parity_at_freeze, dict)
            and r5_context_state_parity_at_freeze.get("exact") is True
        )
    )
    calibration_required = hardening_arm_spec(arm_name).requires_accelerometer_calibration
    calibration_pass = bool(
        calibration is not None
        and (
            not calibration_required
            or (
                calibration.valid.all()
                and (calibration.sample_count >= int(runtime["minimum_calibration_samples"])).all()
            )
        )
    )
    quarantine_bound_update_attempts = (
        int(estimator.post_freeze_quarantine_bound_update_attempts.item())
        if quarantine_enabled and estimator is not None
        else 0
    )
    quarantine_mechanism_matches = bool(
        not quarantine_protocol_enabled
        or (
            quarantine_enabled
            == (
                arm_name == HardeningArm.CAUSAL_IMU_PATCH.value
                and estimator is not None
                and estimator.config.prior_quarantine_enabled
            )
        )
    )
    quarantine_recurrence_pass = True
    if quarantine_protocol_enabled:
        quarantine_audit_arrays = {
            field: torch.stack(raw_evidence_trace[field], dim=0).contiguous().numpy()
            for field in (
                "active_before_step",
                "innovation_norm",
                "quarantine_bound",
                "newly_quarantined",
                "prior_quarantined",
                "prior_quarantine_count",
            )
        }
        try:
            validate_prior_quarantine_raw_recurrence(
                quarantine_audit_arrays,
                dropout_start_step=dropout_start,
                mechanism_enabled=quarantine_enabled,
                expected_frozen_bound=(
                    frozen_residual_quantile_mps2.detach().cpu().tolist()
                    if quarantine_enabled
                    and frozen_residual_quantile_mps2 is not None
                    else None
                ),
            )
        except RepairEvaluationError:
            quarantine_recurrence_pass = False
    checks = {
        "backend_is_amdgpu": gs.backend == gs.amdgpu,
        "visible_gpu_count_is_one": visible_gpu_count == 1,
        "torch_hip_nonempty": bool(torch.version.hip),
        "all_outputs_finite": all_finite
        and all(
            math.isfinite(float(value))
            for key, value in metrics.items()
            if isinstance(value, (int, float)) and key != "terminal_failure_count"
        ),
        "all_contexts_active_at_freeze": all_active_at_freeze,
        "all_contexts_qualified_at_freeze": context_qualified_at_freeze,
        "frozen_r5_baseline_structural_parity_pass": (r5_structural_parity["status"] == "PASS"),
        "frozen_context_has_zero_post_freeze_observation_updates": (
            r5_context_summary["post_freeze_update_attempts"] == 0
        ),
        "calibration_gate_pass": calibration_pass,
        "post_step_native_calibration_frame_alignment_raw_bit_exact": (
            pending_post_step_calibration_quaternion is None
            and calibration_alignment_compared_values == dropout_start * contexts * 4
            and calibration_alignment_raw_bit_mismatched_values == 0
        ),
        "fault_activated_exactly_once_after_first_onset_action": (
            activation_order_pass
            and env.scheduled_fault_activation_attempts == 1
            and env.scheduled_fault_activation_count == 1
        ),
        "scheduled_targets_persist_to_end": scheduled_targets_persist,
        "native_sensor_attached_prebuild": (
            binding.evidence["scene_was_unbuilt_on_prebuild_return"] is True
        ),
        "noise_free_native_profile_exact": (
            binding.evidence["sensor_profile_sha256"]
            == NOISE_FREE_API_FRAME_PROFILE.canonical_sha256()
        ),
        "deterministic_formal_error_bank_available": bool(sensor_bank["sha256"]),
        "sensor_error_bank_generator_code_bound": (
            sensor_error_bank_generator_code_sha256()
            == contract["sensor"]["post_read_error_bank_generator_code_sha256"]
        ),
        "sensor_error_bank_consumed_once_per_step": (sensor_bank_steps_consumed == steps),
        "native_sensor_read_once_per_step": native_sensor_read_count == steps,
        "policy_sensor_commit_schedule_exact": (
            policy_sensor_commit_count
            == (0 if arm_name == HardeningArm.ACTION_ONLY.value else dropout_steps)
        ),
        "pre_dropout_trace_available": trace_digest["steps"] == dropout_start + 1,
        "action_only_exact_frozen_r5_shadow_parity": action_only_shadow_exact,
        "sensor_on_kill_magnitude_pass": kill["status"] == "PASS",
        "zero_bank_exact_and_active_bank_kill_pass": (intervention["status"] == "PASS"),
        "patch_off_structural_noop_pass": noop["status"] == "PASS",
        "demo_replay_records_every_step": len(demo_replay_records) == steps,
        "applied_action_saturation_within_gate": (
            runtime.get("causal_prior_quarantine_variant")
            == "frozen-residual-q95-prior-quarantine"
            or metrics["maximum_applied_action_saturation_fraction"]
            <= float(protocol["acceptance_gates"]["maximum_applied_action_saturation_fraction"])
        ),
    }
    if quarantine_protocol_enabled:
        checks.update(
            {
                "prior_quarantine_threshold_has_zero_post_freeze_updates": (
                    quarantine_bound_update_attempts == 0
                ),
                "prior_quarantine_mechanism_matches_runtime_and_arm": (
                    quarantine_mechanism_matches
                ),
                "prior_quarantine_raw_state_recurrence_pass": (
                    quarantine_recurrence_pass
                ),
            }
        )
    status = "PASS" if all(checks.values()) else "FAIL"
    episodes = [
        {
            "context_index": index,
            "context_seed": context_seed,
            "mission_success": bool(success[index].item()),
            "mission_failure": not bool(success[index].item()),
            "terminal": bool(terminal[index].item()),
            "failed": bool(failed[index].item()),
            "terminal_step": (
                int(terminal_step[index].item()) if terminal_step[index].item() >= 0 else None
            ),
            "gates_passed": int(gates_passed[index].item()),
            "endpoint_error_m": float(endpoint_error[index].item()),
            "applied_action_saturation_fraction": float(
                (
                    saturation_steps[index].float()
                    / active_control_steps[index].clamp_min(1).float()
                ).item()
            ),
        }
        for index, context_seed in enumerate(context_seed_bank)
    ]
    raw_evidence_arrays: dict[str, np.ndarray] = {
        "schema_version": np.asarray(
            PRIOR_QUARANTINE_RAW_EVIDENCE_SCHEMA_VERSION
            if quarantine_protocol_enabled
            else RAW_EVIDENCE_SCHEMA_VERSION
        ),
        "arm": np.asarray(arm_name),
        "checkpoint_seed": np.asarray(checkpoint_seed, dtype=np.int64),
        "lane_role": np.asarray(lane_role),
        "candidate_id": np.asarray(candidate["candidate_id"]),
        "context_seeds": np.asarray(context_seed_bank, dtype=np.int64),
        "step_index": np.arange(steps, dtype=np.int64),
        "gate_count": np.asarray(int(env.gates.shape[1]), dtype=np.int64),
        **{
            field: torch.stack(values, dim=0).contiguous().numpy()
            for field, values in raw_evidence_trace.items()
        },
    }
    raw_evidence = write_raw_evidence_npz(
        raw_evidence_path,
        output_root=Path(contract["outputs"]["output_root"]),
        arrays=raw_evidence_arrays,
    )
    return {
        "schema_version": SCHEMA_VERSION,
        "status": status,
        "simulation_only": True,
        "repair_claim_eligible": False,
        "protocol": {
            "path": str(protocol_path),
            "sha256": contract["sha256"],
            "version": protocol["protocol_version"],
        },
        "identity": {
            "arm": arm_name,
            "checkpoint_seed": checkpoint_seed,
            "lane_role": lane_role,
            "candidate_id": candidate["candidate_id"],
            "context_seeds": context_seed_bank,
            "genesis_seed": genesis_seed,
        },
        "selection": {
            "path": selection["path"],
            "sha256": selection["sha256"],
            "discovery_seal_sha256": selection["discovery_seal"]["sha256"],
            "hidden_summary_sha256": selection["hidden_summary"]["sha256"],
            "hidden_evidence_sha256": selection["hidden_evidence_sha256"],
        },
        "checkpoint": checkpoint,
        "execution": {
            "backend": str(gs.backend),
            "device": str(device),
            "gpu_name": torch.cuda.get_device_name(0),
            "visible_gpu_count": visible_gpu_count,
            "torch_version": torch.__version__,
            "torch_hip": torch.version.hip,
            "genesis_version": str(gs.__version__),
            "genesis_source_tree": genesis_source_tree,
            "runtime_race_asset": str(env.drone_urdf),
            "runtime_race_asset_sha256": runtime_asset_sha,
            "elapsed_s": elapsed,
            "transitions_per_s": contexts * steps / elapsed,
            "implementation_files_sha256": implementation_hashes,
            "maximum_concurrent_gpu_processes": 1,
        },
        "runtime": {
            **runtime,
            "contexts": contexts,
            "transitions": contexts * steps,
        },
        "sensor": {
            "native_profile_sha256": (NOISE_FREE_API_FRAME_PROFILE.canonical_sha256()),
            "formal_error_profile_sha256": (FORMAL_REALISTIC_SENSOR_PROFILE.canonical_sha256()),
            "formal_error_bank_sha256": sensor_bank["sha256"],
            "formal_error_bank_raw_bytes_sha256": sensor_bank["raw_bytes_sha256"],
            "formal_error_bank_shape": sensor_bank["shape"],
            "formal_error_bank_dtype": sensor_bank["dtype"],
            "formal_error_bank_device": sensor_bank["device"],
            "r5_context_measurement_bank_sha256": r5_measurement_bank["sha256"],
            "r5_context_measurement_bank_raw_bytes_sha256": r5_measurement_bank["raw_bytes_sha256"],
            "r5_context_measurement_bank_shape": r5_measurement_bank["shape"],
            "r5_context_measurement_bank_dtype": r5_measurement_bank["dtype"],
            "r5_context_measurement_bank_device": r5_measurement_bank["device"],
            "r5_context_measurement_source_function_sha256": r5_measurement_bank[
                "source_function_sha256"
            ],
            "registered_noise_seed": sensor_bank["registered_noise_seed"],
            "post_read_error_bank_generator_code_sha256": (
                sensor_error_bank_generator_code_sha256()
            ),
            "bank_step_index_evidence": {
                "first_index": 0,
                "last_index": steps - 1,
                "consumed_count": sensor_bank_steps_consumed,
                "exactly_once_in_monotonic_loop": sensor_bank_steps_consumed == steps,
            },
            "native_sensor_schedule": {
                "native_sensor_attached_once_prebuild": True,
                "native_sensor_read_count": native_sensor_read_count,
                "post_read_error_bank_application_count": sensor_bank_steps_consumed,
                "policy_sensor_commit_count": policy_sensor_commit_count,
            },
            "matching_strategy": contract["sensor"]["matching_strategy"],
            "genesis_native_noise_matching_claimed": False,
            "policy_consumes_native_plus_bank": hardening_arm_spec(arm_name).consumes_native_imu,
            "action_only_sensor_attach_read_schedule_preserved_but_policy_zero_access": (
                arm_name != HardeningArm.ACTION_ONLY.value
                or not hardening_arm_spec(arm_name).consumes_native_imu
            ),
            "measurement_error_intervention_gates": intervention,
        },
        "causal_integrity": {
            "pre_dropout_raw_bit_trace": trace_digest,
            "r5_baseline_structural_parity": r5_structural_parity,
            "frozen_r5_same_process_shadow": {
                "name": (
                    "perturb_imu + FrozenAffineDelayContext + "
                    "BatchedWaypointController + frozen R5 integration"
                ),
                "applicable": arm_name == HardeningArm.ACTION_ONLY.value,
                "action": {
                    "compared_values": baseline_action_compared_values,
                    "raw_bit_mismatched_values": (baseline_action_raw_bit_mismatched_values),
                },
                "prior": {
                    "compared_values": baseline_prior_compared_values,
                    "raw_bit_mismatched_values": (baseline_prior_raw_bit_mismatched_values),
                },
                "state": {
                    "compared_values": baseline_state_compared_values,
                    "raw_bit_mismatched_values": (baseline_state_raw_bit_mismatched_values),
                },
                "context_state": {
                    "compared_tensors": baseline_context_state_compared_tensors,
                    "mismatched_tensors": baseline_context_state_mismatched_tensors,
                    "at_freeze": r5_context_state_parity_at_freeze,
                },
                "exact": action_only_shadow_exact,
            },
            "frozen_r5_context": r5_context_summary,
            **(
                {
                    "prior_quarantine": {
                        "protocol_enabled": True,
                        "mechanism_enabled_for_arm": quarantine_enabled,
                        "source": (
                            "frozen_r5_context.selected_residual_quantile_mps2"
                        ),
                        "frozen_residual_quantile_mps2": (
                            frozen_residual_quantile_mps2.detach().cpu().tolist()
                            if quarantine_enabled
                            and frozen_residual_quantile_mps2 is not None
                            else None
                        ),
                        "post_freeze_quarantine_bound_update_attempts": (
                            quarantine_bound_update_attempts
                        ),
                        "threshold_immutable": (
                            quarantine_bound_update_attempts == 0
                        ),
                        "raw_state_recurrence_pass": quarantine_recurrence_pass,
                    }
                }
                if quarantine_protocol_enabled
                else {}
            ),
            "all_contexts_qualified_at_freeze": context_qualified_at_freeze,
            "native_calibration_alignment": {
                "sensor_sample_time": "post_step_t_plus_1",
                "quaternion_time": "post_step_t_plus_1",
                "velocity_transition": "pre_step_t_to_post_step_t_plus_1",
                "next_visible_quaternion_raw_bit_equivalence_required": True,
                "compared_values": calibration_alignment_compared_values,
                "raw_bit_mismatched_values": (calibration_alignment_raw_bit_mismatched_values),
                "exact": (
                    pending_post_step_calibration_quaternion is None
                    and calibration_alignment_compared_values == dropout_start * contexts * 4
                    and calibration_alignment_raw_bit_mismatched_values == 0
                ),
            },
            "ordering": (
                "begin_scoring -> freeze -> measured_imu -> issued_action -> "
                "context_push -> frozen_context_prior -> fault_activation -> "
                "env.step -> cloned_native_imu -> estimator_commit"
            ),
            "last_applied_action_available_to_policy": False,
            "fault_parameters_available_to_policy": False,
            "domain_labels_available_to_policy": False,
        },
        "integrity": {
            "status": status,
            "checks": checks,
            "calibration": (
                None
                if calibration is None
                else {
                    "valid": calibration.valid.detach().cpu().tolist(),
                    "sample_count": calibration.sample_count.detach().cpu().tolist(),
                    "bias_body_mps2": (calibration.bias_body_mps2.detach().cpu().tolist()),
                }
            ),
            "fault_activation_attempts": env.scheduled_fault_activation_attempts,
            "fault_activation_count": env.scheduled_fault_activation_count,
        },
        "metrics": metrics,
        "episodes": episodes,
        "raw_evidence": raw_evidence,
        "demo_replay_trace": {
            "schema_version": "flightguard-causal-imu-demo-replay-trace-v1",
            "registered_lane_index": 0,
            "score_affected": False,
            "fields": list(REPLAY_FIELDS),
            "record_count": len(demo_replay_records),
            "records_sha256": hashlib.sha256(canonical_json_bytes(demo_replay_records)).hexdigest(),
            "records": demo_replay_records,
        },
    }


def _raw_evidence_expected_shapes(
    *,
    contexts: int,
    steps: int,
    include_prior_quarantine: bool = False,
) -> dict[str, tuple[tuple[int, ...], np.dtype[Any] | None]]:
    vector3 = (steps, contexts, 3)
    vector4 = (steps, contexts, 4)
    scalar = (steps, contexts)
    shapes = {
        "schema_version": ((), None),
        "arm": ((), None),
        "checkpoint_seed": ((), np.dtype("int64")),
        "lane_role": ((), None),
        "candidate_id": ((), None),
        "context_seeds": ((contexts,), np.dtype("int64")),
        "step_index": ((steps,), np.dtype("int64")),
        "gate_count": ((), np.dtype("int64")),
        "truth_position": (vector3, np.dtype("float32")),
        "truth_velocity": (vector3, np.dtype("float32")),
        "truth_quaternion": ((steps, contexts, 4), np.dtype("float32")),
        "truth_angular_velocity": (vector3, np.dtype("float32")),
        "estimated_position": (vector3, np.dtype("float32")),
        "estimated_velocity": (vector3, np.dtype("float32")),
        "estimated_quaternion": ((steps, contexts, 4), np.dtype("float32")),
        "estimated_angular_velocity": (vector3, np.dtype("float32")),
        "issued_action": (vector4, np.dtype("float32")),
        "applied_action": (vector4, np.dtype("float32")),
        "active_before_step": (scalar, np.dtype("bool")),
        "terminal": (scalar, np.dtype("bool")),
        "failed": (scalar, np.dtype("bool")),
        "success": (scalar, np.dtype("bool")),
        "gates_passed": (scalar, np.dtype("int64")),
        "gate_index": (scalar, np.dtype("int64")),
        "position_error_squared_m2": (scalar, np.dtype("float32")),
        "scored_position_error_squared_m2": (scalar, np.dtype("float32")),
        "applied_action_saturated": (scalar, np.dtype("bool")),
    }
    if include_prior_quarantine:
        shapes.update(
            {
                "innovation_norm": (scalar, np.dtype("float32")),
                "quarantine_bound": (scalar, np.dtype("float32")),
                "newly_quarantined": (scalar, np.dtype("bool")),
                "prior_quarantined": (scalar, np.dtype("bool")),
                "prior_quarantine_count": (scalar, np.dtype("int64")),
            }
        )
    return shapes


def validate_prior_quarantine_raw_recurrence(
    arrays: Mapping[str, np.ndarray],
    *,
    dropout_start_step: int,
    mechanism_enabled: bool,
    expected_frozen_bound: Sequence[float] | None = None,
) -> None:
    """Fail closed on threshold drift or a quarantine-state recurrence mismatch."""

    if type(mechanism_enabled) is not bool:
        raise TypeError("mechanism_enabled must be bool")
    fields = {
        "innovation_norm",
        "quarantine_bound",
        "newly_quarantined",
        "prior_quarantined",
        "prior_quarantine_count",
    }
    if not fields.issubset(arrays):
        raise RepairEvaluationError("prior quarantine raw evidence is missing")
    innovation = arrays["innovation_norm"]
    bound = arrays["quarantine_bound"]
    newly = arrays["newly_quarantined"]
    quarantined = arrays["prior_quarantined"]
    count = arrays["prior_quarantine_count"]
    active = arrays["active_before_step"]
    if (
        dropout_start_step < 0
        or dropout_start_step >= innovation.shape[0]
        or bool(innovation[:dropout_start_step].any())
        or bool(bound[:dropout_start_step].any())
        or bool(newly[:dropout_start_step].any())
        or bool(quarantined[:dropout_start_step].any())
        or bool(count[:dropout_start_step].any())
    ):
        raise RepairEvaluationError("prior quarantine pre-freeze evidence is nonzero")
    if not mechanism_enabled:
        if expected_frozen_bound is not None:
            raise RepairEvaluationError("disabled prior quarantine carries a frozen bound")
        if any(bool(arrays[name].any()) for name in fields):
            raise RepairEvaluationError("disabled prior quarantine emitted nonzero evidence")
        return
    frozen_bound = bound[dropout_start_step]
    if expected_frozen_bound is not None and not np.array_equal(
        frozen_bound,
        np.asarray(expected_frozen_bound, dtype=np.float32),
    ):
        raise RepairEvaluationError(
            "raw quarantine bound differs from frozen R5 residual quantile"
        )
    if not np.array_equal(
        bound[dropout_start_step:],
        np.broadcast_to(frozen_bound, bound[dropout_start_step:].shape),
    ):
        raise RepairEvaluationError("prior quarantine threshold changed after freeze")
    previous = np.zeros(innovation.shape[1], dtype=np.bool_)
    for step in range(dropout_start_step, innovation.shape[0]):
        expected_new = active[step] & ~previous & (innovation[step] > bound[step])
        expected_state = previous | expected_new
        expected_count = expected_state.astype(np.int64)
        if not np.array_equal(newly[step], expected_new) or not np.array_equal(
            quarantined[step],
            expected_state,
        ) or not np.array_equal(count[step], expected_count):
            raise RepairEvaluationError("prior quarantine state recurrence mismatch")
        previous = expected_state


def _assert_json_numbers_close(
    actual: Any,
    expected: Any,
    *,
    name: str,
) -> None:
    if isinstance(expected, dict):
        if not isinstance(actual, dict) or set(actual) != set(expected):
            raise RepairEvaluationError(f"{name} field set mismatch")
        for key in expected:
            _assert_json_numbers_close(
                actual[key],
                expected[key],
                name=f"{name}.{key}",
            )
        return
    if isinstance(expected, list):
        if not isinstance(actual, list) or len(actual) != len(expected):
            raise RepairEvaluationError(f"{name} list shape mismatch")
        for index, (actual_item, expected_item) in enumerate(zip(actual, expected, strict=True)):
            _assert_json_numbers_close(
                actual_item,
                expected_item,
                name=f"{name}[{index}]",
            )
        return
    if isinstance(expected, bool) or expected is None or isinstance(expected, str):
        if actual != expected or type(actual) is not type(expected):
            raise RepairEvaluationError(f"{name} scalar mismatch")
        return
    if isinstance(expected, int):
        if type(actual) is not int or actual != expected:
            raise RepairEvaluationError(f"{name} integer mismatch")
        return
    if (
        type(actual) not in {int, float}
        or not math.isfinite(float(actual))
        or not math.isclose(
            float(actual),
            float(expected),
            rel_tol=2.0e-5,
            abs_tol=2.0e-6,
        )
    ):
        raise RepairEvaluationError(f"{name} numeric mismatch")


def recompute_raw_evidence_metrics(
    arrays: Mapping[str, np.ndarray],
    *,
    dropout_start_step: int,
    prior_quarantine_enabled: bool | None = None,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Recompute every score-bearing pass field from step-level evidence."""

    active = arrays["active_before_step"]
    terminal = arrays["terminal"]
    failed = arrays["failed"]
    success = arrays["success"]
    gates_passed = arrays["gates_passed"]
    contexts = active.shape[1]
    steps = active.shape[0]
    dropout_steps = steps - dropout_start_step
    if dropout_steps <= 0:
        raise RepairEvaluationError("raw evidence dropout window is empty")
    quarantine_fields_present = set(PRIOR_QUARANTINE_RAW_EVIDENCE_FIELDS) == set(arrays)
    if prior_quarantine_enabled is not None:
        if not quarantine_fields_present:
            raise RepairEvaluationError("prior quarantine audit was requested without raw fields")
        validate_prior_quarantine_raw_recurrence(
            arrays,
            dropout_start_step=dropout_start_step,
            mechanism_enabled=prior_quarantine_enabled,
        )
    elif quarantine_fields_present:
        raise RepairEvaluationError("prior quarantine raw evidence requires explicit mechanism state")
    if (
        not bool(active[0].all())
        or not np.array_equal(active[1:], ~terminal[:-1])
        or not np.array_equal(terminal, np.logical_or.accumulate(terminal, axis=0))
        or not np.array_equal(failed, np.logical_or.accumulate(failed, axis=0))
        or not np.array_equal(success, np.logical_or.accumulate(success, axis=0))
        or bool(np.logical_and(success, failed).any())
        or not np.array_equal(terminal, np.logical_or(success, failed))
        or not np.array_equal(failed[-1], terminal[-1] & ~success[-1])
        or bool((gates_passed < 0).any())
        or bool((gates_passed > int(arrays["gate_count"])).any())
        or bool((np.diff(gates_passed, axis=0) < 0).any())
        or bool(arrays["issued_action"][~active].any())
    ):
        raise RepairEvaluationError("raw evidence episode state transition mismatch")

    position_delta = arrays["estimated_position"].astype(np.float32, copy=False) - arrays[
        "truth_position"
    ].astype(np.float32, copy=False)
    recomputed_position_squared = np.sum(
        position_delta * position_delta,
        axis=2,
        dtype=np.float32,
    )
    if not np.allclose(
        arrays["position_error_squared_m2"],
        recomputed_position_squared,
        rtol=2.0e-5,
        atol=2.0e-6,
    ):
        raise RepairEvaluationError("raw evidence position error mismatch")
    expected_saturated = active & (
        np.abs(arrays["applied_action"]) >= np.float32(1.0 - 1.0e-6)
    ).any(axis=2)
    if not np.array_equal(
        arrays["applied_action_saturated"],
        expected_saturated,
    ):
        raise RepairEvaluationError("raw evidence saturation mask mismatch")

    expected_scored = np.zeros_like(recomputed_position_squared)
    carried_endpoint_squared = np.zeros(contexts, dtype=np.float32)
    for step in range(dropout_start_step, steps):
        carried_endpoint_squared = np.where(
            active[step],
            recomputed_position_squared[step],
            carried_endpoint_squared,
        ).astype(np.float32, copy=False)
        expected_scored[step] = carried_endpoint_squared
    if not np.allclose(
        arrays["scored_position_error_squared_m2"],
        expected_scored,
        rtol=2.0e-5,
        atol=2.0e-6,
    ):
        raise RepairEvaluationError("raw evidence scored error recurrence mismatch")

    success_final = success[-1]
    terminal_final = terminal[-1]
    failed_final = failed[-1]
    gates_final = gates_passed[-1]
    endpoint = np.sqrt(carried_endpoint_squared, dtype=np.float32)
    dropout_error_sum = float(
        np.sum(
            expected_scored[dropout_start_step:],
            dtype=np.float64,
        )
    )
    active_dropout = active[dropout_start_step:]
    saturated_dropout = expected_saturated[dropout_start_step:]
    active_counts = active_dropout.sum(axis=0, dtype=np.int64)
    saturation_counts = saturated_dropout.sum(axis=0, dtype=np.int64)
    saturation = saturation_counts.astype(np.float64) / np.maximum(
        active_counts,
        1,
    )
    terminal_steps: list[int | None] = []
    for context_index in range(contexts):
        terminal_indices = np.flatnonzero(terminal[:, context_index])
        terminal_steps.append(int(terminal_indices[0]) + 1 if terminal_indices.size else None)
    context_seeds = arrays["context_seeds"].tolist()
    episodes = [
        {
            "context_index": index,
            "context_seed": int(context_seeds[index]),
            "mission_success": bool(success_final[index]),
            "mission_failure": not bool(success_final[index]),
            "terminal": bool(terminal_final[index]),
            "failed": bool(failed_final[index]),
            "terminal_step": terminal_steps[index],
            "gates_passed": int(gates_final[index]),
            "endpoint_error_m": float(endpoint[index]),
            "applied_action_saturation_fraction": float(saturation[index]),
        }
        for index in range(contexts)
    ]
    endpoint_tensor = torch.from_numpy(endpoint.astype(np.float64, copy=False))
    gate_count = int(arrays["gate_count"])
    success_count = int(success_final.sum())
    metrics = {
        "episode_count": contexts,
        "mission_success_count": success_count,
        "mission_success_rate": success_count / contexts,
        "mission_failure_count": contexts - success_count,
        "mission_failure_rate": (contexts - success_count) / contexts,
        "terminal_failure_count": int((terminal_final & ~success_final).sum()),
        "trajectory_ate_rmse_m": math.sqrt(dropout_error_sum / (contexts * dropout_steps)),
        "dropout_squared_error_sum_m2": dropout_error_sum,
        "dropout_error_sample_count": contexts * dropout_steps,
        "endpoint_rmse_m": float(torch.sqrt(endpoint_tensor.square().mean()).item()),
        "endpoint_p95_m": float(torch.quantile(endpoint_tensor, 0.95).item()),
        "endpoint_error_m": [float(value) for value in endpoint],
        "mission_progress_fraction": float(
            gates_final.sum(dtype=np.int64) / (contexts * gate_count)
        ),
        "maximum_applied_action_saturation_fraction": float(saturation.max()),
        "mean_applied_action_saturation_fraction": float(saturation.mean()),
        "per_episode_applied_action_saturation_fraction": [float(value) for value in saturation],
    }
    return metrics, episodes


def load_and_validate_raw_evidence(
    descriptor: Any,
    *,
    protocol: Mapping[str, Any],
    arm: str,
    checkpoint_seed: int,
    lane_role: str,
    candidate_id: str,
    context_seeds: Sequence[int],
    steps: int,
    dropout_start_step: int,
    frozen_residual_quantile_mps2: Sequence[float] | None = None,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Load the protocol-registered archive and return independently recomputed scores."""

    quarantine_protocol_enabled = prior_quarantine_protocol_enabled(protocol["runtime"])
    quarantine_enabled = prior_quarantine_enabled_for_arm(protocol["runtime"], arm)
    expected_raw_schema = (
        PRIOR_QUARANTINE_RAW_EVIDENCE_SCHEMA_VERSION
        if quarantine_protocol_enabled
        else RAW_EVIDENCE_SCHEMA_VERSION
    )
    expected_raw_fields = (
        PRIOR_QUARANTINE_RAW_EVIDENCE_FIELDS
        if quarantine_protocol_enabled
        else RAW_EVIDENCE_FIELDS
    )
    expected_path = registered_raw_evidence_path(
        protocol,
        arm=arm,
        checkpoint_seed=checkpoint_seed,
        lane_role=lane_role,
    )
    output_root = Path(protocol["registered_outputs"]["output_root"]).expanduser().resolve()
    required_descriptor_keys = {
        "schema_version",
        "relative_path",
        "sha256",
        "archive_format",
        "raw_evidence_schema_version",
        "context_count",
        "step_count",
        "context_seeds",
        "arrays",
    }
    if (
        not isinstance(descriptor, dict)
        or set(descriptor) != required_descriptor_keys
        or descriptor.get("schema_version") != RAW_EVIDENCE_DESCRIPTOR_SCHEMA_VERSION
        or descriptor.get("archive_format") != "deterministic-pickle-free-npz-v1"
        or descriptor.get("raw_evidence_schema_version") != expected_raw_schema
        or descriptor.get("context_count") != len(context_seeds)
        or descriptor.get("step_count") != steps
        or descriptor.get("context_seeds") != list(context_seeds)
        or not isinstance(descriptor.get("relative_path"), str)
        or not _is_sha256(descriptor.get("sha256"))
    ):
        raise RepairEvaluationError("raw evidence descriptor mismatch")
    relative_path = Path(descriptor["relative_path"])
    resolved_path = (output_root / relative_path).resolve()
    if (
        relative_path.is_absolute()
        or ".." in relative_path.parts
        or resolved_path != expected_path
        or not resolved_path.is_relative_to(output_root)
        or not resolved_path.is_file()
        or resolved_path.stat().st_size <= 0
        or resolved_path.stat().st_size > 512 * 1024 * 1024
        or sha256_file(resolved_path) != descriptor["sha256"]
    ):
        raise RepairEvaluationError("raw evidence registered path/SHA mismatch")
    expected_members = {f"{name}.npy" for name in expected_raw_fields}
    try:
        with zipfile.ZipFile(resolved_path, mode="r") as archive:
            members = archive.namelist()
            if (
                len(members) != len(expected_members)
                or set(members) != expected_members
                or any(info.file_size > 256 * 1024 * 1024 for info in archive.infolist())
            ):
                raise RepairEvaluationError("raw evidence archive member set mismatch")
        with np.load(resolved_path, allow_pickle=False) as archive:
            if set(archive.files) != set(expected_raw_fields):
                raise RepairEvaluationError("raw evidence array field set mismatch")
            arrays = {name: np.array(archive[name], copy=True) for name in expected_raw_fields}
    except (OSError, ValueError, zipfile.BadZipFile) as error:
        raise RepairEvaluationError("raw evidence archive is unreadable") from error

    expected_shapes = _raw_evidence_expected_shapes(
        contexts=len(context_seeds),
        steps=steps,
        include_prior_quarantine=quarantine_protocol_enabled,
    )
    for name, (shape, dtype) in expected_shapes.items():
        value = arrays[name]
        if value.shape != shape or (dtype is not None and value.dtype != dtype):
            raise RepairEvaluationError(f"raw evidence {name} dtype/shape mismatch")
        if value.dtype.kind in {"f", "c"} and not bool(np.isfinite(value).all()):
            raise RepairEvaluationError(f"raw evidence {name} contains non-finite values")
    if descriptor.get("arrays") != _array_manifest(arrays):
        raise RepairEvaluationError("raw evidence array manifest mismatch")
    if (
        arrays["schema_version"].dtype.kind != "U"
        or arrays["schema_version"].item() != expected_raw_schema
        or arrays["arm"].dtype.kind != "U"
        or arrays["arm"].item() != arm
        or int(arrays["checkpoint_seed"]) != checkpoint_seed
        or arrays["lane_role"].dtype.kind != "U"
        or arrays["lane_role"].item() != lane_role
        or arrays["candidate_id"].dtype.kind != "U"
        or arrays["candidate_id"].item() != candidate_id
        or not np.array_equal(
            arrays["context_seeds"],
            np.asarray(context_seeds, dtype=np.int64),
        )
        or not np.array_equal(arrays["step_index"], np.arange(steps, dtype=np.int64))
        or int(arrays["gate_count"]) <= 0
    ):
        raise RepairEvaluationError("raw evidence identity mismatch")
    if quarantine_enabled:
        expected_bound = np.asarray(frozen_residual_quantile_mps2, dtype=np.float32)
        if expected_bound.shape != (len(context_seeds),) or not np.array_equal(
            arrays["quarantine_bound"][dropout_start_step],
            expected_bound,
        ):
            raise RepairEvaluationError(
                "raw quarantine bound differs from frozen R5 residual quantile"
            )
    elif frozen_residual_quantile_mps2 is not None:
        raise RepairEvaluationError("disabled arm carries a frozen quarantine bound")
    return recompute_raw_evidence_metrics(
        arrays,
        dropout_start_step=dropout_start_step,
        prior_quarantine_enabled=(
            quarantine_enabled if quarantine_protocol_enabled else None
        ),
    )


def aggregate_pass_metrics(passes: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    episodes = [
        episode
        for payload in passes
        for episode in payload.get("episodes", [])
        if isinstance(episode, dict)
    ]
    count = len(episodes)
    if count == 0:
        raise RepairEvaluationError("cannot aggregate zero episodes")
    success_count = sum(bool(episode.get("mission_success")) for episode in episodes)
    squared_error_sum = sum(
        float(payload["metrics"]["dropout_squared_error_sum_m2"]) for payload in passes
    )
    error_sample_count = sum(
        int(payload["metrics"]["dropout_error_sample_count"]) for payload in passes
    )
    endpoint = torch.tensor(
        [float(episode["endpoint_error_m"]) for episode in episodes],
        dtype=torch.float64,
    )
    saturation = [float(episode["applied_action_saturation_fraction"]) for episode in episodes]
    return {
        "episode_count": count,
        "mission_success_count": success_count,
        "mission_success_rate": success_count / count,
        "mission_failure_count": count - success_count,
        "mission_failure_rate": (count - success_count) / count,
        "trajectory_ate_rmse_m": math.sqrt(squared_error_sum / error_sample_count),
        "endpoint_rmse_m": float(torch.sqrt(endpoint.square().mean()).item()),
        "endpoint_p95_m": float(torch.quantile(endpoint, 0.95).item()),
        "maximum_applied_action_saturation_fraction": max(saturation),
        "mean_applied_action_saturation_fraction": sum(saturation) / count,
    }


def relative_id_success_degradation_fraction(
    *,
    baseline_success_rate: float,
    patch_success_rate: float,
) -> float | None:
    """Return relative nominal degradation, failing closed at zero baseline."""

    baseline = float(baseline_success_rate)
    patch = float(patch_success_rate)
    if (
        not math.isfinite(baseline)
        or not math.isfinite(patch)
        or baseline < 0.0
        or baseline > 1.0
        or patch < 0.0
        or patch > 1.0
    ):
        raise RepairEvaluationError("nominal success rates must be finite probabilities")
    if baseline == 0.0:
        return None
    return (baseline - patch) / baseline


def validate_demo_replay(
    replay: Any,
    *,
    steps: int,
    dropout_start_step: int,
) -> None:
    """Fail closed unless the registered lane has a complete hash-bound trace."""

    required_keys = {
        "schema_version",
        "registered_lane_index",
        "score_affected",
        "fields",
        "record_count",
        "records_sha256",
        "records",
    }
    if not isinstance(replay, dict) or set(replay) != required_keys:
        raise RepairEvaluationError("demo replay field set mismatch")
    records = replay.get("records")
    if (
        replay.get("schema_version") != "flightguard-causal-imu-demo-replay-trace-v1"
        or replay.get("registered_lane_index") != 0
        or replay.get("score_affected") is not False
        or replay.get("fields") != list(REPLAY_FIELDS)
        or replay.get("record_count") != steps
        or not isinstance(records, list)
        or len(records) != steps
        or not _is_sha256(replay.get("records_sha256"))
        or replay["records_sha256"] != hashlib.sha256(canonical_json_bytes(records)).hexdigest()
    ):
        raise RepairEvaluationError("demo replay identity/hash mismatch")

    vector_widths = {
        "truth_position": 3,
        "truth_quaternion": 4,
        "estimated_position": 3,
        "issued_action": 4,
        "applied_action": 4,
    }
    for step, record in enumerate(records):
        if not isinstance(record, dict) or set(record) != set(REPLAY_FIELDS):
            raise RepairEvaluationError("demo replay record field set mismatch")
        if (
            record.get("step") != step
            or type(record.get("fault_onset")) is not bool
            or record["fault_onset"] is not (step == dropout_start_step)
            or type(record.get("terminal")) is not bool
            or type(record.get("gate_index")) is not int
            or record["gate_index"] < 0
        ):
            raise RepairEvaluationError("demo replay scalar semantics mismatch")
        for field, width in vector_widths.items():
            value = record.get(field)
            if (
                not isinstance(value, list)
                or len(value) != width
                or any(
                    type(component) not in {int, float} or not math.isfinite(float(component))
                    for component in value
                )
            ):
                raise RepairEvaluationError(f"demo replay {field} is invalid")


def validate_pass_evidence(
    payload: Mapping[str, Any],
    *,
    protocol: Mapping[str, Any],
    arm: str,
    checkpoint_seed: int,
    lane_role: str,
    contract: Mapping[str, Any],
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Recompute every pass-level eligibility condition needed by the merge."""

    steps = int(contract["runtime"]["steps"])
    dropout_steps = int(contract["runtime"]["dropout_steps"])
    contexts = len(contract["rng"]["checkpoint_context_seed_banks"][str(checkpoint_seed)])
    checkpoint = next(
        record
        for record in contract["selection"]["checkpoints"]
        if record["seed"] == checkpoint_seed
    )
    expected_selection = {
        "path": contract["selection"]["path"],
        "sha256": contract["selection"]["sha256"],
        "discovery_seal_sha256": contract["selection"]["discovery_seal"]["sha256"],
        "hidden_summary_sha256": contract["selection"]["hidden_summary"]["sha256"],
        "hidden_evidence_sha256": contract["selection"]["hidden_evidence_sha256"],
    }
    runtime = payload.get("runtime")
    execution = payload.get("execution")
    sensor = payload.get("sensor")
    causal = payload.get("causal_integrity")
    integrity = payload.get("integrity")
    metrics = payload.get("metrics")
    episodes = payload.get("episodes")
    if (
        payload.get("selection") != expected_selection
        or payload.get("checkpoint") != checkpoint
        or not isinstance(runtime, dict)
        or any(runtime.get(key) != value for key, value in contract["runtime"].items())
        or runtime.get("contexts") != contexts
        or runtime.get("transitions") != contexts * steps
        or not isinstance(execution, dict)
        or str(execution.get("backend", "")).lower()
        not in {"3", "amdgpu", "gs.amdgpu", "genesis.amdgpu"}
        or not isinstance(execution.get("device"), str)
        or not execution["device"]
        or not isinstance(execution.get("gpu_name"), str)
        or not execution["gpu_name"]
        or execution.get("visible_gpu_count") != 1
        or execution.get("maximum_concurrent_gpu_processes") != 1
        or not execution.get("torch_hip")
        or not isinstance(sensor, dict)
        or not isinstance(causal, dict)
        or not isinstance(integrity, dict)
        or not isinstance(metrics, dict)
        or not isinstance(episodes, list)
    ):
        raise RepairEvaluationError("repair pass runtime/evidence sections mismatch")
    genesis_tree = execution.get("genesis_source_tree")
    runtime_asset = Path(str(execution.get("runtime_race_asset"))).expanduser().resolve()
    if (
        not isinstance(genesis_tree, dict)
        or genesis_tree.get("sha256")
        != contract["execution_environment"]["genesis_source_tree_sha256"]
        or execution.get("genesis_version") != contract["execution_environment"]["genesis_version"]
        or type(genesis_tree.get("file_count")) is not int
        or genesis_tree["file_count"] <= 0
        or type(genesis_tree.get("total_bytes")) is not int
        or genesis_tree["total_bytes"] <= 0
        or not runtime_asset.is_file()
        or not _is_sha256(execution.get("runtime_race_asset_sha256"))
        or sha256_file(runtime_asset) != execution["runtime_race_asset_sha256"]
        or execution.get("runtime_race_asset_sha256")
        != contract["execution_environment"]["corrected_racer_urdf_sha256"]
        or execution.get("implementation_files_sha256")
        != contract["implementation_contract"]["files"]
        or type(execution.get("elapsed_s")) not in {int, float}
        or not math.isfinite(float(execution["elapsed_s"]))
        or float(execution["elapsed_s"]) <= 0.0
        or type(execution.get("transitions_per_s")) not in {int, float}
        or not math.isfinite(float(execution["transitions_per_s"]))
        or float(execution["transitions_per_s"]) <= 0.0
    ):
        raise RepairEvaluationError("repair pass execution binding mismatch")
    expected_sensor_access = arm != HardeningArm.ACTION_ONLY.value
    bank_step_evidence = sensor.get("bank_step_index_evidence")
    schedule = sensor.get("native_sensor_schedule")
    intervention = sensor.get("measurement_error_intervention_gates")
    expected_r5_measurement_bank = build_r5_context_measurement_bank(
        context_seeds=contract["rng"]["checkpoint_context_seed_banks"][str(checkpoint_seed)],
        steps=steps,
        runtime=contract["runtime"],
    )
    if (
        sensor.get("native_profile_sha256") != NOISE_FREE_API_FRAME_PROFILE.canonical_sha256()
        or sensor.get("formal_error_profile_sha256")
        != FORMAL_REALISTIC_SENSOR_PROFILE.canonical_sha256()
        or not _is_sha256(sensor.get("formal_error_bank_sha256"))
        or not _is_sha256(sensor.get("formal_error_bank_raw_bytes_sha256"))
        or sensor.get("formal_error_bank_shape") != [steps, contexts, 3]
        or sensor.get("formal_error_bank_dtype") != "torch.float32"
        or sensor.get("formal_error_bank_device") != "cpu"
        or not _is_sha256(sensor.get("r5_context_measurement_bank_sha256"))
        or sensor.get("r5_context_measurement_bank_sha256")
        != expected_r5_measurement_bank["sha256"]
        or not _is_sha256(sensor.get("r5_context_measurement_bank_raw_bytes_sha256"))
        or sensor.get("r5_context_measurement_bank_raw_bytes_sha256")
        != expected_r5_measurement_bank["raw_bytes_sha256"]
        or sensor.get("r5_context_measurement_bank_shape") != [steps, contexts, 3]
        or sensor.get("r5_context_measurement_bank_dtype") != "torch.float32"
        or sensor.get("r5_context_measurement_bank_device") != "cpu"
        or sensor.get("r5_context_measurement_source_function_sha256")
        != R5_CONTEXT_NOISE_SOURCE_SHA256
        or sensor.get("registered_noise_seed")
        != registered_sensor_seed(
            contract["sensor"],
            checkpoint_seed=checkpoint_seed,
        )
        or sensor.get("post_read_error_bank_generator_code_sha256")
        != contract["sensor"]["post_read_error_bank_generator_code_sha256"]
        or sensor.get("matching_strategy") != contract["sensor"]["matching_strategy"]
        or sensor.get("genesis_native_noise_matching_claimed") is not False
        or sensor.get("policy_consumes_native_plus_bank") is not expected_sensor_access
        or sensor.get("action_only_sensor_attach_read_schedule_preserved_but_policy_zero_access")
        is not True
        or not isinstance(bank_step_evidence, dict)
        or bank_step_evidence
        != {
            "first_index": 0,
            "last_index": steps - 1,
            "consumed_count": steps,
            "exactly_once_in_monotonic_loop": True,
        }
        or not isinstance(schedule, dict)
        or schedule
        != {
            "native_sensor_attached_once_prebuild": True,
            "native_sensor_read_count": steps,
            "post_read_error_bank_application_count": steps,
            "policy_sensor_commit_count": dropout_steps if expected_sensor_access else 0,
        }
        or not isinstance(intervention, dict)
        or intervention.get("status") != "PASS"
        or intervention.get("bank_generator_code_sha256")
        != contract["sensor"]["post_read_error_bank_generator_code_sha256"]
        or not isinstance(intervention.get("checks"), dict)
        or not intervention["checks"]
        or not all(value is True for value in intervention["checks"].values())
    ):
        raise RepairEvaluationError("sensor bank/access evidence mismatch")

    trace = causal.get("pre_dropout_raw_bit_trace")
    baseline = causal.get("frozen_r5_same_process_shadow")
    structural_parity = causal.get("r5_baseline_structural_parity")
    context_summary = causal.get("frozen_r5_context")
    calibration_alignment = causal.get("native_calibration_alignment")
    quarantine_protocol_enabled = prior_quarantine_protocol_enabled(contract["runtime"])
    quarantine_enabled = prior_quarantine_enabled_for_arm(contract["runtime"], arm)
    quarantine_evidence = causal.get("prior_quarantine")
    if (
        not isinstance(trace, dict)
        or trace.get("steps") != int(contract["runtime"]["dropout_start_step"]) + 1
        or trace.get("lanes") != contexts
        or not _is_sha256(trace.get("sha256"))
        or not isinstance(trace.get("lane_sha256"), list)
        or len(trace["lane_sha256"]) != contexts
        or not all(_is_sha256(value) for value in trace["lane_sha256"])
        or causal.get("ordering")
        != (
            "begin_scoring -> freeze -> measured_imu -> issued_action -> "
            "context_push -> frozen_context_prior -> fault_activation -> "
            "env.step -> cloned_native_imu -> estimator_commit"
        )
        or causal.get("last_applied_action_available_to_policy") is not False
        or causal.get("fault_parameters_available_to_policy") is not False
        or causal.get("domain_labels_available_to_policy") is not False
        or not isinstance(baseline, dict)
        or not isinstance(structural_parity, dict)
        or structural_parity.get("status") != "PASS"
        or not isinstance(structural_parity.get("checks"), dict)
        or not structural_parity["checks"]
        or not all(value is True for value in structural_parity["checks"].values())
        or structural_parity.get("reference_code")
        != contract["r5_baseline"]["reference_helper_code"]
        or not isinstance(context_summary, dict)
        or context_summary.get("type") != "frozen_affine_delay"
        or context_summary.get("frozen") is not True
        or context_summary.get("batch_size") != contexts
        or context_summary.get("valid_count") != contexts
        or context_summary.get("invalid_count") != 0
        or context_summary.get("selected_valid") != [True] * contexts
        or context_summary.get("post_freeze_update_attempts") != 0
        or context_summary.get("uses_last_applied_action") is not False
        or causal.get("all_contexts_qualified_at_freeze") is not True
        or not isinstance(calibration_alignment, dict)
        or calibration_alignment
        != {
            "sensor_sample_time": "post_step_t_plus_1",
            "quaternion_time": "post_step_t_plus_1",
            "velocity_transition": "pre_step_t_to_post_step_t_plus_1",
            "next_visible_quaternion_raw_bit_equivalence_required": True,
            "compared_values": (int(contract["runtime"]["dropout_start_step"]) * contexts * 4),
            "raw_bit_mismatched_values": 0,
            "exact": True,
        }
    ):
        raise RepairEvaluationError("causal-integrity evidence mismatch")
    if quarantine_protocol_enabled:
        frozen_quantile = context_summary.get("selected_residual_quantile_mps2")
        expected_frozen_quantile = frozen_quantile if quarantine_enabled else None
        if (
            not isinstance(quarantine_evidence, dict)
            or quarantine_evidence
            != {
                "protocol_enabled": True,
                "mechanism_enabled_for_arm": quarantine_enabled,
                "source": "frozen_r5_context.selected_residual_quantile_mps2",
                "frozen_residual_quantile_mps2": expected_frozen_quantile,
                "post_freeze_quarantine_bound_update_attempts": 0,
                "threshold_immutable": True,
                "raw_state_recurrence_pass": True,
            }
            or not isinstance(frozen_quantile, list)
            or len(frozen_quantile) != contexts
            or any(
                type(value) not in {int, float}
                or not math.isfinite(float(value))
                or float(value) < 0.0
                for value in frozen_quantile
            )
        ):
            raise RepairEvaluationError("prior quarantine causal-integrity evidence mismatch")
    elif quarantine_evidence is not None:
        raise RepairEvaluationError("legacy pass carries unauthorized prior quarantine evidence")
    if arm == HardeningArm.ACTION_ONLY.value:
        action_parity = baseline.get("action")
        prior_parity = baseline.get("prior")
        state_parity = baseline.get("state")
        context_parity = baseline.get("context_state")
        at_freeze = context_parity.get("at_freeze") if isinstance(context_parity, dict) else None
        if (
            baseline.get("applicable") is not True
            or baseline.get("exact") is not True
            or not all(
                isinstance(section, dict)
                for section in (
                    action_parity,
                    prior_parity,
                    state_parity,
                    context_parity,
                )
            )
            or any(
                type(section.get("compared_values")) is not int
                or section["compared_values"] <= 0
                or section.get("raw_bit_mismatched_values") != 0
                for section in (action_parity, prior_parity, state_parity)
            )
            or type(context_parity.get("compared_tensors")) is not int
            or context_parity["compared_tensors"] <= 0
            or context_parity.get("mismatched_tensors") != 0
            or not isinstance(at_freeze, dict)
            or at_freeze.get("exact") is not True
            or at_freeze.get("mismatched_tensor_names") != []
        ):
            raise RepairEvaluationError("ActionOnly exact frozen R5 shadow parity is unproven")
    elif baseline.get("applicable") is not False or baseline.get("exact") is not True:
        raise RepairEvaluationError("non-ActionOnly R5 shadow applicability mismatch")

    checks = integrity.get("checks")
    expected_integrity_checks = set(PASS_INTEGRITY_CHECKS)
    if quarantine_protocol_enabled:
        expected_integrity_checks.update(PRIOR_QUARANTINE_PASS_INTEGRITY_CHECKS)
    if (
        integrity.get("status") != "PASS"
        or not isinstance(checks, dict)
        or set(checks) != expected_integrity_checks
        or not all(value is True for value in checks.values())
    ):
        raise RepairEvaluationError("pass integrity checks are not all true")
    expected_context_seeds = contract["rng"]["checkpoint_context_seed_banks"][str(checkpoint_seed)]
    recomputed_metrics, recomputed_episodes = load_and_validate_raw_evidence(
        payload.get("raw_evidence"),
        protocol=protocol,
        arm=arm,
        checkpoint_seed=checkpoint_seed,
        lane_role=lane_role,
        candidate_id=contract["selection"]["candidate"]["candidate_id"],
        context_seeds=expected_context_seeds,
        steps=steps,
        dropout_start_step=int(contract["runtime"]["dropout_start_step"]),
        frozen_residual_quantile_mps2=(
            context_summary["selected_residual_quantile_mps2"]
            if quarantine_enabled
            else None
        ),
    )
    _assert_json_numbers_close(
        metrics,
        recomputed_metrics,
        name="raw-evidence-bound metrics",
    )
    _assert_json_numbers_close(
        episodes,
        recomputed_episodes,
        name="raw-evidence-bound episodes",
    )
    validate_demo_replay(
        payload.get("demo_replay_trace"),
        steps=steps,
        dropout_start_step=int(contract["runtime"]["dropout_start_step"]),
    )
    return recomputed_metrics, recomputed_episodes


def merge_passes(
    *,
    protocol_path: Path,
    output_path: Path,
) -> dict[str, Any]:
    protocol_path = protocol_path.expanduser().resolve()
    output_path = output_path.expanduser().resolve()
    if output_path.exists():
        raise FileExistsError(f"refusing to overwrite repair summary: {output_path}")
    protocol = load_strict_json(protocol_path)
    contract = validate_protocol(protocol, protocol_path=protocol_path)
    verify_implementation_contract(
        protocol,
        project_root=Path(__file__).resolve().parent.parent,
    )
    if output_path != registered_summary_path(protocol):
        raise RepairEvaluationError("repair summary differs from registered slot")
    passes: dict[str, dict[int, dict[str, dict[str, Any]]]] = {arm: {} for arm in ARMS}
    pass_manifest = []
    for arm in ARMS:
        for checkpoint_seed in contract["checkpoint_seeds"]:
            passes[arm][checkpoint_seed] = {}
            for role in LANE_ROLES:
                path = registered_pass_path(
                    protocol,
                    arm=arm,
                    checkpoint_seed=checkpoint_seed,
                    lane_role=role,
                )
                if not path.is_file():
                    raise RepairEvaluationError(f"repair pass is missing: {path}")
                payload = load_strict_json(path)
                expected_identity = {
                    "arm": arm,
                    "checkpoint_seed": checkpoint_seed,
                    "lane_role": role,
                    "candidate_id": contract["selection"]["candidate"]["candidate_id"],
                    "context_seeds": contract["rng"]["checkpoint_context_seed_banks"][
                        str(checkpoint_seed)
                    ],
                    "genesis_seed": contract["rng"]["checkpoint_genesis_seeds"][
                        str(checkpoint_seed)
                    ],
                }
                if (
                    payload.get("schema_version") != SCHEMA_VERSION
                    or payload.get("status") != "PASS"
                    or payload.get("simulation_only") is not True
                    or payload.get("repair_claim_eligible") is not False
                    or payload.get("protocol", {}).get("sha256") != contract["sha256"]
                    or payload.get("identity") != expected_identity
                    or payload.get("selection", {}).get("sha256") != contract["selection"]["sha256"]
                ):
                    raise RepairEvaluationError("repair pass identity/integrity mismatch")
                recomputed_metrics, recomputed_episodes = validate_pass_evidence(
                    payload,
                    protocol=protocol,
                    arm=arm,
                    checkpoint_seed=checkpoint_seed,
                    lane_role=role,
                    contract=contract,
                )
                verified_payload = dict(payload)
                verified_payload["metrics"] = recomputed_metrics
                verified_payload["episodes"] = recomputed_episodes
                passes[arm][checkpoint_seed][role] = verified_payload
                pass_manifest.append(
                    {
                        "arm": arm,
                        "checkpoint_seed": checkpoint_seed,
                        "lane_role": role,
                        "path": str(path),
                        "sha256": sha256_file(path),
                        "raw_evidence_path": str(
                            registered_raw_evidence_path(
                                protocol,
                                arm=arm,
                                checkpoint_seed=checkpoint_seed,
                                lane_role=role,
                            )
                        ),
                        "raw_evidence_sha256": payload["raw_evidence"]["sha256"],
                    }
                )

    trace_match_by_checkpoint = {}
    sensor_bank_match_by_checkpoint = {}
    sensor_bank_raw_bytes_match_by_checkpoint = {}
    r5_measurement_bank_match_by_checkpoint = {}
    r5_measurement_bank_raw_bytes_match_by_checkpoint = {}
    for checkpoint_seed in contract["checkpoint_seeds"]:
        checkpoint_payloads = [
            passes[arm][checkpoint_seed][role] for arm in ARMS for role in LANE_ROLES
        ]
        trace_hashes = {
            payload["causal_integrity"]["pre_dropout_raw_bit_trace"]["sha256"]
            for payload in checkpoint_payloads
        }
        bank_hashes = {
            payload["sensor"]["formal_error_bank_sha256"] for payload in checkpoint_payloads
        }
        raw_bank_hashes = {
            payload["sensor"]["formal_error_bank_raw_bytes_sha256"]
            for payload in checkpoint_payloads
        }
        r5_bank_hashes = {
            payload["sensor"]["r5_context_measurement_bank_sha256"]
            for payload in checkpoint_payloads
        }
        r5_raw_bank_hashes = {
            payload["sensor"]["r5_context_measurement_bank_raw_bytes_sha256"]
            for payload in checkpoint_payloads
        }
        trace_match_by_checkpoint[str(checkpoint_seed)] = len(trace_hashes) == 1
        sensor_bank_match_by_checkpoint[str(checkpoint_seed)] = len(bank_hashes) == 1
        sensor_bank_raw_bytes_match_by_checkpoint[str(checkpoint_seed)] = len(raw_bank_hashes) == 1
        r5_measurement_bank_match_by_checkpoint[str(checkpoint_seed)] = len(r5_bank_hashes) == 1
        r5_measurement_bank_raw_bytes_match_by_checkpoint[str(checkpoint_seed)] = (
            len(r5_raw_bank_hashes) == 1
        )

    aggregate = {
        arm: {
            role: aggregate_pass_metrics(
                [
                    passes[arm][checkpoint_seed][role]
                    for checkpoint_seed in contract["checkpoint_seeds"]
                ]
            )
            for role in LANE_ROLES
        }
        for arm in ARMS
    }
    fault = {arm: aggregate[arm]["fault"] for arm in ARMS}
    nominal = {arm: aggregate[arm]["nominal"] for arm in ARMS}
    action_failure = fault["ActionOnly"]["mission_failure_rate"]
    patch_failure = fault["CausalIMUPatch"]["mission_failure_rate"]
    failure_reduction = (
        (action_failure - patch_failure) / action_failure if action_failure > 0.0 else None
    )
    success_improvement_pp = 100.0 * (
        fault["CausalIMUPatch"]["mission_success_rate"]
        - fault["ActionOnly"]["mission_success_rate"]
    )
    id_degradation = relative_id_success_degradation_fraction(
        baseline_success_rate=nominal["ActionOnly"]["mission_success_rate"],
        patch_success_rate=nominal["CausalIMUPatch"]["mission_success_rate"],
    )
    competitors = ("RawStrapdown", "CalibratedStrapdown")
    patch_not_worse = {}
    for competitor in competitors:
        patch_not_worse[competitor] = {
            "mission_success_rate": (
                fault["CausalIMUPatch"]["mission_success_rate"]
                >= fault[competitor]["mission_success_rate"]
            ),
            "mission_failure_rate": (
                fault["CausalIMUPatch"]["mission_failure_rate"]
                <= fault[competitor]["mission_failure_rate"]
            ),
            "trajectory_ate_rmse_m": (
                fault["CausalIMUPatch"]["trajectory_ate_rmse_m"]
                <= fault[competitor]["trajectory_ate_rmse_m"]
            ),
            "endpoint_p95_m": (
                fault["CausalIMUPatch"]["endpoint_p95_m"] <= fault[competitor]["endpoint_p95_m"]
            ),
            "maximum_applied_action_saturation_fraction": (
                fault["CausalIMUPatch"]["maximum_applied_action_saturation_fraction"]
                <= fault[competitor]["maximum_applied_action_saturation_fraction"]
            ),
        }
    acceptance = protocol["acceptance_gates"]
    action_shadow_parity = all(
        passes["ActionOnly"][checkpoint_seed][role]["causal_integrity"][
            "frozen_r5_same_process_shadow"
        ]["exact"]
        and all(
            passes["ActionOnly"][checkpoint_seed][role]["causal_integrity"][
                "frozen_r5_same_process_shadow"
            ][section]["raw_bit_mismatched_values"]
            == 0
            for section in ("action", "prior", "state")
        )
        and passes["ActionOnly"][checkpoint_seed][role]["causal_integrity"][
            "frozen_r5_same_process_shadow"
        ]["context_state"]["mismatched_tensors"]
        == 0
        for checkpoint_seed in contract["checkpoint_seeds"]
        for role in LANE_ROLES
    )
    all_metric_values_finite = all(
        math.isfinite(float(value))
        for arm in ARMS
        for role in LANE_ROLES
        for value in aggregate[arm][role].values()
        if isinstance(value, (int, float))
    )
    checks = {
        "all_24_registered_passes_present_and_pass": len(pass_manifest) == 24,
        "same_candidate_checkpoint_context_genesis_seed_across_arms": True,
        "pre_dropout_raw_bit_trace_exact_per_checkpoint": all(trace_match_by_checkpoint.values()),
        "formal_sensor_error_bank_raw_bit_exact_per_checkpoint": all(
            sensor_bank_match_by_checkpoint.values()
        )
        and all(sensor_bank_raw_bytes_match_by_checkpoint.values()),
        "r5_context_measurement_bank_raw_bit_exact_per_checkpoint": all(
            r5_measurement_bank_match_by_checkpoint.values()
        )
        and all(r5_measurement_bank_raw_bytes_match_by_checkpoint.values()),
        "action_only_exact_frozen_r5_same_process_shadow": (action_shadow_parity),
        "sensor_on_kill_magnitude_pass": all(
            passes[arm][checkpoint_seed][role]["integrity"]["checks"][
                "sensor_on_kill_magnitude_pass"
            ]
            for arm in ARMS
            for checkpoint_seed in contract["checkpoint_seeds"]
            for role in LANE_ROLES
        ),
        "all_outputs_finite": all_metric_values_finite,
        "all_saturation_within_5_percent": all(
            aggregate[arm][role]["maximum_applied_action_saturation_fraction"]
            <= float(acceptance["maximum_applied_action_saturation_fraction"])
            for arm in ARMS
            for role in LANE_ROLES
        ),
        "patch_fresh_repair_success_improvement_at_least_20pp": (
            success_improvement_pp
            >= float(acceptance["minimum_patch_fresh_repair_success_improvement_percentage_points"])
        ),
        "patch_failure_reduction_at_least_50_percent": (
            failure_reduction is not None
            and failure_reduction >= float(acceptance["minimum_patch_failure_reduction_fraction"])
        ),
        "patch_id_nominal_degradation_at_most_10_percent": (
            id_degradation is not None
            and id_degradation
            <= float(acceptance["maximum_patch_id_nominal_success_degradation_fraction"])
        ),
        "patch_not_worse_than_raw_or_calibrated": all(
            all(values.values()) for values in patch_not_worse.values()
        ),
    }
    if prior_quarantine_protocol_enabled(contract["runtime"]):
        checks.update(
            {
                "prior_quarantine_enabled_only_for_patch": all(
                    passes[arm][checkpoint_seed][role]["causal_integrity"][
                        "prior_quarantine"
                    ]["mechanism_enabled_for_arm"]
                    is (arm == HardeningArm.CAUSAL_IMU_PATCH.value)
                    for arm in ARMS
                    for checkpoint_seed in contract["checkpoint_seeds"]
                    for role in LANE_ROLES
                ),
                "prior_quarantine_thresholds_immutable": all(
                    passes[arm][checkpoint_seed][role]["causal_integrity"][
                        "prior_quarantine"
                    ]["post_freeze_quarantine_bound_update_attempts"]
                    == 0
                    for arm in ARMS
                    for checkpoint_seed in contract["checkpoint_seeds"]
                    for role in LANE_ROLES
                ),
                "prior_quarantine_raw_recurrence_all_passes": all(
                    passes[arm][checkpoint_seed][role]["causal_integrity"][
                        "prior_quarantine"
                    ]["raw_state_recurrence_pass"]
                    for arm in ARMS
                    for checkpoint_seed in contract["checkpoint_seeds"]
                    for role in LANE_ROLES
                ),
            }
        )
    status = "PASS" if all(checks.values()) else "FAIL"
    return {
        "schema_version": SUMMARY_SCHEMA_VERSION,
        "status": status,
        "simulation_only": True,
        "repair_claim_eligible": status == "PASS",
        "claim_boundary": protocol["claim_boundary"],
        "protocol": {
            "path": str(protocol_path),
            "sha256": contract["sha256"],
            "version": protocol["protocol_version"],
        },
        "selection": contract["selection"],
        "fixed_budget": protocol["fixed_budget"],
        "pass_manifest": pass_manifest,
        "integrity": {
            "status": status,
            "checks": checks,
            "pre_dropout_trace_match_by_checkpoint": trace_match_by_checkpoint,
            "sensor_error_bank_match_by_checkpoint": (sensor_bank_match_by_checkpoint),
            "sensor_error_bank_raw_bytes_match_by_checkpoint": (
                sensor_bank_raw_bytes_match_by_checkpoint
            ),
            "r5_measurement_bank_match_by_checkpoint": (r5_measurement_bank_match_by_checkpoint),
            "r5_measurement_bank_raw_bytes_match_by_checkpoint": (
                r5_measurement_bank_raw_bytes_match_by_checkpoint
            ),
        },
        "metrics": aggregate,
        "capability_effect": {
            "evaluation_population": "fresh_after_hidden_selection",
            "hidden_outcomes_used_only_for_candidate_selection": True,
            "patch_minus_action_only_success_percentage_points": (success_improvement_pp),
            "patch_vs_action_only_failure_reduction_fraction": failure_reduction,
            "patch_vs_action_only_id_nominal_success_degradation_fraction": (id_degradation),
            "patch_not_worse_than": patch_not_worse,
        },
    }


def write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path = path.expanduser().resolve()
    if path.exists():
        raise FileExistsError(f"refusing to overwrite output: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, allow_nan=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def main() -> None:
    args = parse_args()
    if args.command == "run":
        payload = run_pass(
            protocol_path=args.protocol,
            arm_name=args.arm,
            checkpoint_seed=args.checkpoint_seed,
            lane_role=args.lane_role,
            output_path=args.output,
        )
        write_json(args.output, payload)
        print(
            json.dumps(
                {
                    "event": "causal_imu_repair_pass_complete",
                    "status": payload["status"],
                    "output": str(args.output.expanduser().resolve()),
                },
                sort_keys=True,
            ),
            flush=True,
        )
    else:
        payload = merge_passes(
            protocol_path=args.protocol,
            output_path=args.output,
        )
        write_json(args.output, payload)
        print(
            json.dumps(
                {
                    "event": "causal_imu_repair_merge_complete",
                    "status": payload["status"],
                    "repair_claim_eligible": payload["repair_claim_eligible"],
                    "output": str(args.output.expanduser().resolve()),
                },
                sort_keys=True,
            ),
            flush=True,
        )
    if payload["status"] != "PASS":
        raise SystemExit(2)


if __name__ == "__main__":
    main()
