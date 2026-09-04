from __future__ import annotations

import argparse
import contextlib
import hashlib
import json
import os
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx

from benchmarks.compare_strategies import (
    BenchmarkCase,
    BenchmarkReport,
    ExperimentReport,
    ModelParameters,
    RuntimeEvidence,
    StrategyDefinition,
    WorkloadEvidence,
    benchmark_input_sha256,
    improvement_percent,
    run_strategy,
)
from policyseal.agent.llm_client import LocalVllmClient
from policyseal.evals.assets import load_eval_assets

EXPERIMENT_A_IDS = (
    "semantic-001",
    "semantic-005",
    "semantic-008",
    "semantic-028",
    "semantic-032",
    "semantic-036",
    "semantic-052",
    "semantic-057",
    "semantic-059",
)
EXPERIMENT_B_IDS = (
    "semantic-001",
    "semantic-002",
    "semantic-003",
    "semantic-004",
    "semantic-005",
    "semantic-006",
    "semantic-007",
    "semantic-008",
    "semantic-010",
    "semantic-011",
    "semantic-021",
    "semantic-023",
    "semantic-024",
    "semantic-025",
    "semantic-026",
    "semantic-027",
    "semantic-028",
    "semantic-030",
    "semantic-032",
    "semantic-036",
    "semantic-046",
    "semantic-047",
    "semantic-048",
    "semantic-049",
    "semantic-050",
    "semantic-051",
    "semantic-052",
    "semantic-055",
    "semantic-057",
    "semantic-059",
)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _source_commit(explicit: str | None) -> str:
    candidates = [explicit, os.environ.get("POLICYSEAL_SOURCE_COMMIT")]
    marker = Path("var/radeon/source-commit")
    if marker.is_file():
        candidates.append(marker.read_text(encoding="ascii").strip())
    with contextlib.suppress(OSError, subprocess.CalledProcessError):
        candidates.append(
            subprocess.run(
                ["git", "rev-parse", "HEAD"],
                check=True,
                capture_output=True,
                text=True,
            ).stdout.strip()
        )
    for candidate in candidates:
        if candidate is not None and len(candidate) == 40:
            return candidate
    raise ValueError("a 40-character source commit is required for Radeon evidence")


def _runtime(path: Path) -> tuple[RuntimeEvidence, dict[str, Any]]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    if raw.get("model_sha256") in {None, "not_checked"}:
        raise ValueError("benchmark runtime evidence must include verified model hashes")
    startup_path = Path("var/radeon/vllm-startup-ms")
    startup_ms = (
        float(startup_path.read_text(encoding="ascii").strip()) if startup_path.exists() else 0
    )
    return (
        RuntimeEvidence(
            platform=raw["platform"],
            python=raw["python"],
            rocm=raw["rocm"],
            hip=raw["hip"],
            gpu_architecture=raw["gpu_architecture"],
            gpu_name=raw["gpu_name"],
            gpu_vram_bytes=raw["gpu_vram_bytes"],
            torch=raw["torch"],
            vllm=raw["vllm"],
            transformers=raw["transformers"],
            model=raw["model"],
            model_sha256=raw["model_sha256"],
            model_files=raw["model_files"],
            model_parameters=ModelParameters(
                dtype="bfloat16",
                attention_backend="TRITON_ATTN",
                max_model_len=8192,
                max_num_seqs=8,
                max_num_batched_tokens=8192,
                gpu_memory_utilization=0.46,
                thinking=False,
            ),
            model_server_cold_start_ms=startup_ms,
            endpoint_scope="localhost",
        ),
        raw,
    )


def _cases(ids: tuple[str, ...], uncertain_ids: set[str]) -> tuple[BenchmarkCase, ...]:
    snippets = {item.id: item for item in load_eval_assets().semantic_snippets}
    return tuple(
        BenchmarkCase(snippet=snippets[item_id], deterministic=item_id not in uncertain_ids)
        for item_id in ids
    )


