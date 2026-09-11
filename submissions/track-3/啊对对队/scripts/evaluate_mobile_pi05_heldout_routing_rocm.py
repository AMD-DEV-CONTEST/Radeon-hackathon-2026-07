#!/usr/bin/env python3
"""Evaluate one frozen PI0.5 checkpoint on the one-shot held-out RGB-D panel."""

from __future__ import annotations

import argparse
from dataclasses import replace
import json
import math
from pathlib import Path
import statistics

from parcel_sorter.mobile_pi05_contract import (
    decode_pi05_context,
    select_pi05_mode_consensus,
)
from parcel_sorter.mobile_pi05_heldout_capture import (
    validate_pi05_heldout_collection,
    validate_pi05_heldout_observation,
)
from parcel_sorter.mobile_pi05_heldout_evaluation import (
    summarize_pi05_heldout_routing,
)
from parcel_sorter.mobile_vla_controller import MobileVLAHarnessController


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("checkpoint", type=Path)
    parser.add_argument("--collection", type=Path, required=True)
    parser.add_argument("--panel", type=Path, required=True)
    parser.add_argument("--workspace-block", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--samples", type=int, default=3)
    parser.add_argument("--seed", type=int, default=20260727)
    args = parser.parse_args()
    if args.samples < 3 or args.samples > 9 or args.samples % 2 == 0:
        parser.error("samples must be an odd integer in [3, 9]")
    if args.output.exists():
        raise FileExistsError(f"held-out evaluation already exists: {args.output}")

    import numpy as np
    import torch

    panel = json.loads(args.panel.read_text(encoding="utf-8"))
    block = json.loads(args.workspace_block.read_text(encoding="utf-8"))
    collection_audit = validate_pi05_heldout_collection(
        args.collection, panel, block
    )
    manifest = json.loads(
        (args.collection / "PI05_HELDOUT_OBSERVATION_MANIFEST.json").read_text(
            encoding="utf-8"
        )
    )
    captures = {str(item["episode_id"]): item for item in manifest["captures"]}
    controller = MobileVLAHarnessController(args.checkpoint, seed=args.seed)
    evaluations = []
    for panel_episode in panel["episodes"]:
        episode_id = str(panel_episode["episode_id"])
        capture = captures[episode_id]
        observation_path = args.collection / str(capture["observation"])
        metadata_path = args.collection / str(capture["metadata"])
        capture_audit = validate_pi05_heldout_observation(
            observation_path, metadata_path
        )
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        with np.load(observation_path, allow_pickle=False) as loaded:
            rgb = loaded["overhead_rgb"]
            depth = loaded["overhead_depth_m"]
            encoded_state = loaded["observation_state"].astype(float).tolist()
        expected_mode = str(panel_episode["grasp_mode"])
        context = replace(
            decode_pi05_context(encoded_state),
            grasp_mode=expected_mode,
            grasp_mode_conditioned=False,
        )
        expert_action = (
            0.0,
            0.0,
            0.0,
            *context.left_contact_anchor_m,
            1.0,
            0.0,
            0.0,
            0.0,
            1.0,
            *context.right_contact_anchor_m,
            1.0,
            0.0,
            0.0,
            0.0,
            1.0,
        )
        controller.reset_runtime_state()
        samples = []
        mode_logits = []
        for sample_index in range(args.samples):
            selected, telemetry = controller.select(
                rgb=rgb,
                depth=depth,
                state=encoded_state[:43],
                residual_context=context,
                task=str(metadata["task_text"]),
                expert_action=expert_action,
                stage="pregrasp",
                force_new_chunk=True,
            )
            projection = telemetry.get("residual_projection") or {}
            logits = tuple(float(value) for value in projection.get("mode_logits", ()))
            if len(logits) != 3:
                raise RuntimeError("PI0.5 did not return three held-out mode logits")
            residuals = tuple(
                tuple(float(value) for value in projection.get(key, (0.0, 0.0, 0.0)))
                for key in (
                    "base_residual",
                    "left_contact_residual_m",
                    "right_contact_residual_m",
                )
            )
            maximum_residual = max(
                math.sqrt(sum(value * value for value in values))
                for values in residuals
            )
            mode_logits.append(logits)
            samples.append(
                {
                    "sample_index": sample_index,
                    "seed": int(telemetry["seed"]),
                    "mode_logits": list(logits),
                    "maximum_residual_norm": maximum_residual,
                    "finite": all(math.isfinite(float(value)) for value in selected),
                    "fallback_to_expert": bool(telemetry["fallback_to_expert"]),
                    "latency_ms": float(telemetry["latency_ms"]),
                }
            )
        consensus = select_pi05_mode_consensus(mode_logits)
        evaluations.append(
            {
                "episode_id": episode_id,
                "capture_sha256": capture_audit["observation_sha256"],
                "capture_integrity_passed": capture_audit["status"] == "passed",
                "policy_type": controller.policy_type,
                "mode_input_hidden": not context.grasp_mode_conditioned,
                "expected_grasp_mode": expected_mode,
                "predicted_grasp_mode": consensus.selected_mode,
                "mode_vote_counts": dict(
                    zip(
                        ("top_suction", "side_suction", "cooperative_cradle"),
                        consensus.vote_counts,
                        strict=True,
                    )
                ),
                "mean_mode_logits": list(consensus.mean_logits),
                "consensus_fraction": consensus.consensus_fraction,
                "sample_count": len(samples),
                "sample_seeds": [item["seed"] for item in samples],
                "finite": all(item["finite"] for item in samples),
                "maximum_residual_norm": max(
                    item["maximum_residual_norm"] for item in samples
                ),
                "material_residual": max(
                    item["maximum_residual_norm"] for item in samples
                )
                > 1e-5,
                "fallback_to_expert": any(
                    item["fallback_to_expert"] for item in samples
                ),
                "mean_latency_ms": statistics.fmean(
                    item["latency_ms"] for item in samples
                ),
                "samples": samples,
            }
        )
    result = summarize_pi05_heldout_routing(evaluations, panel)
    result.update(
        {
            "checkpoint": str(args.checkpoint.resolve()),
            "collection": str(args.collection.resolve()),
            "collection_audit": collection_audit,
            "seed": args.seed,
        }
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["status"] == "passed" else 2


if __name__ == "__main__":
    raise SystemExit(main())
