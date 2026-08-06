import os
import sys

import numpy as np

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

from control_utils import (
    compose_full_joint_targets,
    compose_joint_targets,
    store_robot_actions,
)


def test_compose_joint_targets_applies_scaled_policy_action():
    actions = np.array([[1.0, -0.5, 0.0]], dtype=np.float32)
    defaults = np.array([0.1, 0.2, 0.3], dtype=np.float32)

    targets = compose_joint_targets(actions, 0.25, defaults)

    np.testing.assert_allclose(targets, [[0.35, 0.075, 0.3]])


def test_store_robot_actions_only_updates_selected_robot():
    buffers = [np.zeros((1, 3), dtype=np.float32) for _ in range(3)]
    action = np.array([[0.1, 0.2, 0.3]], dtype=np.float32)

    store_robot_actions(buffers, 1, action)

    np.testing.assert_array_equal(buffers[0], np.zeros((1, 3)))
    np.testing.assert_array_equal(buffers[1], action)
    np.testing.assert_array_equal(buffers[2], np.zeros((1, 3)))


def test_compose_full_joint_targets_embeds_21_actions_in_23_motors():
    actions = np.ones((1, 21), dtype=np.float32)
    defaults = np.arange(23, dtype=np.float32) / 10
    policy_indices = np.array([2, 6, 3, 7, 4, 8, 5, 9, 10, 14, 11, 15, 12,
                               16, 13, 17, 18, 19, 20, 21, 22])

    targets = compose_full_joint_targets(actions, 0.25, defaults, policy_indices)

    assert targets.shape == (1, 23)
    np.testing.assert_allclose(targets[0, policy_indices], defaults[policy_indices] + 0.25)
    np.testing.assert_allclose(targets[0, [0, 1]], defaults[[0, 1]])
