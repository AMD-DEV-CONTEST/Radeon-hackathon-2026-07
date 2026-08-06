#!/usr/bin/env python3
"""Fail-closed acceptance for the bound winner, stability set, and long soak."""

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
        FATAL_SERVER_RE,
        load_binding,
        normalized_report_service_configuration,
        require_number,
        server_gate_zero_call_allowed,
        validate_binding,
        validate_request_configuration,
    )
except ModuleNotFoundError:  # Direct ``python evaluation/validate_soak.py``.
    from compare_benchmarks import (  # type: ignore[no-redef]
        FATAL_SERVER_RE,
        load_binding,
        normalized_report_service_configuration,
        require_number,
        server_gate_zero_call_allowed,
        validate_binding,
        validate_request_configuration,
    )

SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
FORMAL_MIN_DURATION_SECONDS = 1800.0
FORMAL_MAX_VRAM_PERCENT = 90.0
FORMAL_MIN_LIFECYCLES = 5
FORMAL_MIN_REPETITIONS = 3
OFFICIAL_CONCURRENCY = (1, 2, 4)
OFFICIAL_CASE_IDS = (
    *(f"KQ-{index:03d}" for index in range(1, 9)),
    "TOOL-001",
    "TOOL-002",
    "TOOL-003",
    "MS-001",
    "MS-002",
    "MEM-002",
    "SEC-004",
    "SEC-005",
)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Validate one long, full-quality lifecycle of the selected winner."
    )
    parser.add_argument("--winner-report", type=Path, required=True)
    parser.add_argument("--stability-report", type=Path, required=True)
    parser.add_argument("--benchmark", type=Path, required=True)
    parser.add_argument("--binding", type=Path, required=True)
    parser.add_argument("--minimum-duration-seconds", type=float, default=1800.0)
    parser.add_argument("--maximum-vram-percent", type=float, default=90.0)
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


def _parse_utc(value: Any, label: str) -> datetime:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{label} is missing")
    normalized = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError as exc:
        raise ValueError(f"{label} is invalid") from exc
    if parsed.tzinfo is None:
        raise ValueError(f"{label} must include a timezone")
    return parsed.astimezone(UTC)


def _require_sha256(value: Any, label: str) -> str:
    if not isinstance(value, str) or not SHA256_RE.fullmatch(value):
        raise ValueError(f"{label} must be a lowercase SHA256")
    return value


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


def _winner_sources(
    winner: dict[str, Any],
    winner_rows: dict[str, Any],
    winner_label: str,
    reference_label: str,
    qualified_labels: list[str],
) -> tuple[dict[str, str], dict[str, str]]:
    sources = winner.get("candidate_sources")
    expected_labels = set(qualified_labels)
    if (
        not isinstance(sources, dict)
        or set(sources) != expected_labels
        or set(winner_rows) != expected_labels
    ):
        raise ValueError(
            "winner candidates and candidate_sources must exactly match the "
            "quality-qualified labels"
        )
    if reference_label not in sources or winner_label not in sources:
        raise ValueError(
            "winner sources must contain the reference and selected candidate"
        )
    required = {
        "label",
        "benchmark_basename",
        "benchmark_sha256",
        "binding_basename",
        "binding_sha256",
    }
    for label in sorted(sources):
        source = sources.get(label)
        if not isinstance(source, dict) or set(source) != required:
            raise ValueError(f"winner source {label} fields are incomplete")
        if source.get("label") != label:
            raise ValueError(f"winner source {label} has the wrong label")
        _safe_basename(source.get("benchmark_basename"), f"winner {label} benchmark")
        _safe_basename(source.get("binding_basename"), f"winner {label} binding")
        _require_sha256(source.get("benchmark_sha256"), f"winner {label} benchmark")
        _require_sha256(source.get("binding_sha256"), f"winner {label} binding")
        row = winner_rows.get(label)
        if not isinstance(row, dict) or row.get("source") != source:
            raise ValueError(f"winner row {label} does not match its source index")
    selected = sources[winner_label]
    reference = sources[reference_label]
    assessment = winner.get("assessment")
    if not isinstance(assessment, dict):
        raise ValueError("winner assessment is missing")
    if assessment.get("winner_source") != selected:
        raise ValueError("accepted winner source does not match the selected candidate")
    if assessment.get("reference_source") != reference:
        raise ValueError("accepted reference source does not match the reference candidate")
    return dict(selected), dict(reference)


