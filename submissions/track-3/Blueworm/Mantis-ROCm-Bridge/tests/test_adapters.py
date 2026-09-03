from __future__ import annotations

import unittest
from pathlib import Path

from mantis_rocm_bridge.adapters import adapt_source_action, reorder_images, reorder_source_state
from mantis_rocm_bridge.contracts import ContractError, load_json


ROOT = Path(__file__).resolve().parents[1]


class AdapterTests(unittest.TestCase):
    def setUp(self) -> None:
        self.port = load_json(ROOT / "configs/mantis-port-config.json")

    def test_wrist_values_are_semantically_reordered(self) -> None:
        result = reorder_source_state(range(16), self.port)
        self.assertEqual(result[4:7], [6.0, 5.0, 4.0])
        self.assertEqual(result[12:15], [14.0, 13.0, 12.0])

    def test_action_conversion_is_blocked_until_units_and_limits_are_frozen(self) -> None:
        with self.assertRaises(ContractError):
            adapt_source_action(range(16), self.port)

    def test_camera_values_follow_target_order(self) -> None:
        result = reorder_images(
            {"head_camera": "env", "right_camera": "right", "left_camera": "left"},
            self.port["camera_map"],
            self.port["target"]["camera_order"],
        )
        self.assertEqual(list(result), ["env_cam", "left_wrist_cam", "right_wrist_cam"])
        self.assertEqual(list(result.values()), ["env", "left", "right"])


if __name__ == "__main__":
    unittest.main()

