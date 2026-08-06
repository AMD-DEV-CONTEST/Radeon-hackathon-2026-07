"""Summarize Insurance RAG Agent evaluation results and generate a release-gate report.

The output format is JSON (not Excel), adapted to the Insurance RAG Agent project structure.
Release-gate criteria:
- min_pass_rate: 0.80 — end-to-end pass rate >= 80%
- max_fail_rate: 0.10 — fail rate <= 10%
- critical_stages_must_pass: ["retrieval", "citation", "answer"]
- min_cases_evaluated: 10
"""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Any


# ── default release-gate criteria ──
DEFAULT_GATE_CRITERIA: dict[str, Any] = {
    "min_pass_rate": 0.80,
    "max_fail_rate": 0.10,
    "critical_stages_must_pass": ["retrieval", "citation", "answer"],
    "min_cases_evaluated": 10,
}


def summarize_levels(rows: list[dict[str, Any]]) -> dict[str, int | float]:
    """Count pass, fail, unknown; unknown stays in the denominator.

    Args:
        rows: The verdict row list, each row containing a level field.

    Returns:
        A statistics dict containing total, passed, failed, unknown, pass_rate.
    """

    total = len(rows)
    counter = Counter(str(row.get("level", "unknown")) for row in rows)
    passed = counter.get("pass", 0)
    failed = counter.get("fail", 0)
    unknown = counter.get("unknown", 0)
    return {
        "total": total,
        "passed": passed,
        "failed": failed,
        "unknown": unknown,
        "pass_rate": passed / total if total else 0.0,
    }


def _aggregate_stage_level(verdicts: list[dict[str, Any]]) -> str:
    """Aggregate all rule verdicts of a stage within a case into a single level.

    - any fail → fail
    - all pass → pass
    - otherwise → unknown
    """

    levels = {str(v.get("level", "unknown")) for v in verdicts}
    if "fail" in levels:
        return "fail"
    if levels == {"pass"}:
        return "pass"
    return "unknown"


def write_results_json(results: dict[str, Any], output_path: Path) -> Path:
    """Write the complete evaluation results to a JSON file.

    Args:
        results: The complete evaluation-results dict.
        output_path: The output file path.

    Returns:
        The actual file path written.
    """

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(results, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )
    return output_path


def generate_release_gate_report(
    eval_results: dict[str, Any],
    gate_criteria: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Generate a release-gate report from the evaluation results.

    Gate decision logic:
    1. number of evaluated cases >= min_cases_evaluated
    2. end-to-end pass rate >= min_pass_rate
    3. fail rate <= max_fail_rate
    4. each stage in critical_stages has a pass rate >= min_pass_rate

    Args:
        eval_results: The complete evaluation-results dict, containing
                      case_results and rule_results.
        gate_criteria: Gate criteria dict (optional, defaults to DEFAULT_GATE_CRITERIA).

    Returns:
        A gate-report dict containing passed, criteria, details, etc.
    """

    criteria = {**DEFAULT_GATE_CRITERIA, **(gate_criteria or {})}
    case_results = eval_results.get("case_results", [])
    rule_results = eval_results.get("rule_results", [])

    # ── gate 1: number of evaluated cases ──
    case_count = len(case_results)
    min_cases = int(criteria["min_cases_evaluated"])
    gate_case_count = case_count >= min_cases

    # ── gate 2: end-to-end pass rate ──
    case_summary = summarize_levels(case_results)
    pass_rate = float(case_summary["pass_rate"])
    min_pass = float(criteria["min_pass_rate"])
    gate_pass_rate = pass_rate >= min_pass

    # ── gate 3: fail rate ──
    fail_rate = float(case_summary["failed"]) / float(case_summary["total"]) if case_summary["total"] else 1.0
    max_fail = float(criteria["max_fail_rate"])
    gate_fail_rate = fail_rate <= max_fail

    # ── gate 4: critical stage pass rate ──
    critical_stages: list[str] = list(criteria["critical_stages_must_pass"])
    stage_details: list[dict[str, Any]] = []
    critical_stages_pass = True

    for stage in critical_stages:
        stage_verdicts = [
            v for v in rule_results
            if str(v.get("stage")) == stage
        ]
        stage_summary = summarize_levels(stage_verdicts)
        stage_pass_rate = float(stage_summary["pass_rate"])
        stage_passed = stage_pass_rate >= min_pass
        if not stage_passed:
            critical_stages_pass = False
        stage_details.append({
            "stage": stage,
            "passed": stage_passed,
            "pass_rate": stage_pass_rate,
            "summary": stage_summary,
        })

    # ── overall decision ──
    all_passed = (
        gate_case_count
        and gate_pass_rate
        and gate_fail_rate
        and critical_stages_pass
    )

    return {
        "passed": all_passed,
        "criteria": criteria,
        "case_count": case_count,
        "case_summary": case_summary,
        "gates": {
            "min_cases_evaluated": {
                "passed": gate_case_count,
                "actual": case_count,
                "required": min_cases,
            },
            "min_pass_rate": {
                "passed": gate_pass_rate,
                "actual": pass_rate,
                "required": min_pass,
            },
            "max_fail_rate": {
                "passed": gate_fail_rate,
                "actual": fail_rate,
                "required": max_fail,
            },
            "critical_stages_must_pass": {
                "passed": critical_stages_pass,
                "details": stage_details,
            },
        },
    }


__all__ = [
    "DEFAULT_GATE_CRITERIA",
    "summarize_levels",
    "write_results_json",
    "generate_release_gate_report",
]
