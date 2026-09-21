"""Offline Q-VGM residual velocity matching for SmolVLA.

The critic operates on executable LIBERO actions while SmolVLA's flow lives in
dataset-normalized, padded action coordinates.  This module keeps that boundary
explicit and stops gradients through the denoising trajectory, frozen SFT
teacher, critic, and Q-ascent target.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

import torch
from torch import nn

from .q_guidance import QGuidanceConfig, guide_action_chunk
from .qvgm_critic import QVGMCriticEnsemble


@dataclass(frozen=True)
class QVGMResidualConfig:
    denoising_steps: int = 10
    horizon: int = 5
    action_dim: int = 7
    gate_power: float = 1.0
    guidance_steps: int = 10
    guidance_step_size: float = 0.01
    guidance_max_delta: float = 0.05
    guidance_max_gradient_norm: float = 1.0
    action_min: float = -1.0
    action_max: float = 1.0
    use_confidence_gate: bool = False
    advantage_threshold: float = 0.0
    advantage_soft_scale: float = 0.01
    uncertainty_scale: float = 0.0
    minimum_confidence: float = 0.0
    base_anchor_weight: float = 0.0
    target_residual_max_norm: float = 0.0

    def __post_init__(self):
        if self.denoising_steps <= 0 or self.horizon <= 0 or self.action_dim <= 0:
            raise ValueError("denoising_steps, horizon, and action_dim must be positive")
        if self.gate_power < 0:
            raise ValueError("gate_power must be non-negative")
        if self.advantage_soft_scale <= 0:
            raise ValueError("advantage_soft_scale must be positive")
        if self.uncertainty_scale < 0 or self.base_anchor_weight < 0:
            raise ValueError("uncertainty_scale and base_anchor_weight must be non-negative")
        if not 0 <= self.minimum_confidence <= 1:
            raise ValueError("minimum_confidence must be in [0, 1]")
        if self.target_residual_max_norm < 0:
            raise ValueError("target_residual_max_norm must be non-negative")

    @property
    def guidance(self) -> QGuidanceConfig:
        return QGuidanceConfig(
            steps=self.guidance_steps,
            step_size=self.guidance_step_size,
            max_delta=self.guidance_max_delta,
            max_gradient_norm=self.guidance_max_gradient_norm,
            action_min=self.action_min,
            action_max=self.action_max,
            optimize_prefix_steps=self.horizon,
            optimize_action_dims=self.action_dim,
        )

    @property
    def config_dict(self) -> dict[str, Any]:
        return asdict(self)


def configure_qvgm_trainable_parameters(policy: nn.Module) -> tuple[list[nn.Parameter], list[str]]:
    """Freeze the prefix/VLM and train only SmolVLA's action expert path."""
    prefixes = (
        "model.vlm_with_expert.lm_expert.",
        "model.action_in_proj.",
        "model.action_out_proj.",
        "model.action_time_mlp_in.",
        "model.action_time_mlp_out.",
    )
    parameters: list[nn.Parameter] = []
    names: list[str] = []
    for name, parameter in policy.named_parameters():
        trainable = name.startswith(prefixes)
        parameter.requires_grad_(trainable)
        if trainable:
            parameters.append(parameter)
            names.append(name)
    if not parameters:
        raise ValueError("no SmolVLA action-expert parameters were selected")
    return parameters, names


def action_normalization_stats(
    policy: nn.Module, *, action_dim: int, device: torch.device
) -> tuple[torch.Tensor, torch.Tensor]:
    buffer = policy.normalize_targets.buffer_action
    mean = buffer.mean.detach().to(device=device, dtype=torch.float32).flatten()[:action_dim]
    std = buffer.std.detach().to(device=device, dtype=torch.float32).flatten()[:action_dim]
    if len(mean) != action_dim or len(std) != action_dim:
        raise ValueError("policy action normalization buffers are too short")
    if not torch.isfinite(mean).all() or not torch.isfinite(std).all() or torch.any(std <= 0):
        raise ValueError("invalid action normalization statistics")
    return mean, std


def model_to_environment_action(
    action: torch.Tensor, mean: torch.Tensor, std: torch.Tensor
) -> torch.Tensor:
    return action * std.view(1, 1, -1) + mean.view(1, 1, -1)


def environment_to_model_action(
    action: torch.Tensor, mean: torch.Tensor, std: torch.Tensor
) -> torch.Tensor:
    return (action - mean.view(1, 1, -1)) / std.view(1, 1, -1)


