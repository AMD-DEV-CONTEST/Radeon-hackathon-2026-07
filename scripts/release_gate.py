"""Insurance RAG Agent release gate checker.

Reads eval_results/{trial_id}/eval_results.json, checks each gate standard item by item,
and prints PASS/FAIL results.

Usage:
    python scripts/release_gate.py --trial-id trial-001
    python scripts/release_gate.py --results eval_results/trial-001/eval_results.json
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

# Ensure the project root is on the Python path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.eval.report import DEFAULT_GATE_CRITERIA, generate_release_gate_report


def _format_bool(passed: bool) -> str:
    """Format a boolean value as PASS/FAIL."""

    return "PASS" if passed else "FAIL"


def _print_gate_report(report: dict[str, Any]) -> None:
    """Print the release gate report."""

    gates = report.get("gates", {})
    criteria = report.get("criteria", {})

    print("=" * 60)
    print("Insurance RAG Agent release gate check report")
    print("=" * 60)
    print()

    # Gate 1: number of evaluated cases
    gate1 = gates.get("min_cases_evaluated", {})
    print(f"[1] Evaluated cases >= {gate1.get('required', '?')}")
    print(f"    actual: {gate1.get('actual', '?')}")
    print(f"    result: {_format_bool(bool(gate1.get('passed', False)))}")
    print()

    # Gate 2: end-to-end pass rate
    gate2 = gates.get("min_pass_rate", {})
    actual_rate = float(gate2.get("actual", 0))
    required_rate = float(gate2.get("required", 0))
    print(f"[2] End-to-end pass rate >= {required_rate:.0%}")
    print(f"    actual: {actual_rate:.1%}")
    print(f"    result: {_format_bool(bool(gate2.get('passed', False)))}")
    print()

    # Gate 3: fail rate
    gate3 = gates.get("max_fail_rate", {})
    actual_fail = float(gate3.get("actual", 0))
    max_fail = float(gate3.get("required", 0))
    print(f"[3] Fail rate <= {max_fail:.0%}")
    print(f"    actual: {actual_fail:.1%}")
    print(f"    result: {_format_bool(bool(gate3.get('passed', False)))}")
    print()

    # Gate 4: critical stages
    gate4 = gates.get("critical_stages_must_pass", {})
    critical_stages = criteria.get("critical_stages_must_pass", [])
    print(f"[4] All critical stages pass (pass rate >= {float(criteria.get('min_pass_rate', 0)):.0%})")
    for stage_name in critical_stages:
        stage_detail = None
        for detail in gate4.get("details", []):
            if str(detail.get("stage")) == str(stage_name):
                stage_detail = detail
                break
        if stage_detail:
            stage_rate = float(stage_detail.get("pass_rate", 0))
            stage_passed = bool(stage_detail.get("passed", False))
            print(f"    {stage_name}: {stage_rate:.1%} -> {_format_bool(stage_passed)}")
        else:
            print(f"    {stage_name}: no data -> FAIL")
    print(f"    result: {_format_bool(bool(gate4.get('passed', False)))}")
    print()

    # Overall verdict
    overall = bool(report.get("passed", False))
    print("=" * 60)
    print(f"Overall verdict: {_format_bool(overall)}")
    print("=" * 60)

    # Case summary
    case_summary = report.get("case_summary", {})
    print()
    print("Case summary:")
    print(f"  total:  {case_summary.get('total', 0)}")
    print(f"  passed: {case_summary.get('passed', 0)}")
    print(f"  failed: {case_summary.get('failed', 0)}")
    print(f"  unknown:{case_summary.get('unknown', 0)}")
    print(f"  pass rate: {float(case_summary.get('pass_rate', 0)):.1%}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Insurance RAG Agent release gate check")
    parser.add_argument(
        "--results",
        type=Path,
        default=None,
        help="path to eval_results.json",
    )
    parser.add_argument(
        "--trial-id",
        default=None,
        help="evaluation batch ID (auto-find eval_results/{trial_id}/eval_results.json)",
    )
    parser.add_argument(
        "--output-root",
        type=Path,
        default=PROJECT_ROOT / "eval_results",
        help="evaluation results root directory",
    )
    args = parser.parse_args()

    # Determine the results file path
    if args.results is not None:
        results_path = args.results
    elif args.trial_id is not None:
        results_path = args.output_root / args.trial_id / "eval_results.json"
    else:
        # Auto-find the latest trial
        if not args.output_root.exists():
            print(f"Error: evaluation results directory does not exist: {args.output_root}")
            sys.exit(1)
        trials = sorted(
            [p for p in args.output_root.iterdir() if p.is_dir()],
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
        if not trials:
            print(f"Error: no evaluation batches found in {args.output_root}")
            sys.exit(1)
        results_path = trials[0] / "eval_results.json"
        print(f"Auto-selected latest batch: {trials[0].name}")

    if not results_path.exists():
        print(f"Error: results file does not exist: {results_path}")
        sys.exit(1)

    # Load results
    results = json.loads(results_path.read_text(encoding="utf-8"))

    # If the results already contain a release_gate, use it directly
    if "release_gate" in results:
        report = results["release_gate"]
    else:
        # Otherwise regenerate it
        from src.eval.report import generate_release_gate_report

        report = generate_release_gate_report(
            {
                "case_results": results.get("case_results", []),
                "rule_results": results.get("rule_results", []),
            },
        )

    _print_gate_report(report)

    # Exit code
    if report.get("passed"):
        sys.exit(0)
    else:
        sys.exit(1)


if __name__ == "__main__":
    main()
