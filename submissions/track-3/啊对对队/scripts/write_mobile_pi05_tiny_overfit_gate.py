#!/usr/bin/env python3
"""Write a passed tiny-overfit gate from complete PI0.5 contract evidence."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from parcel_sorter.mobile_pi05_research_protocol import (
    PI05_TINY_OVERFIT_GATE_PROTOCOL,
    PI05_TINY_OVERFIT_ROLE,
    canonical_payload_sha256,
    file_sha256,
    validate_action_thresholds,
    validate_stage_panel,
    validate_tiny_overfit_gate,
)
from parcel_sorter.mobile_pi05_training_contract import validate_pi05_training_contract
from parcel_sorter.pi05_action_projection_adapter import (
    PI05_FULL_ACTION_PROJECTION_PROTOCOL,
)


SCREEN_PROTOCOL = "pi05-stage-complete-action-screen-v3"


def build_gate(
    *,
    screen: dict,
    panel: dict,
    thresholds: dict,
    checkpoint: Path,
    training_contract: Path,
) -> dict:
    validate_stage_panel(panel, expected_role=PI05_TINY_OVERFIT_ROLE)
    validate_action_thresholds(thresholds, panel_role=PI05_TINY_OVERFIT_ROLE)
    if screen.get("protocol") != SCREEN_PROTOCOL:
        raise ValueError("unexpected tiny-overfit screen protocol")
    required = {
        "status": "passed",
        "observation_panel_role": PI05_TINY_OVERFIT_ROLE,
        "stage_panel_sha256": panel["panel_sha256"],
        "action_thresholds_sha256": thresholds["thresholds_sha256"],
        "dataset_manifest_sha256": panel["dataset_manifest_sha256"],
        "action_contract": "pi05_absolute_v1",
        "routing_error_count": 0,
        "action_fidelity_error_count": 0,
        "structural_error_count": 0,
        "mode_stage_cells": 18,
    }
    for field, value in required.items():
        if screen.get(field) != value:
            raise ValueError(f"tiny-overfit screen mismatch: {field}")
    if screen.get("errors"):
        raise ValueError("tiny-overfit screen contains errors")
    resolved_checkpoint = checkpoint.resolve()
    if Path(str(screen.get("checkpoint"))).resolve() != resolved_checkpoint:
        raise ValueError("tiny-overfit checkpoint does not match its screen")
    artifact = resolved_checkpoint / "adapter_model.safetensors"
    if not artifact.is_file() or not training_contract.is_file():
        raise ValueError("tiny-overfit checkpoint or training contract is missing")
    contract = json.loads(training_contract.read_text(encoding="utf-8"))
    validate_pi05_training_contract(
        contract,
        state_dim=int(contract.get("state_dimension", 0)),
        action_dim=int(contract.get("action_dimension", 0)),
        chunk_size=int(contract.get("action_chunk_size", 0)),
        required_action_projection_protocol=PI05_FULL_ACTION_PROJECTION_PROTOCOL,
    )
    if contract.get("training_role") != "tiny_overfit":
        raise ValueError("tiny-overfit checkpoint has the wrong training role")
    if contract.get("stage_panel_sha256") != panel["panel_sha256"]:
        raise ValueError("tiny-overfit training contract has the wrong panel")
    payload = {
        "schema_version": 1,
        "protocol": PI05_TINY_OVERFIT_GATE_PROTOCOL,
        "status": "passed",
        "panel_role": PI05_TINY_OVERFIT_ROLE,
        "action_contract": "absolute_v1",
        "routing_error_count": 0,
        "action_fidelity_error_count": 0,
        "structural_error_count": 0,
        "mode_stage_cells": 18,
        "panel_sha256": panel["panel_sha256"],
        "thresholds_sha256": thresholds["thresholds_sha256"],
        "checkpoint_sha256": file_sha256(artifact),
        "training_contract_sha256": file_sha256(training_contract),
        "dataset_manifest_sha256": panel["dataset_manifest_sha256"],
        "screen_sha256": file_sha256(Path(str(screen["screen_path"])))
        if screen.get("screen_path")
        else None,
    }
    payload["gate_sha256"] = canonical_payload_sha256(
        payload, hash_field="gate_sha256"
    )
    validate_tiny_overfit_gate(payload, action_contract="absolute_v1")
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--screen", type=Path, required=True)
    parser.add_argument("--panel", type=Path, required=True)
    parser.add_argument("--thresholds", type=Path, required=True)
    parser.add_argument("--checkpoint", type=Path, required=True)
    parser.add_argument("--training-contract", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    screen = json.loads(args.screen.read_text(encoding="utf-8"))
    screen["screen_path"] = str(args.screen.resolve())
    try:
        payload = build_gate(
            screen=screen,
            panel=json.loads(args.panel.read_text(encoding="utf-8")),
            thresholds=json.loads(args.thresholds.read_text(encoding="utf-8")),
            checkpoint=args.checkpoint,
            training_contract=args.training_contract,
        )
    except ValueError as exc:
        parser.error(str(exc))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