def _validate_quality_negative_sources(
    winner: dict[str, Any],
    negative_labels: list[str],
) -> None:
    sources = winner.get("quality_negative_sources")
    if not isinstance(sources, dict) or set(sources) != set(negative_labels):
        raise ValueError(
            "winner quality_negative_sources must exactly match the "
            "quality-negative labels"
        )
    required = {"label", "manifest_basename", "manifest_sha256"}
    for label in negative_labels:
        source = sources.get(label)
        if not isinstance(source, dict) or set(source) != required:
            raise ValueError(f"winner quality-negative source {label} is incomplete")
        if source.get("label") != label:
            raise ValueError(
                f"winner quality-negative source {label} has the wrong label"
            )
        _safe_basename(
            source.get("manifest_basename"),
            f"winner quality-negative {label} manifest",
        )
        _require_sha256(
            source.get("manifest_sha256"),
            f"winner quality-negative {label} manifest",
        )


def _validated_configuration(value: Any, label: str) -> tuple[int, dict[str, Any]]:
    if not isinstance(value, dict):
        raise ValueError(f"{label} benchmark configuration is missing")
    repetitions = value.get("repetitions")
    if (
        isinstance(repetitions, bool)
        or not isinstance(repetitions, int)
        or repetitions < FORMAL_MIN_REPETITIONS
    ):
        raise ValueError(
            f"{label} requires at least {FORMAL_MIN_REPETITIONS} repetitions"
        )
    if tuple(value.get("concurrency") or ()) != OFFICIAL_CONCURRENCY:
        raise ValueError(f"{label} requires concurrency 1,2,4")
    if value.get("min_success_rate") != 1.0:
        raise ValueError(f"{label} must require 100% request success")
    if value.get("min_citation_hit_rate") != 1.0:
        raise ValueError(f"{label} must require 100% citation success")
    return repetitions, dict(value)


def _validate_official_workload(
    report: dict[str, Any],
    label: str,
) -> dict[str, Any]:
    if tuple(report.get("case_ids") or ()) != OFFICIAL_CASE_IDS:
        raise ValueError(f"{label} must use the official 16-case workload")
    repetitions, configuration = _validated_configuration(
        report.get("configuration"), label
    )
    expected_case_ids = list(OFFICIAL_CASE_IDS) * repetitions
    if report.get("request_case_ids") != expected_case_ids:
        raise ValueError(f"{label} request_case_ids do not match the official workload")
    runs = report.get("runs")
    if not isinstance(runs, list) or len(runs) != len(OFFICIAL_CONCURRENCY):
        raise ValueError(f"{label} must contain exactly three concurrency runs")
    if tuple(
        row.get("concurrency") for row in runs if isinstance(row, dict)
    ) != OFFICIAL_CONCURRENCY:
        raise ValueError(f"{label} run order must be concurrency 1,2,4")

    request_ids: set[str] = set()
    success_by_concurrency: dict[str, dict[str, int | float]] = {}
    for run in runs:
        concurrency = run["concurrency"]
        requests = run.get("requests")
        if not isinstance(requests, list) or len(requests) != len(expected_case_ids):
            raise ValueError(
                f"{label} concurrency {concurrency} requires at least "
                f"{len(OFFICIAL_CASE_IDS) * FORMAL_MIN_REPETITIONS} requests"
            )
        if [
            item.get("case_id") for item in requests if isinstance(item, dict)
        ] != expected_case_ids:
            raise ValueError(
                f"{label} concurrency {concurrency} has the wrong case sequence"
            )
        for item in requests:
            request_id = item.get("request_id")
            if (
                not isinstance(request_id, str)
                or not request_id
                or request_id in request_ids
            ):
                raise ValueError(f"{label} contains a missing or duplicate request_id")
            request_ids.add(request_id)
        summary = run.get("summary")
        if not isinstance(summary, dict):
            raise ValueError(f"{label} concurrency {concurrency} summary is missing")
        successful = summary.get("successful")
        success_rate = summary.get("success_rate")
        model_metrics = summary.get("model_call_metrics")
        failed_calls = (
            model_metrics.get("failed_calls")
            if isinstance(model_metrics, dict)
            else None
        )
        if (
            isinstance(successful, bool)
            or not isinstance(successful, int)
            or successful != len(requests)
            or success_rate != 1.0
            or isinstance(failed_calls, bool)
            or not isinstance(failed_calls, int)
            or failed_calls != 0
        ):
            raise ValueError(
                f"{label} concurrency {concurrency} did not pass every request/model call"
            )
        success_by_concurrency[str(concurrency)] = {
            "requests": len(requests),
            "successful": successful,
            "success_rate": success_rate,
            "failed_model_calls": failed_calls,
        }
    return {
        "case_ids": list(OFFICIAL_CASE_IDS),
        "request_case_ids": expected_case_ids,
        "configuration": configuration,
        "success_by_concurrency": success_by_concurrency,
    }


