from types import SimpleNamespace

import torch
from torch import nn

from smolvla_qvgm_rlinf.models.qvgm_residual import (
    QVGMResidualConfig,
    bound_residual_norm,
    conservative_target_confidence,
    configure_qvgm_trainable_parameters,
    effective_residual_velocity,
    environment_to_model_action,
    improve_model_clean_action,
    model_to_environment_action,
)


class QuadraticCritic(nn.Module):
    def __init__(self, target):
        super().__init__()
        self.register_buffer("target", target)

    def mean_value(self, z_state, proprio, action, action_mask=None):
        del z_state, proprio, action_mask
        return -(action - self.target).square().flatten(1).sum(dim=1, keepdim=True)


def test_action_coordinate_roundtrip():
    model = torch.randn(3, 5, 7)
    mean = torch.linspace(-0.2, 0.2, 7)
    std = torch.linspace(0.5, 1.1, 7)
    env = model_to_environment_action(model, mean, std)
    assert torch.allclose(environment_to_model_action(env, mean, std), model, atol=1e-6)


def test_effective_residual_projects_exactly_to_improved_clean_action():
    x_t = torch.randn(2, 4, 3)
    base_velocity = torch.randn_like(x_t)
    improved = torch.randn_like(x_t)
    time = torch.tensor([0.25, 0.8])
    clean, residual = effective_residual_velocity(x_t, base_velocity, improved, time)
    projected = x_t - time[:, None, None] * (base_velocity + residual)
    assert torch.allclose(clean, x_t - time[:, None, None] * base_velocity)
    assert torch.allclose(projected, improved, atol=1e-6)


def test_conservative_confidence_rejects_low_advantage_and_penalizes_uncertainty():
    config = QVGMResidualConfig(
        use_confidence_gate=True,
        advantage_threshold=0.01,
        advantage_soft_scale=0.02,
        uncertainty_scale=10.0,
        minimum_confidence=0.05,
    )
    advantage = torch.tensor([[0.005], [0.02], [0.02], [0.04]])
    disagreement = torch.tensor([[0.0], [0.0], [0.1], [0.0]])
    confidence = conservative_target_confidence(advantage, disagreement, config)
    assert confidence[0].item() == 0
    assert confidence[1] > confidence[2]
    assert confidence[3].item() == 1
    assert torch.all((confidence >= 0) & (confidence <= 1))


def test_confidence_gate_is_backward_compatible_when_disabled():
    config = QVGMResidualConfig(
        use_confidence_gate=False,
        advantage_threshold=0.5,
        uncertainty_scale=100.0,
    )
    confidence = conservative_target_confidence(
        torch.tensor([[0.0], [0.1]]),
        torch.tensor([[10.0], [10.0]]),
        config,
    )
    assert torch.equal(confidence, torch.ones_like(confidence))


def test_target_residual_norm_bound_is_per_sample():
    residual = torch.tensor([[[3.0, 4.0]], [[0.3, 0.4]]])
    bounded = bound_residual_norm(residual, 1.0)
    norms = bounded.flatten(1).norm(dim=1)
    assert torch.allclose(norms, torch.tensor([1.0, 0.5]))


def test_q_ascent_keep_best_and_preserves_unoptimized_model_dimensions():
    clean = torch.zeros(2, 6, 9)
    target = torch.full((1, 3, 2), 0.5)
    critic = QuadraticCritic(target)
    config = QVGMResidualConfig(
        denoising_steps=2,
        horizon=3,
        action_dim=2,
        guidance_steps=5,
        guidance_step_size=0.05,
        guidance_max_delta=0.2,
    )
    improved, details = improve_model_clean_action(
        clean,
        critic,
        torch.zeros(2, 4),
        torch.zeros(2, 8),
        torch.zeros(2),
        torch.ones(2),
        config,
    )
    assert torch.all(details["best_q"] >= details["base_q"])
    assert torch.any(improved[:, :3, :2] != 0)
    assert torch.equal(improved[:, 3:], clean[:, 3:])
    assert torch.equal(improved[:, :3, 2:], clean[:, :3, 2:])


class ParameterSelectionPolicy(nn.Module):
    def __init__(self):
        super().__init__()
        self.model = nn.Module()
        self.model.vlm_with_expert = nn.Module()
        self.model.vlm_with_expert.vlm = nn.Linear(2, 2)
        self.model.vlm_with_expert.lm_expert = nn.Linear(2, 2)
        self.model.action_in_proj = nn.Linear(2, 2)
        self.model.action_out_proj = nn.Linear(2, 2)
        self.model.action_time_mlp_in = nn.Linear(2, 2)
        self.model.action_time_mlp_out = nn.Linear(2, 2)
        self.model.state_proj = nn.Linear(2, 2)


def test_trainable_selection_is_action_expert_only():
    policy = ParameterSelectionPolicy()
    parameters, names = configure_qvgm_trainable_parameters(policy)
    assert parameters
    assert any("lm_expert" in name for name in names)
    assert not any("state_proj" in name or ".vlm." in name for name in names)
    selected = set(names)
    for name, parameter in policy.named_parameters():
        assert parameter.requires_grad == (name in selected)
