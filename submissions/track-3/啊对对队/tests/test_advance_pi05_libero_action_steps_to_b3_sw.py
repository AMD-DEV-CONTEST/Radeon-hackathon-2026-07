import importlib.util
from pathlib import Path
import unittest


ROOT = Path(__file__).parents[1]
SCRIPT = ROOT / "scripts" / "advance_pi05_libero_action_steps_to_b3_sw_rocm.py"
SPEC = importlib.util.spec_from_file_location("advance_pi05_action_steps", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


class AdvancePI05ActionStepsToB3SWTests(unittest.TestCase):
    def test_candidate_runs_confirmation_before_b3(self) -> None:
        actions = MODULE.plan_next_actions(
            {
                "status": "candidate_frozen",
                "candidate_strictly_better": True,
                "confirmation_may_start": True,
            }
        )
        self.assertEqual(actions, ["run_confirmation", "launch_b3_sw"])

    def test_control_retained_skips_confirmation(self) -> None:
        self.assertEqual(
            MODULE.plan_next_actions({"status": "control_retained"}),
            ["skip_confirmation", "launch_b3_sw"],
        )

    def test_incomplete_development_fails_closed(self) -> None:
        with self.assertRaisesRegex(ValueError, "incomplete or invalid"):
            MODULE.plan_next_actions({"status": "failed"})


if __name__ == "__main__":
    unittest.main()
