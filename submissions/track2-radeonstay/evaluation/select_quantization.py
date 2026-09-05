#!/usr/bin/env python3
"""Select Q5/Q4 only when independently proven better than full-quality Q6."""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

try:
    from evaluation.compare_benchmarks import (
        OFFICIAL_CONCURRENCY,
        load_binding,
        load_report,
        normalized_report_service_configuration,
        require_number,
        validate_binding,
        validate_request_configuration,
    )
except ModuleNotFoundError:  # Direct ``python evaluation/select_quantization.py``.
    from compare_benchmarks import (  # type: ignore[no-redef]
        OFFICIAL_CONCURRENCY,
        load_binding,
        load_report,
        normalized_report_service_configuration,
        require_number,
        validate_binding,
        validate_request_configuration,
    )

QUANTIZATION_LABELS = ("Q6", "Q5", "Q4")
FORMAL_MINIMUM_P95_IMPROVEMENT_PERCENT = 10.0
FORMAL_MINIMUM_C4_THROUGHPUT_IMPROVEMENT_PERCENT = 15.0
FORMAL_MAXIMUM_CORE_REGRESSION_PERCENT = 5.0
FORMAL_MAXIMUM_VRAM_PERCENT = 90.0


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _safe_basename(path: Path, label: str) -> str:
    name = path.name
    if not name or name in {".", ".."} or "/" in name or "\\" in name:
        raise ValueError(f"{label} must have a path-safe basename")
    return name


def _load_validated_candidates(
    candidate_paths: dict[str, tuple[Path, Path]],
) -> tuple[
    dict[str, tuple[dict[str, Any], dict[str, Any], dict[str, str]]],
    dict[str, dict[str, str]],
]:
    candidates: dict[
        str, tuple[dict[str, Any], dict[str, Any], dict[str, str]]
    ] = {}
    sources: dict[str, dict[str, str]] = {}
    for label, (raw_report_path, raw_binding_path) in candidate_paths.items():
        report_path = Path(raw_report_path).expanduser().resolve()
        binding_path = Path(raw_binding_path).expanduser().resolve()
        for source_label, path in (
            (f"{label} benchmark", report_path),
            (f"{label} binding", binding_path),
        ):
            if not path.is_file() or path.is_symlink():
                raise FileNotFoundError(f"{source_label} is not a regular file: {path}")
        report = load_report(report_path, label)
        binding = load_binding(binding_path, label)
        runtime = validate_binding(report, report_path, binding_path, binding, label)
        candidates[label] = (report, runtime, binding)
        sources[label] = {
            "label": label,
            "benchmark_basename": _safe_basename(
                report_path, f"{label} benchmark"
            ),
            "benchmark_sha256": file_sha256(report_path),
            "binding_basename": _safe_basename(binding_path, f"{label} binding"),
            "binding_sha256": file_sha256(binding_path),
        }
    return candidates, sources


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Keep Q6 by default; admit Q5/Q4 only with full quality and >=10% "
            "single-request P95 or >=15% concurrency-4 throughput improvement."
        )
    )
    parser.add_argument(
        "--candidate",
        action="append",
        nargs=3,
        metavar=("Q6|Q5|Q4", "BENCHMARK", "BINDING"),
        required=True,
    )
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--minimum-p95-improvement-percent",
        type=float,
        default=FORMAL_MINIMUM_P95_IMPROVEMENT_PERCENT,
        help="May be stricter than 10, but the formal 10%% floor cannot be lowered.",
    )
    parser.add_argument(
        "--minimum-c4-throughput-improvement-percent",
        type=float,
        default=FORMAL_MINIMUM_C4_THROUGHPUT_IMPROVEMENT_PERCENT,
        help="May be stricter than 15, but the formal 15%% floor cannot be lowered.",
    )
    parser.add_argument("--require-complete", action="store_true")
    parser.add_argument("--require-replacement", action="store_true")
    return parser.parse_args(argv)


def _positive_percent(value: Any, label: str) -> float:
    number = require_number(value, label)
    if not 0 < number <= 100:
        raise ValueError(f"{label} must be greater than 0 and at most 100")
    return number


