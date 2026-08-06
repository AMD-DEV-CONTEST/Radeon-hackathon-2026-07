from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from mantis_rocm_bridge.lerobot_dataset_gate import audit_mantis_dataset_metadata


ROOT = Path(__file__).resolve().parents[1]
CONTRACT = ROOT / "configs/mantis-lerobot-interface-v1.json"


class MantisDatasetGateTests(unittest.TestCase):
    def make_dataset(self, root: Path, *, zero_shoulders: bool = False) -> None:
        contract = json.loads(CONTRACT.read_text(encoding="utf-8"))
        features = {
            "observation.state": {"names": contract["state_names"], "shape": [16]},
            "action": {"names": contract["action_names"], "shape": [16]},
        }
        features.update(
            {key: {"shape": shape} for key, shape in contract["camera_features"].items()}
        )
        info = {
            "robot_type": "mantis",
            "fps": 30,
            "total_episodes": 12,
            "total_frames": 1200,
            "features": features,
        }
        action_std = [0.2] * 16
        if zero_shoulders:
            action_std[1] = 0.0
            action_std[9] = 0.0
        stats = {}
        for feature in ("observation.state", "action"):
            stats[feature] = {
                "mean": [0.0] * 16,
                "std": action_std if feature == "action" else [0.2] * 16,
                "q01": [-1.0] * 16,
                "q99": [1.0] * 16,
            }
        (root / "meta").mkdir(parents=True)
        (root / "meta/info.json").write_text(json.dumps(info), encoding="utf-8")
        (root / "meta/stats.json").write_text(json.dumps(stats), encoding="utf-8")

    def test_ready_metadata_passes_for_all_policies(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.make_dataset(root)
            receipt = audit_mantis_dataset_metadata(root, CONTRACT)
            self.assertTrue(receipt["dataset_metadata_gate_pass"])
            self.assertEqual(
                receipt["policy_ready"], {"act": True, "smolvla": True, "pi05": True}
            )

    def test_known_zero_shoulder_actions_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.make_dataset(root, zero_shoulders=True)
            receipt = audit_mantis_dataset_metadata(root, CONTRACT)
            self.assertFalse(receipt["dataset_metadata_gate_pass"])
            self.assertFalse(receipt["policy_ready"]["act"])
            self.assertFalse(receipt["policy_ready"]["smolvla"])
            self.assertIn("known_zero_action_guard:1", receipt["issues"])
            self.assertIn("known_zero_action_guard:9", receipt["issues"])


if __name__ == "__main__":
    unittest.main()
