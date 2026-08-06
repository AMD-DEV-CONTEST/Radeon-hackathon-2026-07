import numpy as np

from sparse_view_plant.views import select_diverse_views


def _cameras_on_circle(view_count: int) -> np.ndarray:
    angles = np.linspace(0.0, 2.0 * np.pi, view_count, endpoint=False)
    positions = np.stack(
        [np.cos(angles), np.sin(angles), np.zeros_like(angles)], axis=1
    )
    c2w = np.tile(np.eye(4), (view_count, 1, 1))
    c2w[:, :3, 3] = positions
    return c2w


def test_selection_prefers_wide_baseline():
    view_count = 12
    c2w = _cameras_on_circle(view_count)
    ids = [f"v{i:02d}" for i in range(view_count)]
    selected = select_diverse_views(c2w, ids, count=3)
    indices = sorted(ids.index(view_id) for view_id in selected)
    # FPS on a ring of 12 should never pick three adjacent views (indices 0,1,2).
    assert len(selected) == 3
    assert len(set(selected)) == 3
    assert indices[1] - indices[0] >= 2
    assert indices[2] - indices[1] >= 2


def test_selection_returns_input_order_and_caps():
    c2w = _cameras_on_circle(6)
    ids = ["a", "b", "c", "d", "e", "f"]
    assert select_diverse_views(c2w, ids, count=10) == ids
    assert select_diverse_views(c2w, ids, count=0) == []
    selected = select_diverse_views(c2w, ids, count=3)
    assert selected == sorted(selected, key=ids.index)
