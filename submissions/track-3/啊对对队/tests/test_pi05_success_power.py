import importlib.util
from pathlib import Path
import unittest


SCRIPT = Path(__file__).parents[1] / "scripts" / "plan_pi05_success_power.py"
SPEC = importlib.util.spec_from_file_location("plan_pi05_success_power", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


class PI05SuccessPowerTests(unittest.TestCase):
    def test_frozen_105_exact_claim_gate_is_100_successes(self) -> None:
        self.assertEqual(MODULE.exact_critical_successes(105, 0.90, 0.05), 100)
        self.assertAlmostEqual(
            MODULE.exact_one_sided_lower_bound(100, 105, 0.05),
            0.9025,
            places=4,
        )

    def test_95_successes_is_only_an_engineering_point_estimate(self) -> None:
        lower, _upper = MODULE.wilson_interval(95, 105, 0.05)
        self.assertAlmostEqual(lower, 0.8335, places=4)
        self.assertLess(lower, 0.90)

    def test_power_sensitivity_matches_exact_binomial_design(self) -> None:
        critical = MODULE.exact_critical_successes(105, 0.90, 0.05)
        self.assertAlmostEqual(
            MODULE.binomial_upper_tail(critical, 105, 0.95),
            0.5711,
            places=4,
        )
        result = MODULE.required_trials(
            null_probability=0.90,
            alternative_probability=0.95,
            alpha=0.05,
            target_power=0.80,
        )
        self.assertEqual(result["trials"], 179)


if __name__ == "__main__":
    unittest.main()
