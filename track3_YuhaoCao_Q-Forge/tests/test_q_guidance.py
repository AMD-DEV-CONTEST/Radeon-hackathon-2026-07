import torch

from smolvla_qvgm_rlinf.models.q_guidance import QGuidanceConfig, guide_action_chunk
from smolvla_qvgm_rlinf.models.qvgm_critic import QVGMCriticConfig, QVGMCriticEnsemble


def test_guidance_keeps_base_candidate_and_respects_constraints():
    critic = QVGMCriticEnsemble(
        QVGMCriticConfig(z_dim=4, proprio_dim=2, proprio_feature_dim=2, action_dim=2, horizon=2, hidden_dim=8, ensemble_size=2)
    ).eval()
    z = torch.randn(5, 4)
    proprio = torch.randn(5, 2)
    base = torch.empty(5, 2, 2).uniform_(-0.8, 0.8)
    mask = torch.tensor([[True, True], [True, False], [True, True], [True, True], [True, False]])
    guided, info = guide_action_chunk(
        critic, z, proprio, base, mask, QGuidanceConfig(steps=4, step_size=0.1, max_delta=0.05)
    )
    assert torch.all(info["best_q"] >= info["base_q"])
    assert torch.max(torch.abs(guided - base)) <= 0.050001
    assert torch.all(guided <= 1) and torch.all(guided >= -1)
    assert torch.equal(guided[~mask], base[~mask])
    assert torch.isfinite(info["gradient_norm"]).all()


def test_guidance_can_optimize_only_executed_prefix():
    critic = QVGMCriticEnsemble(
        QVGMCriticConfig(z_dim=4, proprio_dim=2, proprio_feature_dim=2, action_dim=2, horizon=2, hidden_dim=8, ensemble_size=2)
    ).eval()
    base = torch.zeros(3, 2, 2)
    guided, _ = guide_action_chunk(
        critic,
        torch.randn(3, 4),
        torch.randn(3, 2),
        base,
        torch.ones(3, 2, dtype=torch.bool),
        QGuidanceConfig(steps=3, step_size=0.1, optimize_prefix_steps=1),
    )
    assert torch.equal(guided[:, 1], base[:, 1])


def test_guidance_can_preserve_uncovered_action_dimensions():
    critic = QVGMCriticEnsemble(
        QVGMCriticConfig(
            z_dim=4,
            proprio_dim=2,
            proprio_feature_dim=2,
            action_dim=7,
            horizon=2,
            hidden_dim=8,
            ensemble_size=2,
        )
    ).eval()
    base = torch.zeros(3, 2, 7)
    guided, _ = guide_action_chunk(
        critic,
        torch.randn(3, 4),
        torch.randn(3, 2),
        base,
        torch.ones(3, 2, dtype=torch.bool),
        QGuidanceConfig(steps=3, step_size=0.1, optimize_action_dims=6),
    )
    assert torch.equal(guided[..., 6], base[..., 6])
