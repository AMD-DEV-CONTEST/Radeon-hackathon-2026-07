"""Training primitives shared by Q-VGM offline critic stages."""

from __future__ import annotations

import torch
import torch.nn.functional as F

from .qvgm_critic import QVGMCriticEnsemble


@torch.no_grad()
def polyak_update(
    source: torch.nn.Module, target: torch.nn.Module, *, tau: float
) -> None:
    """Update a floating-point target network in place."""
    if not 0.0 < tau <= 1.0:
        raise ValueError("tau must be in (0, 1]")
    source_parameters = dict(source.named_parameters())
    target_parameters = dict(target.named_parameters())
    if source_parameters.keys() != target_parameters.keys():
        raise ValueError("source and target parameter structures differ")
    for name, target_parameter in target_parameters.items():
        source_parameter = source_parameters[name]
        target_parameter.mul_(1.0 - tau).add_(source_parameter, alpha=tau)
    source_buffers = dict(source.named_buffers())
    target_buffers = dict(target.named_buffers())
    for name, target_buffer in target_buffers.items():
        source_buffer = source_buffers[name]
        if target_buffer.is_floating_point():
            target_buffer.mul_(1.0 - tau).add_(source_buffer, alpha=tau)
        else:
            target_buffer.copy_(source_buffer)


def td_target(
    target_critic: QVGMCriticEnsemble,
    batch: dict[str, torch.Tensor],
    *,
    next_action_source: str,
) -> torch.Tensor:
    """Compute a detached ensemble-mean H-step TD target."""
    mapping = {
        "reference": ("next_ref_chunk", "next_ref_chunk_mask"),
        "dataset": ("next_action_chunk_executed", "next_action_mask"),
    }
    if next_action_source not in mapping:
        raise ValueError(f"unsupported next action source: {next_action_source}")
    action_key, mask_key = mapping[next_action_source]
    with torch.no_grad():
        # Q-VGM trains and improves against the ensemble mean.  The CQL term
        # remains per-head, while the Bellman continuation uses \bar Q.
        next_q = target_critic.mean_value(
            batch["next_z_state"],
            batch["next_proprio"],
            batch[action_key],
            batch[mask_key],
        )
        return batch["reward"].float() + (
            batch["discount"].float() * batch["bootstrap_mask"].float() * next_q
        )


def td_ensemble_loss(
    critic: QVGMCriticEnsemble,
    target_critic: QVGMCriticEnsemble,
    batch: dict[str, torch.Tensor],
    *,
    next_action_source: str,
) -> tuple[torch.Tensor, dict[str, torch.Tensor]]:
    target = td_target(target_critic, batch, next_action_source=next_action_source)
    prediction = critic(
        batch["z_state"],
        batch["proprio"],
        batch["action_chunk_executed"],
        batch["action_mask"],
    )
    loss = F.mse_loss(prediction, target.expand_as(prediction))
    return loss, {"prediction": prediction, "target": target}


def evaluate_action_candidates(
    critic: QVGMCriticEnsemble,
    z_state: torch.Tensor,
    proprio: torch.Tensor,
    candidates: torch.Tensor,
    action_mask: torch.Tensor,
) -> torch.Tensor:
    """Evaluate [B,N,H,D] candidates and return [B,N,E] ensemble values."""
    if candidates.ndim != 4:
        raise ValueError("candidates must be [B,N,H,D]")
    batch_size, candidate_count = candidates.shape[:2]
    expanded_z = z_state[:, None].expand(-1, candidate_count, -1).reshape(
        batch_size * candidate_count, -1
    )
    expanded_proprio = proprio[:, None].expand(-1, candidate_count, -1).reshape(
        batch_size * candidate_count, -1
    )
    expanded_mask = action_mask[:, None].expand(-1, candidate_count, -1).reshape(
        batch_size * candidate_count, -1
    )
    values = critic(
        expanded_z,
        expanded_proprio,
        candidates.reshape(batch_size * candidate_count, *candidates.shape[-2:]),
        expanded_mask,
    )
    return values.reshape(batch_size, candidate_count, -1)


def cql_conservative_loss(
    critic: QVGMCriticEnsemble,
    batch: dict[str, torch.Tensor],
    *,
    random_action_count: int = 10,
    reference_noise_std: float = 0.1,
    temperature: float = 1.0,
    calibration_floor: torch.Tensor | None = None,
) -> tuple[torch.Tensor, dict[str, torch.Tensor]]:
    """Penalize high values on uniform and locally perturbed OOD chunks."""
    if random_action_count <= 0 or temperature <= 0:
        raise ValueError("random_action_count and temperature must be positive")
    data_q = critic(
        batch["z_state"], batch["proprio"], batch["action_chunk_executed"], batch["action_mask"]
    )
    shape = (len(data_q), random_action_count, *batch["action_chunk_executed"].shape[-2:])
    uniform = torch.empty(shape, device=data_q.device).uniform_(-1.0, 1.0)
    # Cal-QL's local candidates are centered on the behavior action stored in
    # the fixed rollout dataset, matching the paper's fully offline critic.
    reference = batch["action_chunk_executed"][:, None].expand(
        -1, random_action_count, -1, -1
    )
    perturbed = (reference + torch.randn_like(reference) * reference_noise_std).clamp(-1.0, 1.0)
    candidates = torch.cat([uniform, perturbed], dim=1)
    candidate_q = evaluate_action_candidates(
        critic, batch["z_state"], batch["proprio"], candidates, batch["action_mask"]
    )
    conservative_candidates = candidate_q
    if calibration_floor is not None:
        floor = calibration_floor.float().reshape(len(data_q), 1, 1)
        conservative_candidates = torch.maximum(candidate_q, floor)
    conservative = temperature * torch.logsumexp(
        conservative_candidates / temperature, dim=1
    )
    conservative = conservative - temperature * torch.log(
        torch.tensor(candidate_q.shape[1], device=data_q.device, dtype=data_q.dtype)
    )
    loss = (conservative - data_q).mean()
    return loss, {
        "data_q": data_q,
        "candidate_q": candidate_q,
        "conservative_candidate_q": conservative_candidates,
        "conservative_q": conservative,
    }
