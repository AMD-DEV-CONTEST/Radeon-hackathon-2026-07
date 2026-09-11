#!/usr/bin/env python3
"""Probe PI0.5 mode logits directly at the pure-noise flow endpoint."""

from __future__ import annotations

import argparse
from collections import Counter
from dataclasses import replace
import json
from pathlib import Path

from lerobot.datasets.lerobot_dataset import LeRobotDataset
from lerobot.policies.pi05.modeling_pi05 import (
    OBS_LANGUAGE_ATTENTION_MASK,
    OBS_LANGUAGE_TOKENS,
)

from parcel_sorter.dataset import metric_depth_to_visual_rgb
from parcel_sorter.mobile_dataset import (
    MOBILE_DEPTH_RGB_KEY,
    MOBILE_RGB_KEY,
    MOBILE_WRIST_DEPTH_KEY,
    MOBILE_WRIST_DEPTH_RGB_KEY,
    MOBILE_WRIST_RGB_KEY,
)
from parcel_sorter.mobile_pi05_contract import (
    PI05_GRASP_MODES,
    decode_pi05_context,
    encode_pi05_absolute_state,
    encode_pi05_state,
    select_pi05_mode_consensus,
)
from parcel_sorter.mobile_pi05_research_protocol import (
    file_sha256,
    validate_stage_panel,
)
from parcel_sorter.mobile_vla_controller import (
    MobileVLAHarnessController,
    select_vla_policy_task,
)
from parcel_sorter.pi05_weighted_loss import pi05_flow_velocity


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("checkpoint", type=Path)
    parser.add_argument("dataset", type=Path)
    parser.add_argument("--panel", type=Path, required=True)
    parser.add_argument("--samples", type=int, default=3)
    parser.add_argument("--seed", type=int, default=20260727)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.samples < 1 or args.samples > 31 or args.samples % 2 == 0:
        parser.error("samples must be an odd integer in [1, 31]")

    import numpy as np
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
        "local/mobile-bimanual-parcel-expert", root=dataset_root
    )
    observations = list(panel["observations"])
    controller = MobileVLAHarnessController(args.checkpoint, seed=args.seed)
    if controller.policy_type != "pi05" or not controller.uses_absolute_contract:
        raise RuntimeError(
            "stage-panel high-noise probe requires an absolute_v1 PI0.5 checkpoint"
        )
    mode_start = 19
    policy = controller._policy.get_base_model()
    screens = []
    for observation in observations:
        index = int(observation["dataset_index"])
        frame = dataset[index]
        frame_episode = frame.get("episode_index")
        if hasattr(frame_episode, "item"):
            frame_episode = frame_episode.item()
        if int(frame_episode) != int(observation["episode_index"]):
            raise RuntimeError("dataset episode index does not match the frozen panel")
        encoded_state = tuple(float(value) for value in frame["observation.state"])
        context = decode_pi05_context(encoded_state)
        action = tuple(float(value) for value in frame["action"])
        expected_mode = PI05_GRASP_MODES[
            max(
                range(3),
                key=action[mode_start : mode_start + 3].__getitem__,
            )
        ]
        if expected_mode != observation["grasp_mode"]:
            raise RuntimeError("action label grasp mode does not match the frozen panel")
        if context.stage != observation["stage"]:
            raise RuntimeError("observation stage does not match the frozen panel")
        context = replace(
            context, grasp_mode=expected_mode, grasp_mode_conditioned=False
        )
        rgb = (
            frame[MOBILE_RGB_KEY]
            .permute(1, 2, 0)
            .mul(255.0)
            .clamp(0.0, 255.0)
            .byte()
            .numpy()
        )
        depth = frame["observation.images.overhead_depth"].squeeze().float().numpy()
        task = select_vla_policy_task(
            str(frame["task"]),
            context.stage,
            uses_progress_channel=True,
            uses_residual_contract=True,
            residual_context=context,
        )
        state_values = (
            encode_pi05_absolute_state(encoded_state[:43], context)
            if controller.uses_absolute_contract
            else encode_pi05_state(encoded_state[:43], context)
        )
        image_tensor = (
            torch.from_numpy(np.asarray(rgb, dtype=np.uint8).copy())
            .permute(2, 0, 1)
            .float()
            .div_(255.0)
        )
        depth_rgb = metric_depth_to_visual_rgb(depth, np)
        depth_tensor = (
            torch.from_numpy(depth_rgb.copy()).permute(2, 0, 1).float().div_(255.0)
        )
        policy_batch = {
            "observation.state": torch.tensor(
                state_values, dtype=torch.float32
            ).unsqueeze(0).cuda(),
            MOBILE_RGB_KEY: image_tensor.unsqueeze(0).cuda(),
            MOBILE_DEPTH_RGB_KEY: depth_tensor.unsqueeze(0).cuda(),
            "task": [task],
        }
        if controller._uses_wrist_rgb:
            wrist_image = (
                frame[MOBILE_WRIST_RGB_KEY]
                .permute(1, 2, 0)
                .mul(255.0)
                .clamp(0.0, 255.0)
                .byte()
                .numpy()
            )
            wrist_tensor = (
                torch.from_numpy(np.asarray(wrist_image, dtype=np.uint8).copy())
                .permute(2, 0, 1)
                .float()
                .div_(255.0)
            )
            policy_batch[MOBILE_WRIST_RGB_KEY] = wrist_tensor.unsqueeze(0).cuda()
        if controller._uses_wrist_depth_rgb:
            wrist_depth = (
                frame[MOBILE_WRIST_DEPTH_KEY].squeeze().float().numpy()
            )
            wrist_depth_rgb = metric_depth_to_visual_rgb(wrist_depth, np)
            wrist_depth_tensor = (
                torch.from_numpy(wrist_depth_rgb.copy())
                .permute(2, 0, 1)
                .float()
                .div_(255.0)
            )
            policy_batch[MOBILE_WRIST_DEPTH_RGB_KEY] = (
                wrist_depth_tensor.unsqueeze(0).cuda()
            )
        batch = controller._preprocessor(policy_batch)
        images, image_masks = policy._preprocess_images(batch)
        tokens = batch[OBS_LANGUAGE_TOKENS]
        masks = batch[OBS_LANGUAGE_ATTENTION_MASK]
        samples = []
        for sample_index in range(args.samples):
            seed = args.seed + sample_index
            controller._reset()
            with torch.random.fork_rng(devices=[torch.cuda.current_device()]):
                torch.manual_seed(seed)
                torch.cuda.manual_seed_all(seed)
                with torch.inference_mode():
                    noise = policy.model.sample_noise(
                        (
                            1,
                            policy.config.chunk_size,
                            policy.config.max_action_dim,
                        ),
                        torch.device("cuda"),
                    )
                    time = torch.ones(1, device=noise.device, dtype=noise.dtype)
                    velocity = pi05_flow_velocity(
                        policy.model,
                        images,
                        image_masks,
                        tokens,
                        masks,
                        noise,
                        time,
                        batch.get("observation.state"),
                    )
                    predicted_clean = noise - velocity
                    normalized_logits = predicted_clean[
                        0, 0, mode_start : mode_start + 3
                    ].float()
                    denormalized = controller._postprocessor(
                        predicted_clean[0, 0, : controller.action_dim]
                    )
                    denormalized_logits = denormalized[
                        mode_start : mode_start + 3
                    ].float()
            samples.append(
                {
                    "seed": seed,
                    "normalized_mode_logits": normalized_logits.cpu().tolist(),
                    "normalized_mode": PI05_GRASP_MODES[
                        int(normalized_logits.argmax().item())
                    ],
                    "denormalized_mode_logits": denormalized_logits.cpu().tolist(),
                    "denormalized_mode": PI05_GRASP_MODES[
                        int(denormalized_logits.argmax().item())
                    ],
                }
            )
        normalized_consensus = select_pi05_mode_consensus(
            sample["normalized_mode_logits"] for sample in samples
        )
        denormalized_consensus = select_pi05_mode_consensus(
            sample["denormalized_mode_logits"] for sample in samples
        )
        screens.append(
            {
                "dataset_index": index,
                "observation_id": observation["observation_id"],
                "episode_index": int(observation["episode_index"]),
                "source_identity": observation["source_identity"],
                "expected_grasp_mode": expected_mode,
                "stage": context.stage,
                "observable_object_context": {
                    "shape": context.parcel_shape,
                    "size_m": list(context.parcel_size_m),
                    "mass_kg": context.parcel_mass_kg,
                },
                "grasp_mode_conditioned": context.grasp_mode_conditioned,
                "sample_count": args.samples,
                "sample_seeds": [int(sample["seed"]) for sample in samples],
                "sampling_seed_protocol": "common-random-numbers-per-observation-v1",
                "normalized_mode": normalized_consensus.selected_mode,
                "normalized_correct": normalized_consensus.selected_mode
                == expected_mode,
                "normalized_vote_counts": dict(
                    zip(
                        PI05_GRASP_MODES,
                        normalized_consensus.vote_counts,
                        strict=True,
                    )
                ),
                "denormalized_mode": denormalized_consensus.selected_mode,
                "denormalized_correct": denormalized_consensus.selected_mode
                == expected_mode,
                "denormalized_vote_counts": dict(
                    zip(
                        PI05_GRASP_MODES,
                        denormalized_consensus.vote_counts,
                        strict=True,
                    )
                ),
                "samples": samples,
            }
        )
    expected_counts = Counter(item["expected_grasp_mode"] for item in screens)
    normalized_correct = sum(item["normalized_correct"] for item in screens)
    denormalized_correct = sum(item["denormalized_correct"] for item in screens)
    payload = {
        "schema_version": 1,
        "protocol": "pi05-pure-noise-endpoint-mode-probe-v1",
        "checkpoint": str(args.checkpoint.resolve()),
        "dataset": str(dataset_root),
        "observation_panel_role": panel_audit["role"],
        "stage_panel_sha256": panel["panel_sha256"],
        "dataset_manifest_sha256": panel["dataset_manifest_sha256"],
        "policy_visual_keys": sorted(
            key
            for key in controller._config.input_features
            if key.startswith("observation.images.")
        ),
        "sample_count_per_index": args.samples,
        "sample_seeds": [args.seed + offset for offset in range(args.samples)],
        "sampling_seed_protocol": "common-random-numbers-per-observation-v1",
        "action_contract": (
            "pi05_absolute_v1"
            if controller.uses_absolute_contract
            else "pi05_residual_v1"
        ),
        "expected_mode_counts": dict(expected_counts),
        "normalized_correct": normalized_correct,
        "denormalized_correct": denormalized_correct,
        "screens": screens,
        "claim_boundary": (
            "Diagnostic PI0.5 t=1 flow-field classification only; this is not "
            "full diffusion inference or closed-loop task success."
        ),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(payload, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
