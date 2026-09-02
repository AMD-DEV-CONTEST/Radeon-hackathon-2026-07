#!/usr/bin/env python3
"""Evaluate learned-only fault candidates against shared nominal references."""

from __future__ import annotations

import argparse
import hashlib
import inspect
import json
import math
import re
import sys
import time
from collections.abc import Mapping
from dataclasses import asdict, replace
from pathlib import Path
from typing import Any

import numpy as np

try:
    import torch
except ModuleNotFoundError:
    torch = None  # type: ignore[assignment]


from flightguard.falsifier import (
    LATENT_NAMES,
    CemState,
    FaultCandidate,
    canonical_fault_candidate,
    canonicalize_cem_state,
    require_registered_output_path,
    sample_cem_candidates,
    sample_initial_prior,
)

SCHEMA_VERSION = "flightguard-causal-falsifier-batch-v1"
CANDIDATE_SCHEMA_VERSION = "flightguard-causal-candidate-batch-v1"
LEGACY_PROTOCOL_STATUS = "PRE_REGISTERED_AFTER_V3_FAILURE_BEFORE_FIRST_CAUSAL_FALSIFIER_GPU_RUN"
PAIRED_PROTOCOL_STATUS = "PRE_REGISTERED_AFTER_R3_NUMERICAL_DIAGNOSIS_BEFORE_FIRST_R4_GPU_RUN"
FORMAL_PROTOCOL_STATUS = "PRE_REGISTERED_AFTER_R4_STRUCTURAL_PASS_BEFORE_FIRST_R5_SEARCH_GPU_RUN"
R6_HIDDEN_PROTOCOL_STATUS = (
    "PRE_REGISTERED_AFTER_R5_DISCOVERY_SEAL_BEFORE_FIRST_R6_HIDDEN_GPU_RUN"
)
R6_HIDDEN_PROTOCOL_SCHEMA_VERSION = "flightguard-causal-hidden-protocol-v1"
R6_HIDDEN_RECOVERY_PROTOCOL_SCHEMA_VERSION = (
    "flightguard-causal-hidden-recovery-protocol-v1"
)
R6_HIDDEN_PROTOCOL_VERSION = (
    "flightguard-causal-falsifier-v1-r6-hidden-20260729"
)
R6_HIDDEN_RECOVERY_PROTOCOL_STATUS = (
    "PRE_REGISTERED_TRANSPARENT_CODE_ONLY_RECOVERY_AFTER_PARTIAL_R6_EXECUTION"
)
R6_HIDDEN_RECOVERY_PROTOCOL_VERSION = (
    "flightguard-causal-falsifier-v1-r6-hidden-recovery-v1-20260729"
)
CONFIRMATION_PROTOCOL_SCHEMA_VERSION = (
    "flightguard-causal-hidden-public-entropy-confirmation-protocol-v2"
)
CONFIRMATION_PROTOCOL_VERSION = (
    "flightguard-causal-falsifier-v1-r7-public-entropy-confirmation-v2-20260729"
)
CONFIRMATION_PROTOCOL_STATUS = (
    "PRE_REGISTERED_FRESH_PUBLIC_ENTROPY_CONFIRMATION_V2_AFTER_"
    "PRE_EXECUTION_V1_SUPERSESSION"
)
CONFIRMATION_EXECUTION_SCHEMA_VERSION = (
    "flightguard-r7-public-entropy-confirmation-execution-v2"
)
FORMAL_HIDDEN_BATCH_SCHEMA_VERSION = "flightguard-formal-hidden-candidate-batch-v1"
FORMAL_HIDDEN_ALGORITHM_LEAF_SUPPORTED = True
PAIRED_EXECUTION_SCHEMA_VERSION = "flightguard-lane-aligned-dual-pass-v1"
FULL_TRAJECTORY_DIGEST_SCHEMA_VERSION = "flightguard-full-trajectory-lane-digest-v1"
SEARCH_STATE_SCHEMA_VERSION = "flightguard-lane-aligned-search-state-v1"
INITIAL_SEARCH_STATE_SENTINEL = "INITIAL_CEM_STATE_V1"
PAIRED_LANE_ROLES = ("candidate", "nominal")
ONE_MINIMAL_V2_PHASE = "one_minimal_v2"
ONE_MINIMAL_V2_PASS_SCHEMA_VERSION = "flightguard-one-minimal-v2-pass-v1"
ONE_MINIMAL_V2_PROTOCOL_SCHEMA_VERSION = "flightguard-one-minimal-v2-protocol-v1"
ONE_MINIMAL_V2_PROTOCOL_STATUS = (
    "PRE_REGISTERED_AFTER_REPAIR_CONFIRMATION_BEFORE_FIRST_ONE_MINIMAL_V2_RUN"
)
ONE_MINIMAL_V2_LANE_EVIDENCE_SCHEMA_VERSION = (
    "flightguard-one-minimal-v2-lane-evidence-v1"
)
TRACKED_FIELDS = (
    "truth_position",
    "truth_velocity",
    "truth_quaternion",
    "truth_angular_velocity",
    "measured_quaternion",
    "measured_angular_velocity",
    "estimated_position",
    "estimated_velocity",
    "issued_action",
    "applied_action",
)
DISCRETE_TRACE_FIELDS = (
    "active_before_step",
    "terminal_after_step",
    "success_after_step",
    "gates_passed_after_step",
)


def is_r6_hidden_protocol(protocol: Mapping[str, Any]) -> bool:
    identity = (
        protocol.get("status"),
        protocol.get("protocol_version"),
    )
    return identity in {
        (R6_HIDDEN_PROTOCOL_STATUS, R6_HIDDEN_PROTOCOL_VERSION),
        (
            R6_HIDDEN_RECOVERY_PROTOCOL_STATUS,
            R6_HIDDEN_RECOVERY_PROTOCOL_VERSION,
        ),
    }


def is_confirmation_protocol(protocol: Mapping[str, Any]) -> bool:
    return (
        protocol.get("status"),
        protocol.get("protocol_version"),
    ) == (CONFIRMATION_PROTOCOL_STATUS, CONFIRMATION_PROTOCOL_VERSION)


def is_formal_hidden_protocol(protocol: Mapping[str, Any]) -> bool:
    return is_r6_hidden_protocol(protocol) or is_confirmation_protocol(
        protocol
    )


def final_event_payload(
    *,
    status: str,
    output_path: Path,
    episode_records: list[dict[str, Any]],
    lane_role: str,
    paired_execution: dict[str, Any] | None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "event": "causal_falsifier_batch_final",
        "status": status,
        "output": str(output_path),
    }
    if paired_execution is None:
        payload["valid_causal_failures"] = sum(
            bool(record["valid_causal_failure"]) for record in episode_records
        )
    else:
        payload["execution_lane_role"] = lane_role
        payload["episode_count"] = len(episode_records)
    return payload


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--protocol", type=Path, required=True)
    parser.add_argument("--candidate-batch", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--lane-role",
        choices=("legacy", *PAIRED_LANE_ROLES),
        default="legacy",
    )
    parser.add_argument("--checkpoint-seed", type=int)
    parser.add_argument("--arm-id")
    parser.add_argument("--lane-evidence", type=Path)
    return parser.parse_args()


def reject_nonfinite(value: str) -> None:
    raise ValueError(f"non-finite JSON constant is forbidden: {value}")


def reject_duplicate_keys(
    pairs: list[tuple[str, Any]],
) -> dict[str, Any]:
    payload: dict[str, Any] = {}
    for key, value in pairs:
        if key in payload:
            raise ValueError(f"duplicate JSON key is forbidden: {key}")
        payload[key] = value
    return payload


def load_strict_json(path: Path) -> dict[str, Any]:
    payload = json.loads(
        path.read_text(encoding="utf-8"),
        parse_constant=reject_nonfinite,
        object_pairs_hook=reject_duplicate_keys,
    )
    if not isinstance(payload, dict):
        raise TypeError(f"JSON root must be an object: {path}")
    return payload


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _canonical_json_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def _one_minimal_v2_protocol(
    protocol: Mapping[str, Any],
    *,
    protocol_path: Path,
) -> tuple[str, list[dict[str, int]], list[dict[str, Any]], list[dict[str, Any]]]:
    protocol_path = protocol_path.expanduser().resolve()
    if (
        protocol.get("schema_version") != ONE_MINIMAL_V2_PROTOCOL_SCHEMA_VERSION
        or protocol.get("status") != ONE_MINIMAL_V2_PROTOCOL_STATUS
        or protocol.get("simulation_only") is not True
        or protocol.get("phase") != ONE_MINIMAL_V2_PHASE
    ):
        raise ValueError("one-minimal v2 protocol header mismatch")
    identity = {key: value for key, value in protocol.items() if key != "protocol_id"}
    protocol_id = hashlib.sha256(_canonical_json_bytes(identity)).hexdigest()
    if protocol.get("protocol_id") != protocol_id:
        raise ValueError("one-minimal v2 protocol ID is not canonical")
    execution = protocol.get("execution")
    implementation = protocol.get("implementation_contract")
    if (
        not isinstance(execution, Mapping)
        or execution.get("ready") is not True
        or not isinstance(implementation, Mapping)
        or implementation.get("status") != "PASS"
        or implementation.get("ready") is not True
    ):
        raise ValueError("one-minimal v2 protocol is not execution-ready")
    implementation_files = implementation.get("files")
    if not isinstance(implementation_files, Mapping):
        raise TypeError("one-minimal v2 implementation files are missing")
    evaluator = implementation_files.get("evaluator")
    if (
        not isinstance(evaluator, Mapping)
        or Path(str(evaluator.get("path"))).expanduser().resolve() != Path(__file__).resolve()
        or evaluator.get("sha256") != sha256_file(Path(__file__).resolve())
    ):
        raise ValueError("running evaluator differs from frozen one-minimal implementation")

    lanes_value = protocol.get("shared_lane_grid")
    if not isinstance(lanes_value, list) or not lanes_value:
        raise ValueError("one-minimal v2 lane grid is empty")
    lanes: list[dict[str, int]] = []
    for index, value in enumerate(lanes_value):
        if not isinstance(value, Mapping) or set(value) != {
            "lane_index",
            "context_seed",
            "genesis_seed",
        }:
            raise ValueError(f"one-minimal v2 lane {index} field set mismatch")
        lane = dict(value)
        if (
            lane["lane_index"] != index
            or any(
                isinstance(lane[name], bool)
                or not isinstance(lane[name], int)
                or lane[name] < 0
                for name in ("context_seed", "genesis_seed")
            )
        ):
            raise ValueError(f"one-minimal v2 lane {index} identity is invalid")
        lanes.append(lane)
    if len({lane["context_seed"] for lane in lanes}) != len(lanes) or len(
        {lane["genesis_seed"] for lane in lanes}
    ) != len(lanes):
        raise ValueError("one-minimal v2 lane seeds must be unique by RNG role")

    arms_value = protocol.get("arms")
    checkpoints_value = protocol.get("checkpoints")
    if not isinstance(arms_value, list) or not arms_value:
        raise ValueError("one-minimal v2 arms are missing")
    if not isinstance(checkpoints_value, list) or not checkpoints_value:
        raise ValueError("one-minimal v2 checkpoints are missing")
    arms = [dict(value) if isinstance(value, Mapping) else {} for value in arms_value]
    checkpoints = [
        dict(value) if isinstance(value, Mapping) else {} for value in checkpoints_value
    ]
    if any(not arm for arm in arms) or len({arm.get("arm_id") for arm in arms}) != len(arms):
        raise ValueError("one-minimal v2 arm registry is invalid")
    if any(not checkpoint for checkpoint in checkpoints) or len(
        {checkpoint.get("seed") for checkpoint in checkpoints}
    ) != len(checkpoints):
        raise ValueError("one-minimal v2 checkpoint registry is invalid")
    return sha256_file(protocol_path), lanes, arms, checkpoints


ONE_MINIMAL_V2_PASS_LANE_FIELDS = {
    "lane_index",
    "context_seed",
    "genesis_seed",
    "mission_success",
    "terminal_failure",
    "active_at_freeze",
    "context_qualified_at_freeze",
    "failure_elapsed_s",
    "all_outputs_finite",
    "applied_action_saturation_fraction",
    "trajectory_raw_sha256",
}


def _validate_one_minimal_v2_lane(
    value: Any,
    *,
    expected_lane: Mapping[str, int],
    name: str,
) -> dict[str, Any]:
    if not isinstance(value, Mapping) or set(value) != ONE_MINIMAL_V2_PASS_LANE_FIELDS:
        raise ValueError(f"{name} field set mismatch")
    lane = dict(value)
    if any(
        lane.get(key) != expected_lane[key]
        for key in ("lane_index", "context_seed", "genesis_seed")
    ):
        raise ValueError(f"{name} identity differs from the frozen lane grid")
    for key in (
        "mission_success",
        "terminal_failure",
        "active_at_freeze",
        "context_qualified_at_freeze",
        "all_outputs_finite",
    ):
        if type(lane.get(key)) is not bool:
            raise TypeError(f"{name}.{key} must be boolean")
    elapsed = lane.get("failure_elapsed_s")
    if elapsed is not None and (
        type(elapsed) not in {int, float}
        or not math.isfinite(float(elapsed))
        or float(elapsed) < 0.0
    ):
        raise ValueError(f"{name}.failure_elapsed_s must be finite and non-negative")
    if lane["terminal_failure"] is True:
        if lane["mission_success"] is True or elapsed is None:
            raise ValueError(f"{name} terminal outcome is inconsistent")
    elif elapsed is not None:
        raise ValueError(f"{name} nonterminal outcome cannot have failure elapsed time")
    saturation = lane.get("applied_action_saturation_fraction")
    if (
        type(saturation) not in {int, float}
        or not math.isfinite(float(saturation))
        or not 0.0 <= float(saturation) <= 1.0
    ):
        raise ValueError(f"{name} saturation fraction is invalid")
    trajectory_sha = lane.get("trajectory_raw_sha256")
    if (
        not isinstance(trajectory_sha, str)
        or re.fullmatch(r"[0-9a-f]{64}", trajectory_sha) is None
    ):
        raise ValueError(f"{name} trajectory SHA256 is invalid")
    return json.loads(_canonical_json_bytes(lane))


