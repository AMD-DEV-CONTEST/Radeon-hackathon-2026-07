"""Test-time Q selection over independently sampled policy action chunks."""

from __future__ import annotations

import torch

from .qvgm_critic import QVGMCriticEnsemble


def repeat_policy_batch(batch: dict, repeats: int) -> dict:
    """Repeat each prepared policy row contiguously for candidate sampling."""
    if repeats < 2:
        raise ValueError("repeats must be at least two")
    output = {}
    for key, value in batch.items():
        if torch.is_tensor(value):
            output[key] = value.repeat_interleave(repeats, dim=0)
        elif key == "task":
            tasks = [value] if isinstance(value, str) else list(value)
            output[key] = [task for task in tasks for _ in range(repeats)]
        else:
            raise TypeError(f"cannot repeat prepared policy field {key!r}")
    return output


def select_best_action_chunk(
    critic: QVGMCriticEnsemble,
    z_state: torch.Tensor,
    proprio: torch.Tensor,
    candidates: torch.Tensor,
    action_mask: torch.Tensor | None = None,
) -> tuple[torch.Tensor, dict[str, torch.Tensor]]:
    """Select the ensemble-mean-Q argmax from ``[B,N,H,D]`` candidates.

    This baseline is deliberately gradient-free: candidates come from the
    frozen policy, are scored without action optimization, and the selected
    chunk is returned unchanged.
    """
    if candidates.ndim != 4:
        raise ValueError("candidates must be [B,N,H,D]")
    batch_size, candidate_count, horizon, action_dim = candidates.shape
    if candidate_count < 2:
        raise ValueError("Q selection requires at least two candidates")
    expected = (critic.config.horizon, critic.config.action_dim)
    if (horizon, action_dim) != expected:
        raise ValueError(f"candidate chunks must end in {expected}")
    if z_state.shape[0] != batch_size or proprio.shape[0] != batch_size:
        raise ValueError("state and candidate batch sizes do not match")
    if action_mask is None:
        action_mask = torch.ones(
            batch_size, horizon, dtype=torch.bool, device=candidates.device
        )
    if tuple(action_mask.shape) != (batch_size, horizon):
        raise ValueError("action_mask must be [B,H]")

    expanded_z = z_state[:, None].expand(-1, candidate_count, -1).reshape(
        batch_size * candidate_count, -1
    )
    expanded_proprio = proprio[:, None].expand(-1, candidate_count, -1).reshape(
        batch_size * candidate_count, -1
    )
    expanded_mask = action_mask[:, None].expand(-1, candidate_count, -1).reshape(
        batch_size * candidate_count, horizon
    )
    with torch.no_grad():
        ensemble_values = critic(
            expanded_z,
            expanded_proprio,
            candidates.reshape(batch_size * candidate_count, horizon, action_dim),
            expanded_mask,
        ).reshape(batch_size, candidate_count, -1)
        mean_values = ensemble_values.mean(dim=-1)
        selected_index = mean_values.argmax(dim=1)
        batch_index = torch.arange(batch_size, device=candidates.device)
        selected = candidates[batch_index, selected_index]
        selected_q = mean_values[batch_index, selected_index]
    return selected, {
        "candidate_q": mean_values,
        "candidate_ensemble_q": ensemble_values,
        "selected_index": selected_index,
        "selected_q": selected_q,
        "first_candidate_q": mean_values[:, 0],
        "candidate_q_std": mean_values.std(dim=1, unbiased=False),
        "selected_disagreement": ensemble_values[batch_index, selected_index].std(
            dim=-1, unbiased=False
        ),
    }
