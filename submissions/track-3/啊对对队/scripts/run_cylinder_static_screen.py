#!/usr/bin/env python3
from __future__ import annotations

import argparse
from dataclasses import asdict
import hashlib
import json
import math
from pathlib import Path
import sys
import time
import tomllib
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from parcel_sorter.config import load_config
from parcel_sorter.cylinder_candidate_audit import initial_cylinder_pose
from parcel_sorter.cylinder_static_screen import (
    screen_cylinder_environment,
    screen_episode_keys,
    summarize_static_screen,
)
from parcel_sorter.genesis_env import GenesisParcelEnv
from parcel_sorter.grasp_scoring import sha256_file
from parcel_sorter.randomization import DomainRandomizer


SUPPORTED_PROTOCOL_IDS = frozenset(
    {
        "cylinder-static-ik-collision-screen-v1",
        "cylinder-static-ik-collision-screen-v2",
    }
)


def _load_toml(path: Path) -> dict[str, Any]:
    with path.open("rb") as handle:
        payload = tomllib.load(handle)
    if not isinstance(payload, dict):
        raise ValueError(f"expected TOML table: {path}")
    return payload


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def _sample_sha256(sample: Any) -> str:
    canonical = json.dumps(
        asdict(sample),
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def _sample_matches_source(sample: Any, source_row: dict[str, Any]) -> bool:
    """Verify every geometry-affecting source field before scene construction."""

    if str(source_row.get("profile_id")) != str(sample.profile_id):
        return False
    if int(source_row.get("episode", -1)) != int(sample.episode_index):
        return False
    scalar_fields = (
        ("mass_kg", sample.mass_kg),
        ("friction", sample.friction),
        ("rolling_friction", sample.rolling_friction),
        ("yaw_rad", sample.yaw_rad),
    )
    for field, actual in scalar_fields:
        expected = source_row.get(field)
        if expected is None or not math.isclose(
            float(actual), float(expected), rel_tol=0.0, abs_tol=1e-12
        ):
            return False
    if str(source_row.get("orientation_mode")) != str(sample.orientation_mode):
        return False
    for field, actual_values in (
        ("dimensions_m", sample.dimensions_m),
        ("position_xy", sample.position_xy),
        ("pose", initial_cylinder_pose(sample)),
    ):
        expected_values = source_row.get(field)
        if expected_values is None or len(expected_values) != len(actual_values):
            return False
        if any(
            not math.isclose(
                float(actual), float(expected), rel_tol=0.0, abs_tol=1e-12
            )
            for actual, expected in zip(actual_values, expected_values, strict=True)
        ):
            return False
    return True


def _device_metadata(env: GenesisParcelEnv, backend: str) -> dict[str, Any]:
    torch = env.torch
    properties = torch.cuda.get_device_properties(0)
    return {
        "backend": backend,
        "torch_version": str(torch.__version__),
        "torch_hip_version": str(torch.version.hip or ""),
        "visible_device_count": int(torch.cuda.device_count()),
        "device_name": str(torch.cuda.get_device_name(0)),
        "gcn_arch_name": str(getattr(properties, "gcnArchName", "unknown")),
        "total_memory_bytes": int(properties.total_memory),
    }


def _validate_protocol(protocol_path: Path, protocol: dict[str, Any]) -> list[str]:
    errors = []
    if str(protocol["metadata"]["protocol_id"]) not in SUPPORTED_PROTOCOL_IDS:
        errors.append("protocol_id")
    execution = protocol.get("execution", {})
    if str(execution.get("backend")) != "rocm":
        errors.append("execution_backend")
    if bool(execution.get("require_single_visible_device")) is not True:
        errors.append("single_device_requirement")
    if bool(execution.get("require_hip")) is not True:
        errors.append("hip_requirement")
    if bool(execution.get("defer_initialization_settle")) is not True:
        errors.append("initialization_settle_not_deferred")
    if int(execution.get("expected_physics_steps", -1)) != 0:
        errors.append("physics_step_contract")
    try:
        screen_episode_keys(protocol)
    except (KeyError, TypeError, ValueError) as error:
        errors.append(f"population:{error}")
    implementation = protocol["implementation"]
    for name in (
        "planner",
        "screen_module",
        "runner",
        "genesis_env",
        "grasp_planning",
        "catalog",
        "source_audit",
        "config",
        "randomization",
        "expert",
        "capabilities",
        "source_audit_module",
        "source_audit_runner",
    ):
        path = PROJECT_ROOT / str(implementation[name])
        expected = str(implementation[f"{name}_sha256"])
        if expected == "PENDING_AFTER_FREEZE":
            errors.append(f"{name}_hash_not_frozen")
        elif sha256_file(path) != expected:
            errors.append(f"{name}_hash_mismatch")
    source_path = PROJECT_ROOT / str(implementation["source_audit"])
    source = json.loads(source_path.read_text(encoding="utf-8"))
    if source.get("status") != "candidate_population_valid":
        errors.append("source_audit_invalid")
    source_contract = source.get("selection_contract", {})
    if (
        bool(source_contract.get("physics_stepped"))
        or bool(source_contract.get("scene_constructed"))
        or bool(source_contract.get("robot_action_executed"))
        or source_contract.get("outcome_fields_read") != []
    ):
        errors.append("source_audit_used_physics_or_outcomes")
    source_implementation = source.get("implementation_sha256", {})
    for source_name, protocol_name in (
        ("planner", "planner"),
        ("catalog", "catalog"),
        ("audit_module", "source_audit_module"),
        ("runner", "source_audit_runner"),
    ):
        if str(source_implementation.get(source_name, "")) != str(
            implementation[f"{protocol_name}_sha256"]
        ):
            errors.append(f"source_implementation:{source_name}")
    source_keys = {
        (str(row["profile_id"]), int(row["episode"]))
        for row in source.get("samples", ())
    }
    if not set(screen_episode_keys(protocol)) <= source_keys:
        errors.append("screen_population_outside_source_audit")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--protocol", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--backend", choices=("rocm", "cpu"), default="rocm")
    parser.add_argument("--resume", action="store_true")
    args = parser.parse_args()

    protocol = _load_toml(args.protocol)
    protocol_errors = _validate_protocol(args.protocol, protocol)
    if protocol_errors:
        raise ValueError("invalid static-screen protocol: " + ", ".join(protocol_errors))
    expected_backend = str(protocol["execution"]["backend"])
    protocol_id = str(protocol["metadata"]["protocol_id"])
    if args.backend != expected_backend:
        raise ValueError(
            f"static-screen backend must match frozen protocol: {expected_backend}"
        )
    protocol_sha256 = sha256_file(args.protocol)
    implementation = protocol["implementation"]
    config = load_config(PROJECT_ROOT / str(implementation["catalog"]))
    randomizer = DomainRandomizer(
        config.randomization,
        config.seed,
        config.parcel_profiles,
    )
    keys = screen_episode_keys(protocol)
    source_payload = json.loads(
        (PROJECT_ROOT / str(implementation["source_audit"])).read_text(
            encoding="utf-8"
        )
    )
    source_rows = {
        (str(row["profile_id"]), int(row["episode"])): row
        for row in source_payload.get("samples", ())
    }
    mismatched_source_keys = [
        key
        for key in keys
        if key not in source_rows
        or not _sample_matches_source(
            randomizer.sample_profile(key[0], key[1]),
            source_rows[key],
        )
    ]
    if mismatched_source_keys:
        raise ValueError(
            "static-screen sample projection differs from the frozen outcome-free "
            f"source: {mismatched_source_keys}"
        )
    manifest = {
        "schema_version": "1.0",
        "protocol_id": protocol_id,
        "protocol_sha256": protocol_sha256,
        "backend": args.backend,
        "runs": [],
    }
    completed = []
    frozen_device: dict[str, Any] | None = None
    for profile_id, episode in keys:
        sample = randomizer.sample_profile(profile_id, episode)
        sample_sha256 = _sample_sha256(sample)
        output_path = args.output_dir / "samples" / profile_id / f"{episode}.json"
        if args.resume and output_path.exists():
            existing = json.loads(output_path.read_text(encoding="utf-8"))
            if (
                existing.get("protocol_sha256") == protocol_sha256
                and existing.get("status") == "complete"
                and existing.get("profile_id") == profile_id
                and int(existing.get("episode", -1)) == episode
                and existing.get("sample_sha256") == sample_sha256
                and existing.get("backend") == expected_backend
                and isinstance(existing.get("device"), dict)
            ):
                if frozen_device is None:
                    frozen_device = dict(existing["device"])
                elif existing["device"] != frozen_device:
                    raise ValueError("resumed sample device metadata differs")
                completed.append(existing)
                manifest["runs"].append(
                    {
                        "profile_id": profile_id,
                        "episode": episode,
                        "status": "complete",
                        "output": str(output_path.resolve()),
                        "resumed": True,
                    }
                )
                _write_json(args.output_dir / "manifest.json", manifest)
                continue

        scene_started = time.perf_counter_ns()
        try:
            with GenesisParcelEnv(
                config,
                sample,
                backend=args.backend,
                defer_initialization_settle=bool(
                    protocol["execution"]["defer_initialization_settle"]
                ),
            ) as env:
                scene_build_ms = (time.perf_counter_ns() - scene_started) / 1_000_000
                device = _device_metadata(env, args.backend)
                if bool(protocol["execution"]["require_hip"]) and not device[
                    "torch_hip_version"
                ]:
                    raise RuntimeError("frozen ROCm screen requires a HIP PyTorch build")
                if (
                    bool(protocol["execution"]["require_single_visible_device"])
                    and device["visible_device_count"] != 1
                ):
                    raise RuntimeError("frozen ROCm screen requires one visible GPU")
                if frozen_device is None:
                    frozen_device = device
                elif device != frozen_device:
                    raise RuntimeError("device metadata changed during static screen")
                result = screen_cylinder_environment(env, protocol)
            result.update(
                {
                    "protocol_id": protocol_id,
                    "protocol_sha256": protocol_sha256,
                    "backend": args.backend,
                    "device": device,
                    "sample_sha256": sample_sha256,
                    "scene_build_ms": scene_build_ms,
                }
            )
            _write_json(output_path, result)
            completed.append(result)
            status = "complete"
            error = None
        except Exception as exception:
            status = "failed"
            error = f"{type(exception).__name__}: {exception}"
        manifest["runs"].append(
            {
                "profile_id": profile_id,
                "episode": episode,
                "status": status,
                "output": str(output_path.resolve()),
                "resumed": False,
                "error": error,
            }
        )
        _write_json(args.output_dir / "manifest.json", manifest)
        if error is not None:
            raise RuntimeError(error)

    summary = summarize_static_screen(completed, protocol)
    summary.update(
        {
            "protocol_id": protocol_id,
            "protocol_sha256": protocol_sha256,
            "backend": args.backend,
            "implementation_sha256": {
                name: str(implementation[f"{name}_sha256"])
                for name in (
                    "planner",
                    "screen_module",
                    "runner",
                    "genesis_env",
                    "grasp_planning",
                "catalog",
                "source_audit",
                "config",
                "randomization",
                "expert",
                "capabilities",
                "source_audit_module",
                "source_audit_runner",
            )
            },
        }
    )
    _write_json(args.output_dir / "result.json", summary)
    print(
        json.dumps(
            {
                "status": summary["status"],
                "observed_samples": summary["observed_samples"],
                "errors": summary["errors"],
            }
        )
    )
    return 0 if summary["status"] == "screen_pass" else 2


if __name__ == "__main__":
    raise SystemExit(main())