def effective_residual_velocity(
    x_t: torch.Tensor,
    base_velocity: torch.Tensor,
    improved_clean_action: torch.Tensor,
    time: torch.Tensor,
) -> tuple[torch.Tensor, torch.Tensor]:
    """Return clean base look-forward and the velocity residual targeting improvement."""
    if time.ndim != 1 or len(time) != len(x_t) or torch.any(time <= 0):
        raise ValueError("time must be a positive [B] tensor")
    clean_base = x_t - time[:, None, None] * base_velocity
    residual = (clean_base - improved_clean_action) / time[:, None, None]
    return clean_base, residual


def _prefix_cache(policy: nn.Module, batch: dict[str, Any]):
    normalized = policy.normalize_inputs(dict(batch))
    images, image_masks = policy.prepare_images(normalized)
    state = policy.prepare_state(normalized)
    language, language_masks = policy.prepare_language(normalized)
    model = policy.model
    prefix, pad_mask, block_mask = model.embed_prefix(
        images, image_masks, language, language_masks, state=state
    )
    cumulative = torch.cumsum(block_mask, dim=1)
    attention = cumulative[:, None, :] <= cumulative[:, :, None]
    attention = attention & pad_mask[:, None, :] & pad_mask[:, :, None]
    positions = torch.cumsum(pad_mask, dim=1) - 1
    _, past_key_values = model.vlm_with_expert.forward(
        attention_mask=attention,
        position_ids=positions,
        past_key_values=None,
        inputs_embeds=[prefix, None],
        use_cache=True,
        fill_kv_cache=True,
    )
    return pad_mask, past_key_values, state


def improve_model_clean_action(
    clean_model_action: torch.Tensor,
    critic: QVGMCriticEnsemble,
    z_state: torch.Tensor,
    proprio: torch.Tensor,
    mean: torch.Tensor,
    std: torch.Tensor,
    config: QVGMResidualConfig,
) -> tuple[torch.Tensor, dict[str, torch.Tensor]]:
    """Perform keep-best Q ascent in env coordinates and map back to flow coordinates."""
    base_env = model_to_environment_action(
        clean_model_action[:, : config.horizon, : config.action_dim], mean, std
    ).clamp(config.action_min, config.action_max)
    # The guidance target is detached from the policy by design, so the frozen
    # critic may safely live on a different device.  This is also useful on
    # ROCm systems where mixing two large BF16 policies with small FP32 critic
    # GEMMs in one context can trigger a native rocBLAS fault.
    first_critic_parameter = next(critic.parameters(), None)
    critic_device = (
        first_critic_parameter.device
        if first_critic_parameter is not None
        else base_env.device
    )
    critic_base_env = base_env.detach().to(critic_device)
    critic_z_state = z_state.detach().to(critic_device)
    critic_proprio = proprio.detach().to(critic_device)
    mask = torch.ones(
        critic_base_env.shape[:2], dtype=torch.bool, device=critic_device
    )
    critic_improved_env, details = guide_action_chunk(
        critic,
        critic_z_state,
        critic_proprio,
        critic_base_env,
        mask,
        config.guidance,
    )
    improved_env = critic_improved_env.to(base_env.device)
    improved = clean_model_action.detach().clone()
    improved[:, : config.horizon, : config.action_dim] = environment_to_model_action(
        improved_env, mean, std
    )
    details = {
        **{
            key: value.to(base_env.device) if torch.is_tensor(value) else value
            for key, value in details.items()
        },
        "base_env": base_env.detach(),
        "improved_env": improved_env.detach(),
    }
    if hasattr(critic, "disagreement"):
        with torch.no_grad():
            details["disagreement"] = critic.disagreement(
                critic_z_state,
                critic_proprio,
                critic_improved_env,
                mask,
            ).to(base_env.device)
    else:
        details["disagreement"] = torch.zeros_like(details["best_q"])
    return improved, details


def conservative_target_confidence(
    advantage: torch.Tensor,
    disagreement: torch.Tensor,
    config: QVGMResidualConfig,
) -> torch.Tensor:
    """Continuous confidence gate for a detached critic-generated target."""
    if not config.use_confidence_gate:
        return torch.ones_like(advantage).detach()
    advantage_gate = (
        (advantage - config.advantage_threshold) / config.advantage_soft_scale
    ).clamp(0.0, 1.0)
    uncertainty_gate = torch.exp(-config.uncertainty_scale * disagreement.clamp_min(0.0))
    confidence = advantage_gate * uncertainty_gate
    if config.minimum_confidence > 0:
        confidence = torch.where(
            advantage > config.advantage_threshold,
            confidence.clamp_min(config.minimum_confidence),
            torch.zeros_like(confidence),
        )
    return confidence.detach()


