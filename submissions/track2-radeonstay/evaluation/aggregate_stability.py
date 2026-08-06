#!/usr/bin/env python3
"""Validate and aggregate five independent RadeonStay C3 evidence bundles."""

from __future__ import annotations

import argparse
import json
import math
import sys
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, TypeVar

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from evaluation.compare_benchmarks import (  # noqa: E402
    file_sha256,
    indexed_runs,
    load_binding,
    load_checksum_manifest,
    load_json_object,
    load_report,
    load_server_configuration,
    require_integer,
    require_number,
    validate_binding,
)
from evaluation.configuration import normalized_report_service_configuration  # noqa: E402

EXPECTED_RUN_COUNT = 5
REPORT_SCHEMA_VERSION = 1
BUNDLE_DIGEST_ALGORITHM = "sha256-of-verified-SHA256SUMS.txt"
T = TypeVar("T")


@dataclass(frozen=True)
class ValidatedBundle:
    """One complete bundle after schema, checksum, quality, and GPU validation."""

    binding_path: Path
    bundle_sha256: str
    binding_manifest_sha256: str
    binding: dict[str, str]
    benchmark: dict[str, Any]
    retrieval_quality_gate: dict[str, bool]
    agent_quality_gates: dict[str, bool]
    quality_score: float
    benchmark_quality_gate: dict[str, Any]
    benchmark_success: dict[int, dict[str, int | float]]
    runtime_gpu: dict[str, Any]
    server_configuration: dict[str, str]

    @property
    def run_id(self) -> str:
        return self.binding["run_id"]

    @property
    def bundle_dir(self) -> Path:
        return self.binding_path.parent


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Validate exactly five same-configuration schema-v3 RadeonStay evidence "
            "bundles and emit one stability index."
        )
    )
    parser.add_argument(
        "--binding",
        action="append",
        type=Path,
        required=True,
        help="Path to one bundle binding-manifest.txt; repeat exactly five times",
    )
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args(argv)


def _require_all_boolean_gates(
    value: Any,
    label: str,
    *,
    includes_passed: bool,
) -> dict[str, bool]:
    if not isinstance(value, dict) or not value:
        raise ValueError(f"{label} must contain quality gates")
    if not all(isinstance(key, str) and type(item) is bool for key, item in value.items()):
        raise ValueError(f"{label} quality gates must be named booleans")
    gates = dict(value)
    if includes_passed and gates.pop("passed", None) is not True:
        raise ValueError(f"{label} aggregate quality gate did not pass")
    if not gates or not all(gates.values()):
        failed = sorted(key for key, passed in gates.items() if not passed)
        raise ValueError(f"{label} contains failed quality gates: {failed}")
    return dict(value)


def _benchmark_success(
    report: dict[str, Any],
    label: str,
) -> dict[int, dict[str, int | float]]:
    result: dict[int, dict[str, int | float]] = {}
    for concurrency, run in sorted(indexed_runs(report, label).items()):
        requests = run.get("requests")
        if not isinstance(requests, list) or not requests:
            raise ValueError(f"{label} concurrency {concurrency} has no request evidence")
        summary = run["summary"]
        request_count = len(requests)
        successful = require_integer(
            summary.get("successful"),
            f"{label}.c{concurrency}.successful",
        )
        success_rate = require_number(
            summary.get("success_rate"),
            f"{label}.c{concurrency}.success_rate",
        )
        model_metrics = summary.get("model_call_metrics")
        if not isinstance(model_metrics, dict):
            raise ValueError(f"{label} concurrency {concurrency} has no model metrics")
        failed_model_calls = require_integer(
            model_metrics.get("failed_calls"),
            f"{label}.c{concurrency}.failed_model_calls",
        )
        if successful != request_count or not math.isclose(success_rate, 1.0):
            raise ValueError(f"{label} concurrency {concurrency} is not 100% successful")
        if failed_model_calls != 0:
            raise ValueError(f"{label} concurrency {concurrency} has failed model calls")
        result[concurrency] = {
            "requests": request_count,
            "successful": successful,
            "success_rate": success_rate,
            "failed_model_calls": failed_model_calls,
        }
    return result


