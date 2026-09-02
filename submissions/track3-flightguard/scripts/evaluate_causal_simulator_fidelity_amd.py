#!/usr/bin/env python3
"""Generate protocol-bound Genesis RACE simulator-fidelity evidence on Radeon."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import stat
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

from flightguard.falsifier import require_registered_output_path

SCHEMA_VERSION = "flightguard-causal-simulator-fidelity-v1"
PROTOCOL_VERSION = "flightguard-causal-falsifier-v1-20260729"
FROZEN_STATUS = "PRE_REGISTERED_AFTER_V3_FAILURE_BEFORE_FIRST_CAUSAL_FALSIFIER_GPU_RUN"
GENESIS_SEED = 66_001
PHYSICS_STEPS = 8
MOTOR_ACTION_PERTURBATION = 0.10
MOTOR_RPM_MULTIPLIER = 1.08
EXPECTED_PROP_OFFSETS = {
    "prop0": (0.0850, 0.0675, 0.0),
    "prop1": (-0.0850, 0.0675, 0.0),
    "prop2": (-0.0850, -0.0675, 0.0),
    "prop3": (0.0850, -0.0675, 0.0),
}
EXPECTED_ROLL_PITCH_SIGNS = {
    "prop0": (1.0, -1.0),
    "prop1": (1.0, 1.0),
    "prop2": (-1.0, 1.0),
    "prop3": (-1.0, -1.0),
}
REQUIRED_IMPLEMENTATION_FILES = frozenset(
    {
        "scripts/evaluate_causal_simulator_fidelity_amd.py",
        "src/flightguard/genesis_env.py",
        "src/flightguard/racer_asset.py",
    }
)
PHYSICS_CHECKS = frozenset(
    {
        "all_numeric_evidence_finite",
        "stock_geometry_matches_audited_bug",
        "corrected_fixed_joint_offsets_exact",
        "corrected_inertial_offsets_zero",
        "nonzero_propeller_moment_arms",
        "genesis_link_offsets_match_corrected_asset",
        "four_isolated_single_motor_responses_present",
        "signed_roll_pitch_mapping_matches",
        "minimum_signed_roll_pitch_response_met",
        "balanced_hover_roll_pitch_norm_within_limit",
        "stock_and_corrected_asset_hashes_recorded_and_distinct",
    }
)


class FidelityError(RuntimeError):
    """Raised when fidelity evidence cannot be produced safely."""


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=("Run the frozen FlightGuard RACE moment-arm fidelity gate on one Radeon GPU.")
    )
    parser.add_argument("--protocol", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args(argv)


def reject_nonfinite(value: str) -> None:
    raise FidelityError(f"non-finite JSON constant is forbidden: {value}")


def reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    payload: dict[str, Any] = {}
    for key, value in pairs:
        if key in payload:
            raise FidelityError(f"duplicate JSON key is forbidden: {key}")
        payload[key] = value
    return payload


def load_strict_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(
            path.read_text(encoding="utf-8"),
            parse_constant=reject_nonfinite,
            object_pairs_hook=reject_duplicate_keys,
        )
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise FidelityError(f"cannot read strict JSON {path}: {error}") from error
    if not isinstance(payload, dict):
        raise FidelityError(f"JSON root must be an object: {path}")
    return payload


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def sha256_source_tree(root: Path) -> dict[str, Any]:
    root = root.resolve()
    files: list[tuple[str, Path]] = []
    for path in root.rglob("*"):
        relative = path.relative_to(root)
        if any(part in {".git", "__pycache__", ".pytest_cache"} for part in relative.parts):
            continue
        if path.is_file() and path.suffix not in {".pyc", ".pyo"}:
            files.append((relative.as_posix(), path))
    digest = hashlib.sha256()
    total_bytes = 0
    for relative_name, path in sorted(files):
        digest.update(relative_name.encode())
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


def verify_implementation_contract(
    protocol: dict[str, Any],
    *,
    project_root: Path,
) -> dict[str, str]:
    contract = protocol.get("implementation_contract")
    if not isinstance(contract, dict):
        raise FidelityError("protocol implementation contract is missing")
    files = contract.get("files")
    if not isinstance(files, dict) or not files:
        raise FidelityError("protocol implementation file hashes are not frozen")
    missing = REQUIRED_IMPLEMENTATION_FILES - set(files)
    if missing:
        raise FidelityError(f"fidelity implementation files are not frozen: {sorted(missing)}")
    project_root = project_root.resolve()
    verified: dict[str, str] = {}
    for relative_name, expected_sha256 in sorted(files.items()):
        relative = Path(relative_name)
        if (
            relative.is_absolute()
            or ".." in relative.parts
            or not isinstance(expected_sha256, str)
            or len(expected_sha256) != 64
            or any(character not in "0123456789abcdef" for character in expected_sha256)
        ):
            raise FidelityError(f"invalid implementation contract entry: {relative_name!r}")
        path = (project_root / relative).resolve()
        if not path.is_relative_to(project_root) or not path.is_file():
            raise FidelityError(f"implementation file is missing: {path}")
        actual_sha256 = sha256_file(path)
        if actual_sha256 != expected_sha256:
            raise FidelityError(f"implementation SHA256 mismatch: {relative_name}")
        verified[relative.as_posix()] = actual_sha256
    return verified


def _parse_xyz(value: str | None, *, name: str) -> tuple[float, float, float]:
    if value is None:
        raise FidelityError(f"{name} is missing xyz")
    try:
        result = tuple(float(component) for component in value.split())
    except ValueError as error:
        raise FidelityError(f"{name} contains invalid xyz") from error
    if len(result) != 3 or not all(math.isfinite(component) for component in result):
        raise FidelityError(f"{name} must contain three finite coordinates")
    return result


def inspect_racer_geometry(xml_bytes: bytes) -> dict[str, dict[str, list[float]]]:
    """Read the four propeller inertial and fixed-joint offsets from a RACE URDF."""

    try:
        root = ET.fromstring(xml_bytes)
    except ET.ParseError as error:
        raise FidelityError("RACE URDF is not valid XML") from error
    if root.tag != "robot" or root.attrib.get("name") != "racer":
        raise FidelityError("asset is not the Genesis RACE URDF")
    fixed_joint_offsets: dict[str, list[float]] = {}
    inertial_offsets: dict[str, list[float]] = {}
    for propeller in EXPECTED_PROP_OFFSETS:
        joint = root.find(f"./joint[@name='{propeller}_joint']")
        link = root.find(f"./link[@name='{propeller}_link']")
        if joint is None or link is None or joint.attrib.get("type") != "fixed":
            raise FidelityError(f"asset is missing fixed geometry for {propeller}")
        child = joint.find("child")
        if child is None or child.attrib.get("link") != f"{propeller}_link":
            raise FidelityError(f"{propeller}_joint does not attach {propeller}_link")
        joint_origin = joint.find("origin")
        inertial_origin = link.find("./inertial/origin")
        fixed_joint_offsets[propeller] = list(
            _parse_xyz(
                "0 0 0" if joint_origin is None else joint_origin.attrib.get("xyz", "0 0 0"),
                name=f"{propeller}_joint",
            )
        )
        if inertial_origin is None:
            raise FidelityError(f"{propeller}_link is missing inertial origin")
        inertial_offsets[propeller] = list(
            _parse_xyz(
                inertial_origin.attrib.get("xyz"),
                name=f"{propeller}_link inertial origin",
            )
        )
    return {
        "fixed_joint_offsets_m": fixed_joint_offsets,
        "inertial_offsets_m": inertial_offsets,
    }


def _all_finite(value: Any) -> bool:
    if isinstance(value, dict):
        return all(_all_finite(nested) for nested in value.values())
    if isinstance(value, (list, tuple)):
        return all(_all_finite(nested) for nested in value)
    return (
        not isinstance(value, bool)
        and isinstance(value, (int, float))
        and math.isfinite(float(value))
    )


def _maximum_offset_error(
    actual: dict[str, list[float]],
    expected: dict[str, tuple[float, float, float]],
) -> float:
    return max(
        abs(float(actual[propeller][axis]) - expected[propeller][axis])
        for propeller in expected
        for axis in range(3)
    )


def evaluate_physics_gates(
    measurements: dict[str, Any],
    *,
    minimum_signed_response_rad_s: float,
    maximum_hover_roll_pitch_norm_rad_s: float,
) -> tuple[dict[str, bool], dict[str, Any]]:
    """Validate measured evidence without importing Torch or Genesis."""

    if (
        not math.isfinite(minimum_signed_response_rad_s)
        or minimum_signed_response_rad_s <= 0.0
        or not math.isfinite(maximum_hover_roll_pitch_norm_rad_s)
        or maximum_hover_roll_pitch_norm_rad_s <= 0.0
    ):
        raise FidelityError("simulator-fidelity thresholds must be finite and positive")
    stock = measurements.get("stock_geometry")
    corrected = measurements.get("corrected_geometry")
    link_offsets = measurements.get("measured_link_offsets_m")
    angular_velocity = measurements.get("angular_velocity_rad_s")
    if not all(isinstance(value, dict) for value in (stock, corrected, link_offsets)):
        raise FidelityError("geometry measurements are incomplete")
    if not isinstance(angular_velocity, list) or len(angular_velocity) != 5:
        raise FidelityError("physics evidence must contain hover plus four motor responses")
    for row in angular_velocity:
        if not isinstance(row, list) or len(row) != 3:
            raise FidelityError("each angular-velocity response must contain xyz")
    for geometry_name, geometry in (("stock", stock), ("corrected", corrected)):
        if set(geometry) != {"fixed_joint_offsets_m", "inertial_offsets_m"}:
            raise FidelityError(f"{geometry_name} geometry field set mismatch")
        for field in ("fixed_joint_offsets_m", "inertial_offsets_m"):
            offsets = geometry[field]
            if not isinstance(offsets, dict) or set(offsets) != set(EXPECTED_PROP_OFFSETS):
                raise FidelityError(f"{geometry_name} {field} propeller set mismatch")
            if any(not isinstance(value, list) or len(value) != 3 for value in offsets.values()):
                raise FidelityError(f"{geometry_name} {field} must contain xyz triplets")
    if set(link_offsets) != set(EXPECTED_PROP_OFFSETS):
        raise FidelityError("Genesis link-offset propeller set mismatch")

    zero = {propeller: (0.0, 0.0, 0.0) for propeller in EXPECTED_PROP_OFFSETS}
    stock_fixed = stock["fixed_joint_offsets_m"]
    stock_inertial = stock["inertial_offsets_m"]
    corrected_fixed = corrected["fixed_joint_offsets_m"]
    corrected_inertial = corrected["inertial_offsets_m"]
    numeric_evidence = {
        "stock": stock,
        "corrected": corrected,
        "link_offsets": link_offsets,
        "angular_velocity": angular_velocity,
        "maximum_measured_link_offset_error_m": measurements.get(
            "maximum_measured_link_offset_error_m"
        ),
    }
    finite = _all_finite(numeric_evidence)
    stock_bug_matches = bool(
        finite
        and _maximum_offset_error(stock_fixed, zero) == 0.0
        and _maximum_offset_error(stock_inertial, EXPECTED_PROP_OFFSETS) == 0.0
    )
    corrected_exact = bool(
        finite and _maximum_offset_error(corrected_fixed, EXPECTED_PROP_OFFSETS) == 0.0
    )
    corrected_inertial_zero = bool(
        finite and _maximum_offset_error(corrected_inertial, zero) == 0.0
    )
    moment_arms_nonzero = bool(
        finite
        and all(
            math.hypot(float(corrected_fixed[propeller][0]), float(corrected_fixed[propeller][1]))
            > 0.0
            for propeller in EXPECTED_PROP_OFFSETS
        )
    )
    reported_link_offset_error = measurements.get("maximum_measured_link_offset_error_m")
    link_offset_error = (
        max(
            _maximum_offset_error(link_offsets, EXPECTED_PROP_OFFSETS),
            float(reported_link_offset_error),
        )
        if finite
        else math.inf
    )
    motor_rows = angular_velocity[1:]
    signed_responses = {
        propeller: [
            float(motor_rows[index][axis]) * EXPECTED_ROLL_PITCH_SIGNS[propeller][axis]
            for axis in range(2)
        ]
        for index, propeller in enumerate(EXPECTED_PROP_OFFSETS)
    }
    minimum_signed_response = (
        min(value for row in signed_responses.values() for value in row) if finite else -math.inf
    )
    hover_roll_pitch_norm = (
        math.hypot(float(angular_velocity[0][0]), float(angular_velocity[0][1]))
        if finite
        else math.inf
    )
    stock_sha256 = measurements.get("stock_source_urdf_sha256")
    corrected_sha256 = measurements.get("corrected_runtime_urdf_sha256")
    hashes_recorded = bool(
        isinstance(stock_sha256, str)
        and len(stock_sha256) == 64
        and isinstance(corrected_sha256, str)
        and len(corrected_sha256) == 64
        and stock_sha256 != corrected_sha256
    )
    checks = {
        "all_numeric_evidence_finite": finite,
        "stock_geometry_matches_audited_bug": stock_bug_matches,
        "corrected_fixed_joint_offsets_exact": corrected_exact,
        "corrected_inertial_offsets_zero": corrected_inertial_zero,
        "nonzero_propeller_moment_arms": moment_arms_nonzero,
        "genesis_link_offsets_match_corrected_asset": link_offset_error <= 1.0e-6,
        "four_isolated_single_motor_responses_present": len(motor_rows) == 4,
        "signed_roll_pitch_mapping_matches": minimum_signed_response > 0.0,
        "minimum_signed_roll_pitch_response_met": (
            minimum_signed_response >= minimum_signed_response_rad_s
        ),
        "balanced_hover_roll_pitch_norm_within_limit": (
            hover_roll_pitch_norm <= maximum_hover_roll_pitch_norm_rad_s
        ),
        "stock_and_corrected_asset_hashes_recorded_and_distinct": hashes_recorded,
    }
    if set(checks) != PHYSICS_CHECKS:
        raise RuntimeError("internal fidelity check set drift")
    derived = {
        "expected_propeller_offsets_m": {
            propeller: list(offset) for propeller, offset in EXPECTED_PROP_OFFSETS.items()
        },
        "expected_signed_roll_pitch_mapping": {
            propeller: list(signs) for propeller, signs in EXPECTED_ROLL_PITCH_SIGNS.items()
        },
        "maximum_genesis_link_offset_error_m": link_offset_error,
        "balanced_hover_roll_pitch_norm_rad_s": hover_roll_pitch_norm,
        "signed_roll_pitch_response_rad_s": signed_responses,
        "minimum_signed_roll_pitch_response_rad_s": minimum_signed_response,
        "registered_minimum_signed_response_rad_s": minimum_signed_response_rad_s,
        "registered_maximum_hover_roll_pitch_norm_rad_s": (maximum_hover_roll_pitch_norm_rad_s),
    }
    return checks, derived


def _json_safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _json_safe(nested) for key, nested in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(nested) for nested in value]
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return value


def write_json_new(path: Path, payload: dict[str, Any]) -> None:
    """Atomically create a strict JSON artifact without an overwrite race."""

    path = path.expanduser().absolute()
    if os.path.lexists(path):
        raise FileExistsError(f"refusing to overwrite output: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    serialized = (json.dumps(payload, allow_nan=False, indent=2, sort_keys=True) + "\n").encode(
        "utf-8"
    )
    descriptor, temporary_name = tempfile.mkstemp(
        dir=path.parent,
        prefix=f".{path.name}.",
        suffix=".tmp",
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(serialized)
            stream.flush()
            os.fsync(stream.fileno())
        try:
            os.link(temporary, path)
        except FileExistsError as error:
            raise FileExistsError(f"refusing to overwrite output: {path}") from error
        directory_fd = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass


def _validate_frozen_protocol(protocol: dict[str, Any]) -> dict[str, float]:
    if protocol.get("status") != FROZEN_STATUS:
        raise FidelityError("causal falsifier protocol is not frozen")
    if protocol.get("protocol_version") != PROTOCOL_VERSION:
        raise FidelityError("causal falsifier protocol version mismatch")
    environment = protocol.get("execution_environment")
    gate = protocol.get("simulator_fidelity_gate")
    if not isinstance(environment, dict) or not isinstance(gate, dict):
        raise FidelityError("protocol execution/fidelity gate is missing")
    if (
        environment.get("visible_gpu_count") != 1
        or environment.get("hip_visible_devices") != "0"
        or environment.get("backend") != "genesis.amdgpu"
        or environment.get("require_nonempty_torch_hip") is not True
    ):
        raise FidelityError("protocol one-Radeon execution contract mismatch")
    minimum = gate.get("minimum_signed_single_motor_roll_pitch_response_rad_s")
    maximum = gate.get("maximum_balanced_hover_roll_pitch_norm_rad_s")
    if (
        isinstance(minimum, bool)
        or not isinstance(minimum, (int, float))
        or isinstance(maximum, bool)
        or not isinstance(maximum, (int, float))
        or not math.isfinite(float(minimum))
        or float(minimum) <= 0.0
        or not math.isfinite(float(maximum))
        or float(maximum) <= 0.0
        or gate.get("runtime_race_asset_must_have_nonzero_propeller_moment_arms") is not True
        or gate.get("runtime_generated_asset_sha256_must_be_recorded") is not True
    ):
        raise FidelityError("protocol simulator-fidelity thresholds are invalid")
    return {
        "minimum_signed_response_rad_s": float(minimum),
        "maximum_hover_roll_pitch_norm_rad_s": float(maximum),
    }


def run_fidelity(
    *,
    protocol_path: Path,
) -> dict[str, Any]:
    protocol_path = protocol_path.expanduser().resolve()
    protocol = load_strict_json(protocol_path)
    thresholds = _validate_frozen_protocol(protocol)
    protocol_sha256 = sha256_file(protocol_path)
    project_root = Path(__file__).resolve().parent.parent
    implementation_files_sha256 = verify_implementation_contract(
        protocol,
        project_root=project_root,
    )
    if os.environ.get("HIP_VISIBLE_DEVICES") != "0":
        raise FidelityError("HIP_VISIBLE_DEVICES must be exactly 0")

    import genesis as gs
    import torch

    genesis_source = Path(gs.__file__).resolve().parents[1]
    genesis_source_tree = sha256_source_tree(genesis_source)
    expected_genesis_sha256 = protocol["execution_environment"].get("genesis_source_tree_sha256")
    if genesis_source_tree["sha256"] != expected_genesis_sha256:
        raise FidelityError("Genesis source-tree SHA256 mismatch")
    stock_source = Path(gs.__file__).resolve().parent / "assets" / "urdf" / "drones" / "racer.urdf"
    if (
        stock_source.is_symlink()
        or not stock_source.is_file()
        or not stat.S_ISREG(stock_source.stat().st_mode)
    ):
        raise FidelityError(f"stock Genesis RACE asset is invalid: {stock_source}")

    from flightguard.racer_asset import prepare_corrected_racer_urdf

    corrected_runtime = prepare_corrected_racer_urdf(stock_source)
    stock_geometry = inspect_racer_geometry(stock_source.read_bytes())
    corrected_geometry = inspect_racer_geometry(corrected_runtime.read_bytes())
    stock_sha256 = sha256_file(stock_source)
    corrected_sha256 = sha256_file(corrected_runtime)

    gs.init(
        backend=gs.amdgpu,
        precision="32",
        seed=GENESIS_SEED,
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
        raise FidelityError("exactly one Radeon/ROCm GPU is required")

    from flightguard.genesis_env import FlightGuardGenesisEnv

    env = FlightGuardGenesisEnv(5, drone_urdf=corrected_runtime)
    base_position = env.drone.get_link("base_link").get_pos()
    measured_link_offsets: dict[str, list[float]] = {}
    maximum_measured_link_offset_error = 0.0
    for propeller, expected_offset in EXPECTED_PROP_OFFSETS.items():
        offsets = env.drone.get_link(f"{propeller}_link").get_pos() - base_position
        measured_link_offsets[propeller] = offsets[0].detach().cpu().tolist()
        expected = torch.tensor(
            expected_offset,
            dtype=offsets.dtype,
            device=offsets.device,
        ).expand_as(offsets)
        maximum_measured_link_offset_error = max(
            maximum_measured_link_offset_error,
            float(torch.abs(offsets - expected).max().item()),
        )

    actions = torch.zeros((5, 4), dtype=torch.float32, device=env.device)
    for motor_index in range(4):
        actions[motor_index + 1, motor_index] = MOTOR_ACTION_PERTURBATION
    torch.cuda.synchronize()
    for _ in range(PHYSICS_STEPS):
        env.step(actions)
    torch.cuda.synchronize()
    angular_velocity = env.drone.get_ang().detach().cpu().tolist()
    measurements = {
        "stock_geometry": stock_geometry,
        "corrected_geometry": corrected_geometry,
        "measured_link_offsets_m": measured_link_offsets,
        "angular_velocity_rad_s": angular_velocity,
        "maximum_measured_link_offset_error_m": maximum_measured_link_offset_error,
        "stock_source_urdf_sha256": stock_sha256,
        "corrected_runtime_urdf_sha256": corrected_sha256,
    }
    physics_checks, derived = evaluate_physics_gates(
        measurements,
        minimum_signed_response_rad_s=thresholds["minimum_signed_response_rad_s"],
        maximum_hover_roll_pitch_norm_rad_s=thresholds["maximum_hover_roll_pitch_norm_rad_s"],
    )
    checks = {
        "backend_is_amdgpu": gs.backend == gs.amdgpu,
        "visible_gpu_count_is_one": visible_gpu_count == 1,
        "torch_hip_nonempty": bool(torch.version.hip),
        "genesis_source_tree_matches_protocol": (
            genesis_source_tree["sha256"] == expected_genesis_sha256
        ),
        "implementation_contract_verified": (
            implementation_files_sha256 == protocol["implementation_contract"]["files"]
        ),
        **physics_checks,
    }
    status = "PASS" if all(checks.values()) else "FAIL"
    return {
        "schema_version": SCHEMA_VERSION,
        "status": status,
        "simulation_only": True,
        "protocol": {
            "path": str(protocol_path),
            "sha256": protocol_sha256,
            "version": protocol["protocol_version"],
        },
        "execution": {
            "backend": str(gs.backend),
            "device": str(gs.device),
            "gpu_name": torch.cuda.get_device_name(0),
            "visible_gpu_count": visible_gpu_count,
            "torch_version": torch.__version__,
            "torch_hip": torch.version.hip,
            "genesis_version": str(gs.__version__),
            "genesis_seed": GENESIS_SEED,
            "genesis_source": str(genesis_source),
            "genesis_source_tree": genesis_source_tree,
            "implementation_files_sha256": implementation_files_sha256,
        },
        "assets": {
            "stock_source": {
                "path": str(stock_source.resolve()),
                "sha256": stock_sha256,
                **stock_geometry,
            },
            "corrected_runtime": {
                "path": str(corrected_runtime.resolve()),
                "sha256": corrected_sha256,
                **corrected_geometry,
            },
        },
        "physics": {
            "real_genesis_scene_executed": True,
            "environment_count": 5,
            "environment_roles": [
                "balanced_hover",
                "isolated_prop0_perturbation",
                "isolated_prop1_perturbation",
                "isolated_prop2_perturbation",
                "isolated_prop3_perturbation",
            ],
            "steps": PHYSICS_STEPS,
            "dt_s": env.dt,
            "motor_action_perturbation": MOTOR_ACTION_PERTURBATION,
            "motor_rpm_multiplier": MOTOR_RPM_MULTIPLIER,
            "measured_link_offsets_m": measured_link_offsets,
            "balanced_hover_angular_velocity_rad_s": angular_velocity[0],
            "single_motor_angular_velocity_rad_s": {
                propeller: angular_velocity[index + 1]
                for index, propeller in enumerate(EXPECTED_PROP_OFFSETS)
            },
            **derived,
        },
        "checks": checks,
    }


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    protocol_path = args.protocol.expanduser().resolve()
    output_path = args.output.expanduser().absolute()
    if output_path == protocol_path:
        raise ValueError("--output must not overwrite --protocol")
    if os.path.lexists(output_path):
        raise FileExistsError(f"refusing to overwrite output: {output_path}")
    protocol = load_strict_json(protocol_path)
    require_registered_output_path(protocol, output_path, "fidelity.json")
    payload = run_fidelity(protocol_path=protocol_path)
    write_json_new(output_path, _json_safe(payload))
    print(
        json.dumps(
            {
                "event": "causal_simulator_fidelity_complete",
                "status": payload["status"],
                "output": str(output_path),
            },
            allow_nan=False,
            sort_keys=True,
        ),
        flush=True,
    )
    return 0 if payload["status"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
