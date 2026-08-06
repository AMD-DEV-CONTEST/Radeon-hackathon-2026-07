#!/usr/bin/env python3
"""Audit Mantis LeRobot metadata before ACT, SmolVLA, or PI0.5 training."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from mantis_rocm_bridge.lerobot_dataset_gate import audit_mantis_dataset_metadata


ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("dataset_root", type=Path)
    parser.add_argument(
        "--contract",
        type=Path,
        default=ROOT / "configs/mantis-lerobot-interface-v1.json",
    )
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    receipt = audit_mantis_dataset_metadata(args.dataset_root, args.contract)
    rendered = json.dumps(receipt, indent=2, sort_keys=True) + "\n"
    if args.output is not None:
        if args.output.exists():
            parser.error(f"refusing to overwrite output: {args.output}")
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    return 0 if receipt["dataset_metadata_gate_pass"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
