#!/usr/bin/env python3
"""Select the preregistered Radeon runtime from the compile ablation."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ablation-summary", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    summary = json.loads(args.ablation_summary.read_text(encoding="utf-8"))
    promoted = summary.get("promotion_status") == "passed"
    payload = {
        "schema_version": 1,
        "source": str(args.ablation_summary.resolve()),
        "source_protocol_id": summary.get("protocol_id"),
        "source_promotion_status": summary.get("promotion_status"),
        "compile": promoted,
        "runtime": "compile_true" if promoted else "compile_false",
        "selection_rule": "compile true only when every preregistered ablation gate passes",
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print("true" if promoted else "false")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
