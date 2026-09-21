from smolvla_qvgm_rlinf.data.collection_plan import (
    make_plan,
    make_suite_plan,
    parse_states,
)


def test_parse_states_and_weighted_plan():
    states = parse_states("0-2,5")
    plan = make_plan(states, {0, 5})
    assert states == [0, 1, 2, 5]
    assert sum(item.state_id == 0 for item in plan) == 6
    assert sum(item.state_id == 1 for item in plan) == 3
    assert sum(item.state_id == 2 for item in plan) == 3
    assert sum(item.state_id == 5 for item in plan) == 6
    assert len({item.key for item in plan}) == len(plan)


def test_suite_plan_is_exact_and_task_state_unique():
    plan = make_suite_plan(list(range(10)), list(range(30)))
    assert len(plan) == 300
    assert len({item.key for item in plan}) == 300
    assert sum(item.task_id == 7 for item in plan) == 30
    assert sum(item.state_id == 12 for item in plan) == 10
