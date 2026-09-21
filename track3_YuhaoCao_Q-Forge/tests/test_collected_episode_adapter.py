import pickle

import numpy as np

from smolvla_qvgm_rlinf.data.collect_episode import CompatibleLeRobotDatasetWriter
from smolvla_qvgm_rlinf.data.collected_episode_adapter import (
    episode_to_trajectory,
    load_collected_episode,
)


def _observation(value: float) -> dict:
    return {
        "main_images": np.full((4, 5, 3), value, dtype=np.uint8),
        "wrist_images": np.full((4, 5, 3), value, dtype=np.uint8),
        "states": np.full(8, value, dtype=np.float32),
    }


def test_collected_episode_alignment_and_trajectory_shapes(tmp_path):
    reset_info = {}
    step_info = {
        "predicted_action_chunk": np.zeros((50, 7), dtype=np.float32),
        "executed_chunk_prefix": np.zeros((1, 7), dtype=np.float32),
        "model_action_before_clip": np.zeros((1, 7), dtype=np.float32),
        "initial_noise_seed": 17,
        "task_id": 7,
        "task_reset_state_id": 3,
    }
    episode = {
        "actions": [np.zeros(7, dtype=np.float32), np.ones(7, dtype=np.float32)],
        "observations": [_observation(0), _observation(1), _observation(2)],
        "rewards": [0.0, 0.0, 1.0],
        "terminated": [False, False, True],
        "truncated": [False, False, False],
        "infos": [reset_info, step_info, step_info],
    }
    path = tmp_path / "episode.pkl"
    with path.open("wb") as handle:
        pickle.dump(episode, handle)

    loaded = load_collected_episode(path)
    trajectory = episode_to_trajectory(loaded, model_weights_id="test")

    assert trajectory.actions.shape == (2, 1, 7)
    assert trajectory.curr_obs["main_images"].shape == (2, 1, 4, 5, 3)
    assert trajectory.next_obs["states"].shape == (2, 1, 8)
    assert trajectory.forward_inputs["predicted_action_chunk"].shape == (2, 1, 50, 7)
    assert trajectory.dones[:, 0, 0].tolist() == [False, True]


def test_lerobot_writer_passes_task_as_explicit_argument():
    calls = []

    class FakeDataset:
        def add_frame(self, frame, task):
            calls.append((frame, task))

        def save_episode(self):
            calls.append("saved")

    writer = CompatibleLeRobotDatasetWriter()
    writer.dataset = FakeDataset()
    writer.add_episode([{"state": np.zeros(8), "task": "stove task"}])

    assert calls[0][1] == "stove task"
    assert "task" not in calls[0][0]
    assert calls[1] == "saved"
