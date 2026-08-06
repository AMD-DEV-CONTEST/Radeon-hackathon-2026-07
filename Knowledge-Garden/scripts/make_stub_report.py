#!/usr/bin/env python3
"""make_stub_report.py — generate a schema-valid eval report (Todo 6).

Deterministic stub generator matching docs/report-schema.json (v1). Used by
run_model_eval.sh when a live model arm is unavailable, and by the routing
toolchain tests for adversarial decision coverage.

Usage:
  python scripts/make_stub_report.py --model <name> --out <path> \
      [--support F] [--unsupported F] [--coverage F] [--agreement F] \
      [--duplicate F] [--schema-validity F] [--fatal N]
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--support", type=float, default=0.0)
    ap.add_argument("--unsupported", type=float, default=0.0)
    ap.add_argument("--coverage", type=float, default=0.0)
    ap.add_argument("--agreement", type=float, default=0.0)
    ap.add_argument("--duplicate", type=float, default=0.0)
    ap.add_argument("--schema-validity", type=float, default=100.0)
    ap.add_argument("--fatal", type=int, default=0)
    args = ap.parse_args()

    fatal = [
        {"fixture": f"stub-fixture-{i}", "condition": "unparseable_json"}
        for i in range(args.fatal)
    ]
    report = {
        "report_schema_version": 1,
        "model": args.model,
        "metrics": {
            "source_support": round(args.support, 2),
            "unsupported_claim": round(args.unsupported, 2),
            "key_point_coverage": round(args.coverage, 2),
            "grading_agreement": round(args.agreement, 2),
            "duplicate": round(args.duplicate, 2),
            "schema_validity": round(args.schema_validity, 2),
        },
        "fatal_failures": fatal,
        "inputs": {"fixtures": 0, "manifest": "stub", "responses": "stub"},
        "environment": {"eval_time": "stub", "stub": True},
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(report, ensure_ascii=False, indent=2))
    print(f"STUB_OK: {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
