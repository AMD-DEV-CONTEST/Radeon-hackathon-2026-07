#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path

from prooflaunch_remix.files import atomic_write_text
from prooflaunch_remix.gtm_organic_signal_sampling_standard import (
    build_global_organic_signal_sampling_standard,
    verify_global_organic_signal_sampling_standard,
)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    result = build_global_organic_signal_sampling_standard()
    verify_global_organic_signal_sampling_standard(result)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_text(args.output, json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    print(json.dumps({
        "output": str(args.output),
        "segment_market_cells": result["coverage_truth"]["segment_market_cell_count"],
        "platform_market_lanes": result["coverage_truth"]["platform_market_lane_count"],
        "content_sha256": result["content_sha256"],
    }, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