def _client(http_client: httpx.Client, model: str, timeout_seconds: float) -> LocalVllmClient:
    return LocalVllmClient(
        "http://127.0.0.1:8000/v1",
        model,
        timeout_seconds=timeout_seconds,
        max_tokens=1200,
        http_client=http_client,
    )


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        f"{json.dumps(payload, ensure_ascii=True, indent=2, sort_keys=True)}\n",
        encoding="utf-8",
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Run frozen PolicySeal Radeon experiments")
    parser.add_argument("--runtime", type=Path, required=True)
    parser.add_argument("--source-commit")
    parser.add_argument("--warm-runs", type=int, default=10)
    parser.add_argument("--consistency-passes", type=int, default=2)
    parser.add_argument("--timeout-seconds", type=float, default=180)
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("artifacts/benchmarks/radeon-benchmark-results.json"),
    )
    args = parser.parse_args()
    if args.warm_runs < 10 or args.consistency_passes < 2:
        parser.error("competition benchmarks require at least 10 warm runs and two passes")

    runtime, _ = _runtime(args.runtime)
    uncertain_ids = set(EXPERIMENT_A_IDS)
    cases_a = _cases(EXPERIMENT_A_IDS, uncertain_ids)
    cases_b = _cases(EXPERIMENT_B_IDS, uncertain_ids)

    with httpx.Client(timeout=args.timeout_seconds, follow_redirects=False) as http_client:
        print("Experiment A: per-region calls versus stable-ID batching", flush=True)
        a_baseline = run_strategy(
            StrategyDefinition("per-region", 1, False),
            cases_a,
            _client(http_client, runtime.model, args.timeout_seconds),
            warm_repetitions=args.warm_runs,
            consistency_passes=args.consistency_passes,
        )
        a_optimized = run_strategy(
            StrategyDefinition("stable-id-batching", 8, False),
            cases_a,
            _client(http_client, runtime.model, args.timeout_seconds),
            warm_repetitions=args.warm_runs,
            consistency_passes=args.consistency_passes,
        )
        a_improvement = improvement_percent(
            a_baseline.summary.p95_latency_ms,
            a_optimized.summary.p95_latency_ms,
        )
        a_met = a_improvement >= 20
        experiment_a = ExperimentReport(
            experiment_id="experiment-a-batching",
            title="Per-region calls versus stable-ID batching",
            input_sha256=benchmark_input_sha256(cases_a),
            sample_count=len(cases_a),
            baseline_strategy_id=a_baseline.strategy_id,
            optimized_strategy_id=a_optimized.strategy_id,
            target_metric="warm p95 workflow latency reduction",
            target_improvement_percent=20,
            actual_improvement_percent=a_improvement,
            target_status="met" if a_met else "not_met",
            result_reason=(
                "Stable-ID batching met the approved p95 reduction target."
                if a_met
                else (
                    "The measured p95 gain was below target; safety passes and evidence "
                    "validation were retained."
                )
            ),
            strategies=(a_baseline, a_optimized),
        )

        print("Experiment B: all-model classification versus deterministic cascade", flush=True)
        b_baseline = run_strategy(
            StrategyDefinition("all-region-model", 8, False),
            cases_b,
            _client(http_client, runtime.model, args.timeout_seconds),
            warm_repetitions=args.warm_runs,
            consistency_passes=args.consistency_passes,
        )
        b_optimized = run_strategy(
            StrategyDefinition("deterministic-short-circuit", 8, True),
            cases_b,
            _client(http_client, runtime.model, args.timeout_seconds),
            warm_repetitions=args.warm_runs,
            consistency_passes=args.consistency_passes,
        )
        b_improvement = improvement_percent(
            float(b_baseline.summary.model_region_count_total),
            float(b_optimized.summary.model_region_count_total),
        )
        b_met = b_improvement >= 70
        experiment_b = ExperimentReport(
            experiment_id="experiment-b-cascade",
            title="All-region model classification versus deterministic short circuit",
            input_sha256=benchmark_input_sha256(cases_b),
            sample_count=len(cases_b),
            baseline_strategy_id=b_baseline.strategy_id,
            optimized_strategy_id=b_optimized.strategy_id,
            target_metric="model-region count reduction",
            target_improvement_percent=70,
            actual_improvement_percent=b_improvement,
            target_status="met" if b_met else "not_met",
            result_reason=(
                "Deterministic preclassification met the approved model-region reduction target."
                if b_met
                else (
                    "The measured model-region reduction was below target; no policy or "
                    "residual checks were removed."
                )
            ),
            strategies=(b_baseline, b_optimized),
        )

    combined_input = hashlib.sha256(
        f"{experiment_a.input_sha256}:{experiment_b.input_sha256}".encode("ascii")
    ).hexdigest()
    report = BenchmarkReport(
        schema_version=1,
        recorded_at=datetime.now(UTC).isoformat(),
        source_commit=_source_commit(args.source_commit),
        runtime=runtime,
        workload=WorkloadEvidence(
            input_sha256=combined_input,
            policy_sha256=_sha256(Path("policies/v1/policy.yaml")),
            sample_count=len(cases_b),
            warm_repetitions=args.warm_runs,
            consistency_passes=args.consistency_passes,
        ),
        experiments=(experiment_a, experiment_b),
    )
    payload = report.model_dump(mode="json")
    _write_json(args.output, payload)
    for experiment in report.experiments:
        comparison_path = args.output.with_name(f"{experiment.experiment_id}.json")
        _write_json(comparison_path, experiment.model_dump(mode="json"))
        print(
            f"{experiment.experiment_id}: {experiment.target_status} "
            f"({experiment.actual_improvement_percent:.2f}% improvement)",
            flush=True,
        )
    print(f"Benchmark report: {args.output}", flush=True)
    optimized = (experiment_a.strategies[1], experiment_b.strategies[1])
    return 0 if all(item.quality.gate_passed for item in optimized) else 1


if __name__ == "__main__":
    raise SystemExit(main())
