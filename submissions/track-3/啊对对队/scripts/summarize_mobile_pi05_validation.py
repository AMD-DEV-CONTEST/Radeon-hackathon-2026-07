#!/usr/bin/env python3
"""Report frozen PI0.5 success, routing, safety, and long-run ROCm metrics."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from parcel_sorter.mobile_pi05_validation import (
    summarize_pi05_frozen_validation,
    summarize_pi05_long_run,
)


def _read(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--design", type=Path, required=True)
    parser.add_argument("--campaign-audit", type=Path, required=True)
    parser.add_argument("--telemetry-summary", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    design = _read(args.design)
    audit = _read(args.campaign_audit)
    telemetry = _read(args.telemetry_summary) if args.telemetry_summary else None
    if design.get("protocol") == "pi05-pure-vla-two-cycle-long-run-v1":
        result = summarize_pi05_long_run(design, audit, telemetry=telemetry)
    else:
        result = summarize_pi05_frozen_validation(design, audit, telemetry=telemetry)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps(result, sort_keys=True))
    return 0 if result["status"] == "passed" else 2


if __name__ == "__main__":
    raise SystemExit(main())
