import unittest

from scripts.run_mobile_quick_eval_rocm import render_report


class MobileQuickEvaluationTests(unittest.TestCase):
    def test_report_contains_overall_and_profile_results(self) -> None:
        report = render_report(
            {
                "successes": 2,
                "trials": 3,
                "success_rate": 2 / 3,
                "profile_summaries": {
                    "small_carton": {
                        "successes": 2,
                        "trials": 3,
                        "success_rate": 2 / 3,
                        "wilson_95": [0.21, 0.94],
                        "mean_success_placement_error_m": 0.012,
                        "force_violation_count": 0,
                        "failure_stages": {"lift_success": 1},
                    }
                },
            }
        )
        self.assertIn("2/3", report)
        self.assertIn("小纸箱 / Small carton", report)
        self.assertIn("1.20 cm", report)
        self.assertIn("21.0%-94.0%", report)
        self.assertIn("lift_success: 1", report)


if __name__ == "__main__":
    unittest.main()
