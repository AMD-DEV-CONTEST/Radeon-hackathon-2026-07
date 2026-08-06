#!/usr/bin/env python3
"""validate_producer_registry.py — validate docs/producer-registry.json (Todo 11).

Checks:
  - schema-valid against docs/producer-registry.schema.json
  - exactly ONE artifact path per row; no duplicates
  - every owner is a real Todo ID (1-11)
  - every expected-inventory path (docs/expected-producer-artifacts.json) has a
    matching registry row
  - len(rows) == 51 == len(unique artifact paths)

DELETION PROOF: removing any expected artifact row must make validation fail
naming that artifact — asserted by test_final_infra.py via a tamper loop.

Usage:
  python scripts/validate_producer_registry.py --registry docs/producer-registry.json \
      --inventory docs/expected-producer-artifacts.json
Exit 0 when valid, 1 otherwise.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EXPECTED_COUNT = 51


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--registry", required=True)
    ap.add_argument("--inventory", required=True)
    args = ap.parse_args()

    registry = json.loads(Path(args.registry).read_text())
    inventory = json.loads(Path(args.inventory).read_text())
    schema = json.loads((ROOT / "docs" / "producer-registry.schema.json").read_text())

    try:
        import jsonschema
        jsonschema.validate(registry, schema)
    except Exception as e:  # noqa: BLE001
        print(f"REGISTRY_SCHEMA_FAIL: {e}", file=sys.stderr)
        return 1

    rows = registry.get("rows", [])
    paths = [r.get("artifact", "") for r in rows]

    valid_todos = set(range(1, 12))
    for r in rows:
        if r.get("owner") not in valid_todos:
            print(f"REGISTRY_BAD_OWNER: {r.get('artifact')} owner={r.get('owner')}", file=sys.stderr)
            return 1

    # DELETION PROOF FIRST: report missing expected artifacts BEFORE the count
    # check, so removing any expected row fails validation NAMING that artifact.
    expected = {a["path"] for a in inventory.get("artifacts", [])}
    registered = set(paths)
    missing = expected - registered
    if missing:
        for m in sorted(missing):
            print(f"REGISTRY_MISSING_ARTIFACT: {m}", file=sys.stderr)
        return 1
    extra = registered - expected
    if extra:
        print(f"REGISTRY_UNEXPECTED: {sorted(extra)}", file=sys.stderr)
        return 1

    if len(rows) != EXPECTED_COUNT:
        print(f"REGISTRY_COUNT_FAIL: rows={len(rows)} expected={EXPECTED_COUNT}", file=sys.stderr)
        return 1
    if len(set(paths)) != EXPECTED_COUNT:
        dup = [p for p in set(paths) if paths.count(p) > 1]
        print(f"REGISTRY_DUPLICATE: {dup}", file=sys.stderr)
        return 1

    print(f"REGISTRY_OK: {EXPECTED_COUNT} rows, {len(set(paths))} unique artifacts, all owners valid")
    return 0


if __name__ == "__main__":
    sys.exit(main())
