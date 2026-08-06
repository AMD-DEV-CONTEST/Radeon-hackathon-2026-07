from __future__ import annotations

import json
import math
import unittest
from pathlib import Path

from mantis_rocm_bridge.contracts import ContractError
from mantis_rocm_bridge.gripper import virtual_to_physical
from mantis_rocm_bridge.lerobot_adapter import (
    features_to_policy_vector,
    lerobot_action_to_physical_qpos,
    pack_policy_observation,
    physical_qpos_to_lerobot_state,
    policy_vector_to_features,
)


ROOT = Path(__file__).resolve().parents[1]


class LeRobotAdapterTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.port = json.loads(
            (ROOT / "configs/mantis-port-config.json").read_text(encoding="utf-8")
        )
        cls.interface = json.loads(
            (ROOT / "configs/mantis-lerobot-interface-v1.json").read_text(
                encoding="utf-8"
            )
        )

    def test_named_features_round_trip_in_frozen_order(self) -> None:
        vector = [index / 20 for index in range(16)]
        features = policy_vector_to_features(vector, self.interface, kind="action")
        self.assertEqual(
            features_to_policy_vector(features, self.interface, kind="action"), vector
        )

    def test_physical_and_lerobot_adapters_round_trip(self) -> None:
        virtual = [0.01 * index for index in range(16)]
        virtual[7] = 0.25
        virtual[15] = 0.75
        physical = virtual_to_physical(virtual, self.port, allow_unverified=True)
        state = physical_qpos_to_lerobot_state(
            physical, self.port, self.interface, allow_unverified_gripper=True
        )
        restored = lerobot_action_to_physical_qpos(
            state, self.port, self.interface, allow_unverified_gripper=True
        )
        self.assertTrue(
            all(math.isclose(left, right) for left, right in zip(physical, restored))
        )

    def test_camera_role_drift_is_rejected(self) -> None:
        state = policy_vector_to_features([0.0] * 16, self.interface, kind="state")
        images = {key: object() for key in self.interface["camera_features"]}
        images.pop("observation.images.left_wrist_cam")
        with self.assertRaises(ContractError):
            pack_policy_observation(state, images, self.interface)

    def test_missing_action_feature_is_rejected(self) -> None:
        action = policy_vector_to_features([0.0] * 16, self.interface, kind="action")
        action.pop("right_gripper_joint.pos")
        with self.assertRaises(ContractError):
            lerobot_action_to_physical_qpos(
                action, self.port, self.interface, allow_unverified_gripper=True
            )


if __name__ == "__main__":
    unittest.main()
