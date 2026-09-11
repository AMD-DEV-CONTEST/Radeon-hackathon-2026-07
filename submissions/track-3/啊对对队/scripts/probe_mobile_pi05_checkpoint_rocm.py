#!/usr/bin/env python3
"""Load a PI0.5 LoRA checkpoint and run one mobile Harness inference."""

from __future__ import annotations

import argparse
from dataclasses import replace
import json
import math
from pathlib import Path
import statistics
from typing import Any, Mapping

from lerobot.datasets.lerobot_dataset import LeRobotDataset

from parcel_sorter.mobile_vla_controller import MobileVLAHarnessController
from parcel_sorter.mobile_dataset import (
    MOBILE_WRIST_DEPTH_KEY,
    MOBILE_WRIST_RGB_KEY,
)
from parcel_sorter.mobile_pi05_contract import (
    PI05_GRASP_MODES,
    decode_pi05_context,
    select_pi05_mode_consensus,
)
from parcel_sorter.mobile_pi05_action_fidelity import (
    absolute_action_fidelity,
    aggregate_absolute_action_fidelity,
)
from parcel_sorter.mobile_pi05_research_protocol import (
    file_sha256,
    validate_stage_panel,
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("checkpoint", type=Path)
    parser.add_argument("dataset", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--panel", type=Path, required=True)
    parser.add_argument("--samples", type=int, default=1)
    parser.add_argument("--seed", type=int, default=20260727)
    args = parser.parse_args()
    if args.samples < 1 or args.samples > 9 or args.samples % 2 == 0:
        parser.error("samples must be an odd integer in [1, 9]")

    import torch

    panel = json.loads(args.panel.read_text(encoding="utf-8"))
    panel_audit = validate_stage_panel(panel)
    dataset_root = args.dataset.resolve()
    if dataset_root != Path(str(panel.get("dataset_root"))).resolve():
        parser.error("dataset path does not match the frozen stage panel")
    manifest_paths = [
        path
        for path in (
            dataset_root / "PI05_ABSOLUTE_DATASET_MANIFEST.json",
            dataset_root / "PI05_RESIDUAL_DATASET_MANIFEST.json",
            dataset_root / "PI05_INCREMENTAL_DATASET_MANIFEST.json",
        )
        if path.is_file()
    ]
    if len(manifest_paths) != 1:
        parser.error("dataset must contain exactly one PI0.5 manifest")
    if file_sha256(manifest_paths[0]) != panel["dataset_manifest_sha256"]:
        parser.error("dataset manifest fingerprint does not match the frozen panel")
    dataset = LeRobotDataset(
        "local/mobile-bimanual-parcel-expert",
        root=dataset_root,
    )
    observations = list(panel["observations"])
    indices = [int(item["dataset_index"]) for item in observations]
    if any(not 0 <= index < len(dataset) for index in indices):
        parser.error(f"every index must be in [0, {len(dataset) - 1}]")

    torch.cuda.reset_peak_memory_stats()
    controller = MobileVLAHarnessController(args.checkpoint, seed=args.seed)
    if not controller.uses_absolute_contract:
        raise RuntimeError("stage-complete action screening requires absolute_v1")
    summaries = [
        _probe_index(
            controller=controller,
            dataset=dataset,
            panel_observation=observation,
            samples=args.samples,
            checkpoint=args.checkpoint,
            dataset_path=args.dataset,
            panel=panel,
            torch=torch,
        )
        for observation in observations
    ]
    summary = {
        "schema_version": 1,
        "protocol": "pi05-frozen-stage-panel-checkpoint-probe-v2",
        "checkpoint": str(args.checkpoint.resolve()),
        "dataset": str(dataset_root),
        "observation_panel_role": panel_audit["role"],
        "stage_panel_sha256": panel["panel_sha256"],
        "dataset_manifest_sha256": panel["dataset_manifest_sha256"],
        "sample_count_per_index": args.samples,
        "sample_seeds": [args.seed + offset for offset in range(args.samples)],
        "sampling_seed_protocol": "common-random-numbers-per-observation-v1",
        "peak_vram_bytes": torch.cuda.max_memory_allocated(),
        "screens": summaries,
    }
    payload = json.dumps(summary, indent=2, sort_keys=True)
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(payload + "\n", encoding="utf-8")
    print(payload)
    return 0


def _probe_index(
    *,
    controller: MobileVLAHarnessController,
    dataset: LeRobotDataset,
    panel_observation: Mapping[str, Any],
    samples: int,
    checkpoint: Path,
    dataset_path: Path,
    panel: Mapping[str, Any],
    torch: object,
) -> dict[str, object]:
    dataset_index = int(panel_observation["dataset_index"])
    frame = dataset[dataset_index]
    frame_episode = frame.get("episode_index")
    if hasattr(frame_episode, "item"):
        frame_episode = frame_episode.item()
    if int(frame_episode) != int(panel_observation["episode_index"]):
        raise RuntimeError("dataset episode index does not match the frozen panel")
    rgb = (
        frame["observation.images.overhead_rgb"]
        .permute(1, 2, 0)
        .mul(255.0)
        .clamp(0.0, 255.0)
        .byte()
        .numpy()
    )
    depth = frame["observation.images.overhead_depth"].squeeze().float().numpy()
    wrist_rgb = None
    wrist_depth = None
    if controller._uses_wrist_rgb:
        wrist_rgb = (
            frame[MOBILE_WRIST_RGB_KEY]
            .permute(1, 2, 0)
            .mul(255.0)
            .clamp(0.0, 255.0)
            .byte()
            .numpy()
        )
    if controller._uses_wrist_depth_rgb:
        wrist_depth = frame[MOBILE_WRIST_DEPTH_KEY].squeeze().float().numpy()
    encoded_state = frame["observation.state"].tolist()
    residual_context = decode_pi05_context(encoded_state)
    label_action = tuple(float(value) for value in frame["action"].tolist())
    mode_start = 19 if controller.uses_absolute_contract else 9
    progress_index = 22 if controller.uses_absolute_contract else 13
    expected_mode = PI05_GRASP_MODES[
        max(range(3), key=label_action[mode_start : mode_start + 3].__getitem__)
    ]
    if expected_mode != panel_observation["grasp_mode"]:
        raise RuntimeError("action label grasp mode does not match the frozen panel")
    if residual_context.stage != panel_observation["stage"]:
        raise RuntimeError("observation stage does not match the frozen panel")
    residual_context = replace(residual_context, grasp_mode=expected_mode)
    state = encoded_state[:43]
    expert_action = (
        0.0,
        0.0,
        0.0,
        *residual_context.left_contact_anchor_m,
        1.0,
        0.0,
        0.0,
        0.0,
        1.0,
        *residual_context.right_contact_anchor_m,
        1.0,
        0.0,
        0.0,
        0.0,
        1.0,
    )

    probes = []
    # Every observation receives the same diffusion-noise panel. This avoids
    # confounding parcel geometry with the controller's monotonically increasing seed.
    controller.reset_runtime_state()
    for sample_index in range(samples):
        selected, telemetry = controller.select(
            rgb=rgb,
            depth=depth,
            wrist_rgb=wrist_rgb,
            wrist_depth=wrist_depth,
            state=state,
            residual_context=residual_context,
            task=str(frame["task"]),
            expert_action=expert_action,
            stage=residual_context.stage,
        )
        projection = (
            telemetry.get("absolute_projection")
            or telemetry.get("residual_projection")
            or {}
        )
        predicted_residuals = {
            key: [float(value) for value in projection.get(key, (0.0, 0.0, 0.0))]
            for key in (
                "base_residual",
                "left_contact_residual_m",
                "right_contact_residual_m",
            )
        }
        probes.append(
            {
                "sample_index": sample_index,
                "seed": int(telemetry["seed"]),
                "predicted_grasp_mode": projection.get("predicted_mode"),
                "mode_logits": projection.get("mode_logits"),
                "requested_suction": projection.get("requested_suction"),
                "predicted_progress": projection.get("progress"),
                "raw_absolute_action": telemetry.get("raw_absolute_action"),
                "action_fidelity": (
                    absolute_action_fidelity(
                        telemetry["raw_absolute_action"], label_action
                    )
                    if controller.uses_absolute_contract
                    else None
                ),
                "predicted_residuals": predicted_residuals,
                "maximum_residual_norm": max(
                    math.sqrt(sum(value * value for value in values))
                    for values in predicted_residuals.values()
                ),
                "latency_ms": telemetry["latency_ms"],
                "selected_scale": telemetry["selected_scale"],
                "fallback_to_expert": telemetry["fallback_to_expert"],
                "expert_reference_used": telemetry["expert_reference_used"],
                "pure_vla_qualified_step": telemetry["pure_vla_qualified_step"],
                "selected_action": [float(value) for value in selected],
                "output_dim": len(selected),
                "finite": all(math.isfinite(value) for value in selected),
            }
        )
    consensus = select_pi05_mode_consensus(
        probe["mode_logits"] for probe in probes
    )
    maximum_residual = max(
        float(probe["maximum_residual_norm"]) for probe in probes
    )
    maximum_absolute_motion = max(
        max(
            math.sqrt(sum(value * value for value in probe["selected_action"][:3])),
            math.dist(probe["selected_action"][3:6], state[24:27]),
            math.dist(probe["selected_action"][11:14], state[31:34]),
        )
        for probe in probes
    )
    summary = {
        "policy_type": controller.policy_type,
        "checkpoint": str(checkpoint.resolve()),
        "dataset": str(dataset_path.resolve()),
        "dataset_index": dataset_index,
        "observation_id": panel_observation["observation_id"],
        "episode_index": int(panel_observation["episode_index"]),
        "source_identity": panel_observation["source_identity"],
        "policy_visual_keys": sorted(
            key
            for key in controller._config.input_features
            if key.startswith("observation.images.")
        ),
        "observation_panel_role": panel["role"],
        "stage_panel_sha256": panel["panel_sha256"],
        "dataset_manifest_sha256": panel["dataset_manifest_sha256"],
        "stage": residual_context.stage,
        "grasp_mode_conditioned": residual_context.grasp_mode_conditioned,
        "expected_grasp_mode": expected_mode,
        "observable_object_context": {
            "shape": residual_context.parcel_shape,
            "size_m": list(residual_context.parcel_size_m),
            "mass_kg": residual_context.parcel_mass_kg,
        },
        "sample_count": samples,
        "sample_seeds": [int(probe["seed"]) for probe in probes],
        "sampling_seed_protocol": "common-random-numbers-per-observation-v1",
        "predicted_grasp_mode": consensus.selected_mode,
        "predicted_mode_logits": list(consensus.mean_logits),
        "mode_vote_counts": dict(zip(PI05_GRASP_MODES, consensus.vote_counts, strict=True)),
        "mode_consensus_fraction": consensus.consensus_fraction,
        "grasp_mode_correct": consensus.selected_mode == expected_mode,
        "requested_suction_fraction": sum(
            bool(probe["requested_suction"]) for probe in probes
        )
        / len(probes),
        "predicted_residuals": probes[0]["predicted_residuals"],
        "maximum_residual_norm": maximum_residual,
        "material_residual": (
            maximum_residual > 1e-5
            if controller.uses_residual_contract
            else None
        ),
        "maximum_absolute_motion": maximum_absolute_motion,
        "material_action": maximum_absolute_motion > 1e-5,
        "label_residual": (
            list(label_action[:9]) if controller.uses_residual_contract else None
        ),
        "label_action": list(label_action) if controller.uses_absolute_contract else None,
        "predicted_progress": statistics.fmean(
            float(probe["predicted_progress"]) for probe in probes
        ),
        "label_progress": label_action[progress_index],
        "action_fidelity": (
            aggregate_absolute_action_fidelity(
                probe["action_fidelity"] for probe in probes
            )
            if controller.uses_absolute_contract
            else None
        ),
        "output_dim": int(probes[0]["output_dim"]),
        "finite": all(bool(probe["finite"]) for probe in probes),
        "mean_latency_ms": statistics.fmean(
            float(probe["latency_ms"]) for probe in probes
        ),
        "selected_scale_min": min(float(probe["selected_scale"]) for probe in probes),
        "fallback_to_expert": any(bool(probe["fallback_to_expert"]) for probe in probes),
        "expert_reference_used": any(
            bool(probe["expert_reference_used"]) for probe in probes
        ),
        "pure_vla_qualified": all(
            bool(probe["pure_vla_qualified_step"]) for probe in probes
        ),
        "peak_vram_bytes": torch.cuda.max_memory_allocated(),
        "samples": probes,
    }
    summary["action_contract"] = (
        "pi05_absolute_v1"
        if controller.uses_absolute_contract
        else "pi05_residual_v1"
    )
    if summary["policy_type"] != "pi05" or summary["output_dim"] != 19 or not summary["finite"]:
        raise RuntimeError(f"PI0.5 checkpoint probe failed: {summary}")
    return summary


if __name__ == "__main__":
    raise SystemExit(main())
