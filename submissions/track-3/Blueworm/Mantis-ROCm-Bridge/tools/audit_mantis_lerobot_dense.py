#!/usr/bin/env python3
"""Audit dense Mantis parquet frames and strict expert episode outcomes."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from mantis_rocm_bridge.contracts import load_json
from mantis_rocm_bridge.lerobot_dense_gate import audit_mantis_dense_dataset


ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("dataset_root", type=Path)
    parser.add_argument("--metadata-receipt", type=Path, required=True)
    parser.add_argument("--episode-outcomes", type=Path, required=True)
    parser.add_argument(
        "--gate",
        type=Path,
        default=ROOT / "configs/dense-dataset-gate-v1.json",
    )
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    receipt = audit_mantis_dense_dataset(
        dataset_root=args.dataset_root,
        metadata_receipt=load_json(args.metadata_receipt),
        outcomes=load_json(args.episode_outcomes),
        gate_path=args.gate,
    )
    rendered = json.dumps(receipt, indent=2, sort_keys=True) + "\n"
    if args.output is not None:
        if args.output.exists():
            parser.error(f"refusing to overwrite output: {args.output}")
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    return 0 if receipt["dense_demonstration_gate_pass"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
