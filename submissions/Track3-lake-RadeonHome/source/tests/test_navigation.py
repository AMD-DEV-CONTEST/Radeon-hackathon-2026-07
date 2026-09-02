import pytest

from radeon_home.navigation import GridMap, astar, simplify_path


def test_astar_routes_around_obstacle() -> None:
    grid = GridMap(
        width=7,
        height=7,
        resolution_m=0.25,
        origin_xy=(-0.75, -0.75),
        occupied=frozenset({(3, 1), (3, 2), (3, 3), (3, 4), (3, 5)}),
    )
    path = astar(grid, (1, 3), (5, 3))
    assert path[0] == (1, 3)
    assert path[-1] == (5, 3)
    assert not set(path) & grid.occupied
    assert len(simplify_path(path)) < len(path)


def test_astar_rejects_occupied_goal() -> None:
    grid = GridMap(3, 3, 1.0, (0.0, 0.0), frozenset({(2, 2)}))
    with pytest.raises(ValueError, match="Goal cell"):
        astar(grid, (0, 0), (2, 2))

