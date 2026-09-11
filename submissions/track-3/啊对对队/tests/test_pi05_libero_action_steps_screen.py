from __future__ import annotations

import importlib.util
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


def load_script():
    path = ROOT / "scripts" / "run_pi05_libero_action_steps_screen_rocm.py"
    spec = importlib.util.spec_from_file_location("pi05_libero_action_steps_screen", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


screen = load_script()


class PI05LiberoActionStepsScreenTests(unittest.TestCase):
    def test_selects_strictly_better_candidate(self) -> None:
        result = screen.select_arm(
            [
                {"arm_id": "steps10_control", "action_steps": 10, "eligible": True, "successes": 38},
                {"arm_id": "steps4_candidate", "action_steps": 4, "eligible": True, "successes": 40},
                {"arm_id": "steps8_candidate", "action_steps": 8, "eligible": True, "successes": 39},
            ]
        )
        self.assertEqual(result["status"], "candidate_selected")
        self.assertEqual(result["selected_action_steps"], 4)

    def test_tie_retains_higher_step_control(self) -> None:
        result = screen.select_arm(
            [
                {"arm_id": "steps10_control", "action_steps": 10, "eligible": True, "successes": 39},
                {"arm_id": "steps4_candidate", "action_steps": 4, "eligible": True, "successes": 39},
                {"arm_id": "steps8_candidate", "action_steps": 8, "eligible": True, "successes": 39},
            ]
        )
        self.assertEqual(result["status"], "control_retained")
        self.assertEqual(result["selected_action_steps"], 10)

    def test_missing_control_fails_closed(self) -> None:
        result = screen.select_arm(
            [
                {"arm_id": "steps4_candidate", "action_steps": 4, "eligible": True, "successes": 40}
            ]
        )
        self.assertEqual(result["status"], "failed")


if __name__ == "__main__":
    unittest.main()
