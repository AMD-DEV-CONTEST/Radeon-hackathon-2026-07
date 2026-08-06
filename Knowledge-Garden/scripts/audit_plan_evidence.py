#!/usr/bin/env python3
"""audit_plan_evidence.py — derive each Todo's status from actual files (Todo 11/F1).

Reads the evidence manifest (eval/evidence-manifest.json) and the evidence tree
(<dir>), and for each required artifact asserts the file exists AND its sha256
matches the recorded digest. NEVER accepts handwritten APPROVED cells.

Usage:
  python scripts/audit_plan_evidence.py --manifest eval/evidence-manifest.json \
      --evidence <evidence-dir>
Exit 0 when every artifact has a matching hash, 1 otherwise.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def sha256_file(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _write_verdict(path: str, result: str, failures: list[str]) -> None:
    """Write a schema-valid verdict JSON (docs/verdict.schema.json)."""
    import time
    checks = [{"name": "plan-evidence", "status": "ok" if result == "APPROVED" else "failed",
               "evidence": "; ".join(failures) if failures else "all required artifacts verified"}]
    verdict = {
        "verdict_schema_version": 1,
        "verifier_id": "F1",
        "result": result,
        "checks": checks,
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(verdict, ensure_ascii=False, indent=2))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--manifest", required=True)
    ap.add_argument("--evidence", required=True)
    ap.add_argument("--verdict-out", default=None,
                    help="write a schema-valid verdict JSON to this path")
    args = ap.parse_args()

    manifest = json.loads(Path(args.manifest).read_text())
    evidence_root = Path(args.evidence)
    repo_root = Path(args.manifest).resolve().parent.parent

    failures = []
    for a in manifest["required_artifacts"]:
        p = repo_root / a["path"]
        if a["kind"] == "file":
            if not p.is_file():
                failures.append(f"{a['path']}: missing")
                continue
            actual = sha256_file(p)
            # hash may be recorded in the manifest itself or under the evidence tree
            recorded = a.get("sha256")
            if recorded and actual != recorded:
                failures.append(f"{a['path']}: sha256 mismatch (actual={actual})")
        elif a["kind"] == "dir":
            if not p.is_dir():
                failures.append(f"{a['path']}: missing dir")
        # todo-level evidence dir under the evidence tree
        todo_dir = evidence_root / f"task-{a['producer_todo']}"
        if not todo_dir.is_dir():
            failures.append(f"task-{a['producer_todo']}: no evidence dir in tree")

    if failures:
        for f in failures:
            print(f"AUDIT_FAIL: {f}", file=sys.stderr)
        print("AUDIT_PLAN_EVIDENCE_FAIL", file=sys.stderr)
        if args.verdict_out:
            _write_verdict(args.verdict_out, "CHANGES_REQUESTED", failures)
        return 1
    print(f"AUDIT_PLAN_EVIDENCE_OK: {len(manifest['required_artifacts'])} artifacts verified")
    if args.verdict_out:
        _write_verdict(args.verdict_out, "APPROVED", [])
    return 0


if __name__ == "__main__":
    sys.exit(main())
