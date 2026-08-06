#!/usr/bin/env python3
"""validate_baseline_gate.py — validate a baseline-gate.json (Todo 11/F1/F2/F4).

Recomputes the schema_hash from the canonical db/migrations/*.sql concatenation
(per the SCHEMA-CANONICALIZATION CONTRACT in scripts/canonicalize_schema.py) —
NEVER trusting the stored field — and validates endpoint health + web build.

Usage:
  python scripts/validate_baseline_gate.py <baseline-gate.json>
Exit 0 when valid, 1 otherwise.
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def canonical_schema_hash() -> str:
    """sha256 of the canonical db/migrations/*.sql concatenation (byte-exact)."""
    files = sorted(
        (f for f in (ROOT / "db" / "migrations").glob("*.sql")
         if not f.name.startswith("golden-")),
        key=lambda p: p.name.encode("utf-8"))
    parts = []
    for f in files:
        raw = f.read_bytes()
        # strict UTF-8, strip BOM
        text = raw.decode("utf-8").lstrip("\ufeff")
        lines = []
        for ln in text.split("\n"):
            ln = ln.rstrip("\r").rstrip(" \t")
            if ln:
                lines.append(ln)
        parts.append("\n".join(lines))
    blob = "\n".join(parts) + "\n"
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: validate_baseline_gate.py <baseline-gate.json>", file=sys.stderr)
        return 2
    gate_path = Path(sys.argv[1])
    if not gate_path.exists():
        print(f"GATE_NOT_FOUND: {gate_path}", file=sys.stderr)
        return 1
    gate = json.loads(gate_path.read_text())
    schema = json.loads((ROOT / "docs" / "baseline-gate.schema.json").read_text())
    try:
        import jsonschema
        jsonschema.validate(gate, schema)
    except Exception as e:  # noqa: BLE001
        print(f"GATE_SCHEMA_FAIL: {e}", file=sys.stderr)
        return 1
    # recompute schema_hash (never trust stored field)
    recomputed = canonical_schema_hash()
    if gate.get("schema_hash") != recomputed:
        print(f"GATE_SCHEMA_HASH_MISMATCH: stored={gate.get('schema_hash')} recomputed={recomputed}",
              file=sys.stderr)
        return 1
    if gate.get("web_build_ok") is not True:
        print("GATE_WEB_BUILD_NOT_OK", file=sys.stderr)
        return 1
    for k, v in gate.get("endpoint_health", {}).items():
        if v != "ok":
            print(f"GATE_ENDPOINT_UNHEALTHY: {k}={v}", file=sys.stderr)
            return 1
    print("BASELINE_GATE_OK: schema_hash recomputed and matches; endpoints healthy; web build ok")
    return 0


if __name__ == "__main__":
    sys.exit(main())