def _verified_bundle_sha256(bundle_dir: Path, label: str) -> str:
    checksum_path = bundle_dir / "SHA256SUMS.txt"
    if not checksum_path.is_file() or checksum_path.is_symlink():
        raise FileNotFoundError(f"{label} bundle has no regular SHA256SUMS.txt")
    checksums = load_checksum_manifest(checksum_path, label)
    for name, expected in sorted(checksums.items()):
        artifact = bundle_dir / name
        if not artifact.is_file() or artifact.is_symlink():
            raise FileNotFoundError(f"{label} bundle is missing regular file {name}")
        if file_sha256(artifact) != expected:
            raise ValueError(f"{label} bundle checksum mismatch: {name}")
    regular_files = {
        path.name
        for path in bundle_dir.iterdir()
        if path.is_file() and not path.is_symlink()
    }
    unbound = sorted(regular_files - set(checksums) - {checksum_path.name})
    if unbound:
        raise ValueError(f"{label} bundle contains files absent from SHA256SUMS.txt: {unbound}")
    return file_sha256(checksum_path)


def load_stability_bundle(binding_path: Path, label: str) -> ValidatedBundle:
    resolved_binding = binding_path.expanduser().resolve()
    binding = load_binding(resolved_binding, label)
    benchmark_path = resolved_binding.parent / binding["benchmark_file"]
    benchmark = load_report(benchmark_path, label)
    runtime_gpu = validate_binding(
        benchmark,
        benchmark_path,
        resolved_binding,
        binding,
        label,
    )
    if benchmark.get("deterministic_mode") is not False:
        raise ValueError(f"{label} benchmark must use the real local ROCm model path")

    retrieval = load_json_object(
        resolved_binding.parent / binding["retrieval_file"],
        f"{label} retrieval",
    )
    quality = load_json_object(
        resolved_binding.parent / binding["quality_file"],
        f"{label} Agent quality",
    )
    retrieval_quality_gate = _require_all_boolean_gates(
        retrieval.get("quality_gate"),
        f"{label} retrieval",
        includes_passed=True,
    )
    agent_quality_gates = _require_all_boolean_gates(
        quality.get("gates"),
        f"{label} Agent quality",
        includes_passed=False,
    )
    if quality.get("passed") is not True:
        raise ValueError(f"{label} Agent quality report did not pass")
    quality_score = require_number(
        (quality.get("metrics") or {}).get("total_score"),
        f"{label}.quality.total_score",
    )
    if quality_score != 300:
        raise ValueError(f"{label} Agent quality must be 300/300")
    benchmark_quality_gate = benchmark.get("quality_gate")
    if not isinstance(benchmark_quality_gate, dict):
        raise ValueError(f"{label} benchmark quality gate is missing")
    if benchmark_quality_gate.get("passed") is not True:
        raise ValueError(f"{label} benchmark quality gate did not pass")
    if benchmark_quality_gate.get("failures") != []:
        raise ValueError(f"{label} benchmark quality gate contains failures")

    return ValidatedBundle(
        binding_path=resolved_binding,
        bundle_sha256=_verified_bundle_sha256(resolved_binding.parent, label),
        binding_manifest_sha256=file_sha256(resolved_binding),
        binding=binding,
        benchmark=benchmark,
        retrieval_quality_gate=retrieval_quality_gate,
        agent_quality_gates=agent_quality_gates,
        quality_score=quality_score,
        benchmark_quality_gate=dict(benchmark_quality_gate),
        benchmark_success=_benchmark_success(benchmark, label),
        runtime_gpu=runtime_gpu,
        server_configuration=load_server_configuration(
            resolved_binding.parent / binding["server_log"]
        ),
    )


def _require_same(
    bundles: list[ValidatedBundle],
    field: str,
    getter: Callable[[ValidatedBundle], T],
) -> T:
    expected = getter(bundles[0])
    for bundle in bundles[1:]:
        if getter(bundle) != expected:
            raise ValueError(f"All stability bundles must match {field}")
    return expected


