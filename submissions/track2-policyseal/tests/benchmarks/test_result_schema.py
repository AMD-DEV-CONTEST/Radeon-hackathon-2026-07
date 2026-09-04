from __future__ import annotations

import importlib.util
import json
from copy import deepcopy
from pathlib import Path
from types import ModuleType

import pytest
from pydantic import ValidationError

from benchmarks.compare_strategies import BenchmarkReport


def _runtime_module() -> ModuleType:
    path = Path("ops/radeon/validate-runtime.py")
    spec = importlib.util.spec_from_file_location("policyseal_validate_runtime", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _warm_run(iteration: int) -> dict[str, object]:
    return {
        "iteration": iteration,
        "latency_ms": 1000.0,
        "model_latency_ms": 900.0,
        "throughput_regions_per_second": 9.0,
        "model_region_count": 9,
        "model_request_count": 6,
        "gpu_utilization_percent_mean": 75.0,
        "gpu_utilization_percent_peak": 90.0,
        "vram_used_bytes_peak": 24_000_000_000,
        "prompt_tokens": 100,
        "completion_tokens": 50,
        "output_sha256": "a" * 64,
    }


def _strategy(strategy_id: str) -> dict[str, object]:
    return {
        "strategy_id": strategy_id,
        "configuration": {
            "batch_size": 8,
            "consistency_passes": 2,
            "deterministic_short_circuit": strategy_id == "deterministic-short-circuit",
        },
        "cold_workflow_latency_ms": 1200.0,
        "warm_runs": [_warm_run(index) for index in range(1, 11)],
        "summary": {
            "p50_latency_ms": 1000.0,
            "p95_latency_ms": 1100.0,
            "throughput_regions_per_second": 9.0,
            "model_region_count_total": 90,
            "model_request_count_total": 60,
            "gpu_utilization_percent_mean": 75.0,
            "gpu_utilization_percent_peak": 90.0,
            "vram_used_bytes_peak": 24_000_000_000,
            "prompt_tokens_total": 1000,
            "completion_tokens_total": 500,
            "deterministic_output": True,
        },
        "quality": {
            "macro_f1": 1.0,
            "accuracy": 1.0,
            "leakage_count": 0,
            "over_removal_count": 0,
            "review_count": 0,
            "high_risk_to_ordinary_false_negative_count": 0,
            "gate_passed": True,
        },
    }


def _experiment(
    experiment_id: str,
    baseline_id: str,
    optimized_id: str,
) -> dict[str, object]:
    return {
        "experiment_id": experiment_id,
        "title": "Frozen comparison",
        "input_sha256": "b" * 64,
        "sample_count": 30,
        "baseline_strategy_id": baseline_id,
        "optimized_strategy_id": optimized_id,
        "target_metric": "p95 latency",
        "target_improvement_percent": 20.0,
        "actual_improvement_percent": 25.0,
        "target_status": "met",
        "result_reason": "Measured result retained all quality gates.",
        "strategies": [_strategy(baseline_id), _strategy(optimized_id)],
    }


def _report() -> dict[str, object]:
    return {
        "schema_version": 1,
        "recorded_at": "2026-08-02T12:00:00+00:00",
        "source_commit": "c" * 40,
        "runtime": {
            "platform": "Linux",
            "python": "3.12.3",
            "rocm": "7.2.1",
            "hip": "7.2.53211-e1a6bc5663",
            "gpu_architecture": "gfx1100",
            "gpu_name": "AMD Radeon",
            "gpu_vram_bytes": 51_522_830_336,
            "torch": "2.9.1+gitff65f5b",
            "vllm": "0.16.1.dev0+g89a77b108.d20260317",
            "transformers": "4.57.6",
            "model": "Qwen/Qwen3-8B",
            "model_sha256": "d" * 64,
            "model_files": {"config.json": "e" * 64},
            "model_parameters": {
                "dtype": "bfloat16",
                "attention_backend": "TRITON_ATTN",
                "max_model_len": 8192,
                "max_num_seqs": 8,
                "max_num_batched_tokens": 8192,
                "gpu_memory_utilization": 0.46,
                "thinking": False,
            },
            "model_server_cold_start_ms": 90_000,
            "endpoint_scope": "localhost",
        },
        "workload": {
            "input_sha256": "f" * 64,
            "policy_sha256": "0" * 64,
            "sample_count": 30,
            "warm_repetitions": 10,
            "consistency_passes": 2,
        },
        "experiments": [
            _experiment(
                "experiment-a-batching",
                "per-region",
                "stable-id-batching",
            ),
            _experiment(
                "experiment-b-cascade",
                "all-region-model",
                "deterministic-short-circuit",
            ),
        ],
    }


def test_committed_schema_matches_the_typed_result_contract() -> None:
    committed = json.loads(Path("benchmarks/schema.json").read_text(encoding="utf-8"))
    assert committed == BenchmarkReport.model_json_schema()
    assert BenchmarkReport.model_validate(_report()).workload.warm_repetitions == 10


def test_result_contract_rejects_fewer_than_ten_warm_runs() -> None:
    report = deepcopy(_report())
    report["experiments"][0]["strategies"][0]["warm_runs"] = [_warm_run(1)]  # type: ignore[index]
    with pytest.raises(ValidationError, match="at least 10 items"):
        BenchmarkReport.model_validate(report)


def test_runtime_manifest_and_endpoint_scope_are_frozen() -> None:
    runtime = _runtime_module()
    manifest = runtime._manifest(Path("ops/radeon/qwen3-8b.sha256"))
    assert len(manifest) == 8
    assert set(runtime.EXPECTED) == {
        "python",
        "rocm",
        "gpu_architecture",
        "torch",
        "vllm",
        "transformers",
    }
    runtime._validate_loopback_url("http://127.0.0.1:8000/v1/models")
    with pytest.raises(runtime.RuntimeValidationError, match="localhost"):
        runtime._validate_loopback_url("https://public-model.example/v1")
