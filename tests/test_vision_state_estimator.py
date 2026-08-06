import torch

from algorithms.vision_state_estimator import VisualTaskStateEstimator


def test_visual_task_state_estimator_shape():
    model = VisualTaskStateEstimator(image_height=96, image_width=96, proprio_dim=25)
    estimate = model(torch.zeros(2, 96, 96, 3, dtype=torch.uint8), torch.zeros(2, 25))
    assert estimate.shape == (2, 6)