def _metric_range(values: list[tuple[str, float]]) -> dict[str, Any]:
    if len(values) != EXPECTED_RUN_COUNT:
        raise ValueError("A stability metric range requires exactly five values")
    numbers = [value for _, value in values]
    return {
        "minimum": round(min(numbers), 6),
        "maximum": round(max(numbers), 6),
        "spread": round(max(numbers) - min(numbers), 6),
        "values_by_run": [
            {"run_id": run_id, "value": round(value, 6)}
            for run_id, value in values
        ],
    }


def _benchmark_metrics(bundle: ValidatedBundle) -> dict[int, dict[str, float]]:
    metrics: dict[int, dict[str, float]] = {}
    for concurrency, run in sorted(indexed_runs(bundle.benchmark, bundle.run_id).items()):
        summary = run["summary"]
        metrics[concurrency] = {
            "latency_p50_ms": require_number(
                summary["latency_ms"].get("p50"),
                f"{bundle.run_id}.c{concurrency}.latency_p50_ms",
            ),
            "latency_p95_ms": require_number(
                summary["latency_ms"].get("p95"),
                f"{bundle.run_id}.c{concurrency}.latency_p95_ms",
            ),
            "successful_throughput_requests_per_second": require_number(
                summary.get("successful_throughput_requests_per_second"),
                f"{bundle.run_id}.c{concurrency}.successful_throughput",
            ),
        }
    return metrics


