import numpy as np
import torch

from sparse_view_plant.plant_fusion import (
    conflict_aware_budget_indices,
    front_conflict_counts,
)


def test_conflict_budget_prioritizes_visibility_before_confidence() -> None:
    confidence = np.asarray([0.9, 0.8, 0.2, 0.1], dtype=np.float32)
    conflicts = np.asarray([2, 1, 0, 0], dtype=np.int16)
    selected = conflict_aware_budget_indices(confidence, conflicts, 0.5)
    np.testing.assert_array_equal(selected, [2, 3])


def test_front_conflict_ignores_source_and_counts_other_view() -> None:
    points = torch.tensor([[0.0, 0.0, 1.0]])
    sources = torch.tensor([0])
    cameras = torch.eye(4).repeat(2, 1, 1)
    intrinsics = torch.tensor([[[1.0, 0.0, 0.5], [0.0, 1.0, 0.5], [0.0, 0.0, 1.0]]] * 2)
    masks = torch.ones(2, 2, 2)
    depth = torch.stack([torch.full((2, 2), 2.0), torch.full((2, 2), 2.0)])
    conflicts = front_conflict_counts(
        points,
        sources,
        cameras,
        intrinsics,
        masks,
        depth,
        depth_tolerance=0.1,
    )
    assert conflicts.tolist() == [1]
