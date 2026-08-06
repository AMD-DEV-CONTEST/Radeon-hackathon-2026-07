#!/usr/bin/env python3
"""decide_routing.py — deterministic Qwen2.5/Qwen3 routing decision (Todo 6).

Reads two schema-valid eval reports (qwen25 + qwen3), extracts the metrics,
applies the plan's routing pseudocode, and writes a schema-valid
routing-decision.json atomically (tmp+rename). NEVER mutates the input reports.

Routing pseudocode (threshold_version 1):
    select_qwen3 = (fatal_qwen3 == 0
                    AND fatal_qwen25 <= fatal_qwen3
                    AND support_gain  >= 2
                    AND unsupported_reduction >= 2
                    AND (coverage_gain >= 2 OR agreement_gain >= 2))

Usage:
  python scripts/decide_routing.py \
      --qwen25-report <a.json> --qwen3-report <b.json> \
      --schema <routing-decision.schema.json> --out <routing-decision.json>
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import tempfile
import time
from pathlib import Path

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def report_sha256(report_a: dict, report_b: dict) -> str:
    """Canonical digest over both reports (sort_keys) for tamper-evidence."""
    h = hashlib.sha256()
    h.update(json.dumps(report_a, ensure_ascii=False, sort_keys=True).encode())
    h.update(b"|")
    h.update(json.dumps(report_b, ensure_ascii=False, sort_keys=True).encode())
    return h.hexdigest()


def decide(metrics: dict) -> str:
    """Apply threshold_version 1 pseudocode. Returns 'qwen3' or 'qwen2.5'."""
    support_gain = metrics["support_qwen3"] - metrics["support_qwen25"]
    unsupported_reduction = metrics["unsupported_qwen25"] - metrics["unsupported_qwen3"]
    coverage_gain = metrics["coverage_qwen3"] - metrics["coverage_qwen25"]
    agreement_gain = metrics["agreement_qwen3"] - metrics["agreement_qwen25"]
    select_qwen3 = (
        metrics["fatal_qwen3"] == 0
        and metrics["fatal_qwen25"] <= metrics["fatal_qwen3"]
        and support_gain >= 2
        and unsupported_reduction >= 2
        and (coverage_gain >= 2 or agreement_gain >= 2)
    )
    return "qwen3" if select_qwen3 else "qwen2.5"


def extract_metrics(report: dict) -> dict:
    m = report["metrics"]
    return {
        "fatal": len(report.get("fatal_failures", [])),
        "support": m["source_support"],
        "unsupported": m["unsupported_claim"],
        "coverage": m["key_point_coverage"],
        "agreement": m.get("grading_agreement"),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--qwen25-report", required=True)
    ap.add_argument("--qwen3-report", required=True)
    ap.add_argument("--schema", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    a = json.loads(Path(args.qwen25_report).read_text())
    b = json.loads(Path(args.qwen3_report).read_text())
    ma, mb = extract_metrics(a), extract_metrics(b)

    # agreement may be null in reports; normalize to 0.0 for comparability
    agree25 = ma["agreement"] if ma["agreement"] is not None else 0.0
    agree3 = mb["agreement"] if mb["agreement"] is not None else 0.0

    metrics = {
        "fatal_qwen25": ma["fatal"],
        "fatal_qwen3": mb["fatal"],
        "support_qwen25": round(ma["support"], 2),
        "support_qwen3": round(mb["support"], 2),
        "unsupported_qwen25": round(ma["unsupported"], 2),
        "unsupported_qwen3": round(mb["unsupported"], 2),
        "coverage_qwen25": round(ma["coverage"], 2),
        "coverage_qwen3": round(mb["coverage"], 2),
        "agreement_qwen25": round(agree25, 2),
        "agreement_qwen3": round(agree3, 2),
    }

    decision = decide(metrics)
    # Store REPO-RELATIVE report paths so the decision is self-consistent inside
    # any disposable worktree (F1/F2/F4 run validate_routing_decision.py there).
    q25_rel = os.path.relpath(args.qwen25_report, ROOT_DIR)
    q3_rel = os.path.relpath(args.qwen3_report, ROOT_DIR)
    decision_doc = {
        "routing_schema_version": 1,
        "report_sha256": report_sha256(a, b),
        "report_schema_version": 1,
        "model_revisions": {
            "qwen25": {"model": a.get("model", "unknown"), "report": q25_rel, "sha256": hashlib.sha256(Path(args.qwen25_report).read_bytes()).hexdigest()},
            "qwen3": {"model": b.get("model", "unknown"), "report": q3_rel, "sha256": hashlib.sha256(Path(args.qwen3_report).read_bytes()).hexdigest()},
        },
        "metrics": metrics,
        "threshold_version": 1,
        "decision": decision,
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }

    # validate against schema before writing
    schema = json.loads(Path(args.schema).read_text())
    try:
        import jsonschema
        jsonschema.validate(decision_doc, schema)
    except ImportError:
        pass  # structural self-check below
    except Exception as e:  # noqa: BLE001
        print(f"SCHEMA_FAIL: {e}", file=sys.stderr)
        return 1

    # atomic write
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(os.path.abspath(args.out)) or ".",
                               prefix=".routing-decision-", suffix=".json.tmp")
    try:
        with os.fdopen(fd, "w") as fh:
            json.dump(decision_doc, fh, ensure_ascii=False, indent=2)
            fh.write("\n")
        os.replace(tmp, args.out)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)

    print(f"ROUTING_DECISION={decision} -> {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
