#!/usr/bin/env python3
"""Convert one timestamped source-order dense TOPP trace into 30 Hz Mantis commands."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from mantis_rocm_bridge.adapters import reorder_source_state
from mantis_rocm_bridge.contracts import ContractError, load_json
from mantis_rocm_bridge.control_resampling import resample_topp_trace


ROOT = Path(__file__).resolve().parents[1]


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("input", type=Path, help="JSON with timestamps_s and positions")
    parser.add_argument("output", type=Path)
    parser.add_argument("--input-order", choices=("source", "target"), default="source")
    parser.add_argument("--port", type=Path, default=ROOT / "configs/mantis-port-config.json")
    parser.add_argument(
        "--resampling-contract",
        type=Path,
        default=ROOT / "configs/control-resampling-v1.json",
    )
    args = parser.parse_args()
    if args.output.exists():
        parser.error(f"output already exists and will not be overwritten: {args.output}")
    payload = load_json(args.input)
    port = load_json(args.port)
    contract = load_json(args.resampling_contract)
    positions = payload.get("positions")
    if not isinstance(positions, list):
        raise ContractError("input positions must be a list")
    if args.input_order == "source":
        positions = [reorder_source_state(row, port) for row in positions]
    result = resample_topp_trace(
        payload.get("timestamps_s", []),
        positions,
        target_hz=contract["target"]["control_hz"],
        velocity_limits_per_s=contract["target"]["velocity_limits_per_s"],
    )
    result["input_sha256"] = _sha256(args.input)
    result["resampling_contract_sha256"] = _sha256(args.resampling_contract)
    result["port_config_sha256"] = _sha256(args.port)
    result["input_order"] = args.input_order
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(args.output), "commands": len(result["positions"])}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
