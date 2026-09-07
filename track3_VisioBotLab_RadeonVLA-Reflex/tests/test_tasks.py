import numpy as np
import pytest

from radeonvla.grounding import ATTRIBUTES, _expand_attribute_goals, _select_spatial
from radeonvla.tasks import L1_TASKS, L2_TASKS, L3_TASKS, L4_TASKS, SUITES, TASKS, get_task, list_task_ids


def test_registry_contains_all_tiers() -> None:
    assert set(L1_TASKS).issubset(TASKS)
    assert set(L2_TASKS).issubset(TASKS)
    assert set(L3_TASKS).issubset(TASKS)
    assert set(L4_TASKS).issubset(TASKS)
    # 5 fruits × 4 bowls = 20 L1 tasks, plus spatial / multi-step / rules.
    assert len(L1_TASKS) == 20
    assert "apple_blue_left" in L1_TASKS
    assert "banana_white_left" in L1_TASKS
    assert "orange_blue_right" in L1_TASKS
    assert len(TASKS) >= 30


def test_suites_partition_is_consistent() -> None:
    assert set(SUITES["basic"]) == set(L1_TASKS)
    assert set(SUITES["full"]) == set(TASKS)
    assert set(SUITES["advanced"]).isdisjoint(set())  # non-empty advanced set
    assert len(SUITES["advanced"]) >= 8


def test_training_and_evaluation_language_are_separate() -> None:
    for task in TASKS.values():
        assert task.training_instructions
        assert task.evaluation_instructions
        assert set(task.training_instructions).isdisjoint(task.evaluation_instructions)


def test_l1_default_evaluation_instruction_names_the_fruit() -> None:
    for task_id in L1_TASKS:
        task = get_task(task_id)
        assert task.target_object in task.evaluation_instructions[0].lower()


def test_l3_is_multi_step() -> None:
    task = get_task("seq_banana_white_left_lemon_white_right")
    assert task.tier == "L3"
    assert task.is_multi_step
    assert len(task.goals) == 2


def test_l4_attribute_expansion() -> None:
    task = get_task("rule_yellow_white_left_purple_white_right")
    expanded = _expand_attribute_goals(task.goals)
    names = [g.object_name for g in expanded]
    assert "banana" in names and "lemon" in names and "plum" in names
    assert ATTRIBUTES["yellow"] == frozenset({"banana", "lemon"})
    assert ATTRIBUTES["red"] == frozenset({"apple"})
    assert ATTRIBUTES["orange"] == frozenset({"orange"})


def test_new_fruits_and_bowls_in_l1() -> None:
    apple = get_task("apple_blue_left")
    assert apple.target_object == "apple"
    assert apple.target_container == "blue_left_bowl"
    banana = get_task("banana_white_left")
    assert banana.target_container == "white_left_bowl"
    orange = get_task("orange_white_right")
    assert orange.target_container == "white_right_bowl"


def test_spatial_grounding_uses_table_axes() -> None:
    positions = {
        "banana": np.array([0.3, 0.2, 0.8]),
        "lemon": np.array([0.4, -0.1, 0.8]),
        "plum": np.array([0.5, 0.0, 0.8]),
    }
    assert _select_spatial(positions, "leftmost") == "banana"
    assert _select_spatial(positions, "rightmost") == "lemon"
    assert _select_spatial(positions, "nearest_robot") == "banana"
    assert _select_spatial(positions, "farthest_robot") == "plum"


def test_unknown_task_fails_clearly() -> None:
    with pytest.raises(ValueError, match="Unknown task"):
        get_task("kiwi_purple")


def test_list_task_ids_suite() -> None:
    ids = list_task_ids("multistep")
    assert all(tid in L3_TASKS for tid in ids)
