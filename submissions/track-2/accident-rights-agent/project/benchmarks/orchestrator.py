"""Synthetic end-to-end workflow and checkpoint-recovery benchmark."""

from __future__ import annotations

import json
import sqlite3
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.evidence.workspace import CaseWorkspace
from app.graph.workflow import CaseOrchestrator
from app.rag.service import build_retriever
from scripts.create_orchestrator_demo import create_demo


def main() -> int:
    output = Path("benchmarks/reports/orchestrator.json")
    with tempfile.TemporaryDirectory(prefix="accident-rights-benchmark-") as temporary:
        root = Path(temporary)
        case_root = root / "cases"
        case_id = create_demo(case_root, "CASE-BENCHMARK")
        retriever = build_retriever(
            embedding_provider="hash", reranker_provider="heuristic"
        )
        orchestrator = CaseOrchestrator(
            workspace=CaseWorkspace(case_root),
            retriever=retriever,
            checkpoint_path=root / "checkpoints.sqlite3",
        )
        try:
            started = time.perf_counter()
            interrupted = orchestrator.run(
                case_id,
                thread_id="THREAD-BENCHMARK",
                interrupt_after="evidence_ready",
            )
            interrupt_ms = (time.perf_counter() - started) * 1000
            status = orchestrator.status("THREAD-BENCHMARK")
            started = time.perf_counter()
            completed = orchestrator.resume("THREAD-BENCHMARK")
            resume_ms = (time.perf_counter() - started) * 1000
        finally:
            orchestrator.close()
            retriever.close()

        database = case_root / case_id / "case.sqlite3"
        with sqlite3.connect(database) as connection:
            rows = connection.execute(
                "SELECT node_name, before_tokens, after_tokens "
                "FROM working_memory ORDER BY id"
            ).fetchall()
        before = sum(row[1] for row in rows)
        after = sum(row[2] for row in rows)
        result = {
            "case_id": case_id,
            "interrupted_at": interrupted["current_node"],
            "recoverable": status["recoverable"],
            "resumed_to": completed["current_node"],
            "high_cost_parser_reexecuted": completed["evidence_summary"][
                "high_cost_parser_reexecuted"
            ],
            "approval_status": completed["approval_status"],
            "document_status": completed["document_status"],
            "verifier_passed": completed["verifier_results"]["passed"],
            "protected_fields_valid": completed["protected_fields_valid"],
            "interrupt_phase_ms": round(interrupt_ms, 3),
            "resume_phase_ms": round(resume_ms, 3),
            "context_before_tokens": before,
            "context_after_tokens": after,
            "context_reduction_percent": round(
                100 * (before - after) / max(1, before), 2
            ),
            "context_rows": [
                {
                    "node": row[0],
                    "before_tokens": row[1],
                    "after_tokens": row[2],
                }
                for row in rows
            ],
            "node_metrics": {
                name: payload["metrics"]
                for name, payload in completed["node_results"].items()
            },
            "reranker": "heuristic-overlap",
            "reranker_degraded_reason": (
                "BGE reranker not enabled in this local Mac validation runtime"
            ),
        }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if (
        result["recoverable"]
        and result["verifier_passed"]
        and result["protected_fields_valid"]
    ) else 2


if __name__ == "__main__":
    raise SystemExit(main())
