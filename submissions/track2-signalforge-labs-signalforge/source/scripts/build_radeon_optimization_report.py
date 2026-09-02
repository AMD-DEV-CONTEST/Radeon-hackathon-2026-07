#!/usr/bin/env python3
"""Build the public Sprint 11 Radeon optimization decision from measured artifacts."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RUNS = ROOT / "evidence" / "runs" / "sprint11"


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def relative(path: Path) -> str:
    return str(path.relative_to(ROOT))


def micro_profile(profile_id: str, decision: str, reason: str) -> dict:
    directory = RUNS / profile_id
    manifest_path = directory / "manifest.json"
    manifest = load(manifest_path)
    modes: dict[str, dict] = {}
    for mode in ("single", "contention"):
        summary_path = directory / f"{mode}-summary.json"
        telemetry_path = directory / f"{mode}-telemetry-summary.json"
        summary = load(summary_path)
        telemetry = load(telemetry_path)
        modes[mode] = {
            "contract_success_rate": summary["overall"]["success_rate"],
            "duration_ms_p50": summary["overall"]["duration_ms_p50"],
            "duration_ms_p95": summary["overall"]["duration_ms_p95"],
            "requests_per_second": summary["aggregate"]["requests_per_second"],
            "completion_tokens_per_wall_second": summary["aggregate"]["completion_tokens_per_wall_second"],
            "vram_used_mb_max": telemetry["metrics"]["vram_used_mb"]["maximum"],
            "summary_path": relative(summary_path),
            "summary_sha256": sha256(summary_path),
        }
    return {
        "profile_id": profile_id,
        "runtime": manifest["runtime"],
        "startup_ready_ms": manifest["startup_ready_ms"],
        "quality_gate": manifest["quality_gate"],
        "modes": modes,
        "decision": decision,
        "reason": reason,
        "manifest_path": relative(manifest_path),
        "manifest_sha256": sha256(manifest_path),
    }


def golden_profile(profile_id: str, decision: str, reason: str) -> dict:
    directory = RUNS / profile_id
    replay_path = directory / "safe-replay.json"
    evaluation_path = directory / "semantic-evaluation.json"
    replay = load(replay_path)
    evaluation = load(evaluation_path)
    return {
        "profile_id": profile_id,
        "metrics": replay["metrics"],
        "run_status": replay["status"],
        "semantic_passed": evaluation["passed"],
        "semantic_checks_passed": evaluation["passed_checks"],
        "semantic_checks_total": evaluation["total_checks"],
        "decision": decision,
        "reason": reason,
        "safe_replay_path": relative(replay_path),
        "safe_replay_sha256": sha256(replay_path),
        "semantic_evaluation_path": relative(evaluation_path),
        "semantic_evaluation_sha256": sha256(evaluation_path),
    }


def build() -> dict:
    invalid = micro_profile(
        "baseline-controlled",
        "invalid_experiment",
        "Explicit four-slot launch without unified KV divided the 32,768-token cache into 8,192 tokens per slot and rejected every long-context case.",
    )
    baseline = micro_profile(
        "baseline-unified-kv",
        "selected_runtime",
        "Unified KV restored the intended 32,768-token request capacity and passed all 80 isolated and concurrent observations.",
    )
    flash = micro_profile(
        "flash-attn-on",
        "rejected_after_golden_journey",
        "The microbenchmark tail improved, but the controlled full journey was slower than flash-attention auto.",
    )
    ubatch = micro_profile(
        "flash-on-ubatch-1024",
        "rejected",
        "Prefill improved, but concurrent p95 regressed against the flash-on candidate and VRAM increased.",
    )
    kv_q8 = micro_profile(
        "flash-on-kv-q8",
        "rejected_quality_gate",
        "KV Q8 saved little VRAM and reduced isolated contract success to 90 percent.",
    )

    golden_auto_4 = golden_profile(
        "golden-context-4-auto",
        "selected_product_concurrency",
        "Lowest passing end-to-end duration with all 44 frozen semantic checks.",
    )
    golden_flash_4 = golden_profile(
        "golden-context-4",
        "rejected",
        "Passed all semantic checks but was slower end to end than flash-attention auto.",
    )
    golden_auto_3 = golden_profile(
        "golden-context-3-auto",
        "rejected",
        "Passed all semantic checks but required three additional model calls and was slower.",
    )
    golden_auto_2 = golden_profile(
        "golden-context-2",
        "rejected_quality_gate",
        "The final synthesis failed closed after contradicting a successful DCF receipt.",
    )
    selected_ms = golden_auto_4["metrics"]["end_to_end_duration_ms"]
    three_ms = golden_auto_3["metrics"]["end_to_end_duration_ms"]

    return {
        "schema_version": "signalforge/radeon-optimization-decision/v1",
        "measured_at": "2026-07-22",
        "hardware": {
            "gpu_architecture": "gfx1100",
            "vram_gib": 47.98,
            "rocm_version": "7.2.1",
            "runtime": "llama.cpp",
            "runtime_revision": "305ba519ab61cdff8044922cba2347826a04453f",
            "model": "google/gemma-4-26B-A4B-it-qat-q4_0-gguf",
            "model_revision": "d1c082be9cf3c8a514acf63b8761f4b41935842e",
            "quantization": "QAT Q4_0",
        },
        "frozen_contract": {
            "path": "configs/runtime/radeon-optimization-v1.json",
            "sha256": sha256(ROOT / "configs" / "runtime" / "radeon-optimization-v1.json"),
            "benchmark_suite_sha256": "c6e7dcc6af829f434dc2e940719c4f6264fdc5536cef7a720f6c4199377cb0cc",
        },
        "accepted_improvements": {
            "launcher_contract_success_before": 0.875,
            "launcher_contract_success_after": 1.0,
            "long_context_capacity_before_tokens_per_slot": 8192,
            "long_context_capacity_after_tokens_per_request": 32768,
            "selected_vs_three_context_workers_end_to_end_improvement_percent": (three_ms - selected_ms) / three_ms * 100,
        },
        "selected_configuration": {
            "flash_attention": "auto",
            "kv_cache": "unified_f16",
            "context_capacity_tokens": 32768,
            "server_slots": 4,
            "product_context_concurrency": 4,
            "continuous_batching": True,
            "stable_fallback": "The same hash-pinned QAT Q4_0 model and F16 cache with SIGNALFORGE_FLASH_ATTN=auto.",
        },
        "microbenchmarks": [invalid, baseline, flash, ubatch, kv_q8],
        "golden_journeys": [golden_auto_4, golden_flash_4, golden_auto_3, golden_auto_2],
        "scope": "Measured on the allocated Radeon node. Contract checks and the frozen semantic rubric are quality gates; they are not universal model-accuracy claims.",
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=ROOT / "evidence" / "radeon-optimization.json")
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    encoded = json.dumps(build(), indent=2, sort_keys=True) + "\n"
    if args.check:
        if not args.output.exists() or args.output.read_text(encoding="utf-8") != encoded:
            raise SystemExit(f"stale Radeon optimization report: {args.output}")
        return
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(encoded, encoding="utf-8")


if __name__ == "__main__":
    main()
