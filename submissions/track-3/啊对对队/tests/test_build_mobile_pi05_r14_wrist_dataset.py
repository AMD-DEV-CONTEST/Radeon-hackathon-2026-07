import json
from pathlib import Path
import tempfile
import unittest

from scripts.build_mobile_pi05_r14_wrist_dataset_rocm import _successful_config


class BuildMobilePI05R14WristDatasetTests(unittest.TestCase):
    def _summary(self, root: Path, *, verified: bool = True) -> Path:
        path = root / "summary.json"
        path.write_text(
            json.dumps(
                {
                    "successful_episode_order": ["a", "b"],
                    "results": [
                        {
                            "episode_id": "a",
                            "success": True,
                            "parameters": {"episode_id": "a", "mass_kg": 0.1},
                            "recovery_label": {"verified_success": verified},
                        },
                        {
                            "episode_id": "failed",
                            "success": False,
                            "parameters": {"episode_id": "failed", "mass_kg": 0.2},
                            "recovery_label": {"verified_success": False},
                        },
                        {
                            "episode_id": "b",
                            "success": True,
                            "parameters": {"episode_id": "b", "mass_kg": 0.3},
                            "recovery_label": {"verified_success": True},
                        },
                    ],
                }
            ),
            encoding="utf-8",
        )
        return path

    def test_only_verified_successes_enter_frozen_source_order(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            config = _successful_config(self._summary(Path(directory)), group="side")

        self.assertEqual([item["episode_id"] for item in config["episodes"]], ["a", "b"])
        self.assertNotIn("failed", str(config["episodes"]))
        self.assertEqual(config["policy_visual_modality"], "rgbd_wrist")

    def test_unverified_success_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(ValueError, "not a verified recovery"):
                _successful_config(
                    self._summary(Path(directory), verified=False), group="side"
                )


if __name__ == "__main__":
    unittest.main()
