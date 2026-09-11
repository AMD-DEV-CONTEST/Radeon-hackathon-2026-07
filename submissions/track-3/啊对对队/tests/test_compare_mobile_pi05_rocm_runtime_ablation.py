import importlib.util
from pathlib import Path
import unittest


SCRIPT = (
    Path(__file__).resolve().parents[1]
    / "scripts/compare_mobile_pi05_rocm_runtime_ablation.py"
)
SPEC = importlib.util.spec_from_file_location("compare_rocm_runtime", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


def _summary(successes: set[int], energy: float, *, persistent: bool) -> dict:
    outcomes = [
        {
            "episode_id": f"episode-{index}",
            "pure_vla_action": True,
            "pure_vla_complete_success": index in successes,
        }
        for index in range(10)
    ]
    return {
        "design_fingerprint_sha256": "abc",
        "checkpoints": ["checkpoint"],
        "pure_vla_complete_success": {
            "successes": len(successes),
            "trials": 10,
        },
        "force_violation_count": 0,
        "expert_fallback_count": 0,
        "emergency_stop_count": 0,
        "telemetry": {"wh_per_pure_vla_success": energy},
        "policy_runtime": {"persistent": persistent},
        "outcomes": outcomes,
    }


class CompareRocmRuntimeAblationTests(unittest.TestCase):
    def test_selects_energy_reduction_without_success_regression(self) -> None:
        baseline = _summary(set(range(8)), 1.0, persistent=False)
        resident = _summary(set(range(8)), 0.75, persistent=True)
        queued = _summary(set(range(9)), 0.70, persistent=True)
        result = MODULE.compare_runtime_arms(
            {
                "P0_COLD_FIRST_HOLD": baseline,
                "P1_RESIDENT_FIRST_HOLD": resident,
                "P2_RESIDENT_STAGE_QUEUE": queued,
            }
        )
        self.assertEqual(result["selected_arm"], "P2_RESIDENT_STAGE_QUEUE")
        self.assertEqual(result["status"], "passed")

    def test_rejects_energy_gain_with_success_regression(self) -> None:
        baseline = _summary(set(range(8)), 1.0, persistent=False)
        regressed = _summary(set(range(7)), 0.50, persistent=True)
        result = MODULE.compare_runtime_arms(
            {
                "P0_COLD_FIRST_HOLD": baseline,
                "P1_RESIDENT_FIRST_HOLD": regressed,
                "P2_RESIDENT_STAGE_QUEUE": regressed,
            }
        )
        self.assertIsNone(result["selected_arm"])
        self.assertEqual(result["status"], "no_promotion")

    def test_requires_same_frozen_design(self) -> None:
        baseline = _summary(set(range(8)), 1.0, persistent=False)
        treatment = _summary(set(range(8)), 0.75, persistent=True)
        treatment["design_fingerprint_sha256"] = "different"
        with self.assertRaisesRegex(ValueError, "fingerprint"):
            MODULE.compare_runtime_arms(
                {
                    "P0_COLD_FIRST_HOLD": baseline,
                    "P1_RESIDENT_FIRST_HOLD": treatment,
                    "P2_RESIDENT_STAGE_QUEUE": baseline,
                }
            )


if __name__ == "__main__":
    unittest.main()
