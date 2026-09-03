#!/usr/bin/env python3
"""Build but never execute the frozen LeRobot ACT-on-ROCm command."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from mantis_rocm_bridge.contracts import load_json
from mantis_rocm_bridge.training_preflight import build_act_rocm_preflight


ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("dataset_root", type=Path)
    parser.add_argument("dataset_repo_id")
    parser.add_argument("output_dir", type=Path)
    parser.add_argument("--dataset-receipt", type=Path, required=True)
    parser.add_argument("--rocm-receipt", type=Path, required=True)
    parser.add_argument("--dense-receipt", type=Path)
    parser.add_argument("--scripted-g1-receipt", type=Path)
    parser.add_argument(
        "--training-contract",
        type=Path,
        default=ROOT / "configs/act-rocm-corrective-multiseed6-v2.json",
    )
    parser.add_argument(
        "--interface-contract",
        type=Path,
        default=ROOT / "configs/mantis-lerobot-interface-v1.json",
    )
    parser.add_argument(
        "--task-contract",
        type=Path,
        default=ROOT / "configs/task-pack-v1.json",
    )
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    receipt = build_act_rocm_preflight(
        dataset_root=args.dataset_root,
        dataset_repo_id=args.dataset_repo_id,
        output_dir=args.output_dir,
        training_contract_path=args.training_contract,
        interface_contract_path=args.interface_contract,
        task_contract_path=args.task_contract,
        dataset_receipt=load_json(args.dataset_receipt),
        rocm_receipt=load_json(args.rocm_receipt),
        dense_receipt=load_json(args.dense_receipt) if args.dense_receipt else None,
        scripted_g1_receipt=(
            load_json(args.scripted_g1_receipt) if args.scripted_g1_receipt else None
        ),
    )
    rendered = json.dumps(receipt, indent=2, sort_keys=True) + "\n"
    if args.output is not None:
        if args.output.exists():
            parser.error(f"refusing to overwrite output: {args.output}")
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    return 0 if receipt["training_authorized"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
