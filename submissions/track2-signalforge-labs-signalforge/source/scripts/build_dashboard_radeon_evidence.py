#!/usr/bin/env python3
"""Build or verify synchronized local and hybrid Radeon dashboard evidence."""

from __future__ import annotations

import argparse
import hashlib
import json
import struct
from pathlib import Path
from typing import Any

JOURNEY_SCHEMA = "signalforge/dashboard-radeon-journey/v1"
OUTPUT_SCHEMA = "signalforge/dashboard-radeon-synchronized-captures/v1"
EXPECTED_PHASES = {
    "interpretation",
    "planning",
    "context",
    "tools",
    "review",
    "synthesis",
    "memory",
    "release",
}
PRIVACY_FIELDS = {
    "credentials_retained",
    "prompt_bodies_retained",
    "response_bodies_retained",
    "source_bodies_retained",
}
FORBIDDEN_KEYS = {
    "api_key",
    "answer",
    "authorization",
    "content",
    "headers",
    "prompt",
    "question",
    "response",
    "source_body",
}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def require_sha256(value: str, label: str) -> str:
    if len(value) != 64 or any(character not in "0123456789abcdef" for character in value):
        raise ValueError(f"{label} must be a lowercase SHA-256 digest")
    return value


def reject_protected_fields(value: Any, path: str = "$") -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            if key.lower() in FORBIDDEN_KEYS:
                raise ValueError(f"protected field present at {path}.{key}")
            reject_protected_fields(child, f"{path}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            reject_protected_fields(child, f"{path}[{index}]")


def load_journey(path: Path, mode: str) -> dict[str, Any]:
    journey = json.loads(path.read_text(encoding="utf-8"))
    reject_protected_fields(journey)
    if journey.get("schema_version") != JOURNEY_SCHEMA:
        raise ValueError(f"{path} uses an unexpected journey schema")
    if journey.get("mode") != mode:
        raise ValueError(f"{path} must use mode {mode}")
    if journey.get("status") != "completed":
        raise ValueError(f"{path} must record a completed journey")
    if not journey.get("run_id") or not journey.get("trace_id"):
        raise ValueError(f"{path} must bind one run and trace")
    require_sha256(str(journey.get("source_trace_sha256", "")), "source trace")

    privacy = journey.get("privacy")
    if not isinstance(privacy, dict) or set(privacy) != PRIVACY_FIELDS:
        raise ValueError(f"{path} has an incomplete privacy declaration")
    if any(privacy.values()):
        raise ValueError(f"{path} retains protected bodies or credentials")

    plan = journey.get("execution_plan")
    if not isinstance(plan, dict):
        raise ValueError(f"{path} is missing the execution plan")
    if plan.get("status") != "passed" or plan.get("progress_ratio") != 1:
        raise ValueError(f"{path} does not contain an accepted completed plan")
    if plan.get("terminal_steps") != plan.get("total_steps") or not plan.get("total_steps"):
        raise ValueError(f"{path} has incomplete execution steps")
    phases = plan.get("phases")
    if not isinstance(phases, list) or {phase.get("phase_id") for phase in phases} != EXPECTED_PHASES:
        raise ValueError(f"{path} does not contain the eight governed phases")
    require_sha256(str(plan.get("projection_sha256", "")), "projection")

    intelligence = journey.get("intelligence")
    if not isinstance(intelligence, dict) or intelligence.get("release_status") != "released":
        raise ValueError(f"{path} does not contain released intelligence lineage")
    if not isinstance(intelligence.get("model_calls"), int) or intelligence["model_calls"] <= 0:
        raise ValueError(f"{path} must report positive model calls")
    return journey


def image_dimensions(path: Path) -> tuple[str, int, int]:
    payload = path.read_bytes()
    if payload.startswith(b"\x89PNG\r\n\x1a\n") and len(payload) >= 24:
        width, height = struct.unpack(">II", payload[16:24])
        return "png", width, height
    if payload.startswith(b"\xff\xd8"):
        index = 2
        while index + 9 < len(payload):
            if payload[index] != 0xFF:
                index += 1
                continue
            marker = payload[index + 1]
            index += 2
            if marker in {0xD8, 0xD9}:
                continue
            if index + 2 > len(payload):
                break
            segment_length = struct.unpack(">H", payload[index:index + 2])[0]
            if marker in {
                0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7,
                0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF,
            }:
                if index + 7 > len(payload):
                    break
                height, width = struct.unpack(">HH", payload[index + 3:index + 7])
                return "jpeg", width, height
            index += segment_length
    raise ValueError(f"{path} is not a supported PNG or JPEG capture")


def capture_record(path: Path) -> dict[str, Any]:
    image_format, width, height = image_dimensions(path)
    if width < 1280 or height < 720:
        raise ValueError(f"{path} must be at least 1280x720")
    if path.suffix.lower() not in {".jpg", ".jpeg", ".png"}:
        raise ValueError(f"{path} must use a web-safe image extension")
    if image_format == "jpeg" and path.suffix.lower() not in {".jpg", ".jpeg"}:
        raise ValueError(f"{path} contains JPEG data but does not use a JPEG extension")
    if image_format == "png" and path.suffix.lower() != ".png":
        raise ValueError(f"{path} contains PNG data but does not use a PNG extension")
    return {
        "path": path.as_posix(),
        "format": image_format,
        "width": width,
        "height": height,
        "sha256": sha256_file(path),
    }


def build_report(
    local_path: Path,
    hybrid_path: Path,
    captures: dict[str, Path],
    binary_sha256: str,
    frontend_sha256: str,
) -> dict[str, Any]:
    local = load_journey(local_path, "local_only")
    hybrid = load_journey(hybrid_path, "hybrid_radeon_api")

    local_routes = set(local["intelligence"].get("routes", []))
    local_providers = set(local["intelligence"].get("providers", []))
    if local_routes != {"local_rocm"} or local_providers != {"local-rocm"}:
        raise ValueError("local journey must use only local ROCm inference")

    hybrid_routes = set(hybrid["intelligence"].get("routes", []))
    hybrid_providers = set(hybrid["intelligence"].get("providers", []))
    if not {"provided_radeon_api", "local_rocm"}.issubset(hybrid_routes):
        raise ValueError("hybrid journey must prove Radeon API and local ROCm fallback routes")
    if not {"radeon-vllm", "local-rocm"}.issubset(hybrid_providers):
        raise ValueError("hybrid journey must prove Radeon API and local ROCm providers")

    return {
        "schema_version": OUTPUT_SCHEMA,
        "decision": {
            "status": "passed",
            "claim": "synchronized expandable Workspace and Mission Control journeys on Radeon",
            "exact_release_artifact": False,
        },
        "build_identity": {
            "workspace_binary_sha256": require_sha256(binary_sha256, "workspace binary"),
            "frontend_index_sha256": require_sha256(frontend_sha256, "frontend index"),
            "source_identity": "working-tree-j08; not an accepted release image",
        },
        "journeys": {
            "local": {
                "run_id": local["run_id"],
                "trace_id": local["trace_id"],
                "manifest_sha256": sha256_file(local_path),
                "model_calls": local["intelligence"]["model_calls"],
                "routes": sorted(local_routes),
                "providers": sorted(local_providers),
            },
            "hybrid": {
                "run_id": hybrid["run_id"],
                "trace_id": hybrid["trace_id"],
                "manifest_sha256": sha256_file(hybrid_path),
                "model_calls": hybrid["intelligence"]["model_calls"],
                "routes": sorted(hybrid_routes),
                "providers": sorted(hybrid_providers),
            },
        },
        "captures": {name: capture_record(path) for name, path in sorted(captures.items())},
        "privacy": {
            "credentials_retained": False,
            "prompt_bodies_retained": False,
            "response_bodies_retained": False,
            "source_bodies_retained": False,
        },
        "boundaries": {
            "workspace_and_mission_control_share_run_and_trace_identity": True,
            "sealed_population_opened": False,
            "release_claim_permitted": False,
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--local", type=Path, required=True)
    parser.add_argument("--hybrid", type=Path, required=True)
    parser.add_argument("--local-plan", type=Path, required=True)
    parser.add_argument("--local-mission", type=Path, required=True)
    parser.add_argument("--hybrid-plan", type=Path, required=True)
    parser.add_argument("--hybrid-mission", type=Path, required=True)
    parser.add_argument("--binary-sha256", required=True)
    parser.add_argument("--frontend-sha256", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    report = build_report(
        args.local,
        args.hybrid,
        {
            "hybrid_mission_control": args.hybrid_mission,
            "hybrid_plan": args.hybrid_plan,
            "local_mission_control": args.local_mission,
            "local_plan": args.local_plan,
        },
        args.binary_sha256,
        args.frontend_sha256,
    )
    payload = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if args.check:
        if args.output.read_text(encoding="utf-8") != payload:
            raise SystemExit("dashboard Radeon evidence is stale")
    else:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(payload, encoding="utf-8")
    print(json.dumps(report["decision"], sort_keys=True))


if __name__ == "__main__":
    main()
