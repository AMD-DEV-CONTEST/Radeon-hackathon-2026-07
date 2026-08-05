import torch

from smolvla_qvgm_rlinf.models.prefix_features import (
    make_fixed_projection,
    pool_prefix_hidden,
)


def test_fixed_projection_is_deterministic_and_seeded():
    first = make_fixed_projection(8, 4, seed=17)
    second = make_fixed_projection(8, 4, seed=17)
    different = make_fixed_projection(8, 4, seed=18)
    assert torch.equal(first, second)
    assert not torch.equal(first, different)


def test_pool_ignores_padding_and_is_finite():
    hidden = torch.tensor([[[1.0, 2.0], [2.0, 1.0], [999.0, -999.0]]])
    projection = torch.eye(2)
    result = pool_prefix_hidden(hidden, torch.tensor([[True, True, False]]), projection)
    expected = pool_prefix_hidden(hidden[:, :2], torch.tensor([[True, True]]), projection)
    assert torch.allclose(result, expected)
    assert result.shape == (1, 2)
    assert torch.isfinite(result).all()


def test_pool_rejects_empty_prefix():
    hidden = torch.zeros(1, 2, 4)
    try:
        pool_prefix_hidden(hidden, torch.zeros(1, 2, dtype=torch.bool), torch.ones(4, 3))
    except ValueError as error:
        assert "at least one valid token" in str(error)
    else:
        raise AssertionError("empty prefix should fail")
