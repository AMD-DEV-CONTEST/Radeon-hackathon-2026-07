import pytest
import torch

from smolvla_qvgm_rlinf.data.feature_cache import state_stratified_split, within_state_episode_split


def test_state_stratified_split_keeps_all_episodes_for_state_together():
    manifest = {
        "episodes": [
            {"task_reset_state_id": 0, "transitions": 2, "success": False},
            {"task_reset_state_id": 1, "transitions": 3, "success": True},
            {"task_reset_state_id": 0, "transitions": 1, "success": True},
            {"task_reset_state_id": 2, "transitions": 2, "success": False},
        ]
    }
    train, validation, success = state_stratified_split(manifest, {0, 2})

    assert torch.equal(train, torch.tensor([2, 3, 4]))
    assert torch.equal(validation, torch.tensor([0, 1, 5, 6, 7]))
    assert torch.equal(
        success,
        torch.tensor([False, False, True, True, True, True, False, False]),
    )


def test_state_stratified_split_rejects_missing_state_metadata():
    manifest = {"episodes": [{"transitions": 2, "success": True}]}
    with pytest.raises(ValueError, match="task_reset_state_id"):
        state_stratified_split(manifest, {0})


def test_state_stratified_split_rejects_unknown_validation_state():
    manifest = {
        "episodes": [
            {"task_reset_state_id": 0, "transitions": 2, "success": True},
            {"task_reset_state_id": 1, "transitions": 2, "success": False},
        ]
    }
    with pytest.raises(ValueError, match="absent"):
        state_stratified_split(manifest, {9})


def test_within_state_episode_split_holds_out_latest_third_per_state():
    episodes = []
    for state_id, count in ((0, 3), (1, 6)):
        for repeat_id in range(count):
            episodes.append(
                {
                    "task_reset_state_id": state_id,
                    "repeat_id": repeat_id,
                    "transitions": 1,
                    "success": repeat_id % 2 == 0,
                }
            )
    train, validation, success = within_state_episode_split(
        {"episodes": episodes}, validation_fraction=1 / 3
    )
    assert torch.equal(train, torch.tensor([0, 1, 3, 4, 5, 6]))
    assert torch.equal(validation, torch.tensor([2, 7, 8]))
    assert len(success) == 9


def test_within_state_episode_split_rejects_duplicate_repeats():
    manifest = {
        "episodes": [
            {"task_reset_state_id": 0, "repeat_id": 0, "transitions": 1, "success": True},
            {"task_reset_state_id": 0, "repeat_id": 0, "transitions": 1, "success": False},
        ]
    }
    with pytest.raises(ValueError, match="duplicate repeat_id"):
        within_state_episode_split(manifest)
