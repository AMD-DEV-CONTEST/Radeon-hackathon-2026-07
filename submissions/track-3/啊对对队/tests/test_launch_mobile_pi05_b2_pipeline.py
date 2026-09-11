import unittest
from pathlib import Path


ROOT = Path(__file__).parents[1]


class LaunchMobilePI05B2PipelineTests(unittest.TestCase):
    def test_b2_trains_full_action_projections_from_droid(self) -> None:
        text = (
            ROOT / "scripts" / "launch_mobile_pi05_b2_droid_full_projection_rocm.sh"
        ).read_text(encoding="utf-8")

        self.assertIn("PI05_BASE_MODEL=\"${DROID_MODEL}\"", text)
        self.assertIn("MOBILE_PI05_FULL_ACTION_PROJECTIONS=1", text)
        self.assertIn("MOBILE_PI05_ACTION_CONTRACT=absolute_v1", text)

    def test_b2_postscreen_requires_action_fidelity_and_full_projections(self) -> None:
        text = (
            ROOT
            / "scripts"
            / "launch_mobile_pi05_b2_full_projection_pipeline_rocm.sh"
        ).read_text(encoding="utf-8")

        self.assertIn("MOBILE_PI05_REQUIRE_ACTION_FIDELITY=1", text)
        self.assertIn("MOBILE_PI05_REQUIRE_FULL_ACTION_PROJECTIONS=1", text)
        self.assertIn("advance_mobile_pi05_b0_after_postscreen_rocm.sh", text)

    def test_b2_handoff_waits_for_the_complete_b1_pipeline(self) -> None:
        text = (
            ROOT / "scripts" / "advance_mobile_pi05_b2_after_b1_rocm.sh"
        ).read_text(encoding="utf-8")

        self.assertIn('while kill -0 "${B1_AUTO_PID}"', text)
        self.assertIn("launch_mobile_pi05_b2_full_projection_pipeline_rocm.sh", text)


if __name__ == "__main__":
    unittest.main()
