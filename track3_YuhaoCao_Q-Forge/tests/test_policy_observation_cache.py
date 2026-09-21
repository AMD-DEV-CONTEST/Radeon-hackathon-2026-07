import json

import pytest
import torch

from smolvla_qvgm_rlinf.data.policy_observation_cache import (
    QVGMPolicyObservationDataset,
    load_policy_observation_cache,
    prepare_cached_policy_batch,
    validate_policy_feature_alignment,
)


def payload(count=3):
    return {
        "main_images": torch.zeros(count, 4, 5, 3, dtype=torch.uint8),
        "wrist_images": torch.ones(count, 4, 5, 3, dtype=torch.uint8),
        "states": torch.arange(count * 2, dtype=torch.float32).reshape(count, 2),
        "episode_index": torch.zeros(count, dtype=torch.int32),
        "transition_index": torch.arange(count, dtype=torch.int32),
        "task_index": torch.zeros(count, dtype=torch.int16),
        "reset_state_id": torch.full((count,), 7, dtype=torch.int16),
    }


def test_mmap_dataset_joins_features_and_prepares_images(tmp_path):
    observations = payload()
    features = {
        "z_state": torch.randn(3, 8),
        "proprio": observations["states"].clone(),
    }
    observation_path = tmp_path / "observations.pt"
    feature_path = tmp_path / "features.pt"
    manifest_path = tmp_path / "manifest.json"
    torch.save(observations, observation_path)
    torch.save(features, feature_path)
    manifest_path.write_text(json.dumps({"tasks": ["do the task"]}))
    loaded = load_policy_observation_cache(observation_path)
    assert torch.equal(loaded["states"], observations["states"])
    dataset = QVGMPolicyObservationDataset(observation_path, manifest_path, feature_path)
    item = dataset[1]
    assert item["task"] == "do the task"
    assert torch.equal(item["z_state"], features["z_state"][1])
    batch = prepare_cached_policy_batch(
        {
            "observation.images.agentview": observations["main_images"][:2],
            "observation.images.wrist": observations["wrist_images"][:2],
            "observation.state": observations["states"][:2],
            "task": ["do the task", "do the task"],
        },
        "cpu",
    )
    assert batch["observation.images.agentview"].shape == (2, 3, 4, 5)
    assert batch["observation.images.wrist"].max() == pytest.approx(1 / 255)


def test_alignment_fails_closed_on_reordered_states():
    observations = payload()
    features = {"z_state": torch.randn(3, 8), "proprio": observations["states"].flip(0)}
    with pytest.raises(ValueError, match="alignment failed"):
        validate_policy_feature_alignment(observations, features)
