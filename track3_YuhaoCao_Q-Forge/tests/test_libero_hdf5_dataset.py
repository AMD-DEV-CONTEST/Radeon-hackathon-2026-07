from pathlib import Path

import h5py
import numpy as np

from smolvla_qvgm_rlinf.data import (
    LiberoHDF5MultiTaskDataset,
    LiberoHDF5TaskDataset,
    compute_libero_hdf5_stats,
)


def _write_demo(path: Path, length: int, value: float) -> None:
    with h5py.File(path, "w") as handle:
        demo = handle.create_group("data/demo_0")
        obs = demo.create_group("obs")
        obs.create_dataset("ee_pos", data=np.full((length, 3), value))
        obs.create_dataset("ee_ori", data=np.full((length, 3), value))
        obs.create_dataset("gripper_states", data=np.full((length, 2), value))
        obs.create_dataset(
            "agentview_rgb", data=np.zeros((length, 4, 5, 3), dtype=np.uint8)
        )
        obs.create_dataset(
            "eye_in_hand_rgb", data=np.zeros((length, 4, 5, 3), dtype=np.uint8)
        )
        demo.create_dataset("actions", data=np.full((length, 7), value, dtype=np.float32))


def test_hdf5_dataset_pads_action_chunks(tmp_path: Path):
    path = tmp_path / "demo.hdf5"
    with h5py.File(path, "w") as handle:
        demo = handle.create_group("data/demo_0")
        obs = demo.create_group("obs")
        obs.create_dataset("ee_pos", data=np.zeros((2, 3)))
        obs.create_dataset("ee_ori", data=np.zeros((2, 3)))
        obs.create_dataset("gripper_states", data=np.zeros((2, 2)))
        obs.create_dataset("agentview_rgb", data=np.zeros((2, 4, 5, 3), dtype=np.uint8))
        obs.create_dataset("eye_in_hand_rgb", data=np.zeros((2, 4, 5, 3), dtype=np.uint8))
        demo.create_dataset("actions", data=np.array([[1] * 7, [2] * 7], dtype=np.float32))
    dataset = LiberoHDF5TaskDataset(path, "task", chunk_size=3)
    sample = dataset[1]
    assert sample["observation.state"].shape == (8,)
    assert sample["action"].shape == (3, 7)
    np.testing.assert_array_equal(sample["actions_id_pad"], [False, True, True])
    np.testing.assert_array_equal(sample["action"][1], sample["action"][0])


def test_multitask_dataset_preserves_tasks_and_balances_weights(tmp_path: Path):
    first, second = tmp_path / "first.hdf5", tmp_path / "second.hdf5"
    _write_demo(first, length=2, value=1.0)
    _write_demo(second, length=4, value=3.0)
    dataset = LiberoHDF5MultiTaskDataset([first, second], ["first task", "second task"])

    assert len(dataset) == 6
    assert dataset[0]["task"] == "first task"
    assert dataset[2]["task"] == "second task"
    weights = dataset.task_balanced_sample_weights()
    assert weights[:2].sum().item() == weights[2:].sum().item()

    stats = compute_libero_hdf5_stats([first, second])
    np.testing.assert_allclose(stats["action"]["mean"], np.full(7, 7 / 3))


def test_hdf5_images_are_rotated_to_match_live_libero_observations(tmp_path: Path):
    path = tmp_path / "orientation.hdf5"
    _write_demo(path, length=1, value=0.0)
    pattern = np.arange(4 * 5 * 3, dtype=np.uint8).reshape(4, 5, 3)
    with h5py.File(path, "r+") as handle:
        handle["data/demo_0/obs/agentview_rgb"][0] = pattern
        handle["data/demo_0/obs/eye_in_hand_rgb"][0] = pattern

    sample = LiberoHDF5TaskDataset(path, "orientation task")[0]
    expected = pattern[::-1, ::-1].transpose(2, 0, 1) / 255.0
    np.testing.assert_allclose(sample["observation.images.agentview"], expected)
    np.testing.assert_allclose(sample["observation.images.wrist"], expected)
