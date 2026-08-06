"""SQLite-backed persistence for documents and audit reports.

Ensures that uploaded documents, spans, and generated reports survive server restarts,
supporting multi-turn operations and persistent UI state.
"""
from __future__ import annotations

import json
import sqlite3
from typing import Any

from veil.config import CONFIG
from veil.types import Span, Finding, IterationResult, Tier

_SCHEMA = """
CREATE TABLE IF NOT EXISTS documents (
    document_id  TEXT PRIMARY KEY,
    filename     TEXT NOT NULL,
    filepath     TEXT NOT NULL,
    text         TEXT NOT NULL,
    spans        TEXT NOT NULL,
    created_at   INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS audit_reports (
    document_id  TEXT PRIMARY KEY,
    final_text   TEXT NOT NULL,
    report_json  TEXT NOT NULL,
    updated_at   INTEGER NOT NULL,
    FOREIGN KEY(document_id) REFERENCES documents(document_id)
);
"""

class PersistenceStore:
    def __init__(self, db_path: str | None = None) -> None:
        self.db_path = db_path or CONFIG.storage.db_path
        con = self._con()
        try:
            con.executescript(_SCHEMA)
            con.commit()
        finally:
            con.close()

    def _con(self) -> sqlite3.Connection:
        return sqlite3.connect(self.db_path)

    def save_document(
        self, doc_id: str, filename: str, filepath: str, text: str, spans: list[Span]
    ) -> None:
        con = self._con()
        try:
            spans_json = json.dumps([
                {"start": s.start, "end": s.end, "text": s.text, "page": s.page, "source": s.source}
                for s in spans
            ])
            import time
            con.execute(
                "INSERT OR REPLACE INTO documents (document_id, filename, filepath, text, spans, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (doc_id, filename, filepath, text, spans_json, int(time.time() * 1000))
            )
            con.commit()
        finally:
            con.close()

    def load_document(self, doc_id: str) -> dict[str, Any] | None:
        con = self._con()
        try:
            row = con.execute(
                "SELECT filename, filepath, text, spans FROM documents WHERE document_id = ?",
                (doc_id,)
            ).fetchone()
            if not row:
                return None
            spans_data = json.loads(row[3])
            spans = [
                Span(start=s["start"], end=s["end"], text=s["text"], page=s.get("page"), source=s.get("source", "body"))
                for s in spans_data
            ]
            return {
                "ok": True,
                "document_id": doc_id,
                "filename": row[0],
                "path": row[1],
                "text": row[2],
                "spans": spans,
                "char_count": len(row[2]),
                "span_count": len(spans),
            }
        finally:
            con.close()

    def save_report(self, doc_id: str, final_text: str, report: Any) -> None:
        con = self._con()
        try:
            import time
            # Serialize the RunReport
            report_dict = {
                "document_id": report.document_id,
                "original_text": report.original_text,
                "final_text": report.final_text,
                "iterations": [
                    {
                        "iteration": it.iteration,
                        "findings": [
                            {
                                "persona": f.persona,
                                "tier": f.tier.value,
                                "claim": f.claim,
                                "reasoning": f.reasoning,
                                "spans": [
                                    {"start": s.start, "end": s.end, "text": s.text, "page": s.page, "source": s.source}
                                    for s in f.spans
                                ],
                                "severity": f.severity,
                                "candidate_set_size": f.candidate_set_size,
                                "caveat": f.caveat,
                                "id": f.id,
                                "resolved": f.resolved,
                            }
                            for f in it.findings
                        ],
                        "residual_risk": it.residual_risk,
                        "utility_retained": it.utility_retained,
                        "elapsed_s": it.elapsed_s,
                    }
                    for it in report.iterations
                ],
                "curve": report.curve,
                "metrics": report.metrics,
                "plan": report.plan,
                "stopped_because": report.stopped_because,
            }
            con.execute(
                "INSERT OR REPLACE INTO audit_reports (document_id, final_text, report_json, updated_at) "
                "VALUES (?, ?, ?, ?)",
                (doc_id, final_text, json.dumps(report_dict), int(time.time() * 1000))
            )
            con.commit()
        finally:
            con.close()

    def load_report(self, doc_id: str) -> Any | None:
        con = self._con()
        try:
            row = con.execute(
                "SELECT final_text, report_json FROM audit_reports WHERE document_id = ?",
                (doc_id,)
            ).fetchone()
            if not row:
                return None
            report_dict = json.loads(row[1])

            from veil.agents.orchestrator import RunReport

            report = RunReport(
                document_id=report_dict["document_id"],
                original_text=report_dict["original_text"],
                final_text=report_dict["final_text"],
                iterations=[
                    IterationResult(
                        iteration=it["iteration"],
                        findings=[
                            Finding(
                                persona=f["persona"],
                                tier=Tier(f["tier"]),
                                claim=f["claim"],
                                reasoning=f["reasoning"],
                                spans=[
                                    Span(start=s["start"], end=s["end"], text=s["text"], page=s.get("page"), source=s.get("source", "body"))
                                    for s in f["spans"]
                                ],
                                severity=f["severity"],
                                candidate_set_size=f["candidate_set_size"],
                                caveat=f["caveat"],
                                id=f["id"],
                                resolved=f["resolved"],
                            )
                            for f in it["findings"]
                        ],
                        residual_risk=it["residual_risk"],
                        utility_retained=it["utility_retained"],
                        elapsed_s=it["elapsed_s"],
                    )
                    for it in report_dict["iterations"]
                ],
                curve=report_dict["curve"],
                metrics=report_dict["metrics"],
                plan=report_dict["plan"],
                stopped_because=report_dict["stopped_because"],
            )
            return report
        finally:
            con.close()

PERSISTENCE = PersistenceStore()
