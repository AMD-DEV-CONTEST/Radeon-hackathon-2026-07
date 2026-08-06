#!/usr/bin/env python3
"""validate_verdict.py — validate a verdict JSON against docs/verdict.schema.json.

Usage:
  python scripts/validate_verdict.py --schema docs/verdict.schema.json <verdict.json>
Exit 0 when valid, 1 otherwise.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--schema", default=str(ROOT / "docs" / "verdict.schema.json"))
    ap.add_argument("verdict")
    args = ap.parse_args()

    schema = json.loads(Path(args.schema).read_text())
    verdict = json.loads(Path(args.verdict).read_text())
    try:
        import jsonschema
        jsonschema.validate(verdict, schema)
    except Exception as e:  # noqa: BLE001
        print(f"VERDICT_SCHEMA_FAIL: {e}", file=sys.stderr)
        return 1
    # every check must carry evidence
    for c in verdict.get("checks", []):
        if not c.get("evidence"):
            print(f"VERDICT_CHECK_MISSING_EVIDENCE: {c.get('name')}", file=sys.stderr)
            return 1
    print(f"VERDICT_OK: {verdict.get('result')} ({len(verdict.get('checks', []))} checks)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