def _all_boolean_gates(value: Any, label: str) -> bool:
    if not isinstance(value, dict) or not value:
        raise ValueError(f"{label} gates are missing")
    if not all(isinstance(key, str) and type(item) is bool for key, item in value.items()):
        raise ValueError(f"{label} gates must be named booleans")
    return all(value.values())


def _raw_health(report: dict[str, Any]) -> dict[str, Any]:
    request_count = 0
    successful_request_count = 0
    model_call_count = 0
    failed_model_call_count = 0
    server_gate_zero_call_response_count = 0
    request_errors: list[dict[str, Any]] = []
    model_errors: list[dict[str, Any]] = []
    for run in report.get("runs", []):
        if not isinstance(run, dict):
            continue
        concurrency = run.get("concurrency")
        for request in run.get("requests", []):
            if not isinstance(request, dict):
                continue
            request_count += 1
            if request.get("ok") is True:
                successful_request_count += 1
            else:
                request_errors.append(
                    {
                        "concurrency": concurrency,
                        "request_id": request.get("request_id"),
                        "error_type": request.get("error_type"),
                    }
                )
            calls = request.get("model_calls")
            if not isinstance(calls, list):
                model_errors.append(
                    {
                        "concurrency": concurrency,
                        "request_id": request.get("request_id"),
                        "reason": "invalid_model_calls",
                    }
                )
                continue
            if not calls:
                if request.get("ok") is True and server_gate_zero_call_allowed(
                    request
                ):
                    server_gate_zero_call_response_count += 1
                    continue
                model_errors.append(
                    {
                        "concurrency": concurrency,
                        "request_id": request.get("request_id"),
                        "reason": "missing_model_calls_or_server_gate",
                    }
                )
                continue
            for call in calls:
                model_call_count += 1
                if not isinstance(call, dict) or call.get("ok") is not True:
                    failed_model_call_count += 1
                    model_errors.append(
                        {
                            "concurrency": concurrency,
                            "request_id": request.get("request_id"),
                            "sequence": call.get("sequence") if isinstance(call, dict) else None,
                            "purpose": call.get("purpose") if isinstance(call, dict) else None,
                            "error_type": (
                                call.get("error_type")
                                if isinstance(call, dict)
                                else "invalid_call"
                            ),
                        }
                    )
    return {
        "request_count": request_count,
        "successful_request_count": successful_request_count,
        "request_success_rate": (
            round(successful_request_count / request_count, 6)
            if request_count
            else 0.0
        ),
        "model_call_count": model_call_count,
        "failed_model_call_count": failed_model_call_count,
        "server_gate_zero_call_response_count": (
            server_gate_zero_call_response_count
        ),
        "request_errors": request_errors,
        "model_errors": model_errors,
    }


def _load_stability_runtime_proofs(
    stability: dict[str, Any],
) -> list[dict[str, Any]]:
    bundles = stability.get("bundles")
    if not isinstance(bundles, list):
        raise ValueError("stability report bundles are missing")
    proofs: list[dict[str, Any]] = []
    for index, row in enumerate(bundles, 1):
        if not isinstance(row, dict):
            raise ValueError(f"stability bundle {index} is invalid")
        raw_binding_path = row.get("binding_manifest")
        if not isinstance(raw_binding_path, str) or not raw_binding_path:
            raise ValueError(f"stability bundle {index} binding path is missing")
        binding_path = Path(raw_binding_path).expanduser().resolve()
        if not binding_path.is_file() or binding_path.is_symlink():
            raise FileNotFoundError(
                f"stability bundle {index} binding is not a regular file: "
                f"{binding_path}"
            )
        binding_sha = file_sha256(binding_path)
        if binding_sha != _require_sha256(
            row.get("binding_manifest_sha256"),
            f"stability bundle {index} binding",
        ):
            raise ValueError(f"stability bundle {index} binding SHA256 changed")
        binding = load_binding(binding_path, f"stability bundle {index}")
        benchmark_path = binding_path.parent / binding["benchmark_file"]
        benchmark = load_json_object(benchmark_path, f"stability bundle {index} benchmark")
        workload = _validate_official_workload(
            benchmark, f"stability bundle {index}"
        )
        runtime = validate_binding(
            benchmark,
            benchmark_path,
            binding_path,
            binding,
            f"stability bundle {index}",
        )
        server_path = binding_path.parent / binding["server_log"]
        server_text = server_path.read_text(encoding="utf-8", errors="replace")
        fatal_lines = [
            line[:500]
            for line in server_text.splitlines()
            if FATAL_SERVER_RE.search(line)
        ]
        proofs.append(
            {
                "run_id": binding["run_id"],
                "binding_manifest_sha256": binding_sha,
                "benchmark_sha256": file_sha256(benchmark_path),
                "server_log_sha256": file_sha256(server_path),
                "peak_vram_utilization_percent": require_number(
                    runtime.get("peak_vram_utilization_percent"),
                    f"stability bundle {index} peak VRAM percent",
                ),
                "fatal_server_lines": fatal_lines,
                "workload": workload,
                "raw_health": _raw_health(benchmark),
            }
        )
    return proofs


