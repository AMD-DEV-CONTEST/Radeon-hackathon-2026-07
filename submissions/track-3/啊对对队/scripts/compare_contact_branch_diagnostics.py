#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys
from typing import Any, Mapping


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from parcel_sorter.contact_branch import (
    compare_contact_branch_events,
    summarize_contact_branch_events,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Compare preregistered lightweight and mass-aware contact traces."
    )
    parser.add_argument("--reference", type=Path, required=True)
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _load(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("status") != "complete" or len(payload.get("rollouts", ())) != 1:
        raise ValueError(f"{path} must contain one complete rollout")
    return payload


def _events(payload: Mapping[str, Any]) -> list[dict[str, Any]]:
    return list(
        payload["rollouts"][0]["report"]["safety_summary"][
            "contact_branch_events"
        ]
    )


def _validate_pair(reference: Mapping[str, Any], candidate: Mapping[str, Any]) -> None:
    fixed_fields = (
        "backend",
        "config",
        "episode",
        "profile",
        "repeat_count",
        "sample",
        "tested_candidate_ids",
    )
    for field in fixed_fields:
        if reference[field] != candidate[field]:
            raise ValueError(f"comparison field differs: {field}")
    if reference["repeat_count"] != 1:
        raise ValueError("comparison requires exactly one rollout per condition")
    left = reference["contract"]
    right = candidate["contract"]
    physical_model_fields = {
        "parcel_gripper_adapter_inertia_enabled",
        "parcel_gripper_adapter_inertia_model",
        "parcel_gripper_adapter_mass_per_finger_kg",
    }
    for field in sorted(set(left) | set(right)):
        if field not in physical_model_fields and left.get(field) != right.get(field):
            raise ValueError(f"comparison contract differs: {field}")
    if not left["parcel_gripper_adapter_enabled"] or not right[
        "parcel_gripper_adapter_enabled"
    ]:
        raise ValueError("both conditions must use adapter geometry")
    if not left["contact_branch_telemetry_enabled"] or not right[
        "contact_branch_telemetry_enabled"
    ]:
        raise ValueError("both conditions must contain contact-branch telemetry")
    if left["parcel_gripper_adapter_inertia_enabled"]:
        raise ValueError("reference must be the stock-inertia ablation")
    if not right["parcel_gripper_adapter_inertia_enabled"]:
        raise ValueError("candidate must use combined adapter inertia")


def run(args: argparse.Namespace) -> dict[str, Any]:
    reference_path = args.reference.resolve()
    candidate_path = args.candidate.resolve()
    reference = _load(reference_path)
    candidate = _load(candidate_path)
    _validate_pair(reference, candidate)
    comparison = compare_contact_branch_events(
        reference_events := _events(reference),
        candidate_events := _events(candidate),
        force_difference_n=1.0,
        finger_position_difference_m=0.0001,
        finger_velocity_difference_m_s=0.01,
        finger_force_difference_n=1.0,
    )
    force_abort_n = float(reference["contract"]["force_abort_n"])
    return {
        "schema_version": "1.0",
        "study_type": "preregistered_parcel_adapter_contact_branch_comparison",
        "claim_boundary": (
            "One observed deterministic episode and one rollout per physical "
            "model; mechanism evidence only."
        ),
        "fixed_case": {
            "episode": reference["episode"],
            "profile": reference["profile"],
            "candidate_id": reference["tested_candidate_ids"][0],
            "force_abort_n": reference["contract"]["force_abort_n"],
            "contact_branch_control_window": reference["contract"][
                "contact_branch_control_window"
            ],
        },
        "reference": {
            "path": str(reference_path),
            "bytes": reference_path.stat().st_size,
            "sha256": _sha256(reference_path),
            "inertia_model": reference["contract"][
                "parcel_gripper_adapter_inertia_model"
            ],
            "outcome": {
                key: reference["rollouts"][0][key]
                for key in (
                    "success",
                    "safety_aborted",
                    "force_abort_frame",
                    "dropped",
                    "max_contact_force_n",
                    "duration_seconds",
                )
            },
            "contact_branch_summary": summarize_contact_branch_events(
                reference_events,
                force_abort_n,
            ),
        },
        "candidate": {
            "path": str(candidate_path),
            "bytes": candidate_path.stat().st_size,
            "sha256": _sha256(candidate_path),
            "inertia_model": candidate["contract"][
                "parcel_gripper_adapter_inertia_model"
            ],
            "outcome": {
                key: candidate["rollouts"][0][key]
                for key in (
                    "success",
                    "safety_aborted",
                    "force_abort_frame",
                    "dropped",
                    "max_contact_force_n",
                    "duration_seconds",
                )
            },
            "contact_branch_summary": summarize_contact_branch_events(
                candidate_events,
                force_abort_n,
            ),
        },
        "comparison": comparison,
        "forbidden_adaptation_observed": False,
        "holdout_opened": False,
        "new_episode_opened": False,
    }


def main() -> int:
    args = parse_args()
    payload = run(args)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "output": str(args.output),
                "reference_outcome": payload["reference"]["outcome"],
                "candidate_outcome": payload["candidate"]["outcome"],
                "first_divergence": payload["comparison"]["first_divergence"],
            },
            allow_nan=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
