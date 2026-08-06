#!/usr/bin/env python3
"""validate_eval_report.py — validate an eval report JSON against docs/report-schema.json.

Usage:
  python scripts/validate_eval_report.py <report.json>
Exit 0 when valid, 1 otherwise.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCHEMA = ROOT / "docs" / "report-schema.json"


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: validate_eval_report.py <report.json>", file=sys.stderr)
        return 2
    report_path = Path(sys.argv[1])
    if not report_path.exists():
        print(f"report not found: {report_path}", file=sys.stderr)
        return 1
    report = json.loads(report_path.read_text())
    schema = json.loads(SCHEMA.read_text())
    try:
        import jsonschema
        jsonschema.validate(report, schema)
    except ImportError:
        # structural fallback: required keys + report_schema_version
        for key in ("report_schema_version", "model", "metrics",
                    "fatal_failures", "inputs", "created_at"):
            if key not in report:
                print(f"missing key: {key}", file=sys.stderr)
                return 1
        if report["report_schema_version"] != 1:
            print("report_schema_version must be 1", file=sys.stderr)
            return 1
    except Exception as e:  # noqa: BLE001
        print(f"REPORT_SCHEMA_FAIL: {e}", file=sys.stderr)
        return 1
    print(f"REPORT_OK: {report_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
