#!/usr/bin/env python3
"""Load SmolVLA with LIBERO-shaped features and run inference/training smoke tests."""

import argparse
import json
from pathlib import Path
import time

import torch
import safetensors.torch

from lerobot.common.policies.smolvla.configuration_smolvla import SmolVLAConfig
from lerobot.common.policies.smolvla.modeling_smolvla import SmolVLAPolicy
from lerobot.configs.types import FeatureType, PolicyFeature
from draccus import decode


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--checkpoint", default="checkpoints/smolvla_base")
    parser.add_argument("--output", default="outputs/phase_3/smoke_metrics.json")
    args = parser.parse_args()

    checkpoint = Path(args.checkpoint).resolve()
    output = Path(args.output).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)

    raw_config = json.loads((checkpoint / "config.json").read_text())
    assert raw_config.pop("type") == "smolvla"
    # These are Hub publication metadata from the checkpoint's original
    # LeRobot schema and do not affect model construction.
    for key in ("push_to_hub", "repo_id", "private", "tags", "license"):
        raw_config.pop(key, None)
    base = decode(SmolVLAConfig, raw_config)
    base.device = "cuda"
    base.load_vlm_weights = False
    base.input_features = {
        "observation.state": PolicyFeature(type=FeatureType.STATE, shape=(8,)),
        "observation.images.agentview": PolicyFeature(
            type=FeatureType.VISUAL, shape=(3, 256, 256)
        ),
        "observation.images.wrist": PolicyFeature(
            type=FeatureType.VISUAL, shape=(3, 256, 256)
        ),
    }
    base.output_features = {
        "action": PolicyFeature(type=FeatureType.ACTION, shape=(7,))
    }
    # Identity statistics make this a shape/gradient smoke test. LIBERO dataset
    # statistics will be supplied by the adapter/SFT stage.
    stats = {
        "observation.state": {"mean": torch.zeros(8), "std": torch.ones(8)},
        "action": {"mean": torch.zeros(7), "std": torch.ones(7)},
    }

    torch.manual_seed(7)
    torch.cuda.reset_peak_memory_stats()
    load_start = time.perf_counter()
    policy = SmolVLAPolicy(base, dataset_stats=stats)
    missing, unexpected = safetensors.torch.load_model(
        policy, checkpoint / "model.safetensors", strict=False, device="cuda"
    )
    allowed_missing = {
        "normalize_inputs.buffer_observation_state.mean",
        "normalize_inputs.buffer_observation_state.std",
        "normalize_targets.buffer_action.mean",
        "normalize_targets.buffer_action.std",
        "unnormalize_outputs.buffer_action.mean",
        "unnormalize_outputs.buffer_action.std",
    }
    assert set(missing) <= allowed_missing, missing
    assert not unexpected, unexpected
    policy.to(device="cuda", dtype=torch.bfloat16)
    load_seconds = time.perf_counter() - load_start

    batch = {
        "observation.state": torch.randn(1, 8, device="cuda"),
        "observation.images.agentview": torch.rand(1, 3, 256, 256, device="cuda"),
        "observation.images.wrist": torch.rand(1, 3, 256, 256, device="cuda"),
        "action": torch.randn(1, base.chunk_size, 7, device="cuda"),
        "task": ["pick up the black bowl and place it on the plate"],
    }

    policy.train()
    policy.zero_grad(set_to_none=True)
    forward_start = time.perf_counter()
    with torch.autocast("cuda", dtype=torch.bfloat16):
        loss, losses = policy(batch)
    forward_seconds = time.perf_counter() - forward_start
    assert torch.isfinite(loss)
    loss.backward()
    trainable_grads = {
        name: float(parameter.grad.norm().item())
        for name, parameter in policy.named_parameters()
        if parameter.requires_grad and parameter.grad is not None
    }
    assert trainable_grads, "No trainable parameter received gradients"

    policy.eval()
    with torch.no_grad(), torch.autocast("cuda", dtype=torch.bfloat16):
        normalized = policy.normalize_inputs(batch)
        images, image_masks = policy.prepare_images(normalized)
        state = policy.prepare_state(normalized)
        language, language_masks = policy.prepare_language(normalized)
        inference_start = time.perf_counter()
        action_chunk = policy.model.sample_actions(
            images, image_masks, language, language_masks, state
        )[:, :, :7]
        inference_seconds = time.perf_counter() - inference_start
    assert action_chunk.shape == (1, 50, 7)
    assert torch.isfinite(action_chunk).all()
    torch.cuda.synchronize()

    metrics = {
        "checkpoint": str(checkpoint),
        "torch": torch.__version__,
        "torch_cuda": torch.version.cuda,
        "gpu": torch.cuda.get_device_name(),
        "dtype": str(next(policy.parameters()).dtype),
        "views": 2,
        "state_shape": [1, 8],
        "training_action_shape": [1, 50, 7],
        "action_chunk_shape": list(action_chunk.shape),
        "loss": float(loss.item()),
        "load_seconds": load_seconds,
        "forward_seconds": forward_seconds,
        "inference_seconds": inference_seconds,
        "peak_vram_mib": torch.cuda.max_memory_allocated() / 2**20,
        "trainable_parameters_with_grad": len(trainable_grads),
        "gradient_norm_min": min(trainable_grads.values()),
        "gradient_norm_max": max(trainable_grads.values()),
        "loss_detail_keys": sorted(losses),
    }
    output.write_text(json.dumps(metrics, indent=2) + "\n")
    print(json.dumps(metrics, indent=2))


if __name__ == "__main__":
    main()
