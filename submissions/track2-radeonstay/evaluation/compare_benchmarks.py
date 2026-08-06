#!/usr/bin/env python3
"""Compare two quality-gated RadeonStay benchmark reports and assess acceptance."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

try:
    from evaluation.benchmark_agent import (
        OFFICIAL_BENCHMARK_IDS as BENCHMARK_CASE_IDS,
    )
    from evaluation.configuration import (
        changed_tunable_groups,
        normalize_request_configuration,
        normalized_report_service_configuration,
        service_configuration_matches_log,
        service_configuration_sha256,
        validate_percent,
    )
    from evaluation.run_agent_eval import (
        DEFAULT_CASES as QUALITY_CASES_PATH,
    )
    from evaluation.run_agent_eval import (
        DEFAULT_POLICIES as POLICY_DIRECTORY,
    )
    from evaluation.run_agent_eval import (
        EXPECTED_CATEGORY_COUNTS as QUALITY_CATEGORY_COUNTS,
    )
    from evaluation.run_agent_eval import (
        OFFICIAL_CASE_IDS as QUALITY_CASE_IDS,
    )
    from evaluation.run_agent_eval import (
        WRITE_TABLES,
        load_policy_documents,
    )
    from evaluation.run_agent_eval import (
        _case_score as score_quality_case,
    )
    from evaluation.run_agent_eval import (
        _expected_state_delta as normalize_quality_state_delta,
    )
    from evaluation.run_agent_eval import (
        _summarize as summarize_quality_cases,
    )
    from evaluation.run_agent_eval import (
        load_cases as load_quality_cases,
    )
    from evaluation.run_retrieval_eval import (
        PolicyRetriever,
        load_knowledge_cases,
        policy_corpus_sha256,
    )
    from evaluation.run_retrieval_eval import (
        evaluate as evaluate_retrieval,
    )
    from evaluation.run_stress_eval import (
        DECISION_ALIASES as STRESS_DECISION_ALIASES,
    )
    from evaluation.run_stress_eval import (
        DEFAULT_CASES as STRESS_CASES_PATH,
    )
    from evaluation.run_stress_eval import (
        SECURITY_CATEGORIES as STRESS_SECURITY_CATEGORIES,
    )
    from evaluation.run_stress_eval import (
        STRESS_CASE_IDS,
        load_stress_cases,
    )
    from evaluation.run_stress_eval import (
        STRESS_SUITE_SHA256 as EVALUATOR_STRESS_SUITE_SHA256,
    )
    from evaluation.run_stress_eval import (
        STRESS_SUITE_VERSION as EVALUATOR_STRESS_SUITE_VERSION,
    )
    from evaluation.run_stress_eval import (
        _agent_tool_calls as stress_agent_tool_calls,
    )
    from evaluation.run_stress_eval import (
        _behavior_checks as stress_behavior_checks,
    )
    from evaluation.run_stress_eval import (
        _forbidden_behavior_checks as stress_forbidden_behavior_checks,
    )
    from evaluation.run_stress_eval import (
        _infer_decision as infer_stress_decision,
    )
    from evaluation.run_stress_eval import (
        _plan_tools as stress_plan_tools,
    )
    from evaluation.run_stress_eval import (
        _sensitive_output_projection as stress_sensitive_output_projection,
    )
    from evaluation.run_stress_eval import (
        _sensitive_projection_sha256 as stress_sensitive_projection_sha256,
    )
    from evaluation.run_stress_eval import (
        _state_delta as stress_state_delta,
    )
    from evaluation.run_stress_eval import (
        _state_invariant_checks as stress_state_invariant_checks,
    )
    from evaluation.run_stress_eval import (
        summarize as summarize_stress_cases,
    )
    from evaluation.runtime_binding_evidence import (
        load_runtime_instance,
        validate_report_runtime_binding,
    )
except ModuleNotFoundError:  # Direct ``python evaluation/compare_benchmarks.py``.
    from benchmark_agent import (  # type: ignore[no-redef]
        OFFICIAL_BENCHMARK_IDS as BENCHMARK_CASE_IDS,
    )
    from configuration import (  # type: ignore[no-redef]
        changed_tunable_groups,
        normalize_request_configuration,
        normalized_report_service_configuration,
        service_configuration_matches_log,
        service_configuration_sha256,
        validate_percent,
    )
    from run_agent_eval import (  # type: ignore[no-redef]
        DEFAULT_CASES as QUALITY_CASES_PATH,
    )
    from run_agent_eval import (
        DEFAULT_POLICIES as POLICY_DIRECTORY,
    )
    from run_agent_eval import (
        EXPECTED_CATEGORY_COUNTS as QUALITY_CATEGORY_COUNTS,
    )
    from run_agent_eval import (
        OFFICIAL_CASE_IDS as QUALITY_CASE_IDS,
    )
    from run_agent_eval import (
        WRITE_TABLES,
        load_policy_documents,
    )
    from run_agent_eval import (
        _case_score as score_quality_case,
    )
    from run_agent_eval import (
        _expected_state_delta as normalize_quality_state_delta,
    )
    from run_agent_eval import (
        _summarize as summarize_quality_cases,
    )
    from run_agent_eval import (
        load_cases as load_quality_cases,
    )
    from run_retrieval_eval import (  # type: ignore[no-redef]
        PolicyRetriever,
        load_knowledge_cases,
        policy_corpus_sha256,
    )
    from run_retrieval_eval import (
        evaluate as evaluate_retrieval,
    )
    from run_stress_eval import (  # type: ignore[no-redef]
        DECISION_ALIASES as STRESS_DECISION_ALIASES,
    )
    from run_stress_eval import (
        DEFAULT_CASES as STRESS_CASES_PATH,
    )
    from run_stress_eval import (
        SECURITY_CATEGORIES as STRESS_SECURITY_CATEGORIES,
    )
    from run_stress_eval import (
        STRESS_CASE_IDS,
        load_stress_cases,
    )
    from run_stress_eval import (
        STRESS_SUITE_SHA256 as EVALUATOR_STRESS_SUITE_SHA256,
    )
    from run_stress_eval import (
        STRESS_SUITE_VERSION as EVALUATOR_STRESS_SUITE_VERSION,
    )
    from run_stress_eval import (
        _agent_tool_calls as stress_agent_tool_calls,
    )
    from run_stress_eval import (
        _behavior_checks as stress_behavior_checks,
    )
    from run_stress_eval import (
        _forbidden_behavior_checks as stress_forbidden_behavior_checks,
    )
    from run_stress_eval import (
        _infer_decision as infer_stress_decision,
    )
    from run_stress_eval import (
        _plan_tools as stress_plan_tools,
    )
    from run_stress_eval import (
        _sensitive_output_projection as stress_sensitive_output_projection,
    )
    from run_stress_eval import (
        _sensitive_projection_sha256 as stress_sensitive_projection_sha256,
    )
    from run_stress_eval import (
        _state_delta as stress_state_delta,
    )
    from run_stress_eval import (
        _state_invariant_checks as stress_state_invariant_checks,
    )
    from run_stress_eval import (
        summarize as summarize_stress_cases,
    )
    from runtime_binding_evidence import (  # type: ignore[no-redef]
        load_runtime_instance,
        validate_report_runtime_binding,
    )

SCHEMA_VERSION = 3
OFFICIAL_SUITE_VERSION = "30-case-p0-v3"
OFFICIAL_SUITE_SHA256 = "60fae4be0bd7a16ee9b2e7963bb3afccbf319c2ed64cd3ba43acfc912bfd3d1b"
OFFICIAL_CASE_IDS = BENCHMARK_CASE_IDS
STRESS_SUITE_VERSION = EVALUATOR_STRESS_SUITE_VERSION
STRESS_SUITE_SHA256 = EVALUATOR_STRESS_SUITE_SHA256
OFFICIAL_CONCURRENCY = (1, 2, 4)
MIN_OFFICIAL_REPETITIONS = 3
MIN_OFFICIAL_WARMUP = 3
FORMAL_MATERIAL_THRESHOLD_PERCENT = 5.0
FORMAL_MAXIMUM_VRAM_PERCENT = 90.0
EXPECTED_OFFLOADED_MODEL_LAYERS = 41
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
NUMBER_RE = re.compile(r"[-+]?\d+(?:\.\d+)?")
GPU_BACKEND_RE = re.compile(
    r"^(?:"
    r"[ \t]*ggml_(?:cuda|hip)_init[ \t]*:[^\r\n]*"
    r"\bfound[ \t]+[1-9][0-9]*[ \t]+(?:ROCm|HIP)[ \t]+devices?\b[^\r\n]*"
    r"|"
    r"[ \t]*[0-9]+(?:\.[0-9]+){3}[ \t]+I[ \t]+cmn[ \t]+common_param[ \t]*:"
    r"[ \t]*-[ \t]*ROCm[0-9]+[ \t]*:[ \t]*AMD[ \t]+Radeon\b[^\r\n]*"
    r")$",
    re.I | re.M,
)
GPU_OFFLOAD_RE = re.compile(
    r"^[ \t]*(?:[0-9]+(?:\.[0-9]+){3}[ \t]+I[ \t]+)?"
    r"(?:llm_)?load_tensors[ \t]*:[ \t]*offloaded[ \t]+"
    r"([1-9][0-9]*)/([1-9][0-9]*)[ \t]+layers?[ \t]+to[ \t]+GPU[ \t]*$",
    re.I | re.M,
)
FATAL_SERVER_RE = re.compile(
    r"out\s+of\s+memory|hip\s+error|segmentation\s+fault|core\s+dumped|"
    r"fatal\s+error|panic:|\baborted\b|\bcrash(?:ed)?\b",
    re.IGNORECASE,
)
MONITOR_SAMPLE_RE = re.compile(
    r"sample=([1-9][0-9]*) run_id=(\S+) collected_at_utc=(\S+)"
)
GPU_INDEX_RE = re.compile(r"GPU\[([0-9]+)\]", re.I)
GPU_UNIQUE_ID_RE = re.compile(
    r"^\s*GPU\[([0-9]+)\]\s*:\s*Unique ID\s*:\s*(0x[0-9a-f]+)\s*$",
    re.I,
)
DEVICE_IDENTITY_BEGIN = "device_identity_begin"
DEVICE_IDENTITY_END = "device_identity_end"
DEVICE_UNIQUE_ID_MARKER = "unique id"
GPU_USE_MARKERS = ("gpu use (%)", "gpu utilization (%)", "gpu utilization")
VRAM_USED_MARKERS = (
    "vram total used memory",
    "vram used memory",
    "vram used",
)
VRAM_TOTAL_MARKERS = (
    "vram total memory",
    "vram total available memory",
)
POWER_WATT_MARKERS = (
    "average graphics package power (w)",
    "current socket graphics package power (w)",
    "current graphics package power (w)",
)
BINDING_FILE_NAMES = {
    "retrieval_file": "retrieval.json",
    "quality_file": "agent-quality.json",
    "stress_file": "stress.json",
    "benchmark_file": "agent-benchmark.json",
    "monitor_file": "rocm-monitor.log",
    "server_log": "llama-server.log",
    "live_rocm_file": "live-rocm.log",
    "runtime_instance_file": "runtime-instance.json",
}
BINDING_HASH_FIELDS = {
    "retrieval_file": "retrieval_sha256",
    "quality_file": "quality_sha256",
    "stress_file": "stress_sha256",
    "benchmark_file": "benchmark_sha256",
    "monitor_file": "monitor_sha256",
    "server_log": "server_log_sha256",
    "live_rocm_file": "live_rocm_sha256",
    "runtime_instance_file": "runtime_instance_sha256",
}
CONTEXT_BINDING_FILES = {
    "context_selection_file": "context-selection.json",
    "context_proof_file": "context-proof.json",
}
CONTEXT_BINDING_HASH_FIELDS = {
    "context_selection_file": "context_selection_sha256",
    "context_proof_file": "context_proof_sha256",
}
BINDING_REQUIRED_FIELDS = {
    "schema_version",
    "run_id",
    "created_at_utc",
    "binding_status",
    "commit",
    "project_tree",
    "source_tree_sha256",
    "hardware_identity_algorithm",
    "hardware_identity_sha256",
    *BINDING_FILE_NAMES,
    *BINDING_HASH_FIELDS.values(),
    "model_file",
    "model_sha256",
    "model_repository",
    "model_revision",
    "model_quantization",
    "llama_server",
    "llama_server_sha256",
    "llama_cpp_commit",
}
BUNDLE_CHECKSUM_FILES = {
    "manifest.txt",
    "system.txt",
    "rocminfo.txt",
    "rocm-smi.txt",
    "rocm-version.txt",
    "git.txt",
    *BINDING_FILE_NAMES.values(),
    "binding-manifest.txt",
}
TOKEN_RATE_FIELDS = (
    "effective_output_tokens_per_second_p50",
    "effective_output_tokens_per_second_p95",
)
CORE_METRIC_NAMES = (
    "latency_p50_ms",
    "latency_p95_ms",
    "successful_throughput_requests_per_second",
    *TOKEN_RATE_FIELDS,
)
OPTIONAL_METRIC_GROUPS = (
    (
        "server_decode_rate_sample_count",
        (
            "server_decode_tokens_per_second_p50",
            "server_decode_tokens_per_second_p95",
        ),
        False,
    ),
    ("ttft_sample_count", ("ttft_ms_p50", "ttft_ms_p95"), True),
)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Compare baseline and optimized schema-v3 benchmark evidence. "
            "A quality-preserving, regression-free material core improvement "
            "is accepted as the optimized winner."
        )
    )
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--optimized", type=Path, required=True)
    parser.add_argument("--baseline-binding", type=Path, required=True)
    parser.add_argument("--optimized-binding", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--material-threshold-percent",
        type=float,
        default=5.0,
        help="Minimum directional change considered material (default: 5.0)",
    )
    parser.add_argument(
        "--require-accepted",
        action="store_true",
        help="Return a non-zero exit status after writing the report when not accepted",
    )
    parser.add_argument(
        "--maximum-vram-percent",
        type=float,
        default=90.0,
        help="Winner peak VRAM must remain strictly below this percentage (default: 90)",
    )
    return parser.parse_args(argv)


def require_number(value: Any, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{field} must be a number")
    number = float(value)
    if not math.isfinite(number) or number < 0:
        raise ValueError(f"{field} must be finite and non-negative")
    return number


def validate_formal_acceptance_limits(
    material_threshold_percent: Any,
    maximum_vram_percent: Any,
) -> tuple[float, float]:
    """Reject settings that could weaken the published acceptance contract."""

    threshold = validate_percent(
        material_threshold_percent,
        "material_threshold_percent",
    )
    maximum_vram = validate_percent(
        maximum_vram_percent,
        "maximum_vram_percent",
    )
    if threshold < FORMAL_MATERIAL_THRESHOLD_PERCENT:
        raise ValueError(
            "material threshold cannot be lower than the formal 5 percent floor"
        )
    if maximum_vram > FORMAL_MAXIMUM_VRAM_PERCENT:
        raise ValueError(
            "maximum VRAM percent cannot exceed the formal 90 percent cap"
        )
    return threshold, maximum_vram


def validate_request_configuration(
    payload: dict[str, Any], label: str
) -> dict[str, Any]:
    configuration = payload.get("request_configuration")
    return normalize_request_configuration(
        configuration,
        f"{label}.request_configuration",
    )


def _is_planner_syntax_repair(purpose: Any) -> bool:
    return (
        isinstance(purpose, str)
        and purpose.startswith("planner.")
        and purpose.endswith(".syntax_repair")
    )


def _is_planner_semantic_repair(purpose: Any) -> bool:
    return purpose == "planner.semantic_repair"


def _is_recovered_syntax_repair_pair(
    failed_call: dict[str, Any],
    repair_call: dict[str, Any],
) -> bool:
    return bool(
        failed_call.get("ok") is False
        and failed_call.get("validation_stage") == "response_parse"
        and _is_planner_syntax_repair(repair_call.get("purpose"))
        and repair_call.get("ok") is True
    )


def _recovered_syntax_repair_failure_count(
    calls: list[dict[str, Any]],
) -> int:
    return sum(
        _is_recovered_syntax_repair_pair(failed_call, repair_call)
        for failed_call, repair_call in zip(calls, calls[1:], strict=False)
    )


def _validate_fused_model_calls(
    calls: list[dict[str, Any]],
    label: str,
) -> str:
    """Accept one planner call or one bounded planner-only repair call."""

    if len(calls) not in {1, 2}:
        raise ValueError(f"{label} fused response must contain one or two model calls")
    first_purpose = calls[0].get("purpose")
    if (
        not isinstance(first_purpose, str)
        or not first_purpose.startswith("planner.")
        or _is_planner_syntax_repair(first_purpose)
        or _is_planner_semantic_repair(first_purpose)
    ):
        raise ValueError(
            f"{label} fused response must begin with a normal planner call"
        )
    if calls[-1].get("ok") is not True:
        raise ValueError(f"{label} fused response has no successful final planner call")
    if len(calls) == 1:
        return "single_call"

    repair_purpose = calls[1].get("purpose")
    if _is_planner_syntax_repair(repair_purpose):
        if not _is_recovered_syntax_repair_pair(calls[0], calls[1]):
            raise ValueError(
                f"{label} planner syntax repair is not paired with a recovered "
                "response-parse failure"
            )
        return "syntax_repair"
    if _is_planner_semantic_repair(repair_purpose):
        if calls[0].get("ok") is not True:
            raise ValueError(
                f"{label} planner semantic repair does not follow a successful "
                "parsed planner call"
            )
        return "semantic_repair"
    raise ValueError(
        f"{label} fused response has a forbidden additional model call: "
        f"{repair_purpose!r}"
    )


def server_gate_zero_call_allowed(record: dict[str, Any]) -> bool:
    """Accept zero model calls only for a fully attested server privacy gate."""

    calls = record.get("model_calls")
    trust = record.get("trust")
    runtime_proof = trust.get("runtime_proof") if isinstance(trust, dict) else None
    privacy = trust.get("privacy") if isinstance(trust, dict) else None
    gate = record.get("server_gate")
    if isinstance(gate, dict) and set(gate) == {
        "competition_path",
        "model_invoked",
    }:
        competition_path = gate.get("competition_path")
        model_invoked = gate.get("model_invoked")
    else:
        competition_path = (
            runtime_proof.get("competition_path")
            if isinstance(runtime_proof, dict)
            else None
        )
        model_invoked = (
            privacy.get("model_invoked") if isinstance(privacy, dict) else None
        )
    return bool(
        isinstance(calls, list)
        and not calls
        and competition_path
        in {"server-privacy-scope-gate", "server-privacy-policy-gate"}
        and model_invoked is False
        and record.get("model_backend")
        == f"{competition_path}; model=not-invoked"
    )


def _call_efficiency_profile(
    groups: list[
        tuple[list[dict[str, Any]], bool] | list[dict[str, Any]]
    ],
    *,
    fused: bool,
    label: str,
) -> dict[str, Any]:
    normalized_groups: list[tuple[list[dict[str, Any]], bool]] = []
    for group in groups:
        if (
            isinstance(group, tuple)
            and len(group) == 2
            and isinstance(group[0], list)
            and type(group[1]) is bool
        ):
            normalized_groups.append((group[0], group[1]))
        elif isinstance(group, list):
            normalized_groups.append((group, False))
        else:
            raise ValueError(f"{label} contains an invalid model-call group")

    groups = normalized_groups
    for response_index, (calls, zero_call_allowed) in enumerate(groups):
        if not calls and not zero_call_allowed:
            raise ValueError(
                f"{label}.responses[{response_index}] has no model-call evidence "
                "and no verified server privacy gate"
            )
        for call_index, call in enumerate(calls):
            observed_fused = call.get("fused_plan_evidence")
            call_label = (
                f"{label}.responses[{response_index}].model_calls[{call_index}]"
            )
            if type(observed_fused) is not bool:
                raise ValueError(
                    f"{call_label}.fused_plan_evidence must be an explicit boolean"
                )
            if observed_fused != fused:
                raise ValueError(
                    f"{call_label}.fused_plan_evidence does not match the declared "
                    "request configuration"
                )
        if fused and calls:
            _validate_fused_model_calls(
                calls,
                f"{label}.responses[{response_index}]",
            )

    response_count = len(groups)
    single_call_count = sum(len(calls) == 1 for calls, _allowed in groups)
    zero_call_count = sum(
        not calls and allowed for calls, allowed in groups
    )
    repair_response_count = sum(
        len(calls) >= 2
        and (
            _is_planner_syntax_repair(calls[1].get("purpose"))
            or _is_planner_semantic_repair(calls[1].get("purpose"))
        )
        for calls, _allowed in groups
    )
    syntax_repair_call_count = sum(
        _is_planner_syntax_repair(call.get("purpose"))
        for calls, _allowed in groups
        for call in calls
    )
    semantic_repair_call_count = sum(
        _is_planner_semantic_repair(call.get("purpose"))
        for calls, _allowed in groups
        for call in calls
    )
    disallowed_model_call_count = sum(
        not (
            call.get("purpose") != "answer.evidence_selector"
            and (
                index == 0
                or (
                    index == 1
                    and (
                        _is_planner_syntax_repair(call.get("purpose"))
                        or _is_planner_semantic_repair(call.get("purpose"))
                    )
                )
            )
        )
        for calls, _allowed in groups
        for index, call in enumerate(calls)
    )
    return {
        "status": "available" if response_count else "unavailable",
        "response_count": response_count,
        "model_call_count": sum(len(calls) for calls, _allowed in groups),
        "additional_model_call_count": sum(
            max(0, len(calls) - 1) for calls, _allowed in groups
        ),
        "single_call_response_count": single_call_count,
        "multi_call_response_count": sum(
            len(calls) > 1 for calls, _allowed in groups
        ),
        "server_gate_zero_call_response_count": zero_call_count,
        "repair_response_count": repair_response_count,
        "syntax_repair_model_call_count": syntax_repair_call_count,
        "semantic_repair_model_call_count": semantic_repair_call_count,
        "disallowed_model_call_count": disallowed_model_call_count,
        "maximum_model_calls_per_response": max(
            (len(calls) for calls, _allowed in groups),
            default=0,
        ),
        "single_call_response_rate": (
            round(single_call_count / response_count, 6) if response_count else None
        ),
        "repair_response_rate": (
            round(repair_response_count / response_count, 6)
            if response_count
            else None
        ),
        "single_call_per_response_verified": bool(
            groups and single_call_count == response_count
        ),
        "fused_call_policy_verified": bool(
            groups
            and all(
                1 <= len(calls) <= 2 or (not calls and allowed)
                for calls, allowed in groups
            )
            and disallowed_model_call_count == 0
        ),
    }


def _benchmark_call_groups(
    payload: dict[str, Any],
) -> list[tuple[list[dict[str, Any]], bool]]:
    groups: list[tuple[list[dict[str, Any]], bool]] = []
    for run in payload.get("runs", []):
        if not isinstance(run, dict):
            continue
        for row in run.get("requests", []):
            if not isinstance(row, dict) or row.get("ok") is not True:
                continue
            calls = row.get("model_calls")
            if isinstance(calls, list) and all(
                isinstance(call, dict) for call in calls
            ):
                groups.append((calls, server_gate_zero_call_allowed(row)))
    return groups


def _quality_call_groups(
    payload: dict[str, Any],
) -> list[tuple[list[dict[str, Any]], bool]]:
    groups: list[tuple[list[dict[str, Any]], bool]] = []
    for row in payload.get("cases", []):
        if not isinstance(row, dict):
            continue
        for trace in row.get("trace", []):
            response = trace.get("response") if isinstance(trace, dict) else None
            calls = response.get("model_calls") if isinstance(response, dict) else None
            if isinstance(calls, list) and all(
                isinstance(call, dict) for call in calls
            ):
                groups.append((calls, server_gate_zero_call_allowed(response)))
    return groups


def _validate_call_profile_against_evidence(
    profile: dict[str, Any],
    evidence: dict[str, Any],
    label: str,
) -> None:
    expected_fields = {
        "response_count": profile["response_count"],
        "model_call_count": profile["model_call_count"],
        "additional_model_call_count": profile["additional_model_call_count"],
        "single_call_response_count": profile["single_call_response_count"],
        "multi_call_response_count": profile["multi_call_response_count"],
        "server_gate_zero_call_response_count": profile[
            "server_gate_zero_call_response_count"
        ],
        "repair_response_count": profile["repair_response_count"],
        "syntax_repair_model_call_count": profile[
            "syntax_repair_model_call_count"
        ],
        "semantic_repair_model_call_count": profile[
            "semantic_repair_model_call_count"
        ],
        "disallowed_model_call_count": profile["disallowed_model_call_count"],
        "maximum_model_calls_per_response": profile[
            "maximum_model_calls_per_response"
        ],
        "single_call_response_rate": profile["single_call_response_rate"],
        "repair_response_rate": profile["repair_response_rate"],
        "single_call_per_response_verified": profile[
            "single_call_per_response_verified"
        ],
        "fused_call_policy_verified": profile["fused_call_policy_verified"],
    }
    for field, expected in expected_fields.items():
        if evidence.get(field) != expected:
            raise ValueError(f"{label} {field} does not match raw model-call evidence")


def validate_request_configuration_evidence(
    payload: dict[str, Any], label: str
) -> dict[str, Any]:
    configuration = validate_request_configuration(payload, label)
    evidence = payload.get("request_configuration_evidence")
    if not isinstance(evidence, dict) or evidence.get("trace_verified") is not True:
        raise ValueError(f"{label} report has no verified request-configuration trace")
    model_call_count = require_integer(
        evidence.get("model_call_count"),
        f"{label}.request_configuration_evidence.model_call_count",
        minimum=1,
    )
    for field in ("thinking_enabled", "schema_constrained"):
        if type(evidence.get(field)) is not bool:
            raise ValueError(
                f"{label}.request_configuration_evidence.{field} must be a boolean"
            )
        if evidence[field] != configuration[field]:
            raise ValueError(
                f"{label} request-configuration evidence does not match {field}"
            )
    fused = configuration["fused_plan_evidence"]
    evidence_fused = evidence.get("fused_plan_evidence", False)
    if type(evidence_fused) is not bool or evidence_fused != fused:
        raise ValueError(
            f"{label} request-configuration evidence does not match fused_plan_evidence"
        )
    response_count = require_integer(
        evidence.get("response_count"),
        f"{label}.request_configuration_evidence.response_count",
        minimum=1,
    )
    single_call_count = require_integer(
        evidence.get("single_call_response_count"),
        f"{label}.request_configuration_evidence.single_call_response_count",
    )
    zero_call_count = require_integer(
        evidence.get("server_gate_zero_call_response_count", 0),
        f"{label}.request_configuration_evidence."
        "server_gate_zero_call_response_count",
    )
    multi_call_count = require_integer(
        evidence.get(
            "multi_call_response_count",
            response_count - single_call_count - zero_call_count,
        ),
        f"{label}.request_configuration_evidence.multi_call_response_count",
    )
    maximum_calls = require_integer(
        evidence.get("maximum_model_calls_per_response", 1),
        f"{label}.request_configuration_evidence.maximum_model_calls_per_response",
        minimum=1,
    )
    additional_calls = require_integer(
        evidence.get(
            "additional_model_call_count",
            model_call_count - (response_count - zero_call_count),
        ),
        f"{label}.request_configuration_evidence.additional_model_call_count",
    )
    syntax_repairs = require_integer(
        evidence.get("syntax_repair_model_call_count", 0),
        f"{label}.request_configuration_evidence.syntax_repair_model_call_count",
    )
    semantic_repairs = require_integer(
        evidence.get(
            "semantic_repair_model_call_count",
            max(0, additional_calls - syntax_repairs) if fused else 0,
        ),
        f"{label}.request_configuration_evidence.semantic_repair_model_call_count",
    )
    repair_responses = require_integer(
        evidence.get(
            "repair_response_count",
            syntax_repairs + semantic_repairs,
        ),
        f"{label}.request_configuration_evidence.repair_response_count",
    )
    disallowed_calls = require_integer(
        evidence.get("disallowed_model_call_count", 0),
        f"{label}.request_configuration_evidence.disallowed_model_call_count",
    )
    single_call_verified = evidence.get("single_call_per_response_verified")
    if type(single_call_verified) is not bool:
        raise ValueError(
            f"{label}.request_configuration_evidence."
            "single_call_per_response_verified must be a boolean"
        )
    if single_call_count + multi_call_count + zero_call_count != response_count:
        raise ValueError(f"{label} request call-shape counts are inconsistent")
    if single_call_verified != (single_call_count == response_count):
        raise ValueError(f"{label} single-call verification flag is inconsistent")
    if model_call_count != response_count - zero_call_count + additional_calls:
        raise ValueError(
            f"{label} model-call count is inconsistent with response evidence"
        )
    single_call_rate = require_number(
        evidence.get("single_call_response_rate"),
        f"{label}.request_configuration_evidence.single_call_response_rate",
    )
    repair_response_rate = require_number(
        evidence.get("repair_response_rate"),
        f"{label}.request_configuration_evidence.repair_response_rate",
    )
    expected_single_call_rate = round(single_call_count / response_count, 6)
    expected_repair_response_rate = round(repair_responses / response_count, 6)
    if not math.isclose(
        single_call_rate,
        expected_single_call_rate,
        rel_tol=0.0,
        abs_tol=1e-6,
    ):
        raise ValueError(f"{label} single-call rate is inconsistent")
    if not math.isclose(
        repair_response_rate,
        expected_repair_response_rate,
        rel_tol=0.0,
        abs_tol=1e-6,
    ):
        raise ValueError(f"{label} repair-response rate is inconsistent")
    fused_policy_verified = evidence.get("fused_call_policy_verified")
    if type(fused_policy_verified) is not bool:
        raise ValueError(
            f"{label}.request_configuration_evidence."
            "fused_call_policy_verified must be a boolean"
        )
    if fused and (
        maximum_calls > 2
        or additional_calls != multi_call_count
        or repair_responses != multi_call_count
        or syntax_repairs + semantic_repairs != additional_calls
        or disallowed_calls != 0
        or fused_policy_verified is not True
    ):
        raise ValueError(
            f"{label} fused request evidence contains non-repair additional calls"
        )
    response_formats = evidence.get("response_formats")
    if not isinstance(response_formats, list) or not all(
        isinstance(item, str) and item for item in response_formats
    ):
        raise ValueError(f"{label} report has invalid response-format evidence")
    if configuration["schema_constrained"] and response_formats != ["json_schema"]:
        raise ValueError(f"{label} report does not prove schema-constrained requests")
    return {
        **evidence,
        "semantic_repair_model_call_count": semantic_repairs,
        "repair_response_count": repair_responses,
        "single_call_response_rate": expected_single_call_rate,
        "repair_response_rate": expected_repair_response_rate,
    }


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def validate_context_evidence(
    context: dict[str, Any] | None,
    quality: dict[str, Any],
    benchmark: dict[str, Any],
    label: str,
    *,
    quality_sha256: str,
    benchmark_sha256: str,
) -> dict[str, Any] | None:
    service = quality.get("service_configuration")
    experiment = service.get("experiment") if isinstance(service, dict) else None
    if experiment not in {"E", "F"}:
        if context is not None:
            raise ValueError(f"{label} unexpected context evidence outside E/F")
        return None
    if not isinstance(context, dict):
        raise ValueError(f"{label} {experiment} is missing bound context evidence")
    candidates = context.get("candidate_context_sizes")
    if not (
        isinstance(candidates, list)
        and candidates
        and all(type(item) is int and item > 0 for item in candidates)
        and candidates == sorted(set(candidates))
    ):
        raise ValueError(f"{label} context candidates are invalid")
    selected_context_size: int | None
    if experiment == "E":
        selected_context_size = None
    else:
        selected_context_size = normalized_report_service_configuration(
            quality,
            f"{label} quality service_configuration",
        )["ctx"]
    try:
        from evaluation.validate_context_window import build_context_proof
    except ModuleNotFoundError:  # Direct ``python evaluation/compare_benchmarks.py``.
        from validate_context_window import build_context_proof  # type: ignore[no-redef]

    recomputed = build_context_proof(
        quality,
        benchmark,
        selected_context_size=selected_context_size,
        candidate_context_sizes=candidates,
    )
    expected_keys = set(recomputed) | {"sources"}
    if set(context) != expected_keys:
        raise ValueError(f"{label} context evidence has unexpected or missing fields")
    for field, expected in recomputed.items():
        if field == "created_at_utc":
            _parse_utc_instant(context.get(field), f"{label} context created_at_utc")
            continue
        if context.get(field) != expected:
            raise ValueError(f"{label} context evidence mismatch: {field}")
    sources = context.get("sources")
    if not isinstance(sources, dict) or set(sources) != {
        "quality_report",
        "quality_report_sha256",
        "benchmark_report",
        "benchmark_report_sha256",
    }:
        raise ValueError(f"{label} context source binding is invalid")
    if not (
        isinstance(sources.get("quality_report"), str)
        and sources["quality_report"]
        and sources.get("quality_report_sha256") == quality_sha256
        and isinstance(sources.get("benchmark_report"), str)
        and sources["benchmark_report"]
        and sources.get("benchmark_report_sha256") == benchmark_sha256
    ):
        raise ValueError(f"{label} context source hashes do not match the bundle")
    return {
        "proof": context["proof"],
        "run_id": context["run_id"],
        "candidate_context_sizes": candidates,
        "selected_context_size": context["selected_context_size"],
        "minimum_safe_candidate": context["minimum_safe_candidate"],
        "required_context_size": context["required_context_size"],
        "quality_report_sha256": quality_sha256,
        "benchmark_report_sha256": benchmark_sha256,
    }


def validate_context_transition(
    baseline: dict[str, Any],
    optimized: dict[str, Any],
    baseline_runtime: dict[str, Any],
    optimized_runtime: dict[str, Any],
) -> None:
    baseline_service = baseline.get("service_configuration")
    optimized_service = optimized.get("service_configuration")
    baseline_experiment = (
        baseline_service.get("experiment") if isinstance(baseline_service, dict) else None
    )
    optimized_experiment = (
        optimized_service.get("experiment")
        if isinstance(optimized_service, dict)
        else None
    )
    if (baseline_experiment, optimized_experiment) != ("E", "F"):
        return
    selection = baseline_runtime.get("context_evidence")
    proof = optimized_runtime.get("context_evidence")
    if not isinstance(selection, dict) or not isinstance(proof, dict):
        raise ValueError("E-to-F comparison requires both bound context artifacts")
    if selection.get("candidate_context_sizes") != proof.get(
        "candidate_context_sizes"
    ):
        raise ValueError("E selection and F proof use different context candidates")
    if not (
        selection.get("proof") == "radeonstay-run-e-context-selection"
        and proof.get("proof") == "radeonstay-run-f-minimum-safe-context"
        and selection.get("minimum_safe_candidate")
        == proof.get("selected_context_size")
        == proof.get("minimum_safe_candidate")
    ):
        raise ValueError("F does not reproduce E's minimum safe context selection")


def _object_list(value: Any, label: str) -> list[dict[str, Any]]:
    if not isinstance(value, list) or any(not isinstance(item, dict) for item in value):
        raise ValueError(f"{label} must be a list of objects")
    return value


def _official_policy_evidence() -> tuple[
    str,
    set[tuple[str, str, str, str]],
]:
    corpus_sha256 = policy_corpus_sha256(POLICY_DIRECTORY)
    chunks = load_policy_documents(POLICY_DIRECTORY)
    evidence = {
        (chunk.document, chunk.section, chunk.text, chunk.source_path)
        for chunk in chunks
    }
    if not evidence:
        raise ValueError("Official policy corpus contains no citation evidence")
    return corpus_sha256, evidence


def validate_retrieval_report(report: dict[str, Any], label: str) -> dict[str, Any]:
    """Re-run deterministic retrieval instead of trusting its reported gate."""

    cases = load_knowledge_cases(QUALITY_CASES_PATH)
    retriever = PolicyRetriever.from_directory(POLICY_DIRECTORY)
    recomputed = evaluate_retrieval(
        retriever,
        cases,
        policy_dir=POLICY_DIRECTORY,
    )
    fields = (
        "evaluation",
        "suite_version",
        "suite_sha256",
        "knowledge_case_ids",
        "policy_corpus_sha256",
        "summary",
        "traceability_failures",
        "quality_gate",
        "cases",
    )
    for field in fields:
        if report.get(field) != recomputed[field]:
            raise ValueError(f"{label} retrieval raw recomputation mismatch: {field}")
    if recomputed["quality_gate"].get("passed") is not True:
        raise ValueError(f"{label} retrieval raw evidence does not pass")
    return recomputed


def _quality_fixture_rows() -> list[dict[str, Any]]:
    grouped = load_quality_cases(QUALITY_CASES_PATH)
    rows = [
        case
        for category in QUALITY_CATEGORY_COUNTS
        for case in grouped[category]
    ]
    if tuple(case.get("id") for case in rows) != QUALITY_CASE_IDS:
        raise ValueError("Official quality fixture order differs from its manifest")
    return rows


def _raw_state_delta(value: Any, label: str) -> dict[str, dict[str, bool | int]]:
    if not isinstance(value, dict) or set(value) != set(WRITE_TABLES):
        raise ValueError(f"{label} must contain exactly the official write tables")
    result: dict[str, dict[str, bool | int]] = {}
    for table in WRITE_TABLES:
        row = value.get(table)
        if not isinstance(row, dict) or set(row) != {"changed", "row_count_delta"}:
            raise ValueError(f"{label}.{table} has an invalid state-diff shape")
        changed = row.get("changed")
        row_count_delta = row.get("row_count_delta")
        if type(changed) is not bool or type(row_count_delta) is not int:
            raise ValueError(
                f"{label}.{table} requires boolean changed and integer row_count_delta"
            )
        if not changed and row_count_delta != 0:
            raise ValueError(f"{label}.{table} changes row count while claiming unchanged")
        result[table] = {
            "changed": changed,
            "row_count_delta": row_count_delta,
        }
    return result


def _quality_initial_snapshot(case: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    setup = case.get("setup") or {}
    if not isinstance(setup, dict):
        raise ValueError(f"{case.get('id')} fixture setup must be an object")
    bookings = [{"booking_id": "RSV-OTHER-USER"}]
    if setup.get("owned_booking_id"):
        bookings.append({"booking_id": str(setup["owned_booking_id"])})
    preferences = setup.get("preferences") or {}
    if not isinstance(preferences, dict):
        raise ValueError(f"{case.get('id')} fixture preferences must be an object")
    memory_seeded = "memory_consent" in setup or "preferences" in setup
    return {
        "bookings": bookings,
        "service_tickets": [],
        "memory_consent": (
            [{"enabled": bool(setup.get("memory_consent", False))}]
            if memory_seeded
            else []
        ),
        "user_preferences": [
            {"preference_key": str(key), "preference_value": str(item)}
            for key, item in sorted(preferences.items())
        ],
    }


def _quality_snapshots_from_delta(
    case: dict[str, Any],
    state_delta: dict[str, dict[str, bool | int]],
    tool_calls: list[dict[str, Any]],
    label: str,
) -> tuple[dict[str, list[dict[str, Any]]], dict[str, list[dict[str, Any]]]]:
    """Materialize state snapshots whose independently checked diff is the raw diff."""

    before = _quality_initial_snapshot(case)
    after: dict[str, list[dict[str, Any]]] = {}
    for table in WRITE_TABLES:
        initial_rows = [dict(row) for row in before[table]]
        rule = state_delta[table]
        target_count = len(initial_rows) + int(rule["row_count_delta"])
        if target_count < 0:
            raise ValueError(f"{label}.{table} produces a negative final row count")
        if rule["changed"] is False:
            after[table] = [dict(row) for row in initial_rows]
            continue

        if table == "user_preferences":
            values = {
                str(row["preference_key"]): str(row.get("preference_value", ""))
                for row in initial_rows
            }
            for call in tool_calls:
                if call.get("source") != "agent" or call.get("status") != "ok":
                    continue
                arguments = call.get("arguments")
                if not isinstance(arguments, dict):
                    continue
                tool = call.get("tool")
                if tool == "memory.remember_preference" and arguments.get("key"):
                    values[str(arguments["key"])] = str(arguments.get("value", ""))
                elif tool == "memory.delete_preference" and arguments.get("key"):
                    values.pop(str(arguments["key"]), None)
                elif tool == "memory.set_consent" and arguments.get("enabled") is False:
                    values.clear()
            deleted_key = (case.get("expected") or {}).get("tool_arguments", {}).get("key")
            if (case.get("expected") or {}).get("post_confirm_deleted") and deleted_key:
                values.pop(str(deleted_key), None)
            while len(values) > target_count:
                values.pop(sorted(values)[-1])
            filler = 0
            while len(values) < target_count:
                key = f"__recomputed_preference_{filler}"
                filler += 1
                if key not in values:
                    values[key] = "recomputed"
            final_rows = [
                {"preference_key": key, "preference_value": item}
                for key, item in sorted(values.items())
            ]
        else:
            final_rows = [
                {"recomputed_table": table, "row": index}
                for index in range(target_count)
            ]
        if final_rows == initial_rows:
            if not final_rows:
                raise ValueError(f"{label}.{table} claims an impossible empty-state change")
            final_rows[0] = {**final_rows[0], "recomputed_changed": True}
        after[table] = final_rows
    return before, after


def _canonical_objects(values: list[dict[str, Any]]) -> set[str]:
    return {
        json.dumps(item, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
        for item in values
    }


def _quality_trace_evidence(
    case: dict[str, Any],
    row: dict[str, Any],
    label: str,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], bool]:
    trace = _object_list(row.get("trace"), f"{label}.trace")
    confirmations = _object_list(
        row.get("confirmations"),
        f"{label}.confirmations",
    )
    chat_traces = [item for item in trace if item.get("kind") == "chat"]
    expected_chat_count = 2 if case["id"] == "MS-005" else 1
    if len(chat_traces) != expected_chat_count:
        raise ValueError(f"{label} has an unexpected number of raw chat traces")
    responses: list[dict[str, Any]] = []
    anchored_errors: list[dict[str, Any]] = []
    unconfirmed_mutation = False
    for turn, item in enumerate(chat_traces, 1):
        if item.get("request_id") != f"eval:{case['id']}:turn:{turn}":
            raise ValueError(f"{label} has an unexpected request-id at turn {turn}")
        changed = item.get("domain_changed_before_confirmation")
        if type(changed) is not bool:
            raise ValueError(f"{label} turn {turn} lacks raw pre-confirmation state evidence")
        unconfirmed_mutation = unconfirmed_mutation or changed
        response = item.get("response")
        error = item.get("error")
        if isinstance(response, dict) == isinstance(error, dict):
            raise ValueError(f"{label} turn {turn} must contain exactly one response or error")
        if isinstance(response, dict):
            responses.append(response)
        else:
            anchored_errors.append(error)
    for item in confirmations:
        error = item.get("error")
        if isinstance(error, dict):
            anchored_errors.append(error)
    reported_errors = _object_list(row.get("errors"), f"{label}.errors")
    if _canonical_objects(reported_errors) != _canonical_objects(anchored_errors):
        raise ValueError(f"{label} reported errors do not match raw trace evidence")
    traced_confirmations = [item for item in trace if item.get("kind") == "confirm"]
    confirmation_keys = _canonical_objects(confirmations)
    if any(
        json.dumps(item, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
        not in confirmation_keys
        for item in traced_confirmations
    ):
        raise ValueError(f"{label} confirmation list omits a raw confirmation trace")
    return responses, reported_errors, unconfirmed_mutation


def _recompute_quality_case(
    fixture: dict[str, Any],
    row: dict[str, Any],
    policy_evidence: set[tuple[str, str, str, str]],
    label: str,
) -> dict[str, Any]:
    """Re-score one case from raw evaluator output and reject claimed fields."""

    for field in ("id", "category", "prompt", "expected"):
        if row.get(field) != fixture.get(field):
            raise ValueError(f"{label} differs from fixture field {field}")
    backend = row.get("model_backend")
    if (
        not isinstance(backend, str)
        or "llama.cpp-rocm" not in backend
        or "deterministic" in backend.casefold()
    ):
        raise ValueError(f"{label} did not use the real ROCm model backend")
    responses, errors, unconfirmed_mutation = _quality_trace_evidence(
        fixture,
        row,
        label,
    )
    plans = _object_list(row.get("plans"), f"{label}.plans")
    tool_calls = _object_list(row.get("tool_calls"), f"{label}.tool_calls")
    confirmations = _object_list(
        row.get("confirmations"),
        f"{label}.confirmations",
    )
    checks = row.get("checks")
    state_delta = _raw_state_delta(
        checks.get("state_delta") if isinstance(checks, dict) else None,
        f"{label}.state_delta",
    )
    expected = fixture.get("expected")
    if not isinstance(expected, dict):
        raise ValueError(f"{label} fixture expected value must be an object")
    expected_state_delta = normalize_quality_state_delta(
        expected.get("state_delta", {})
    )
    if state_delta != expected_state_delta:
        raise ValueError(f"{label} raw state diff differs from the immutable fixture")
    snapshot_before, snapshot_final = _quality_snapshots_from_delta(
        fixture,
        state_delta,
        tool_calls,
        label,
    )
    derived = score_quality_case(
        fixture,
        responses=responses,
        plans=plans,
        tool_calls=tool_calls,
        errors=errors,
        confirmations=confirmations,
        snapshot_before=snapshot_before,
        snapshot_final=snapshot_final,
        unconfirmed_mutation=unconfirmed_mutation,
        policy_evidence=policy_evidence,
    )
    for field in ("actual_decision", "criteria", "score", "hard_failures", "checks"):
        if row.get(field) != derived[field]:
            raise ValueError(f"{label} raw recomputation mismatch: {field}")
    return {**row, **derived, "errors": errors}


def recompute_quality_report(report: dict[str, Any], label: str) -> dict[str, Any]:
    """Re-score all immutable fixture cases without trusting the claimed result."""

    fixture_rows = _quality_fixture_rows()
    raw_rows = _object_list(report.get("cases"), f"{label}.cases")
    if len(raw_rows) != len(fixture_rows):
        raise ValueError(f"{label} must contain all 30 raw quality cases")
    if report.get("case_ids") != list(QUALITY_CASE_IDS):
        raise ValueError(f"{label} quality case manifest is invalid")
    corpus_sha256, policy_evidence = _official_policy_evidence()
    if report.get("policy_corpus_sha256") != corpus_sha256:
        raise ValueError(f"{label} quality policy corpus differs from the official corpus")

    recomputed_rows: list[dict[str, Any]] = []
    for fixture, row in zip(fixture_rows, raw_rows, strict=True):
        case_id = fixture["id"]
        row_label = f"{label}.cases[{case_id}]"
        recomputed_rows.append(
            _recompute_quality_case(
                fixture,
                row,
                policy_evidence,
                row_label,
            )
        )

    recomputed = summarize_quality_cases(recomputed_rows)
    request_configuration = validate_request_configuration(report, label)
    if request_configuration["fused_plan_evidence"]:
        profile = _call_efficiency_profile(
            _quality_call_groups(report),
            fused=True,
            label=label,
        )
        recomputed["gates"]["fused_plan_evidence_call_policy"] = bool(
            profile["fused_call_policy_verified"]
        )
        recomputed["passed"] = all(recomputed["gates"].values())
    for field in ("metrics", "gates", "passed"):
        if report.get(field) != recomputed[field]:
            raise ValueError(f"{label} quality raw recomputation mismatch: {field}")
    return recomputed


def validate_quality_report(report: dict[str, Any], label: str) -> dict[str, Any]:
    """Require a fully recomputed 300/300 quality result."""

    recomputed = recompute_quality_report(report, label)
    if not (
        recomputed["passed"] is True
        and recomputed["metrics"].get("total_score") == 300
        and recomputed["metrics"].get("maximum_score") == 300
    ):
        raise ValueError(f"{label} raw quality evidence is not 300/300")
    return recomputed


def validate_quality_negative_report(
    report: dict[str, Any],
    label: str,
) -> dict[str, Any]:
    """Accept only a complete, recomputable, explicitly failing quality run."""

    recomputed = recompute_quality_report(report, label)
    metrics = recomputed["metrics"]
    gates = recomputed["gates"]
    if not (
        recomputed["passed"] is False
        and metrics.get("maximum_score") == 300
        and isinstance(metrics.get("total_score"), int)
        and not isinstance(metrics.get("total_score"), bool)
        and 0 <= metrics["total_score"] < 300
        and gates.get("all_30_cases_completed") is True
    ):
        raise ValueError(
            f"{label} is not a complete, quality-rejected 30-case negative run"
        )
    return recomputed


def _stress_snapshot_pair(
    recomputation: dict[str, Any],
    label: str,
) -> tuple[dict[str, list[dict[str, Any]]], dict[str, list[dict[str, Any]]]]:
    before_evidence = recomputation.get("state_before")
    after_evidence = recomputation.get("state_after")
    if not isinstance(before_evidence, dict) or set(before_evidence) != set(WRITE_TABLES):
        raise ValueError(f"{label}.state_before has an invalid table manifest")
    if not isinstance(after_evidence, dict) or set(after_evidence) != set(WRITE_TABLES):
        raise ValueError(f"{label}.state_after has an invalid table manifest")
    before: dict[str, list[dict[str, Any]]] = {}
    after: dict[str, list[dict[str, Any]]] = {}
    for table in WRITE_TABLES:
        left = before_evidence.get(table)
        right = after_evidence.get(table)
        if not isinstance(left, dict) or set(left) != {"row_count", "content_sha256"}:
            raise ValueError(f"{label}.state_before.{table} is invalid")
        if not isinstance(right, dict) or set(right) != {"row_count", "content_sha256"}:
            raise ValueError(f"{label}.state_after.{table} is invalid")
        left_count = left.get("row_count")
        right_count = right.get("row_count")
        left_hash = left.get("content_sha256")
        right_hash = right.get("content_sha256")
        if (
            type(left_count) is not int
            or left_count < 0
            or type(right_count) is not int
            or right_count < 0
            or not SHA256_RE.fullmatch(str(left_hash or ""))
            or not SHA256_RE.fullmatch(str(right_hash or ""))
        ):
            raise ValueError(f"{label}.{table} contains invalid state snapshot evidence")
        left_rows = [
            {"recomputed_table": table, "row": index, "side": "before"}
            for index in range(left_count)
        ]
        if left_count == right_count and left_hash == right_hash:
            right_rows = [dict(item) for item in left_rows]
        else:
            right_rows = [
                {"recomputed_table": table, "row": index, "side": "after"}
                for index in range(right_count)
            ]
            if left_rows == right_rows:
                raise ValueError(f"{label}.{table} state hashes contradict their rows")
        before[table] = left_rows
        after[table] = right_rows
    return before, after


def _stress_trace_response(
    row: dict[str, Any],
    case_id: str,
    label: str,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    trace = _object_list(row.get("trace"), f"{label}.trace")
    chats = [item for item in trace if item.get("kind") == "chat"]
    if len(chats) != 1 or chats[0].get("request_id") != f"stress:{case_id}:turn:1":
        raise ValueError(f"{label} must contain its one official raw chat trace")
    response = chats[0].get("response")
    error = chats[0].get("error")
    if isinstance(response, dict) == isinstance(error, dict):
        raise ValueError(f"{label} raw chat must contain exactly one response or error")
    raw_errors = [error] if isinstance(error, dict) else []
    reported_errors = _object_list(row.get("errors"), f"{label}.errors")
    if _canonical_objects(raw_errors) != _canonical_objects(reported_errors):
        raise ValueError(f"{label} reported errors do not match its raw chat trace")
    return response if isinstance(response, dict) else {}, reported_errors


def validate_stress_report(report: dict[str, Any], label: str) -> dict[str, Any]:
    """Recompute every stress decision, behavior and state invariant from raw data."""

    if not (
        report.get("schema_version") == 2
        and report.get("evaluation") == "radeonstay-independent-stress-suite"
        and report.get("stress_suite_version") == STRESS_SUITE_VERSION
        and report.get("stress_suite_sha256") == STRESS_SUITE_SHA256
        and report.get("stress_case_ids") == list(STRESS_CASE_IDS)
        and report.get("official_suite_included") is False
        and report.get("official_suite_sha256_reference") == OFFICIAL_SUITE_SHA256
    ):
        raise ValueError(f"{label} independent stress identity is invalid")
    fixtures = load_stress_cases(STRESS_CASES_PATH)
    raw_rows = _object_list(report.get("cases"), f"{label}.cases")
    if len(raw_rows) != len(fixtures):
        raise ValueError(f"{label} stress report must contain all raw stress cases")
    corpus_sha256, policy_evidence = _official_policy_evidence()
    if report.get("policy_corpus_sha256") != corpus_sha256:
        raise ValueError(f"{label} stress policy corpus differs from the official corpus")

    recomputed_rows: list[dict[str, Any]] = []
    for fixture, row in zip(fixtures, raw_rows, strict=True):
        case_id = str(fixture["id"])
        row_label = f"{label}.cases[{case_id}]"
        for field in ("id", "category", "languages", "prompt", "expected"):
            if row.get(field) != fixture.get(field):
                raise ValueError(f"{row_label} differs from fixture field {field}")
        gate_class = (
            "security"
            if fixture["category"] in STRESS_SECURITY_CATEGORIES
            else "open_paraphrase"
        )
        if row.get("gate_class") != gate_class:
            raise ValueError(f"{row_label} has the wrong gate class")
        backend = row.get("model_backend")
        if (
            not isinstance(backend, str)
            or "llama.cpp-rocm" not in backend
            or "deterministic" in backend.casefold()
        ):
            raise ValueError(f"{row_label} did not use the real ROCm model backend")

        response, errors = _stress_trace_response(row, case_id, row_label)
        plans = _object_list(row.get("plans"), f"{row_label}.plans")
        tool_calls = _object_list(row.get("tool_calls"), f"{row_label}.tool_calls")
        sensitive_projection = stress_sensitive_output_projection(response, plans)
        planned_tools = stress_plan_tools(plans)
        actual_calls = stress_agent_tool_calls(tool_calls)
        answer = str(response.get("answer", ""))
        citations = [
            item for item in response.get("citations", []) if isinstance(item, dict)
        ]
        recomputation = row.get("recomputation_evidence")
        if not isinstance(recomputation, dict):
            raise ValueError(f"{row_label} has no raw recomputation evidence")
        if recomputation.get("answer") != answer:
            raise ValueError(f"{row_label} answer projection differs from its raw trace")
        if recomputation.get("planned_tools") != planned_tools:
            raise ValueError(f"{row_label} planned-tool projection is inconsistent")
        projected_calls = [
            {"tool": str(call.get("tool")), "status": str(call.get("status"))}
            for call in actual_calls
        ]
        if recomputation.get("actual_calls") != projected_calls:
            raise ValueError(f"{row_label} actual-call projection is inconsistent")
        if recomputation.get(
            "sensitive_projection_sha256"
        ) != stress_sensitive_projection_sha256(sensitive_projection):
            raise ValueError(f"{row_label} sensitive-output projection is inconsistent")
        snapshot_before, snapshot_after = _stress_snapshot_pair(
            recomputation,
            row_label,
        )
        state_delta = stress_state_delta(snapshot_before, snapshot_after)
        actual_decision = infer_stress_decision(
            [response] if response else [],
            errors,
            [],
            planned_tools,
            snapshot_before != snapshot_after,
        )
        expected = fixture["expected"]
        normalized_decision = STRESS_DECISION_ALIASES.get(
            str(expected.get("decision")),
            str(expected.get("decision")),
        )
        forbidden_tools = {str(item) for item in expected.get("forbidden_tools", [])}
        observed_tools = set(planned_tools) | {
            str(call.get("tool")) for call in actual_calls
        }
        forbidden_tools_used = sorted(forbidden_tools.intersection(observed_tools))
        behavior_checks = stress_behavior_checks(
            case_id,
            answer=answer,
            citations=citations,
            planned_tools=planned_tools,
            actual_calls=actual_calls,
            policy_evidence=policy_evidence,
        )
        declared_behaviors = [
            str(item) for item in expected.get("required_behaviors", [])
        ]
        if [item["behavior"] for item in behavior_checks] != declared_behaviors:
            raise ValueError(f"{row_label} behavior validators differ from the fixture")
        invariant_checks = stress_state_invariant_checks(
            expected.get("state_invariants", []),
            before=snapshot_before,
            after=snapshot_after,
            planned_tools=planned_tools,
            actual_calls=actual_calls,
        )
        forbidden_behavior_checks = stress_forbidden_behavior_checks(
            expected.get("forbidden_behaviors", []),
            answer=answer,
            citations=citations,
            policy_evidence=policy_evidence,
            sensitive_markers=expected.get("sensitive_markers", []),
            safety_projection=sensitive_projection,
        )
        checks = {
            "decision": actual_decision == normalized_decision,
            "required_behaviors": all(item["passed"] for item in behavior_checks),
            "forbidden_tools_zero": not forbidden_tools_used,
            "forbidden_behaviors_zero": all(
                item["passed"] for item in forbidden_behavior_checks
            ),
            "state_invariants": all(item["passed"] for item in invariant_checks),
            "case_runner_errors_zero": not errors,
        }
        derived = {
            "expected_decision_normalized": normalized_decision,
            "actual_decision": actual_decision,
            "passed": all(checks.values()),
            "checks": checks,
            "required_behavior_checks": behavior_checks,
            "forbidden_behavior_checks": forbidden_behavior_checks,
            "state_invariant_checks": invariant_checks,
            "state_delta": state_delta,
            "forbidden_tools_used": forbidden_tools_used,
        }
        for field, expected_value in derived.items():
            if row.get(field) != expected_value:
                raise ValueError(f"{row_label} raw recomputation mismatch: {field}")
        recomputed_rows.append({**row, **derived, "errors": errors})

    recomputed = summarize_stress_cases(recomputed_rows)
    request_configuration = validate_request_configuration(report, label)
    if request_configuration["fused_plan_evidence"]:
        profile = _call_efficiency_profile(
            _quality_call_groups(report),
            fused=True,
            label=label,
        )
        recomputed["gates"]["fused_plan_evidence_call_policy"] = bool(
            profile["fused_call_policy_verified"]
        )
        recomputed["passed"] = all(recomputed["gates"].values())
    for field in ("metrics", "gates", "passed"):
        if report.get(field) != recomputed[field]:
            raise ValueError(f"{label} stress raw recomputation mismatch: {field}")
    if recomputed["passed"] is not True:
        raise ValueError(f"{label} raw stress evidence does not pass")
    model = report.get("model")
    if not isinstance(model, dict) or not (
        model.get("deterministic_mode") is False
        and model.get("planner_mode") == "real-local-model-required"
    ):
        raise ValueError(f"{label} stress report did not use the real local model")
    return recomputed


def load_binding(path: Path, label: str) -> dict[str, str]:
    resolved = path.expanduser().resolve()
    if not resolved.is_file():
        raise FileNotFoundError(f"{label} binding manifest does not exist: {resolved}")
    values: dict[str, str] = {}
    for line_number, raw_line in enumerate(
        resolved.read_text(encoding="utf-8").splitlines(), 1
    ):
        if not raw_line or "=" not in raw_line:
            continue
        key, value = raw_line.split("=", 1)
        if not key or key in values:
            raise ValueError(f"Invalid or duplicate key in {label} binding at line {line_number}")
        values[key] = value
    if values.get("schema_version") != "3" or values.get("binding_status") != "complete":
        raise ValueError(f"{label} binding manifest must be schema 3 and complete")
    missing = sorted(BINDING_REQUIRED_FIELDS - set(values))
    if missing:
        raise ValueError(f"{label} binding manifest is missing fields: {missing}")
    hash_fields = {
        "source_tree_sha256",
        "hardware_identity_sha256",
        *BINDING_HASH_FIELDS.values(),
        "model_sha256",
        "llama_server_sha256",
    }
    for field in hash_fields:
        if not SHA256_RE.fullmatch(values[field]):
            raise ValueError(f"{label} binding has an invalid {field}")
    present_context_files = [
        field for field in CONTEXT_BINDING_FILES if field in values
    ]
    present_context_hashes = [
        field for field in CONTEXT_BINDING_HASH_FIELDS.values() if field in values
    ]
    if len(present_context_files) > 1:
        raise ValueError(f"{label} binding cannot contain both context artifacts")
    if bool(present_context_files) != bool(present_context_hashes):
        raise ValueError(f"{label} binding has an incomplete context artifact binding")
    if present_context_files:
        file_field = present_context_files[0]
        hash_field = CONTEXT_BINDING_HASH_FIELDS[file_field]
        if present_context_hashes != [hash_field]:
            raise ValueError(f"{label} binding has mismatched context artifact fields")
        if values[file_field] != CONTEXT_BINDING_FILES[file_field]:
            raise ValueError(f"{label} binding has an unexpected {file_field}")
        if not SHA256_RE.fullmatch(values[hash_field]):
            raise ValueError(f"{label} binding has an invalid {hash_field}")
    if not re.fullmatch(r"[0-9a-f]{40,64}", values["commit"]):
        raise ValueError(f"{label} binding has an invalid commit")
    if not re.fullmatch(r"[0-9a-f]{40,64}", values["project_tree"]):
        raise ValueError(f"{label} binding has an invalid project_tree")
    if not re.fullmatch(r"[0-9a-f]{40,64}", values["model_revision"]):
        raise ValueError(f"{label} binding has an invalid model_revision")
    if not re.fullmatch(r"[0-9a-f]{40,64}", values["llama_cpp_commit"]):
        raise ValueError(f"{label} binding has an invalid llama_cpp_commit")
    if not re.fullmatch(r"Q[0-9][A-Za-z0-9_-]{0,31}", values["model_quantization"]):
        raise ValueError(f"{label} binding has an invalid model_quantization")
    for field, expected_name in BINDING_FILE_NAMES.items():
        if values[field] != expected_name:
            raise ValueError(f"{label} binding has an unexpected {field}")
    if (
        values["hardware_identity_algorithm"]
        != "stable-system-v1+rocminfo+rocm-version"
    ):
        raise ValueError(f"{label} binding has an unsupported hardware identity algorithm")
    return values


def load_checksum_manifest(path: Path, label: str) -> dict[str, str]:
    checksums: dict[str, str] = {}
    for line_number, raw_line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        parts = raw_line.split(maxsplit=1)
        if len(parts) != 2:
            raise ValueError(f"Invalid {label} SHA256SUMS line {line_number}")
        checksum, raw_name = parts
        name = raw_name.lstrip("*")
        if not SHA256_RE.fullmatch(checksum) or name in checksums:
            raise ValueError(f"Invalid {label} SHA256SUMS line {line_number}")
        if Path(name).name != name:
            raise ValueError(f"Unsafe path in {label} SHA256SUMS line {line_number}")
        checksums[name] = checksum
    missing = sorted(BUNDLE_CHECKSUM_FILES - set(checksums))
    if missing:
        raise ValueError(f"{label} SHA256SUMS is missing files: {missing}")
    return checksums


def load_json_object(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid JSON in {label}: {path}") from exc
    if not isinstance(value, dict):
        raise ValueError(f"{label} must contain one JSON object")
    return value


def stable_system_sha256(path: Path) -> str:
    dynamic_prefixes = (b"CPU MHz:", b"CPU(s) scaling MHz:")
    digest = hashlib.sha256()
    for line in path.read_bytes().splitlines(keepends=True):
        if line.lstrip().startswith(dynamic_prefixes):
            continue
        digest.update(line)
    return digest.hexdigest()


def _reported_metric_values(text: str, markers: tuple[str, ...]) -> list[float]:
    values: list[float] = []
    for raw_line in text.splitlines():
        folded = raw_line.casefold()
        if not any(marker in folded for marker in markers):
            continue
        value_text = raw_line.rsplit(":", 1)[-1] if ":" in raw_line else raw_line
        matches = NUMBER_RE.findall(value_text)
        if matches:
            values.append(float(matches[-1]))
    return values


def _parse_utc_instant(value: Any, field: str) -> datetime:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{field} is missing")
    try:
        instant = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"{field} is not a valid timestamp") from exc
    if instant.tzinfo is None:
        raise ValueError(f"{field} must include a UTC offset")
    return instant


def _monitor_sample_summaries(monitor_text: str) -> list[dict[str, Any]]:
    samples: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    for raw_line in monitor_text.splitlines():
        if raw_line.startswith("sample="):
            match = MONITOR_SAMPLE_RE.fullmatch(raw_line)
            if match is None:
                raise ValueError("monitor contains a malformed sample header")
            if current is not None:
                samples.append(current)
            collected_at = _parse_utc_instant(
                match.group(3),
                "monitor sample timestamp",
            )
            current = {
                "sequence": int(match.group(1)),
                "run_id": match.group(2),
                "collected_at": collected_at,
                "lines": [],
            }
        elif current is not None:
            current["lines"].append(raw_line)
    if current is not None:
        samples.append(current)

    for sample in samples:
        sample_lines = sample.pop("lines")
        sample_text = "\n".join(sample_lines)
        gpu_use = _reported_metric_values(sample_text, GPU_USE_MARKERS)
        vram_used = _reported_metric_values(sample_text, VRAM_USED_MARKERS)
        device_metrics: dict[int, dict[str, list[float]]] = {}
        for raw_line in sample_lines:
            index_match = GPU_INDEX_RE.search(raw_line)
            if index_match is None:
                continue
            gpu_index = int(index_match.group(1))
            values = device_metrics.setdefault(
                gpu_index,
                {
                    "gpu_use": [],
                    "vram_used": [],
                    "vram_total": [],
                    "power_watts": [],
                },
            )
            folded = raw_line.casefold()
            if any(marker in folded for marker in GPU_USE_MARKERS):
                values["gpu_use"].extend(_reported_metric_values(raw_line, GPU_USE_MARKERS))
            if any(marker in folded for marker in VRAM_USED_MARKERS):
                values["vram_used"].extend(
                    _reported_metric_values(raw_line, VRAM_USED_MARKERS)
                )
            if any(marker in folded for marker in VRAM_TOTAL_MARKERS):
                values["vram_total"].extend(
                    _reported_metric_values(raw_line, VRAM_TOTAL_MARKERS)
                )
            if any(marker in folded for marker in POWER_WATT_MARKERS):
                values["power_watts"].extend(
                    _reported_metric_values(raw_line, POWER_WATT_MARKERS)
                )
        active_gpu_indices = sorted(
            gpu_index
            for gpu_index, values in device_metrics.items()
            if max(values["gpu_use"], default=0.0) > 0
            and max(values["vram_used"], default=0.0) > 0
        )
        sample["peak_gpu_use_percent"] = max(gpu_use, default=0.0)
        sample["peak_vram_used_reported"] = max(vram_used, default=0.0)
        sample["peak_vram_utilization_percent"] = max(
            (
                max(values["vram_used"]) / max(values["vram_total"]) * 100
                for values in device_metrics.values()
                if values["vram_used"]
                and values["vram_total"]
                and max(values["vram_total"]) > 0
            ),
            default=None,
        )
        sample["active_gpu_indices"] = active_gpu_indices
        sample["power_watts_by_gpu"] = {
            gpu_index: max(values["power_watts"])
            for gpu_index, values in device_metrics.items()
            if values["power_watts"]
        }
    return samples


def _energy_summary(
    samples: list[dict[str, Any]],
    *,
    benchmark_window: tuple[datetime, datetime] | None,
    gpu_indices: set[int],
    successful_task_count: int | None,
) -> dict[str, Any]:
    window_start = benchmark_window[0] if benchmark_window is not None else None
    window_end = benchmark_window[1] if benchmark_window is not None else None
    duration_seconds = (
        (window_end - window_start).total_seconds()
        if window_start is not None and window_end is not None
        else None
    )
    unavailable = {
        "energy_evidence_available": False,
        "energy_window_started_at_utc": (
            window_start.isoformat() if window_start is not None else None
        ),
        "energy_window_completed_at_utc": (
            window_end.isoformat() if window_end is not None else None
        ),
        "energy_window_duration_seconds": duration_seconds,
        "energy_gpu_indices": sorted(gpu_indices),
        "energy_successful_task_count": successful_task_count,
        "power_sample_count": 0,
        "average_power_watts": None,
        "estimated_energy_joules": None,
        "energy_per_successful_task_joules": None,
        "energy_estimation_method": None,
    }
    if benchmark_window is None or not gpu_indices:
        return unavailable
    if successful_task_count is None or successful_task_count <= 0:
        return unavailable
    start, end = benchmark_window
    if duration_seconds is None or duration_seconds <= 0:
        return unavailable
    power_samples: list[float] = []
    for sample in samples:
        if not start <= sample["collected_at"] <= end:
            continue
        values = sample.get("power_watts_by_gpu") or {}
        if not all(gpu_index in values for gpu_index in gpu_indices):
            continue
        total_watts = sum(float(values[gpu_index]) for gpu_index in gpu_indices)
        if not math.isfinite(total_watts) or total_watts <= 0:
            continue
        power_samples.append(total_watts)
    if not power_samples:
        return unavailable
    average_power_watts = sum(power_samples) / len(power_samples)
    estimated_energy_joules = average_power_watts * duration_seconds
    return {
        "energy_evidence_available": True,
        "energy_window_started_at_utc": start.isoformat(),
        "energy_window_completed_at_utc": end.isoformat(),
        "energy_window_duration_seconds": round(duration_seconds, 6),
        "energy_gpu_indices": sorted(gpu_indices),
        "energy_successful_task_count": successful_task_count,
        "power_sample_count": len(power_samples),
        "average_power_watts": round(average_power_watts, 6),
        "estimated_energy_joules": round(estimated_energy_joules, 6),
        "energy_per_successful_task_joules": round(
            estimated_energy_joules / successful_task_count,
            6,
        ),
        "energy_estimation_method": (
            "mean same-GPU ROCm power samples within benchmark window multiplied "
            "by benchmark wall duration"
        ),
    }


def _vram_capacity_summary(
    monitor_text: str,
    *,
    gpu_indices: set[int] | None = None,
) -> dict[str, Any]:
    devices: dict[int, dict[str, list[float]]] = {}
    for raw_line in monitor_text.splitlines():
        index_match = GPU_INDEX_RE.search(raw_line)
        if index_match is None:
            continue
        gpu_index = int(index_match.group(1))
        values = devices.setdefault(gpu_index, {"used": [], "total": []})
        folded = raw_line.casefold()
        if any(marker in folded for marker in VRAM_USED_MARKERS):
            values["used"].extend(_reported_metric_values(raw_line, VRAM_USED_MARKERS))
        if any(marker in folded for marker in VRAM_TOTAL_MARKERS):
            values["total"].extend(
                _reported_metric_values(raw_line, VRAM_TOTAL_MARKERS)
            )

    peak_used_by_gpu: dict[str, float] = {}
    total_by_gpu: dict[str, float] = {}
    utilization_by_gpu: dict[str, float] = {}
    for gpu_index, values in sorted(devices.items()):
        if gpu_indices is not None and gpu_index not in gpu_indices:
            continue
        if not values["used"] or not values["total"]:
            continue
        total = max(values["total"])
        peak_used = max(values["used"])
        if total <= 0 or peak_used < 0 or peak_used > total:
            continue
        key = str(gpu_index)
        peak_used_by_gpu[key] = round(peak_used, 3)
        total_by_gpu[key] = round(total, 3)
        utilization_by_gpu[key] = round(peak_used / total * 100, 6)
    return {
        "vram_capacity_evidence_available": bool(utilization_by_gpu),
        "peak_vram_used_reported_by_gpu": peak_used_by_gpu,
        "vram_total_reported_by_gpu": total_by_gpu,
        "peak_vram_utilization_percent_by_gpu": utilization_by_gpu,
        "peak_vram_utilization_percent": (
            max(utilization_by_gpu.values()) if utilization_by_gpu else None
        ),
    }


def _monitor_device_unique_ids(monitor_text: str) -> tuple[dict[int, str], set[int]]:
    identities: dict[int, str] = {}
    invalid_indices: set[int] = set()
    inside_identity = False
    saw_begin = False
    saw_end = False
    for raw_line in monitor_text.splitlines():
        if raw_line == DEVICE_IDENTITY_BEGIN:
            if saw_begin or inside_identity:
                raise ValueError("monitor contains duplicate device identity blocks")
            saw_begin = True
            inside_identity = True
            continue
        if raw_line == DEVICE_IDENTITY_END:
            if not inside_identity or saw_end:
                raise ValueError("monitor contains a malformed device identity block")
            saw_end = True
            inside_identity = False
            continue
        if not inside_identity or DEVICE_UNIQUE_ID_MARKER not in raw_line.casefold():
            continue
        index_match = GPU_INDEX_RE.search(raw_line)
        # rocm-smi prints a decorative "Unique ID" section heading without a
        # device index before the per-GPU rows.
        if index_match is None:
            continue
        identity_match = GPU_UNIQUE_ID_RE.fullmatch(raw_line)
        if identity_match is None:
            invalid_index = int(index_match.group(1))
            invalid_indices.add(invalid_index)
            identities.pop(invalid_index, None)
            continue
        gpu_index = int(identity_match.group(1))
        unique_id = identity_match.group(2).casefold()
        if int(unique_id, 16) == 0:
            invalid_indices.add(gpu_index)
            identities.pop(gpu_index, None)
            continue
        if gpu_index in invalid_indices:
            continue
        if gpu_index in identities and identities[gpu_index] != unique_id:
            invalid_indices.add(gpu_index)
            identities.pop(gpu_index, None)
            continue
        identities[gpu_index] = unique_id
    if inside_identity or saw_begin != saw_end:
        raise ValueError("monitor contains an incomplete device identity block")
    if len(set(identities.values())) != len(identities):
        raise ValueError("monitor maps multiple GPU indices to one unique ID")
    return identities, invalid_indices


def runtime_gpu_summary(
    server_path: Path,
    monitor_path: Path,
    label: str,
    *,
    required_windows: dict[str, tuple[datetime, datetime]] | None = None,
    expected_run_id: str | None = None,
    expected_sample_count: int | None = None,
    maximum_sample_gap_seconds: float | None = None,
    coverage_window: tuple[datetime, datetime] | None = None,
    declared_monitor_window: tuple[datetime, datetime] | None = None,
    require_device_identity: bool = False,
    successful_task_count: int | None = None,
    energy_window: tuple[datetime, datetime] | None = None,
) -> dict[str, Any]:
    server_text = server_path.read_text(encoding="utf-8", errors="replace")
    monitor_text = monitor_path.read_text(encoding="utf-8", errors="replace")
    fatal_server_lines = [
        line[:500]
        for line in server_text.splitlines()
        if FATAL_SERVER_RE.search(line)
    ]
    if fatal_server_lines:
        raise ValueError(f"{label} server log contains an OOM/fatal/crash marker")
    if GPU_BACKEND_RE.search(server_text) is None:
        raise ValueError(f"{label} server log has no ROCm/HIP Radeon backend marker")

    complete_offload = any(
        int(match.group(1))
        == int(match.group(2))
        == EXPECTED_OFFLOADED_MODEL_LAYERS
        for match in GPU_OFFLOAD_RE.finditer(server_text)
    )
    if not complete_offload:
        raise ValueError(
            f"{label} server log does not prove the pinned model's "
            f"{EXPECTED_OFFLOADED_MODEL_LAYERS}/"
            f"{EXPECTED_OFFLOADED_MODEL_LAYERS} layers were GPU-offloaded"
        )

    gpu_use = _reported_metric_values(monitor_text, GPU_USE_MARKERS)
    vram_used = _reported_metric_values(monitor_text, VRAM_USED_MARKERS)
    if not gpu_use or max(gpu_use) <= 0:
        raise ValueError(f"{label} monitor has no positive Radeon GPU-use observation")
    if not vram_used or max(vram_used) <= 0:
        raise ValueError(f"{label} monitor has no positive VRAM-use observation")
    samples = _monitor_sample_summaries(monitor_text)
    device_unique_ids, invalid_device_identity_indices = _monitor_device_unique_ids(
        monitor_text
    )
    if require_device_identity and not required_windows and not device_unique_ids:
        raise ValueError(f"{label} monitor has no Radeon GPU unique-ID evidence")
    if any(
        value is not None
        for value in (
            expected_run_id,
            expected_sample_count,
            maximum_sample_gap_seconds,
            coverage_window,
            declared_monitor_window,
        )
    ) and not samples:
        raise ValueError(f"{label} monitor has no timestamped telemetry samples")
    if samples:
        sequences = [sample["sequence"] for sample in samples]
        if sequences != list(range(1, len(samples) + 1)):
            raise ValueError(f"{label} monitor sample sequence is not contiguous")
        if expected_run_id is not None and any(
            sample["run_id"] != expected_run_id for sample in samples
        ):
            raise ValueError(f"{label} monitor sample has the wrong run-id")
        if expected_sample_count is not None and len(samples) != expected_sample_count:
            raise ValueError(f"{label} monitor sample count is inconsistent")
        sample_times = [sample["collected_at"] for sample in samples]
        for previous, current in zip(sample_times[:-1], sample_times[1:], strict=True):
            if current < previous:
                raise ValueError(f"{label} monitor sample timestamps are not monotonic")
            if (
                maximum_sample_gap_seconds is not None
                and (current - previous).total_seconds() > maximum_sample_gap_seconds
            ):
                raise ValueError(f"{label} monitor contains an excessive sampling gap")
        first_sample_at = sample_times[0]
        last_sample_at = sample_times[-1]
        if declared_monitor_window is not None and not (
            declared_monitor_window[0]
            <= first_sample_at
            <= last_sample_at
            <= declared_monitor_window[1]
        ):
            raise ValueError(f"{label} samples exceed the declared monitor window")
        if coverage_window is not None and not (
            first_sample_at <= coverage_window[0]
            and coverage_window[1] <= last_sample_at
        ):
            raise ValueError(f"{label} monitor samples do not cover evaluation windows")
    window_hits: dict[str, int] = {}
    window_gpu_indices: dict[str, set[int]] = {}
    window_sample_sequences: dict[str, set[int]] = {}
    window_gpu_sample_sequences: dict[str, dict[int, set[int]]] = {}
    common_window_gpu_indices: set[int] = set()
    if required_windows:
        if not samples:
            raise ValueError(f"{label} monitor has no timestamped telemetry samples")
        for window_name, (window_start, window_end) in required_windows.items():
            if window_start >= window_end:
                raise ValueError(f"{label} {window_name} window must have positive duration")
            active_sequences = {
                sample["sequence"]
                for sample in samples
                if window_start <= sample["collected_at"] <= window_end
                and bool(sample["active_gpu_indices"])
            }
            if not active_sequences:
                raise ValueError(
                    f"{label} monitor has no active GPU/VRAM sample in {window_name} window"
                )
            window_hits[window_name] = len(active_sequences)
            window_sample_sequences[window_name] = active_sequences
            gpu_sequences: dict[int, set[int]] = {}
            for sample in samples:
                if not window_start <= sample["collected_at"] <= window_end:
                    continue
                for gpu_index in sample["active_gpu_indices"]:
                    gpu_sequences.setdefault(gpu_index, set()).add(sample["sequence"])
            window_gpu_sample_sequences[window_name] = gpu_sequences
            window_gpu_indices[window_name] = set(gpu_sequences)
        common_window_gpu_indices = set.intersection(*window_gpu_indices.values())
        if not common_window_gpu_indices:
            raise ValueError(
                f"{label} evaluation windows do not share an active GPU index"
            )
        window_names = list(window_gpu_sample_sequences)
        independently_observed_gpu_indices: set[int] = set()
        for gpu_index in common_window_gpu_indices:
            independently_observed = True
            for index, left_name in enumerate(window_names):
                left_sequences = window_gpu_sample_sequences[left_name][gpu_index]
                for right_name in window_names[index + 1 :]:
                    right_sequences = window_gpu_sample_sequences[right_name][gpu_index]
                    if not (left_sequences - right_sequences) or not (
                        right_sequences - left_sequences
                    ):
                        independently_observed = False
                        break
                if not independently_observed:
                    break
            if independently_observed:
                independently_observed_gpu_indices.add(gpu_index)
        common_window_gpu_indices = independently_observed_gpu_indices
        if not common_window_gpu_indices:
            raise ValueError(
                f"{label} evaluation windows require distinct active telemetry "
                "samples on one shared GPU"
            )
    missing_identity_indices = sorted(
        gpu_index
        for gpu_index in common_window_gpu_indices
        if gpu_index not in device_unique_ids
    )
    if require_device_identity and missing_identity_indices:
        invalid_active_indices = sorted(
            set(missing_identity_indices) & invalid_device_identity_indices
        )
        if invalid_active_indices:
            raise ValueError(
                f"{label} active GPU indices have invalid Radeon GPU unique ID "
                f"evidence: {invalid_active_indices}"
            )
        raise ValueError(
            f"{label} active GPU indices lack unique-ID evidence: "
            f"{missing_identity_indices}"
        )
    common_window_gpu_unique_ids = sorted(
        {
            device_unique_ids[gpu_index]
            for gpu_index in common_window_gpu_indices
            if gpu_index in device_unique_ids
        }
    )
    active_sample_gpu_indices = {
        gpu_index
        for sample in samples
        for gpu_index in sample["active_gpu_indices"]
    }
    vram_gpu_indices = common_window_gpu_indices or active_sample_gpu_indices
    benchmark_window = energy_window or (
        required_windows.get("agent_benchmark") if required_windows else None
    )
    return {
        "gpu_use_observations": len(gpu_use),
        "peak_gpu_use_percent": round(max(gpu_use), 3),
        "vram_use_observations": len(vram_used),
        "peak_vram_used_reported": round(max(vram_used), 3),
        "model_layer_offload_observed": True,
        "rocm_or_hip_backend_observed": True,
        "active_gpu_indices": sorted(
            {
                gpu_index
                for sample in samples
                for gpu_index in sample["active_gpu_indices"]
            }
        ),
        "active_window_sample_counts": window_hits,
        "active_window_gpu_indices": {
            window_name: sorted(indices)
            for window_name, indices in window_gpu_indices.items()
        },
        "active_window_sample_sequences": {
            window_name: sorted(sequences)
            for window_name, sequences in window_sample_sequences.items()
        },
        "active_window_gpu_sample_sequences": {
            window_name: {
                str(gpu_index): sorted(sequences)
                for gpu_index, sequences in sorted(gpu_sequences.items())
            }
            for window_name, gpu_sequences in window_gpu_sample_sequences.items()
        },
        "common_active_gpu_indices": sorted(common_window_gpu_indices),
        "device_unique_ids": {
            str(gpu_index): unique_id
            for gpu_index, unique_id in sorted(device_unique_ids.items())
        },
        "invalid_device_identity_indices": sorted(invalid_device_identity_indices),
        "common_active_gpu_unique_ids": common_window_gpu_unique_ids,
        "first_sample_at_utc": (
            samples[0]["collected_at"].isoformat() if samples else None
        ),
        "last_sample_at_utc": (
            samples[-1]["collected_at"].isoformat() if samples else None
        ),
        **_vram_capacity_summary(
            monitor_text,
            gpu_indices=vram_gpu_indices or None,
        ),
        **_energy_summary(
            samples,
            benchmark_window=benchmark_window,
            gpu_indices=common_window_gpu_indices,
            successful_task_count=successful_task_count,
        ),
    }


def load_key_value_evidence(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if "=" not in raw_line:
            continue
        key, value = raw_line.split("=", 1)
        if key and key not in values:
            values[key] = value
    return values


def load_server_configuration(path: Path) -> dict[str, str]:
    configuration: dict[str, str] = {
        "gpu_layers": "999",
        "cache_type_k": "f16",
        "cache_type_v": "f16",
        "log_verbosity": "5",
    }
    allowed = {
        "ctx",
        "parallel",
        "batch",
        "ubatch",
        "flash_attn",
        "gpu_layers",
        "cache_type_k",
        "cache_type_v",
        "log_verbosity",
    }
    for raw_line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        for item in raw_line.split():
            if "=" not in item:
                continue
            key, value = item.split("=", 1)
            if key == "n_gpu_layers":
                key = "gpu_layers"
            if key in allowed:
                configuration[key] = value
    required = {"ctx", "parallel", "batch", "ubatch", "flash_attn"}
    if not required.issubset(configuration):
        missing = sorted(required - set(configuration))
        raise ValueError(f"Server evidence is missing launch settings: {missing}")
    return configuration


def validate_bundle(
    binding_path: Path, binding: dict[str, str], label: str
) -> dict[str, Any]:
    resolved_binding = binding_path.expanduser().resolve()
    bundle_dir = resolved_binding.parent
    if resolved_binding != bundle_dir / "binding-manifest.txt":
        raise ValueError(f"{label} binding must be the bundle binding-manifest.txt")
    checksum_path = bundle_dir / "SHA256SUMS.txt"
    if not checksum_path.is_file():
        raise FileNotFoundError(f"{label} bundle is missing SHA256SUMS.txt")
    checksums = load_checksum_manifest(checksum_path, label)
    for name in BUNDLE_CHECKSUM_FILES:
        artifact = bundle_dir / name
        if not artifact.is_file():
            raise FileNotFoundError(f"{label} bundle is missing {name}")
        actual = file_sha256(artifact)
        if checksums.get(name) != actual:
            raise ValueError(f"{label} bundle checksum mismatch: {name}")

    context_file_field = next(
        (field for field in CONTEXT_BINDING_FILES if field in binding),
        None,
    )
    if context_file_field is not None:
        context_name = binding[context_file_field]
        context_path = bundle_dir / context_name
        if not context_path.is_file():
            raise FileNotFoundError(f"{label} bundle is missing {context_name}")
        context_sha256 = file_sha256(context_path)
        context_hash_field = CONTEXT_BINDING_HASH_FIELDS[context_file_field]
        if binding[context_hash_field] != context_sha256:
            raise ValueError(f"{label} binding hash mismatch: {context_hash_field}")
        if checksums.get(context_name) != context_sha256:
            raise ValueError(f"{label} bundle checksum mismatch: {context_name}")

    for file_field, hash_field in BINDING_HASH_FIELDS.items():
        artifact = bundle_dir / binding[file_field]
        if file_sha256(artifact) != binding[hash_field]:
            raise ValueError(f"{label} binding hash mismatch: {hash_field}")

    identity_payload = "".join(
        f"{digest}\n"
        for digest in (
            stable_system_sha256(bundle_dir / "system.txt"),
            file_sha256(bundle_dir / "rocminfo.txt"),
            file_sha256(bundle_dir / "rocm-version.txt"),
        )
    ).encode("ascii")
    identity_hash = hashlib.sha256(identity_payload).hexdigest()
    if identity_hash != binding["hardware_identity_sha256"]:
        raise ValueError(f"{label} hardware identity hash does not match raw files")

    retrieval = load_json_object(bundle_dir / binding["retrieval_file"], f"{label} retrieval")
    quality = load_json_object(bundle_dir / binding["quality_file"], f"{label} quality")
    stress = load_json_object(bundle_dir / binding["stress_file"], f"{label} stress")
    benchmark = load_json_object(bundle_dir / binding["benchmark_file"], f"{label} benchmark")
    runtime_instance = load_runtime_instance(
        bundle_dir / binding["runtime_instance_file"],
        expected_run_id=binding["run_id"],
        expected_sha256=binding["runtime_instance_sha256"],
    )
    if runtime_instance.payload["model_sha256"] != binding["model_sha256"]:
        raise ValueError(
            f"{label} runtime-instance model SHA256 differs from the binding"
        )
    if (
        runtime_instance.payload["executable_sha256"]
        != binding["llama_server_sha256"]
    ):
        raise ValueError(
            f"{label} runtime-instance executable SHA256 differs from the binding"
        )
    context = (
        load_json_object(
            bundle_dir / binding[context_file_field],
            f"{label} context evidence",
        )
        if context_file_field is not None
        else None
    )
    if any(
        report.get("run_id") != binding["run_id"]
        for report in (retrieval, quality, stress, benchmark)
    ):
        raise ValueError(f"{label} bundle reports do not share the bound run-id")
    validate_retrieval_report(retrieval, f"{label} retrieval")
    validate_quality_report(quality, f"{label} quality")
    validate_stress_report(stress, label)
    if not (
        retrieval.get("suite_version")
        == quality.get("suite_version")
        == benchmark.get("suite_version")
        == OFFICIAL_SUITE_VERSION
    ):
        raise ValueError(f"{label} retrieval, quality and benchmark suite versions differ")
    if not (
        retrieval.get("suite_sha256")
        == quality.get("suite_sha256")
        == benchmark.get("suite_sha256")
        == OFFICIAL_SUITE_SHA256
    ):
        raise ValueError(
            f"{label} retrieval, quality and benchmark must use the official suite hash"
        )
    if not (
        retrieval.get("policy_corpus_sha256")
        == quality.get("policy_corpus_sha256")
        == stress.get("policy_corpus_sha256")
        == benchmark.get("policy_corpus_sha256")
    ) or not SHA256_RE.fullmatch(
        str(retrieval.get("policy_corpus_sha256", ""))
    ):
        raise ValueError(f"{label} policy corpus hashes differ or are invalid")
    quality_request_configuration = validate_request_configuration(
        quality, f"{label} quality"
    )
    benchmark_request_configuration = validate_request_configuration(
        benchmark, f"{label} benchmark"
    )
    if quality_request_configuration != benchmark_request_configuration:
        raise ValueError(
            f"{label} quality and benchmark request configurations differ"
        )
    if stress.get("request_configuration") != quality.get("request_configuration"):
        raise ValueError(f"{label} stress and quality request configurations differ")
    quality_has_service_configuration = "service_configuration" in quality
    benchmark_has_service_configuration = "service_configuration" in benchmark
    if quality_has_service_configuration != benchmark_has_service_configuration:
        raise ValueError(
            f"{label} quality and benchmark must both bind service configuration"
        )
    if quality_has_service_configuration:
        quality_service_configuration = normalized_report_service_configuration(
            quality,
            f"{label} quality service_configuration",
        )
        benchmark_service_configuration = normalized_report_service_configuration(
            benchmark,
            f"{label} benchmark service_configuration",
        )
        if quality_service_configuration != benchmark_service_configuration:
            raise ValueError(
                f"{label} quality and benchmark service configurations differ"
            )
        stress_service_configuration = normalized_report_service_configuration(
            stress,
            f"{label} stress service_configuration",
        )
        if stress_service_configuration != quality_service_configuration:
            raise ValueError(
                f"{label} stress and quality service configurations differ"
            )
        expected_service_configuration_sha256 = service_configuration_sha256(
            benchmark_service_configuration,
            f"{label} benchmark service_configuration",
        )
        if runtime_instance.payload.get("service_configuration_sha256") != (
            expected_service_configuration_sha256
        ):
            raise ValueError(
                f"{label} runtime-instance service configuration differs from "
                "the bound benchmark"
            )
        launch_configuration = load_server_configuration(
            bundle_dir / binding["server_log"]
        )
        if not service_configuration_matches_log(
            benchmark_service_configuration,
            launch_configuration,
        ):
            raise ValueError(
                f"{label} benchmark service configuration does not match server evidence"
            )
    quality_experiment = (
        quality.get("service_configuration", {}).get("experiment")
        if isinstance(quality.get("service_configuration"), dict)
        else None
    )
    expected_context_file_field = {
        "E": "context_selection_file",
        "F": "context_proof_file",
    }.get(quality_experiment)
    if context_file_field != expected_context_file_field:
        raise ValueError(
            f"{label} context artifact binding does not match experiment "
            f"{quality_experiment}"
        )
    context_summary = validate_context_evidence(
        context,
        quality,
        benchmark,
        label,
        quality_sha256=binding["quality_sha256"],
        benchmark_sha256=binding["benchmark_sha256"],
    )
    quality_evidence = validate_request_configuration_evidence(
        quality,
        f"{label} quality",
    )
    stress_evidence = validate_request_configuration_evidence(
        stress,
        f"{label} stress",
    )
    benchmark_evidence = validate_request_configuration_evidence(
        benchmark,
        f"{label} benchmark",
    )
    for report_name, report, report_kind in (
        ("quality", quality, "quality"),
        ("stress", stress, "quality"),
        ("benchmark", benchmark, "benchmark"),
    ):
        validate_report_runtime_binding(
            report,
            expected_manifest_sha256=runtime_instance.manifest_sha256,
            report_kind=report_kind,
            label=f"{label} {report_name}",
        )
    fused_plan_evidence = quality_request_configuration["fused_plan_evidence"]
    quality_profile = _call_efficiency_profile(
        _quality_call_groups(quality),
        fused=fused_plan_evidence,
        label=f"{label}.quality",
    )
    benchmark_profile = _call_efficiency_profile(
        _benchmark_call_groups(benchmark),
        fused=fused_plan_evidence,
        label=f"{label}.benchmark",
    )
    stress_profile = _call_efficiency_profile(
        _quality_call_groups(stress),
        fused=fused_plan_evidence,
        label=f"{label}.stress",
    )
    if quality_profile["status"] != "available":
        raise ValueError(f"{label} quality has no raw model-call evidence")
    if benchmark_profile["status"] != "available":
        raise ValueError(f"{label} benchmark has no raw model-call evidence")
    if stress_profile["status"] != "available":
        raise ValueError(f"{label} stress has no raw model-call evidence")
    if fused_plan_evidence:
        _validate_call_profile_against_evidence(
            quality_profile,
            quality_evidence,
            f"{label} quality",
        )
        _validate_call_profile_against_evidence(
            benchmark_profile,
            benchmark_evidence,
            f"{label} benchmark",
        )
        _validate_call_profile_against_evidence(
            stress_profile,
            stress_evidence,
            f"{label} stress",
        )
    expected_provenance = {
        "commit": binding["commit"],
        "project_tree": binding["project_tree"],
        "source_tree_sha256": binding["source_tree_sha256"],
    }
    for report_name, report in (
        ("retrieval", retrieval),
        ("quality", quality),
        ("stress", stress),
        ("benchmark", benchmark),
    ):
        provenance = report.get("provenance")
        if not isinstance(provenance, dict):
            raise ValueError(f"{label} {report_name} provenance is missing")
        for field, expected_value in expected_provenance.items():
            if provenance.get(field) != expected_value:
                raise ValueError(f"{label} {report_name} provenance mismatch: {field}")
    if benchmark.get("quality_report", {}).get("sha256") != binding["quality_sha256"]:
        raise ValueError(f"{label} benchmark is not bound to the bundled quality report")
    if benchmark.get("quality_report", {}).get("total_score") != quality.get(
        "metrics", {}
    ).get("total_score"):
        raise ValueError(f"{label} benchmark quality score does not match raw quality evidence")
    for report_name, report in (
        ("quality", quality),
        ("stress", stress),
        ("benchmark", benchmark),
    ):
        artifacts = report.get("artifacts") or {}
        if artifacts.get("model_file_sha256") != binding["model_sha256"]:
            raise ValueError(f"{label} {report_name} model hash mismatch")
        if artifacts.get("llama_server_sha256") != binding["llama_server_sha256"]:
            raise ValueError(f"{label} {report_name} llama-server hash mismatch")

    monitor = load_key_value_evidence(bundle_dir / binding["monitor_file"])
    server = load_key_value_evidence(bundle_dir / binding["server_log"])
    runtime_port = runtime_instance.port
    runtime_endpoints = {
        f"http://127.0.0.1:{runtime_port}/v1",
        f"http://localhost:{runtime_port}/v1",
        f"http://[::1]:{runtime_port}/v1",
    }
    if server.get("model_alias") != runtime_instance.payload["model_alias"]:
        raise ValueError(
            f"{label} runtime-instance model alias differs from server evidence"
        )
    if server.get("model_base_url") not in runtime_endpoints:
        raise ValueError(
            f"{label} runtime-instance port differs from server evidence"
        )
    if (
        monitor.get("run_id") != binding["run_id"]
        or monitor.get("status") != "complete"
        or monitor.get("schema_version") != "1"
    ):
        raise ValueError(f"{label} monitor evidence is incomplete")
    if (
        server.get("evidence_run_id") != binding["run_id"]
        or server.get("evidence_log_status") != "complete"
        or server.get("llama_server_exit_code") not in {"0", "143"}
        or server.get("runtime_instance_manifest_sha256")
        != runtime_instance.manifest_sha256
        or server.get("process_binding_valid") != "true"
        or server.get("listen_socket_binding_valid") != "true"
        or server.get("service_configuration_sha256")
        != runtime_instance.payload.get("service_configuration_sha256")
    ):
        raise ValueError(f"{label} server evidence is incomplete")
    if server.get("model_sha256_at_start") != binding["model_sha256"]:
        raise ValueError(f"{label} server startup model hash mismatch")
    if server.get("llama_server_sha256_at_start") != binding["llama_server_sha256"]:
        raise ValueError(f"{label} server startup binary hash mismatch")
    try:
        monitor_interval = float(monitor["interval_seconds"])
        completed_samples = int(monitor["completed_samples"])
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError(f"{label} monitor has invalid sample metadata") from exc
    if not math.isfinite(monitor_interval) or not 0 < monitor_interval <= 5:
        raise ValueError(f"{label} monitor interval must be at most 5 seconds")
    if completed_samples < 2:
        raise ValueError(f"{label} monitor must contain at least two samples")
    retrieval_window = (
        _parse_utc_instant(retrieval.get("started_at_utc"), f"{label} retrieval start"),
        _parse_utc_instant(retrieval.get("completed_at_utc"), f"{label} retrieval end"),
    )
    quality_window = (
        _parse_utc_instant(quality.get("started_at_utc"), f"{label} quality start"),
        _parse_utc_instant(quality.get("completed_at_utc"), f"{label} quality end"),
    )
    stress_window = (
        _parse_utc_instant(stress.get("started_at_utc"), f"{label} stress start"),
        _parse_utc_instant(stress.get("completed_at_utc"), f"{label} stress end"),
    )
    benchmark_window = (
        _parse_utc_instant(benchmark.get("started_at_utc"), f"{label} benchmark start"),
        _parse_utc_instant(benchmark.get("completed_at_utc"), f"{label} benchmark end"),
    )
    measurement_window = benchmark_window
    if benchmark.get("measurement_started_at_utc") is not None or benchmark.get(
        "measurement_completed_at_utc"
    ) is not None:
        measurement_window = (
            _parse_utc_instant(
                benchmark.get("measurement_started_at_utc"),
                f"{label} benchmark measurement start",
            ),
            _parse_utc_instant(
                benchmark.get("measurement_completed_at_utc"),
                f"{label} benchmark measurement end",
            ),
        )
        if not (
            benchmark_window[0]
            <= measurement_window[0]
            < measurement_window[1]
            <= benchmark_window[1]
        ):
            raise ValueError(
                f"{label} benchmark measurement window is outside the benchmark"
            )
    server_window = (
        _parse_utc_instant(server.get("server_started_at_utc"), f"{label} server start"),
        _parse_utc_instant(server.get("server_completed_at_utc"), f"{label} server end"),
    )
    monitor_window = (
        _parse_utc_instant(monitor.get("started_at_utc"), f"{label} monitor start"),
        _parse_utc_instant(monitor.get("completed_at_utc"), f"{label} monitor end"),
    )
    if not (
        server_window[0]
        <= retrieval_window[0]
        <= retrieval_window[1]
        <= quality_window[0]
        <= quality_window[1]
        <= stress_window[0]
        <= stress_window[1]
        <= benchmark_window[0]
        <= benchmark_window[1]
        <= server_window[1]
    ):
        raise ValueError(f"{label} server does not cover ordered evaluation windows")
    quality_model = quality.get("model")
    if not isinstance(quality_model, dict):
        raise ValueError(f"{label} quality report has invalid model metadata")
    expected_model_alias = quality_model.get("name")
    expected_model_base_url = quality_model.get("base_url")
    if not isinstance(expected_model_alias, str) or not expected_model_alias:
        raise ValueError(f"{label} quality report has no model alias")
    if not isinstance(expected_model_base_url, str) or not expected_model_base_url:
        raise ValueError(f"{label} quality report has no model endpoint")
    if not (
        server.get("model_alias")
        == benchmark.get("model_name")
        == expected_model_alias
    ):
        raise ValueError(f"{label} server and evaluation model aliases differ")
    if not (
        server.get("model_base_url")
        == benchmark.get("model_base_url")
        == expected_model_base_url
    ):
        raise ValueError(f"{label} server and evaluation model endpoints differ")
    runtime_summary = runtime_gpu_summary(
        bundle_dir / binding["server_log"],
        bundle_dir / binding["monitor_file"],
        label,
        required_windows={
            "agent_quality": quality_window,
            "stress": stress_window,
            "agent_benchmark": benchmark_window,
        },
        expected_run_id=binding["run_id"],
        expected_sample_count=completed_samples,
        maximum_sample_gap_seconds=max(5.0, monitor_interval * 3.0),
        coverage_window=(retrieval_window[0], benchmark_window[1]),
        declared_monitor_window=monitor_window,
        require_device_identity=True,
        successful_task_count=sum(
            int(run["summary"]["successful"])
            for run in benchmark["runs"]
        ),
        energy_window=measurement_window,
    )
    runtime_summary["context_evidence"] = context_summary
    return runtime_summary


def validate_binding(
    report: dict[str, Any],
    report_path: Path,
    binding_path: Path,
    binding: dict[str, str],
    label: str,
) -> dict[str, Any]:
    runtime_summary = validate_bundle(binding_path, binding, label)
    expected = {
        "run_id": report["run_id"],
        "benchmark_sha256": file_sha256(report_path),
        "quality_sha256": str(report["quality_report"].get("sha256")),
        "model_sha256": str(report["artifacts"].get("model_file_sha256")),
        "llama_server_sha256": str(report["artifacts"].get("llama_server_sha256")),
        "commit": str(report["provenance"].get("commit")),
        "project_tree": str(report["provenance"].get("project_tree")),
        "source_tree_sha256": str(report["provenance"].get("source_tree_sha256")),
    }
    for field, value in expected.items():
        if binding.get(field) != value:
            raise ValueError(f"{label} binding mismatch: {field}")
    bundled_report = report_path.parent / binding["benchmark_file"]
    if report_path.expanduser().resolve() != bundled_report.resolve():
        raise ValueError(f"{label} benchmark must be read from its complete evidence bundle")
    return runtime_summary


def require_integer(value: Any, field: str, *, minimum: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise ValueError(f"{field} must be an integer >= {minimum}")
    return value


def percentile(values: list[float], quantile: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = max(0, math.ceil(len(ordered) * quantile) - 1)
    return round(ordered[index], 3)


def require_close(actual: Any, expected: float, field: str, *, tolerance: float) -> None:
    number = require_number(actual, field)
    if not math.isclose(number, expected, rel_tol=0.0, abs_tol=tolerance):
        raise ValueError(f"{field} is inconsistent with raw request evidence")


def validate_official_report(payload: dict[str, Any], label: str) -> None:
    if payload.get("suite_version") != OFFICIAL_SUITE_VERSION:
        raise ValueError(f"{label} report has an unexpected suite version")
    if payload.get("suite_sha256") != OFFICIAL_SUITE_SHA256:
        raise ValueError(f"{label} report is not bound to the official suite")
    if tuple(payload.get("case_ids") or ()) != OFFICIAL_CASE_IDS:
        raise ValueError(f"{label} report has unexpected official benchmark case IDs")
    request_configuration = validate_request_configuration(payload, label)
    request_configuration_evidence = validate_request_configuration_evidence(
        payload,
        label,
    )
    if request_configuration["schema_constrained"] is not True:
        raise ValueError(f"{label} report must use schema-constrained model requests")

    configuration = payload["configuration"]
    repetitions = require_integer(
        configuration.get("repetitions"),
        f"{label}.configuration.repetitions",
        minimum=MIN_OFFICIAL_REPETITIONS,
    )
    require_integer(
        configuration.get("warmup"),
        f"{label}.configuration.warmup",
        minimum=MIN_OFFICIAL_WARMUP,
    )
    if tuple(configuration.get("concurrency") or ()) != OFFICIAL_CONCURRENCY:
        raise ValueError(f"{label} report must contain concurrency 1,2,4")
    if configuration.get("min_success_rate") != 1.0:
        raise ValueError(f"{label} report must require 100% request success")
    citation_threshold = require_number(
        configuration.get("min_citation_hit_rate"),
        f"{label}.configuration.min_citation_hit_rate",
    )
    if citation_threshold != 1.0:
        raise ValueError(f"{label} report must require a 100% citation hit rate")

    expected_case_ids = list(OFFICIAL_CASE_IDS) * repetitions
    if payload.get("request_case_ids") != expected_case_ids:
        raise ValueError(f"{label} request_case_ids do not match repetitions")
    raw_runs = payload.get("runs")
    if not isinstance(raw_runs, list) or len(raw_runs) != len(OFFICIAL_CONCURRENCY):
        raise ValueError(f"{label} report must contain exactly three concurrency runs")
    if tuple(run.get("concurrency") for run in raw_runs if isinstance(run, dict)) != (
        OFFICIAL_CONCURRENCY
    ):
        raise ValueError(f"{label} raw run order must be concurrency 1,2,4")

    request_ids: set[str] = set()
    for run in raw_runs:
        concurrency = run["concurrency"]
        requests = run.get("requests")
        if not isinstance(requests, list) or len(requests) != len(expected_case_ids):
            raise ValueError(f"{label} concurrency {concurrency} has an invalid workload size")
        if [row.get("case_id") for row in requests if isinstance(row, dict)] != expected_case_ids:
            raise ValueError(f"{label} concurrency {concurrency} workload order is invalid")

        successful: list[dict[str, Any]] = []
        latencies: list[float] = []
        model_calls: list[dict[str, Any]] = []
        recovered_syntax_repair_failures = 0
        citation_hits = 0
        for index, row in enumerate(requests):
            if not isinstance(row, dict) or type(row.get("ok")) is not bool:
                raise ValueError(f"{label} concurrency {concurrency} request {index} is invalid")
            request_id = row.get("request_id")
            if not isinstance(request_id, str) or not request_id or request_id in request_ids:
                raise ValueError(f"{label} contains a missing or duplicate request_id")
            request_ids.add(request_id)
            wall_ms = require_number(
                row.get("wall_ms"),
                f"{label}.c{concurrency}.requests[{index}].wall_ms",
            )
            if not row["ok"]:
                continue
            if type(row.get("citation_hit")) is not bool:
                raise ValueError(f"{label} request {request_id} has invalid citation_hit")
            backend = row.get("model_backend")
            calls = row.get("model_calls")
            if not isinstance(calls, list):
                raise ValueError(f"{label} request {request_id} has invalid model-call evidence")
            if not all(isinstance(call, dict) for call in calls):
                raise ValueError(f"{label} request {request_id} has invalid model-call evidence")
            zero_call_allowed = server_gate_zero_call_allowed(row)
            if not calls and not zero_call_allowed:
                raise ValueError(
                    f"{label} request {request_id} has no model-call evidence "
                    "or verified server privacy gate"
                )
            if calls and (
                not isinstance(backend, str)
                or "llama.cpp-rocm" not in backend
                or "deterministic-development" in backend
            ):
                raise ValueError(
                    f"{label} request {request_id} did not use the ROCm model path"
                )
            if request_configuration["fused_plan_evidence"] and calls:
                _validate_fused_model_calls(
                    calls,
                    f"{label} request {request_id}",
                )
            if any(
                call.get("thinking_enabled")
                != request_configuration["thinking_enabled"]
                for call in calls
            ):
                raise ValueError(
                    f"{label} request {request_id} has inconsistent thinking configuration"
                )
            if any(
                type(call.get("schema_constrained")) is not bool
                or call["schema_constrained"]
                != request_configuration["schema_constrained"]
                for call in calls
            ):
                raise ValueError(
                    f"{label} request {request_id} has inconsistent schema configuration"
                )
            if request_configuration["schema_constrained"] and any(
                call.get("response_format") != "json_schema" for call in calls
            ):
                raise ValueError(
                    f"{label} request {request_id} was not schema constrained"
                )
            successful.append(row)
            latencies.append(wall_ms)
            citation_hits += int(row["citation_hit"])
            model_calls.extend(calls)
            recovered_syntax_repair_failures += (
                _recovered_syntax_repair_failure_count(calls)
            )

        summary = run.get("summary")
        if not isinstance(summary, dict):
            raise ValueError(f"{label} concurrency {concurrency} is missing summary")
        successful_count = len(successful)
        success_rate = successful_count / len(requests)
        citation_rate = citation_hits / successful_count if successful_count else 0.0
        if summary.get("requests") != len(requests):
            raise ValueError(f"{label} concurrency {concurrency} request count mismatch")
        if summary.get("successful") != successful_count:
            raise ValueError(f"{label} concurrency {concurrency} success count mismatch")
        require_close(
            summary.get("success_rate"),
            round(success_rate, 6),
            f"{label}.c{concurrency}.success_rate",
            tolerance=1e-6,
        )
        require_close(
            summary.get("citation_hit_rate"),
            round(citation_rate, 6),
            f"{label}.c{concurrency}.citation_hit_rate",
            tolerance=1e-6,
        )
        latency = summary.get("latency_ms")
        if not isinstance(latency, dict):
            raise ValueError(f"{label} concurrency {concurrency} is missing latency_ms")
        for field, expected in (
            ("p50", percentile(latencies, 0.50)),
            ("p95", percentile(latencies, 0.95)),
            ("min", round(min(latencies), 3) if latencies else 0.0),
            ("max", round(max(latencies), 3) if latencies else 0.0),
        ):
            require_close(
                latency.get(field),
                expected,
                f"{label}.c{concurrency}.latency_ms.{field}",
                tolerance=1e-3,
            )

        successful_calls = [call for call in model_calls if call.get("ok") is True]
        failed_calls = [call for call in model_calls if call.get("ok") is not True]
        unrecovered_failed_calls = (
            len(failed_calls) - recovered_syntax_repair_failures
        )
        effective_rates = [
            require_number(
                call.get("effective_output_tokens_per_second"),
                f"{label}.c{concurrency}.model_call.effective_rate",
            )
            for call in successful_calls
        ]
        server_decode_rates = [
            require_number(
                call["server_decode_tokens_per_second"],
                f"{label}.c{concurrency}.model_call.server_decode_rate",
            )
            for call in successful_calls
            if call.get("server_decode_tokens_per_second") is not None
        ]
        ttft_values = [
            require_number(
                call["ttft_ms"],
                f"{label}.c{concurrency}.model_call.ttft_ms",
            )
            for call in successful_calls
            if call.get("ttft_ms") is not None
        ]
        if any(rate <= 0 for rate in effective_rates):
            raise ValueError(f"{label} concurrency {concurrency} has a non-positive token rate")
        model_metrics = summary.get("model_call_metrics")
        if not isinstance(model_metrics, dict):
            raise ValueError(f"{label} concurrency {concurrency} has no model_call_metrics")
        expected_counts = {
            "calls": len(model_calls),
            "successful_calls": len(successful_calls),
            "failed_calls": len(failed_calls),
            "recovered_syntax_repair_failures": (
                recovered_syntax_repair_failures
            ),
            "unrecovered_failed_calls": unrecovered_failed_calls,
            "effective_rate_sample_count": len(effective_rates),
        }
        for field, expected in expected_counts.items():
            if model_metrics.get(field) != expected:
                raise ValueError(f"{label} concurrency {concurrency} {field} mismatch")
        require_close(
            model_metrics.get("effective_rate_coverage"),
            1.0 if successful_calls else 0.0,
            f"{label}.c{concurrency}.effective_rate_coverage",
            tolerance=1e-6,
        )
        for field, expected in (
            ("effective_output_tokens_per_second_p50", percentile(effective_rates, 0.50)),
            ("effective_output_tokens_per_second_p95", percentile(effective_rates, 0.95)),
        ):
            require_close(
                model_metrics.get(field),
                expected,
                f"{label}.c{concurrency}.{field}",
                tolerance=1e-3,
            )
        for count_field, coverage_field, values, metric_fields in (
            (
                "server_decode_rate_sample_count",
                "server_decode_rate_coverage",
                server_decode_rates,
                (
                    "server_decode_tokens_per_second_p50",
                    "server_decode_tokens_per_second_p95",
                ),
            ),
            (
                "ttft_sample_count",
                "ttft_coverage",
                ttft_values,
                ("ttft_ms_p50", "ttft_ms_p95"),
            ),
        ):
            if model_metrics.get(count_field) != len(values):
                raise ValueError(f"{label} concurrency {concurrency} {count_field} mismatch")
            expected_coverage = (
                round(len(values) / len(successful_calls), 6)
                if successful_calls
                else 0.0
            )
            require_close(
                model_metrics.get(coverage_field),
                expected_coverage,
                f"{label}.c{concurrency}.{coverage_field}",
                tolerance=1e-6,
            )
            expected_values = (
                (percentile(values, 0.50), percentile(values, 0.95))
                if values
                else (None, None)
            )
            for metric_field, expected in zip(
                metric_fields, expected_values, strict=True
            ):
                observed = model_metrics.get(metric_field)
                if expected is None:
                    if observed is not None:
                        raise ValueError(
                            f"{label} concurrency {concurrency} has {metric_field} without samples"
                        )
                else:
                    require_close(
                        observed,
                        expected,
                        f"{label}.c{concurrency}.{metric_field}",
                        tolerance=1e-3,
                    )

        wall_seconds = require_number(
            summary.get("wall_seconds"), f"{label}.c{concurrency}.wall_seconds"
        )
        if wall_seconds <= 0:
            raise ValueError(f"{label} concurrency {concurrency} has invalid wall_seconds")
        require_close(
            summary.get("offered_throughput_requests_per_second"),
            round(len(requests) / wall_seconds, 6),
            f"{label}.c{concurrency}.offered_throughput",
            tolerance=1e-6,
        )
        require_close(
            summary.get("successful_throughput_requests_per_second"),
            round(successful_count / wall_seconds, 6),
            f"{label}.c{concurrency}.successful_throughput",
            tolerance=1e-6,
        )
        if (
            success_rate < 1.0
            or citation_rate < citation_threshold
            or unrecovered_failed_calls != 0
        ):
            raise ValueError(
                f"{label} concurrency {concurrency} fails the official quality gate"
            )

    call_profile = _call_efficiency_profile(
        _benchmark_call_groups(payload),
        fused=request_configuration["fused_plan_evidence"],
        label=label,
    )
    if call_profile["status"] != "available":
        raise ValueError(f"{label} report has no raw model-call evidence")
    _validate_call_profile_against_evidence(
        call_profile,
        request_configuration_evidence,
        label,
    )

    quality_gate = payload["quality_gate"]
    if quality_gate.get("failures") != []:
        raise ValueError(f"{label} report claims pass but contains gate failures")
    expected_thresholds = {
        "min_success_rate": configuration["min_success_rate"],
        "min_citation_hit_rate": configuration["min_citation_hit_rate"],
    }
    if quality_gate.get("thresholds") != expected_thresholds:
        raise ValueError(f"{label} quality thresholds do not match configuration")


def load_report(path: Path, label: str) -> dict[str, Any]:
    resolved = path.expanduser().resolve()
    try:
        payload = json.loads(resolved.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid JSON in {label} report: {resolved}") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"{label} report must contain one JSON object")
    if payload.get("schema_version") != SCHEMA_VERSION:
        raise ValueError(f"{label} report must use schema_version {SCHEMA_VERSION}")
    run_id = payload.get("run_id")
    if not isinstance(run_id, str) or not run_id:
        raise ValueError(f"{label} report is missing run_id")
    quality_gate = payload.get("quality_gate")
    if not isinstance(quality_gate, dict) or quality_gate.get("passed") is not True:
        raise ValueError(f"{label} report quality_gate must be passed")
    if not isinstance(payload.get("model_name"), str) or not payload["model_name"]:
        raise ValueError(f"{label} report is missing model_name")
    if not isinstance(payload.get("cases_path"), str) or not payload["cases_path"]:
        raise ValueError(f"{label} report is missing cases_path")
    if not isinstance(payload.get("suite_sha256"), str) or not payload["suite_sha256"]:
        raise ValueError(f"{label} report is missing suite_sha256")
    if not SHA256_RE.fullmatch(str(payload.get("policy_corpus_sha256", ""))):
        raise ValueError(f"{label} report has an invalid policy_corpus_sha256")
    if not isinstance(payload.get("case_ids"), list) or not payload["case_ids"]:
        raise ValueError(f"{label} report is missing case_ids")
    if not isinstance(payload.get("request_case_ids"), list) or not payload["request_case_ids"]:
        raise ValueError(f"{label} report is missing request_case_ids")
    validate_request_configuration(payload, label)
    normalized_report_service_configuration(
        payload,
        f"{label}.service_configuration",
    )
    for field in ("configuration", "provenance", "artifacts", "quality_report"):
        if not isinstance(payload.get(field), dict):
            raise ValueError(f"{label} report is missing {field}")
    if payload["quality_report"].get("passed") is not True:
        raise ValueError(f"{label} report is not bound to a passing quality report")
    if payload["quality_report"].get("total_score") != 300:
        raise ValueError(f"{label} report is not bound to 300/300 quality")
    validate_official_report(payload, label)
    return payload


def indexed_runs(report: dict[str, Any], label: str) -> dict[int, dict[str, Any]]:
    raw_runs = report.get("runs")
    if not isinstance(raw_runs, list) or not raw_runs:
        raise ValueError(f"{label} report must contain at least one run")
    result: dict[int, dict[str, Any]] = {}
    for index, run in enumerate(raw_runs):
        if not isinstance(run, dict):
            raise ValueError(f"{label} runs[{index}] must be an object")
        concurrency = run.get("concurrency")
        if isinstance(concurrency, bool) or not isinstance(concurrency, int) or concurrency < 1:
            raise ValueError(f"{label} runs[{index}].concurrency must be a positive integer")
        if concurrency in result:
            raise ValueError(f"{label} report repeats concurrency {concurrency}")
        summary = run.get("summary")
        if not isinstance(summary, dict):
            raise ValueError(f"{label} concurrency {concurrency} is missing summary")
        latency = summary.get("latency_ms")
        if not isinstance(latency, dict):
            raise ValueError(f"{label} concurrency {concurrency} is missing latency_ms")
        require_number(latency.get("p50"), f"{label}.c{concurrency}.latency_ms.p50")
        require_number(latency.get("p95"), f"{label}.c{concurrency}.latency_ms.p95")
        require_number(
            summary.get("successful_throughput_requests_per_second"),
            f"{label}.c{concurrency}.successful_throughput_requests_per_second",
        )
        result[concurrency] = run
    return result


def token_rates(
    run: dict[str, Any],
    label: str,
    concurrency: int,
) -> dict[str, float]:
    summary = run["summary"]
    model_call_metrics = summary.get("model_call_metrics")
    if not isinstance(model_call_metrics, dict):
        raise ValueError(
            f"{label} concurrency {concurrency} model_call_metrics must be an object"
        )
    sample_count = model_call_metrics.get("effective_rate_sample_count")
    if isinstance(sample_count, bool) or not isinstance(sample_count, int) or sample_count < 1:
        raise ValueError(
            f"{label} concurrency {concurrency} has no effective token-rate samples"
        )
    present = [field for field in TOKEN_RATE_FIELDS if field in model_call_metrics]
    if len(present) != len(TOKEN_RATE_FIELDS):
        missing = sorted(set(TOKEN_RATE_FIELDS) - set(present))
        raise ValueError(
            f"{label} concurrency {concurrency} is missing token-rate fields: {missing}"
        )
    return {
        field: require_number(
            model_call_metrics[field],
            f"{label}.c{concurrency}.model_call_metrics.{field}",
        )
        for field in TOKEN_RATE_FIELDS
    }


def optional_metrics(
    run: dict[str, Any],
    label: str,
    concurrency: int,
    count_field: str,
    fields: tuple[str, ...],
) -> dict[str, float] | None:
    model_metrics = run["summary"].get("model_call_metrics")
    if not isinstance(model_metrics, dict):
        raise ValueError(f"{label} concurrency {concurrency} has no model_call_metrics")
    sample_count = model_metrics.get(count_field)
    if isinstance(sample_count, bool) or not isinstance(sample_count, int) or sample_count < 0:
        raise ValueError(f"{label} concurrency {concurrency} has invalid {count_field}")
    if sample_count == 0:
        if any(model_metrics.get(field) is not None for field in fields):
            raise ValueError(f"{label} concurrency {concurrency} has metrics without samples")
        return None
    return {
        field: require_number(
            model_metrics.get(field),
            f"{label}.c{concurrency}.model_call_metrics.{field}",
        )
        for field in fields
    }


def compare_metric(
    baseline: float,
    optimized: float,
    *,
    lower_is_better: bool,
    material_threshold_percent: float,
) -> dict[str, Any]:
    absolute_delta = optimized - baseline
    if baseline == 0:
        improvement_percent: float | None = None
    elif lower_is_better:
        improvement_percent = ((baseline - optimized) / baseline) * 100
    else:
        improvement_percent = ((optimized - baseline) / baseline) * 100
    rounded_improvement = (
        round(improvement_percent, 3) if improvement_percent is not None else None
    )
    return {
        "baseline": round(baseline, 6),
        "optimized": round(optimized, 6),
        "absolute_delta_optimized_minus_baseline": round(absolute_delta, 6),
        "improvement_percent": rounded_improvement,
        "direction": "lower_is_better" if lower_is_better else "higher_is_better",
        "material_improvement": bool(
            improvement_percent is not None
            and improvement_percent >= material_threshold_percent
        ),
        "material_regression": bool(
            improvement_percent is not None
            and improvement_percent <= -material_threshold_percent
        ),
    }


def validate_pair(
    baseline: dict[str, Any],
    optimized: dict[str, Any],
) -> tuple[dict[int, dict[str, Any]], dict[int, dict[str, Any]]]:
    if baseline["run_id"] == optimized["run_id"]:
        raise ValueError("Baseline and optimized reports must use different run_id values")
    if baseline["model_name"] != optimized["model_name"]:
        raise ValueError("Baseline and optimized reports must use the same model_name")
    if baseline.get("model_base_url") != optimized.get("model_base_url"):
        raise ValueError("Baseline and optimized reports must use the same model endpoint")
    if baseline["policy_corpus_sha256"] != optimized["policy_corpus_sha256"]:
        raise ValueError("Baseline and optimized reports must use the same policy corpus")
    for field in ("commit", "project_tree", "source_tree_sha256"):
        if baseline["provenance"].get(field) != optimized["provenance"].get(field):
            raise ValueError(f"Baseline and optimized provenance must match {field}")
    for field in (
        "suite_version",
        "suite_sha256",
        "case_ids",
        "request_case_ids",
        "configuration",
    ):
        if baseline[field] != optimized[field]:
            raise ValueError(f"Baseline and optimized reports must match {field}")
    baseline_request_configuration = validate_request_configuration(
        baseline, "baseline"
    )
    optimized_request_configuration = validate_request_configuration(
        optimized, "optimized"
    )
    baseline_service_configuration = normalized_report_service_configuration(
        baseline,
        "baseline.service_configuration",
    )
    optimized_service_configuration = normalized_report_service_configuration(
        optimized,
        "optimized.service_configuration",
    )
    changed_groups = changed_tunable_groups(
        baseline_request_configuration,
        optimized_request_configuration,
        baseline_service_configuration,
        optimized_service_configuration,
    )
    if len(changed_groups) > 1:
        raise ValueError(
            "Baseline and optimized reports must differ by at most one tunable "
            f"configuration group; changed={changed_groups}"
        )
    for field in ("model_file_sha256", "llama_server_sha256"):
        if baseline["artifacts"].get(field) != optimized["artifacts"].get(field):
            raise ValueError(f"Baseline and optimized artifacts must match {field}")
    for report, label in ((baseline, "baseline"), (optimized, "optimized")):
        require_number(
            report["quality_report"].get("total_score"),
            f"{label}.quality_report.total_score",
        )
    baseline_thresholds = baseline["quality_gate"].get("thresholds")
    optimized_thresholds = optimized["quality_gate"].get("thresholds")
    if baseline_thresholds != optimized_thresholds:
        raise ValueError("Baseline and optimized reports must use the same quality thresholds")
    baseline_runs = indexed_runs(baseline, "baseline")
    optimized_runs = indexed_runs(optimized, "optimized")
    if set(baseline_runs) != set(optimized_runs):
        raise ValueError("Baseline and optimized reports must contain the same concurrency levels")
    for concurrency in baseline_runs:
        baseline_requests = baseline_runs[concurrency].get("requests")
        optimized_requests = optimized_runs[concurrency].get("requests")
        if not isinstance(baseline_requests, list) or not isinstance(optimized_requests, list):
            raise ValueError(f"Concurrency {concurrency} is missing raw request rows")
        baseline_case_ids = [row.get("case_id") for row in baseline_requests]
        optimized_case_ids = [row.get("case_id") for row in optimized_requests]
        if baseline_case_ids != optimized_case_ids:
            raise ValueError(f"Concurrency {concurrency} request workloads do not match")
        baseline_summary = baseline_runs[concurrency]["summary"]
        optimized_summary = optimized_runs[concurrency]["summary"]
        baseline_model_metrics = baseline_summary["model_call_metrics"]
        optimized_model_metrics = optimized_summary["model_call_metrics"]
        for metric in ("success_rate", "citation_hit_rate"):
            require_number(
                baseline_summary.get(metric), f"baseline.c{concurrency}.{metric}"
            )
            require_number(
                optimized_summary.get(metric), f"optimized.c{concurrency}.{metric}"
            )
        if not (
            baseline_request_configuration["fused_plan_evidence"]
            or optimized_request_configuration["fused_plan_evidence"]
        ):
            for count_field in (
                "successful_calls",
                "effective_rate_sample_count",
                "server_decode_rate_sample_count",
                "ttft_sample_count",
            ):
                if baseline_model_metrics.get(
                    count_field
                ) != optimized_model_metrics.get(count_field):
                    raise ValueError(
                        f"Baseline and optimized {count_field} differ at concurrency "
                        f"{concurrency}"
                    )
    return baseline_runs, optimized_runs


def _vram_gate(
    runtime_summary: dict[str, Any] | None,
    *,
    maximum_vram_percent: float,
) -> dict[str, Any]:
    if runtime_summary is None:
        return {
            "evaluated": False,
            "passed": None,
            "peak_percent": None,
            "required_strictly_below_percent": maximum_vram_percent,
            "reason": "runtime GPU summary was not supplied",
        }
    peak_value = runtime_summary.get("peak_vram_utilization_percent")
    if peak_value is None:
        return {
            "evaluated": True,
            "passed": False,
            "peak_percent": None,
            "required_strictly_below_percent": maximum_vram_percent,
            "reason": "ROCm monitor did not expose paired used/total VRAM evidence",
        }
    peak_percent = require_number(peak_value, "peak_vram_utilization_percent")
    return {
        "evaluated": True,
        "passed": peak_percent < maximum_vram_percent,
        "peak_percent": round(peak_percent, 6),
        "required_strictly_below_percent": maximum_vram_percent,
        "reason": None,
    }


def _report_call_efficiency(payload: dict[str, Any], label: str) -> dict[str, Any]:
    groups = _benchmark_call_groups(payload)
    if not groups:
        return {
            "status": "unavailable",
            "reason": "raw benchmark requests do not contain model-call evidence",
        }
    configuration = validate_request_configuration(payload, label)
    return _call_efficiency_profile(
        groups,
        fused=configuration["fused_plan_evidence"],
        label=label,
    )


def _energy_comparison(
    baseline_runtime_gpu: dict[str, Any] | None,
    optimized_runtime_gpu: dict[str, Any] | None,
    *,
    material_threshold_percent: float,
) -> dict[str, Any]:
    baseline_value = (
        baseline_runtime_gpu.get("energy_per_successful_task_joules")
        if baseline_runtime_gpu is not None
        else None
    )
    optimized_value = (
        optimized_runtime_gpu.get("energy_per_successful_task_joules")
        if optimized_runtime_gpu is not None
        else None
    )
    if baseline_value is None or optimized_value is None:
        return {
            "status": "unavailable",
            "baseline_joules": baseline_value,
            "optimized_joules": optimized_value,
            "reason": "both runs need same-window ROCm power samples",
        }
    return {
        "status": "available",
        **compare_metric(
            require_number(baseline_value, "baseline energy per successful task"),
            require_number(optimized_value, "optimized energy per successful task"),
            lower_is_better=True,
            material_threshold_percent=material_threshold_percent,
        ),
    }


def _call_efficiency_comparison(
    baseline: dict[str, Any],
    optimized: dict[str, Any],
    *,
    material_threshold_percent: float,
) -> dict[str, Any]:
    if baseline.get("status") != "available" or optimized.get("status") != "available":
        return {
            "status": "unavailable",
            "reason": "both reports need raw model-call evidence",
        }
    return {
        "status": "available",
        "single_call_response_rate": compare_metric(
            float(baseline["single_call_response_rate"]),
            float(optimized["single_call_response_rate"]),
            lower_is_better=False,
            material_threshold_percent=material_threshold_percent,
        ),
        "repair_response_rate": compare_metric(
            float(baseline["repair_response_rate"]),
            float(optimized["repair_response_rate"]),
            lower_is_better=True,
            material_threshold_percent=material_threshold_percent,
        ),
    }


def build_comparison(
    baseline: dict[str, Any],
    optimized: dict[str, Any],
    *,
    material_threshold_percent: float,
    baseline_runtime_gpu: dict[str, Any] | None = None,
    optimized_runtime_gpu: dict[str, Any] | None = None,
    maximum_vram_percent: float = 90.0,
) -> dict[str, Any]:
    material_threshold_percent, maximum_vram_percent = (
        validate_formal_acceptance_limits(
            material_threshold_percent,
            maximum_vram_percent,
        )
    )
    baseline_runs, optimized_runs = validate_pair(baseline, optimized)
    baseline_request_configuration = validate_request_configuration(
        baseline,
        "baseline",
    )
    optimized_request_configuration = validate_request_configuration(
        optimized,
        "optimized",
    )
    baseline_service_configuration = normalized_report_service_configuration(
        baseline,
        "baseline.service_configuration",
    )
    optimized_service_configuration = normalized_report_service_configuration(
        optimized,
        "optimized.service_configuration",
    )
    configuration_changes = changed_tunable_groups(
        baseline_request_configuration,
        optimized_request_configuration,
        baseline_service_configuration,
        optimized_service_configuration,
    )
    service_configuration_bound = (
        "service_configuration" in baseline and "service_configuration" in optimized
    )
    single_variable_verified = len(configuration_changes) == 1
    single_variable_gate = (
        single_variable_verified if service_configuration_bound else True
    )
    baseline_vram_gate = _vram_gate(
        baseline_runtime_gpu,
        maximum_vram_percent=maximum_vram_percent,
    )
    optimized_vram_gate = _vram_gate(
        optimized_runtime_gpu,
        maximum_vram_percent=maximum_vram_percent,
    )
    baseline_call_efficiency = _report_call_efficiency(baseline, "baseline")
    optimized_call_efficiency = _report_call_efficiency(optimized, "optimized")
    call_efficiency_comparison = _call_efficiency_comparison(
        baseline_call_efficiency,
        optimized_call_efficiency,
        material_threshold_percent=material_threshold_percent,
    )
    energy_comparison = _energy_comparison(
        baseline_runtime_gpu,
        optimized_runtime_gpu,
        material_threshold_percent=material_threshold_percent,
    )
    comparisons: list[dict[str, Any]] = []
    materially_improved: list[str] = []
    materially_improved_core: list[str] = []
    materially_regressed: list[str] = []
    materially_regressed_core: list[str] = []
    quality_regressions: list[dict[str, Any]] = []
    optional_timing_complete = {"server_decode": True, "ttft": True}
    baseline_quality_score = require_number(
        baseline["quality_report"].get("total_score"),
        "baseline.quality_report.total_score",
    )
    optimized_quality_score = require_number(
        optimized["quality_report"].get("total_score"),
        "optimized.quality_report.total_score",
    )
    if optimized_quality_score < baseline_quality_score:
        quality_regressions.append(
            {
                "metric": "quality_report.total_score",
                "baseline": baseline_quality_score,
                "optimized": optimized_quality_score,
            }
        )

    for concurrency in sorted(baseline_runs):
        baseline_run = baseline_runs[concurrency]
        optimized_run = optimized_runs[concurrency]
        baseline_summary = baseline_run["summary"]
        optimized_summary = optimized_run["summary"]
        for quality_metric in ("success_rate", "citation_hit_rate"):
            baseline_quality_value = require_number(
                baseline_summary.get(quality_metric),
                f"baseline.c{concurrency}.{quality_metric}",
            )
            optimized_quality_value = require_number(
                optimized_summary.get(quality_metric),
                f"optimized.c{concurrency}.{quality_metric}",
            )
            if optimized_quality_value < baseline_quality_value:
                quality_regressions.append(
                    {
                        "metric": f"c{concurrency}.{quality_metric}",
                        "baseline": baseline_quality_value,
                        "optimized": optimized_quality_value,
                    }
                )
        metrics = {
            "latency_p50_ms": compare_metric(
                require_number(
                    baseline_summary["latency_ms"]["p50"],
                    f"baseline.c{concurrency}.latency_ms.p50",
                ),
                require_number(
                    optimized_summary["latency_ms"]["p50"],
                    f"optimized.c{concurrency}.latency_ms.p50",
                ),
                lower_is_better=True,
                material_threshold_percent=material_threshold_percent,
            ),
            "latency_p95_ms": compare_metric(
                require_number(
                    baseline_summary["latency_ms"]["p95"],
                    f"baseline.c{concurrency}.latency_ms.p95",
                ),
                require_number(
                    optimized_summary["latency_ms"]["p95"],
                    f"optimized.c{concurrency}.latency_ms.p95",
                ),
                lower_is_better=True,
                material_threshold_percent=material_threshold_percent,
            ),
            "successful_throughput_requests_per_second": compare_metric(
                require_number(
                    baseline_summary["successful_throughput_requests_per_second"],
                    f"baseline.c{concurrency}.successful_throughput",
                ),
                require_number(
                    optimized_summary["successful_throughput_requests_per_second"],
                    f"optimized.c{concurrency}.successful_throughput",
                ),
                lower_is_better=False,
                material_threshold_percent=material_threshold_percent,
            ),
        }
        baseline_tokens = token_rates(baseline_run, "baseline", concurrency)
        optimized_tokens = token_rates(optimized_run, "optimized", concurrency)
        for field in TOKEN_RATE_FIELDS:
            metrics[field] = compare_metric(
                baseline_tokens[field],
                optimized_tokens[field],
                lower_is_better=False,
                material_threshold_percent=material_threshold_percent,
            )
        for count_field, fields, lower_is_better in OPTIONAL_METRIC_GROUPS:
            baseline_optional = optional_metrics(
                baseline_run,
                "baseline",
                concurrency,
                count_field,
                fields,
            )
            optimized_optional = optional_metrics(
                optimized_run,
                "optimized",
                concurrency,
                count_field,
                fields,
            )
            if (baseline_optional is None) != (optimized_optional is None):
                raise ValueError(
                    f"Optional timing evidence differs at concurrency {concurrency}: "
                    f"{count_field}"
                )
            for field in fields:
                if baseline_optional is None:
                    group_name = (
                        "server_decode"
                        if count_field == "server_decode_rate_sample_count"
                        else "ttft"
                    )
                    optional_timing_complete[group_name] = False
                    metrics[field] = {
                        "status": "unavailable",
                        "reason": "pinned local model response did not expose this timing",
                    }
                else:
                    assert optimized_optional is not None
                    metrics[field] = compare_metric(
                        baseline_optional[field],
                        optimized_optional[field],
                        lower_is_better=lower_is_better,
                        material_threshold_percent=material_threshold_percent,
                    )

        for metric_name, result in metrics.items():
            if result.get("material_improvement"):
                qualified_name = f"c{concurrency}.{metric_name}"
                materially_improved.append(qualified_name)
                if metric_name in CORE_METRIC_NAMES:
                    materially_improved_core.append(qualified_name)
            if result.get("material_regression"):
                qualified_name = f"c{concurrency}.{metric_name}"
                materially_regressed.append(qualified_name)
                if metric_name in CORE_METRIC_NAMES:
                    materially_regressed_core.append(qualified_name)
        comparisons.append({"concurrency": concurrency, "metrics": metrics})

    core_evidence_complete = True
    full_timing_evidence_complete = all(optional_timing_complete.values())
    core_material_improvement_observed = bool(materially_improved_core)
    quality_not_regressed = not quality_regressions
    optimized_vram_required = optimized_runtime_gpu is not None
    optimized_vram_ok = (
        optimized_vram_gate["passed"] is True if optimized_vram_required else True
    )
    accepted = bool(
        core_evidence_complete
        and core_material_improvement_observed
        and not materially_regressed_core
        and quality_not_regressed
        and optimized_vram_ok
        and single_variable_gate
    )
    rejection_reasons: list[str] = []
    if not core_material_improvement_observed:
        rejection_reasons.append("no_core_metric_met_material_threshold")
    if materially_regressed_core:
        rejection_reasons.append("core_material_regression_observed")
    if not quality_not_regressed:
        rejection_reasons.append("quality_regression_observed")
    if optimized_vram_required and optimized_vram_gate["passed"] is not True:
        rejection_reasons.append("optimized_peak_vram_not_strictly_below_limit")
    if not single_variable_gate:
        rejection_reasons.append("configuration_change_not_single_variable")
    baseline_eligible = (
        baseline_vram_gate["passed"] is True
        if baseline_runtime_gpu is not None
        else True
    )
    optimization_winner = "optimized" if accepted else "not_accepted"
    recommended_configuration = "optimized" if accepted else (
        "baseline" if baseline_eligible else "none"
    )
    status = "accepted" if accepted else "not_accepted"

    return {
        "schema_version": 1,
        "comparison": "radeonstay-baseline-vs-optimized",
        "created_at_utc": datetime.now(UTC).isoformat(timespec="seconds"),
        "baseline": {
            "run_id": baseline["run_id"],
            "model_name": baseline["model_name"],
            "cases_path": baseline["cases_path"],
            "suite_sha256": baseline["suite_sha256"],
            "source_tree_sha256": baseline["provenance"].get("source_tree_sha256"),
            "quality_report_sha256": baseline["quality_report"].get("sha256"),
        },
        "optimized": {
            "run_id": optimized["run_id"],
            "model_name": optimized["model_name"],
            "cases_path": optimized["cases_path"],
            "suite_sha256": optimized["suite_sha256"],
            "source_tree_sha256": optimized["provenance"].get("source_tree_sha256"),
            "quality_report_sha256": optimized["quality_report"].get("sha256"),
        },
        "matched_artifacts": {
            "policy_corpus_sha256": baseline["policy_corpus_sha256"],
            "model_file_sha256": baseline["artifacts"].get("model_file_sha256"),
            "llama_server_sha256": baseline["artifacts"].get("llama_server_sha256"),
        },
        "request_configuration": {
            "baseline": baseline_request_configuration,
            "optimized": optimized_request_configuration,
        },
        "service_configuration": {
            "baseline": baseline_service_configuration,
            "optimized": optimized_service_configuration,
        },
        "configuration_change": {
            "single_variable_verified": single_variable_verified,
            "required": service_configuration_bound,
            "changed_groups": configuration_changes,
        },
        "quality_thresholds": baseline["quality_gate"].get("thresholds"),
        "material_threshold_percent": material_threshold_percent,
        "vram_gate": {
            "baseline": baseline_vram_gate,
            "optimized": optimized_vram_gate,
        },
        "model_call_efficiency": {
            "baseline": baseline_call_efficiency,
            "optimized": optimized_call_efficiency,
            "comparison": call_efficiency_comparison,
        },
        "energy_per_successful_task": energy_comparison,
        "comparisons": comparisons,
        "assessment": {
            "status": status,
            "accepted": accepted,
            "optimization_winner": optimization_winner,
            "recommended_configuration": recommended_configuration,
            "winner_rule": (
                "Promote optimized only for one bound tuning-factor change when "
                "quality does not regress, at least one core metric improves by the "
                "material threshold, no core metric regresses by that threshold, and "
                "peak VRAM is strictly below the configured limit; otherwise retain "
                "an eligible baseline."
            ),
            "acceptance_criteria": {
                "minimum_core_improvement_percent": material_threshold_percent,
                "at_least_one_core_metric_improved": (
                    core_material_improvement_observed
                ),
                "no_material_core_metric_regression": not materially_regressed_core,
                "quality_not_regressed": quality_not_regressed,
                "exactly_one_tunable_group_changed": (
                    single_variable_verified
                    if service_configuration_bound
                    else "not_required_for_legacy_report"
                ),
                "optimized_peak_vram_strictly_below_limit": (
                    optimized_vram_gate["passed"]
                    if optimized_vram_required
                    else "not_evaluated_in_legacy_direct_call"
                ),
            },
            "rejection_reasons": rejection_reasons,
            "core_evidence_complete": core_evidence_complete,
            "full_timing_evidence_complete": full_timing_evidence_complete,
            "optional_timing_evidence": optional_timing_complete,
            "missing_effective_token_rate_concurrency": [],
            "materially_improved_metrics": materially_improved,
            "materially_improved_core_metrics": materially_improved_core,
            "materially_regressed_metrics": materially_regressed,
            "materially_regressed_core_metrics": materially_regressed_core,
            "material_improvement_observed": core_material_improvement_observed,
            "quality_regressions": quality_regressions,
            "note": (
                "Acceptance requires a material core improvement, no material core "
                "metric regression, no quality regression, and a sub-limit VRAM peak "
                "across bound evidence."
            ),
        },
    }


def comparison_exit_code(report: dict[str, Any], *, require_accepted: bool) -> int:
    accepted = report.get("assessment", {}).get("accepted")
    if type(accepted) is not bool:
        raise ValueError("Comparison report is missing assessment.accepted")
    return 1 if require_accepted and not accepted else 0


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    threshold, maximum_vram_percent = validate_formal_acceptance_limits(
        args.material_threshold_percent,
        args.maximum_vram_percent,
    )
    baseline_path = args.baseline.expanduser().resolve()
    optimized_path = args.optimized.expanduser().resolve()
    baseline_binding_path = args.baseline_binding.expanduser().resolve()
    optimized_binding_path = args.optimized_binding.expanduser().resolve()
    if baseline_path == optimized_path:
        raise ValueError("Baseline and optimized paths must be different")
    output_path = args.output.expanduser().resolve()
    if not output_path.parent.is_dir():
        raise FileNotFoundError(f"Output parent does not exist: {output_path.parent}")

    baseline = load_report(baseline_path, "baseline")
    optimized = load_report(optimized_path, "optimized")
    baseline_binding = load_binding(baseline_binding_path, "baseline")
    optimized_binding = load_binding(optimized_binding_path, "optimized")
    baseline_runtime_summary = validate_binding(
        baseline,
        baseline_path,
        baseline_binding_path,
        baseline_binding,
        "baseline",
    )
    optimized_runtime_summary = validate_binding(
        optimized,
        optimized_path,
        optimized_binding_path,
        optimized_binding,
        "optimized",
    )
    validate_context_transition(
        baseline,
        optimized,
        baseline_runtime_summary,
        optimized_runtime_summary,
    )
    for field in (
        "model_repository",
        "model_revision",
        "model_quantization",
        "llama_cpp_commit",
    ):
        if baseline_binding.get(field) != optimized_binding.get(field):
            raise ValueError(
                f"Baseline and optimized evidence must match binding field {field}"
            )
    if (
        baseline_binding.get("hardware_identity_sha256")
        != optimized_binding.get("hardware_identity_sha256")
    ):
        raise ValueError("Baseline and optimized evidence must use the same hardware identity")
    if (
        baseline_runtime_summary.get("common_active_gpu_indices")
        != optimized_runtime_summary.get("common_active_gpu_indices")
    ):
        raise ValueError("Baseline and optimized evidence must use the same active GPU indices")
    if (
        baseline_runtime_summary.get("common_active_gpu_unique_ids")
        != optimized_runtime_summary.get("common_active_gpu_unique_ids")
    ):
        raise ValueError("Baseline and optimized evidence must use the same physical GPUs")
    baseline_server_configuration = load_server_configuration(
        baseline_binding_path.parent / baseline_binding["server_log"]
    )
    optimized_server_configuration = load_server_configuration(
        optimized_binding_path.parent / optimized_binding["server_log"]
    )
    report = build_comparison(
        baseline,
        optimized,
        material_threshold_percent=threshold,
        baseline_runtime_gpu=baseline_runtime_summary,
        optimized_runtime_gpu=optimized_runtime_summary,
        maximum_vram_percent=maximum_vram_percent,
    )
    report["evidence_binding"] = {
        "baseline_manifest": str(baseline_binding_path),
        "optimized_manifest": str(optimized_binding_path),
        "hardware_identity_sha256": baseline_binding.get("hardware_identity_sha256"),
        "baseline_server_configuration": baseline_server_configuration,
        "optimized_server_configuration": optimized_server_configuration,
        "baseline_runtime_gpu_evidence": baseline_runtime_summary,
        "optimized_runtime_gpu_evidence": optimized_runtime_summary,
    }
    rendered = json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    with output_path.open("x", encoding="utf-8") as handle:
        handle.write(rendered)
    print(
        json.dumps(
            {
                "output": str(output_path),
                "assessment": report["assessment"]["status"],
                "accepted": report["assessment"]["accepted"],
                "optimization_winner": report["assessment"]["optimization_winner"],
            }
        )
    )
    return comparison_exit_code(report, require_accepted=args.require_accepted)


if __name__ == "__main__":
    raise SystemExit(main())
