#!/usr/bin/env python3
"""compare_logical_digests.py — logical-content equality check (Todo 6).

Compares two schema-valid service descriptors and asserts that their LOGICAL
content is identical: executable, argv, cwd, checkpoint_path, checkpoint_revision,
env, port, served_model_id, launcher_method. Volatile fields (captured_at, pid
if present) are excluded.

Used by run_model_eval.sh to enforce READ-ONLY model experimentation: the
descriptor captured BEFORE any model swap must match the descriptor captured
AFTER restoration, proving no service identity drift.

Usage:
  python scripts/compare_logical_digests.py --before <a.json> --after <b.json>
Exit 0 when logically identical, 1 otherwise.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

LOGICAL_FIELDS = [
    "executable", "argv", "cwd", "checkpoint_path", "checkpoint_revision",
    "env", "port", "served_model_id", "launcher_method",
]
VOLATILE_FIELDS = {"captured_at", "pid", "log_path"}


def logical_view(desc: dict) -> dict:
    return {k: desc.get(k) for k in LOGICAL_FIELDS}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--before", required=True)
    ap.add_argument("--after", required=True)
    args = ap.parse_args()

    before = json.loads(Path(args.before).read_text())
    after = json.loads(Path(args.after).read_text())

    if before.get("descriptor_schema_version") != after.get("descriptor_schema_version"):
        print(f"SCHEMA_VERSION_MISMATCH: {before.get('descriptor_schema_version')} vs {after.get('descriptor_schema_version')}", file=sys.stderr)
        return 1

    vb, va = logical_view(before), logical_view(after)
    if vb != va:
        for k in LOGICAL_FIELDS:
            if vb.get(k) != va.get(k):
                print(f"FIELD_DIFF {k}:\n  before={vb.get(k)!r}\n  after ={va.get(k)!r}", file=sys.stderr)
        print("LOGICAL_DIGEST_MISMATCH", file=sys.stderr)
        return 1

    print("LOGICAL_DIGESTS_MATCH: executable/argv/cwd/checkpoint/env/port/served-model/launcher identical")
    return 0


if __name__ == "__main__":
    sys.exit(main())
