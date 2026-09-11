import json
import unittest
from pathlib import Path


ROOT = Path(__file__).parents[1]


class LaunchMobilePI05B3SWMPipelineTests(unittest.TestCase):
    def test_joint_stage_mode_weights_preserve_population_loss_scale(self) -> None:
        config = json.loads(
            (
                ROOT
                / "configs"
                / "mobile_pi05_b3_swm_stage_mode_weighted_flow_v1.json"
            ).read_text(encoding="utf-8")
        )
        counts = config["population_normalization"]["mode_by_stage_frame_counts"]
        mode_weights = config["isolated_factor"]["treatment"]
        stage_weights = config["isolated_factor"]["unchanged_stage_loss_weights"]
        normalizer = config["isolated_factor"]["joint_population_normalizer"]
        total = sum(sum(row) for row in counts)
        expected = sum(
            counts[mode][stage] * mode_weights[mode] * stage_weights[stage]
            for mode in range(3)
            for stage in range(6)
        ) / (total * normalizer)

        self.assertAlmostEqual(expected, 1.0, places=12)
        self.assertEqual(config["candidate"], "B3-SWM")
        self.assertEqual(config["control"]["name"], "B3-SW")
        self.assertTrue(config["frozen_before_candidate_training"])

    def test_training_changes_only_target_mode_flow_weighting_from_b3_sw(self) -> None:
        text = (
            ROOT
            / "scripts"
            / "launch_mobile_pi05_b3_swm_stage_mode_weighted_rocm.sh"
        ).read_text(encoding="utf-8")

        self.assertIn("MOBILE_PI05_ACTION_CONTRACT=absolute_v1", text)
        self.assertIn("MOBILE_PI05_STEPS=12000", text)
        self.assertIn("MOBILE_PI05_LORA_R=16", text)
        self.assertIn("MOBILE_PI05_STAGE_LOSS_WEIGHTS", text)
        self.assertIn("MOBILE_PI05_MODE_FLOW_LOSS_WEIGHTS", text)
        self.assertIn("MOBILE_PI05_MODE_FLOW_LOSS_NORMALIZER", text)
        self.assertIn("MOBILE_PI05_MODE_HEAD_CE_WEIGHT=2", text)
        self.assertIn("MOBILE_PI05_FULL_ACTION_PROJECTIONS=1", text)

    def test_pipeline_requires_frozen_mode_flow_contract_and_stops_at_development(self) -> None:
        text = (
            ROOT / "scripts" / "launch_mobile_pi05_b3_swm_pipeline_rocm.sh"
        ).read_text(encoding="utf-8")

        self.assertIn("PRE_REGISTERED_CONFIG.json", text)
        self.assertIn("MOBILE_PI05_EXPECTED_MODE_FLOW_LOSS_WEIGHTS", text)
        self.assertIn("MOBILE_PI05_EXPECTED_MODE_FLOW_LOSS_NORMALIZER", text)
        self.assertIn('"automatic_confirmation":false', text)
        self.assertNotIn("run_mobile_pi05_frozen_validation_rocm.sh", text)


if __name__ == "__main__":
    unittest.main()
