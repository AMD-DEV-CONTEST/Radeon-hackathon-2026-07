"""Shape contracts for the RGB + proprioception policy modules."""

import pytest

torch = pytest.importorskip("torch")

from algorithms.vision_actor_critic import SpatialSoftmax, VisualActorCritic


def test_spatial_softmax_and_visual_actor_critic_shapes():
    spatial = SpatialSoftmax(height=4, width=5, channels=3)
    assert spatial(torch.zeros(2, 3, 4, 5)).shape == (2, 6)

    model = VisualActorCritic(
        image_height=96, image_width=96, proprio_dim=25, action_dim=9,
    )
    action, logprob, entropy, value = model.get_action_and_value(
        torch.zeros(2, 96, 96, 3, dtype=torch.uint8), torch.zeros(2, 25),
    )
    assert action.shape == (2, 9)
    assert logprob.shape == entropy.shape == (2,)
    assert value.shape == (2, 1)