def _validate_stability(
    stability: dict[str, Any],
    winner: dict[str, Any],
    winner_row: dict[str, Any],
    runtime_proofs: list[dict[str, Any]],
    *,
    maximum_vram_percent: float,
) -> dict[str, Any]:
    if (
        stability.get("schema_version") != 1
        or stability.get("report") != "radeonstay-five-run-stability"
        or stability.get("accepted") is not True
        or stability.get("assessment", {}).get("accepted") is not True
    ):
        raise ValueError("stability report must be an accepted five-run report")
    bundles = stability.get("bundles")
    run_count = stability.get("run_count")
    if (
        isinstance(run_count, bool)
        or not isinstance(run_count, int)
        or run_count < FORMAL_MIN_LIFECYCLES
        or not isinstance(bundles, list)
        or len(bundles) != run_count
    ):
        raise ValueError(
            f"stability report requires at least {FORMAL_MIN_LIFECYCLES} lifecycles"
        )
    if len(runtime_proofs) != run_count:
        raise ValueError("stability runtime proof count does not match run_count")

    matched = stability.get("matched_evidence")
    fixed_binding = winner.get("fixed_binding")
    fixed_workload = winner.get("fixed_workload")
    if not isinstance(matched, dict) or not isinstance(fixed_binding, dict):
        raise ValueError("stability or winner fixed evidence is missing")
    if not isinstance(fixed_workload, dict):
        raise ValueError("winner fixed workload evidence is missing")
    for field in (
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
    ):
        if matched.get(field) != fixed_binding.get(field):
            raise ValueError(f"stability differs from winner field {field}")
    workload_mapping = {
        "suite_version": "suite_version",
        "suite_sha256": "suite_sha256",
        "policy_corpus_sha256": "policy_corpus_sha256",
        "case_ids": "case_ids",
        "request_case_ids": "request_case_ids",
        "benchmark_configuration": "configuration",
    }
    for stability_field, winner_field in workload_mapping.items():
        if matched.get(stability_field) != fixed_workload.get(winner_field):
            raise ValueError(
                f"stability differs from winner workload field {stability_field}"
            )
    if matched.get("request_configuration") != winner_row.get(
        "request_configuration"
    ):
        raise ValueError("stability request configuration differs from winner")
    if matched.get("reported_service_configuration") != winner_row.get(
        "service_configuration"
    ):
        raise ValueError("stability service configuration differs from winner")
    repetitions, _configuration = _validated_configuration(
        matched.get("benchmark_configuration"), "stability"
    )
    expected_case_ids = list(OFFICIAL_CASE_IDS) * repetitions
    if matched.get("case_ids") != list(OFFICIAL_CASE_IDS):
        raise ValueError("stability does not bind the official 16-case workload")
    if matched.get("request_case_ids") != expected_case_ids:
        raise ValueError("stability request workload does not match repetitions")
    if not _all_boolean_gates(
        matched.get("retrieval_quality_gates"), "stability retrieval"
    ):
        raise ValueError("stability retrieval quality gates did not all pass")
    if not _all_boolean_gates(
        matched.get("agent_quality_gates"), "stability Agent"
    ):
        raise ValueError("stability Agent quality/safety gates did not all pass")

    run_ids: list[str] = []
    binding_hashes: list[str] = []
    bundle_hashes: list[str] = []
    proof_by_run = {
        proof.get("run_id"): proof
        for proof in runtime_proofs
        if isinstance(proof, dict) and isinstance(proof.get("run_id"), str)
    }
    if len(proof_by_run) != run_count:
        raise ValueError("stability runtime proofs must use unique run IDs")
    lifecycle_rows: list[dict[str, Any]] = []
    for index, row in enumerate(bundles, 1):
        if not isinstance(row, dict):
            raise ValueError(f"stability bundle {index} is invalid")
        run_id = row.get("run_id")
        if not isinstance(run_id, str) or not run_id:
            raise ValueError(f"stability bundle {index} run_id is invalid")
        run_ids.append(run_id)
        binding_hash = _require_sha256(
            row.get("binding_manifest_sha256"),
            f"stability bundle {index} binding",
        )
        bundle_hash = _require_sha256(
            row.get("bundle_sha256"), f"stability bundle {index} bundle"
        )
        binding_hashes.append(binding_hash)
        bundle_hashes.append(bundle_hash)
        if row.get("quality_total_score") != 300:
            raise ValueError(f"stability bundle {index} quality is not 300/300")
        success = row.get("benchmark_success")
        if not isinstance(success, dict) or set(success) != {"1", "2", "4"}:
            raise ValueError(
                f"stability bundle {index} must prove concurrency 1,2,4"
            )
        minimum_requests = len(OFFICIAL_CASE_IDS) * FORMAL_MIN_REPETITIONS
        for concurrency in ("1", "2", "4"):
            status = success.get(concurrency)
            if not isinstance(status, dict):
                raise ValueError(
                    f"stability bundle {index} concurrency {concurrency} is missing"
                )
            requests = status.get("requests")
            if (
                isinstance(requests, bool)
                or not isinstance(requests, int)
                or requests < minimum_requests
                or status.get("successful") != requests
                or status.get("success_rate") != 1.0
                or status.get("failed_model_calls") != 0
            ):
                raise ValueError(
                    f"stability bundle {index} concurrency {concurrency} is incomplete"
                )
        proof = proof_by_run.get(run_id)
        if proof is None or proof.get("binding_manifest_sha256") != binding_hash:
            raise ValueError(
                f"stability bundle {index} runtime proof is not source-bound"
            )
        peak_vram = require_number(
            proof.get("peak_vram_utilization_percent"),
            f"stability bundle {index} peak VRAM percent",
        )
        if peak_vram >= maximum_vram_percent:
            raise ValueError(
                f"stability bundle {index} peak VRAM is not strictly below the limit"
            )
        if proof.get("fatal_server_lines") != []:
            raise ValueError(
                f"stability bundle {index} contains an OOM/fatal/crash marker"
            )
        raw_health = proof.get("raw_health")
        if not (
            isinstance(raw_health, dict)
            and raw_health.get("request_count")
            == len(expected_case_ids) * len(OFFICIAL_CONCURRENCY)
            and raw_health.get("successful_request_count")
            == raw_health.get("request_count")
            and raw_health.get("request_success_rate") == 1.0
            and raw_health.get("model_call_count", 0) > 0
            and raw_health.get("failed_model_call_count") == 0
            and raw_health.get("request_errors") == []
            and raw_health.get("model_errors") == []
        ):
            raise ValueError(
                f"stability bundle {index} raw requests/model calls did not all pass"
            )
        proof_workload = proof.get("workload")
        if not isinstance(proof_workload, dict):
            raise ValueError(f"stability bundle {index} workload proof is missing")
        if proof_workload.get("case_ids") != list(OFFICIAL_CASE_IDS):
            raise ValueError(f"stability bundle {index} workload changed")
        if proof_workload.get("request_case_ids") != expected_case_ids:
            raise ValueError(f"stability bundle {index} repetitions changed")
        if proof_workload.get("configuration") != matched.get(
            "benchmark_configuration"
        ):
            raise ValueError(f"stability bundle {index} configuration changed")
        if proof_workload.get("success_by_concurrency") != success:
            raise ValueError(
                f"stability bundle {index} success summary changed"
            )
        lifecycle_rows.append(
            {
                "run_id": run_id,
                "binding_manifest_sha256": binding_hash,
                "bundle_sha256": bundle_hash,
                "benchmark_sha256": _require_sha256(
                    proof.get("benchmark_sha256"),
                    f"stability bundle {index} benchmark",
                ),
                "server_log_sha256": _require_sha256(
                    proof.get("server_log_sha256"),
                    f"stability bundle {index} server log",
                ),
                "peak_vram_utilization_percent": peak_vram,
            }
        )
    if len(set(run_ids)) != run_count:
        raise ValueError("stability lifecycles must use unique run IDs")
    if len(set(binding_hashes)) != run_count:
        raise ValueError("stability lifecycles must use unique binding hashes")
    if len(set(bundle_hashes)) != run_count:
        raise ValueError("stability lifecycles must use unique bundle hashes")
    return {
        "run_count": run_count,
        "run_ids": run_ids,
        "lifecycles": lifecycle_rows,
        "repetitions": repetitions,
    }