def bound_residual_norm(residual: torch.Tensor, maximum_norm: float) -> torch.Tensor:
    """Bound each target residual without changing its direction."""
    if maximum_norm <= 0:
        return residual
    flat = residual.flatten(1)
    norm = flat.norm(dim=1, keepdim=True).clamp_min(1e-8)
    scale = torch.clamp(maximum_norm / norm, max=1.0)
    return residual * scale.view(-1, 1, 1)


def residual_velocity_matching_loss(
    policy: nn.Module,
    base_policy: nn.Module,
    critic: QVGMCriticEnsemble,
    batch: dict[str, Any],
    config: QVGMResidualConfig | None = None,
    *,
    noise: torch.Tensor | None = None,
) -> tuple[torch.Tensor, dict[str, torch.Tensor]]:
    """Run a locally detached denoising rollout and compute full Q-VGM loss."""
    cfg = config or QVGMResidualConfig()
    device = batch["observation.state"].device
    observation = {
        key: value
        for key, value in batch.items()
        if key.startswith("observation.") or key == "task"
    }
    with torch.no_grad():
        prefix_mask, prefix_cache, state = _prefix_cache(policy, observation)
    batch_size = len(state)
    shape = (batch_size, policy.config.chunk_size, policy.config.max_action_dim)
    x_t = policy.model.sample_noise(shape, device) if noise is None else noise.to(device).float()
    if tuple(x_t.shape) != shape:
        raise ValueError(f"noise must have shape {shape}, got {tuple(x_t.shape)}")
    mean, std = action_normalization_stats(policy, action_dim=cfg.action_dim, device=device)
    z_state = batch["z_state"].to(device=device)
    proprio = batch["proprio"].to(device=device)
    dt = -1.0 / cfg.denoising_steps
    losses = []
    q_improvements = []
    action_deltas = []
    residual_norms = []
    confidences = []
    disagreements = []
    anchor_losses = []

    for step in range(cfg.denoising_steps):
        scalar_time = 1.0 - step / cfg.denoising_steps
        time = torch.full((batch_size,), scalar_time, device=device, dtype=torch.float32)
        x_t = x_t.detach()
        current_velocity = policy.model.denoise_step(
            prefix_mask, prefix_cache, x_t, time
        )
        with torch.no_grad():
            base_velocity = base_policy.model.denoise_step(
                prefix_mask, prefix_cache, x_t, time
            ).float()
            clean_base = x_t - time[:, None, None] * base_velocity

        gate = (1.0 - scalar_time) ** cfg.gate_power
        if gate > 0:
            improved, guidance = improve_model_clean_action(
                clean_base,
                critic,
                z_state,
                proprio,
                mean,
                std,
                cfg,
            )
            _, target = effective_residual_velocity(
                x_t, base_velocity, improved, time
            )
            target = bound_residual_norm(
                target.detach(), cfg.target_residual_max_norm
            )
            residual = current_velocity.float() - base_velocity
            per_sample = (residual - target).square().flatten(1).mean(dim=1)
            advantage = guidance["best_q"] - guidance["base_q"]
            disagreement = guidance["disagreement"]
            confidence = conservative_target_confidence(
                advantage, disagreement, cfg
            ).flatten()
            anchor = residual.square().flatten(1).mean(dim=1)
            losses.append(
                (
                    per_sample * confidence
                    + cfg.base_anchor_weight * anchor
                ).mean()
                * gate
            )
            q_improvements.append(advantage.mean().detach())
            action_deltas.append(
                (guidance["improved_env"] - guidance["base_env"]).abs().mean().detach()
            )
            residual_norms.append(target.flatten(1).norm(dim=1).mean().detach())
            confidences.append(confidence.mean())
            disagreements.append(disagreement.mean().detach())
            anchor_losses.append(anchor.mean().detach())
        else:
            losses.append(current_velocity.sum() * 0.0)
        x_t = (x_t + dt * current_velocity.detach()).detach()

    loss = torch.stack(losses).mean()
    if not torch.isfinite(loss):
        raise FloatingPointError("non-finite Q-VGM residual velocity loss")
    empty = torch.zeros((), device=device)
    details = {
        "loss": loss.detach(),
        "q_improvement": torch.stack(q_improvements).mean() if q_improvements else empty,
        "action_delta_abs": torch.stack(action_deltas).mean() if action_deltas else empty,
        "target_residual_norm": torch.stack(residual_norms).mean() if residual_norms else empty,
        "target_confidence": torch.stack(confidences).mean() if confidences else empty,
        "critic_disagreement": torch.stack(disagreements).mean() if disagreements else empty,
        "base_anchor_loss": torch.stack(anchor_losses).mean() if anchor_losses else empty,
        "final_noise_norm": x_t.flatten(1).norm(dim=1).mean(),
    }
    return loss, details
