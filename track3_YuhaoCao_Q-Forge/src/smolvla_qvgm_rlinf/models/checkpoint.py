"""Compatibility loader for the pinned SmolVLA base checkpoint."""

import json
from pathlib import Path

from draccus import decode
import safetensors.torch
import torch

from lerobot.common.policies.smolvla.configuration_smolvla import SmolVLAConfig
from lerobot.common.policies.smolvla.modeling_smolvla import SmolVLAPolicy
from lerobot.configs.types import FeatureType, PolicyFeature


NON_MODEL_CONFIG_FIELDS = {
    "push_to_hub",
    "repo_id",
    "private",
    "tags",
    "license",
    "pretrained_path",
    # Native LeRobot training-only scheduler controls. They are saved beside
    # the policy config but do not affect the SmolVLA module architecture.
    "scheduler_auto_scale",
    "scheduler_decay_after_warmup",
}


def _identity_stats(state_dim: int, action_dim: int) -> dict:
    return {
        "observation.state": {
            "mean": torch.zeros(state_dim),
            "std": torch.ones(state_dim),
        },
        "action": {
            "mean": torch.zeros(action_dim),
            "std": torch.ones(action_dim),
        },
    }


def _native_processor_stats(checkpoint: Path) -> dict | None:
    """Read state/action mean-std saved by LeRobot's native processor pipeline.

    LeRobot 0.4 stores normalization statistics beside the policy rather than
    inside ``model.safetensors``.  The vendored rollout policy still owns
    normalization modules, so reconstruct their dataset stats from the native
    preprocessor state when loading a native SFT checkpoint.
    """
    candidates = sorted(
        checkpoint.glob("policy_preprocessor_step_*_normalizer_processor.safetensors")
    )
    if not candidates:
        return None
    if len(candidates) != 1:
        raise RuntimeError(
            f"expected one native normalizer state in {checkpoint}, found {candidates}"
        )
    tensors = safetensors.torch.load_file(candidates[0], device="cpu")
    output = {}
    for feature in ("observation.state", "action"):
        mean_key = f"{feature}.mean"
        std_key = f"{feature}.std"
        if mean_key not in tensors or std_key not in tensors:
            raise RuntimeError(
                f"native normalizer {candidates[0]} is missing {mean_key!r} or {std_key!r}"
            )
        output[feature] = {
            "mean": tensors[mean_key].float(),
            "std": tensors[std_key].float(),
        }
    return output


def _restore_fp32_normalizer_stats(policy: SmolVLAPolicy, stats: dict) -> None:
    """Keep native processor statistics in FP32 after casting model weights.

    Native LeRobot normalizes observations and unnormalizes actions in its
    processor pipeline before/after the BF16 model.  The compatibility policy
    embeds those operations as modules, so a blanket ``policy.to(dtype=...)``
    would otherwise quantize the statistics themselves to BF16.
    """
    bindings = (
        (policy.normalize_inputs.buffer_observation_state, stats["observation.state"]),
        (policy.normalize_targets.buffer_action, stats["action"]),
        (policy.unnormalize_outputs.buffer_action, stats["action"]),
    )
    device = next(policy.parameters()).device
    for buffer, feature_stats in bindings:
        buffer.mean.data = feature_stats["mean"].to(device=device, dtype=torch.float32)
        buffer.std.data = feature_stats["std"].to(device=device, dtype=torch.float32)


def load_smolvla_checkpoint(
    checkpoint: str | Path,
    *,
    device: str = "cuda",
    dtype: torch.dtype = torch.bfloat16,
    state_dim: int = 8,
    action_dim: int = 7,
    num_steps: int | None = None,
    dataset_stats: dict | None = None,
) -> SmolVLAPolicy:
    checkpoint = Path(checkpoint).expanduser().resolve()
    config_path = checkpoint / "config.json"
    weights_path = checkpoint / "model.safetensors"
    if not config_path.is_file() or not weights_path.is_file():
        raise FileNotFoundError(
            f"SmolVLA checkpoint must contain config.json and model.safetensors: {checkpoint}"
        )

    raw = json.loads(config_path.read_text())
    if raw.pop("type", None) != "smolvla":
        raise ValueError(f"Not a SmolVLA checkpoint: {config_path}")
    for key in NON_MODEL_CONFIG_FIELDS:
        raw.pop(key, None)
    config = decode(SmolVLAConfig, raw)
    config.device = device
    # All learned VLM weights are present in the policy checkpoint. Avoid a
    # redundant backbone download before loading them.
    config.load_vlm_weights = False
    if num_steps is not None:
        config.num_steps = int(num_steps)
    config.input_features = {
        "observation.state": PolicyFeature(type=FeatureType.STATE, shape=(state_dim,)),
        "observation.images.agentview": PolicyFeature(
            type=FeatureType.VISUAL, shape=(3, 256, 256)
        ),
        "observation.images.wrist": PolicyFeature(
            type=FeatureType.VISUAL, shape=(3, 256, 256)
        ),
    }
    config.output_features = {
        "action": PolicyFeature(type=FeatureType.ACTION, shape=(action_dim,))
    }

    processor_stats = _native_processor_stats(checkpoint)
    stats = dataset_stats or processor_stats or _identity_stats(state_dim, action_dim)
    policy = SmolVLAPolicy(config, dataset_stats=stats)
    missing, unexpected = safetensors.torch.load_model(
        policy, weights_path, strict=False, device=device
    )
    allowed_missing = {
        "normalize_inputs.buffer_observation_state.mean",
        "normalize_inputs.buffer_observation_state.std",
        "normalize_targets.buffer_action.mean",
        "normalize_targets.buffer_action.std",
        "unnormalize_outputs.buffer_action.mean",
        "unnormalize_outputs.buffer_action.std",
    }
    if set(missing) - allowed_missing:
        raise RuntimeError(f"Unexpected missing SmolVLA weights: {sorted(missing)}")
    if unexpected:
        raise RuntimeError(f"Unexpected SmolVLA weights: {sorted(unexpected)}")
    policy.to(device=device, dtype=dtype)
    if dataset_stats is not None or processor_stats is not None:
        _restore_fp32_normalizer_stats(policy, stats)
    policy.eval()
    return policy