def build_soak_report(
    winner: dict[str, Any],
    stability: dict[str, Any],
    benchmark: dict[str, Any],
    binding: dict[str, str],
    runtime: dict[str, Any],
    *,
    stability_runtime_proofs: list[dict[str, Any]],
    server_text: str,
    minimum_duration_seconds: float,
    maximum_vram_percent: float,
) -> dict[str, Any]:
    if minimum_duration_seconds < FORMAL_MIN_DURATION_SECONDS:
        raise ValueError(
            f"minimum duration cannot be lower than {FORMAL_MIN_DURATION_SECONDS:g} seconds"
        )
    if not 0 < maximum_vram_percent <= FORMAL_MAX_VRAM_PERCENT:
        raise ValueError(
            f"maximum VRAM percent cannot exceed {FORMAL_MAX_VRAM_PERCENT:g}"
        )
    matrix = winner.get("matrix_completeness")
    observed_labels = matrix.get("observed_labels") if isinstance(matrix, dict) else None
    if not (
        winner.get("schema_version") == 2
        and winner.get("selection") == "radeonstay-a-h-winner"
        and isinstance(matrix, dict)
        and matrix.get("required_labels") == list("ABCDEFGH")
        and observed_labels == list("ABCDEFGH")
        and matrix.get("missing_labels") == []
        and matrix.get("reference_complete") is True
        and matrix.get("baseline_complete") is True
        and matrix.get("selection_candidate_set_complete") is True
        and matrix.get("complete") is True
    ):
        raise ValueError("winner report must prove the complete schema-v2 A-H matrix")
    reference_label = matrix.get("reference_experiment")
    contracts = {
        "A": {
            "quality_qualified_labels": list("ABCDEFGH"),
            "quality_negative_labels": [],
            "optimized_complete_count": 7,
            "winner_labels": set("BCDEFGH"),
        },
        "B": {
            "quality_qualified_labels": list("BCDEFGH"),
            "quality_negative_labels": ["A"],
            "optimized_complete_count": 6,
            "winner_labels": set("CDEFGH"),
        },
    }
    contract = contracts.get(reference_label)
    if contract is None:
        raise ValueError("winner reference experiment must be A or B")
    qualified_labels = contract["quality_qualified_labels"]
    negative_labels = contract["quality_negative_labels"]
    if not (
        matrix.get("quality_qualified_labels") == qualified_labels
        and matrix.get("quality_negative_labels") == negative_labels
        and matrix.get("optimized_complete_count")
        == contract["optimized_complete_count"]
    ):
        raise ValueError(
            "winner quality-qualified and quality-negative labels do not match "
            "the reference experiment"
        )
    assessment = winner.get("assessment")
    if (
        not isinstance(assessment, dict)
        or assessment.get("accepted") is not True
        or assessment.get("optimization_winner") != "optimized"
        or assessment.get("reference_experiment") != reference_label
    ):
        raise ValueError("winner report must contain an accepted optimization winner")
    winner_label = assessment.get("winner_experiment")
    winner_rows = winner.get("candidates")
    if not isinstance(winner_label, str) or not isinstance(winner_rows, dict):
        raise ValueError("winner report is missing the selected candidate")
    if (
        winner_label not in contract["winner_labels"]
        or winner_label <= reference_label
    ):
        raise ValueError("winner experiment must be strictly after the reference")
    winner_row = winner_rows.get(winner_label)
    if not isinstance(winner_row, dict) or winner_row.get("eligible") is not True:
        raise ValueError("winner candidate is not eligible")
    selected_source, reference_source = _winner_sources(
        winner,
        winner_rows,
        winner_label,
        reference_label,
        qualified_labels,
    )
    _validate_quality_negative_sources(winner, negative_labels)
    transition = winner.get("quality_reference_transition")
    reference_run_id = winner_rows[reference_label].get("run_id")
    if reference_label == "A":
        if not (
            isinstance(transition, dict)
            and transition.get("mode") == "A_quality_qualified_reference"
            and transition.get("quality_negative_experiment") is None
            and transition.get("quality_negative_run_id") is None
            and transition.get("performance_reference_experiment") == "A"
            and transition.get("performance_reference_run_id") == reference_run_id
        ):
            raise ValueError("winner A-reference transition evidence is invalid")
        quality_negative_run_id = None
    else:
        quality_negative_run_id = (
            transition.get("quality_negative_run_id")
            if isinstance(transition, dict)
            else None
        )
        if not (
            isinstance(transition, dict)
            and transition.get("mode") == "A_quality_negative_B_reference"
            and transition.get("quality_negative_experiment") == "A"
            and isinstance(quality_negative_run_id, str)
            and quality_negative_run_id
            and transition.get("performance_reference_experiment") == "B"
            and transition.get("performance_reference_run_id") == reference_run_id
            and transition.get("performance_excluded_labels") == ["A"]
            and transition.get("changed_request_fields") == ["thinking_enabled"]
            and transition.get("changed_service_fields") == []
            and transition.get("same_active_gpu_identity") is True
            and transition.get("a_gpu_offload") == "41/41"
            and transition.get("a_gpu_activity_verified") is True
        ):
            raise ValueError("winner A-negative/B-reference transition is invalid")
    soak_workload = _validate_official_workload(benchmark, "soak")
    fixed_workload = winner.get("fixed_workload")
    if not isinstance(fixed_workload, dict):
        raise ValueError("winner fixed workload evidence is missing")
    for field in (
        "suite_version",
        "suite_sha256",
        "policy_corpus_sha256",
        "case_ids",
    ):
        if benchmark.get(field) != fixed_workload.get(field):
            raise ValueError(f"soak differs from winner workload field {field}")
    stability_evidence = _validate_stability(
        stability,
        winner,
        winner_row,
        stability_runtime_proofs,
        maximum_vram_percent=maximum_vram_percent,
    )
    prior_run_ids = {
        row.get("run_id") for row in winner_rows.values() if isinstance(row, dict)
    } | set(stability_evidence["run_ids"])
    if quality_negative_run_id is not None:
        prior_run_ids.add(quality_negative_run_id)
    if benchmark.get("run_id") in prior_run_ids:
        raise ValueError("soak lifecycle must use a fresh run-id")

    measurement_start = _parse_utc(
        benchmark.get("measurement_started_at_utc"), "measurement start"
    )
    measurement_end = _parse_utc(
        benchmark.get("measurement_completed_at_utc"), "measurement end"
    )
    duration_seconds = (measurement_end - measurement_start).total_seconds()
    raw_health = _raw_health(benchmark)
    fixed_binding = winner.get("fixed_binding")
    if not isinstance(fixed_binding, dict):
        raise ValueError("winner report is missing fixed binding evidence")
    fixed_fields = (
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
    binding_match = all(
        binding.get(field) == fixed_binding.get(field) for field in fixed_fields
    )
    request_configuration_match = validate_request_configuration(
        benchmark, "soak"
    ) == winner_row.get("request_configuration")
    service_configuration_match = normalized_report_service_configuration(
        benchmark, "soak.service_configuration"
    ) == winner_row.get("service_configuration")
    peak_vram_percent = require_number(
        runtime.get("peak_vram_utilization_percent"), "soak peak VRAM percent"
    )
    fatal_server_lines = [
        line[:500]
        for line in server_text.splitlines()
        if FATAL_SERVER_RE.search(line)
    ]
    gates = {
        "duration_at_least_minimum": duration_seconds >= minimum_duration_seconds,
        "all_requests_succeeded": bool(
            raw_health["request_count"] > 0
            and raw_health["request_success_rate"] == 1.0
            and not raw_health["request_errors"]
        ),
        "all_model_calls_succeeded_without_repair_failure": bool(
            raw_health["model_call_count"] > 0
            and raw_health["failed_model_call_count"] == 0
            and not raw_health["model_errors"]
        ),
        "no_oom_fatal_or_crash_marker": not fatal_server_lines,
        "winner_source_artifact_hardware_hashes_unchanged": binding_match,
        "winner_request_configuration_unchanged": request_configuration_match,
        "winner_service_configuration_unchanged": service_configuration_match,
        "benchmark_quality_gate_passed": bool(
            benchmark.get("quality_gate", {}).get("passed") is True
            and benchmark.get("quality_gate", {}).get("failures") == []
            and benchmark.get("quality_report", {}).get("passed") is True
            and benchmark.get("quality_report", {}).get("total_score") == 300
        ),
        "peak_vram_strictly_below_limit": (
            0 < peak_vram_percent < maximum_vram_percent
        ),
        "same_gpu_energy_window_evidence_available": runtime.get(
            "energy_evidence_available"
        )
        is True,
        "official_16_case_workload_at_all_concurrency_levels": bool(
            soak_workload["case_ids"] == list(OFFICIAL_CASE_IDS)
            and set(soak_workload["success_by_concurrency"]) == {"1", "2", "4"}
        ),
        "five_or_more_independent_stability_lifecycles_passed": bool(
            stability_evidence["run_count"] >= FORMAL_MIN_LIFECYCLES
        ),
    }
    failures = [name for name, passed in gates.items() if not passed]
    return {
        "schema_version": 1,
        "report": "radeonstay-final-winner-long-soak",
        "created_at_utc": datetime.now(UTC).isoformat(timespec="seconds"),
        "reference_experiment": reference_label,
        "reference_source": reference_source,
        "winner_experiment": winner_label,
        "winner_source": selected_source,
        "soak_run_id": benchmark.get("run_id"),
        "stability": stability_evidence,
        "workload": soak_workload,
        "minimum_duration_seconds": minimum_duration_seconds,
        "measurement_duration_seconds": round(duration_seconds, 6),
        "maximum_vram_percent_strict": maximum_vram_percent,
        "peak_vram_percent": peak_vram_percent,
        "raw_health": raw_health,
        "fatal_server_evidence": {
            "count": len(fatal_server_lines),
            "line_sha256": [
                hashlib.sha256(line.encode("utf-8")).hexdigest()
                for line in fatal_server_lines
            ],
        },
        "binding_fields_checked": list(fixed_fields),
        "gates": gates,
        "passed": all(gates.values()),
        "failures": failures,
    }


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    output = args.output.expanduser().resolve()
    if output.exists():
        raise FileExistsError(f"Refusing to overwrite soak report: {output}")
    if not output.parent.is_dir():
        raise FileNotFoundError(f"Output parent does not exist: {output.parent}")
    winner_path = args.winner_report.expanduser().resolve()
    stability_path = args.stability_report.expanduser().resolve()
    benchmark_path = args.benchmark.expanduser().resolve()
    binding_path = args.binding.expanduser().resolve()
    for label, path in (
        ("winner report", winner_path),
        ("stability report", stability_path),
        ("benchmark", benchmark_path),
        ("binding", binding_path),
    ):
        if not path.is_file() or path.is_symlink():
            raise FileNotFoundError(f"{label} is not a regular file: {path}")
    winner = load_json_object(winner_path, "winner report")
    stability = load_json_object(stability_path, "stability report")
    stability_runtime_proofs = _load_stability_runtime_proofs(stability)
    benchmark = load_json_object(benchmark_path, "soak benchmark")
    binding = load_binding(binding_path, "soak")
    runtime = validate_binding(
        benchmark,
        benchmark_path,
        binding_path,
        binding,
        "soak",
    )
    server_path = binding_path.parent / binding["server_log"]
    report = build_soak_report(
        winner,
        stability,
        benchmark,
        binding,
        runtime,
        stability_runtime_proofs=stability_runtime_proofs,
        server_text=server_path.read_text(encoding="utf-8", errors="replace"),
        minimum_duration_seconds=args.minimum_duration_seconds,
        maximum_vram_percent=args.maximum_vram_percent,
    )
    report["sources"] = {
        "winner_report_basename": _safe_basename(
            winner_path.name, "winner report source"
        ),
        "winner_report_sha256": file_sha256(winner_path),
        "stability_report_basename": _safe_basename(
            stability_path.name, "stability report source"
        ),
        "stability_report_sha256": file_sha256(stability_path),
        "benchmark_basename": _safe_basename(
            benchmark_path.name, "soak benchmark source"
        ),
        "benchmark_sha256": file_sha256(benchmark_path),
        "binding_basename": _safe_basename(
            binding_path.name, "soak binding source"
        ),
        "binding_sha256": file_sha256(binding_path),
        "server_log_basename": _safe_basename(
            server_path.name, "soak server log source"
        ),
        "server_log_sha256": file_sha256(server_path),
    }
    rendered = json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    with output.open("x", encoding="utf-8") as handle:
        handle.write(rendered)
    print(
        json.dumps(
            {
                "output": str(output),
                "passed": report["passed"],
                "duration_seconds": report["measurement_duration_seconds"],
                "failures": report["failures"],
            },
            sort_keys=True,
        )
    )
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
