import numpy as np

from smolvla_qvgm_rlinf.processors.libero_obs import (
    build_libero_state,
    prepare_raw_libero_observation,
)


def _raw_observation():
    return {
        "agentview_image": np.arange(4 * 5 * 3, dtype=np.uint8).reshape(4, 5, 3),
        "robot0_eye_in_hand_image": np.arange(3 * 2 * 3, dtype=np.uint8).reshape(3, 2, 3),
        "robot0_eef_pos": np.array([0.1, 0.2, 0.3], dtype=np.float32),
        "robot0_eef_quat": np.array([0.0, 0.0, 0.0, 1.0], dtype=np.float32),
        "robot0_gripper_qpos": np.array([0.04, -0.04], dtype=np.float32),
    }


def test_raw_libero_observation_orientation_and_state():
    raw = _raw_observation()
    output = prepare_raw_libero_observation(raw, "pick up the block")
    np.testing.assert_array_equal(output["main_images"], raw["agentview_image"][::-1, ::-1])
    np.testing.assert_array_equal(
        output["wrist_images"], raw["robot0_eye_in_hand_image"][::-1, ::-1]
    )
    np.testing.assert_allclose(output["states"], [0.1, 0.2, 0.3, 0, 0, 0, 0.04, -0.04])
    assert output["states"].shape == (8,)


def test_state_quaternion_sign_is_invariant():
    raw = _raw_observation()
    angle = 0.7
    raw["robot0_eef_quat"] = np.array([0, np.sin(angle / 2), 0, np.cos(angle / 2)])
    first = build_libero_state(raw)
    raw["robot0_eef_quat"] *= -1
    second = build_libero_state(raw)
    np.testing.assert_allclose(first, second, atol=1e-6)
