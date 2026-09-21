import numpy as np
import torch

from smolvla_qvgm_rlinf.data.feature_cache import (
    episode_reference_chunks,
    next_reference_chunks,
    observation_indices,
)


def _episode(length=4, predicted_horizon=6):
    infos = [{}]
    for step in range(length):
        infos.append(
            {
                "predicted_action_chunk": np.full(
                    (predicted_horizon, 7), step / 10, dtype=np.float32
                )
            }
        )
    return {"infos": infos}


def test_reference_and_next_reference_alignment():
    reference, mask = episode_reference_chunks(_episode(), horizon=2)
    next_reference, next_mask = next_reference_chunks(reference, mask, horizon=2)
    assert reference.shape == (4, 2, 7)
    torch.testing.assert_close(reference[:, 0, 0], torch.tensor([0.0, 0.1, 0.2, 0.3]))
    torch.testing.assert_close(next_reference[:, 0, 0], torch.tensor([0.2, 0.3, 0.0, 0.0]))
    assert next_mask.tolist() == [[True, True], [True, True], [False, False], [False, False]]


def test_reference_chunks_use_executable_action_domain():
    episode = _episode()
    episode["infos"][1]["predicted_action_chunk"][0, 0] = 1.25
    episode["infos"][2]["predicted_action_chunk"][0, 0] = -1.25

    reference, _ = episode_reference_chunks(episode, horizon=2)

    assert reference[0, 0, 0] == 1.0
    assert reference[1, 0, 0] == -1.0


def test_observation_indices_clip_only_at_episode_boundary():
    current, next_indices = observation_indices(4, horizon=2)
    assert current.tolist() == [0, 1, 2, 3]
    assert next_indices.tolist() == [2, 3, 4, 4]
