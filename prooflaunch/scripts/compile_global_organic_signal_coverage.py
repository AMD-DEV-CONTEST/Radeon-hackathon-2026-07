#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path

from prooflaunch_remix.files import atomic_write_text
from prooflaunch_remix.gtm_organic_signal_sampling_standard import (
    compile_global_organic_signal_coverage_receipt,
)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--standard", required=True, type=Path)
    parser.add_argument("--signal-pack", required=True, action="append", type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    standard = json.loads(args.standard.read_text(encoding="utf-8"))
    packs = [json.loads(path.read_text(encoding="utf-8")) for path in args.signal_pack]
    result = compile_global_organic_signal_coverage_receipt(standard, packs)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_text(args.output, json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    print(json.dumps({
        "output": str(args.output),
        "qualified_segment_market_cells": result["qualified_segment_market_cell_count"],
        "observed_segment_market_cells": result["observed_segment_market_cell_count"],
        "target_segment_market_cells": result["target_segment_market_cell_count"],
        "qualified_platform_market_lanes": result["qualified_platform_market_lane_count"],
        "observed_platform_market_lanes": result["observed_platform_market_lane_count"],
        "target_platform_market_lanes": result["target_platform_market_lane_count"],
        "global_coverage_complete": result["global_coverage_complete"],
        "content_sha256": result["content_sha256"],
    }, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