def _formal_threshold(value: Any, label: str, *, minimum: float) -> float:
    number = _positive_percent(value, label)
    if number < minimum:
        raise ValueError(
            f"{label} cannot be lower than the formal {minimum:g}% release threshold"
        )
    return number


def _indexed_summaries(report: dict[str, Any]) -> dict[int, dict[str, Any]]:
    summaries: dict[int, dict[str, Any]] = {}
    for row in report.get("runs", []):
        if not isinstance(row, dict) or not isinstance(row.get("summary"), dict):
            raise ValueError("quantization report contains an invalid run")
        concurrency = row.get("concurrency")
        if concurrency in summaries:
            raise ValueError(f"duplicate concurrency row: {concurrency}")
        summaries[concurrency] = row["summary"]
    if tuple(sorted(summaries)) != OFFICIAL_CONCURRENCY:
        raise ValueError("quantization selection requires concurrency 1, 2, and 4")
    return summaries


def _optional_number(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return require_number(value, "optional metric")
    except ValueError:
        return None


def _metrics(
    report: dict[str, Any], runtime: dict[str, Any]
) -> dict[str, float | None]:
    summaries = _indexed_summaries(report)
    return {
        "single_request_p95_ms": require_number(
            summaries[1]["latency_ms"]["p95"], "single-request P95"
        ),
        "concurrency_4_successful_throughput_requests_per_second": require_number(
            summaries[4]["successful_throughput_requests_per_second"],
            "concurrency-4 throughput",
        ),
        "peak_vram_percent": _optional_number(
            runtime.get("peak_vram_utilization_percent")
        ),
    }


def _vram_gate(metrics: dict[str, float | None]) -> tuple[bool, str | None]:
    peak_vram = metrics["peak_vram_percent"]
    if peak_vram is None or peak_vram <= 0:
        return False, "peak_vram_evidence_missing_or_invalid"
    if peak_vram >= FORMAL_MAXIMUM_VRAM_PERCENT:
        return False, "peak_vram_not_strictly_below_90_percent"
    return True, None


def _improvement_percent(
    baseline: float,
    candidate: float,
    *,
    lower_is_better: bool,
) -> float:
    if baseline <= 0:
        raise ValueError("baseline metric must be positive")
    delta = baseline - candidate if lower_is_better else candidate - baseline
    return round(delta / baseline * 100.0, 6)


def _full_quality(report: dict[str, Any]) -> bool:
    quality = report.get("quality_report")
    gate = report.get("quality_gate")
    return bool(
        isinstance(quality, dict)
        and quality.get("passed") is True
        and quality.get("total_score") == 300
        and isinstance(gate, dict)
        and gate.get("passed") is True
        and gate.get("failures") == []
    )


def _quantization_matches(label: str, binding: dict[str, str]) -> bool:
    declared = binding.get("model_quantization", "").upper().replace("-", "_")
    return declared == label or declared.startswith(f"{label}_")


def _build_quantization_report_from_validated(
    candidates: dict[str, tuple[dict[str, Any], dict[str, Any], dict[str, str]]],
    *,
    candidate_sources: dict[str, dict[str, str]],
    minimum_p95_improvement_percent: float,
    minimum_c4_throughput_improvement_percent: float,
) -> dict[str, Any]:
    minimum_p95_improvement_percent = _formal_threshold(
        minimum_p95_improvement_percent,
        "minimum_p95_improvement_percent",
        minimum=FORMAL_MINIMUM_P95_IMPROVEMENT_PERCENT,
    )
    minimum_c4_throughput_improvement_percent = _formal_threshold(
        minimum_c4_throughput_improvement_percent,
        "minimum_c4_throughput_improvement_percent",
        minimum=FORMAL_MINIMUM_C4_THROUGHPUT_IMPROVEMENT_PERCENT,
    )
    if "Q6" not in candidates:
        raise ValueError("Q6 baseline evidence is required")
    unknown = sorted(set(candidates) - set(QUANTIZATION_LABELS))
    if unknown:
        raise ValueError(f"unsupported quantization labels: {unknown}")
    if set(candidate_sources) != set(candidates):
        raise ValueError("quantization source labels must match candidate labels")
    run_ids = [value[0].get("run_id") for value in candidates.values()]
    if any(not isinstance(run_id, str) or not run_id for run_id in run_ids):
        raise ValueError("every quantization candidate requires a non-empty run-id")
    if len(set(run_ids)) != len(run_ids):
        raise ValueError("quantization candidates require independent run-ids")
    q6_report, q6_runtime, q6_binding = candidates["Q6"]
    q6_metrics = _metrics(q6_report, q6_runtime)
    fixed_binding_fields = (
        "commit",
        "project_tree",
        "source_tree_sha256",
        "hardware_identity_sha256",
        "llama_server_sha256",
        "model_repository",
        "model_revision",
        "llama_cpp_commit",
    )
    fixed_report_fields = (
        "suite_version",
        "suite_sha256",
        "case_ids",
        "request_case_ids",
        "policy_corpus_sha256",
        "configuration",
    )
    q6_request = validate_request_configuration(q6_report, "Q6")
    q6_service = normalized_report_service_configuration(
        q6_report, "Q6.service_configuration"
    )
    rows: dict[str, dict[str, Any]] = {}
    baseline_reasons: list[str] = []
    q6_vram_passed, q6_vram_reason = _vram_gate(q6_metrics)
    if not _full_quality(q6_report):
        baseline_reasons.append("q6_not_bound_to_300_of_300_and_all_quality_gates")
    if not _quantization_matches("Q6", q6_binding):
        baseline_reasons.append("q6_quantization_not_explicitly_bound")
    if q6_vram_reason is not None:
        baseline_reasons.append(f"q6_{q6_vram_reason}")
    rows["Q6"] = {
        "status": "baseline" if not baseline_reasons else "rejected",
        "run_id": q6_report.get("run_id"),
        "model_quantization": q6_binding.get("model_quantization"),
        "model_sha256": q6_binding.get("model_sha256"),
        "metrics": q6_metrics,
        "quality_300_of_300_with_all_gates": _full_quality(q6_report),
        "peak_vram_strictly_below_90_percent": q6_vram_passed,
        "replacement_eligible": False,
        "rejection_reasons": baseline_reasons,
        "source": dict(candidate_sources["Q6"]),
    }

    eligible: list[str] = []
    for label in ("Q5", "Q4"):
        if label not in candidates:
            rows[label] = {
                "status": "not_assessed",
                "replacement_eligible": False,
                "rejection_reasons": ["complete_candidate_bundle_not_supplied"],
            }
            continue
        report, runtime, binding = candidates[label]
        metrics = _metrics(report, runtime)
        vram_passed, vram_reason = _vram_gate(metrics)
        reasons: list[str] = []
        if baseline_reasons:
            reasons.append("q6_baseline_not_release_eligible")
        if not _full_quality(report):
            reasons.append("quality_not_300_of_300_with_all_gates")
        if not _quantization_matches(label, binding):
            reasons.append("quantization_label_not_explicitly_bound")
        for field in fixed_binding_fields:
            if not q6_binding.get(field) or binding.get(field) != q6_binding.get(field):
                reasons.append(f"binding_mismatch:{field}")
        if binding.get("model_sha256") == q6_binding.get("model_sha256"):
            reasons.append("candidate_model_artifact_is_identical_to_q6")
        for field in fixed_report_fields:
            if report.get(field) != q6_report.get(field):
                reasons.append(f"report_mismatch:{field}")
        if validate_request_configuration(report, label) != q6_request:
            reasons.append("request_configuration_mismatch")
        if normalized_report_service_configuration(
            report, f"{label}.service_configuration"
        ) != q6_service:
            reasons.append("service_configuration_mismatch")
        if runtime.get("common_active_gpu_unique_ids") != q6_runtime.get(
            "common_active_gpu_unique_ids"
        ):
            reasons.append("active_gpu_identity_mismatch")
        if vram_reason is not None:
            reasons.append(vram_reason)

        p95_improvement = _improvement_percent(
            q6_metrics["single_request_p95_ms"],
            metrics["single_request_p95_ms"],
            lower_is_better=True,
        )
        c4_improvement = _improvement_percent(
            q6_metrics[
                "concurrency_4_successful_throughput_requests_per_second"
            ],
            metrics[
                "concurrency_4_successful_throughput_requests_per_second"
            ],
            lower_is_better=False,
        )
        threshold_met = bool(
            p95_improvement >= minimum_p95_improvement_percent
            or c4_improvement >= minimum_c4_throughput_improvement_percent
        )
        if not threshold_met:
            reasons.append("neither_replacement_performance_threshold_met")
        core_metric_improvements = {
            "single_request_p95_ms": p95_improvement,
            "concurrency_4_successful_throughput_requests_per_second": c4_improvement,
        }
        material_core_regressions = sorted(
            metric
            for metric, improvement in core_metric_improvements.items()
            if improvement <= -FORMAL_MAXIMUM_CORE_REGRESSION_PERCENT
        )
        if material_core_regressions:
            reasons.append("core_metric_regressed_by_at_least_5_percent")
        accepted = not reasons
        if accepted:
            eligible.append(label)
        rows[label] = {
            "status": "eligible" if accepted else "rejected",
            "run_id": report.get("run_id"),
            "model_quantization": binding.get("model_quantization"),
            "model_sha256": binding.get("model_sha256"),
            "metrics": metrics,
            "quality_300_of_300_with_all_gates": _full_quality(report),
            "peak_vram_strictly_below_90_percent": vram_passed,
            "single_request_p95_improvement_percent_vs_q6": p95_improvement,
            "concurrency_4_throughput_improvement_percent_vs_q6": c4_improvement,
            "performance_threshold_met": threshold_met,
            "material_core_regressions_vs_q6": material_core_regressions,
            "no_core_metric_regressed_by_5_percent_or_more": not (
                material_core_regressions
            ),
            "replacement_eligible": accepted,
            "rejection_reasons": reasons,
            "source": dict(candidate_sources[label]),
        }

    def replacement_sort_key(label: str) -> tuple[float, float, int]:
        metrics = rows[label]["metrics"]
        return (
            -float(
                metrics[
                    "concurrency_4_successful_throughput_requests_per_second"
                ]
            ),
            float(metrics["single_request_p95_ms"]),
            0 if label == "Q5" else 1,
        )

    winner = min(eligible, key=replacement_sort_key) if eligible else None
    complete = all(label in candidates for label in QUANTIZATION_LABELS)
    baseline_ready = not baseline_reasons
    recommended = winner or ("Q6" if baseline_ready else None)
    return {
        "schema_version": 1,
        "selection": "radeonstay-model-quantization",
        "created_at_utc": datetime.now(UTC).isoformat(timespec="seconds"),
        "rules": {
            "default_quantization": "Q6",
            "same_model_repository_and_revision_required": True,
            "quality_score_required": 300,
            "all_quality_gates_required": True,
            "minimum_single_request_p95_improvement_percent": (
                minimum_p95_improvement_percent
            ),
            "minimum_concurrency_4_throughput_improvement_percent": (
                minimum_c4_throughput_improvement_percent
            ),
            "formal_threshold_floors_cannot_be_lowered": True,
            "maximum_core_metric_regression_percent": (
                FORMAL_MAXIMUM_CORE_REGRESSION_PERCENT
            ),
            "peak_vram_must_be_strictly_below_percent": (
                FORMAL_MAXIMUM_VRAM_PERCENT
            ),
            "replacement_condition": "P95 threshold OR concurrency-4 threshold",
            "replacement_safety_condition": (
                "No tracked core metric may regress by 5% or more; all bound "
                "quality, permission, confirmation, citation, state, stress, and "
                "benchmark gates must remain passed."
            ),
        },
        "fixed_model_source": {
            "model_repository": q6_binding.get("model_repository"),
            "model_revision": q6_binding.get("model_revision"),
        },
        "candidate_sources": candidate_sources,
        "complete_candidate_set": complete,
        "candidates": rows,
        "assessment": {
            "baseline_ready": baseline_ready,
            "replacement_accepted": winner is not None,
            "recommended_quantization": recommended,
            "selected_source": (
                dict(candidate_sources[recommended])
                if recommended is not None
                else None
            ),
            "winning_replacement": winner,
            "reason": (
                "qualified_replacement"
                if winner is not None
                else (
                    "retain_q6_no_candidate_met_all_gates"
                    if baseline_ready
                    else "no_valid_q6_baseline"
                )
            ),
        },
    }


def build_quantization_report(
    candidate_paths: dict[str, tuple[Path, Path]],
    *,
    minimum_p95_improvement_percent: float,
    minimum_c4_throughput_improvement_percent: float,
) -> dict[str, Any]:
    """Load and verify complete bundle paths before selecting a quantization."""

    if "Q6" not in candidate_paths:
        raise ValueError("Q6 baseline evidence is required")
    unknown = sorted(set(candidate_paths) - set(QUANTIZATION_LABELS))
    if unknown:
        raise ValueError(f"unsupported quantization labels: {unknown}")
    for label, value in candidate_paths.items():
        if (
            not isinstance(value, tuple)
            or len(value) != 2
            or not all(isinstance(item, (str, Path)) for item in value)
        ):
            raise ValueError(
                f"{label} candidate must provide benchmark and binding paths"
            )
    candidates, sources = _load_validated_candidates(candidate_paths)
    return _build_quantization_report_from_validated(
        candidates,
        candidate_sources=sources,
        minimum_p95_improvement_percent=minimum_p95_improvement_percent,
        minimum_c4_throughput_improvement_percent=(
            minimum_c4_throughput_improvement_percent
        ),
    )


def selection_exit_code(
    report: dict[str, Any],
    *,
    require_complete: bool,
    require_replacement: bool,
) -> int:
    assessment = report.get("assessment")
    if not isinstance(assessment, dict):
        raise ValueError("quantization report is missing assessment")
    if assessment.get("baseline_ready") is not True:
        return 1
    if require_complete and report.get("complete_candidate_set") is not True:
        return 1
    if require_replacement and assessment.get("replacement_accepted") is not True:
        return 1
    return 0


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    p95_threshold = _formal_threshold(
        args.minimum_p95_improvement_percent,
        "minimum-p95-improvement-percent",
        minimum=FORMAL_MINIMUM_P95_IMPROVEMENT_PERCENT,
    )
    throughput_threshold = _formal_threshold(
        args.minimum_c4_throughput_improvement_percent,
        "minimum-c4-throughput-improvement-percent",
        minimum=FORMAL_MINIMUM_C4_THROUGHPUT_IMPROVEMENT_PERCENT,
    )
    output = args.output.expanduser().resolve()
    if output.exists():
        raise FileExistsError(f"Refusing to overwrite quantization report: {output}")
    if not output.parent.is_dir():
        raise FileNotFoundError(f"Output parent does not exist: {output.parent}")

    candidate_paths: dict[str, tuple[Path, Path]] = {}
    for raw_label, raw_report, raw_binding in args.candidate:
        label = raw_label.upper()
        if label not in QUANTIZATION_LABELS or label in candidate_paths:
            raise ValueError(f"invalid or duplicate quantization label: {raw_label}")
        report_path = Path(raw_report).expanduser().resolve()
        binding_path = Path(raw_binding).expanduser().resolve()
        candidate_paths[label] = (report_path, binding_path)

    report = build_quantization_report(
        candidate_paths,
        minimum_p95_improvement_percent=p95_threshold,
        minimum_c4_throughput_improvement_percent=throughput_threshold,
    )
    rendered = json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    with output.open("x", encoding="utf-8") as handle:
        handle.write(rendered)
    print(
        json.dumps(
            {
                "output": str(output),
                "complete_candidate_set": report["complete_candidate_set"],
                **report["assessment"],
            },
            sort_keys=True,
        )
    )
    return selection_exit_code(
        report,
        require_complete=args.require_complete,
        require_replacement=args.require_replacement,
    )


if __name__ == "__main__":
    raise SystemExit(main())
