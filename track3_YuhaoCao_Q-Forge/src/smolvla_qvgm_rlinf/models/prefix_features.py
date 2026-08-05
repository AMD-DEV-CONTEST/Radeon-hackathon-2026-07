"""Frozen SmolVLA prefix features for the lightweight Q-VGM critic."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import torch
import torch.nn.functional as F
from torch import nn


@dataclass(frozen=True)
class PrefixFeatureConfig:
    output_dim: int = 512
    projection_seed: int = 1000
    pooling: str = "layer_norm_masked_mean"


@dataclass(frozen=True)
class RLTFeatureConfig:
    input_dim: int = 960
    embed_dim: int = 2048
    num_rl_tokens: int = 1
    prefix_seq_len: int = 177
    num_layers: int = 2
    num_heads: int = 8
    mlp_ratio: float = 4.0


def make_fixed_projection(
    input_dim: int, output_dim: int, *, seed: int, dtype: torch.dtype = torch.float32
) -> torch.Tensor:
    """Create a reproducible Gaussian random projection on CPU."""
    if input_dim <= 0 or output_dim <= 0:
        raise ValueError("projection dimensions must be positive")
    generator = torch.Generator(device="cpu").manual_seed(seed)
    projection = torch.randn(input_dim, output_dim, generator=generator, dtype=dtype)
    return projection / input_dim**0.5


def pool_prefix_hidden(
    hidden: torch.Tensor, pad_mask: torch.Tensor, projection: torch.Tensor
) -> torch.Tensor:
    """Layer-normalize tokens, masked-mean pool, then project to compact state."""
    if hidden.ndim != 3 or pad_mask.shape != hidden.shape[:2]:
        raise ValueError("hidden must be [B,L,D] and pad_mask must be [B,L]")
    if projection.shape[0] != hidden.shape[-1]:
        raise ValueError("projection input dimension does not match hidden size")
    mask = pad_mask.to(device=hidden.device, dtype=torch.bool)
    if torch.any(mask.sum(dim=1) == 0):
        raise ValueError("each prefix must contain at least one valid token")
    normalized = F.layer_norm(hidden.float(), (hidden.shape[-1],))
    weights = mask.unsqueeze(-1).to(normalized.dtype)
    pooled = (normalized * weights).sum(dim=1) / weights.sum(dim=1)
    return pooled @ projection.to(device=pooled.device, dtype=pooled.dtype)


class FrozenSmolVLAPrefixExtractor(nn.Module):
    """Extract compact features using the exact frozen SmolVLA prefix path."""

    def __init__(self, policy: nn.Module, config: PrefixFeatureConfig | None = None):
        super().__init__()
        self.policy = policy
        self.feature_config = config or PrefixFeatureConfig()
        hidden_size = int(policy.model.vlm_with_expert.config.text_config.hidden_size)
        self.register_buffer(
            "projection",
            make_fixed_projection(
                hidden_size,
                self.feature_config.output_dim,
                seed=self.feature_config.projection_seed,
            ),
            persistent=True,
        )
        self.policy.eval()
        for parameter in self.policy.parameters():
            parameter.requires_grad_(False)

    @property
    def config_dict(self) -> dict:
        return {**asdict(self.feature_config), "hidden_size": int(self.projection.shape[0])}

    @torch.inference_mode()
    def forward(self, batch: dict) -> torch.Tensor:
        prefix_hidden, pad_mask = extract_prefix_hidden(self.policy, batch)
        return pool_prefix_hidden(prefix_hidden, pad_mask, self.projection)


def extract_prefix_hidden(policy: nn.Module, batch: dict) -> tuple[torch.Tensor, torch.Tensor]:
    """Run the exact frozen SmolVLA prefix path and return token features/mask."""
    normalized_batch = policy.normalize_inputs(dict(batch))
    images, image_masks = policy.prepare_images(normalized_batch)
    state = policy.prepare_state(normalized_batch)
    language_tokens, language_masks = policy.prepare_language(normalized_batch)
    model = policy.model
    prefix, pad_mask, attention_mask = model.embed_prefix(
        images, image_masks, language_tokens, language_masks, state=state
    )
    attention_2d = _make_attention_mask(pad_mask, attention_mask)
    position_ids = torch.cumsum(pad_mask, dim=1) - 1
    (prefix_hidden, _), _ = model.vlm_with_expert.forward(
        attention_mask=attention_2d,
        position_ids=position_ids,
        past_key_values=None,
        inputs_embeds=[prefix, None],
        use_cache=False,
        fill_kv_cache=True,
    )
    return prefix_hidden, pad_mask


def make_rlt_module(config: RLTFeatureConfig) -> nn.Module:
    from rlinf.models.embodiment.modules.rlt_token_transformer import RLTTokenTransformer

    return RLTTokenTransformer(**asdict(config))


class FrozenSmolVLARLTExtractor(nn.Module):
    """Frozen SmolVLA prefix plus a trained RLT token autoencoder encoder."""

    def __init__(self, policy: nn.Module, rlt_module: nn.Module, config: RLTFeatureConfig):
        super().__init__()
        self.policy = policy
        self.rlt_module = rlt_module
        self.feature_config = config
        self.policy.eval()
        self.rlt_module.eval()
        for parameter in self.parameters():
            parameter.requires_grad_(False)

    @property
    def config_dict(self) -> dict[str, Any]:
        return {"kind": "rlt_autoencoder", **asdict(self.feature_config)}

    @torch.inference_mode()
    def forward(self, batch: dict) -> torch.Tensor:
        prefix_hidden, pad_mask = extract_prefix_hidden(self.policy, batch)
        rlt_parameter = next(self.rlt_module.parameters())
        return self.rlt_module.encode_flat(
            prefix_hidden.to(device=rlt_parameter.device, dtype=rlt_parameter.dtype),
            pad_mask,
        ).float()


def load_rlt_extractor(
    policy: nn.Module, checkpoint: str | Path, *, device: str | torch.device = "cuda"
) -> FrozenSmolVLARLTExtractor:
    payload = torch.load(checkpoint, map_location="cpu", weights_only=True)
    config = RLTFeatureConfig(**payload["config"])
    module = make_rlt_module(config).to(device=device, dtype=torch.bfloat16)
    module.load_state_dict(payload["model"])
    return FrozenSmolVLARLTExtractor(policy, module, config).to(device).eval()


def _make_attention_mask(pad_mask: torch.Tensor, attention_mask: torch.Tensor) -> torch.Tensor:
    """Local copy of SmolVLA prefix-LM mask construction to keep this module testable."""
    cumulative = torch.cumsum(attention_mask, dim=1)
    causal_blocks = cumulative[:, None, :] <= cumulative[:, :, None]
    valid = pad_mask[:, None, :] & pad_mask[:, :, None]
    return causal_blocks & valid
