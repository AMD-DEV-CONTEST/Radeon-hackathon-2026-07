#!/usr/bin/env python3
"""Verify that a PI0.5 resume preserves the exact frozen training contract."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from parcel_sorter.mobile_pi05_research_protocol import (
    canonical_payload_sha256,
    file_sha256,
    validate_training_launch_audit,
)
from parcel_sorter.mobile_pi05_training_contract import (
    validate_pi05_training_contract,
)
from parcel_sorter.pi05_action_projection_adapter import (
    PI05_FULL_ACTION_PROJECTION_PROTOCOL,
)


def audit_resume(
    *,
    existing_contract_path: Path,
    proposed_contract_path: Path,
    existing_launch_audit_path: Path,
    proposed_launch_audit_path: Path,
    checkpoint: Path,
    checkpoint_step: int,
) -> dict[str, object]:
    existing = json.loads(existing_contract_path.read_text(encoding="utf-8"))
    proposed = json.loads(proposed_contract_path.read_text(encoding="utf-8"))
    for payload in (existing, proposed):
        validate_pi05_training_contract(
            payload,
            state_dim=int(payload.get("state_dimension", 0)),
            action_dim=int(payload.get("action_dimension", 0)),
            chunk_size=int(payload.get("action_chunk_size", 0)),
            required_action_projection_protocol=PI05_FULL_ACTION_PROJECTION_PROTOCOL,
        )
        if payload.get("training_role") != "candidate":
            raise ValueError("resume requires a formal candidate training contract")
    if existing.get("contract_sha256") != proposed.get("contract_sha256"):
        raise ValueError("resume would change the frozen training contract")
    for contract, audit_path in (
        (existing, existing_launch_audit_path),
        (proposed, proposed_launch_audit_path),
    ):
        launch_audit = json.loads(audit_path.read_text(encoding="utf-8"))
        validate_training_launch_audit(
            launch_audit,
            expected_training_role="candidate",
            dataset_manifest_sha256=str(contract["dataset_manifest_sha256"]),
        )
        if launch_audit.get("audit_sha256") != contract.get(
            "training_launch_audit_sha256"
        ):
            raise ValueError("resume launch audit does not match its training contract")
    if checkpoint_step < 1 or checkpoint_step > int(
        existing.get("requested_training_steps", 0)
    ):
        raise ValueError("resume checkpoint is outside the contracted training budget")
    resolved_checkpoint = checkpoint.resolve()
    if resolved_checkpoint.name != "pretrained_model":
        raise ValueError("resume checkpoint must be a pretrained_model directory")
    if resolved_checkpoint.parent.name != f"{checkpoint_step:06d}":
        raise ValueError("resume checkpoint path does not match its declared step")
    for name in ("adapter_model.safetensors", "train_config.json"):
        if not (resolved_checkpoint / name).is_file():
            raise ValueError(f"resume checkpoint artifact is missing: {name}")

    payload: dict[str, object] = {
        "schema_version": 1,
        "protocol": "pi05-exact-contract-resume-audit-v1",
        "status": "passed",
        "checkpoint": str(resolved_checkpoint),
        "checkpoint_step": checkpoint_step,
        "training_contract_sha256": existing["contract_sha256"],
        "training_contract_file_sha256": file_sha256(existing_contract_path),
        "proposed_contract_file_sha256": file_sha256(proposed_contract_path),
        "existing_launch_audit_file_sha256": file_sha256(
            existing_launch_audit_path
        ),
        "proposed_launch_audit_file_sha256": file_sha256(
            proposed_launch_audit_path
        ),
        "requested_training_steps": existing["requested_training_steps"],
        "scheduler_warmup_steps": existing["scheduler_warmup_steps"],
        "scheduler_decay_steps": existing["scheduler_decay_steps"],
        "training_launch_audit_sha256": existing["training_launch_audit_sha256"],
        "tiny_overfit_gate_sha256": existing["tiny_overfit_gate_sha256"],
    }
    payload["audit_sha256"] = canonical_payload_sha256(
        payload, hash_field="audit_sha256"
    )
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--existing-contract", type=Path, required=True)
    parser.add_argument("--proposed-contract", type=Path, required=True)
    parser.add_argument("--existing-launch-audit", type=Path, required=True)
    parser.add_argument("--proposed-launch-audit", type=Path, required=True)
    parser.add_argument("--checkpoint", type=Path, required=True)
    parser.add_argument("--checkpoint-step", type=int, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        payload = audit_resume(
            existing_contract_path=args.existing_contract,
            proposed_contract_path=args.proposed_contract,
            existing_launch_audit_path=args.existing_launch_audit,
            proposed_launch_audit_path=args.proposed_launch_audit,
            checkpoint=args.checkpoint,
            checkpoint_step=args.checkpoint_step,
        )
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        parser.error(str(exc))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
