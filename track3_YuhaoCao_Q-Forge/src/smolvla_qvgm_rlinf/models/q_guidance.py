"""Safe test-time action-chunk ascent for a frozen Q-VGM critic."""

from __future__ import annotations

from dataclasses import dataclass

import torch

from .qvgm_critic import QVGMCriticEnsemble


@dataclass(frozen=True)
class QGuidanceConfig:
    steps: int = 10
    step_size: float = 0.02
    max_delta: float = 0.2
    max_gradient_norm: float = 1.0
    action_min: float = -1.0
    action_max: float = 1.0
    optimize_prefix_steps: int | None = None
    optimize_action_dims: int | None = None


def guide_action_chunk(
    critic: QVGMCriticEnsemble,
    z_state: torch.Tensor,
    proprio: torch.Tensor,
    reference: torch.Tensor,
    action_mask: torch.Tensor,
    config: QGuidanceConfig | None = None,
) -> tuple[torch.Tensor, dict[str, torch.Tensor]]:
    """Projected Q ascent with per-sample keep-best including the base action."""
    cfg = config or QGuidanceConfig()
    if cfg.steps <= 0 or cfg.step_size <= 0 or cfg.max_delta < 0:
        raise ValueError("invalid guidance configuration")
    base = reference.detach().float()
    optimization_mask = action_mask.bool()
    if cfg.optimize_prefix_steps is not None:
        if cfg.optimize_prefix_steps <= 0:
            raise ValueError("optimize_prefix_steps must be positive")
        prefix = torch.arange(action_mask.shape[1], device=action_mask.device)
        optimization_mask = optimization_mask & (prefix[None, :] < cfg.optimize_prefix_steps)
    mask = optimization_mask.unsqueeze(-1)
    if cfg.optimize_action_dims is not None:
        if not 0 < cfg.optimize_action_dims <= reference.shape[-1]:
            raise ValueError("optimize_action_dims must be in [1, action_dim]")
        dimensions = torch.arange(reference.shape[-1], device=reference.device)
        mask = mask & (dimensions[None, None, :] < cfg.optimize_action_dims)
    current = base.clone()
    with torch.no_grad():
        base_q = critic.mean_value(z_state, proprio, base, action_mask)
    best = base.clone()
    best_q = base_q.clone()
    gradient_norms = []
    for _ in range(cfg.steps):
        current = current.detach().requires_grad_(True)
        q = critic.mean_value(z_state, proprio, current, action_mask)
        gradient = torch.autograd.grad(q.sum(), current)[0]
        gradient = gradient * mask
        norm = gradient.flatten(1).norm(dim=1, keepdim=True).clamp_min(1e-8)
        scale = torch.clamp(cfg.max_gradient_norm / norm, max=1.0)
        gradient = gradient * scale[:, None]
        gradient_norms.append(norm.squeeze(1).detach())
        proposed = current + cfg.step_size * gradient
        proposed = torch.maximum(proposed, base - cfg.max_delta)
        proposed = torch.minimum(proposed, base + cfg.max_delta)
        proposed = proposed.clamp(cfg.action_min, cfg.action_max)
        current = torch.where(mask, proposed, base).detach()
        with torch.no_grad():
            candidate_q = critic.mean_value(z_state, proprio, current, action_mask)
            improve = candidate_q > best_q
            best = torch.where(improve[:, None], current, best)
            best_q = torch.where(improve, candidate_q, best_q)
    return best, {
        "base_q": base_q,
        "best_q": best_q,
        "gradient_norm": torch.stack(gradient_norms, dim=1),
    }
