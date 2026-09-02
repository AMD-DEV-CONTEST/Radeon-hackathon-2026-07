#!/usr/bin/env python3
"""Build a privacy-safe aggregate from private Technology 20 case checkpoints."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


SCHEMA_VERSION = "signalforge/technology20-evaluation-summary/v2"
STANDALONE_SAFE_GATES = (
    "runtime_passed",
    "required_sections_passed",
    "claim_authority_passed",
    "both_critics_approved",
    "required_receipts_passed",
    "expected_abstentions_passed",
    "visible_limitations",
    "contract_passed",
)
PEER_SAFE_GATES = (
    "runtime_passed",
    "required_sections_passed",
    "claim_authority_passed",
    "both_critics_approved",
    "metric_authority_passed",
    "unavailable_metrics_withheld",
    "visible_comparison_boundary",
    "no_unsupported_pair_ranking",
    "contract_passed",
)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def percentile(values: list[float], probability: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = max(0, math.ceil(probability * len(ordered)) - 1)
    return round(ordered[index], 3)


def rate(passed: int, total: int) -> float:
    return round(passed / total, 6) if total else 0.0


def packet_authority_integrity(cases: dict[str, dict[str, Any]]) -> dict[str, Any]:
    packets_observed = 0
    packets_failed = 0
    missing_references: dict[str, int] = defaultdict(int)
    failures_by_company: dict[str, int] = defaultdict(int)
    for item in cases.values():
        company_id = str(item.get("company_id", "")).strip() or "peer_or_unknown"
        packets = item.get("report", {}).get("result", {}).get("packets", [])
        if not isinstance(packets, list):
            continue
        for packet in packets:
            if not isinstance(packet, dict):
                continue
            packets_observed += 1
            receipts = {
                str(receipt.get("receipt_id", "")).strip()
                for receipt in packet.get("calculation_receipts", [])
                if isinstance(receipt, dict)
            }
            evidence = {
                str(reference.get("evidence_id", "")).strip()
                for reference in packet.get("evidence", [])
                if isinstance(reference, dict)
            }
            numerical = packet.get("numerical_context") or {}
            variables = {
                str(variable.get("variable_id", "")).strip()
                for variable in numerical.get("variables", [])
                if isinstance(variable, dict)
            }
            relations = {
                str(relation.get("relation_id", "")).strip()
                for relation in numerical.get("relations", [])
                if isinstance(relation, dict)
            }
            packet_failed = False
            for key in ("variables", "relations"):
                for numerical_item in numerical.get(key, []):
                    if not isinstance(numerical_item, dict):
                        continue
                    for receipt_id in numerical_item.get("receipt_refs", []):
                        if receipt_id not in receipts:
                            missing_references[
                                f"numerical_{key[:-1]}_receipt"
                            ] += 1
                            packet_failed = True
            for key in ("findings", "counterevidence"):
                for finding in packet.get(key, []):
                    if not isinstance(finding, dict):
                        continue
                    for receipt_id in finding.get("calculation_refs", []):
                        if receipt_id not in receipts:
                            missing_references["finding_receipt"] += 1
                            packet_failed = True
                    for evidence_id in finding.get("evidence_refs", []):
                        if evidence_id not in evidence:
                            missing_references["finding_evidence"] += 1
                            packet_failed = True
                    for numerical_id in finding.get("numerical_refs", []):
                        if numerical_id not in variables and numerical_id not in relations:
                            missing_references["finding_numerical"] += 1
                            packet_failed = True
            if packet_failed:
                packets_failed += 1
                failures_by_company[company_id] += 1
    return {
        "packets_observed": packets_observed,
        "packets_passed": packets_observed - packets_failed,
        "packets_failed": packets_failed,
        "pass_rate": rate(packets_observed - packets_failed, packets_observed),
        "missing_reference_counts": dict(sorted(missing_references.items())),
        "packet_failures_by_company": dict(sorted(failures_by_company.items())),
    }


def summarize(input_directory: Path, expected_cases: int) -> dict[str, Any]:
    paths = sorted(input_directory.glob("**/cases/*.json"))
    cases: dict[str, dict[str, Any]] = {}
    input_hashes: dict[str, str] = {}
    for path in paths:
        payload = json.loads(path.read_text())
        journey_id = str(payload.get("journey_id", "")).strip()
        if not journey_id:
            raise ValueError(f"{path} lacks journey_id")
        if journey_id in cases:
            raise ValueError(f"duplicate journey_id {journey_id}")
        cases[journey_id] = payload
        input_hashes[str(path.relative_to(input_directory))] = sha256_file(path)

    kinds = {
        "peer" if str(item.get("lane_id", "")).strip() else "standalone"
        for item in cases.values()
    }
    if len(kinds) > 1:
        raise ValueError("mixed standalone and peer populations are not allowed")
    evaluation_kind = next(iter(kinds), "standalone")
    safe_gates = (
        PEER_SAFE_GATES if evaluation_kind == "peer" else STANDALONE_SAFE_GATES
    )
    durations = [float(item.get("duration_ms", 0.0)) for item in cases.values()]
    call_durations_ms: list[float] = []
    call_ttft_ms: list[float] = []
    call_throughput: list[float] = []
    failed_model_calls = 0
    for item in cases.values():
        for call in item.get("report", {}).get("model_calls", []):
            duration_ns = int(call.get("duration_ns", 0))
            ttft_ns = int(call.get("ttft_ns", 0))
            completion_tokens = int(call.get("completion_tokens", 0))
            failed = bool(call.get("failed"))
            failed_model_calls += failed
            if duration_ns > 0:
                duration_seconds = duration_ns / 1_000_000_000
                call_durations_ms.append(duration_ns / 1_000_000)
                if not failed and completion_tokens > 0:
                    call_throughput.append(completion_tokens / duration_seconds)
            if ttft_ns > 0:
                call_ttft_ms.append(ttft_ns / 1_000_000)
    gates = {
        gate: sum(bool(item.get(gate)) for item in cases.values())
        for gate in safe_gates
    }
    def group_result(include_questions: bool = False) -> dict[str, Any]:
        result: dict[str, Any] = {
            "cases": 0,
            **{gate: 0 for gate in safe_gates},
        }
        if include_questions:
            result["question_ids"] = []
        return result

    by_question: dict[str, dict[str, Any]] = defaultdict(group_result)
    by_company: dict[str, dict[str, Any]] = defaultdict(
        lambda: group_result(include_questions=True)
    )
    failure_codes: dict[str, int] = defaultdict(int)
    failed_gate_counts: dict[str, int] = defaultdict(int)
    failure_signatures: dict[str, int] = defaultdict(int)
    by_lane: dict[str, dict[str, Any]] = defaultdict(group_result)
    for item in cases.values():
        question_id = str(item.get("question_id", "unknown"))
        company_id = str(item.get("company_id", "")).strip()
        by_question[question_id]["cases"] += 1
        if company_id:
            by_company[company_id]["cases"] += 1
            by_company[company_id]["question_ids"].append(question_id)
        lane_id = str(item.get("lane_id", "")).strip()
        if lane_id:
            by_lane[lane_id]["cases"] += 1
        failed_gates: list[str] = []
        for gate in safe_gates:
            passed = bool(item.get(gate))
            by_question[question_id][gate] += passed
            if company_id:
                by_company[company_id][gate] += passed
            if lane_id:
                by_lane[lane_id][gate] += passed
            if not passed:
                failed_gate_counts[gate] += 1
                failed_gates.append(gate)
        if failed_gates:
            failure_signatures["+".join(sorted(failed_gates))] += 1
        failure_code = str(item.get("failure_code", "")).strip()
        if failure_code:
            failure_codes[failure_code] += 1

    for group in (by_question, by_company, by_lane):
        for value in group.values():
            value["gate_pass_rates"] = {
                gate: rate(value[gate], value["cases"]) for gate in safe_gates
            }
            value["runtime_pass_rate"] = value["gate_pass_rates"]["runtime_passed"]
            value["contract_pass_rate"] = value["gate_pass_rates"]["contract_passed"]
            if "question_ids" in value:
                value["question_ids"] = sorted(set(value["question_ids"]))

    completed = len(cases)
    return {
        "schema_version": SCHEMA_VERSION,
        "evaluation_kind": evaluation_kind,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "expected_cases": expected_cases,
        "completed_cases": completed,
        "population_complete": completed == expected_cases,
        "gate_counts": gates,
        "runtime_pass_rate": rate(gates["runtime_passed"], completed),
        "contract_pass_rate": rate(gates["contract_passed"], completed),
        "latency_ms": {
            "p50": percentile(durations, 0.50),
            "p95": percentile(durations, 0.95),
            "maximum": round(max(durations), 3) if durations else 0.0,
        },
        "model_calls": sum(int(item.get("model_calls", 0)) for item in cases.values()),
        "model_call_performance": {
            "observed_calls": len(call_durations_ms),
            "failed_calls": failed_model_calls,
            "duration_ms": {
                "p50": percentile(call_durations_ms, 0.50),
                "p95": percentile(call_durations_ms, 0.95),
                "maximum": round(max(call_durations_ms), 3)
                if call_durations_ms
                else 0.0,
            },
            "ttft_ms": {
                "p50": percentile(call_ttft_ms, 0.50),
                "p95": percentile(call_ttft_ms, 0.95),
                "maximum": round(max(call_ttft_ms), 3) if call_ttft_ms else 0.0,
            },
            "completion_tokens_per_second_end_to_end": {
                "p50": percentile(call_throughput, 0.50),
                "p95": percentile(call_throughput, 0.95),
                "minimum": round(min(call_throughput), 3)
                if call_throughput
                else 0.0,
            },
        },
        "prompt_tokens": sum(int(item.get("prompt_tokens", 0)) for item in cases.values()),
        "completion_tokens": sum(
            int(item.get("completion_tokens", 0)) for item in cases.values()
        ),
        "failure_codes": dict(sorted(failure_codes.items())),
        "failed_gate_counts": dict(sorted(failed_gate_counts.items())),
        "failure_signatures": dict(sorted(failure_signatures.items())),
        "packet_authority_integrity": packet_authority_integrity(cases),
        "by_question": dict(sorted(by_question.items())),
        "by_company": dict(sorted(by_company.items())),
        "by_lane": dict(sorted(by_lane.items())),
        "input_case_sha256": input_hashes,
        "release_disposition": "evaluation_only_not_promoted",
        "claim_boundary": (
            "This aggregate contains contract and runtime measurements only. It excludes prompts, "
            "responses, private reports, credentials, source bodies, and hidden reasoning, and it "
            "does not replace factual, accounting, rights, or investment-domain review."
        ),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input-directory", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--expected-cases", type=int, default=80)
    parser.add_argument(
        "--require-complete",
        action="store_true",
        help="fail unless completed_cases equals expected_cases",
    )
    args = parser.parse_args()

    report = summarize(args.input_directory, args.expected_cases)
    if args.require_complete and not report["population_complete"]:
        raise SystemExit(
            f"incomplete population: {report['completed_cases']}/{report['expected_cases']}"
        )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    temporary = args.output.with_suffix(args.output.suffix + ".tmp")
    temporary.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    temporary.replace(args.output)
    print(
        f"technology20 evaluation: {report['completed_cases']}/{report['expected_cases']} "
        f"cases; contract_pass_rate={report['contract_pass_rate']:.2%}"
    )


if __name__ == "__main__":
    main()
