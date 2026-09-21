import torch

from smolvla_qvgm_rlinf.models.prefix_features import RLTFeatureConfig, make_rlt_module


def test_small_rlt_autoencoder_shapes_and_gradient():
    config = RLTFeatureConfig(
        input_dim=8,
        embed_dim=16,
        num_rl_tokens=1,
        prefix_seq_len=4,
        num_layers=1,
        num_heads=4,
        mlp_ratio=1.0,
    )
    model = make_rlt_module(config)
    hidden = torch.randn(3, 4, 8)
    mask = torch.tensor([[True, True, True, False]]).expand(3, -1)
    loss, details = model(hidden, mask)
    loss.backward()
    assert details["z_rl"].shape == (3, 16)
    assert torch.isfinite(loss)
    assert any(parameter.grad is not None for parameter in model.parameters())
