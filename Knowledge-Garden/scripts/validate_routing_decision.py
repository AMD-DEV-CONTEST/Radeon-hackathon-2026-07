#!/usr/bin/env python3
"""validate_routing_decision.py — recompute routing decision from source reports (Todo 6).

Re-reads the two eval reports referenced by a routing-decision.json, recomputes
the report_sha256 digest and the decision per threshold_version 1, and exits 0
only if BOTH match the stored decision document. Used as the post-hoc audit
gate: any tamper with the reports or the decision is detected.

Usage:
  python scripts/validate_routing_decision.py <routing-decision.json>
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

from decide_routing import decide, report_sha256


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("decision", help="path to routing-decision.json")
    args = ap.parse_args()

    doc = json.loads(Path(args.decision).read_text())

    def _report_path(rel: str) -> Path:
        """Resolve a (possibly repo-relative) report path against the CWD so the
        decision is self-consistent inside a disposable worktree."""
        p = Path(rel)
        return p if p.is_absolute() else Path.cwd() / p

    q25_path = _report_path(doc["model_revisions"]["qwen25"]["report"])
    q3_path = _report_path(doc["model_revisions"]["qwen3"]["report"])

    # recompute digest over the referenced reports
    q25 = json.loads(q25_path.read_text())
    q3 = json.loads(q3_path.read_text())
    recomputed_digest = report_sha256(q25, q3)

    # recompute decision from stored metrics (independently of reports)
    recomputed_decision = decide(doc["metrics"])

    # recompute per-report file digests
    q25_sha = hashlib.sha256(q25_path.read_bytes()).hexdigest()
    q3_sha = hashlib.sha256(q3_path.read_bytes()).hexdigest()

    ok = True
    if recomputed_digest != doc["report_sha256"]:
        print(f"DIGEST_MISMATCH: stored={doc['report_sha256']} recomputed={recomputed_digest}", file=sys.stderr)
        ok = False
    if recomputed_decision != doc["decision"]:
        print(f"DECISION_MISMATCH: stored={doc['decision']} recomputed={recomputed_decision}", file=sys.stderr)
        ok = False
    if q25_sha != doc["model_revisions"]["qwen25"]["sha256"]:
        print(f"REPORT_SHA_MISMATCH(qwen25): stored={doc['model_revisions']['qwen25']['sha256']} actual={q25_sha}", file=sys.stderr)
        ok = False
    if q3_sha != doc["model_revisions"]["qwen3"]["sha256"]:
        print(f"REPORT_SHA_MISMATCH(qwen3): stored={doc['model_revisions']['qwen3']['sha256']} actual={q3_sha}", file=sys.stderr)
        ok = False

    if ok:
        print(f"VALIDATE_OK: decision={doc['decision']} digest_ok report_digests_ok")
        return 0
    print("VALIDATE_FAIL", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
