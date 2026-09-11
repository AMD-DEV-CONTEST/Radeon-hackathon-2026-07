from pathlib import Path
import unittest


ROOT = Path(__file__).parents[1]


class LaunchMobilePI05B1PipelineTests(unittest.TestCase):
    def test_b1_is_a_fixed_single_factor_droid_initialization(self) -> None:
        text = (ROOT / "scripts/launch_mobile_pi05_b1_droid_absolute_rocm.sh").read_text(
            encoding="utf-8"
        )

        self.assertIn("72824c0a93f00ce5bb8bedb7feb58953ba1da364", text)
        self.assertIn("MOBILE_PI05_FULL_ACTION_PROJECTIONS=0", text)
        self.assertIn("PI05_BASE_MODEL=\"${DROID_MODEL}\"", text)
        self.assertIn("MOBILE_PI05_LORA_R=16", text)
        self.assertIn("MOBILE_PI05_BATCH_SIZE=1", text)

    def test_pipeline_never_accesses_heldout_or_final_105(self) -> None:
        for name in (
            "launch_mobile_pi05_b1_droid_pipeline_rocm.sh",
            "advance_mobile_pi05_b1_after_b0_rocm.sh",
        ):
            text = (ROOT / "scripts" / name).read_text(encoding="utf-8").lower()
            self.assertNotIn("heldout", text)
            self.assertNotIn("105", text)


if __name__ == "__main__":
    unittest.main()
