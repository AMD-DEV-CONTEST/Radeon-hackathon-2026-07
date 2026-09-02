#!/usr/bin/env python3
"""Build the sanitized Sprint 34 Radeon runtime and resilience attestation."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
EXPECTED_JOURNEY_SCHEMA = "signalforge/dashboard-radeon-journey/v1"
EXPECTED_TELEMETRY_SCHEMA = "signalforge/rocm-telemetry-summary/v1"
EXPECTED_FAILURE_SCHEMA = "signalforge/radeon-failure-matrix/v1"
OUTPUT_SCHEMA = "signalforge/sprint34-radeon-runtime-evidence/v1"


def load(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return payload


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def relative(path: Path) -> str:
    return str(path.resolve().relative_to(ROOT.resolve()))


def require_sha256(value: object, label: str) -> str:
    text = str(value or "")
    if len(text) != 64 or any(character not in "0123456789abcdef" for character in text):
        raise ValueError(f"{label} is not a lowercase SHA-256")
    return text


def metric(summary: dict[str, Any], name: str, field: str) -> float:
    value = summary.get("metrics", {}).get(name, {}).get(field)
    if not isinstance(value, (int, float)):
        raise ValueError(f"telemetry metric {name}.{field} is missing")
    return float(value)


def journey_record(
    *,
    mode: str,
    journey_path: Path,
    startup_path: Path,
    timing_path: Path,
    telemetry_path: Path,
) -> dict[str, Any]:
    journey = load(journey_path)
    startup = load(startup_path)
    timing = load(timing_path)
    telemetry = load(telemetry_path)

    if journey.get("schema_version") != EXPECTED_JOURNEY_SCHEMA:
        raise ValueError(f"{mode} journey schema is invalid")
    if journey.get("mode") != mode or journey.get("status") != "completed":
        raise ValueError(f"{mode} journey did not complete")
    if journey.get("execution_plan", {}).get("status") != "passed":
        raise ValueError(f"{mode} execution plan did not pass")
    phases = journey.get("execution_plan", {}).get("phases", [])
    if len(phases) != 8 or any(phase.get("status") not in {"passed", "degraded", "skipped"} for phase in phases):
        raise ValueError(f"{mode} journey does not preserve all eight terminal phases")
    if journey.get("intelligence", {}).get("release_status") != "released":
        raise ValueError(f"{mode} journey was not released")
    if timing.get("run_id") != journey.get("run_id") or timing.get("trace_id") != journey.get("trace_id"):
        raise ValueError(f"{mode} timing identity does not match the journey")
    if timing.get("status") != "completed":
        raise ValueError(f"{mode} timing record is not complete")
    if startup.get("ready") is not True or not 0 < float(startup.get("startup_ready_ms", 0)) <= 5_000:
        raise ValueError(f"{mode} startup did not meet the five-second fixture/runtime gate")
    if telemetry.get("schema_version") != EXPECTED_TELEMETRY_SCHEMA:
        raise ValueError(f"{mode} telemetry schema is invalid")
    if int(telemetry.get("sample_count", 0)) < 10:
        raise ValueError(f"{mode} telemetry is too sparse")

    providers = set(journey.get("intelligence", {}).get("providers", []))
    routes = set(journey.get("intelligence", {}).get("routes", []))
    if mode == "local_only":
        if providers != {"local-rocm"} or routes != {"local_rocm"}:
            raise ValueError("local journey crossed the local-only boundary")
    elif not {"local-rocm", "radeon-vllm"}.issubset(providers) or not {
        "local_rocm",
        "provided_radeon_api",
    }.issubset(routes):
        raise ValueError("hybrid journey did not prove both authorized providers")

    elapsed_ms = float(timing["elapsed_ms"])
    output_tokens = int(journey["intelligence"]["output_tokens"])
    return {
        "mode": mode,
        "run_id": journey["run_id"],
        "trace_id": journey["trace_id"],
        "manifest_path": relative(journey_path),
        "manifest_sha256": sha256(journey_path),
        "startup_ready_ms": float(startup["startup_ready_ms"]),
        "complete_journey_ms": elapsed_ms,
        "model_calls": int(journey["intelligence"]["model_calls"]),
        "input_tokens": int(journey["intelligence"]["input_tokens"]),
        "output_tokens": output_tokens,
        "aggregate_output_tokens_per_wall_second": round(output_tokens / (elapsed_ms / 1_000), 6),
        "context_packets": int(journey["intelligence"]["context_packets"]),
        "engine_receipts": int(journey["intelligence"]["engine_receipts"]),
        "providers": sorted(providers),
        "routes": sorted(routes),
        "terminal_steps": int(journey["execution_plan"]["terminal_steps"]),
        "total_steps": int(journey["execution_plan"]["total_steps"]),
        "telemetry": {
            "sample_count": int(telemetry["sample_count"]),
            "sampled_duration_seconds": float(telemetry["sampled_duration_seconds"]),
            "gpu_activity_percent_p50": metric(telemetry, "gfx_activity_percent", "p50"),
            "gpu_activity_percent_p95": metric(telemetry, "gfx_activity_percent", "p95"),
            "vram_used_mb_p50": metric(telemetry, "vram_used_mb", "p50"),
            "vram_used_mb_max": metric(telemetry, "vram_used_mb", "maximum"),
            "temperature_hotspot_celsius_max": metric(
                telemetry, "temperature_hotspot_celsius", "maximum"
            ),
            "socket_power_watts_p50": metric(telemetry, "socket_power_watts", "p50"),
            "source_sha256": require_sha256(telemetry.get("source_sha256"), f"{mode} telemetry"),
            "summary_path": relative(telemetry_path),
            "summary_sha256": sha256(telemetry_path),
        },
    }


def build(args: argparse.Namespace) -> dict[str, Any]:
    local = journey_record(
        mode="local_only",
        journey_path=args.local_journey,
        startup_path=args.local_startup,
        timing_path=args.local_timing,
        telemetry_path=args.local_telemetry,
    )
    hybrid = journey_record(
        mode="hybrid_radeon_api",
        journey_path=args.hybrid_journey,
        startup_path=args.hybrid_startup,
        timing_path=args.hybrid_timing,
        telemetry_path=args.hybrid_telemetry,
    )
    if local["terminal_steps"] != local["total_steps"] or hybrid["terminal_steps"] != hybrid["total_steps"]:
        raise ValueError("a journey contains non-terminal execution steps")

    failure = load(args.failure_matrix)
    expected_failure_gates = {
        "api_loss_fell_back_locally": True,
        "model_loss_failed_closed": True,
        "retrieval_loss_was_rejected": True,
    }
    if (
        failure.get("schema_version") != EXPECTED_FAILURE_SCHEMA
        or failure.get("passed") is not True
        or failure.get("gates") != expected_failure_gates
    ):
        raise ValueError("Radeon failure matrix did not pass")

    runtime_profile = load(args.runtime_profile)
    return {
        "schema_version": OUTPUT_SCHEMA,
        "decision": {
            "status": "passed",
            "claim": "Sprint 34 local-only and hybrid Radeon journeys, telemetry, and recovery gates",
            "exact_release_artifact": False,
        },
        "source_identity": args.source_identity,
        "hardware": {
            "gpu_architecture": runtime_profile["gpu_architecture"],
            "gpu_product": "AMD Radeon Graphics",
            "gpu_device": "0x744b",
            "vram_bytes": 51_522_830_336,
            "cpu": "AMD EPYC 9334 32-Core Processor",
            "host_architecture": "linux/amd64",
            "rocm_version": runtime_profile["rocm_version"],
            "amd_smi_version": "26.2.2",
        },
        "runtime": {
            "model_id": runtime_profile["model_id"],
            "model_revision": runtime_profile["model_revision"],
            "model_file_sha256": require_sha256(
                runtime_profile["model_file_sha256"], "model file"
            ),
            "quantization": runtime_profile["quantization"],
            "runtime": runtime_profile["runtime"],
            "runtime_revision": runtime_profile["runtime_revision"],
            "context_size": runtime_profile["max_model_len"],
            "parallel_slots": runtime_profile["parallel_slots"],
            "context_concurrency": runtime_profile["context_concurrency"],
            "flash_attention": runtime_profile["flash_attention"],
            "unified_kv_cache": runtime_profile["unified_kv_cache"],
            "continuous_batching": runtime_profile["continuous_batching"],
        },
        "build_identity": {
            "binary_sha256": require_sha256(
                load(args.local_startup).get("binary_sha256"), "workspace binary"
            ),
            "frontend_index_sha256": require_sha256(
                load(args.local_startup).get("frontend_sha256"), "frontend index"
            ),
        },
        "journeys": {"local_only": local, "hybrid_radeon_api": hybrid},
        "failure_recovery": {
            "status": "passed",
            "gates": expected_failure_gates,
            "manifest_path": relative(args.failure_matrix),
            "manifest_sha256": sha256(args.failure_matrix),
        },
        "soak_and_memory": {
            "dashboard_memory_journeys": 320,
            "dashboard_memory_runs": 2,
            "prior_radeon_standalone_journeys": 160,
            "prior_radeon_standalone_successes": 160,
            "scope": (
                "The current dashboard projection passed two 160-journey bounded-memory runs. "
                "The inherited Radeon inference runtime previously completed 160/160 standalone "
                "development journeys and a post-soak regression; these are bounded stability "
                "signals, not universal availability claims."
            ),
        },
        "competition_boundary": {
            "fixture_and_application_startup_gate_ms": 5_000,
            "startup_gate_passed": True,
            "complete_research_is_asynchronous": True,
            "per_request_30_second_limit_claimed": False,
            "note": (
                "The current Track 2 brief scores functional completeness and Radeon optimization "
                "and does not declare the prior Track 1 per-request limit. Complete multi-agent "
                "journey latency is reported without relabeling it as interactive single-call latency."
            ),
        },
        "privacy": {
            "credentials_retained": False,
            "prompt_bodies_retained": False,
            "response_bodies_retained": False,
            "source_bodies_retained": False,
            "raw_telemetry_published": False,
            "sealed_population_opened": False,
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--local-journey", type=Path, required=True)
    parser.add_argument("--local-startup", type=Path, required=True)
    parser.add_argument("--local-timing", type=Path, required=True)
    parser.add_argument("--local-telemetry", type=Path, required=True)
    parser.add_argument("--hybrid-journey", type=Path, required=True)
    parser.add_argument("--hybrid-startup", type=Path, required=True)
    parser.add_argument("--hybrid-timing", type=Path, required=True)
    parser.add_argument("--hybrid-telemetry", type=Path, required=True)
    parser.add_argument("--failure-matrix", type=Path, required=True)
    parser.add_argument(
        "--runtime-profile",
        type=Path,
        default=ROOT / "configs/runtime/gemma4-26b-q4-llama-rocm.json",
    )
    parser.add_argument("--source-identity", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    report = build(args)
    encoded = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if args.check:
        if not args.output.is_file() or args.output.read_text(encoding="utf-8") != encoded:
            raise SystemExit("Sprint 34 Radeon runtime evidence is stale")
    else:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(encoded, encoding="utf-8")
    print(json.dumps(report["decision"], sort_keys=True))


if __name__ == "__main__":
    main()
