import importlib.util
import unittest
from pathlib import Path
import sys


ROOT = Path(__file__).parents[1]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))
SCRIPT = ROOT / "scripts" / "run_pi05_libero_action_steps_development_pair_rocm.py"
SPEC = importlib.util.spec_from_file_location("pi05_action_steps_development", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


class PI05ActionStepsDevelopmentTests(unittest.TestCase):
    def test_requires_a_strictly_winning_screen_candidate(self) -> None:
        config = {
            "protocol_id": "pi05-libero-action-steps-full-development-v1",
            "phase": "development",
            "units_per_arm": 400,
            "screen_protocol": "pi05-libero-development-action-steps-screen-v1",
            "benchmark_manifest_protocol": "pi05-libero-public-benchmark-v2",
            "benchmark_manifest_canonical_sha256": "manifest",
        }
        manifest = {
            "protocol_id": "pi05-libero-public-benchmark-v2",
            "manifest_sha256": "manifest",
            "benchmark": {"action_chunk_size": 50},
        }
        screen = {
            "protocol_id": "pi05-libero-development-action-steps-screen-v1",
            "selection": {
                "status": "candidate_selected",
                "selected_action_steps": 4,
                "selected_successes": 39,
                "control_successes": 38,
                "promotion_requires_full_development": True,
            },
        }

        self.assertEqual(MODULE.validate_inputs(config, manifest, screen), 4)
        screen["selection"]["selected_successes"] = 38
        with self.assertRaisesRegex(ValueError, "strictly exceed"):
            MODULE.validate_inputs(config, manifest, screen)

    def test_full_development_tie_retains_control(self) -> None:
        control = {("suite", index, 0): index < 8 for index in range(10)}
        candidate = {("suite", index, 0): index not in (7, 9) for index in range(10)}

        result = MODULE.select_for_confirmation(control, candidate, 4)

        self.assertEqual(sum(control.values()), sum(candidate.values()))
        self.assertEqual(result["status"], "control_retained")
        self.assertEqual(result["selected_action_steps"], 10)
        self.assertFalse(result["confirmation_may_start"])

    def test_full_development_strict_win_freezes_candidate(self) -> None:
        control = {("suite", index, 0): index < 8 for index in range(10)}
        candidate = {("suite", index, 0): index < 9 for index in range(10)}

        result = MODULE.select_for_confirmation(control, candidate, 8)

        self.assertEqual(result["status"], "candidate_frozen")
        self.assertEqual(result["selected_action_steps"], 8)
        self.assertTrue(result["confirmation_may_start"])


if __name__ == "__main__":
    unittest.main()
