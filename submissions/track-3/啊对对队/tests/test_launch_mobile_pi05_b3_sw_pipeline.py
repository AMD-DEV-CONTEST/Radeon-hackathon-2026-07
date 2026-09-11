import json
import unittest
from pathlib import Path


ROOT = Path(__file__).parents[1]
EXPECTED_WEIGHTS = (
    2.035714286,
    2.035714286,
    1.221428571,
    0.407142857,
    0.610714286,
    0.407142857,
)


class LaunchMobilePI05B3SWPipelineTests(unittest.TestCase):
    def test_preregistered_weights_preserve_population_loss_scale(self) -> None:
        config = json.loads(
            (
                ROOT
                / "configs"
                / "mobile_pi05_b3_sw_stage_weighted_flow_v1.json"
            ).read_text(encoding="utf-8")
        )
        counts = config["population_normalization"]["dataset_stage_counts"]
        weights = tuple(config["isolated_factor"]["treatment"])

        self.assertEqual(weights, EXPECTED_WEIGHTS)
        self.assertAlmostEqual(
            sum(count * weight for count, weight in zip(counts, weights, strict=True))
            / sum(counts),
            1.0,
            places=8,
        )
        self.assertEqual(config["candidate"], "B3-SW")
        self.assertEqual(
            config["persistent_storage_root"],
            "/workspace/persistence/parcel-sorter-opt-v1",
        )
        self.assertEqual(
            config["reserved_name"]["B4"],
            "verified recovery or advantage learning only",
        )

    def test_training_is_a_single_factor_b2_ablation(self) -> None:
        text = (
            ROOT / "scripts" / "launch_mobile_pi05_b3_sw_stage_weighted_rocm.sh"
        ).read_text(encoding="utf-8")

        self.assertIn("MOBILE_PI05_ACTION_CONTRACT=absolute_v1", text)
        self.assertIn("MOBILE_PI05_FULL_ACTION_PROJECTIONS=1", text)
        self.assertIn("MOBILE_PI05_LORA_R=16", text)
        self.assertIn("MOBILE_PI05_STEPS=12000", text)
        self.assertIn("MOBILE_PI05_STAGE_LOSS_WEIGHTS=\"${STAGE_WEIGHTS}\"", text)
        self.assertIn(
            'PYTHONPATH="${ROOT_DIR}/src${PYTHONPATH:+:${PYTHONPATH}}"', text
        )
        self.assertIn("/workspace/persistence/parcel-sorter-opt-v1", text)
        self.assertNotIn("incremental_se3_v1", text)

    def test_pipeline_stops_after_development_screen(self) -> None:
        text = (
            ROOT / "scripts" / "launch_mobile_pi05_b3_sw_pipeline_rocm.sh"
        ).read_text(encoding="utf-8")

        self.assertIn("MOBILE_PI05_EXPECTED_STAGE_LOSS_WEIGHTS", text)
        self.assertIn("PERSISTENCE_ROOT", text)
        self.assertIn("MOBILE_PI05_REQUIRE_ACTION_FIDELITY=1", text)
        self.assertIn("PRE_REGISTERED_CONFIG.json", text)
        self.assertIn("SOURCE_SHA256SUMS.txt", text)
        self.assertIn('"automatic_confirmation":false', text)
        self.assertNotIn("run_mobile_pi05_frozen_validation_rocm.sh", text)

        screen_text = (
            ROOT / "scripts" / "screen_mobile_pi05_checkpoints_rocm.sh"
        ).read_text(encoding="utf-8")
        self.assertIn("MOBILE_PI05_EXPECTED_STAGE_LOSS_WEIGHTS", screen_text)
        self.assertIn("--expected-stage-loss-weights", screen_text)

    def test_training_entry_records_stage_weights_in_the_checkpoint_contract(self) -> None:
        text = (ROOT / "scripts" / "train_mobile_pi05_rocm.sh").read_text(
            encoding="utf-8"
        )

        self.assertIn('STAGE_LOSS_WEIGHTS="${MOBILE_PI05_STAGE_LOSS_WEIGHTS:-}"', text)
        self.assertIn('--stage-loss-weights "${STAGE_LOSS_WEIGHTS}"', text)

    def test_postscreen_continues_diagnostics_after_a_scientific_gate_miss(self) -> None:
        text = (
            ROOT / "scripts" / "postscreen_mobile_pi05_training_rocm.sh"
        ).read_text(encoding="utf-8")

        self.assertIn('if [[ "${screen_status}" -ge 3 ]]; then', text)
        self.assertIn("continuing frozen diagnostics for later-checkpoint selection", text)
        self.assertNotIn(
            'if [[ "${screen_status}" -ne 0 ]]; then\n'
            '  echo "ERROR: checkpoint screen failed',
            text,
        )
        self.assertTrue(text.rstrip().endswith("exit 0"))


if __name__ == "__main__":
    unittest.main()
