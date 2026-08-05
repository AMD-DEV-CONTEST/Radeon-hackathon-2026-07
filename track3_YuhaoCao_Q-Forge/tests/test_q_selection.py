from types import SimpleNamespace

import pytest
import torch
from torch import nn

from smolvla_qvgm_rlinf.models.q_selection import (
    repeat_policy_batch,
    select_best_action_chunk,
)


class SumCritic(nn.Module):
    def __init__(self):
        super().__init__()
        self.config = SimpleNamespace(horizon=2, action_dim=2)

    def forward(self, z_state, proprio, action_chunk, action_mask=None):
        del z_state, proprio
        action = action_chunk
        if action_mask is not None:
            action = action * action_mask.unsqueeze(-1)
        value = action.flatten(1).sum(dim=1, keepdim=True)
        return torch.cat([value, value], dim=1)


def test_selection_returns_unchanged_highest_mean_q_candidate():
    critic = SumCritic()
    candidates = torch.tensor(
        [
            [
                [[0.0, 0.0], [0.0, 0.0]],
                [[0.5, 0.5], [0.5, 0.5]],
                [[-0.5, -0.5], [-0.5, -0.5]],
            ],
            [
                [[0.2, 0.2], [0.2, 0.2]],
                [[0.1, 0.1], [0.1, 0.1]],
                [[0.3, 0.3], [0.3, 0.3]],
            ],
        ],
        requires_grad=True,
    )
    selected, info = select_best_action_chunk(
        critic,
        torch.zeros(2, 3),
        torch.zeros(2, 4),
        candidates,
    )
    assert info["selected_index"].tolist() == [1, 2]
    assert torch.equal(selected[0], candidates.detach()[0, 1])
    assert torch.equal(selected[1], candidates.detach()[1, 2])
    assert torch.all(info["selected_q"] >= info["first_candidate_q"])
    assert not selected.requires_grad


def test_selection_uses_mask_and_rejects_single_candidate():
    critic = SumCritic()
    candidates = torch.zeros(1, 2, 2, 2)
    candidates[0, 0, 1] = 1
    candidates[0, 1, 0] = 0.5
    selected, info = select_best_action_chunk(
        critic,
        torch.zeros(1, 3),
        torch.zeros(1, 4),
        candidates,
        torch.tensor([[True, False]]),
    )
    assert info["selected_index"].item() == 1
    assert torch.equal(selected, candidates[:, 1])
    with pytest.raises(ValueError, match="at least two"):
        select_best_action_chunk(
            critic,
            torch.zeros(1, 3),
            torch.zeros(1, 4),
            candidates[:, :1],
        )


def test_repeat_policy_batch_preserves_row_candidate_order():
    batch = {
        "observation.state": torch.tensor([[1.0], [2.0]]),
        "task": ["first", "second"],
    }
    repeated = repeat_policy_batch(batch, 3)
    assert repeated["observation.state"].flatten().tolist() == [1, 1, 1, 2, 2, 2]
    assert repeated["task"] == ["first", "first", "first", "second", "second", "second"]
