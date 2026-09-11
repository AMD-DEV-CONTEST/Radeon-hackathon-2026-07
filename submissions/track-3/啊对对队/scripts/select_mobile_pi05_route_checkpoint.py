#!/usr/bin/env python3
"""Freeze one PI0.5 checkpoint after the development stage-action screen."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
from typing import Any

from parcel_sorter.mobile_pi05_training_contract import validate_pi05_training_contract
from parcel_sorter.pi05_action_projection_adapter import (
    PI05_FULL_ACTION_PROJECTION_PROTOCOL,
)


SCREEN_PROTOCOL = "pi05-stage-complete-action-screen-v3"
PANEL_ROLE = "heldout_action_development"
SELECTION_PROTOCOL = "pi05-earliest-passing-stage-action-checkpoint-selection-v2"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _is_sha256(value: str) -> bool:
    return len(value) == 64 and all(
        character in "0123456789abcdef" for character in value
    )


def _checkpoint_step(checkpoint: Path) -> int:
    for part in reversed(checkpoint.parts):
        if re.fullmatch(r"[0-9]{6}", part):
            return int(part)
    raise ValueError(f"checkpoint path has no six-digit training step: {checkpoint}")


def _read_screen(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("protocol") != SCREEN_PROTOCOL:
        raise ValueError(f"unexpected screen protocol: {path}")
    if payload.get("observation_panel_role") != PANEL_ROLE:
        raise ValueError(f"screen is not development-only: {path}")
    return payload


def _find_training_contract(checkpoint: Path) -> Path:
    for directory in (checkpoint, *checkpoint.parents):
        candidate = directory / "PI05_TRAINING_CONTRACT.json"
        if candidate.is_file():
            return candidate
    raise ValueError(f"selected checkpoint training contract is missing: {checkpoint}")


def select_checkpoint(
    screen_paths: list[Path],
    *,
    expected_count: int,
) -> dict[str, Any]:
    if len(screen_paths) != expected_count:
        raise ValueError(
            f"expected {expected_count} stage-action screens, received {len(screen_paths)}"
        )

    candidates: list[dict[str, Any]] = []
    datasets: set[str] = set()
    seed_panels: set[tuple[int, ...]] = set()
    panel_hashes: set[str] = set()
    threshold_hashes: set[str] = set()
    manifest_hashes: set[str] = set()
    training_contract_paths: set[Path] = set()
    steps: set[int] = set()
    for path in screen_paths:
        payload = _read_screen(path)
        checkpoint = Path(str(payload.get("checkpoint", ""))).resolve()
        step = _checkpoint_step(checkpoint)
        if step in steps:
            raise ValueError(f"duplicate checkpoint step: {step}")
        steps.add(step)
        training_contract = _find_training_contract(checkpoint).resolve()
        training_contract_paths.add(training_contract)
        metrics = payload.get("metrics") or {}
        passed = (
            payload.get("status") == "passed"
            and not payload.get("errors")
            and payload.get("action_contract") == "pi05_absolute_v1"
            and payload.get("action_fidelity_required") is True
            and payload.get("deployment_calibrated_thresholds") is True
            and int(payload.get("mode_stage_cells", 0)) == 18
            and int(payload.get("routing_error_count", -1)) == 0
            and int(payload.get("action_fidelity_error_count", -1)) == 0
            and int(payload.get("structural_error_count", -1)) == 0
            and int(metrics.get("probes", 0)) >= 18
            and int(metrics.get("correct_probes", -1))
            == int(metrics.get("probes", 0))
            and float(metrics.get("probe_accuracy", 0.0)) == 1.0
        )
        datasets.add(str(payload.get("dataset", "")))
        seed_panels.add(tuple(int(seed) for seed in payload.get("sample_seeds", ())))
        panel_hashes.add(str(payload.get("stage_panel_sha256") or ""))
        threshold_hashes.add(str(payload.get("action_thresholds_sha256") or ""))
        manifest_hashes.add(str(payload.get("dataset_manifest_sha256") or ""))
        candidates.append(
            {
                "step": step,
                "checkpoint": str(checkpoint),
                "screen": str(path.resolve()),
                "screen_sha256": _sha256(path),
                "training_contract": str(training_contract),
                "status": str(payload.get("status")),
                "stage_action_gate_passed": passed,
                "probe_accuracy": float(metrics.get("probe_accuracy", 0.0)),
                "routing_error_count": int(payload.get("routing_error_count", -1)),
                "action_fidelity_error_count": int(
                    payload.get("action_fidelity_error_count", -1)
                ),
                "structural_error_count": int(
                    payload.get("structural_error_count", -1)
                ),
            }
        )

    if len(datasets) != 1 or "" in datasets:
        raise ValueError("stage-action screens do not use one frozen dataset")
    if len(seed_panels) != 1 or not next(iter(seed_panels)):
        raise ValueError("stage-action screens do not use one non-empty seed panel")
    for label, values in (
        ("stage panel", panel_hashes),
        ("action thresholds", threshold_hashes),
        ("dataset manifest", manifest_hashes),
    ):
        if len(values) != 1 or not _is_sha256(next(iter(values))):
            raise ValueError(f"screens do not share one frozen {label}")
    if len(training_contract_paths) != 1:
        raise ValueError("stage-action screens do not belong to one training run")
    passing = [item for item in candidates if item["stage_action_gate_passed"]]
    if not passing:
        raise ValueError("no checkpoint passed the development stage-action gate")

    selected = min(passing, key=lambda item: int(item["step"]))
    checkpoint = Path(str(selected["checkpoint"]))
    artifacts = {}
    for name in (
        "adapter_model.safetensors",
        "adapter_config.json",
        "config.json",
    ):
        path = checkpoint / name
        if not path.is_file():
            raise ValueError(f"selected checkpoint artifact is missing: {path}")
        artifacts[name] = _sha256(path)
    training_contract = next(iter(training_contract_paths))
    training_payload = json.loads(training_contract.read_text(encoding="utf-8"))
    validate_pi05_training_contract(
        training_payload,
        state_dim=int(training_payload.get("state_dimension", 0)),
        action_dim=int(training_payload.get("action_dimension", 0)),
        chunk_size=int(training_payload.get("action_chunk_size", 0)),
        required_action_projection_protocol=PI05_FULL_ACTION_PROJECTION_PROTOCOL,
    )
    if training_payload.get("training_role") != "candidate":
        raise ValueError("selected checkpoint is not from a candidate training run")
    if not training_payload.get("training_launch_audit_sha256"):
        raise ValueError("selected checkpoint lacks a passed training-launch audit")
    if training_payload.get("dataset_manifest_sha256") != next(iter(manifest_hashes)):
        raise ValueError("training contract and development screen dataset mismatch")
    if int(training_payload.get("requested_training_steps", 0)) < max(steps):
        raise ValueError("checkpoint panel exceeds the contracted training budget")

    return {
        "schema_version": 1,
        "protocol": SELECTION_PROTOCOL,
        "status": "selected",
        "selection_panel_role": PANEL_ROLE,
        "checkpoint_selection_rule": (
            "minimum training step among checkpoints with zero routing, action-fidelity, "
            "and structural errors on one frozen stage-complete development panel"
        ),
        "heldout_observations_accessed": False,
        "closed_loop_results_accessed": False,
        "dataset": next(iter(datasets)),
        "sample_seeds": list(next(iter(seed_panels))),
        "stage_panel_sha256": next(iter(panel_hashes)),
        "action_thresholds_sha256": next(iter(threshold_hashes)),
        "dataset_manifest_sha256": next(iter(manifest_hashes)),
        "candidates": sorted(candidates, key=lambda item: int(item["step"])),
        "selected_step": int(selected["step"]),
        "selected_checkpoint": str(checkpoint),
        "selected_screen": str(selected["screen"]),
        "selected_screen_sha256": str(selected["screen_sha256"]),
        "selected_checkpoint_artifact_sha256": artifacts,
        "training_contract": str(training_contract.resolve()),
        "training_contract_sha256": _sha256(training_contract),
        "next_gate": "three-episode-pure-vla-development-closed-loop",
        "claim_boundary": (
            "Deterministic development checkpoint selection only; this is not "
            "held-out generalization or closed-loop success evidence."
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--screen", action="append", type=Path, required=True)
    parser.add_argument("--expected-count", type=int, default=4)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        payload = select_checkpoint(
            [path.resolve() for path in args.screen],
            expected_count=args.expected_count,
        )
    except ValueError as exc:
        parser.error(str(exc))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    temporary = args.output.with_name(f".{args.output.name}.tmp")
    temporary.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    temporary.replace(args.output)
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