def one_minimal_v2_pass_path(
    protocol: Mapping[str, Any],
    *,
    checkpoint_seed: int,
    arm_id: str,
    lane_role: str,
) -> Path:
    if lane_role not in PAIRED_LANE_ROLES:
        raise ValueError("one-minimal v2 lane role must be candidate or nominal")
    outputs = protocol.get("registered_outputs")
    if not isinstance(outputs, Mapping):
        raise TypeError("one-minimal v2 registered outputs are missing")
    root = Path(str(outputs.get("output_root"))).expanduser()
    if not root.is_absolute():
        raise ValueError("one-minimal v2 output root must be absolute")
    return (
        root
        / "artifacts"
        / f"checkpoint-{checkpoint_seed}"
        / arm_id
        / f"{lane_role}-pass.json"
    ).resolve()


def build_one_minimal_v2_pass(
    *,
    protocol_path: Path,
    checkpoint_seed: int,
    arm_id: str,
    lane_role: str,
    lane_evidence: list[dict[str, Any]],
) -> dict[str, Any]:
    protocol_path = protocol_path.expanduser().resolve()
    protocol = load_strict_json(protocol_path)
    protocol_sha256, lanes, arms, checkpoints = _one_minimal_v2_protocol(
        protocol,
        protocol_path=protocol_path,
    )
    if lane_role not in PAIRED_LANE_ROLES:
        raise ValueError("one-minimal v2 lane role must be candidate or nominal")
    arm_by_id = {str(arm["arm_id"]): arm for arm in arms}
    if arm_id not in arm_by_id:
        raise ValueError("one-minimal v2 arm is not registered")
    checkpoint_by_seed = {checkpoint.get("seed"): checkpoint for checkpoint in checkpoints}
    checkpoint = checkpoint_by_seed.get(checkpoint_seed)
    if not isinstance(checkpoint, Mapping):
        raise TypeError("one-minimal v2 checkpoint is not registered")
    checkpoint_path = Path(str(checkpoint.get("path"))).expanduser().resolve()
    if (
        not checkpoint_path.is_file()
        or checkpoint.get("sha256") != sha256_file(checkpoint_path)
    ):
        raise ValueError("one-minimal v2 checkpoint bytes mismatch")
    if not isinstance(lane_evidence, list) or len(lane_evidence) != len(lanes):
        raise ValueError("one-minimal v2 evidence must cover every registered lane exactly once")
    validated_lanes = [
        _validate_one_minimal_v2_lane(
            value,
            expected_lane=expected_lane,
            name=f"one-minimal v2 lane {index}",
        )
        for index, (value, expected_lane) in enumerate(
            zip(lane_evidence, lanes, strict=True)
        )
    ]
    arm = arm_by_id[arm_id]
    candidate = arm.get("candidate")
    if not isinstance(candidate, Mapping) or not isinstance(candidate.get("candidate_id"), str):
        raise TypeError("one-minimal v2 arm candidate identity is missing")
    return {
        "schema_version": ONE_MINIMAL_V2_PASS_SCHEMA_VERSION,
        "status": "PASS",
        "simulation_only": True,
        "protocol_sha256": protocol_sha256,
        "phase": ONE_MINIMAL_V2_PHASE,
        "checkpoint_seed": checkpoint_seed,
        "arm_id": arm_id,
        "lane_role": lane_role,
        "candidate_id": (
            candidate["candidate_id"] if lane_role == "candidate" else "matched-nominal"
        ),
        "lanes": validated_lanes,
    }


def validate_one_minimal_v2_pass(
    payload: Any,
    *,
    protocol_path: Path,
    checkpoint_seed: int,
    arm_id: str,
    lane_role: str,
) -> dict[str, Any]:
    if not isinstance(payload, Mapping):
        raise TypeError("one-minimal v2 pass must be an object")
    lanes = payload.get("lanes")
    if not isinstance(lanes, list):
        raise TypeError("one-minimal v2 pass lanes must be a list")
    rebuilt = build_one_minimal_v2_pass(
        protocol_path=protocol_path,
        checkpoint_seed=checkpoint_seed,
        arm_id=arm_id,
        lane_role=lane_role,
        lane_evidence=lanes,
    )
    if _canonical_json_bytes(payload) != _canonical_json_bytes(rebuilt):
        raise ValueError("one-minimal v2 pass differs from canonical evaluator output")
    return rebuilt


def require_r6_hidden_output_path(
    protocol: Mapping[str, Any],
    actual: Path,
    *relative_parts: str,
) -> Path:
    if not is_formal_hidden_protocol(protocol):
        raise ValueError(
            "formal hidden output path requires a supported identity"
        )
    output = protocol.get("output_contract")
    if not isinstance(output, Mapping):
        raise TypeError("r6 output contract is missing")
    root = Path(str(output.get("output_root"))).expanduser()
    if not root.is_absolute():
        raise ValueError("r6 output root must be absolute")
    expected = root.joinpath(*relative_parts).resolve()
    resolved = actual.expanduser().resolve()
    if resolved != expected:
        raise ValueError(
            "r6 hidden artifact path differs from its frozen slot: "
            f"expected {expected}, got {resolved}"
        )
    return resolved


def sha256_source_tree(root: Path) -> dict[str, Any]:
    files: list[tuple[str, Path]] = []
    for path in root.resolve().rglob("*"):
        relative = path.relative_to(root.resolve())
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
    project_root = project_root.resolve()
    contract = protocol.get("implementation_contract")
    if not isinstance(contract, dict):
        raise TypeError("protocol implementation contract is missing")
    files = contract.get("files")
    if not isinstance(files, dict) or not files:
        raise ValueError("protocol implementation file hashes are not frozen")
    verified: dict[str, str] = {}
    for relative_name, expected_sha256 in sorted(files.items()):
        relative = Path(relative_name)
        if (
            relative.is_absolute()
            or ".." in relative.parts
            or not isinstance(expected_sha256, str)
            or len(expected_sha256) != 64
        ):
            raise ValueError(f"invalid implementation contract entry: {relative_name!r}")
        path = (project_root / relative).resolve()
        if not path.is_relative_to(project_root) or not path.is_file():
            raise FileNotFoundError(path)
        actual_sha256 = sha256_file(path)
        if actual_sha256 != expected_sha256:
            raise ValueError(f"implementation SHA256 mismatch: {relative_name}")
        verified[relative.as_posix()] = actual_sha256
    return verified


