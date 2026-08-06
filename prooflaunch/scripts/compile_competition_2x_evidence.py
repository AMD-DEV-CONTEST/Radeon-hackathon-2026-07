#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path

from prooflaunch_remix.competition_benchmark import compile_competition_evidence
from prooflaunch_remix.quality_contract import QualityTier, contract_for


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Compile case-level ProofLaunch, baseline, and blinded-human evidence "
            "before applying the competition-2X gate"
        )
    )
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--results", required=True, type=Path)
    parser.add_argument("--baseline-results", required=True, type=Path)
    parser.add_argument("--human-comparisons", required=True, type=Path)
    parser.add_argument("--evidence-output", required=True, type=Path)
    parser.add_argument("--report-output", required=True, type=Path)
    arguments = parser.parse_args()
    evidence = compile_competition_evidence(
        manifest_path=arguments.manifest,
        results_path=arguments.results,
        baseline_results_path=arguments.baseline_results,
        human_comparisons_path=arguments.human_comparisons,
    )
    report = contract_for(QualityTier.COMPETITION_2X).evaluate(evidence)
    arguments.evidence_output.parent.mkdir(parents=True, exist_ok=True)
    arguments.report_output.parent.mkdir(parents=True, exist_ok=True)
    arguments.evidence_output.write_text(
        json.dumps(evidence, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    arguments.report_output.write_text(
        json.dumps(report.to_dict(), ensure_ascii=False, indent=2, sort_keys=True)
        + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "compiled_evidence": str(arguments.evidence_output),
                "acceptance_report": str(arguments.report_output),
                "passed": report.passed,
                "passed_metrics": sum(item.passed for item in report.metrics),
                "total_metrics": len(report.metrics),
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0 if report.passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