def build_stability_report(bundles: list[ValidatedBundle]) -> dict[str, Any]:
    if len(bundles) != EXPECTED_RUN_COUNT:
        raise ValueError("Stability acceptance requires exactly five bundles")
    run_ids = [bundle.run_id for bundle in bundles]
    if len(set(run_ids)) != EXPECTED_RUN_COUNT:
        raise ValueError("Stability bundles must use five distinct run_id values")
    bundle_dirs = [bundle.bundle_dir for bundle in bundles]
    if len(set(bundle_dirs)) != EXPECTED_RUN_COUNT:
        raise ValueError("Stability bundles must use five distinct directories")
    if len({bundle.bundle_sha256 for bundle in bundles}) != EXPECTED_RUN_COUNT:
        raise ValueError("Stability bundles must have five distinct bundle digests")

    for bundle in bundles:
        _require_all_boolean_gates(
            bundle.retrieval_quality_gate,
            f"{bundle.run_id} retrieval",
            includes_passed=True,
        )
        _require_all_boolean_gates(
            bundle.agent_quality_gates,
            f"{bundle.run_id} Agent quality",
            includes_passed=False,
        )
        if bundle.benchmark_quality_gate.get("passed") is not True:
            raise ValueError(f"{bundle.run_id} benchmark quality gate did not pass")
        if bundle.benchmark_quality_gate.get("failures") != []:
            raise ValueError(f"{bundle.run_id} benchmark contains gate failures")
        if bundle.quality_score != 300:
            raise ValueError(f"{bundle.run_id} Agent quality must be 300/300")
        for concurrency, status in bundle.benchmark_success.items():
            if status.get("success_rate") != 1.0 or status.get("failed_model_calls") != 0:
                raise ValueError(
                    f"{bundle.run_id} concurrency {concurrency} is not fully successful"
                )

    matched = {
        "commit": _require_same(bundles, "commit", lambda item: item.binding["commit"]),
        "project_tree": _require_same(
            bundles,
            "project_tree",
            lambda item: item.binding["project_tree"],
        ),
        "source_tree_sha256": _require_same(
            bundles,
            "source_tree_sha256",
            lambda item: item.binding["source_tree_sha256"],
        ),
        "suite_version": _require_same(
            bundles,
            "suite_version",
            lambda item: item.benchmark["suite_version"],
        ),
        "suite_sha256": _require_same(
            bundles,
            "suite_sha256",
            lambda item: item.benchmark["suite_sha256"],
        ),
        "policy_corpus_sha256": _require_same(
            bundles,
            "policy_corpus_sha256",
            lambda item: item.benchmark["policy_corpus_sha256"],
        ),
        "model_name": _require_same(
            bundles,
            "model_name",
            lambda item: item.benchmark["model_name"],
        ),
        "model_base_url": _require_same(
            bundles,
            "model_base_url",
            lambda item: item.benchmark["model_base_url"],
        ),
        "model_sha256": _require_same(
            bundles,
            "model_sha256",
            lambda item: item.binding["model_sha256"],
        ),
        "model_repository": _require_same(
            bundles,
            "model_repository",
            lambda item: item.binding["model_repository"],
        ),
        "model_revision": _require_same(
            bundles,
            "model_revision",
            lambda item: item.binding["model_revision"],
        ),
        "model_quantization": _require_same(
            bundles,
            "model_quantization",
            lambda item: item.binding["model_quantization"],
        ),
        "llama_cpp_commit": _require_same(
            bundles,
            "llama_cpp_commit",
            lambda item: item.binding["llama_cpp_commit"],
        ),
        "llama_server_sha256": _require_same(
            bundles,
            "llama_server_sha256",
            lambda item: item.binding["llama_server_sha256"],
        ),
        "hardware_identity_sha256": _require_same(
            bundles,
            "hardware_identity_sha256",
            lambda item: item.binding["hardware_identity_sha256"],
        ),
        "case_ids": _require_same(
            bundles,
            "case_ids",
            lambda item: item.benchmark["case_ids"],
        ),
        "request_case_ids": _require_same(
            bundles,
            "request_case_ids",
            lambda item: item.benchmark["request_case_ids"],
        ),
        "benchmark_configuration": _require_same(
            bundles,
            "benchmark configuration",
            lambda item: item.benchmark["configuration"],
        ),
        "request_configuration": _require_same(
            bundles,
            "request configuration",
            lambda item: item.benchmark["request_configuration"],
        ),
        "reported_service_configuration": _require_same(
            bundles,
            "reported service configuration",
            lambda item: normalized_report_service_configuration(
                item.benchmark,
                f"{item.run_id}.service_configuration",
            ),
        ),
        "server_configuration": _require_same(
            bundles,
            "server configuration",
            lambda item: item.server_configuration,
        ),
        "benchmark_quality_thresholds": _require_same(
            bundles,
            "benchmark quality thresholds",
            lambda item: item.benchmark_quality_gate.get("thresholds"),
        ),
        "retrieval_quality_gates": _require_same(
            bundles,
            "retrieval quality gates",
            lambda item: item.retrieval_quality_gate,
        ),
        "agent_quality_gates": _require_same(
            bundles,
            "Agent quality gates",
            lambda item: item.agent_quality_gates,
        ),
        "active_gpu_indices": _require_same(
            bundles,
            "active GPU indices",
            lambda item: item.runtime_gpu.get("common_active_gpu_indices"),
        ),
        "active_gpu_unique_ids": _require_same(
            bundles,
            "physical GPU unique IDs",
            lambda item: item.runtime_gpu.get("common_active_gpu_unique_ids"),
        ),
    }

    metrics_by_run = {bundle.run_id: _benchmark_metrics(bundle) for bundle in bundles}
    concurrency_levels = sorted(metrics_by_run[bundles[0].run_id])
    if not concurrency_levels:
        raise ValueError("Stability bundles contain no concurrency metrics")
    for bundle in bundles[1:]:
        if sorted(metrics_by_run[bundle.run_id]) != concurrency_levels:
            raise ValueError("Stability bundles contain different concurrency levels")

    aggregate_by_concurrency: list[dict[str, Any]] = []
    for concurrency in concurrency_levels:
        aggregate_by_concurrency.append(
            {
                "concurrency": concurrency,
                "latency_p50_ms": _metric_range(
                    [
                        (
                            bundle.run_id,
                            metrics_by_run[bundle.run_id][concurrency]["latency_p50_ms"],
                        )
                        for bundle in bundles
                    ]
                ),
                "latency_p95_ms": _metric_range(
                    [
                        (
                            bundle.run_id,
                            metrics_by_run[bundle.run_id][concurrency]["latency_p95_ms"],
                        )
                        for bundle in bundles
                    ]
                ),
                "successful_throughput_requests_per_second": _metric_range(
                    [
                        (
                            bundle.run_id,
                            metrics_by_run[bundle.run_id][concurrency][
                                "successful_throughput_requests_per_second"
                            ],
                        )
                        for bundle in bundles
                    ]
                ),
            }
        )

    bundle_index: list[dict[str, Any]] = []
    for index, bundle in enumerate(bundles, 1):
        peak_vram = require_number(
            bundle.runtime_gpu.get("peak_vram_used_reported"),
            f"{bundle.run_id}.peak_vram_used_reported",
        )
        bundle_index.append(
            {
                "index": index,
                "run_id": bundle.run_id,
                "binding_manifest": str(bundle.binding_path),
                "binding_manifest_sha256": bundle.binding_manifest_sha256,
                "bundle_sha256": bundle.bundle_sha256,
                "quality_total_score": round(bundle.quality_score, 6),
                "benchmark_success": {
                    str(key): value for key, value in sorted(bundle.benchmark_success.items())
                },
                "benchmark_metrics": {
                    str(key): value for key, value in sorted(metrics_by_run[bundle.run_id].items())
                },
                "peak_vram_used_reported": round(peak_vram, 6),
            }
        )

    return {
        "schema_version": REPORT_SCHEMA_VERSION,
        "report": "radeonstay-five-run-stability",
        "created_at_utc": datetime.now(UTC).isoformat(timespec="seconds"),
        "accepted": True,
        "run_count": EXPECTED_RUN_COUNT,
        "bundle_sha256_algorithm": BUNDLE_DIGEST_ALGORITHM,
        "matched_evidence": matched,
        "bundles": bundle_index,
        "aggregate": {
            "quality_total_score": _metric_range(
                [(bundle.run_id, bundle.quality_score) for bundle in bundles]
            ),
            "metrics_by_concurrency": aggregate_by_concurrency,
            "peak_vram_used_reported": _metric_range(
                [
                    (
                        bundle.run_id,
                        require_number(
                            bundle.runtime_gpu.get("peak_vram_used_reported"),
                            f"{bundle.run_id}.peak_vram_used_reported",
                        ),
                    )
                    for bundle in bundles
                ]
            ),
        },
        "assessment": {
            "status": "accepted",
            "accepted": True,
            "criteria": {
                "exactly_five_independent_run_ids": True,
                "same_source_suite_policy_model_server_and_configuration": True,
                "all_retrieval_and_agent_quality_gates_passed": True,
                "all_benchmark_requests_and_model_calls_succeeded": True,
                "same_physical_radeon_gpu": True,
            },
        },
    }


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if len(args.binding) != EXPECTED_RUN_COUNT:
        raise ValueError("--binding must be supplied exactly five times")
    binding_paths = [path.expanduser().resolve() for path in args.binding]
    if len(set(binding_paths)) != EXPECTED_RUN_COUNT:
        raise ValueError("Each --binding path must identify a distinct bundle")
    output_path = args.output.expanduser().resolve()
    if output_path.exists():
        raise FileExistsError(f"Refusing to overwrite stability evidence: {output_path}")
    if not output_path.parent.is_dir():
        raise FileNotFoundError(f"Output parent does not exist: {output_path.parent}")

    bundles = [
        load_stability_bundle(path, f"stability run {index}")
        for index, path in enumerate(binding_paths, 1)
    ]
    if any(bundle.bundle_dir in output_path.parents for bundle in bundles):
        raise ValueError("Stability output must not be written inside an immutable bundle")
    report = build_stability_report(bundles)
    rendered = json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    with output_path.open("x", encoding="utf-8") as handle:
        handle.write(rendered)
    print(
        json.dumps(
            {
                "output": str(output_path),
                "accepted": report["accepted"],
                "run_count": report["run_count"],
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
