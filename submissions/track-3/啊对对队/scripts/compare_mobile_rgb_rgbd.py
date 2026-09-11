#!/usr/bin/env python3
"""Apply the paired RGB versus RGB-D SmolVLA offline selection gate."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from parcel_sorter.mobile_multimodal_ablation import compare_mobile_modalities


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rgb", type=Path, required=True)
    parser.add_argument("--rgbd", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = compare_mobile_modalities(
        json.loads(args.rgb.read_text(encoding="utf-8")),
        json.loads(args.rgbd.read_text(encoding="utf-8")),
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
