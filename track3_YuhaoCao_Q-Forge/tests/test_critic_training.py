import copy

import torch

from smolvla_qvgm_rlinf.models.critic_training import (
    cql_conservative_loss,
    evaluate_action_candidates,
    polyak_update,
    td_target,
)
from smolvla_qvgm_rlinf.models.qvgm_critic import QVGMCriticConfig, QVGMCriticEnsemble


def _critic():
    return QVGMCriticEnsemble(
        QVGMCriticConfig(
            z_dim=4,
            proprio_dim=2,
            proprio_feature_dim=2,
            action_dim=2,
            horizon=2,
            hidden_dim=8,
            ensemble_size=2,
        )
    )


def test_polyak_update_endpoints_and_midpoint():
    source = _critic()
    target = copy.deepcopy(source)
    with torch.no_grad():
        for parameter in source.parameters():
            parameter.fill_(2.0)
        for parameter in target.parameters():
            parameter.zero_()
    polyak_update(source, target, tau=0.25)
    assert all(torch.allclose(parameter, torch.full_like(parameter, 0.5)) for parameter in target.parameters())


def test_td_target_respects_discount_done_and_dataset_action_source():
    critic = _critic().eval()
    batch = {
        "next_z_state": torch.randn(2, 4),
        "next_proprio": torch.randn(2, 2),
        "next_ref_chunk": torch.randn(2, 2, 2),
        "next_ref_chunk_mask": torch.ones(2, 2, dtype=torch.bool),
        "next_action_chunk_executed": torch.randn(2, 2, 2),
        "next_action_mask": torch.ones(2, 2, dtype=torch.bool),
        "reward": torch.tensor([[1.0], [2.0]]),
        "discount": torch.tensor([[0.5], [0.5]]),
        "bootstrap_mask": torch.tensor([[1.0], [0.0]]),
    }
    expected_next = critic.mean_value(
        batch["next_z_state"],
        batch["next_proprio"],
        batch["next_action_chunk_executed"],
        batch["next_action_mask"],
    )
    result = td_target(critic, batch, next_action_source="dataset")
    assert torch.allclose(result[0], 1.0 + 0.5 * expected_next[0])
    assert result[1].item() == 2.0
    assert not result.requires_grad


def test_candidate_evaluation_and_cql_are_finite_and_differentiable():
    critic = _critic()
    batch = {
        "z_state": torch.randn(3, 4),
        "proprio": torch.randn(3, 2),
        "action_chunk_executed": torch.randn(3, 2, 2).clamp(-1, 1),
        "action_mask": torch.ones(3, 2, dtype=torch.bool),
        "ref_chunk": torch.randn(3, 2, 2).clamp(-1, 1),
    }
    candidates = torch.randn(3, 5, 2, 2).clamp(-1, 1)
    values = evaluate_action_candidates(
        critic, batch["z_state"], batch["proprio"], candidates, batch["action_mask"]
    )
    loss, details = cql_conservative_loss(critic, batch, random_action_count=3)
    loss.backward()
    assert values.shape == (3, 5, 2)
    assert details["candidate_q"].shape == (3, 6, 2)
    assert torch.isfinite(loss)
    assert any(parameter.grad is not None for parameter in critic.parameters())


def test_calql_floor_is_applied_to_conservative_candidates():
    critic = _critic()
    batch = {
        "z_state": torch.randn(2, 4),
        "proprio": torch.randn(2, 2),
        "action_chunk_executed": torch.zeros(2, 2, 2),
        "action_mask": torch.ones(2, 2, dtype=torch.bool),
        "ref_chunk": torch.zeros(2, 2, 2),
    }
    floor = torch.full((2, 1), 10.0)
    _, details = cql_conservative_loss(
        critic, batch, random_action_count=2, calibration_floor=floor
    )
    assert torch.all(details["conservative_candidate_q"] >= 10.0)
