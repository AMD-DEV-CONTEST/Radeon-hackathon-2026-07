#!/usr/bin/env python3
"""Collect the frozen PI0.5 panel without executing or storing policy actions."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys

from parcel_sorter.mobile_pi05_heldout_capture import (
    canonical_payload_sha256,
    file_sha256,
    validate_pi05_heldout_observation,
    validate_pi05_heldout_collection,
    validate_pi05_workspace_block,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--panel", type=Path, required=True)
    parser.add_argument("--workspace-block", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--backend", choices=("rocm", "cuda"), default="rocm")
    parser.add_argument("--image-size", type=int, default=224)
    args = parser.parse_args()
    if args.output.exists():
        raise FileExistsError(f"held-out output already exists: {args.output}")

    panel = json.loads(args.panel.read_text(encoding="utf-8"))
    block = json.loads(args.workspace_block.read_text(encoding="utf-8"))
    block_audit = validate_pi05_workspace_block(block, panel)
    positions = {
        str(item["episode_id"]): float(item["pedestal_x_m"])
        for item in block["assignments"]
    }
    observations = args.output / "observations"
    work = args.output / "work"
    observations.mkdir(parents=True)
    evaluator = Path(__file__).with_name("evaluate_mobile_suction_lift_rocm.py")
    captures = []
    for episode in panel["episodes"]:
        episode_id = str(episode["episode_id"])
        destination = observations / f"{episode_id}.npz"
        command = [
            sys.executable,
            str(evaluator),
            "--backend",
            args.backend,
            "--output",
            str(work / episode_id),
            "--image-size",
            str(args.image_size),
            "--record-initial-observation",
            str(destination),
            "--initial-observation-only",
            "--observation-episode-id",
            episode_id,
            "--pedestal-x-m",
            str(positions[episode_id]),
            "--parcel-profile",
            str(episode["profile"]),
            "--parcel-shape",
            str(episode["shape"]),
            "--parcel-orientation",
            str(episode["orientation_mode"]),
            "--parcel-yaw-rad",
            str(episode["yaw_rad"]),
            "--grasp-mode",
            str(episode["grasp_mode"]),
            "--minimum-sealed-cups",
            str(episode["minimum_sealed_cups"]),
            "--parcel-size-m",
            *(str(value) for value in episode["size_m"]),
            "--parcel-mass-kg",
            str(episode["mass_kg"]),
            "--parcel-friction",
            str(episode["friction"]),
            "--parcel-offset-m",
            *(str(value) for value in episode["offset_m"]),
            "--retry-index",
            str(episode["retry_index"]),
            "--task-text",
            str(episode["task_text"]),
        ]
        if episode.get("cooperative_cradle"):
            command.append("--cooperative-cradle")
        subprocess.run(command, check=True)
        sidecar = destination.with_suffix(".json")
        audit = validate_pi05_heldout_observation(destination, sidecar)
        captures.append(
            {
                "episode_id": episode_id,
                "observation": str(destination.relative_to(args.output)),
                "metadata": str(sidecar.relative_to(args.output)),
                "observation_sha256": audit["observation_sha256"],
            }
        )

    manifest = {
        "schema_version": 1,
        "protocol": "pi05-heldout-observation-collection-v1",
        "split": "heldout_observation_do_not_train",
        "panel": str(args.panel.resolve()),
        "panel_sha256": canonical_payload_sha256(panel),
        "workspace_block": str(args.workspace_block.resolve()),
        "workspace_block_sha256": canonical_payload_sha256(block),
        "workspace_block_audit": block_audit,
        "episodes": len(captures),
        "captures": captures,
        "contains_actions": False,
        "contains_recovery": False,
        "contains_outcome": False,
        "claim_boundary": (
            "Initial held-out observations only; this collection is forbidden from "
            "training and does not measure model capability."
        ),
    }
    manifest_path = args.output / "PI05_HELDOUT_OBSERVATION_MANIFEST.json"
    manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    collection_audit = validate_pi05_heldout_collection(
        args.output, panel, block
    )
    print(
        json.dumps(
            {
                "manifest": str(manifest_path),
                "manifest_sha256": file_sha256(manifest_path),
                "collection_audit": collection_audit,
                **manifest,
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
