import torch

from smolvla_qvgm_rlinf.models.qvgm_critic import QVGMCriticConfig, QVGMCriticEnsemble


def _critic():
    return QVGMCriticEnsemble(
        QVGMCriticConfig(
            z_dim=16,
            proprio_dim=4,
            proprio_feature_dim=8,
            action_dim=3,
            horizon=2,
            hidden_dim=32,
            first_hidden_dim=32,
            ensemble_size=5,
        )
    )


def test_critic_shapes_finite_and_action_gradient():
    critic = _critic()
    z = torch.randn(7, 16)
    proprio = torch.randn(7, 4)
    action = torch.randn(7, 2, 3, requires_grad=True)
    values = critic(z, proprio, action)
    values.mean().backward()
    assert values.shape == (7, 5)
    assert torch.isfinite(values).all()
    assert action.grad is not None
    assert torch.isfinite(action.grad).all()
    assert action.grad.norm() > 0


def test_action_mask_removes_padded_action_effect():
    critic = _critic().eval()
    z = torch.randn(2, 16)
    proprio = torch.randn(2, 4)
    first = torch.randn(2, 2, 3)
    second = first.clone()
    second[:, 1] = 999
    mask = torch.tensor([[True, False], [True, False]])
    assert torch.equal(critic(z, proprio, first, mask), critic(z, proprio, second, mask))


def test_conservative_value_and_disagreement():
    critic = _critic().eval()
    args = (torch.randn(3, 16), torch.randn(3, 4), torch.randn(3, 2, 3))
    ensemble = critic(*args)
    assert torch.equal(critic.conservative_value(*args), ensemble.min(-1, keepdim=True).values)
    assert torch.equal(critic.mean_value(*args), ensemble.mean(-1, keepdim=True))
    assert critic.disagreement(*args).shape == (3, 1)


def test_paper_aligned_joint_state_norm_and_two_hidden_widths():
    critic = QVGMCriticEnsemble(
        QVGMCriticConfig(
            z_dim=16,
            proprio_dim=4,
            proprio_feature_dim=8,
            action_dim=3,
            horizon=2,
            first_hidden_dim=64,
            hidden_dim=32,
            ensemble_size=2,
            joint_state_norm=True,
        )
    )
    values = critic(torch.randn(2, 16), torch.randn(2, 4), torch.randn(2, 2, 3))
    assert values.shape == (2, 2)
    assert critic.q_networks[0].input_layer[0].out_features == 64
    assert critic.q_networks[0].hidden_layer[0].out_features == 32
