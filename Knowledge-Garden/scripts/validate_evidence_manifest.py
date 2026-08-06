#!/usr/bin/env python3
"""validate_evidence_manifest.py — validate eval/evidence-manifest.json (Todo 11).

Checks:
  - schema-valid (docs/evidence-manifest.schema.json)
  - every required artifact exists with kind file|dir and its expected producer todo
  - NO overlap between required_artifacts paths and excluded_artifacts

Usage:
  python scripts/validate_evidence_manifest.py --manifest eval/evidence-manifest.json
Exit 0 when valid, 1 otherwise.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCHEMA = ROOT / "docs" / "evidence-manifest.schema.json"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--manifest", required=True)
    args = ap.parse_args()

    manifest = json.loads(Path(args.manifest).read_text())
    schema = json.loads(SCHEMA.read_text())
    try:
        import jsonschema
        jsonschema.validate(manifest, schema)
    except Exception as e:  # noqa: BLE001
        print(f"EVIDENCE_SCHEMA_FAIL: {e}", file=sys.stderr)
        return 1

    required = {a["path"] for a in manifest["required_artifacts"]}
    excluded = set(manifest.get("excluded_artifacts", []))
    overlap = required & excluded
    if overlap:
        print(f"EVIDENCE_OVERLAP: required/excluded overlap: {sorted(overlap)}", file=sys.stderr)
        return 1

    root = Path(args.manifest).resolve().parent.parent  # repo root (eval/evidence-manifest.json)
    missing = []
    for a in manifest["required_artifacts"]:
        p = root / a["path"]
        if a["kind"] == "file" and not p.is_file():
            missing.append(a["path"])
        elif a["kind"] == "dir" and not p.is_dir():
            missing.append(a["path"])
    if missing:
        print(f"EVIDENCE_MISSING: {sorted(missing)}", file=sys.stderr)
        return 1

    print(f"EVIDENCE_OK: {len(required)} required artifacts present, no required/excluded overlap")
    return 0


if __name__ == "__main__":
    sys.exit(main())
