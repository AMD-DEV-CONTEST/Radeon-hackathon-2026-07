#!/usr/bin/env python3
"""Prove that Run F uses the smallest declared safe context window."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

try:
    from evaluation.compare_benchmarks import (
        load_binding,
        validate_binding,
        validate_official_report,
        validate_quality_report,
    )
    from evaluation.configuration import normalized_report_service_configuration
    from evaluation.run_agent_eval import OFFICIAL_SUITE_SHA256, OFFICIAL_SUITE_VERSION
except ModuleNotFoundError:  # Direct ``python evaluation/validate_context_window.py``.
    from compare_benchmarks import (  # type: ignore[no-redef]
        load_binding,
        validate_binding,
        validate_official_report,
        validate_quality_report,
    )
    from configuration import (  # type: ignore[no-redef]
        normalized_report_service_configuration,
    )
    from run_agent_eval import (  # type: ignore[no-redef]
        OFFICIAL_SUITE_SHA256,
        OFFICIAL_SUITE_VERSION,
    )


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Validate selected context >= 1.25x the largest bound request and "
            "that it is the smallest safe declared candidate."
        )
    )
    parser.add_argument("--quality-report", type=Path, required=True)
    parser.add_argument("--benchmark-report", type=Path, required=True)
    parser.add_argument(
        "--binding",
        type=Path,
        help="Complete C3 binding manifest for formal post-bundle validation.",
    )
    parser.add_argument(
        "--allow-prebundle",
        action="store_true",
        help=(
            "Permit raw-report proof generation before the circular context artifact "
            "is added to its C3 bundle; formal consumers must revalidate with --binding."
        ),
    )
    parser.add_argument(
        "--selected-context-size",
        type=int,
        help=(
            "Run F context to prove. Omit on Run E to select the smallest safe "
            "candidate for the forthcoming F/G/H rows."
        ),
    )
    parser.add_argument("--candidate-context-sizes", required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args(argv)


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def load_json_object(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid {label} JSON: {path}") from exc
    if not isinstance(value, dict):
        raise ValueError(f"{label} must contain one JSON object")
    return value


def parse_context_candidates(value: str) -> list[int]:
    try:
        raw = [int(item.strip()) for item in value.split(",")]
    except ValueError as exc:
        raise ValueError("candidate context sizes must be comma-separated integers") from exc
    if not raw or any(item <= 0 for item in raw):
        raise ValueError("candidate context sizes must be positive")
    if len(raw) != len(set(raw)):
        raise ValueError("candidate context sizes must not contain duplicates")
    if raw != sorted(raw):
        raise ValueError("candidate context sizes must be in ascending order")
    return raw


def _quality_model_calls(report: dict[str, Any]) -> list[tuple[str, dict[str, Any]]]:
    calls: list[tuple[str, dict[str, Any]]] = []
    for case in report.get("cases", []):
        if not isinstance(case, dict):
            continue
        case_id = str(case.get("id", "unknown"))
        for trace in case.get("trace", []):
            if not isinstance(trace, dict):
                continue
            response = trace.get("response")
            if not isinstance(response, dict):
                continue
            for call in response.get("model_calls", []):
                if isinstance(call, dict):
                    calls.append((case_id, call))
    return calls


def _benchmark_model_calls(report: dict[str, Any]) -> list[tuple[str, dict[str, Any]]]:
    calls: list[tuple[str, dict[str, Any]]] = []
    for run in report.get("runs", []):
        if not isinstance(run, dict):
            continue
        concurrency = run.get("concurrency", "unknown")
        for request in run.get("requests", []):
            if not isinstance(request, dict):
                continue
            request_id = str(request.get("request_id", request.get("case_id", "unknown")))
            for call in request.get("model_calls", []):
                if isinstance(call, dict):
                    calls.append((f"c{concurrency}:{request_id}", call))
    return calls


def _request_max_tokens(call: dict[str, Any]) -> Any:
    for field in ("max_tokens", "request_max_tokens"):
        if field in call:
            return call[field]
    request = call.get("request")
    if isinstance(request, dict):
        return request.get("max_tokens")
    return None


def _token_observations(
    quality: dict[str, Any],
    benchmark: dict[str, Any],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    observations: list[dict[str, Any]] = []
    missing: list[dict[str, Any]] = []
    groups = (
        ("quality", _quality_model_calls(quality)),
        ("benchmark", _benchmark_model_calls(benchmark)),
    )
    for source, calls in groups:
        for record_id, call in calls:
            prompt_tokens = call.get("prompt_tokens")
            maximum_output_tokens = _request_max_tokens(call)
            missing_fields: list[str] = []
            if (
                isinstance(prompt_tokens, bool)
                or not isinstance(prompt_tokens, int)
                or prompt_tokens < 0
            ):
                missing_fields.append("prompt_tokens")
            if (
                isinstance(maximum_output_tokens, bool)
                or not isinstance(maximum_output_tokens, int)
                or maximum_output_tokens <= 0
            ):
                missing_fields.append("max_tokens")
            if missing_fields:
                missing.append(
                    {
                        "source": source,
                        "record_id": record_id,
                        "sequence": call.get("sequence"),
                        "purpose": call.get("purpose"),
                        "missing_or_invalid_fields": missing_fields,
                    }
                )
                continue
            observations.append(
                {
                    "source": source,
                    "record_id": record_id,
                    "sequence": call.get("sequence"),
                    "purpose": call.get("purpose"),
                    "ok": call.get("ok"),
                    "prompt_tokens": prompt_tokens,
                    "max_tokens": maximum_output_tokens,
                    "maximum_request_tokens": prompt_tokens + maximum_output_tokens,
                }
            )
    return observations, missing


def _full_quality_gate(report: dict[str, Any]) -> bool:
    metrics = report.get("metrics")
    gates = report.get("gates")
    return bool(
        report.get("passed") is True
        and isinstance(metrics, dict)
        and metrics.get("total_score") == 300
        and metrics.get("maximum_score") == 300
        and isinstance(gates, dict)
        and gates
        and all(value is True for value in gates.values())
    )


def _build_context_proof_from_validated(
    quality: dict[str, Any],
    benchmark: dict[str, Any],
    *,
    selected_context_size: int | None,
    candidate_context_sizes: list[int],
) -> dict[str, Any]:
    if (
        selected_context_size is not None
        and (
            isinstance(selected_context_size, bool)
            or not isinstance(selected_context_size, int)
            or selected_context_size <= 0
        )
    ):
        raise ValueError("selected context size must be positive")
    if not (
        isinstance(candidate_context_sizes, list)
        and candidate_context_sizes
        and all(
            type(item) is int and item > 0 for item in candidate_context_sizes
        )
        and candidate_context_sizes == sorted(set(candidate_context_sizes))
    ):
        raise ValueError(
            "context candidates must be positive, unique, and ascending"
        )
    if quality.get("evaluation") != "radeonstay-fixed-agent-suite":
        raise ValueError("quality report has the wrong evaluation type")
    if benchmark.get("benchmark") != "radeonstay-agent-end-to-end":
        raise ValueError("benchmark report has the wrong benchmark type")
    if quality.get("suite_sha256") != OFFICIAL_SUITE_SHA256:
        raise ValueError("quality report is not bound to the official suite")
    if benchmark.get("suite_sha256") != OFFICIAL_SUITE_SHA256:
        raise ValueError("benchmark report is not bound to the official suite")
    if not (
        quality.get("suite_version")
        == benchmark.get("suite_version")
        == OFFICIAL_SUITE_VERSION
    ):
        raise ValueError("quality and benchmark use the wrong suite version")

    failures: list[str] = []
    quality_gate_passed = _full_quality_gate(quality)
    if not quality_gate_passed:
        failures.append("quality_report_not_full_score_with_all_gates")
    benchmark_gate = benchmark.get("quality_gate")
    benchmark_gate_passed = bool(
        isinstance(benchmark_gate, dict)
        and benchmark_gate.get("passed") is True
        and benchmark_gate.get("failures") == []
    )
    benchmark_quality_report = benchmark.get("quality_report")
    benchmark_quality_binding_passed = bool(
        isinstance(benchmark_quality_report, dict)
        and benchmark_quality_report.get("passed") is True
        and benchmark_quality_report.get("total_score") == 300
    )
    if not benchmark_gate_passed:
        failures.append("benchmark_quality_gate_not_passed")
    if not benchmark_quality_binding_passed:
        failures.append("benchmark_not_bound_to_full_score_quality")

    fixed_fields_match = bool(
        quality.get("run_id") == benchmark.get("run_id")
        and quality.get("policy_corpus_sha256")
        == benchmark.get("policy_corpus_sha256")
        and quality.get("request_configuration")
        == benchmark.get("request_configuration")
        and quality.get("provenance") == benchmark.get("provenance")
        and quality.get("artifacts") == benchmark.get("artifacts")
    )
    if not fixed_fields_match:
        failures.append("quality_and_benchmark_binding_mismatch")
    quality_service = normalized_report_service_configuration(
        quality, "quality.service_configuration"
    )
    benchmark_service = normalized_report_service_configuration(
        benchmark, "benchmark.service_configuration"
    )
    service_configuration_match = quality_service == benchmark_service
    if not service_configuration_match:
        failures.append("quality_and_benchmark_service_configuration_mismatch")
    report_contexts_match = quality_service["ctx"] == benchmark_service["ctx"]
    context_matches_reports = bool(
        report_contexts_match
        and (
            selected_context_size is None
            or quality_service["ctx"] == selected_context_size
        )
    )
    if not report_contexts_match:
        failures.append("quality_and_benchmark_context_mismatch")
    elif selected_context_size is not None and not context_matches_reports:
        failures.append("selected_context_does_not_match_run_reports")

    observations, missing = _token_observations(quality, benchmark)
    failed_calls = [item for item in observations if item.get("ok") is not True]
    if missing:
        failures.append("model_calls_missing_request_token_evidence")
    if not observations:
        failures.append("no_model_call_token_evidence")
    if failed_calls:
        failures.append("model_calls_contain_failed_requests")
    maximum_request_tokens = max(
        (int(item["maximum_request_tokens"]) for item in observations),
        default=0,
    )
    required_context_size = math.ceil(maximum_request_tokens * 1.25)
    safe_candidates = [
        item for item in candidate_context_sizes if item >= required_context_size
    ]
    minimum_safe_candidate = safe_candidates[0] if safe_candidates else None
    if minimum_safe_candidate is None:
        failures.append("no_declared_candidate_meets_125_percent_request_margin")
    if selected_context_size is not None:
        if selected_context_size not in candidate_context_sizes:
            failures.append("selected_context_not_in_declared_candidates")
        if selected_context_size < required_context_size:
            failures.append("selected_context_below_125_percent_request_margin")
        if (
            minimum_safe_candidate is not None
            and selected_context_size != minimum_safe_candidate
        ):
            failures.append("selected_context_is_not_smallest_safe_candidate")

    gates = {
        "source_reports_full_quality": bool(
            quality_gate_passed
            and benchmark_gate_passed
            and benchmark_quality_binding_passed
        ),
        "quality_and_benchmark_binding_match": fixed_fields_match
        and service_configuration_match,
        "all_model_calls_have_request_token_evidence": bool(
            observations and not missing
        ),
        "all_model_calls_succeeded": bool(observations and not failed_calls),
        "quality_and_benchmark_context_match": report_contexts_match,
    }
    if selected_context_size is None:
        gates["minimum_safe_declared_candidate_selected_for_run_f"] = bool(
            observations and minimum_safe_candidate is not None
        )
    else:
        gates.update(
            {
                "selected_context_matches_run_f_reports": context_matches_reports,
                "selected_context_at_least_125_percent_of_max_request_tokens": bool(
                    observations and selected_context_size >= required_context_size
                ),
                "selected_context_is_smallest_safe_declared_candidate": bool(
                    minimum_safe_candidate is not None
                    and selected_context_size == minimum_safe_candidate
                ),
            }
        )
    return {
        "schema_version": 1,
        "proof": (
            "radeonstay-run-e-context-selection"
            if selected_context_size is None
            else "radeonstay-run-f-minimum-safe-context"
        ),
        "created_at_utc": datetime.now(UTC).isoformat(timespec="seconds"),
        "run_id": quality.get("run_id"),
        "suite_sha256": quality.get("suite_sha256"),
        "margin_multiplier": 1.25,
        "candidate_context_sizes": candidate_context_sizes,
        "selected_context_size": selected_context_size,
        "maximum_request_tokens": maximum_request_tokens,
        "required_context_size": required_context_size,
        "minimum_safe_candidate": minimum_safe_candidate,
        "headroom_tokens": (
            selected_context_size - maximum_request_tokens
            if selected_context_size is not None
            else None
        ),
        "headroom_ratio": (
            round(selected_context_size / maximum_request_tokens, 6)
            if maximum_request_tokens and selected_context_size is not None
            else None
        ),
        "token_evidence": {
            "observation_count": len(observations),
            "missing_evidence_count": len(missing),
            "observations": observations,
            "missing_evidence": missing,
            "failed_call_count": len(failed_calls),
        },
        "gates": gates,
        "passed": all(gates.values()),
        "failures": failures,
    }


def build_context_proof(
    quality: dict[str, Any],
    benchmark: dict[str, Any],
    *,
    selected_context_size: int | None,
    candidate_context_sizes: list[int],
) -> dict[str, Any]:
    """Recompute official raw evidence before deriving the context proof."""

    validate_quality_report(quality, "context quality")
    validate_official_report(benchmark, "context benchmark")
    return _build_context_proof_from_validated(
        quality,
        benchmark,
        selected_context_size=selected_context_size,
        candidate_context_sizes=candidate_context_sizes,
    )


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    output = args.output.expanduser().resolve()
    if output.exists():
        raise FileExistsError(f"Refusing to overwrite context proof: {output}")
    if not output.parent.is_dir():
        raise FileNotFoundError(f"Output parent does not exist: {output.parent}")
    quality_path = args.quality_report.expanduser().resolve()
    benchmark_path = args.benchmark_report.expanduser().resolve()
    binding_path = args.binding.expanduser().resolve() if args.binding else None
    if binding_path is None and not args.allow_prebundle:
        raise ValueError(
            "formal context validation requires --binding; use --allow-prebundle "
            "only while constructing the circular E/F bundle artifact"
        )
    if binding_path is not None and args.allow_prebundle:
        raise ValueError("--binding and --allow-prebundle are mutually exclusive")
    for label, path in (("quality", quality_path), ("benchmark", benchmark_path)):
        if not path.is_file() or path.is_symlink():
            raise FileNotFoundError(f"{label} report is not a regular file: {path}")
    candidates = parse_context_candidates(args.candidate_context_sizes)
    quality = load_json_object(quality_path, "quality report")
    benchmark = load_json_object(benchmark_path, "benchmark report")
    quality_sha256 = file_sha256(quality_path)
    benchmark_quality_report = benchmark.get("quality_report")
    if not isinstance(benchmark_quality_report, dict) or (
        benchmark_quality_report.get("sha256") != quality_sha256
    ):
        raise ValueError("benchmark is not bound to the supplied quality report")
    binding_sha256 = None
    if binding_path is not None:
        if not binding_path.is_file() or binding_path.is_symlink():
            raise FileNotFoundError(
                f"binding manifest is not a regular file: {binding_path}"
            )
        binding = load_binding(binding_path, "context")
        expected_quality_path = binding_path.parent / binding["quality_file"]
        if quality_path != expected_quality_path.resolve():
            raise ValueError("quality report must come from the bound C3 bundle")
        validate_binding(
            benchmark,
            benchmark_path,
            binding_path,
            binding,
            "context",
        )
        binding_sha256 = file_sha256(binding_path)
    report = build_context_proof(
        quality,
        benchmark,
        selected_context_size=args.selected_context_size,
        candidate_context_sizes=candidates,
    )
    report["sources"] = {
        "quality_report": quality_path.name,
        "quality_report_sha256": quality_sha256,
        "benchmark_report": benchmark_path.name,
        "benchmark_report_sha256": file_sha256(benchmark_path),
    }
    if binding_path is not None:
        report["sources"].update(
            {
                "binding_manifest": binding_path.name,
                "binding_manifest_sha256": binding_sha256,
            }
        )
    rendered = json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    with output.open("x", encoding="utf-8") as handle:
        handle.write(rendered)
    print(
        json.dumps(
            {
                "output": str(output),
                "passed": report["passed"],
                "selected_context_size": report["selected_context_size"],
                "minimum_safe_candidate": report["minimum_safe_candidate"],
            },
            sort_keys=True,
        )
    )
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
