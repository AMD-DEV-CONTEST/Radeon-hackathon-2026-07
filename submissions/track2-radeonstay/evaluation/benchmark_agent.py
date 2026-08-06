#!/usr/bin/env python3
"""Run the fixed local Agent path and save raw latency/quality evidence.

The harness deliberately refuses deterministic mode and an existing output
file. It measures end-to-end and server-side stage latency; TTFT and GPU
telemetry must be joined from llama.cpp and ``collect_rocm_evidence.sh`` logs.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import UTC, datetime
from functools import partial
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from evaluation.configuration import (  # noqa: E402
    add_service_configuration_arguments,
    request_configuration,
    service_configuration_from_args,
)
from evaluation.runtime_binding_evidence import (  # noqa: E402
    load_runtime_instance,
    validate_model_call_bindings,
    validate_report_runtime_binding,
)
from evaluation.source_provenance import source_tree_sha256  # noqa: E402
from radeonstay.contracts import ChatRequest  # noqa: E402
from radeonstay.main import build_service, load_settings  # noqa: E402
from radeonstay.retrieval import (  # noqa: E402
    policy_corpus_sha256,
    validate_policy_directory,
)

DEFAULT_CASES = PROJECT_ROOT / "evaluation" / "fixtures" / "cases.jsonl"
DEFAULT_POLICIES = PROJECT_ROOT / "data" / "policies"
OFFICIAL_SUITE_VERSION = "30-case-p0-v3"
OFFICIAL_SUITE_SHA256 = "60fae4be0bd7a16ee9b2e7963bb3afccbf319c2ed64cd3ba43acfc912bfd3d1b"
OFFICIAL_BENCHMARK_IDS = (
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
OFFICIAL_CONCURRENCY = (1, 2, 4)
MIN_OFFICIAL_REPETITIONS = 3
MIN_OFFICIAL_WARMUP = 3
OFFICIAL_MIN_SUCCESS_RATE = 1.0
OFFICIAL_MIN_CITATION_HIT_RATE = 1.0


def model_request_configuration(settings: Any) -> dict[str, bool]:
    return request_configuration(settings)


def _is_allowed_fused_repair_purpose(value: Any) -> bool:
    purpose = str(value or "")
    return purpose == "planner.semantic_repair" or (
        purpose.startswith("planner.") and purpose.endswith(".syntax_repair")
    )


def _fused_call_policy_evidence(
    response_call_groups: list[list[dict[str, Any]]],
    *,
    server_gate_zero_call_allowed: list[bool] | None = None,
) -> dict[str, Any]:
    zero_call_allowed = server_gate_zero_call_allowed or [
        False for _ in response_call_groups
    ]
    if len(zero_call_allowed) != len(response_call_groups):
        raise RuntimeError("Server-gate evidence does not align with benchmark traces")
    response_count = len(response_call_groups)
    single_call_response_count = sum(
        len(calls) == 1 for calls in response_call_groups
    )
    repair_response_count = sum(
        len(calls) >= 2
        and _is_allowed_fused_repair_purpose(calls[1].get("purpose"))
        for calls in response_call_groups
    )
    disallowed_model_call_count = 0
    for calls in response_call_groups:
        for index, call in enumerate(calls):
            purpose = str(call.get("purpose", ""))
            allowed = purpose != "answer.evidence_selector" and (
                index == 0
                or (index == 1 and _is_allowed_fused_repair_purpose(purpose))
            )
            disallowed_model_call_count += int(not allowed)

    return {
        "response_count": response_count,
        "single_call_response_count": single_call_response_count,
        "single_call_response_rate": (
            round(single_call_response_count / response_count, 6)
            if response_count
            else 0.0
        ),
        "repair_response_count": repair_response_count,
        "repair_response_rate": (
            round(repair_response_count / response_count, 6)
            if response_count
            else 0.0
        ),
        "multi_call_response_count": sum(
            len(calls) > 1 for calls in response_call_groups
        ),
        "server_gate_zero_call_response_count": sum(
            not calls and allowed
            for calls, allowed in zip(
                response_call_groups,
                zero_call_allowed,
                strict=True,
            )
        ),
        "maximum_model_calls_per_response": max(
            (len(calls) for calls in response_call_groups),
            default=0,
        ),
        "additional_model_call_count": sum(
            max(0, len(calls) - 1) for calls in response_call_groups
        ),
        "syntax_repair_model_call_count": sum(
            str(call.get("purpose", "")).startswith("planner.")
            and str(call.get("purpose", "")).endswith(".syntax_repair")
            for calls in response_call_groups
            for call in calls
        ),
        "semantic_repair_model_call_count": sum(
            call.get("purpose") == "planner.semantic_repair"
            for calls in response_call_groups
            for call in calls
        ),
        "disallowed_model_call_count": disallowed_model_call_count,
        "single_call_per_response_verified": bool(
            response_call_groups
            and all(len(calls) == 1 for calls in response_call_groups)
        ),
        "fused_call_policy_verified": bool(
            response_call_groups
            and all(
                1 <= len(calls) <= 2 or (not calls and allowed)
                for calls, allowed in zip(
                    response_call_groups,
                    zero_call_allowed,
                    strict=True,
                )
            )
            and disallowed_model_call_count == 0
        ),
    }


def _server_gate_zero_call_allowed(row: dict[str, Any]) -> bool:
    calls = row.get("model_calls")
    gate = row.get("server_gate")
    competition_path = gate.get("competition_path") if isinstance(gate, dict) else None
    return bool(
        isinstance(calls, list)
        and not calls
        and isinstance(gate, dict)
        and set(gate) == {"competition_path", "model_invoked"}
        and competition_path
        in {"server-privacy-scope-gate", "server-privacy-policy-gate"}
        and gate.get("model_invoked") is False
        and row.get("model_backend") == f"{competition_path}; model=not-invoked"
    )


def validate_request_configuration_evidence(
    runs: list[dict[str, Any]],
    expected: dict[str, bool],
    *,
    runtime_manifest_sha256: str | None = None,
) -> dict[str, Any]:
    response_rows = [
        row
        for run in runs
        for row in run.get("requests", [])
        if isinstance(row, dict) and row.get("ok") is not False
    ]
    response_call_groups = [row.get("model_calls", []) for row in response_rows]
    if any(not isinstance(calls, list) for calls in response_call_groups):
        raise RuntimeError("Benchmark traces contain invalid model_calls")
    if any(
        not all(isinstance(call, dict) for call in calls)
        for calls in response_call_groups
    ):
        raise RuntimeError("Benchmark traces contain invalid model call records")
    model_calls = [
        call
        for calls in response_call_groups
        for call in calls
    ]
    if not model_calls:
        raise RuntimeError("Benchmark produced no model request-configuration traces")
    if any(type(call.get("thinking_enabled")) is not bool for call in model_calls):
        raise RuntimeError("Benchmark model traces are missing thinking_enabled")
    if any(type(call.get("schema_constrained")) is not bool for call in model_calls):
        raise RuntimeError("Benchmark model traces are missing schema_constrained")
    if any("fused_plan_evidence" not in call for call in model_calls):
        raise RuntimeError("Benchmark model traces are missing fused_plan_evidence")
    if any(type(call["fused_plan_evidence"]) is not bool for call in model_calls):
        raise RuntimeError(
            "Benchmark model trace fused_plan_evidence values must be boolean"
        )
    fused_enabled = expected.get("fused_plan_evidence", False)
    if type(fused_enabled) is not bool:
        raise RuntimeError(
            "Declared benchmark fused_plan_evidence must be boolean"
        )
    if any(
        call["thinking_enabled"] != expected["thinking_enabled"]
        for call in model_calls
    ):
        raise RuntimeError("Benchmark model traces contain mixed thinking settings")
    if any(
        call["schema_constrained"] != expected["schema_constrained"]
        for call in model_calls
    ):
        raise RuntimeError("Benchmark model traces contain mixed schema settings")
    if expected["schema_constrained"] and any(
        call.get("response_format") != "json_schema" for call in model_calls
    ):
        raise RuntimeError("Benchmark schema-constrained traces are not JSON schema")
    if any(
        call["fused_plan_evidence"] != fused_enabled for call in model_calls
    ):
        raise RuntimeError(
            "Benchmark model trace fused_plan_evidence values do not match the "
            "declared request configuration"
        )
    server_gate_zero_call_allowed = [
        _server_gate_zero_call_allowed(row) for row in response_rows
    ]
    if any(
        not calls and not allowed
        for calls, allowed in zip(
            response_call_groups,
            server_gate_zero_call_allowed,
            strict=True,
        )
    ):
        raise RuntimeError(
            "Benchmark contains a zero-call response without a verified server gate"
        )
    call_policy_evidence = _fused_call_policy_evidence(
        response_call_groups,
        server_gate_zero_call_allowed=server_gate_zero_call_allowed,
    )
    observed = {
        "thinking_enabled": model_calls[0]["thinking_enabled"],
        "schema_constrained": all(call["schema_constrained"] for call in model_calls),
        "fused_plan_evidence": model_calls[0]["fused_plan_evidence"],
    }
    normalized_expected = {**expected, "fused_plan_evidence": fused_enabled}
    if observed != normalized_expected:
        raise RuntimeError(
            "Benchmark model traces do not match the declared request configuration"
        )
    runtime_binding_evidence: dict[str, Any] = {}
    if runtime_manifest_sha256 is not None:
        runtime_binding_evidence = validate_model_call_bindings(
            model_calls,
            expected_manifest_sha256=runtime_manifest_sha256,
            label="Agent benchmark",
        )
    return {
        "model_call_count": len(model_calls),
        **observed,
        "response_formats": sorted(
            {str(call.get("response_format")) for call in model_calls}
        ),
        **call_policy_evidence,
        **runtime_binding_evidence,
        "trace_verified": True,
    }


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Benchmark the real local RadeonStay orchestration path."
    )
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--run-id",
        required=True,
        help="Shared evidence run identifier (letters, digits, dot, underscore, colon, hyphen)",
    )
    parser.add_argument("--cases", type=Path, default=DEFAULT_CASES)
    parser.add_argument("--quality-report", type=Path, required=True)
    parser.add_argument("--model-file", type=Path, required=True)
    parser.add_argument("--llama-server", type=Path, required=True)
    parser.add_argument("--concurrency", default="1,2,4")
    parser.add_argument("--repetitions", type=int, default=MIN_OFFICIAL_REPETITIONS)
    parser.add_argument("--warmup", type=int, default=MIN_OFFICIAL_WARMUP)
    parser.add_argument("--min-success-rate", type=float, default=OFFICIAL_MIN_SUCCESS_RATE)
    parser.add_argument(
        "--min-citation-hit-rate",
        type=float,
        default=OFFICIAL_MIN_CITATION_HIT_RATE,
    )
    add_service_configuration_arguments(parser)
    return parser.parse_args(argv)


def load_cases(path: Path) -> list[dict[str, Any]]:
    suite_sha256 = hashlib.sha256(path.read_bytes()).hexdigest()
    if suite_sha256 != OFFICIAL_SUITE_SHA256:
        raise ValueError(
            "Official benchmark requires the immutable suite; "
            f"received SHA256 {suite_sha256}"
        )
    suite: list[dict[str, Any]] = []
    for line_number, raw_line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not raw_line.strip():
            continue
        try:
            case = json.loads(raw_line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"Invalid JSON at {path}:{line_number}") from exc
        suite.append(case)
    cases_by_id = {case.get("id"): case for case in suite}
    if len(cases_by_id) != len(suite):
        raise ValueError("Official suite contains duplicate case IDs")
    try:
        cases = [cases_by_id[case_id] for case_id in OFFICIAL_BENCHMARK_IDS]
    except KeyError as exc:
        raise ValueError(
            "Agent benchmark case IDs do not match the release manifest"
        ) from exc
    if tuple(case.get("id") for case in cases) != OFFICIAL_BENCHMARK_IDS:
        raise ValueError("Agent benchmark case IDs do not match the release manifest")
    return cases


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def git_provenance(project_root: Path) -> dict[str, str]:
    def git(*arguments: str) -> str:
        completed = subprocess.run(
            ["git", "-C", str(project_root), *arguments],
            check=True,
            capture_output=True,
            text=True,
        )
        return completed.stdout.strip()

    repository_root = git("rev-parse", "--show-toplevel")
    project_prefix = git("rev-parse", "--show-prefix").rstrip("/")
    if not project_prefix:
        raise RuntimeError("Benchmark evidence must come from a repository subdirectory")
    status = git("status", "--porcelain=v1", "--untracked-files=all", "--", ".")
    if status:
        raise RuntimeError(
            "Official benchmark requires all RadeonStay source files to be tracked and clean"
        )
    return {
        "repository_root": repository_root,
        "project_prefix": project_prefix,
        "commit": git("rev-parse", "--verify", "HEAD"),
        "project_tree": git("rev-parse", f"HEAD:{project_prefix}"),
        "source_tree_sha256": source_tree_sha256(project_root),
    }


def load_quality_report(path: Path) -> dict[str, Any]:
    try:
        report = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid quality report JSON: {path}") from exc
    if not isinstance(report, dict):
        raise ValueError("Quality report must contain one JSON object")
    if report.get("evaluation") != "radeonstay-fixed-agent-suite":
        raise ValueError("Quality report has an unexpected evaluation type")
    if report.get("suite_sha256") != OFFICIAL_SUITE_SHA256:
        raise ValueError("Quality report is not bound to the official suite")
    if report.get("passed") is not True:
        raise ValueError("Quality report must pass every release gate")
    metrics = report.get("metrics")
    gates = report.get("gates")
    if not isinstance(metrics, dict) or not (
        metrics.get("total_score") == 300
        and metrics.get("maximum_score") == 300
    ):
        raise ValueError("Quality report must prove 300/300")
    if not isinstance(gates, dict) or not gates or any(
        value is not True for value in gates.values()
    ):
        raise ValueError("Quality report must pass every full-score gate")
    return report


def parse_concurrency(value: str) -> list[int]:
    try:
        levels = sorted({int(item.strip()) for item in value.split(",")})
    except ValueError as exc:
        raise ValueError("Concurrency must be a comma-separated integer list") from exc
    if not levels or levels[0] < 1 or levels[-1] > 32:
        raise ValueError("Concurrency values must be between 1 and 32")
    return levels


def validate_run_id(value: str) -> str:
    allowed = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._:-")
    first_allowed = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789")
    if not 1 <= len(value) <= 48 or value[0] not in first_allowed or any(
        character not in allowed for character in value
    ):
        raise ValueError(
            "run-id must be 1-48 characters using only letters, digits, dot, "
            "underscore, colon, or hyphen"
        )
    return value


def validate_rate(name: str, value: float) -> float:
    if not math.isfinite(value) or not 0.0 <= value <= 1.0:
        raise ValueError(f"{name} must be between 0 and 1")
    return value


def percentile(values: list[float], quantile: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = max(0, math.ceil(len(ordered) * quantile) - 1)
    return round(ordered[index], 3)


def _recovered_syntax_repair_failure_count(rows: list[dict[str, Any]]) -> int:
    recovered = 0
    for row in rows:
        calls = row.get("model_calls", [])
        if not isinstance(calls, list):
            continue
        for index, call in enumerate(calls[:-1]):
            if not isinstance(call, dict) or call.get("ok") is not False:
                continue
            repair = calls[index + 1]
            if (
                isinstance(repair, dict)
                and call.get("validation_stage") == "response_parse"
                and str(repair.get("purpose", "")).startswith("planner.")
                and str(repair.get("purpose", "")).endswith(".syntax_repair")
                and repair.get("ok") is True
            ):
                recovered += 1
    return recovered


def citation_hit(response: Any, case: dict[str, Any]) -> bool:
    expected = case.get("expected", {}).get("citations", [])
    if not expected:
        return True
    actual = {(item.document, item.section) for item in response.citations}
    return any(
        (citation.get("document"), citation.get("section")) in actual
        for citation in expected
    )


def run_case(
    service: Any,
    token: str,
    case: dict[str, Any],
    request_id: str,
) -> dict[str, Any]:
    started = time.perf_counter()
    try:
        response = service.chat(
            ChatRequest(
                request_id=request_id,
                session_id=f"bench-{request_id}",
                identity_token=token,
                message=case["prompt"],
            )
        )
        wall_ms = round((time.perf_counter() - started) * 1000, 3)
        privacy = response.trust.privacy
        return {
            "case_id": case["id"],
            "request_id": request_id,
            "ok": True,
            "wall_ms": wall_ms,
            "service_elapsed_ms": response.elapsed_ms,
            "timings_ms": response.timings_ms,
            "model_calls": response.model_calls,
            "citation_hit": citation_hit(response, case),
            "citation_count": len(response.citations),
            "receipt_statuses": [item.status for item in response.receipts],
            "model_backend": response.model_backend,
            "server_gate": {
                "competition_path": response.trust.runtime_proof.get(
                    "competition_path"
                ),
                "model_invoked": (
                    privacy.model_invoked if privacy is not None else None
                ),
            },
        }
    except Exception as exc:
        return {
            "case_id": case.get("id", "unknown"),
            "request_id": request_id,
            "ok": False,
            "wall_ms": round((time.perf_counter() - started) * 1000, 3),
            "error_type": type(exc).__name__,
        }


def run_indexed_case(
    service: Any,
    token: str,
    benchmark_run_id: str,
    concurrency: int,
    item: tuple[int, dict[str, Any]],
) -> dict[str, Any]:
    index, case = item
    request_id = f"{benchmark_run_id}-c{concurrency}-i{index}-{case['id']}"
    return run_case(service, token, case, request_id)


def summarize(rows: list[dict[str, Any]], wall_seconds: float) -> dict[str, Any]:
    recorded_wall_seconds = round(wall_seconds, 6)
    successful = [row for row in rows if row["ok"]]
    latencies = [float(row["wall_ms"]) for row in successful]
    citation_hits = sum(bool(row.get("citation_hit")) for row in successful)
    model_calls = [
        call
        for row in successful
        for call in row.get("model_calls", [])
        if isinstance(call, dict)
    ]
    successful_model_calls = [call for call in model_calls if call.get("ok") is True]
    failed_model_call_count = sum(call.get("ok") is not True for call in model_calls)
    recovered_syntax_repair_failure_count = _recovered_syntax_repair_failure_count(
        successful
    )
    effective_rates = [
        float(call["effective_output_tokens_per_second"])
        for call in model_calls
        if call.get("ok") is True
        and isinstance(call.get("effective_output_tokens_per_second"), (int, float))
    ]
    server_decode_rates = [
        float(call["server_decode_tokens_per_second"])
        for call in model_calls
        if call.get("ok") is True
        and isinstance(call.get("server_decode_tokens_per_second"), (int, float))
    ]
    ttft_values = [
        float(call["ttft_ms"])
        for call in model_calls
        if call.get("ok") is True and isinstance(call.get("ttft_ms"), (int, float))
    ]
    return {
        "requests": len(rows),
        "successful": len(successful),
        "success_rate": round(len(successful) / len(rows), 6) if rows else 0.0,
        "citation_hit_rate": (
            round(citation_hits / len(successful), 6) if successful else 0.0
        ),
        "latency_ms": {
            "p50": percentile(latencies, 0.50),
            "p95": percentile(latencies, 0.95),
            "min": round(min(latencies), 3) if latencies else 0.0,
            "max": round(max(latencies), 3) if latencies else 0.0,
        },
        "model_call_metrics": {
            "calls": len(model_calls),
            "successful_calls": len(successful_model_calls),
            "failed_calls": failed_model_call_count,
            "recovered_syntax_repair_failures": (
                recovered_syntax_repair_failure_count
            ),
            "unrecovered_failed_calls": (
                failed_model_call_count - recovered_syntax_repair_failure_count
            ),
            "prompt_tokens": sum(
                int(call["prompt_tokens"])
                for call in model_calls
                if isinstance(call.get("prompt_tokens"), int)
            ),
            "completion_tokens": sum(
                int(call["completion_tokens"])
                for call in model_calls
                if isinstance(call.get("completion_tokens"), int)
            ),
            "effective_rate_sample_count": len(effective_rates),
            "effective_rate_coverage": (
                round(len(effective_rates) / len(successful_model_calls), 6)
                if successful_model_calls
                else 0.0
            ),
            "effective_output_tokens_per_second_p50": (
                percentile(effective_rates, 0.50) if effective_rates else None
            ),
            "effective_output_tokens_per_second_p95": (
                percentile(effective_rates, 0.95) if effective_rates else None
            ),
            "server_decode_rate_sample_count": len(server_decode_rates),
            "server_decode_rate_coverage": (
                round(len(server_decode_rates) / len(successful_model_calls), 6)
                if successful_model_calls
                else 0.0
            ),
            "server_decode_tokens_per_second_p50": (
                percentile(server_decode_rates, 0.50) if server_decode_rates else None
            ),
            "server_decode_tokens_per_second_p95": (
                percentile(server_decode_rates, 0.95) if server_decode_rates else None
            ),
            "ttft_sample_count": len(ttft_values),
            "ttft_coverage": (
                round(len(ttft_values) / len(successful_model_calls), 6)
                if successful_model_calls
                else 0.0
            ),
            "ttft_ms_p50": percentile(ttft_values, 0.50) if ttft_values else None,
            "ttft_ms_p95": percentile(ttft_values, 0.95) if ttft_values else None,
            "ttft_source": "explicit local model response timing; null when unavailable",
        },
        "wall_seconds": recorded_wall_seconds,
        "offered_throughput_requests_per_second": (
            round(len(rows) / recorded_wall_seconds, 6)
            if recorded_wall_seconds > 0
            else 0.0
        ),
        "successful_throughput_requests_per_second": (
            round(len(successful) / recorded_wall_seconds, 6)
            if recorded_wall_seconds > 0
            else 0.0
        ),
    }


def evaluate_quality_gate(
    runs: list[dict[str, Any]],
    *,
    min_success_rate: float,
    min_citation_hit_rate: float,
) -> dict[str, Any]:
    failures: list[dict[str, Any]] = []
    for run in runs:
        concurrency = run["concurrency"]
        summary = run["summary"]
        if summary["success_rate"] < min_success_rate:
            failures.append(
                {
                    "concurrency": concurrency,
                    "metric": "success_rate",
                    "actual": summary["success_rate"],
                    "required": min_success_rate,
                }
            )
        if summary["citation_hit_rate"] < min_citation_hit_rate:
            failures.append(
                {
                    "concurrency": concurrency,
                    "metric": "citation_hit_rate",
                    "actual": summary["citation_hit_rate"],
                    "required": min_citation_hit_rate,
                }
            )
        model_metrics = summary.get("model_call_metrics") or {}
        unrecovered_failed_calls = model_metrics.get(
            "unrecovered_failed_calls",
            model_metrics.get("failed_calls"),
        )
        if unrecovered_failed_calls != 0:
            failures.append(
                {
                    "concurrency": concurrency,
                    "metric": "unrecovered_failed_model_calls",
                    "actual": unrecovered_failed_calls,
                    "required": 0,
                    "raw_failed_model_calls": model_metrics.get("failed_calls"),
                    "recovered_syntax_repair_failures": model_metrics.get(
                        "recovered_syntax_repair_failures", 0
                    ),
                }
            )
        if not model_metrics.get("effective_rate_sample_count"):
            failures.append(
                {
                    "concurrency": concurrency,
                    "metric": "effective_rate_sample_count",
                    "actual": model_metrics.get("effective_rate_sample_count", 0),
                    "required": "positive",
                }
            )
        if model_metrics.get("effective_rate_sample_count") != model_metrics.get(
            "successful_calls"
        ):
            failures.append(
                {
                    "concurrency": concurrency,
                    "metric": "effective_rate_coverage",
                    "actual": model_metrics.get("effective_rate_coverage", 0.0),
                    "required": 1.0,
                }
            )
    return {
        "passed": not failures,
        "thresholds": {
            "min_success_rate": min_success_rate,
            "min_citation_hit_rate": min_citation_hit_rate,
        },
        "failures": failures,
    }


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    benchmark_started_at = datetime.now(UTC)
    if args.repetitions < MIN_OFFICIAL_REPETITIONS:
        raise ValueError(
            f"Official benchmark requires at least {MIN_OFFICIAL_REPETITIONS} repetitions"
        )
    if args.warmup < MIN_OFFICIAL_WARMUP:
        raise ValueError(
            f"Official benchmark requires at least {MIN_OFFICIAL_WARMUP} warmup requests"
        )
    run_id = validate_run_id(args.run_id)
    min_success_rate = validate_rate("min-success-rate", args.min_success_rate)
    min_citation_hit_rate = validate_rate(
        "min-citation-hit-rate", args.min_citation_hit_rate
    )
    concurrency_levels = parse_concurrency(args.concurrency)
    if tuple(concurrency_levels) != OFFICIAL_CONCURRENCY:
        raise ValueError("Official benchmark requires concurrency levels 1,2,4")
    if min_success_rate != OFFICIAL_MIN_SUCCESS_RATE:
        raise ValueError("Official benchmark requires a 100% request success threshold")
    if min_citation_hit_rate < OFFICIAL_MIN_CITATION_HIT_RATE:
        raise ValueError("Official benchmark requires a 100% citation hit rate")
    output_path = args.output.expanduser().resolve()
    if output_path.exists():
        raise FileExistsError(f"Refusing to overwrite evidence: {output_path}")
    if not output_path.parent.is_dir():
        raise FileNotFoundError(f"Output parent does not exist: {output_path.parent}")

    cases_path = args.cases.expanduser().resolve()
    quality_report_path = args.quality_report.expanduser().resolve()
    model_file = args.model_file.expanduser().resolve()
    llama_server = args.llama_server.expanduser().resolve()
    for label, path in (
        ("quality report", quality_report_path),
        ("model file", model_file),
        ("llama-server", llama_server),
    ):
        if not path.is_file():
            raise FileNotFoundError(f"{label} does not exist: {path}")
    cases = load_cases(cases_path)
    settings = load_settings(PROJECT_ROOT)
    if settings.deterministic_mode:
        raise RuntimeError("Benchmark refuses RADEONSTAY_DETERMINISTIC_MODE=1")
    runtime_instance = load_runtime_instance(
        settings.runtime_instance_path,
        expected_run_id=run_id,
    )
    official_policy_dir = validate_policy_directory(
        DEFAULT_POLICIES,
        project_root=PROJECT_ROOT,
    )
    policy_dir = validate_policy_directory(
        settings.policy_dir,
        project_root=PROJECT_ROOT,
    )
    if policy_dir != official_policy_dir:
        raise RuntimeError("Official benchmark requires data/policies")
    settings = replace(
        settings,
        database_path=Path(":memory:"),
        policy_dir=policy_dir,
    )
    provenance = git_provenance(PROJECT_ROOT)
    policy_hash = policy_corpus_sha256(
        settings.policy_dir,
        project_root=PROJECT_ROOT,
    )
    artifacts = {
        "model_file": str(model_file),
        "model_file_sha256": file_sha256(model_file),
        "llama_server": str(llama_server),
        "llama_server_sha256": file_sha256(llama_server),
    }
    quality_report = load_quality_report(quality_report_path)
    validate_report_runtime_binding(
        quality_report,
        expected_manifest_sha256=runtime_instance.manifest_sha256,
        report_kind="quality",
        label="Quality report",
    )
    request_configuration = model_request_configuration(settings)
    service_configuration = service_configuration_from_args(args)
    if quality_report.get("run_id") != run_id:
        raise ValueError("Quality report and benchmark must share the same run-id")
    if (quality_report.get("model") or {}).get("name") != settings.model_name:
        raise ValueError("Quality report and benchmark model aliases do not match")
    if quality_report.get("policy_corpus_sha256") != policy_hash:
        raise ValueError("Quality report and benchmark policy corpora do not match")
    if quality_report.get("request_configuration") != request_configuration:
        raise ValueError(
            "Quality report and benchmark request configurations do not match"
        )
    if quality_report.get("service_configuration") != service_configuration:
        raise ValueError(
            "Quality report and benchmark service configurations do not match"
        )
    quality_provenance = quality_report.get("provenance") or {}
    for field in ("commit", "project_tree", "source_tree_sha256"):
        if quality_provenance.get(field) != provenance[field]:
            raise ValueError(f"Quality report provenance mismatch: {field}")
    quality_artifacts = quality_report.get("artifacts") or {}
    for field in ("model_file_sha256", "llama_server_sha256"):
        if quality_artifacts.get(field) != artifacts[field]:
            raise ValueError(f"Quality report artifact mismatch: {field}")

    service = build_service(settings)
    try:
        health = service.health()
        if not health.get("ok"):
            raise RuntimeError("Local model or database health check failed")
        token = service.identity_provider.issue(
            user_id="benchmark-guest",
            role="guest",
            ttl_seconds=2 * 60 * 60,
        )
        for index in range(args.warmup):
            case = cases[index % len(cases)]
            warmup = run_case(
                service,
                token,
                case,
                f"{run_id}-warmup-{index}-{case['id']}",
            )
            if not warmup["ok"]:
                raise RuntimeError(
                    "Benchmark warmup failed: "
                    f"{warmup['request_id']} ({warmup.get('error_type', 'unknown error')})"
                )

        measurement_started_at = datetime.now(UTC)
        runs: list[dict[str, Any]] = []
        expanded_cases = cases * args.repetitions
        for concurrency in concurrency_levels:
            batch_started = time.perf_counter()
            with ThreadPoolExecutor(max_workers=concurrency) as executor:
                rows = list(
                    executor.map(
                        partial(
                            run_indexed_case,
                            service,
                            token,
                            run_id,
                            concurrency,
                        ),
                        enumerate(expanded_cases),
                    )
                )
            wall_seconds = time.perf_counter() - batch_started
            runs.append(
                {
                    "concurrency": concurrency,
                    "summary": summarize(rows, wall_seconds),
                    "requests": rows,
                }
            )
        measurement_completed_at = datetime.now(UTC)

        quality_gate = evaluate_quality_gate(
            runs,
            min_success_rate=min_success_rate,
            min_citation_hit_rate=min_citation_hit_rate,
        )
        request_configuration_evidence = validate_request_configuration_evidence(
            runs,
            request_configuration,
            runtime_manifest_sha256=runtime_instance.manifest_sha256,
        )
        if (
            request_configuration["fused_plan_evidence"]
            and not request_configuration_evidence["fused_call_policy_verified"]
        ):
            quality_gate["failures"].append(
                {
                    "metric": "fused_plan_evidence_call_policy",
                    "actual": request_configuration_evidence[
                        "fused_call_policy_verified"
                    ],
                    "required": True,
                    "single_call_response_rate": request_configuration_evidence[
                        "single_call_response_rate"
                    ],
                    "repair_response_rate": request_configuration_evidence[
                        "repair_response_rate"
                    ],
                    "additional_model_calls": request_configuration_evidence[
                        "additional_model_call_count"
                    ],
                    "syntax_repair_model_calls": request_configuration_evidence[
                        "syntax_repair_model_call_count"
                    ],
                    "semantic_repair_model_calls": request_configuration_evidence[
                        "semantic_repair_model_call_count"
                    ],
                    "disallowed_model_calls": request_configuration_evidence[
                        "disallowed_model_call_count"
                    ],
                }
            )
            quality_gate["passed"] = False

        report = {
            "schema_version": 3,
            "benchmark": "radeonstay-agent-end-to-end",
            "run_id": run_id,
            "started_at_utc": benchmark_started_at.isoformat(timespec="milliseconds"),
            "completed_at_utc": datetime.now(UTC).isoformat(timespec="milliseconds"),
            "measurement_started_at_utc": measurement_started_at.isoformat(
                timespec="milliseconds"
            ),
            "measurement_completed_at_utc": measurement_completed_at.isoformat(
                timespec="milliseconds"
            ),
            "cases_path": str(cases_path),
            "suite_version": OFFICIAL_SUITE_VERSION,
            "suite_sha256": OFFICIAL_SUITE_SHA256,
            "case_ids": list(OFFICIAL_BENCHMARK_IDS),
            "request_case_ids": [case["id"] for case in expanded_cases],
            "policy_corpus_sha256": policy_hash,
            "request_configuration": request_configuration,
            "request_configuration_evidence": request_configuration_evidence,
            "runtime_instance": {
                "manifest_sha256": runtime_instance.manifest_sha256,
                "process_binding_valid_for_all_model_calls": True,
                "bound_model_call_count": request_configuration_evidence[
                    "bound_model_call_count"
                ],
            },
            "service_configuration": service_configuration,
            "configuration": {
                "repetitions": args.repetitions,
                "warmup": args.warmup,
                "concurrency": concurrency_levels,
                "min_success_rate": min_success_rate,
                "min_citation_hit_rate": min_citation_hit_rate,
            },
            "provenance": provenance,
            "artifacts": artifacts,
            "quality_report": {
                "path": str(quality_report_path),
                "sha256": file_sha256(quality_report_path),
                "passed": True,
                "total_score": quality_report.get("metrics", {}).get("total_score"),
            },
            "model_name": settings.model_name,
            "model_base_url": settings.model_base_url,
            "deterministic_mode": settings.deterministic_mode,
            "health": health,
            "limitations": {
                "ttft": "collect from the paired llama.cpp server log",
                "gpu": "collect from the paired ROCm evidence directory",
            },
            "quality_gate": quality_gate,
            "runs": runs,
        }
        if policy_corpus_sha256(
            settings.policy_dir,
            project_root=PROJECT_ROOT,
        ) != policy_hash:
            raise RuntimeError("Policy corpus changed during benchmark evaluation")
        if git_provenance(PROJECT_ROOT) != provenance:
            raise RuntimeError("RadeonStay source changed during benchmark evaluation")
        rendered = json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
        with output_path.open("x", encoding="utf-8") as handle:
            handle.write(rendered)
        print(
            json.dumps(
                {
                    "output": str(output_path),
                    "runs": len(runs),
                    "run_id": run_id,
                    "quality_gate_passed": quality_gate["passed"],
                }
            )
        )
        return 0 if quality_gate["passed"] else 1
    finally:
        service.close()


if __name__ == "__main__":
    raise SystemExit(main())
