#!/usr/bin/env python3
"""Select the best quality-gated Radeon configuration from complete A-H rows."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

try:
    from evaluation.compare_benchmarks import (
        OFFICIAL_CONCURRENCY,
        compare_metric,
        load_binding,
        load_report,
        normalized_report_service_configuration,
        require_number,
        validate_binding,
        validate_context_transition,
        validate_request_configuration,
    )
    from evaluation.quality_negative_evidence import (
        _active_gpu_identity_sha256,
        load_quality_negative_bundle,
    )
except ModuleNotFoundError:  # Direct ``python evaluation/select_winner.py``.
    from compare_benchmarks import (  # type: ignore[no-redef]
        OFFICIAL_CONCURRENCY,
        compare_metric,
        load_binding,
        load_report,
        normalized_report_service_configuration,
        require_number,
        validate_binding,
        validate_context_transition,
        validate_request_configuration,
    )
    from quality_negative_evidence import (  # type: ignore[no-redef]
        _active_gpu_identity_sha256,
        load_quality_negative_bundle,
    )

MATRIX_LABELS = tuple("ABCDEFGH")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
FORMAL_MATERIAL_THRESHOLD_PERCENT = 5.0
FORMAL_MAXIMUM_VRAM_PERCENT = 90.0
FORMAL_P95_SLACK_PERCENT = 5.0


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _safe_basename(value: Any, label: str) -> str:
    if (
        not isinstance(value, str)
        or not value
        or value in {".", ".."}
        or "/" in value
        or "\\" in value
        or Path(value).name != value
    ):
        raise ValueError(f"{label} must be a path-safe basename")
    return value


def _validated_candidate_sources(
    candidates: dict[str, tuple[dict[str, Any], dict[str, Any], dict[str, str]]],
    candidate_sources: dict[str, dict[str, str]],
) -> dict[str, dict[str, str]]:
    if set(candidate_sources) != set(candidates):
        raise ValueError("candidate source labels must exactly match candidate labels")
    normalized: dict[str, dict[str, str]] = {}
    required_fields = {
        "label",
        "benchmark_basename",
        "benchmark_sha256",
        "binding_basename",
        "binding_sha256",
    }
    for label in sorted(candidates):
        source = candidate_sources.get(label)
        if not isinstance(source, dict) or set(source) != required_fields:
            raise ValueError(f"{label} candidate source fields are incomplete")
        if source.get("label") != label:
            raise ValueError(f"{label} candidate source label does not match")
        benchmark_sha = source.get("benchmark_sha256")
        binding_sha = source.get("binding_sha256")
        if not isinstance(benchmark_sha, str) or not SHA256_RE.fullmatch(benchmark_sha):
            raise ValueError(f"{label} benchmark source SHA256 is invalid")
        if not isinstance(binding_sha, str) or not SHA256_RE.fullmatch(binding_sha):
            raise ValueError(f"{label} binding source SHA256 is invalid")
        normalized[label] = {
            "label": label,
            "benchmark_basename": _safe_basename(
                source.get("benchmark_basename"),
                f"{label} benchmark source basename",
            ),
            "benchmark_sha256": benchmark_sha,
            "binding_basename": _safe_basename(
                source.get("binding_basename"),
                f"{label} binding source basename",
            ),
            "binding_sha256": binding_sha,
        }
    return normalized


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Select the best eligible configuration from complete C3 A-H evidence "
            "rows. Exactly one complete row for every label A through H is required; "
            "quality- or performance-rejected rows remain bound negative experiments."
        )
    )
    parser.add_argument(
        "--candidate",
        action="append",
        nargs=3,
        metavar=("LABEL", "BENCHMARK", "BINDING"),
        required=True,
    )
    parser.add_argument(
        "--quality-negative",
        action="append",
        nargs=2,
        metavar=("LABEL", "MANIFEST"),
        default=[],
        help="A-only bound quality-negative evidence used when A is not 300/300",
    )
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--material-threshold-percent", type=float, default=5.0)
    parser.add_argument("--maximum-vram-percent", type=float, default=90.0)
    parser.add_argument("--p95-slack-percent", type=float, default=5.0)
    parser.add_argument("--require-accepted", action="store_true")
    return parser.parse_args(argv)


def _number_percent(value: Any, label: str) -> float:
    number = require_number(value, label)
    if not 0 < number <= 100:
        raise ValueError(f"{label} must be greater than 0 and at most 100")
    return number


def _indexed_summaries(report: dict[str, Any]) -> dict[int, dict[str, Any]]:
    summaries: dict[int, dict[str, Any]] = {}
    for row in report["runs"]:
        concurrency = row["concurrency"]
        summary = row["summary"]
        if concurrency in summaries:
            raise ValueError(f"duplicate concurrency row: {concurrency}")
        summaries[concurrency] = summary
    if tuple(sorted(summaries)) != OFFICIAL_CONCURRENCY:
        raise ValueError("winner selection requires concurrency 1, 2, and 4")
    return summaries


def _core_deltas(
    reference: dict[str, Any],
    candidate: dict[str, Any],
    *,
    threshold: float,
    reference_label: str,
    candidate_label: str,
) -> tuple[list[str], list[str]]:
    reference_runs = _indexed_summaries(reference)
    candidate_runs = _indexed_summaries(candidate)
    improved: list[str] = []
    regressed: list[str] = []
    for concurrency in OFFICIAL_CONCURRENCY:
        left = reference_runs[concurrency]
        right = candidate_runs[concurrency]
        metrics = {
            "latency_p50_ms": (
                left["latency_ms"]["p50"],
                right["latency_ms"]["p50"],
                True,
            ),
            "latency_p95_ms": (
                left["latency_ms"]["p95"],
                right["latency_ms"]["p95"],
                True,
            ),
            "successful_throughput_requests_per_second": (
                left["successful_throughput_requests_per_second"],
                right["successful_throughput_requests_per_second"],
                False,
            ),
            "effective_output_tokens_per_second_p50": (
                left["model_call_metrics"][
                    "effective_output_tokens_per_second_p50"
                ],
                right["model_call_metrics"][
                    "effective_output_tokens_per_second_p50"
                ],
                False,
            ),
            "effective_output_tokens_per_second_p95": (
                left["model_call_metrics"][
                    "effective_output_tokens_per_second_p95"
                ],
                right["model_call_metrics"][
                    "effective_output_tokens_per_second_p95"
                ],
                False,
            ),
        }
        for metric, (baseline_value, optimized_value, lower_is_better) in metrics.items():
            comparison = compare_metric(
                require_number(
                    baseline_value,
                    f"{reference_label}.c{concurrency}.{metric}",
                ),
                require_number(
                    optimized_value,
                    f"{candidate_label}.c{concurrency}.{metric}",
                ),
                lower_is_better=lower_is_better,
                material_threshold_percent=threshold,
            )
            qualified = f"c{concurrency}.{metric}"
            if comparison["material_improvement"]:
                improved.append(qualified)
            if comparison["material_regression"]:
                regressed.append(qualified)
    return improved, regressed


def _validate_matrix_shape(
    reports: dict[str, dict[str, Any]],
    *,
    reference_label: str,
) -> None:
    reference_service = normalized_report_service_configuration(
        reports[reference_label], f"{reference_label}.service_configuration"
    )
    base_context = reference_service["ctx"]
    optimized_contexts = {
        normalized_report_service_configuration(
            reports[label], f"{label}.service_configuration"
        )["ctx"]
        for label in reports
        if label >= "F"
    }
    if len(optimized_contexts) > 1:
        raise ValueError("F-H must use one optimized context size")
    optimized_context = next(iter(optimized_contexts), None)
    if optimized_context is not None and optimized_context >= base_context:
        raise ValueError("optimized context must be smaller than A-E context")

    for label, report in reports.items():
        request = validate_request_configuration(report, label)
        service = normalized_report_service_configuration(
            report, f"{label}.service_configuration"
        )
        declared_experiment = report.get("service_configuration", {}).get("experiment")
        if declared_experiment != label:
            raise ValueError(f"{label} report has the wrong experiment label")
        expected_request = {
            "thinking_enabled": label == "A",
            "schema_constrained": True,
            "fused_plan_evidence": label >= "E",
        }
        if request != expected_request:
            raise ValueError(f"{label} request configuration is not the A-H matrix row")
        expected_service = {
            "ctx": base_context if label <= "E" else optimized_context,
            "parallel": 4 if label >= "G" else 1,
            "batch": 256 if label <= "C" else 512,
            "ubatch": 64 if label <= "C" else 128,
            "flash_attn": "off" if label <= "B" else "on",
            "gpu_layers": 999,
            "cache_type_k": "q8_0" if label == "H" else "f16",
            "cache_type_v": "q8_0" if label == "H" else "f16",
            "log_verbosity": 5,
        }
        if service != expected_service:
            raise ValueError(f"{label} service configuration is not the A-H matrix row")


def _require_candidate_set(
    candidates: dict[str, object],
    quality_negatives: dict[str, object],
) -> str:
    if not quality_negatives:
        required = set(MATRIX_LABELS)
        reference = "A"
    elif set(quality_negatives) == {"A"}:
        required = set("BCDEFGH")
        reference = "B"
    else:
        raise ValueError("Only experiment A may be retained as a quality negative")
    observed = set(candidates)
    missing = sorted(required - observed)
    unexpected = sorted(observed - required)
    if observed != required:
        required_description = (
            "A-H complete candidates"
            if not quality_negatives
            else "B-H complete candidates plus one bound A quality negative"
        )
        raise ValueError(
            f"winner selection requires exactly {required_description}; "
            f"missing={missing}, unexpected={unexpected}"
        )
    return reference


def _quality_negative_reference_transition(
    negative_a: dict[str, Any],
    *,
    reference_report: dict[str, Any],
    reference_runtime: dict[str, Any],
    reference_binding: dict[str, str],
) -> dict[str, Any]:
    negative_run_id = negative_a.get("run_id")
    reference_run_id = reference_report.get("run_id")
    if not (
        isinstance(negative_run_id, str)
        and negative_run_id
        and isinstance(reference_run_id, str)
        and reference_run_id
        and negative_run_id != reference_run_id
    ):
        raise ValueError(
            "A quality-negative and B reference must use distinct non-empty run IDs"
        )
    quality_score = negative_a.get("quality_score")
    failed_quality_gates = negative_a.get("failed_quality_gates")
    if not (
        type(quality_score) is int
        and 0 <= quality_score < 300
        and negative_a.get("quality_maximum_score") == 300
        and isinstance(failed_quality_gates, list)
        and failed_quality_gates
        and all(isinstance(item, str) and item for item in failed_quality_gates)
    ):
        raise ValueError("A quality-negative evidence is not an explicit failed run")
    fixed_fields = (
        "commit",
        "project_tree",
        "source_tree_sha256",
        "model_sha256",
        "llama_server_sha256",
    )
    mismatches = [
        field
        for field in fixed_fields
        if negative_a.get(field) != reference_binding.get(field)
    ]
    if mismatches:
        raise ValueError(
            "A quality-negative evidence differs from the B reference: "
            f"{mismatches}"
        )

    negative_request = validate_request_configuration(
        {"request_configuration": negative_a.get("request_configuration")},
        "A quality-negative",
    )
    reference_request = validate_request_configuration(reference_report, "B")
    changed_request_fields = sorted(
        field
        for field in negative_request
        if negative_request[field] != reference_request[field]
    )
    if not (
        changed_request_fields == ["thinking_enabled"]
        and negative_request["thinking_enabled"] is True
        and reference_request["thinking_enabled"] is False
    ):
        raise ValueError(
            "A to B must change only thinking_enabled from true to false"
        )

    negative_service_raw = negative_a.get("service_configuration")
    reference_service = normalized_report_service_configuration(
        reference_report,
        "B.service_configuration",
    )
    if not isinstance(negative_service_raw, dict) or set(
        negative_service_raw
    ) != set(reference_service):
        raise ValueError(
            "A quality-negative manifest must retain every explicit service field, "
            "including ctx"
        )
    negative_service = normalized_report_service_configuration(
        {"service_configuration": negative_service_raw},
        "A quality-negative service_configuration",
    )
    changed_service_fields = sorted(
        field
        for field in negative_service
        if negative_service[field] != reference_service[field]
    )
    if changed_service_fields:
        raise ValueError(
            "A to B may not change service configuration fields: "
            f"{changed_service_fields}"
        )

    negative_gpu_ids = negative_a.get("active_gpu_unique_ids")
    negative_gpu_identity = _active_gpu_identity_sha256(
        negative_gpu_ids,
        "A quality-negative active GPU identity",
    )
    if negative_a.get("active_gpu_identity_sha256") != negative_gpu_identity:
        raise ValueError("A quality-negative active GPU identity digest is invalid")
    reference_gpu_ids = reference_runtime.get("common_active_gpu_unique_ids")
    reference_gpu_identity = _active_gpu_identity_sha256(
        reference_gpu_ids,
        "B reference active GPU identity",
    )
    if not (
        negative_gpu_ids == reference_gpu_ids
        and negative_gpu_identity == reference_gpu_identity
    ):
        raise ValueError(
            "A quality-negative evidence and B reference used different active GPUs"
        )
    if not (
        negative_a.get("offloaded_model_layers") == "41/41"
        and negative_a.get("gpu_activity_verified") is True
    ):
        raise ValueError(
            "A quality-negative evidence lacks 41/41 offload or active-GPU proof"
        )

    return {
        "mode": "A_quality_negative_B_reference",
        "quality_negative_experiment": "A",
        "quality_negative_run_id": negative_run_id,
        "performance_reference_experiment": "B",
        "performance_reference_run_id": reference_run_id,
        "performance_excluded_labels": ["A"],
        "performance_compared_labels": list("BCDEFGH"),
        "changed_request_fields": changed_request_fields,
        "changed_service_fields": changed_service_fields,
        "same_active_gpu_identity": True,
        "active_gpu_identity_sha256": negative_gpu_identity,
        "reference_hardware_identity_sha256": reference_binding.get(
            "hardware_identity_sha256"
        ),
        "a_gpu_offload": "41/41",
        "a_gpu_activity_verified": True,
        "a_quality_score": quality_score,
        "a_failed_quality_gates": sorted(failed_quality_gates),
    }


def _candidate_metrics(
    report: dict[str, Any], runtime: dict[str, Any]
) -> dict[str, Any]:
    summaries = _indexed_summaries(report)
    return {
        "single_request_p50_ms": require_number(
            summaries[1]["latency_ms"]["p50"], "single-request P50"
        ),
        "single_request_p95_ms": require_number(
            summaries[1]["latency_ms"]["p95"], "single-request P95"
        ),
        "concurrency_4_throughput_requests_per_second": require_number(
            summaries[4]["successful_throughput_requests_per_second"],
            "concurrency-4 throughput",
        ),
        "peak_vram_percent": require_number(
            runtime.get("peak_vram_utilization_percent"), "peak VRAM percent"
        ),
        "energy_per_successful_task_joules": (
            require_number(
                runtime["energy_per_successful_task_joules"],
                "energy per successful task",
            )
            if runtime.get("energy_per_successful_task_joules") is not None
            else None
        ),
        "energy_evidence_available": runtime.get("energy_evidence_available") is True,
        "energy_power_sample_count": runtime.get("power_sample_count"),
        "energy_estimation_method": runtime.get("energy_estimation_method"),
    }


def build_winner_report(
    candidates: dict[str, tuple[dict[str, Any], dict[str, Any], dict[str, str]]],
    *,
    candidate_sources: dict[str, dict[str, str]],
    material_threshold_percent: float,
    maximum_vram_percent: float,
    p95_slack_percent: float,
    quality_negatives: dict[str, dict[str, Any]] | None = None,
    quality_negative_sources: dict[str, dict[str, str]] | None = None,
) -> dict[str, Any]:
    material_threshold_percent = _number_percent(
        material_threshold_percent,
        "material-threshold-percent",
    )
    maximum_vram_percent = _number_percent(
        maximum_vram_percent,
        "maximum-vram-percent",
    )
    p95_slack_percent = _number_percent(
        p95_slack_percent,
        "p95-slack-percent",
    )
    if material_threshold_percent < FORMAL_MATERIAL_THRESHOLD_PERCENT:
        raise ValueError(
            "material threshold cannot be lower than the formal 5 percent floor"
        )
    if maximum_vram_percent > FORMAL_MAXIMUM_VRAM_PERCENT:
        raise ValueError("maximum VRAM percent cannot exceed the formal 90 percent cap")
    if p95_slack_percent > FORMAL_P95_SLACK_PERCENT:
        raise ValueError("P95 slack cannot exceed the formal 5 percent cap")
    quality_negatives = dict(quality_negatives or {})
    quality_negative_sources = dict(quality_negative_sources or {})
    reference_label = _require_candidate_set(candidates, quality_negatives)
    candidate_run_ids: dict[str, str] = {}
    for label, (report, _runtime, _binding) in candidates.items():
        run_id = report.get("run_id")
        if not isinstance(run_id, str) or not run_id:
            raise ValueError(f"{label} candidate has no run ID")
        prior_label = candidate_run_ids.get(run_id)
        if prior_label is not None:
            raise ValueError(
                f"Candidate run ID is reused by {prior_label} and {label}: {run_id}"
            )
        candidate_run_ids[run_id] = label
    for label, negative in quality_negatives.items():
        run_id = negative.get("run_id")
        if not isinstance(run_id, str) or not run_id:
            raise ValueError(f"{label} quality-negative evidence has no run ID")
        if run_id in candidate_run_ids:
            raise ValueError(
                "Quality-negative run ID is reused by candidate "
                f"{candidate_run_ids[run_id]}: {run_id}"
            )
    if set(quality_negative_sources) != set(quality_negatives):
        raise ValueError("Quality-negative source index does not match its evidence")
    for label, source in quality_negative_sources.items():
        if not isinstance(source, dict) or set(source) != {
            "label",
            "manifest_basename",
            "manifest_sha256",
        }:
            raise ValueError(f"{label} quality-negative source is incomplete")
        if source.get("label") != label or not SHA256_RE.fullmatch(
            str(source.get("manifest_sha256", ""))
        ):
            raise ValueError(f"{label} quality-negative source is invalid")
        _safe_basename(
            source.get("manifest_basename"),
            f"{label} quality-negative manifest basename",
        )
    sources = _validated_candidate_sources(candidates, candidate_sources)
    reports = {label: value[0] for label, value in candidates.items()}
    _validate_matrix_shape(reports, reference_label=reference_label)
    context_transition_verified = "E" in candidates and "F" in candidates
    if context_transition_verified:
        validate_context_transition(
            candidates["E"][0],
            candidates["F"][0],
            candidates["E"][1],
            candidates["F"][1],
        )

    reference_report = reports[reference_label]
    reference_binding = candidates[reference_label][2]
    workload_fields = (
        "suite_version",
        "suite_sha256",
        "policy_corpus_sha256",
        "case_ids",
        "request_case_ids",
        "configuration",
    )
    fixed_binding_fields = (
        "commit",
        "project_tree",
        "source_tree_sha256",
        "hardware_identity_sha256",
        "model_sha256",
        "llama_server_sha256",
        "model_repository",
        "model_revision",
        "model_quantization",
        "llama_cpp_commit",
    )
    for label, (report, _runtime, binding) in candidates.items():
        for field in fixed_binding_fields:
            if binding.get(field) != reference_binding.get(field):
                raise ValueError(
                    f"{label} differs from {reference_label} binding field {field}"
                )
        if report["suite_sha256"] != reference_report["suite_sha256"]:
            raise ValueError(f"{label} differs from {reference_label} suite")
        if report["policy_corpus_sha256"] != reference_report["policy_corpus_sha256"]:
            raise ValueError(
                f"{label} differs from {reference_label} policy corpus"
            )
        for field in workload_fields:
            if report.get(field) != reference_report.get(field):
                raise ValueError(
                    f"{label} differs from {reference_label} workload field {field}"
                )
    if quality_negatives:
        quality_reference_transition = _quality_negative_reference_transition(
            quality_negatives["A"],
            reference_report=reference_report,
            reference_runtime=candidates[reference_label][1],
            reference_binding=reference_binding,
        )
    else:
        quality_reference_transition = {
            "mode": "A_quality_qualified_reference",
            "quality_negative_experiment": None,
            "quality_negative_run_id": None,
            "performance_reference_experiment": "A",
            "performance_reference_run_id": reference_report.get("run_id"),
            "performance_excluded_labels": [],
            "performance_compared_labels": list(MATRIX_LABELS),
            "changed_request_fields": [],
            "changed_service_fields": [],
            "same_active_gpu_identity": None,
            "active_gpu_identity_sha256": None,
            "reference_hardware_identity_sha256": reference_binding.get(
                "hardware_identity_sha256"
            ),
            "a_gpu_offload": None,
            "a_gpu_activity_verified": None,
        }

    rows: dict[str, dict[str, Any]] = {}
    eligible: list[str] = []
    for label in sorted(candidates):
        report, runtime, _binding = candidates[label]
        quality_score = require_number(
            report["quality_report"]["total_score"], f"{label} quality score"
        )
        metrics = _candidate_metrics(report, runtime)
        reasons: list[str] = []
        improved: list[str] = []
        regressed: list[str] = []
        if quality_score != 300.0:
            reasons.append("quality_not_300_of_300")
        if report.get("quality_report", {}).get("passed") is not True:
            reasons.append("embedded_quality_report_not_passed")
        if report.get("quality_gate", {}).get("passed") is not True:
            reasons.append("benchmark_quality_gate_not_passed")
        if report.get("quality_gate", {}).get("failures") != []:
            reasons.append("benchmark_quality_gate_contains_failures")
        if metrics["peak_vram_percent"] >= maximum_vram_percent:
            reasons.append("peak_vram_not_strictly_below_limit")
        if label >= "F" and not context_transition_verified:
            reasons.append("context_transition_unverifiable_without_complete_E_and_F")
        if label != reference_label:
            improved, regressed = _core_deltas(
                reference_report,
                report,
                threshold=material_threshold_percent,
                reference_label=reference_label,
                candidate_label=label,
            )
            if not improved:
                reasons.append("no_core_metric_improved_materially_vs_reference")
            if regressed:
                reasons.append("core_metric_regressed_materially_vs_reference")
        else:
            reasons.append("reference_not_an_optimized_candidate")
        accepted = not reasons
        if accepted:
            eligible.append(label)
        rows[label] = {
            "run_id": report["run_id"],
            "quality_score": quality_score,
            "request_configuration": validate_request_configuration(report, label),
            "service_configuration": normalized_report_service_configuration(
                report, f"{label}.service_configuration"
            ),
            "metrics": metrics,
            "materially_improved_core_metrics_vs_reference": improved,
            "materially_regressed_core_metrics_vs_reference": regressed,
            "eligible": accepted,
            "rejection_reasons": reasons,
            "source": dict(sources[label]),
        }

    p95_limit = None
    latency_eligible: list[str] = []
    if eligible:
        best_p95 = min(
            float(rows[label]["metrics"]["single_request_p95_ms"])
            for label in eligible
        )
        p95_limit = best_p95 * (1.0 + p95_slack_percent / 100.0)
        latency_eligible = [
            label
            for label in eligible
            if float(rows[label]["metrics"]["single_request_p95_ms"]) <= p95_limit
        ]
        for label in set(eligible) - set(latency_eligible):
            rows[label]["eligible"] = False
            rows[label]["rejection_reasons"].append(
                "single_request_p95_exceeds_best_latency_by_more_than_slack"
            )

    energy_tie_break_available = bool(latency_eligible) and all(
        rows[label]["metrics"]["energy_evidence_available"] is True
        and isinstance(
            rows[label]["metrics"]["energy_per_successful_task_joules"],
            (int, float),
        )
        and not isinstance(
            rows[label]["metrics"]["energy_per_successful_task_joules"], bool
        )
        and float(
            rows[label]["metrics"]["energy_per_successful_task_joules"]
        )
        > 0
        and isinstance(rows[label]["metrics"]["energy_power_sample_count"], int)
        and rows[label]["metrics"]["energy_power_sample_count"] > 0
        and rows[label]["metrics"]["energy_estimation_method"]
        == (
            "mean same-GPU ROCm power samples within benchmark window multiplied "
            "by benchmark wall duration"
        )
        for label in latency_eligible
    )

    def sort_key(label: str) -> tuple[float, float, float, float, str]:
        metrics = rows[label]["metrics"]
        energy = metrics["energy_per_successful_task_joules"]
        return (
            -float(metrics["concurrency_4_throughput_requests_per_second"]),
            float(metrics["single_request_p50_ms"]),
            float(metrics["peak_vram_percent"]),
            float(energy) if energy_tie_break_available else 0.0,
            label,
        )

    winner = min(latency_eligible, key=sort_key) if latency_eligible else None
    accepted = winner is not None
    observed_labels = sorted(set(candidates) | set(quality_negatives))
    missing_labels = sorted(set(MATRIX_LABELS) - set(observed_labels))
    return {
        "schema_version": 2,
        "created_at_utc": datetime.now(UTC).isoformat(timespec="seconds"),
        "selection": "radeonstay-a-h-winner",
        "matrix_completeness": {
            "required_labels": list(MATRIX_LABELS),
            "observed_labels": observed_labels,
            "quality_qualified_labels": sorted(candidates),
            "quality_negative_labels": sorted(quality_negatives),
            "missing_labels": missing_labels,
            "reference_experiment": reference_label,
            "reference_complete": reference_label in candidates,
            "baseline_complete": "A" in observed_labels,
            "optimized_complete_count": len(set(candidates) - {reference_label}),
            "selection_candidate_set_complete": not missing_labels,
            "complete": not missing_labels,
        },
        "quality_reference_transition": quality_reference_transition,
        "fixed_binding": {
            field: reference_binding[field] for field in fixed_binding_fields
        },
        "fixed_workload": {
            field: reference_report[field] for field in workload_fields
        },
        "candidate_sources": sources,
        "quality_negative_sources": quality_negative_sources,
        "rules": {
            "quality_score_required": 300,
            "material_threshold_percent": material_threshold_percent,
            "maximum_vram_percent_strict": maximum_vram_percent,
            "single_request_p95_slack_percent": p95_slack_percent,
            "ordering": [
                "highest concurrency-4 successful throughput",
                "lowest single-request P50",
                "lowest peak VRAM percent",
                (
                    "lowest energy per successful task only when every "
                    "latency-eligible candidate has same-window evidence"
                ),
            ],
        },
        "candidates": rows,
        "best_single_request_p95_limit_ms": (
            round(p95_limit, 6) if p95_limit is not None else None
        ),
        "energy_tie_break": {
            "status": (
                "available_for_complete_latency_eligible_cohort"
                if energy_tie_break_available
                else "unavailable_for_cohort"
            ),
            "used": energy_tie_break_available,
            "latency_eligible_candidates": latency_eligible,
            "rule": (
                "Energy is used only when every latency-eligible candidate has "
                "positive same-GPU power samples from its bound benchmark window."
            ),
        },
        "assessment": {
            "accepted": accepted,
            "optimization_winner": "optimized" if accepted else "not_accepted",
            "winner_experiment": winner,
            "winner_source": dict(sources[winner]) if winner is not None else None,
            "reference_experiment": reference_label,
            "reference_source": dict(sources[reference_label]),
            "recommended_configuration": winner or reference_label,
            "recommended_request_configuration": (
                rows[winner]["request_configuration"] if winner is not None else None
            ),
            "recommended_service_configuration": (
                rows[winner]["service_configuration"] if winner is not None else None
            ),
            "rejection_reasons": [] if accepted else ["no_eligible_optimized_candidate"],
        },
    }


def selection_exit_code(report: dict[str, Any], *, require_accepted: bool) -> int:
    accepted = report.get("assessment", {}).get("accepted")
    if type(accepted) is not bool:
        raise ValueError("winner report is missing assessment.accepted")
    return 1 if require_accepted and not accepted else 0


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    threshold = _number_percent(
        args.material_threshold_percent, "material-threshold-percent"
    )
    maximum_vram = _number_percent(args.maximum_vram_percent, "maximum-vram-percent")
    p95_slack = _number_percent(args.p95_slack_percent, "p95-slack-percent")
    output = args.output.expanduser().resolve()
    if not output.parent.is_dir():
        raise FileNotFoundError(f"output parent does not exist: {output.parent}")

    candidates: dict[
        str, tuple[dict[str, Any], dict[str, Any], dict[str, str]]
    ] = {}
    candidate_sources: dict[str, dict[str, str]] = {}
    quality_negatives: dict[str, dict[str, Any]] = {}
    quality_negative_sources: dict[str, dict[str, str]] = {}
    for raw_label, raw_manifest in args.quality_negative:
        label = raw_label.upper()
        if label != "A" or label in quality_negatives:
            raise ValueError(f"invalid or duplicate quality-negative label: {raw_label}")
        manifest_path = Path(raw_manifest).expanduser().resolve()
        quality_negatives[label] = load_quality_negative_bundle(
            manifest_path,
            expected_label=label,
        )
        quality_negative_sources[label] = {
            "label": label,
            "manifest_basename": manifest_path.name,
            "manifest_sha256": file_sha256(manifest_path),
        }
    for raw_label, raw_report, raw_binding in args.candidate:
        label = raw_label.upper()
        if label not in MATRIX_LABELS or label in candidates:
            raise ValueError(f"invalid or duplicate matrix label: {raw_label}")
        report_path = Path(raw_report).expanduser().resolve()
        binding_path = Path(raw_binding).expanduser().resolve()
        report = load_report(report_path, label)
        binding = load_binding(binding_path, label)
        runtime = validate_binding(report, report_path, binding_path, binding, label)
        candidates[label] = (report, runtime, binding)
        candidate_sources[label] = {
            "label": label,
            "benchmark_basename": report_path.name,
            "benchmark_sha256": file_sha256(report_path),
            "binding_basename": binding_path.name,
            "binding_sha256": file_sha256(binding_path),
        }

    report = build_winner_report(
        candidates,
        candidate_sources=candidate_sources,
        material_threshold_percent=threshold,
        maximum_vram_percent=maximum_vram,
        p95_slack_percent=p95_slack,
        quality_negatives=quality_negatives,
        quality_negative_sources=quality_negative_sources,
    )
    rendered = json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    with output.open("x", encoding="utf-8") as handle:
        handle.write(rendered)
    print(
        json.dumps(
            {
                "output": str(output),
                "accepted": report["assessment"]["accepted"],
                "optimization_winner": report["assessment"][
                    "optimization_winner"
                ],
                "winner_experiment": report["assessment"]["winner_experiment"],
            }
        )
    )
    return selection_exit_code(report, require_accepted=args.require_accepted)


if __name__ == "__main__":
    raise SystemExit(main())
