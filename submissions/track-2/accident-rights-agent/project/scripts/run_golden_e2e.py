"""Run and report the deterministic Golden Case without starting the UI."""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.demo.golden_case import seed_golden_case
from app.schemas.ui import WorkflowMode
from app.services.case_service import CaseService
from app.services.report_service import ReportService
from app.services.workflow_service import WorkflowService


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--mode",
        choices=[item.value for item in WorkflowMode],
        default=os.getenv("MODEL_MODE", "mock"),
    )
    parser.add_argument(
        "--case-root", type=Path, default=Path("data/cases")
    )
    parser.add_argument(
        "--checkpoint",
        type=Path,
        default=Path("data/checkpoints/orchestrator.sqlite3"),
    )
    parser.add_argument(
        "--legal-corpus",
        type=Path,
        default=Path("data/laws/legal_corpus.sqlite3"),
    )
    parser.add_argument(
        "--qdrant", type=Path, default=Path("data/qdrant/legal")
    )
    parser.add_argument(
        "--report-root",
        type=Path,
        default=Path("artifacts/demo_reports"),
    )
    args = parser.parse_args()

    cases = CaseService(args.case_root)
    case_id = seed_golden_case(cases.workspace)
    workflows = WorkflowService(
        cases,
        checkpoint_path=args.checkpoint,
        legal_corpus_path=args.legal_corpus,
        qdrant_path=args.qdrant,
    )
    started = time.perf_counter()
    updates = list(
        workflows.run_incremental(case_id, mode=WorkflowMode(args.mode))
    )
    elapsed = round(time.perf_counter() - started, 3)
    final = updates[-1]
    state = final["state"]
    artifact = ReportService(cases, args.report_root).export(case_id, state)
    result = {
        "case_id": case_id,
        "thread_id": final["thread_id"],
        "mode": args.mode,
        "status": state.get("approval_status"),
        "document_status": state.get("document_status"),
        "policy_gate": state.get("policy_gate", {}).get("decision"),
        "elapsed_seconds": elapsed,
        "node_durations_ms": final["node_durations_ms"],
        "warning_count": final["warning_count"],
        "failure_count": final["failure_count"],
        "checkpoint_cache_hit": bool(
            state.get("evidence_summary", {}).get("high_cost_parser_reexecuted")
            is False
        ),
        "markdown_report": str(artifact.markdown_path),
        "html_report": str(artifact.html_path),
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if final["failure_count"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
