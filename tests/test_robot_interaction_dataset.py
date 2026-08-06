"""Storage-contract tests for HDF5 trajectories and legacy compatibility."""

import numpy as np
import pytest

pytest.importorskip("torch")
pytest.importorskip("h5py")

from data.robot_interaction_dataset import EpisodeTrajectory, RobotInteractionDataset, TrajectoryHDF5Writer


def _trajectory() -> EpisodeTrajectory:
    trajectory = EpisodeTrajectory()
    for step in range(2):
        trajectory.append(
            state=np.full(3, step, dtype=np.float32),
            action=np.full(2, step + 1, dtype=np.float32),
            reward=float(step), terminated=step == 1, truncated=False,
            next_state=np.full(3, step + 1, dtype=np.float32),
        )
    return trajectory


def test_hdf5_trajectory_round_trip(tmp_path):
    with TrajectoryHDF5Writer(tmp_path, env_metadata={"task": "unit-test"}) as writer:
        writer.add_episode(_trajectory(), episode=0, metadata={"success": True})

    dataset = RobotInteractionDataset(tmp_path)
    assert len(dataset) == 2
    sample = dataset[1]
    assert sample["state"].tolist() == [1.0, 1.0, 1.0]
    assert sample["action"].tolist() == [2.0, 2.0]
    assert sample["terminated"].item() is True
    dataset.close()


def test_hdf5_multimodal_round_trip(tmp_path):
    trajectory = _trajectory()
    trajectory.proprio = [np.zeros(2, dtype=np.float32), np.ones(2, dtype=np.float32)]
    trajectory.next_proprio = [np.ones(2, dtype=np.float32), np.full(2, 2, dtype=np.float32)]
    trajectory.rgb = [np.zeros((4, 5, 3), dtype=np.uint8) for _ in range(2)]
    trajectory.next_rgb = [np.ones((4, 5, 3), dtype=np.uint8) for _ in range(2)]
    with TrajectoryHDF5Writer(tmp_path, env_metadata={}) as writer:
        writer.add_episode(trajectory, episode=0, metadata={})

    sample = RobotInteractionDataset(tmp_path, modalities=("state", "proprio", "rgb"))[0]
    assert sample["proprio"].shape == (2,)
    assert sample["rgb"].shape == (4, 5, 3)


def test_legacy_npy_pair_is_readable(tmp_path):
    np.save(tmp_path / "state.npy", np.zeros((2, 3), dtype=np.float32))
    np.save(tmp_path / "action.npy", np.ones((2, 2), dtype=np.float32))
    dataset = RobotInteractionDataset(tmp_path)
    assert len(dataset) == 2
    assert dataset[0]["action"].tolist() == [1.0, 1.0]
