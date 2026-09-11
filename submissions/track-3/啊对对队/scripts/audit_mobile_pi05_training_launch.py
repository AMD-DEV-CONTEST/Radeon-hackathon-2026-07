#!/usr/bin/env python3
"""Fail closed before any PI0.5 ROCm trainer process can start."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from parcel_sorter.mobile_pi05_research_protocol import (
    PI05_TASK_STAGES,
    PI05_TINY_OVERFIT_ROLE,
    PI05_TRAINING_ROLES,
    build_training_launch_audit,
    file_sha256,
    independent_sources_by_mode,
    validate_stage_panel,
)
from parcel_sorter.mobile_pi05_contract import PI05_GRASP_MODES


def _manifest_path(root: Path) -> Path:
    matches = [
        path
        for path in (
            root / "PI05_RESIDUAL_DATASET_MANIFEST.json",
            root / "PI05_ABSOLUTE_DATASET_MANIFEST.json",
            root / "PI05_INCREMENTAL_DATASET_MANIFEST.json",
        )
        if path.is_file()
    ]
    if len(matches) != 1:
        raise ValueError("dataset must contain exactly one PI0.5 manifest")
    return matches[0]


def validate_tiny_overfit_dataset_binding(
    dataset_root: Path,
    manifest: dict,
    panel: dict,
) -> None:
    """Reject mislabeled full datasets at the tiny-overfit training boundary."""

    validate_stage_panel(panel, expected_role=PI05_TINY_OVERFIT_ROLE)
    info = json.loads((dataset_root / "meta/info.json").read_text(encoding="utf-8"))
    expected = len(PI05_GRASP_MODES) * len(PI05_TASK_STAGES)
    if manifest.get("dataset_role") != "tiny_overfit_contract_only":
        raise ValueError("tiny-overfit training requires a contract-only dataset")
    if manifest.get("performance_data") is not False:
        raise ValueError("tiny-overfit dataset must be marked non-performance data")
    if int(info.get("total_frames", -1)) != expected:
        raise ValueError(f"tiny-overfit dataset must contain exactly {expected} frames")
    if int(info.get("total_episodes", -1)) != expected:
        raise ValueError(
            f"tiny-overfit dataset must contain exactly {expected} one-frame episodes"
        )
    if panel.get("dataset_root") != str(dataset_root.resolve()):
        raise ValueError("tiny-overfit panel is not bound to the training dataset")
    observations = list(panel.get("observations") or ())
    if len(observations) != expected:
        raise ValueError("tiny-overfit panel must contain exactly one row per mode-stage cell")
    if [int(item["dataset_index"]) for item in observations] != list(range(expected)):
        raise ValueError("tiny-overfit panel indices must cover the complete 18-row dataset")
    if [int(item["episode_index"]) for item in observations] != list(range(expected)):
        raise ValueError("every tiny-overfit row must be an independent one-frame episode")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--training-role", choices=PI05_TRAINING_ROLES, required=True)
    parser.add_argument("--dataset-root", type=Path, required=True)
    parser.add_argument("--action-contract", required=True)
    parser.add_argument("--steps", type=int, required=True)
    parser.add_argument("--scheduler-warmup-steps", type=int, required=True)
    parser.add_argument("--scheduler-decay-steps", type=int, required=True)
    parser.add_argument("--stage-panel", type=Path)
    parser.add_argument("--action-thresholds", type=Path)
    parser.add_argument("--tiny-overfit-gate", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    try:
        manifest_path = _manifest_path(args.dataset_root.resolve())
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest_action_contract = str(manifest.get("action_contract") or "residual_v1")
        if manifest_action_contract != args.action_contract:
            raise ValueError("requested action contract does not match the dataset")
        source_counts = None
        stage_panel = (
            json.loads(args.stage_panel.read_text(encoding="utf-8"))
            if args.stage_panel is not None
            else None
        )
        if args.training_role == "tiny_overfit":
            if stage_panel is None:
                raise ValueError("tiny-overfit training requires a stage panel")
            validate_tiny_overfit_dataset_binding(
                args.dataset_root.resolve(), manifest, stage_panel
            )
        if args.training_role == "candidate":
            verified_entries = [
                item
                for item in manifest.get("episode_manifests") or ()
                if item.get("seed_role")
                == "verified_successful_absolute_action_supervision"
            ]
            sources = independent_sources_by_mode(verified_entries)
            source_counts = {mode: len(values) for mode, values in sources.items()}
        payload = build_training_launch_audit(
            training_role=args.training_role,
            action_contract=args.action_contract,
            dataset_manifest_sha256=file_sha256(manifest_path),
            requested_training_steps=args.steps,
            scheduler_warmup_steps=args.scheduler_warmup_steps,
            scheduler_decay_steps=args.scheduler_decay_steps,
            stage_panel=stage_panel,
            action_thresholds=(
                json.loads(args.action_thresholds.read_text(encoding="utf-8"))
                if args.action_thresholds is not None
                else None
            ),
            tiny_overfit_gate=(
                json.loads(args.tiny_overfit_gate.read_text(encoding="utf-8"))
                if args.tiny_overfit_gate is not None
                else None
            ),
            independent_source_counts=source_counts,
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
