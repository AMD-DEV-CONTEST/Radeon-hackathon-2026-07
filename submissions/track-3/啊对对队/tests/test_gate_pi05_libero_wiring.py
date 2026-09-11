import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "gate_pi05_libero_wiring.py"
SPEC = importlib.util.spec_from_file_location("gate_pi05_libero_wiring", SCRIPT)
module = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = module
SPEC.loader.exec_module(module)


class GatePI05LiberoWiringTests(unittest.TestCase):
    def write_run(self, root: Path, outcomes: list[bool]) -> None:
        (root / "eval").mkdir(parents=True)
        contract = {
            "phase": "wiring",
            "policy_classification": "pure_pi05_vla",
            "expert_reference_allowed": False,
            "expert_fallback_allowed": False,
            "parcel_harness_allowed": False,
            "run_scope": {
                "score_eligible": False,
                "episodes_per_task": len(outcomes),
                "suites": ["libero_spatial"],
                "task_ids": [0],
            },
        }
        summary = {"returncode": 0}
        eval_info = {
            "per_task": [
                {
                    "task_group": "libero_spatial",
                    "task_id": 0,
                    "metrics": {"successes": outcomes},
                }
            ],
            "overall": {"n_episodes": len(outcomes)},
        }
        (root / "run-contract.json").write_text(json.dumps(contract), encoding="utf-8")
        (root / "run-summary.json").write_text(json.dumps(summary), encoding="utf-8")
        (root / "eval" / "eval_info.json").write_text(json.dumps(eval_info), encoding="utf-8")

    def test_three_episode_gate_passes_at_two_successes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.write_run(root, [True, False, True])
            result = module.gate_wiring(root, expected_episodes=3, minimum_successes=2)
            self.assertEqual(result["status"], "passed")
            self.assertEqual(result["successes"], 2)

    def test_three_episode_gate_fails_below_success_floor(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.write_run(root, [False, False, True])
            result = module.gate_wiring(root, expected_episodes=3, minimum_successes=2)
            self.assertEqual(result["status"], "failed")
            self.assertIn("success_floor_not_met", result["errors"])


if __name__ == "__main__":
    unittest.main()
