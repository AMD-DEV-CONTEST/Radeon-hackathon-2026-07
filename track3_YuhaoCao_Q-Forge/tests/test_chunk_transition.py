import numpy as np
import pytest

from smolvla_qvgm_rlinf.data.chunk_transition import build_chunk_transitions


def _episode(rewards, *, terminated_at=None, truncated_at=None):
    length = len(rewards)
    terminated = [False] * length
    truncated = [False] * length
    if terminated_at is not None:
        terminated[terminated_at] = True
    if truncated_at is not None:
        truncated[truncated_at] = True
    return {
        "actions": [np.full(7, index, dtype=np.float32) for index in range(length)],
        "observations": [
            {"states": np.full(8, index, dtype=np.float32)} for index in range(length + 1)
        ],
        "rewards": [0.0, *rewards],
        "terminated": [False, *terminated],
        "truncated": [False, *truncated],
        "infos": [{} for _ in range(length + 1)],
    }


def test_chunk_reward_mc_return_and_bootstrap():
    transitions = build_chunk_transitions(
        _episode([0.0, 0.0, 1.0], terminated_at=2), horizon=2, gamma=0.5
    )
    assert transitions.chunk_reward[:, 0].tolist() == pytest.approx([0.0, 0.5, 1.0])
    assert transitions.mc_return[:, 0].tolist() == pytest.approx([0.25, 0.5, 1.0])
    assert transitions.bootstrap_mask[:, 0].tolist() == [1.0, 0.0, 0.0]


def test_padding_and_next_chunk_do_not_cross_episode():
    transitions = build_chunk_transitions(_episode([0.0, 0.0, 0.0]), horizon=2)
    assert transitions.action_mask.tolist() == [[True, True], [True, True], [True, False]]
    assert transitions.action_chunk[2, :, 0].tolist() == [2.0, 2.0]
    assert transitions.next_action_mask.tolist() == [[True, False], [False, False], [False, False]]
    assert transitions.done[:, 0].tolist() == [False, True, True]


def test_truncation_disables_bootstrap():
    transitions = build_chunk_transitions(_episode([0.0, 0.0], truncated_at=1), horizon=1)
    assert transitions.bootstrap_mask[:, 0].tolist() == [1.0, 0.0]