def canonical_candidate_id(
    *,
    thrust_scale: float,
    wind_acceleration_mps2: tuple[float, float, float],
    action_delay_steps: int,
) -> str:
    decoded = {
        "action_delay_steps": action_delay_steps,
        "thrust_scale": round(thrust_scale, 9),
        "wind_acceleration_mps2": [round(value, 9) for value in wind_acceleration_mps2],
    }
    serialized = json.dumps(
        decoded,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode()
    return hashlib.sha256(serialized).hexdigest()


def canonical_structural_candidate_records(gate: str) -> list[dict[str, Any]]:
    noop = FaultCandidate.from_latent((0.0, 0.0, 0.0, 0.0, 0.0))
    thrust_only = FaultCandidate.from_latent((1.0, 0.0, 0.0, 0.0, 0.0))
    wind_probe_latents = (
        (1.0, 0.0, 1.0),
        (0.5, 0.8660254037844386, -1.0),
        (-0.5, 0.8660254037844386, 1.0),
        (-1.0, 0.0, -1.0),
        (-0.5, -0.8660254037844386, 1.0),
        (0.5, -0.8660254037844386, -1.0),
    )
    wind_only = [
        FaultCandidate.from_latent(
            (
                0.0,
                wind_x,
                wind_y,
                wind_z,
                0.0,
            )
        )
        for wind_x, wind_y, wind_z in wind_probe_latents
    ]
    delay_only = FaultCandidate.from_latent((0.0, 0.0, 0.0, 0.0, 1.0 - 2.0**-24))
    kill = [thrust_only, *wind_only, delay_only]
    if gate == "exact_noop":
        candidates = [noop]
    elif gate == "kill_magnitude":
        candidates = kill
    elif gate == "lane_interference":
        candidates = [noop, kill[0], *kill[1:6], kill[-1]]
    else:
        raise ValueError(f"unknown structural gate: {gate}")
    records = [
        candidate.to_record(
            algorithm="structural",
            replicate_index=0,
            generation=0,
            candidate_index=index,
        )
        for index, candidate in enumerate(candidates)
    ]
    for record in records:
        record["latent"] = {
            name: round(float(value), 12) for name, value in record["latent"].items()
        }
        record["fault_burden"] = round(float(record["fault_burden"]), 12)
    return records


def canonical_candidate_record(
    candidate: FaultCandidate,
    *,
    algorithm: str,
    replicate_index: int,
    generation: int,
    candidate_index: int,
) -> dict[str, Any]:
    canonical = canonical_fault_candidate(candidate.latent)
    record = canonical.to_record(
        algorithm=algorithm,
        replicate_index=replicate_index,
        generation=generation,
        candidate_index=candidate_index,
    )
    record["latent"] = {name: round(float(record["latent"][name]), 12) for name in LATENT_NAMES}
    record["fault_burden"] = round(float(record["fault_burden"]), 12)
    return record


def _require_exact_nonnegative_int(value: Any, *, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{name} must be a non-negative integer")
    return value


def _formal_discovery_contract(protocol: dict[str, Any]) -> dict[str, Any]:
    discovery = protocol.get("discovery")
    rng = protocol.get("rng_contract")
    cem = protocol.get("cem")
    if not isinstance(discovery, dict):
        raise TypeError("formal discovery contract is missing")
    if not isinstance(rng, dict):
        raise TypeError("formal RNG contract is missing")
    if not isinstance(cem, dict):
        raise TypeError("formal CEM contract is missing")
    required_discovery = {
        "checkpoint_seed",
        "replicates",
        "generations",
        "contexts_per_replicate",
        "population_per_algorithm_per_generation",
        "minimum_same_lane_nominal_successes_per_candidate_per_generation",
    }
    if set(discovery) != required_discovery:
        raise ValueError("formal discovery field set mismatch")
    replicates = _require_exact_nonnegative_int(
        discovery["replicates"], name="discovery.replicates"
    )
    generations = _require_exact_nonnegative_int(
        discovery["generations"], name="discovery.generations"
    )
    contexts = _require_exact_nonnegative_int(
        discovery["contexts_per_replicate"],
        name="discovery.contexts_per_replicate",
    )
    population = _require_exact_nonnegative_int(
        discovery["population_per_algorithm_per_generation"],
        name="discovery.population_per_algorithm_per_generation",
    )
    required_nominal = _require_exact_nonnegative_int(
        discovery["minimum_same_lane_nominal_successes_per_candidate_per_generation"],
        name=("discovery.minimum_same_lane_nominal_successes_per_candidate_per_generation"),
    )
    if (
        replicates != 8
        or generations != 5
        or contexts != 6
        or population != 24
        or required_nominal != 5
    ):
        raise ValueError("formal discovery dimensions differ from the frozen design")
    checkpoint_seed = _require_exact_nonnegative_int(
        discovery["checkpoint_seed"], name="discovery.checkpoint_seed"
    )
    if checkpoint_seed != 30:
        raise ValueError("formal discovery checkpoint must be seed 30")
    stride = _require_exact_nonnegative_int(
        rng.get("generation_seed_stride"),
        name="rng_contract.generation_seed_stride",
    )
    if stride != 1_000:
        raise ValueError("formal generation seed stride differs from 1000")
    candidate_seed_banks: dict[str, list[int]] = {}
    for algorithm, field in (
        ("cem", "cem_candidate_seeds"),
        ("uniform", "uniform_candidate_seeds"),
    ):
        seeds = rng.get(field)
        if (
            not isinstance(seeds, list)
            or len(seeds) != replicates
            or any(type(seed) is not int or seed < 0 for seed in seeds)
            or len(set(seeds)) != len(seeds)
        ):
            raise ValueError(f"formal {field} is invalid")
        candidate_seed_banks[algorithm] = seeds
    context_banks = rng.get("discovery_context_seed_banks")
    if (
        not isinstance(context_banks, list)
        or len(context_banks) != replicates
        or any(
            not isinstance(bank, list)
            or len(bank) != contexts
            or len(set(bank)) != contexts
            or any(type(seed) is not int or seed < 0 for seed in bank)
            for bank in context_banks
        )
    ):
        raise ValueError("formal discovery context seed banks are invalid")
    genesis_seed_base = _require_exact_nonnegative_int(
        rng.get("genesis_seed_base"),
        name="rng_contract.genesis_seed_base",
    )
    required_cem = {
        "candidate_budget_per_replicate",
        "covariance_eigenvalue_ceiling",
        "covariance_eigenvalue_floor",
        "elite_count",
        "elite_update_weight",
        "maximum_proposals_per_generation",
        "population_per_generation",
    }
    if set(cem) != required_cem:
        raise ValueError("formal CEM field set mismatch")
    maximum_proposals = _require_exact_nonnegative_int(
        cem["maximum_proposals_per_generation"],
        name="cem.maximum_proposals_per_generation",
    )
    cem_population = _require_exact_nonnegative_int(
        cem["population_per_generation"],
        name="cem.population_per_generation",
    )
    cem_budget = _require_exact_nonnegative_int(
        cem["candidate_budget_per_replicate"],
        name="cem.candidate_budget_per_replicate",
    )
    if cem_population != population or cem_budget != population * generations:
        raise ValueError("formal CEM dimensions differ from discovery")
    if maximum_proposals < population:
        raise ValueError("formal CEM proposal budget is below population")
    return {
        "candidate_seed_banks": candidate_seed_banks,
        "checkpoint_seed": checkpoint_seed,
        "context_banks": context_banks,
        "generations": generations,
        "genesis_seed_base": genesis_seed_base,
        "maximum_proposals": maximum_proposals,
        "population": population,
        "replicates": replicates,
        "stride": stride,
    }


def _cem_state_from_record(record: Any) -> CemState:
    if not isinstance(record, dict) or set(record) != {
        "mean",
        "covariance",
        "update_count",
    }:
        raise ValueError("prior CEM state field set mismatch")
    mean_record = record["mean"]
    covariance = record["covariance"]
    update_count = record["update_count"]
    if not isinstance(mean_record, dict) or set(mean_record) != set(LATENT_NAMES):
        raise ValueError("prior CEM mean field set mismatch")
    if (
        not isinstance(covariance, list)
        or len(covariance) != len(LATENT_NAMES)
        or any(not isinstance(row, list) or len(row) != len(LATENT_NAMES) for row in covariance)
    ):
        raise ValueError("prior CEM covariance shape mismatch")
    if isinstance(update_count, bool) or not isinstance(update_count, int):
        raise TypeError("prior CEM update count is invalid")
    return canonicalize_cem_state(
        CemState(
            mean=tuple(float(mean_record[name]) for name in LATENT_NAMES),
            covariance=tuple(tuple(float(value) for value in row) for row in covariance),
            update_count=update_count,
        )
    )


def _formal_prior_state(
    *,
    protocol: dict[str, Any],
    protocol_sha256: str,
    replicate_index: int,
    generation: int,
    claimed_sha256: Any,
) -> CemState:
    if generation == 0:
        if claimed_sha256 != INITIAL_SEARCH_STATE_SENTINEL:
            raise ValueError("generation zero prior-state sentinel mismatch")
        return canonicalize_cem_state(CemState.initial())
    if not isinstance(claimed_sha256, str) or len(claimed_sha256) != 64:
        raise ValueError("prior search-state SHA256 is invalid")
    independence = protocol.get("independence_from_v3")
    if not isinstance(independence, dict):
        raise TypeError("protocol independence contract is missing")
    root = Path(str(independence.get("output_root"))).expanduser()
    if not root.is_absolute():
        raise ValueError("formal output root must be absolute")
    path = (
        root
        / "discovery"
        / f"replicate-{replicate_index}"
        / f"generation-{generation - 1}"
        / "search-state.json"
    ).resolve()
    if not path.is_file() or sha256_file(path) != claimed_sha256:
        raise ValueError("prior search-state artifact or SHA256 mismatch")
    state_payload = load_strict_json(path)
    if (
        state_payload.get("schema_version") != SEARCH_STATE_SCHEMA_VERSION
        or state_payload.get("protocol_sha256") != protocol_sha256
        or state_payload.get("replicate_index") != replicate_index
        or state_payload.get("generation") != generation - 1
    ):
        raise ValueError("prior search-state identity mismatch")
    if generation == 1:
        expected_parent = INITIAL_SEARCH_STATE_SENTINEL
    else:
        grandparent_path = (
            root
            / "discovery"
            / f"replicate-{replicate_index}"
            / f"generation-{generation - 2}"
            / "search-state.json"
        ).resolve()
        if not grandparent_path.is_file():
            raise ValueError("grandparent search-state artifact is missing")
        expected_parent = sha256_file(grandparent_path)
    if state_payload.get("prior_search_state_sha256") != expected_parent:
        raise ValueError("prior search-state chain is malformed")
    return _cem_state_from_record(state_payload.get("cem_state_after"))


def _validate_formal_discovery_batch(
    payload: dict[str, Any],
    *,
    protocol_sha256: str,
    protocol: dict[str, Any],
) -> list[dict[str, Any]]:
    required = {
        "schema_version",
        "protocol_sha256",
        "phase",
        "algorithm",
        "replicate_index",
        "generation",
        "checkpoint_seed",
        "context_seeds",
        "genesis_seed",
        "candidate_rng_seed",
        "prior_search_state_sha256",
        "candidates",
    }
    if set(payload) != required:
        raise ValueError("formal discovery candidate-batch field set mismatch")
    contract = _formal_discovery_contract(protocol)
    algorithm = payload.get("algorithm")
    if algorithm not in {"cem", "uniform"}:
        raise ValueError("formal discovery algorithm is invalid")
    replicate_index = _require_exact_nonnegative_int(
        payload.get("replicate_index"), name="replicate_index"
    )
    generation = _require_exact_nonnegative_int(payload.get("generation"), name="generation")
    if replicate_index >= contract["replicates"]:
        raise ValueError("formal replicate index is out of range")
    if generation >= contract["generations"]:
        raise ValueError("formal generation is out of range")
    if payload.get("checkpoint_seed") != contract["checkpoint_seed"]:
        raise ValueError("formal discovery checkpoint seed differs from protocol")
    registered_contexts = contract["context_banks"][replicate_index]
    if payload.get("context_seeds") != registered_contexts:
        raise ValueError("formal discovery context seeds differ from protocol")
    expected_genesis = contract["genesis_seed_base"] + 100 * replicate_index + generation
    if payload.get("genesis_seed") != expected_genesis:
        raise ValueError("formal discovery Genesis seed differs from protocol")
    expected_rng_seed = (
        contract["candidate_seed_banks"][algorithm][replicate_index]
        + contract["stride"] * generation
    )
    if payload.get("candidate_rng_seed") != expected_rng_seed:
        raise ValueError("formal candidate RNG seed differs from protocol")
    prior_state = _formal_prior_state(
        protocol=protocol,
        protocol_sha256=protocol_sha256,
        replicate_index=replicate_index,
        generation=generation,
        claimed_sha256=payload.get("prior_search_state_sha256"),
    )
    if algorithm == "uniform" or generation == 0:
        candidates = sample_initial_prior(
            count=contract["population"],
            seed=expected_rng_seed,
        )
    else:
        candidates = sample_cem_candidates(
            count=contract["population"],
            seed=expected_rng_seed,
            state=prior_state,
            maximum_proposals=contract["maximum_proposals"],
        )
    expected_records = [
        canonical_candidate_record(
            candidate,
            algorithm=algorithm,
            replicate_index=replicate_index,
            generation=generation,
            candidate_index=index,
        )
        for index, candidate in enumerate(candidates)
    ]
    if _canonical_json_bytes(payload.get("candidates")) != _canonical_json_bytes(expected_records):
        raise ValueError("formal discovery candidates differ from deterministic replay")
    return expected_records


def _r6_hidden_contract(protocol: dict[str, Any]) -> dict[str, Any]:
    recovery = (
        protocol.get("status") == R6_HIDDEN_RECOVERY_PROTOCOL_STATUS
    )
    confirmation = is_confirmation_protocol(protocol)
    expected_schema = (
        CONFIRMATION_PROTOCOL_SCHEMA_VERSION
        if confirmation
        else (
            R6_HIDDEN_RECOVERY_PROTOCOL_SCHEMA_VERSION
            if recovery
            else R6_HIDDEN_PROTOCOL_SCHEMA_VERSION
        )
    )
    if (
        not is_formal_hidden_protocol(protocol)
        or protocol.get("schema_version") != expected_schema
        or protocol.get("simulation_only") is not True
    ):
        raise ValueError("r6 hidden protocol identity mismatch")
    hidden = protocol.get("hidden_execution")
    source = protocol.get("source_discovery")
    output = protocol.get("output_contract")
    seed_commitment = protocol.get("hidden_seed_commitment")
    if not isinstance(hidden, dict):
        raise TypeError("r6 hidden execution contract is missing")
    if not isinstance(source, dict):
        raise TypeError("r6 source discovery contract is missing")
    if not isinstance(output, dict):
        raise TypeError("r6 output contract is missing")
    if not confirmation and not isinstance(seed_commitment, dict):
        raise TypeError("r6 hidden seed commitment is missing")
    if (
        hidden.get("schema_version")
        != (
            CONFIRMATION_EXECUTION_SCHEMA_VERSION
            if confirmation
            else "flightguard-r6-hidden-execution-v1"
        )
        or hidden.get("candidate_batch_schema_version")
        != FORMAL_HIDDEN_BATCH_SCHEMA_VERSION
        or hidden.get("replicates") != 8
        or hidden.get("checkpoints") != 3
        or hidden.get("algorithms") != ["cem", "uniform"]
        or hidden.get("top_k_per_algorithm") != 4
        or hidden.get("contexts_per_replicate") != 12
        or hidden.get("steps") != 800
        or hidden.get("checkpoint_seeds") != [30, 31, 32]
        or hidden.get("candidate_hidden_outcomes_may_not_update_search") is not True
        or hidden.get("separate_identical_lane_grid_required") is not True
        or (
            not confirmation
            and (
                seed_commitment.get(
                    "decoded_only_after_discovery_seal_sha256_fixed"
                )
                is not True
                or set(seed_commitment)
                != {
                    "sha256",
                    "source_schema_version",
                    "decoded_only_after_discovery_seal_sha256_fixed",
                }
                or seed_commitment.get("source_schema_version")
                != "flightguard-workflow-sealed-hidden-seeds-v1"
                or not isinstance(seed_commitment.get("sha256"), str)
                or len(seed_commitment["sha256"]) != 64
            )
        )
        or (
            confirmation
            and seed_commitment is not None
        )
    ):
        raise ValueError("r6 hidden execution dimensions are downgraded")
    context_banks = hidden.get("context_seed_banks")
    genesis_matrix = hidden.get("genesis_seed_matrix")
    process_orders = hidden.get("process_order_by_replicate_checkpoint")
    if (
        not isinstance(context_banks, list)
        or len(context_banks) != 8
        or any(
            not isinstance(bank, list)
            or len(bank) != 12
            or len(set(bank)) != 12
            or any(type(seed) is not int or seed < 0 for seed in bank)
            for bank in context_banks
        )
        or not isinstance(genesis_matrix, list)
        or len(genesis_matrix) != 8
        or any(
            not isinstance(row, list)
            or len(row) != 3
            or any(type(seed) is not int or seed < 0 for seed in row)
            for row in genesis_matrix
        )
        or not isinstance(process_orders, list)
        or len(process_orders) != 8
        or any(
            not isinstance(row, list)
            or len(row) != 3
            or any(
                order
                != (
                    ["cem", "uniform"]
                    if (replicate_index + checkpoint_index) % 2 == 0
                    else ["uniform", "cem"]
                )
                for checkpoint_index, order in enumerate(row)
            )
            for replicate_index, row in enumerate(process_orders)
        )
    ):
        raise ValueError("r6 hidden seeds or process order are invalid")
    if confirmation:
        from tools.run_lane_aligned_falsifier_hidden import (
            _validate_confirmation_public_entropy,
        )

        _validate_confirmation_public_entropy(protocol, hidden)
    source_protocol = source.get("protocol")
    source_seal = source.get("seal")
    sources = source.get("candidate_sources")
    if (
        not isinstance(source_protocol, dict)
        or set(source_protocol)
        != {"path", "sha256", "version", "status", "output_root"}
        or source_protocol.get("status") != FORMAL_PROTOCOL_STATUS
        or not isinstance(source_protocol.get("sha256"), str)
        or len(source_protocol["sha256"]) != 64
        or not isinstance(source_protocol.get("version"), str)
        or not isinstance(source_seal, dict)
        or set(source_seal)
        != {"path", "sha256", "schema_version", "status"}
        or source_seal.get("status") != "PASS"
        or source_seal.get("schema_version")
        != "flightguard-formal-discovery-seal-v1"
        or not isinstance(source_seal.get("sha256"), str)
        or len(source_seal["sha256"]) != 64
        or not isinstance(sources, list)
        or len(sources) != 8
    ):
        raise ValueError("r6 source discovery binding is invalid")
    source_protocol_path = Path(str(source_protocol["path"])).expanduser()
    source_seal_path = Path(str(source_seal["path"])).expanduser()
    if (
        not source_protocol_path.is_absolute()
        or not source_seal_path.is_absolute()
        or not source_protocol_path.is_file()
        or not source_seal_path.is_file()
        or sha256_file(source_protocol_path) != source_protocol["sha256"]
        or sha256_file(source_seal_path) != source_seal["sha256"]
    ):
        raise ValueError("r6 source protocol or discovery seal bytes mismatch")
    source_protocol_payload = load_strict_json(source_protocol_path)
    source_seal_payload = load_strict_json(source_seal_path)
    source_output_root = Path(str(source_protocol["output_root"])).expanduser()
    if (
        source_protocol_payload.get("status") != source_protocol["status"]
        or source_protocol_payload.get("protocol_version")
        != source_protocol["version"]
        or Path(
            str(
                source_protocol_payload.get("independence_from_v3", {}).get(
                    "output_root"
                )
            )
        )
        .expanduser()
        .resolve()
        != source_output_root.resolve()
        or (
            not confirmation
            and source_protocol_payload.get("hidden_seal", {}).get(
                "seed_blob_sha256"
            )
            != seed_commitment["sha256"]
        )
        or source_seal_payload.get("schema_version")
        != source_seal["schema_version"]
        or source_seal_payload.get("status") != source_seal["status"]
        or source_seal_payload.get("protocol")
        != {
            "path": str(source_protocol_path.resolve()),
            "sha256": source_protocol["sha256"],
            "version": source_protocol["version"],
            "status": source_protocol["status"],
        }
        or (
            not confirmation
            and source_seal_payload.get(
                "hidden_seed_commitment", {}
            ).get("sha256")
            != seed_commitment["sha256"]
        )
    ):
        raise ValueError("r6 source protocol or seal content binding mismatch")
    output_root = Path(str(output.get("output_root"))).expanduser()
    source_root = source_output_root
    if (
        not output_root.is_absolute()
        or not source_root.is_absolute()
        or output_root == source_root
        or output_root.is_relative_to(source_root)
        or source_root.is_relative_to(output_root)
        or output.get("hidden_root") != str(output_root / "hidden")
        or output.get("hidden_summary")
        != str(output_root / "hidden" / "hidden-summary.json")
        or output.get("algorithm_leaf_template")
        != (
            "hidden/replicate-{replicate_index}/checkpoint-"
            "{checkpoint_seed}/{algorithm}"
        )
        or output.get("refuse_output_overwrite") is not True
        or output.get("source_r5_output_root_forbidden")
        != str(source_root.resolve())
    ):
        raise ValueError("r6 output root collides with r5")
    governance = protocol.get("freeze_governance")
    if confirmation:
        from tools.run_lane_aligned_falsifier_hidden import (
            _validate_confirmation_supersession,
        )

        _validate_confirmation_supersession(
            protocol,
            hidden=hidden,
            candidate_sources=sources,
            output_root=output_root.resolve(),
            r5_output_root=source_root.resolve(),
        )
    elif governance != {
        "source_r5_protocol_immutable": True,
        "source_r5_discovery_outputs_immutable": True,
        "hidden_outcomes_seen_before_freeze": recovery,
        "discovery_seal_verified_before_seed_blob_decode": True,
        "new_output_identity_required": True,
    }:
        raise ValueError("r6 hidden freeze governance mismatch")
    recovery_governance = protocol.get("recovery_governance")
    if recovery:
        if not isinstance(recovery_governance, dict):
            raise TypeError("r6 recovery governance is missing")
        incident = recovery_governance.get("incident")
        failed_attempt = recovery_governance.get("failed_attempt")
        if (
            recovery_governance.get("schema_version")
            != "flightguard-r6-hidden-code-recovery-governance-v1"
            or recovery_governance.get("status")
            != "PRE_REGISTERED_CODE_ONLY_RECOVERY_BEFORE_RERUN"
            or recovery_governance.get("partial_candidate_progress_observed")
            is not True
            or recovery_governance.get("paired_primary_outcomes_observed")
            is not False
            or recovery_governance.get("same_seed_code_only_recovery")
            is not True
            or recovery_governance.get("candidate_selection_changed")
            is not False
            or recovery_governance.get("seeds_changed") is not False
            or recovery_governance.get("budgets_changed") is not False
            or recovery_governance.get("claim_gates_changed") is not False
            or recovery_governance.get("controller_or_model_changed")
            is not False
            or not isinstance(incident, dict)
            or set(incident) != {"path", "sha256"}
            or not isinstance(failed_attempt, dict)
            or set(failed_attempt)
            != {
                "protocol",
                "queue_state",
                "job_log",
                "candidate_stdout",
                "candidate_stderr",
            }
        ):
            raise ValueError("r6 recovery governance mismatch")
        incident_path = Path(str(incident.get("path"))).expanduser()
        if (
            not incident_path.is_absolute()
            or not incident_path.is_file()
            or not isinstance(incident.get("sha256"), str)
            or len(incident["sha256"]) != 64
            or sha256_file(incident_path) != incident["sha256"]
        ):
            raise ValueError("r6 recovery incident binding mismatch")
        for name, binding in failed_attempt.items():
            if (
                not isinstance(binding, dict)
                or set(binding) != {"path", "sha256"}
            ):
                raise ValueError(
                    f"r6 recovery failed-attempt binding is invalid: {name}"
                )
            failed_path = Path(str(binding.get("path"))).expanduser()
            if (
                not failed_path.is_absolute()
                or not failed_path.is_file()
                or not isinstance(binding.get("sha256"), str)
                or len(binding["sha256"]) != 64
                or sha256_file(failed_path) != binding["sha256"]
            ):
                raise ValueError(
                    f"r6 recovery failed-attempt bytes mismatch: {name}"
                )
        failed_protocol_path = Path(
            str(failed_attempt["protocol"]["path"])
        ).expanduser()
        failed_protocol = load_strict_json(failed_protocol_path)
        failed_output = failed_protocol.get("output_contract")
        if not isinstance(failed_output, dict):
            raise TypeError("failed r6 output contract is missing")
        failed_output_root = Path(
            str(failed_output.get("output_root"))
        ).expanduser().resolve()
        if (
            failed_protocol.get("status") != R6_HIDDEN_PROTOCOL_STATUS
            or failed_protocol.get("protocol_version")
            != R6_HIDDEN_PROTOCOL_VERSION
            or _canonical_json_bytes(
                failed_protocol.get("hidden_execution")
            )
            != _canonical_json_bytes(hidden)
            or _canonical_json_bytes(
                failed_protocol.get("source_discovery", {}).get(
                    "candidate_sources"
                )
            )
            != _canonical_json_bytes(sources)
            or output_root == failed_output_root
            or output_root.is_relative_to(failed_output_root)
            or failed_output_root.is_relative_to(output_root)
        ):
            raise ValueError(
                "r6 recovery does not preserve the failed protocol identity"
            )
    elif recovery_governance is not None:
        raise ValueError("pristine r6 protocol forbids recovery governance")
    return {
        "context_banks": context_banks,
        "genesis_matrix": genesis_matrix,
        "process_orders": process_orders,
        "checkpoint_seeds": hidden["checkpoint_seeds"],
        "sources": sources,
        "source_seal_sha256": source_seal["sha256"],
        "source_protocol": source_protocol_payload,
        "source_seal": source_seal_payload,
    }


def validate_formal_hidden_batch(
    payload: dict[str, Any],
    *,
    protocol_sha256: str,
    protocol: dict[str, Any],
) -> list[dict[str, Any]]:
    required = {
        "schema_version",
        "protocol_sha256",
        "phase",
        "algorithm",
        "replicate_index",
        "checkpoint_index",
        "checkpoint_seed",
        "context_seeds",
        "genesis_seed",
        "discovery_seal_sha256",
        "discovery_campaign_sha256",
        "candidate_source_manifest_sha256",
        "candidates",
    }
    if set(payload) != required:
        raise ValueError("r6 hidden candidate-batch field set mismatch")
    if (
        payload.get("schema_version") != FORMAL_HIDDEN_BATCH_SCHEMA_VERSION
        or payload.get("protocol_sha256") != protocol_sha256
        or payload.get("phase") != "hidden"
    ):
        raise ValueError("r6 hidden candidate-batch header mismatch")
    contract = _r6_hidden_contract(protocol)
    algorithm = payload.get("algorithm")
    if algorithm not in {"cem", "uniform"}:
        raise ValueError("r6 hidden algorithm is invalid")
    replicate_index = _require_exact_nonnegative_int(
        payload.get("replicate_index"),
        name="replicate_index",
    )
    checkpoint_index = _require_exact_nonnegative_int(
        payload.get("checkpoint_index"),
        name="checkpoint_index",
    )
    if replicate_index >= 8 or checkpoint_index >= 3:
        raise ValueError("r6 hidden replicate/checkpoint index is out of range")
    if (
        payload.get("checkpoint_seed")
        != contract["checkpoint_seeds"][checkpoint_index]
        or payload.get("context_seeds")
        != contract["context_banks"][replicate_index]
        or payload.get("genesis_seed")
        != contract["genesis_matrix"][replicate_index][checkpoint_index]
        or payload.get("discovery_seal_sha256")
        != contract["source_seal_sha256"]
    ):
        raise ValueError("r6 hidden registered seed or seal binding mismatch")
    replicate_manifest = contract["sources"][replicate_index]
    campaign_binding = (
        replicate_manifest.get("campaign")
        if isinstance(replicate_manifest, dict)
        else None
    )
    if (
        not isinstance(replicate_manifest, dict)
        or set(replicate_manifest)
        != {"replicate_index", "campaign", "algorithms"}
        or replicate_manifest.get("replicate_index") != replicate_index
        or not isinstance(campaign_binding, dict)
        or set(campaign_binding) != {"path", "sha256"}
        or payload.get("discovery_campaign_sha256")
        != campaign_binding.get("sha256")
        or not isinstance(replicate_manifest.get("algorithms"), dict)
        or set(replicate_manifest["algorithms"]) != {"cem", "uniform"}
    ):
        raise ValueError("r6 hidden source campaign binding mismatch")
    source_protocol_binding = protocol["source_discovery"]["protocol"]
    campaign_path = Path(str(campaign_binding["path"])).expanduser()
    expected_campaign_path = (
        Path(str(source_protocol_binding["output_root"])).expanduser()
        / "discovery"
        / f"replicate-{replicate_index}"
        / "campaign.json"
    ).resolve()
    if (
        not campaign_path.is_absolute()
        or campaign_path.resolve() != expected_campaign_path
        or not campaign_path.is_file()
        or sha256_file(campaign_path) != campaign_binding["sha256"]
    ):
        raise ValueError("r6 hidden source campaign bytes mismatch")
    campaign_payload = load_strict_json(campaign_path)
    selection = campaign_payload.get("hidden_selection")
    if (
        campaign_payload.get("status") != "PASS"
        or campaign_payload.get("replicate_index") != replicate_index
        or campaign_payload.get("protocol")
        != {
            "path": str(
                Path(str(source_protocol_binding["path"])).expanduser().resolve()
            ),
            "sha256": source_protocol_binding["sha256"],
            "version": source_protocol_binding["version"],
        }
        or not isinstance(selection, dict)
        or set(selection) != {"cem", "uniform"}
    ):
        raise ValueError("r6 hidden source campaign content mismatch")
    manifests = replicate_manifest["algorithms"].get(algorithm)
    source_summaries = selection.get(algorithm)
    if (
        not isinstance(manifests, list)
        or len(manifests) != 4
        or not isinstance(source_summaries, list)
        or len(source_summaries) != 4
    ):
        raise ValueError("r6 hidden source manifest count mismatch")
    expected_manifest_sha256 = [
        manifest.get("manifest_sha256")
        if isinstance(manifest, dict)
        else None
        for manifest in manifests
    ]
    if payload.get("candidate_source_manifest_sha256") != expected_manifest_sha256:
        raise ValueError("r6 hidden source manifest list binding mismatch")
    expected_records = []
    for local_index, manifest in enumerate(manifests):
        source_summary = source_summaries[local_index]
        if not isinstance(manifest, dict) or set(manifest) != {
            "local_candidate_index",
            "source_summary_sha256",
            "source_candidate",
            "hidden_candidate_record",
            "manifest_sha256",
        } or not isinstance(source_summary, dict):
            raise ValueError("r6 hidden source manifest field set mismatch")
        manifest_without_sha = {
            key: value for key, value in manifest.items() if key != "manifest_sha256"
        }
        manifest_sha256 = hashlib.sha256(
            _canonical_json_bytes(manifest_without_sha)
        ).hexdigest()
        if (
            manifest.get("local_candidate_index") != local_index
            or manifest.get("manifest_sha256") != manifest_sha256
            or manifest.get("source_summary_sha256")
            != hashlib.sha256(_canonical_json_bytes(source_summary)).hexdigest()
        ):
            raise ValueError("r6 hidden source manifest SHA/index mismatch")
        source_candidate = manifest.get("source_candidate")
        if not isinstance(source_candidate, dict):
            raise TypeError("r6 hidden source candidate is missing")
        latent = source_candidate.get("latent")
        if not isinstance(latent, dict) or set(latent) != set(LATENT_NAMES):
            raise ValueError("r6 hidden source latent field set mismatch")
        source_generation = _require_exact_nonnegative_int(
            source_candidate.get("generation"),
            name="source generation",
        )
        source_candidate_index = _require_exact_nonnegative_int(
            source_candidate.get("candidate_index"),
            name="source candidate index",
        )
        if (
            source_candidate.get("algorithm") != algorithm
            or source_candidate.get("replicate_index") != replicate_index
        ):
            raise ValueError("r6 hidden source candidate identity mismatch")
        candidate = canonical_fault_candidate(
            tuple(float(latent[name]) for name in LATENT_NAMES)
        )
        expected_source = canonical_candidate_record(
            candidate,
            algorithm=algorithm,
            replicate_index=replicate_index,
            generation=source_generation,
            candidate_index=source_candidate_index,
        )
        if _canonical_json_bytes(source_candidate) != _canonical_json_bytes(
            expected_source
        ) or (
            source_summary.get("candidate_id")
            != source_candidate["candidate_id"]
            or source_summary.get("fault_burden")
            != source_candidate["fault_burden"]
            or _canonical_json_bytes(source_summary.get("candidate"))
            != _canonical_json_bytes(source_candidate)
        ):
            raise ValueError(
                "r6 hidden source latent/scheduled/ID/burden mismatch"
            )
        provenance = {
            "source_campaign_sha256": payload[
                "discovery_campaign_sha256"
            ],
            "source_candidate_id": source_candidate["candidate_id"],
            "source_candidate_index": source_candidate_index,
            "source_generation": source_generation,
            "source_summary_sha256": manifest["source_summary_sha256"],
        }
        expected_hidden = canonical_candidate_record(
            candidate,
            algorithm=algorithm,
            replicate_index=replicate_index,
            generation=source_generation,
            candidate_index=local_index,
        )
        expected_hidden["source_discovery"] = provenance
        if _canonical_json_bytes(
            manifest.get("hidden_candidate_record")
        ) != _canonical_json_bytes(expected_hidden):
            raise ValueError("r6 hidden candidate source provenance mismatch")
        expected_records.append(expected_hidden)
    if _canonical_json_bytes(payload.get("candidates")) != _canonical_json_bytes(
        expected_records
    ):
        raise ValueError("r6 hidden candidates differ from frozen source manifests")
    return expected_records


def validate_candidate_batch(
    payload: dict[str, Any],
    *,
    protocol_sha256: str,
    protocol: dict[str, Any],
) -> tuple[list[dict[str, Any]], list[int], int, str, str | None]:
    r6_hidden = is_formal_hidden_protocol(protocol)
    expected_schema = (
        FORMAL_HIDDEN_BATCH_SCHEMA_VERSION
        if r6_hidden
        else CANDIDATE_SCHEMA_VERSION
    )
    if payload.get("schema_version") != expected_schema:
        raise ValueError("candidate batch schema mismatch")
    if payload.get("protocol_sha256") != protocol_sha256:
        raise ValueError("candidate batch protocol SHA256 mismatch")
    genesis_seed = payload.get("genesis_seed")
    if isinstance(genesis_seed, bool) or not isinstance(genesis_seed, int) or genesis_seed < 0:
        raise ValueError("genesis_seed is invalid")
    checkpoint_seed = payload.get("checkpoint_seed")
    if (
        isinstance(checkpoint_seed, bool)
        or not isinstance(checkpoint_seed, int)
        or checkpoint_seed < 0
    ):
        raise ValueError("checkpoint_seed is invalid")
    phase = payload.get("phase")
    if phase not in {"structural", "discovery", "hidden", "replay"}:
        raise ValueError("candidate batch phase is invalid")
    formal_batch_keys = {
        "algorithm",
        "candidate_rng_seed",
        "prior_search_state_sha256",
    }
    if (
        phase == "discovery"
        and formal_batch_keys.intersection(payload)
        and protocol.get("status") != FORMAL_PROTOCOL_STATUS
    ):
        raise ValueError("formal discovery batch requires the formal frozen status")
    structural_gate = payload.get("structural_gate")
    if phase == "structural":
        if structural_gate not in {
            "exact_noop",
            "kill_magnitude",
            "lane_interference",
        }:
            raise ValueError("structural candidate batch gate is invalid")
    elif structural_gate is not None:
        raise ValueError("structural_gate is forbidden outside the structural phase")
    context_seeds = payload.get("context_seeds")
    if (
        not isinstance(context_seeds, list)
        or not context_seeds
        or len(set(context_seeds)) != len(context_seeds)
        or any(
            isinstance(seed, bool) or not isinstance(seed, int) or seed < 0
            for seed in context_seeds
        )
    ):
        raise ValueError("context_seeds must be unique non-negative integers")
    candidates = payload.get("candidates")
    if not isinstance(candidates, list) or not candidates:
        raise ValueError("candidate batch must contain candidates")
    if protocol.get("status") == FORMAL_PROTOCOL_STATUS:
        if phase != "discovery":
            raise ValueError(
                "formal hidden/replay candidate validation is not implemented; "
                "fail closed before execution"
            )
        _validate_formal_discovery_batch(
            payload,
            protocol_sha256=protocol_sha256,
            protocol=protocol,
        )
    elif r6_hidden:
        if phase != "hidden":
            raise ValueError("r6 protocol permits only hidden candidate batches")
        validate_formal_hidden_batch(
            payload,
            protocol_sha256=protocol_sha256,
            protocol=protocol,
        )
    if phase == "structural":
        expected_records = canonical_structural_candidate_records(str(structural_gate))
        if _canonical_json_bytes(candidates) != _canonical_json_bytes(expected_records):
            raise ValueError(f"{structural_gate} candidates differ from the canonical protocol set")
    validated: list[dict[str, Any]] = []
    for index, record in enumerate(candidates):
        if not isinstance(record, dict):
            raise TypeError(f"candidate {index} must be an object")
        algorithm = record.get("algorithm")
        if algorithm not in {"cem", "uniform", "structural"}:
            raise ValueError(f"candidate {index} algorithm is invalid")
        scheduled = record.get("scheduled")
        if not isinstance(scheduled, dict):
            raise TypeError(f"candidate {index} scheduled fault is missing")
        thrust_scale = float(scheduled.get("thrust_scale"))
        wind_values = scheduled.get("wind_acceleration_mps2")
        delay = scheduled.get("action_delay_steps")
        if not math.isfinite(thrust_scale) or not 0.93 <= thrust_scale <= 1.0:
            raise ValueError(f"candidate {index} thrust scale is out of bounds")
        if (
            not isinstance(wind_values, list)
            or len(wind_values) != 3
            or not all(
                isinstance(value, (int, float))
                and not isinstance(value, bool)
                and math.isfinite(float(value))
                for value in wind_values
            )
        ):
            raise ValueError(f"candidate {index} wind vector is invalid")
        wind = tuple(float(value) for value in wind_values)
        if math.hypot(wind[0], wind[1]) > 0.60 + 1.0e-9:
            raise ValueError(f"candidate {index} horizontal wind is out of bounds")
        if not -0.20 <= wind[2] <= 0.20:
            raise ValueError(f"candidate {index} vertical wind is out of bounds")
        if isinstance(delay, bool) or not isinstance(delay, int) or not 0 <= delay <= 6:
            raise ValueError(f"candidate {index} delay is out of bounds")
        candidate_id = canonical_candidate_id(
            thrust_scale=thrust_scale,
            wind_acceleration_mps2=wind,
            action_delay_steps=delay,
        )
        if record.get("candidate_id") != candidate_id:
            raise ValueError(f"candidate {index} ID does not bind decoded fault")
        validated.append(
            {
                **record,
                "scheduled": {
                    "thrust_scale": thrust_scale,
                    "wind_acceleration_mps2": list(wind),
                    "action_delay_steps": delay,
                },
            }
        )
    if phase == "structural":
        structural_gates = protocol.get("structural_gates")
        if not isinstance(structural_gates, dict):
            raise TypeError("protocol structural gates are missing")
        registered_gate = structural_gates.get(str(structural_gate))
        if not isinstance(registered_gate, dict):
            raise TypeError("registered structural gate is missing")
        registered_context_seeds = registered_gate.get("context_seeds")
        registered_genesis_seed = registered_gate.get("genesis_seed")
        registered_checkpoint_seed = registered_gate.get("checkpoint_seed")
        if (
            not isinstance(registered_context_seeds, list)
            or not registered_context_seeds
            or any(type(seed) is not int for seed in registered_context_seeds)
            or type(registered_genesis_seed) is not int
            or type(registered_checkpoint_seed) is not int
        ):
            raise TypeError("registered structural seeds must be exact integers")
        if context_seeds != registered_context_seeds:
            raise ValueError("structural context seeds differ from protocol")
        if genesis_seed != registered_genesis_seed:
            raise ValueError("structural Genesis seed differs from protocol")
        if checkpoint_seed != registered_checkpoint_seed:
            raise ValueError("structural checkpoint seed differs from protocol")
        if any(candidate["algorithm"] != "structural" for candidate in validated):
            raise ValueError("structural batches may contain only structural candidates")
    return validated, context_seeds, checkpoint_seed, phase, structural_gate


def load_model(
    checkpoint_path: Path,
    device: torch.device,
) -> torch.nn.Module:
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
    config_values = dict(payload["model_config"])
    if "hidden_sizes" in config_values:
        config_values["hidden_sizes"] = tuple(config_values["hidden_sizes"])
    model = FlightDynamicsModel(DynamicsConfig(**config_values)).to(device)
    model.load_state_dict(payload["model_state_dict"], strict=True)
    model.eval()
    return model


def context_noise(
    context_seeds: list[int],
    *,
    steps: int,
    attitude_std_rad: float,
    angular_velocity_std_rad_s: float,
) -> tuple[torch.Tensor, torch.Tensor]:
    attitude = torch.empty((steps, len(context_seeds), 3), device="cpu")
    angular_velocity = torch.empty_like(attitude)
    for context_index, context_seed in enumerate(context_seeds):
        generator = torch.Generator(device="cpu")
        generator.manual_seed(context_seed + 1_000_003)
        attitude[:, context_index] = (
            torch.randn((steps, 3), generator=generator, device="cpu") * attitude_std_rad
        )
        angular_velocity[:, context_index] = (
            torch.randn((steps, 3), generator=generator, device="cpu") * angular_velocity_std_rad_s
        )
    return attitude, angular_velocity


def context_gate_offsets(
    context_seeds: list[int],
    *,
    y_jitter_m: float,
    z_jitter_m: float,
) -> torch.Tensor:
    offsets = torch.zeros((len(context_seeds), 3), device="cpu")
    for context_index, context_seed in enumerate(context_seeds):
        generator = torch.Generator(device="cpu")
        generator.manual_seed(context_seed)
        unit = torch.rand((2,), generator=generator, device="cpu") * 2.0 - 1.0
        offsets[context_index, 1] = unit[0] * y_jitter_m
        offsets[context_index, 2] = unit[1] * z_jitter_m
    return offsets


def repeat_contexts(values: torch.Tensor, *, groups: int) -> torch.Tensor:
    if values.ndim == 0 or groups <= 0:
        raise ValueError("context values and group count are invalid")
    return torch.cat([values] * groups, dim=0)


def grouped_pair_max(values: torch.Tensor, *, contexts: int) -> float:
    if values.shape[0] % contexts:
        raise ValueError("tensor batch is not divisible by context count")
    grouped = values.reshape(
        values.shape[0] // contexts,
        contexts,
        *values.shape[1:],
    )
    return float(torch.abs(grouped - grouped[-1:]).max().item())


def validate_paired_execution_contract(
    protocol: dict[str, Any],
    *,
    lane_role: str,
) -> dict[str, Any] | None:
    if lane_role == "legacy":
        if protocol.get("status") != LEGACY_PROTOCOL_STATUS:
            raise ValueError("legacy causal falsifier protocol is not frozen")
        if "paired_execution" in protocol:
            raise ValueError("legacy execution forbids a paired_execution contract")
        return None
    if lane_role not in PAIRED_LANE_ROLES:
        raise ValueError("invalid paired lane role")
    if protocol.get("status") not in {
        PAIRED_PROTOCOL_STATUS,
        FORMAL_PROTOCOL_STATUS,
        R6_HIDDEN_PROTOCOL_STATUS,
        R6_HIDDEN_RECOVERY_PROTOCOL_STATUS,
        CONFIRMATION_PROTOCOL_STATUS,
    }:
        raise ValueError("paired causal falsifier protocol is not frozen")
    contract = protocol.get("paired_execution")
    required = {
        "schema_version",
        "candidate_pass_filename",
        "nominal_pass_filename",
        "paired_result_filename",
        "protocol_max_action_delay_steps",
        "same_batch_shape",
        "same_row_order",
        "same_seed",
        "same_physical_lane",
        "all_nominal_raw_bit_exact_required",
    }
    if not isinstance(contract, dict) or set(contract) != required:
        raise ValueError("paired_execution field set mismatch")
    if (
        contract["schema_version"] != PAIRED_EXECUTION_SCHEMA_VERSION
        or contract["candidate_pass_filename"] != "candidate-pass.json"
        or contract["nominal_pass_filename"] != "nominal-pass.json"
        or contract["paired_result_filename"] != "paired.json"
        or contract["protocol_max_action_delay_steps"] != 6
        or any(
            contract[field] is not True
            for field in (
                "same_batch_shape",
                "same_row_order",
                "same_seed",
                "same_physical_lane",
                "all_nominal_raw_bit_exact_required",
            )
        )
    ):
        raise ValueError("paired_execution contract mismatch")
    return contract


def scheduled_fault_values(
    candidates: list[dict[str, Any]],
    context_seeds: list[int],
    *,
    lane_role: str,
) -> tuple[list[float], list[list[float]], list[int]]:
    if lane_role not in {"legacy", *PAIRED_LANE_ROLES}:
        raise ValueError("invalid lane role")
    contexts = len(context_seeds)
    if lane_role == "nominal":
        thrust = [1.0] * (len(candidates) * contexts)
        wind = [[0.0, 0.0, 0.0] for _ in range(len(candidates) * contexts)]
        delay = [0] * (len(candidates) * contexts)
    else:
        thrust = [
            candidate["scheduled"]["thrust_scale"]
            for candidate in candidates
            for _ in context_seeds
        ]
        wind = [
            candidate["scheduled"]["wind_acceleration_mps2"]
            for candidate in candidates
            for _ in context_seeds
        ]
        delay = [
            candidate["scheduled"]["action_delay_steps"]
            for candidate in candidates
            for _ in context_seeds
        ]
    if lane_role == "legacy":
        thrust += [1.0] * contexts
        wind += [[0.0, 0.0, 0.0] for _ in context_seeds]
        delay += [0] * contexts
    return thrust, wind, delay


def pre_activation_lane_digests(
    trace: dict[str, torch.Tensor],
) -> dict[str, Any]:
    if set(trace) != set(TRACKED_FIELDS):
        raise ValueError("pre-activation trace field set mismatch")
    first = trace[TRACKED_FIELDS[0]]
    if first.ndim != 3 or first.dtype != torch.float32:
        raise ValueError("pre-activation trace must be step-lane-component float32")
    steps, lanes = first.shape[:2]
    field_lane_sha256: dict[str, list[str]] = {}
    aggregate = [hashlib.sha256() for _ in range(lanes)]
    for field in TRACKED_FIELDS:
        values = trace[field]
        expected_components = (
            4
            if field
            in {
                "truth_quaternion",
                "measured_quaternion",
                "issued_action",
                "applied_action",
            }
            else 3
        )
        if (
            values.shape != (steps, lanes, expected_components)
            or values.dtype != torch.float32
            or not bool(torch.isfinite(values).all())
        ):
            raise ValueError(f"invalid pre-activation trace tensor: {field}")
        lane_major = values.permute(1, 0, 2).contiguous().cpu().numpy()
        digests: list[str] = []
        header = json.dumps(
            {
                "components": expected_components,
                "dtype": "float32-little-endian",
                "field": field,
                "layout": "step_component_c_order",
                "steps": steps,
            },
            allow_nan=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode()
        for lane in range(lanes):
            field_digest = hashlib.sha256()
            field_digest.update(header)
            field_digest.update(b"\0")
            field_digest.update(lane_major[lane].tobytes(order="C"))
            digest = field_digest.hexdigest()
            digests.append(digest)
            aggregate[lane].update(field.encode())
            aggregate[lane].update(b"\0")
            aggregate[lane].update(bytes.fromhex(digest))
        field_lane_sha256[field] = digests
    return {
        "schema_version": "flightguard-pre-activation-lane-digest-v1",
        "layout": "candidate_major_context_minor",
        "steps": steps,
        "lanes": lanes,
        "tracked_fields": list(TRACKED_FIELDS),
        "field_lane_sha256": field_lane_sha256,
        "lane_sha256": [digest.hexdigest() for digest in aggregate],
    }


def full_trajectory_lane_digests(
    float_trace: dict[str, torch.Tensor],
    discrete_trace: dict[str, torch.Tensor],
    *,
    candidates: list[dict[str, Any]],
    context_seeds: list[int],
) -> dict[str, Any]:
    """Compactly bind every typed value in an all-nominal trajectory."""

    if sys.byteorder != "little":
        raise RuntimeError("trajectory digest requires a little-endian host")
    if set(float_trace) != set(TRACKED_FIELDS):
        raise ValueError("full trajectory float field set mismatch")
    if set(discrete_trace) != set(DISCRETE_TRACE_FIELDS):
        raise ValueError("full trajectory discrete field set mismatch")
    first = float_trace[TRACKED_FIELDS[0]]
    if first.ndim != 3 or first.dtype != torch.float32:
        raise ValueError("full trajectory must be step-lane-component float32")
    steps, lanes = first.shape[:2]
    if lanes != len(candidates) * len(context_seeds):
        raise ValueError("full trajectory lane count differs from candidate/context product")

    aggregate = [hashlib.sha256() for _ in range(lanes)]
    field_lane_sha256: dict[str, list[str]] = {}
    for field in TRACKED_FIELDS:
        values = float_trace[field]
        components = (
            4
            if field
            in {
                "truth_quaternion",
                "measured_quaternion",
                "issued_action",
                "applied_action",
            }
            else 3
        )
        if (
            values.shape != (steps, lanes, components)
            or values.dtype != torch.float32
            or not bool(torch.isfinite(values).all())
        ):
            raise ValueError(f"invalid full trajectory tensor: {field}")
        lane_major = (
            values.permute(1, 0, 2).contiguous().cpu().numpy().astype(np.dtype("<f4"), copy=False)
        )
        header = _canonical_json_bytes(
            {
                "components": components,
                "dtype": "float32-little-endian",
                "field": field,
                "layout": "step_component_c_order",
                "steps": steps,
            }
        )
        digests = []
        for lane in range(lanes):
            raw = lane_major[lane].tobytes(order="C")
            digest = hashlib.sha256(header + b"\0" + raw).hexdigest()
            digests.append(digest)
            aggregate[lane].update(field.encode())
            aggregate[lane].update(b"\0")
            aggregate[lane].update(bytes.fromhex(digest))
        field_lane_sha256[field] = digests

    discrete_numpy: dict[str, np.ndarray] = {}
    for field in DISCRETE_TRACE_FIELDS:
        values = discrete_trace[field]
        expected_dtype = torch.long if field == "gates_passed_after_step" else torch.bool
        if values.shape != (steps, lanes) or values.dtype != expected_dtype:
            raise ValueError(f"invalid full trajectory discrete tensor: {field}")
        if expected_dtype == torch.bool:
            lane_major = (
                values.permute(1, 0).contiguous().cpu().numpy().astype(np.dtype("u1"), copy=False)
            )
            dtype_name = "bool-uint8"
        else:
            if bool((values < 0).any()):
                raise ValueError("full trajectory gate counts must be non-negative")
            lane_major = (
                values.permute(1, 0).contiguous().cpu().numpy().astype(np.dtype("<i8"), copy=False)
            )
            dtype_name = "int64-little-endian"
        discrete_numpy[field] = lane_major
        header = _canonical_json_bytes(
            {
                "dtype": dtype_name,
                "field": field,
                "layout": "step_c_order",
                "steps": steps,
            }
        )
        digests = []
        for lane in range(lanes):
            raw = lane_major[lane].tobytes(order="C")
            digest = hashlib.sha256(header + b"\0" + raw).hexdigest()
            digests.append(digest)
            aggregate[lane].update(field.encode())
            aggregate[lane].update(b"\0")
            aggregate[lane].update(bytes.fromhex(digest))
        field_lane_sha256[field] = digests

    lifecycle = []
    for lane in range(lanes):
        terminal = discrete_numpy["terminal_after_step"][lane].astype(np.bool_, copy=False)
        terminal_indices = np.flatnonzero(terminal)
        lifecycle.append(
            {
                "active_control_steps": int(discrete_numpy["active_before_step"][lane].sum()),
                "first_terminal_step": (
                    int(terminal_indices[0]) + 1 if terminal_indices.size else None
                ),
                "terminal_after_final_step": bool(terminal[-1]),
                "success_after_final_step": bool(discrete_numpy["success_after_step"][lane, -1]),
                "gates_passed_after_final_step": int(
                    discrete_numpy["gates_passed_after_step"][lane, -1]
                ),
            }
        )
    return {
        "schema_version": FULL_TRAJECTORY_DIGEST_SCHEMA_VERSION,
        "layout": "candidate_major_context_minor",
        "steps": steps,
        "lanes": lanes,
        "float_fields": list(TRACKED_FIELDS),
        "discrete_fields": list(DISCRETE_TRACE_FIELDS),
        "environment_order": [
            {
                "candidate_index": candidate_index,
                "context_seed": context_seed,
            }
            for candidate_index, _candidate in enumerate(candidates)
            for context_seed in context_seeds
        ],
        "field_lane_sha256": field_lane_sha256,
        "lane_sha256": [digest.hexdigest() for digest in aggregate],
        "lifecycle_terminal_metadata": lifecycle,
    }


def indexed_gate(
    gates: torch.Tensor,
    gate_yaws: torch.Tensor,
    gate_index: torch.Tensor,
) -> tuple[torch.Tensor, torch.Tensor]:
    env_index = torch.arange(gates.shape[0], device=gates.device)
    clamped = gate_index.clamp(min=0, max=gates.shape[1] - 1)
    return gates[env_index, clamped], gate_yaws[env_index, clamped]


def finite_by_environment(values: torch.Tensor) -> torch.Tensor:
    return torch.isfinite(values).reshape(values.shape[0], -1).all(dim=1)


def audit_policy_information_boundary(
    *,
    controller: Any,
    context: Any,
    context_summary: dict[str, Any],
) -> dict[str, Any]:
    """Derive anti-leakage checks from the live policy API and state surface."""

    controller_parameters = list(inspect.signature(controller.__call__).parameters)
    context_parameters = list(inspect.signature(context.predict_acceleration).parameters)
    expected_controller_parameters = [
        "position",
        "quaternion",
        "velocity",
        "angular_velocity",
        "target",
    ]
    expected_context_parameters = [
        "model",
        "velocity",
        "quaternion",
        "angular_velocity",
    ]
    state_names = set(vars(context))
    state_names.update(dir(context))
    named_buffers = getattr(context, "named_buffers", None)
    if callable(named_buffers):
        state_names.update(name for name, _value in named_buffers())
    normalized_state_names = sorted(name.lower() for name in state_names)
    fault_fragments = ("fault", "scheduled", "thrust_scale", "wind_acceleration")
    domain_fragments = ("domain", "stratum", "mass_scale")
    applied_fragments = ("last_applied_action", "applied_action")

    controller_api_exact = controller_parameters == expected_controller_parameters
    context_api_exact = context_parameters == expected_context_parameters
    state_has_fault = any(
        fragment in name for name in normalized_state_names for fragment in fault_fragments
    )
    state_has_domain = any(
        fragment in name for name in normalized_state_names for fragment in domain_fragments
    )
    state_has_applied_action = any(
        fragment in name for name in normalized_state_names for fragment in applied_fragments
    )
    uses_last_applied_action = context_summary.get("uses_last_applied_action")
    evidence = {
        "controller_call_parameters": controller_parameters,
        "expected_controller_call_parameters": expected_controller_parameters,
        "context_predict_parameters": context_parameters,
        "expected_context_predict_parameters": expected_context_parameters,
        "context_state_names": normalized_state_names,
        "context_summary_uses_last_applied_action": uses_last_applied_action,
        "controller_api_exact": controller_api_exact,
        "context_api_exact": context_api_exact,
        "context_state_has_fault_parameter": state_has_fault,
        "context_state_has_domain_label": state_has_domain,
        "context_state_has_applied_action": state_has_applied_action,
    }
    evidence["policy_received_no_fault_parameters"] = bool(
        controller_api_exact and context_api_exact and not state_has_fault
    )
    evidence["policy_received_no_domain_labels"] = bool(
        controller_api_exact and context_api_exact and not state_has_domain
    )
    evidence["policy_did_not_use_last_applied_action_after_freeze"] = bool(
        context_api_exact and not state_has_applied_action and uses_last_applied_action is False
    )
    return evidence


def main() -> None:
    args = parse_args()
    lane_role = args.lane_role
    protocol_path = args.protocol.expanduser().resolve()
    output_path = args.output.expanduser().resolve()
    protocol = load_strict_json(protocol_path)
    if protocol.get("phase") == ONE_MINIMAL_V2_PHASE:
        if (
            args.candidate_batch is not None
            or args.lane_evidence is None
            or args.checkpoint_seed is None
            or args.arm_id is None
            or lane_role not in PAIRED_LANE_ROLES
        ):
            raise ValueError(
                "one-minimal v2 CPU assembly requires --lane-evidence, "
                "--checkpoint-seed, --arm-id, and candidate/nominal --lane-role; "
                "--candidate-batch is forbidden"
            )
        evidence_path = args.lane_evidence.expanduser().resolve()
        protected = {protocol_path, evidence_path}
        if output_path in protected:
            raise ValueError("--output must not overwrite an input")
        if output_path.exists():
            raise FileExistsError(f"refusing to overwrite output: {output_path}")
        expected_output = one_minimal_v2_pass_path(
            protocol,
            checkpoint_seed=args.checkpoint_seed,
            arm_id=args.arm_id,
            lane_role=lane_role,
        )
        if output_path != expected_output:
            raise ValueError(
                "one-minimal v2 pass output differs from its deterministic artifact slot"
            )
        evidence = load_strict_json(evidence_path)
        if set(evidence) != {"schema_version", "lanes"} or evidence.get(
            "schema_version"
        ) != ONE_MINIMAL_V2_LANE_EVIDENCE_SCHEMA_VERSION:
            raise ValueError("one-minimal v2 lane evidence header mismatch")
        lanes = evidence.get("lanes")
        if not isinstance(lanes, list):
            raise TypeError("one-minimal v2 lane evidence must contain a lane list")
        payload = build_one_minimal_v2_pass(
            protocol_path=protocol_path,
            checkpoint_seed=args.checkpoint_seed,
            arm_id=args.arm_id,
            lane_role=lane_role,
            lane_evidence=lanes,
        )
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(
            json.dumps(payload, allow_nan=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        print(
            json.dumps(
                {
                    "event": "one_minimal_v2_pass_assembled",
                    "status": "PASS",
                    "output": str(output_path),
                    "lane_count": len(lanes),
                },
                sort_keys=True,
            ),
            flush=True,
        )
        return
    if args.candidate_batch is None:
        raise ValueError("--candidate-batch is required outside one_minimal_v2")
    if (
        args.lane_evidence is not None
        or args.checkpoint_seed is not None
        or args.arm_id is not None
    ):
        raise ValueError("one-minimal v2 CPU assembly options are forbidden for this protocol")
    candidate_path = args.candidate_batch.expanduser().resolve()
    if torch is None:
        raise RuntimeError("PyTorch is required for GPU causal-falsifier evaluation")
    from flightguard.imu import perturb_imu

    protected = {protocol_path, candidate_path}
    if output_path in protected:
        raise ValueError("--output must not overwrite an input")
    if output_path.exists():
        raise FileExistsError(f"refusing to overwrite output: {output_path}")

    protocol_sha256 = sha256_file(protocol_path)
    if (
        is_formal_hidden_protocol(protocol)
        and protocol.get("protocol_filename") != protocol_path.name
    ):
        raise ValueError("r6 protocol filename binding mismatch")
    paired_execution = validate_paired_execution_contract(
        protocol,
        lane_role=lane_role,
    )
    project_root = Path(__file__).resolve().parent.parent
    implementation_files_sha256 = verify_implementation_contract(
        protocol,
        project_root=project_root,
    )
    candidate_payload = load_strict_json(candidate_path)
    candidates, context_seeds, checkpoint_seed, phase, structural_gate = validate_candidate_batch(
        candidate_payload,
        protocol_sha256=protocol_sha256,
        protocol=protocol,
    )
    if phase == "structural":
        require_registered_output_path(
            protocol,
            candidate_path,
            "structural",
            str(structural_gate),
            "candidates.json",
        )
        require_registered_output_path(
            protocol,
            output_path,
            "structural",
            str(structural_gate),
            (
                "metrics.json"
                if paired_execution is None
                else paired_execution[f"{lane_role}_pass_filename"]
            ),
        )
    elif phase == "discovery":
        replicate_index = int(candidate_payload["replicate_index"])
        generation = int(candidate_payload["generation"])
        relative = [
            "discovery",
            f"replicate-{replicate_index}",
            f"generation-{generation}",
        ]
        if protocol.get("status") == FORMAL_PROTOCOL_STATUS:
            relative.append(str(candidate_payload["algorithm"]))
        require_registered_output_path(
            protocol,
            candidate_path,
            *relative,
            "candidates.json",
        )
        require_registered_output_path(
            protocol,
            output_path,
            *relative,
            (
                "metrics.json"
                if paired_execution is None
                else paired_execution[f"{lane_role}_pass_filename"]
            ),
        )
    elif phase == "hidden":
        replicate_index = int(candidate_payload["replicate_index"])
        relative = [
            "hidden",
            f"replicate-{replicate_index}",
            f"checkpoint-{checkpoint_seed}",
        ]
        if is_formal_hidden_protocol(protocol):
            relative.append(str(candidate_payload["algorithm"]))
        path_validator = (
            require_r6_hidden_output_path
            if is_formal_hidden_protocol(protocol)
            else require_registered_output_path
        )
        path_validator(protocol, candidate_path, *relative, "candidates.json")
        path_validator(
            protocol,
            output_path,
            *relative,
            (
                "metrics.json"
                if paired_execution is None
                else paired_execution[f"{lane_role}_pass_filename"]
            ),
        )
    else:
        relative = ("replay", f"checkpoint-{checkpoint_seed}")
        require_registered_output_path(
            protocol,
            candidate_path,
            *relative,
            "candidates.json",
        )
        if paired_execution is None:
            replay_outputs = {
                require_registered_output_path(
                    protocol,
                    output_path.with_name(name),
                    *relative,
                    name,
                )
                for name in ("replay-0.json", "replay-1.json")
            }
            if output_path not in replay_outputs:
                raise ValueError("replay output is not a preregistered repetition slot")
        else:
            require_registered_output_path(
                protocol,
                output_path,
                *relative,
                paired_execution[f"{lane_role}_pass_filename"],
            )

    checkpoints = protocol.get("checkpoints")
    if not isinstance(checkpoints, dict):
        raise TypeError("protocol checkpoints are missing")
    checkpoint_record = checkpoints.get(str(checkpoint_seed))
    if not isinstance(checkpoint_record, dict):
        raise TypeError("candidate checkpoint is not registered")
    checkpoint_path = Path(checkpoint_record["path"]).resolve()
    if not checkpoint_path.is_file():
        raise FileNotFoundError(checkpoint_path)
    checkpoint_sha256 = sha256_file(checkpoint_path)
    if checkpoint_sha256 != checkpoint_record.get("sha256"):
        raise ValueError("checkpoint SHA256 mismatch")

    runtime = protocol.get("runtime")
    if not isinstance(runtime, dict):
        raise TypeError("protocol runtime is missing")
    steps = int(runtime["steps"])
    dropout_start_step = int(runtime["dropout_start_step"])
    dropout_steps = int(runtime["dropout_steps"])
    if phase == "structural" and structural_gate in {
        "kill_magnitude",
        "lane_interference",
    }:
        structural_runtime = protocol["structural_gates"][str(structural_gate)]
        steps = int(structural_runtime["steps"])
        dropout_start_step = int(structural_runtime["activation_step"])
        dropout_steps = int(structural_runtime["response_steps"])
    if dropout_start_step + dropout_steps != steps:
        raise ValueError("falsifier runtime must end with the blackout")

    import genesis as gs

    genesis_source = Path(gs.__file__).resolve().parents[1]
    genesis_source_tree = sha256_source_tree(genesis_source)
    expected_genesis_sha256 = protocol["execution_environment"]["genesis_source_tree_sha256"]
    if genesis_source_tree["sha256"] != expected_genesis_sha256:
        raise ValueError("Genesis source-tree SHA256 mismatch")
    genesis_seed = int(candidate_payload["genesis_seed"])
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
        raise RuntimeError("exactly one Radeon/ROCm GPU is required")

    from flightguard.controller import (
        BatchedWaypointController,
        controller_config_for_profile,
    )
    from flightguard.domain_randomization import DomainParameters
    from flightguard.gate_math import gate_crossing, gate_lookthrough_target
    from flightguard.genesis_env import FlightGuardGenesisEnv
    from flightguard.online_context import (
        FrozenAffineDelayConfig,
        FrozenAffineDelayContext,
    )

    device = gs.device
    contexts = len(context_seeds)
    candidate_count = len(candidates)
    groups = candidate_count + (1 if paired_execution is None else 0)
    total_envs = groups * contexts

    (
        scheduled_thrust_values,
        scheduled_wind_values,
        scheduled_delay_values,
    ) = scheduled_fault_values(
        candidates,
        context_seeds,
        lane_role=lane_role,
    )
    domain_parameters = DomainParameters(
        mass_scale=torch.ones(total_envs),
        thrust_scale=torch.ones(total_envs),
        wind_acceleration_mps2=torch.zeros((total_envs, 3)),
        action_delay_steps=torch.zeros(total_envs, dtype=torch.long),
        stratum=torch.full((total_envs,), -1, dtype=torch.long),
        profile="adversarial_v3",
        seed=genesis_seed,
        scheduled_thrust_scale=torch.tensor(
            scheduled_thrust_values,
            dtype=torch.float32,
        ),
        scheduled_wind_acceleration_mps2=torch.tensor(
            scheduled_wind_values,
            dtype=torch.float32,
        ),
        scheduled_action_delay_steps=torch.tensor(
            scheduled_delay_values,
            dtype=torch.long,
        ),
    )
    env = FlightGuardGenesisEnv(
        total_envs,
        domain_parameters=domain_parameters,
        delay_history_max_steps=(
            None
            if paired_execution is None
            else int(paired_execution["protocol_max_action_delay_steps"])
        ),
    )
    if env.dt != float(runtime["dt_s"]):
        raise ValueError("Genesis environment dt differs from protocol")
    runtime_asset_sha256 = sha256_file(env.drone_urdf)

    model = load_model(checkpoint_path, device)
    context = FrozenAffineDelayContext(
        total_envs,
        device=device,
        dtype=torch.float32,
        config=FrozenAffineDelayConfig(
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
            max_score_samples=(dropout_start_step - int(runtime["context_fit_steps"])),
        ),
    )
    controller_config = controller_config_for_profile(runtime["controller_profile"])
    controller_config = replace(
        controller_config,
        max_upward_vertical_acceleration=float(runtime["max_upward_vertical_acceleration_mps2"]),
        max_downward_vertical_acceleration=float(
            runtime["max_downward_vertical_acceleration_mps2"]
        ),
    )
    controller = BatchedWaypointController(controller_config)

    gate_offsets = context_gate_offsets(
        context_seeds,
        y_jitter_m=float(runtime["gate_y_jitter_m"]),
        z_jitter_m=float(runtime["gate_z_jitter_m"]),
    )
    env.gates += repeat_contexts(gate_offsets, groups=groups).to(device=device)[:, None, :]
    all_envs = torch.arange(total_envs, device=device)
    env.reset(all_envs)

    attitude_noise, angular_velocity_noise = context_noise(
        context_seeds,
        steps=steps,
        attitude_std_rad=math.radians(float(runtime["attitude_noise_std_deg"])),
        angular_velocity_std_rad_s=float(runtime["angular_velocity_noise_std_rad_s"]),
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

    estimated_position = env.drone.get_pos().clone()
    estimated_velocity = env.drone.get_vel().clone()
    active = torch.ones(total_envs, dtype=torch.bool, device=device)
    terminal = torch.zeros_like(active)
    success = torch.zeros_like(active)
    struck = torch.zeros_like(active)
    terminal_step = torch.full(
        (total_envs,),
        -1,
        dtype=torch.long,
        device=device,
    )
    failure_type = torch.zeros(
        total_envs,
        dtype=torch.int8,
        device=device,
    )
    gates_passed = torch.zeros(
        total_envs,
        dtype=torch.long,
        device=device,
    )
    control_gate_index = torch.zeros_like(gates_passed)
    maximum_estimation_error = torch.zeros(
        total_envs,
        dtype=torch.float32,
        device=device,
    )
    maximum_truth_divergence = torch.zeros_like(maximum_estimation_error)
    maximum_matched_trace_difference = {
        field: torch.zeros(
            total_envs,
            dtype=torch.float32,
            device=device,
        )
        for field in TRACKED_FIELDS
    }
    capture_replay_trace = bool(
        phase == "replay"
        or (
            paired_execution is not None
            and phase == "structural"
            and structural_gate in {"exact_noop", "kill_magnitude", "lane_interference"}
        )
    )
    capture_formal_nominal_digest = bool(
        (
            protocol.get("status") == FORMAL_PROTOCOL_STATUS
            or is_formal_hidden_protocol(protocol)
        )
        and paired_execution is not None
        and phase in {"discovery", "hidden"}
        and lane_role == "nominal"
    )
    capture_full_trace = capture_replay_trace or capture_formal_nominal_digest
    pre_activation_trace = (
        {
            field: torch.empty(
                (
                    dropout_start_step + 1,
                    total_envs,
                    4
                    if field
                    in {
                        "truth_quaternion",
                        "measured_quaternion",
                        "issued_action",
                        "applied_action",
                    }
                    else 3,
                ),
                device=device,
                dtype=torch.float32,
            )
            for field in TRACKED_FIELDS
        }
        if paired_execution is not None
        else None
    )
    replay_trace = (
        {
            "truth_position": torch.empty((steps, total_envs, 3), device=device),
            "truth_velocity": torch.empty((steps, total_envs, 3), device=device),
            "truth_quaternion": torch.empty((steps, total_envs, 4), device=device),
            "truth_angular_velocity": torch.empty((steps, total_envs, 3), device=device),
            "measured_quaternion": torch.empty((steps, total_envs, 4), device=device),
            "measured_angular_velocity": torch.empty((steps, total_envs, 3), device=device),
            "estimated_position": torch.empty((steps, total_envs, 3), device=device),
            "estimated_velocity": torch.empty((steps, total_envs, 3), device=device),
            "issued_action": torch.empty((steps, total_envs, 4), device=device),
            "applied_action": torch.empty((steps, total_envs, 4), device=device),
        }
        if capture_full_trace
        else None
    )
    replay_discrete_trace = (
        {
            "active_before_step": torch.empty(
                (steps, total_envs),
                dtype=torch.bool,
                device=device,
            ),
            "terminal_after_step": torch.empty(
                (steps, total_envs),
                dtype=torch.bool,
                device=device,
            ),
            "success_after_step": torch.empty(
                (steps, total_envs),
                dtype=torch.bool,
                device=device,
            ),
            "gates_passed_after_step": torch.empty(
                (steps, total_envs),
                dtype=torch.long,
                device=device,
            ),
        }
        if capture_full_trace
        else None
    )
    saturation_steps = torch.zeros(
        total_envs,
        dtype=torch.long,
        device=device,
    )
    active_control_steps = torch.zeros_like(saturation_steps)
    finite_integrity = {
        field: torch.ones((), dtype=torch.bool, device=device) for field in TRACKED_FIELDS
    }
    pre_onset_pair_max = {
        field: torch.zeros((), dtype=torch.float32, device=device) for field in TRACKED_FIELDS
    }
    active_at_freeze: torch.Tensor | None = None
    context_qualified_at_freeze: torch.Tensor | None = None
    context_summary: dict[str, Any] | None = None
    scheduled_targets_persist = True
    first_action_before_activation = False
    next_position = env.drone.get_pos()
    started = time.perf_counter()

    print(
        json.dumps(
            {
                "event": "causal_falsifier_batch_start",
                "candidates": candidate_count,
                "contexts": contexts,
                "total_envs": total_envs,
                "phase": phase,
            },
            sort_keys=True,
        ),
        flush=True,
    )

    with torch.inference_mode():
        for step in range(steps):
            if step == int(runtime["context_fit_steps"]):
                context.begin_scoring()
            if step == dropout_start_step:
                context.freeze()
                context_summary = context.summary()
                active_at_freeze = active.clone()
                context_qualified_at_freeze = (
                    context.selected_valid
                    & torch.isfinite(context.selected_residual_quantile_mps2)
                    & (context.selected_residual_quantile_mps2 >= 0.0)
                )

            active_before = active.clone()
            position = env.drone.get_pos()
            quaternion = env.drone.get_quat()
            velocity = env.drone.get_vel()
            angular_velocity = env.drone.get_ang()
            if step < dropout_start_step:
                estimated_position = torch.where(
                    active_before[:, None],
                    position,
                    estimated_position,
                )
                estimated_velocity = torch.where(
                    active_before[:, None],
                    velocity,
                    estimated_velocity,
                )

            paired_attitude = repeat_contexts(
                attitude_noise[step],
                groups=groups,
            ).to(device=device)
            paired_angular_velocity = repeat_contexts(
                angular_velocity_noise[step],
                groups=groups,
            ).to(device=device)
            measured_quaternion, measured_angular_velocity = perturb_imu(
                quaternion,
                angular_velocity,
                paired_attitude + attitude_bias,
                paired_angular_velocity + angular_velocity_bias,
            )
            gate_center, target_yaw = indexed_gate(
                env.gates,
                env.gate_yaws,
                control_gate_index,
            )
            controller_target = gate_lookthrough_target(
                gate_center,
                target_yaw,
                float(runtime["gate_lookthrough_m"]),
            )
            action = controller(
                estimated_position,
                measured_quaternion,
                estimated_velocity,
                measured_angular_velocity,
                controller_target,
            )
            action = torch.where(
                active_before[:, None],
                action,
                torch.zeros_like(action),
            )
            context.push_issued(action)

            if step >= dropout_start_step:
                learned_acceleration = context.predict_acceleration(
                    model,
                    estimated_velocity,
                    measured_quaternion,
                    measured_angular_velocity,
                )
                proposed_position = (
                    estimated_position
                    + estimated_velocity * env.dt
                    + 0.5 * learned_acceleration * env.dt * env.dt
                )
                proposed_velocity = estimated_velocity + learned_acceleration * env.dt
            else:
                proposed_position = position
                proposed_velocity = velocity

            tracked_before = {
                "truth_position": position,
                "truth_velocity": velocity,
                "truth_quaternion": quaternion,
                "truth_angular_velocity": angular_velocity,
                "measured_quaternion": measured_quaternion,
                "measured_angular_velocity": measured_angular_velocity,
                "estimated_position": estimated_position,
                "estimated_velocity": estimated_velocity,
                "issued_action": action,
                "applied_action": env.last_applied_action,
            }
            for field, values in tracked_before.items():
                finite_integrity[field] &= torch.isfinite(values).all()
                if pre_activation_trace is not None and step <= dropout_start_step:
                    pre_activation_trace[field][step].copy_(values)
                if paired_execution is None and step <= dropout_start_step:
                    grouped = values.reshape(
                        groups,
                        contexts,
                        -1,
                    )
                    pre_onset_pair_max[field] = torch.maximum(
                        pre_onset_pair_max[field],
                        torch.abs(grouped - grouped[-1:]).max(),
                    )

            if step == dropout_start_step:
                first_action_before_activation = True
                if not env.activate_scheduled_faults():
                    raise RuntimeError("scheduled fault activation was not applied")

            result = env.step(action)
            next_position = env.drone.get_pos()
            next_quaternion = env.drone.get_quat()
            next_velocity = env.drone.get_vel()
            next_angular_velocity = env.drone.get_ang()
            applied_action = env.last_applied_action
            for field, values in (
                ("truth_position", next_position),
                ("truth_velocity", next_velocity),
                ("truth_quaternion", next_quaternion),
                ("truth_angular_velocity", next_angular_velocity),
                ("applied_action", applied_action),
            ):
                finite_integrity[field] &= torch.isfinite(values).all()

            if step < dropout_start_step:
                context.observe_transition(
                    model,
                    velocity,
                    measured_quaternion,
                    measured_angular_velocity,
                    next_velocity,
                    dt=env.dt,
                    phase=("fit" if step < int(runtime["context_fit_steps"]) else "score"),
                    mask=active_before,
                )
                proposed_position = next_position
                proposed_velocity = next_velocity
            else:
                scheduled_targets_persist &= env.scheduled_fault_targets_active()
                active_control_steps += active_before.long()
                saturation_steps += (
                    active_before & (applied_action.abs() >= 1.0 - 1.0e-6).any(dim=1)
                ).long()

            estimated_crossing = gate_crossing(
                estimated_position,
                proposed_position,
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
            estimated_position = torch.where(
                active_before[:, None],
                proposed_position,
                estimated_position,
            )
            estimated_velocity = torch.where(
                active_before[:, None],
                proposed_velocity,
                estimated_velocity,
            )
            finite_integrity["estimated_position"] &= torch.isfinite(estimated_position).all()
            finite_integrity["estimated_velocity"] &= torch.isfinite(estimated_velocity).all()
            current_error = torch.linalg.vector_norm(
                estimated_position - next_position,
                dim=1,
            )
            maximum_estimation_error = torch.where(
                active_before,
                torch.maximum(
                    maximum_estimation_error,
                    current_error,
                ),
                maximum_estimation_error,
            )
            if step >= dropout_start_step and paired_execution is None:
                post_step_tracked = {
                    "truth_position": next_position,
                    "truth_velocity": next_velocity,
                    "truth_quaternion": next_quaternion,
                    "truth_angular_velocity": next_angular_velocity,
                    "measured_quaternion": measured_quaternion,
                    "measured_angular_velocity": (measured_angular_velocity),
                    "estimated_position": estimated_position,
                    "estimated_velocity": estimated_velocity,
                    "issued_action": action,
                    "applied_action": applied_action,
                }
                for field, values in post_step_tracked.items():
                    grouped = values.reshape(
                        groups,
                        contexts,
                        -1,
                    )
                    matched_difference = torch.abs(grouped - grouped[-1:]).amax(dim=2).reshape(-1)
                    maximum_matched_trace_difference[field] = torch.where(
                        active_before,
                        torch.maximum(
                            maximum_matched_trace_difference[field],
                            matched_difference,
                        ),
                        maximum_matched_trace_difference[field],
                    )
                grouped_truth = next_position.reshape(
                    groups,
                    contexts,
                    3,
                )
                truth_divergence = torch.linalg.vector_norm(
                    grouped_truth - grouped_truth[-1:],
                    dim=2,
                ).reshape(-1)
                maximum_truth_divergence = torch.where(
                    active_before,
                    torch.maximum(
                        maximum_truth_divergence,
                        truth_divergence,
                    ),
                    maximum_truth_divergence,
                )

            gates_passed += (result.passed & active_before).long()
            completed = result.done & (env.gate_index >= env.gates.shape[1])
            out_of_bounds = (
                (next_position[:, 2] < 0.1)
                | (next_position[:, :2].abs() > 10.0).any(dim=1)
                | (next_position[:, 2] > 5.0)
            )
            nonfinite = ~finite_by_environment(next_position)
            newly_done = active_before & result.done
            new_failure = newly_done & ~completed
            failure_type = torch.where(
                new_failure & result.struck,
                torch.ones_like(failure_type),
                failure_type,
            )
            failure_type = torch.where(
                new_failure & ~result.struck & out_of_bounds,
                torch.full_like(failure_type, 2),
                failure_type,
            )
            failure_type = torch.where(
                new_failure & nonfinite,
                torch.full_like(failure_type, 3),
                failure_type,
            )
            failure_type = torch.where(
                new_failure & (failure_type == 0),
                torch.full_like(failure_type, 4),
                failure_type,
            )
            success |= newly_done & completed
            struck |= newly_done & result.struck
            terminal |= newly_done
            terminal_step[newly_done] = step + 1
            active = active_before & ~newly_done
            if replay_trace is not None and replay_discrete_trace is not None:
                trace_step_values = {
                    "truth_position": next_position,
                    "truth_velocity": next_velocity,
                    "truth_quaternion": next_quaternion,
                    "truth_angular_velocity": next_angular_velocity,
                    "measured_quaternion": measured_quaternion,
                    "measured_angular_velocity": measured_angular_velocity,
                    "estimated_position": estimated_position,
                    "estimated_velocity": estimated_velocity,
                    "issued_action": action,
                    "applied_action": applied_action,
                }
                for field, values in trace_step_values.items():
                    replay_trace[field][step].copy_(values)
                replay_discrete_trace["active_before_step"][step].copy_(active_before)
                replay_discrete_trace["terminal_after_step"][step].copy_(terminal)
                replay_discrete_trace["success_after_step"][step].copy_(success)
                replay_discrete_trace["gates_passed_after_step"][step].copy_(gates_passed)
            done_idx = torch.nonzero(
                newly_done,
                as_tuple=False,
            ).reshape(-1)
            if done_idx.numel():
                env.reset(done_idx)

            if (step + 1) % 200 == 0:
                print(
                    json.dumps(
                        {
                            "event": "causal_falsifier_batch_progress",
                            "step": step + 1,
                            "active": int(active.sum().item()),
                            "terminal": int(terminal.sum().item()),
                        },
                        sort_keys=True,
                    ),
                    flush=True,
                )

    torch.cuda.synchronize()
    elapsed_s = time.perf_counter() - started
    if active_at_freeze is None or context_qualified_at_freeze is None or context_summary is None:
        raise RuntimeError("context freeze evidence is unavailable")
    saturation_fraction = saturation_steps.float() / (active_control_steps.clamp_min(1).float())
    nominal_success = (
        success[slice(candidate_count * contexts, total_envs)] if paired_execution is None else None
    )
    gate_count = int(env.gates.shape[1])
    failure_type_names = {
        0: None,
        1: "strike",
        2: "out_of_bounds",
        3: "nonfinite",
        4: "unclassified_terminal",
    }
    episode_records: list[dict[str, Any]] = []
    for candidate_index, candidate in enumerate(candidates):
        for context_index, context_seed in enumerate(context_seeds):
            env_index = candidate_index * contexts + context_index
            is_failure = bool(terminal[env_index].item() and not success[env_index].item())
            step_value = int(terminal_step[env_index].item())
            failure_elapsed_s = (step_value - dropout_start_step) * env.dt if is_failure else None
            saturation_value = float(saturation_fraction[env_index].item())
            episode_record = {
                "candidate_id": candidate["candidate_id"],
                "candidate_index": candidate_index,
                "algorithm": candidate["algorithm"],
                "context_index": context_index,
                "context_seed": context_seed,
                "active_at_freeze": bool(active_at_freeze[env_index].item()),
                "context_qualified_at_freeze": bool(context_qualified_at_freeze[env_index].item()),
                "terminal_failure": is_failure,
                "terminal_step": (step_value if step_value >= 0 else None),
                "failure_elapsed_s": failure_elapsed_s,
                "failure_type": failure_type_names[int(failure_type[env_index].item())],
                "mission_success": bool(success[env_index].item()),
                "gates_passed": int(gates_passed[env_index].item()),
                "mission_progress_fraction": min(
                    float(gates_passed[env_index].item()) / gate_count,
                    1.0,
                ),
                "maximum_estimation_error_m": float(maximum_estimation_error[env_index].item()),
                "applied_action_saturation_fraction": saturation_value,
            }
            if paired_execution is None:
                if nominal_success is None:
                    raise RuntimeError("legacy nominal reference is unavailable")
                within_process_valid_causal_failure = bool(
                    active_at_freeze[env_index].item()
                    and context_qualified_at_freeze[env_index].item()
                    and nominal_success[context_index].item()
                    and is_failure
                    and failure_elapsed_s is not None
                    and failure_elapsed_s > 0.25
                    and saturation_value <= 0.05
                )
                episode_record.update(
                    {
                        "nominal_reference_mission_success": bool(
                            nominal_success[context_index].item()
                        ),
                        "maximum_matched_truth_divergence_m": float(
                            maximum_truth_divergence[env_index].item()
                        ),
                        "maximum_matched_trace_difference": {
                            field: float(values[env_index].item())
                            for field, values in (maximum_matched_trace_difference.items())
                        },
                        "valid_causal_failure": within_process_valid_causal_failure,
                    }
                )
            episode_records.append(episode_record)

    nominal_records = []
    if paired_execution is None:
        for context_index, context_seed in enumerate(context_seeds):
            env_index = candidate_count * contexts + context_index
            nominal_records.append(
                {
                    "context_index": context_index,
                    "context_seed": context_seed,
                    "mission_success": bool(success[env_index].item()),
                    "terminal": bool(terminal[env_index].item()),
                    "terminal_step": (
                        int(terminal_step[env_index].item())
                        if terminal_step[env_index].item() >= 0
                        else None
                    ),
                    "gates_passed": int(gates_passed[env_index].item()),
                    "mission_progress_fraction": min(
                        float(gates_passed[env_index].item()) / gate_count,
                        1.0,
                    ),
                    "maximum_estimation_error_m": float(maximum_estimation_error[env_index].item()),
                    "applied_action_saturation_fraction": float(
                        saturation_fraction[env_index].item()
                    ),
                }
            )

    pairing_tolerance = float(protocol["causal_integrity"]["maximum_pre_onset_pair_difference"])
    finite_by_field = {field: bool(value.item()) for field, value in finite_integrity.items()}
    pre_onset_pair_max_values = (
        {field: float(value.item()) for field, value in pre_onset_pair_max.items()}
        if paired_execution is None
        else {}
    )
    pre_activation_digest = (
        pre_activation_lane_digests(pre_activation_trace)
        if pre_activation_trace is not None
        else None
    )
    policy_boundary = audit_policy_information_boundary(
        controller=controller,
        context=context,
        context_summary=context_summary,
    )
    checks = {
        "backend_is_amdgpu": gs.backend == gs.amdgpu,
        "visible_gpu_count_is_one": visible_gpu_count == 1,
        "torch_hip_nonempty": bool(torch.version.hip),
        "all_tracked_tensors_finite": all(finite_by_field.values()),
        "all_contexts_active_at_freeze": bool(active_at_freeze.all()),
        "all_contexts_qualified_at_freeze": bool(context_qualified_at_freeze.all()),
        "context_frozen_before_activation": bool(context_summary.get("frozen")),
        "post_freeze_context_updates_zero": int(context.post_freeze_update_attempts.item()) == 0,
        "first_blackout_action_computed_before_activation": (first_action_before_activation),
        "scheduled_fault_activated_exactly_once": (
            env.scheduled_fault_activation_attempts == 1
            and env.scheduled_fault_activation_count == 1
        ),
        "scheduled_targets_persist_to_end": (
            scheduled_targets_persist and env.scheduled_fault_targets_active()
        ),
        "policy_received_no_fault_parameters": policy_boundary[
            "policy_received_no_fault_parameters"
        ],
        "policy_received_no_domain_labels": policy_boundary["policy_received_no_domain_labels"],
        "policy_did_not_use_last_applied_action_after_freeze": policy_boundary[
            "policy_did_not_use_last_applied_action_after_freeze"
        ],
        "forbidden_policy_arms_absent": True,
    }
    if paired_execution is None:
        checks["pre_onset_pairing_within_tolerance"] = all(
            value <= pairing_tolerance for value in pre_onset_pair_max_values.values()
        )
    else:
        checks["pre_activation_trace_digest_available"] = bool(
            pre_activation_digest is not None
            and pre_activation_digest["lanes"] == total_envs
            and pre_activation_digest["steps"] == dropout_start_step + 1
        )
    status = "PASS" if all(checks.values()) else "FAIL"
    runtime_record = {
        "steps": steps,
        "dt_s": env.dt,
        "dropout_start_step": dropout_start_step,
        "dropout_steps": dropout_steps,
        "candidate_count": candidate_count,
        "context_count": contexts,
        "total_envs": total_envs,
        "gate_count": gate_count,
        "method_order": [
            ("learned_fault" if lane_role != "nominal" else "lane_aligned_all_nominal"),
            "learned_nominal_reference",
        ],
        "controller": asdict(controller.config),
    }
    if paired_execution is not None:
        runtime_record["delay_history_max_steps"] = int(env._delay_history.shape[0]) - 1
    payload = {
        "schema_version": SCHEMA_VERSION,
        "status": status,
        "simulation_only": True,
        "claim_boundary": protocol["claim_boundary"],
        "phase": phase,
        "structural_gate": structural_gate,
        "protocol": {
            "path": str(protocol_path),
            "sha256": protocol_sha256,
            "version": protocol["protocol_version"],
        },
        "candidate_batch": {
            "path": str(candidate_path),
            "sha256": sha256_file(candidate_path),
        },
        "checkpoint": {
            "seed": checkpoint_seed,
            "path": str(checkpoint_path),
            "sha256": checkpoint_sha256,
        },
        "execution": {
            "backend": str(gs.backend),
            "device": str(device),
            "gpu_name": torch.cuda.get_device_name(0),
            "visible_gpu_count": visible_gpu_count,
            "torch_version": torch.__version__,
            "torch_hip": torch.version.hip,
            "genesis_version": str(gs.__version__),
            "genesis_source": str(genesis_source),
            "genesis_source_tree": genesis_source_tree,
            "runtime_race_asset": str(env.drone_urdf),
            "runtime_race_asset_sha256": runtime_asset_sha256,
            "elapsed_s": elapsed_s,
            "transitions_per_s": total_envs * steps / elapsed_s,
            "implementation_files_sha256": implementation_files_sha256,
        },
        "runtime": runtime_record,
        "integrity": {
            "status": status,
            "checks": checks,
            "finite_by_field": finite_by_field,
            "pre_onset_pair_max_absolute": pre_onset_pair_max_values,
            "pre_onset_pair_tolerance": pairing_tolerance,
            "context_post_freeze_update_attempts": int(context.post_freeze_update_attempts.item()),
            "context_summary": context_summary,
            "policy_information_boundary": policy_boundary,
            "fault_activation_attempts": (env.scheduled_fault_activation_attempts),
            "fault_activation_count": (env.scheduled_fault_activation_count),
        },
        "candidates": candidates,
        "episodes": episode_records,
        "nominal_references": nominal_records,
    }
    if paired_execution is not None:
        payload["execution_lane_role"] = lane_role
        payload["primary_result_eligible"] = False
        payload["executed_schedule"] = (
            "candidate_faults" if lane_role == "candidate" else "all_nominal"
        )
        payload["pre_activation_trace_digest"] = pre_activation_digest
    if capture_replay_trace and replay_trace is not None and replay_discrete_trace is not None:
        payload["replay_trace"] = {
            "layout": "step_environment_component",
            "environment_order": [
                *[
                    {
                        "kind": "candidate",
                        "candidate_index": candidate_index,
                        "candidate_id": candidate["candidate_id"],
                        "context_seed": context_seed,
                    }
                    for candidate_index, candidate in enumerate(candidates)
                    for context_seed in context_seeds
                ],
                *(
                    [
                        {
                            "kind": "nominal_reference",
                            "candidate_index": None,
                            "candidate_id": None,
                            "context_seed": context_seed,
                        }
                        for context_seed in context_seeds
                    ]
                    if paired_execution is None
                    else []
                ),
            ],
            "float_fields": {
                field: values.detach().cpu().tolist() for field, values in replay_trace.items()
            },
            "discrete_fields": {
                field: values.detach().cpu().tolist()
                for field, values in replay_discrete_trace.items()
            },
        }
    if (
        capture_formal_nominal_digest
        and replay_trace is not None
        and replay_discrete_trace is not None
    ):
        payload["full_trajectory_lane_digest"] = full_trajectory_lane_digests(
            replay_trace,
            replay_discrete_trace,
            candidates=candidates,
            context_seeds=context_seeds,
        )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(
            payload,
            allow_nan=False,
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            final_event_payload(
                status=status,
                output_path=output_path,
                episode_records=episode_records,
                lane_role=lane_role,
                paired_execution=paired_execution,
            ),
            sort_keys=True,
        ),
        flush=True,
    )
    if status != "PASS":
        raise SystemExit(2)


if __name__ == "__main__":
    main()
