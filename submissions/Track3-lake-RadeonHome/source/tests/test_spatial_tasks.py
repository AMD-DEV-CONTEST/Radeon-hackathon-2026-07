from radeon_home.spatial_tasks import (
    INFLATION_CELLS,
    build_room_grid,
    evaluate_tasks,
    generate_task,
    plan_transport,
)


def test_room_obstacles_include_robot_footprint() -> None:
    assert INFLATION_CELLS >= 1
    grid = build_room_grid()
    assert len(grid.occupied) > 0


def test_generated_task_has_two_valid_paths() -> None:
    grid = build_room_grid()
    result = plan_transport(generate_task(20260729, grid), grid)
    assert result.pickup_path
    assert result.delivery_path
    assert result.total_distance_m > 0
    assert not set(result.pickup_path) & grid.occupied
    assert not set(result.delivery_path) & grid.occupied


def test_batch_planning_is_reproducible() -> None:
    first = evaluate_tasks(count=20, seed=7)
    second = evaluate_tasks(count=20, seed=7)
    assert first == second
    assert first["planning_success_rate"] == 1.0

