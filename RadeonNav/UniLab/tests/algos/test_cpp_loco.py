from pathlib import Path

import numpy as np
import pytest
import yaml

from unilab.algos.torch.cpp_loco import (
    DEFAULT_CPP_LOCO_CONTRACT,
    CppLocoPolicyAdapter,
    build_cpp_observation,
    cpp_action_to_unilab,
    unilab_action_to_canonical_target,
)
from unilab.utils.rotation import (
    np_matrix_from_quat,
    np_quat_apply_inverse,
    np_quat_from_euler_xyz,
)

ROOT = Path(__file__).resolve().parents[3]
FIXTURE = ROOT / "UniLab/tests/fixtures/golden-contract-fixture-v1.yaml"
CHECKPOINT = (
    ROOT / "CPP/go2_rl_gym/deploy/pre_train/go2/go2_moe_cts_137k_0.6739.pt"
)


def _fixture() -> dict:
    return yaml.safe_load(FIXTURE.read_text(encoding="utf-8"))


def test_cpp_observation_matches_golden_contract() -> None:
    fixture = _fixture()
    unilab_obs = np.asarray(
        fixture["expected_observation"]["unilab_rough"], dtype=np.float32
    ).reshape(1, -1)
    previous_cpp_action = np.asarray(
        fixture["physical_state"]["previous_action_canonical"], dtype=np.float32
    ).reshape(1, -1)
    projected_gravity = -np.asarray(
        fixture["physical_state"]["upvector_body"], dtype=np.float32
    ).reshape(1, -1)

    converted = build_cpp_observation(
        unilab_obs, previous_cpp_action, projected_gravity
    )

    expected = np.asarray(fixture["expected_observation"]["cpp_moe"], dtype=np.float32)
    np.testing.assert_allclose(
        converted[0], expected, atol=float(fixture["tolerance"]["observation_atol"])
    )


def test_cpp_action_preserves_cpp_physical_target() -> None:
    fixture = _fixture()
    cpp_action = np.asarray(
        fixture["target_test"]["actor_output_model_order"], dtype=np.float32
    ).reshape(1, -1)

    unilab_action = cpp_action_to_unilab(cpp_action)
    target = unilab_action_to_canonical_target(unilab_action)

    expected = np.asarray(
        fixture["target_test"]["expected_target_canonical_rad"]["cpp_moe"],
        dtype=np.float32,
    )
    np.testing.assert_allclose(
        target[0], expected, atol=float(fixture["tolerance"]["target_atol_rad"])
    )


def test_cpp_action_mapping_uses_the_actuator_permutation() -> None:
    cpp_action = (np.arange(12, dtype=np.float32) + 1.0).reshape(1, -1) / 10.0
    expected = np.asarray(
        [0.0, 0.5, 0.6, 1.0, 0.2, 0.3, 1.2, 1.1, 1.2, 2.2, 0.8, 0.9],
        dtype=np.float32,
    )

    np.testing.assert_allclose(cpp_action_to_unilab(cpp_action)[0], expected, atol=1.0e-6)


def test_cpp_action_mapping_fits_the_unilab_clip_contract() -> None:
    cpp_action = np.tile(
        np.asarray([-100.0, 100.0], dtype=np.float32), 6
    ).reshape(1, -1)
    unilab_action = cpp_action_to_unilab(cpp_action)
    assert np.max(np.abs(unilab_action)) <= DEFAULT_CPP_LOCO_CONTRACT.unilab_clip_actions

    expected_target = np.asarray(
        DEFAULT_CPP_LOCO_CONTRACT.cpp_default_dof, dtype=np.float32
    ) + 0.25 * cpp_action[0]
    np.testing.assert_allclose(
        unilab_action_to_canonical_target(unilab_action)[0],
        expected_target,
        atol=1.0e-5,
    )


def test_cpp_observation_uses_body_frame_projected_gravity() -> None:
    quat = np_quat_from_euler_xyz(
        np.asarray([0.3]), np.asarray([-0.2]), np.asarray([0.4])
    ).reshape(1, 4)
    world_gravity = np.asarray([[0.0, 0.0, -1.0]], dtype=np.float32)
    projected_gravity = np_quat_apply_inverse(quat, world_gravity)
    frame_z_axis = -np_matrix_from_quat(quat[0])[:, 2]
    assert not np.allclose(projected_gravity[0], frame_z_axis)

    converted = build_cpp_observation(
        np.zeros((1, 45), dtype=np.float32),
        np.zeros((1, 12), dtype=np.float32),
        projected_gravity,
    )

    np.testing.assert_allclose(converted[0, 3:6], projected_gravity[0])


def test_cpp_observation_rejects_mismatched_batches() -> None:
    with pytest.raises(ValueError, match="batch sizes differ"):
        build_cpp_observation(
            np.zeros((2, 45), dtype=np.float32),
            np.zeros((1, 12), dtype=np.float32),
            np.zeros((2, 3), dtype=np.float32),
        )


def test_cpp_policy_adapter_carries_and_resets_state() -> None:
    adapter = CppLocoPolicyAdapter(CHECKPOINT, device="cpu")
    observation = np.zeros((1, 45), dtype=np.float32)
    gravity = np.asarray([[0.0, 0.0, -1.0]], dtype=np.float32)

    _, first = adapter.act(observation, projected_gravity=gravity)
    _, second = adapter.act(observation, projected_gravity=gravity)

    np.testing.assert_allclose(second["cpp_observation"][0, 33:45], first["cpp_action"][0])
    history = adapter.policy.history.detach().cpu().numpy()
    assert history.shape == (1, 5, 45)
    assert np.any(history)

    adapter.reset()

    assert not np.any(adapter.policy.history.detach().cpu().numpy())
    assert not np.any(adapter.previous_cpp_action)
