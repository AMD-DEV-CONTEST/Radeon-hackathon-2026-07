import unittest
import math

from parcel_sorter.metrics import EpisodeResult, MetricsAccumulator, wilson_interval


class MetricsAccumulatorTests(unittest.TestCase):
    def test_summary_reports_success_recovery_and_latency(self) -> None:
        metrics = MetricsAccumulator()
        metrics.add(EpisodeResult(True, 0, 4.0, (5.0, 7.0), max_contact_force_n=10.0))
        metrics.add(EpisodeResult(True, 1, 6.0, (9.0, 11.0), max_contact_force_n=15.0))
        metrics.add(EpisodeResult(False, 2, 10.0, (13.0,), dropped=True, max_contact_force_n=20.0))

        summary = metrics.summary()

        self.assertEqual(summary["episodes"], 3)
        self.assertAlmostEqual(summary["success_rate"], 2 / 3)
        self.assertAlmostEqual(summary["first_attempt_success_rate"], 1 / 3)
        self.assertAlmostEqual(summary["recovery_success_rate"], 0.5)
        self.assertEqual(summary["p95_inference_latency_ms"], 13.0)
        self.assertEqual(summary["max_contact_force_n"], 20.0)
        self.assertEqual(summary["successes"], 2)
        self.assertLess(summary["success_rate_ci95_low"], summary["success_rate"])
        self.assertGreater(summary["success_rate_ci95_high"], summary["success_rate"])

    def test_wilson_interval_is_bounded_and_zero_trials_are_unknown(self) -> None:
        low, high = wilson_interval(8, 12)

        self.assertGreaterEqual(low, 0.0)
        self.assertLess(low, 8 / 12)
        self.assertGreater(high, 8 / 12)
        self.assertLessEqual(high, 1.0)
        self.assertEqual(wilson_interval(0, 0), (0.0, 1.0))

        with self.assertRaisesRegex(ValueError, "0 <= successes <= trials"):
            wilson_interval(2, 1)
        with self.assertRaisesRegex(ValueError, "finite positive z score"):
            wilson_interval(1, 2, z=0)
        with self.assertRaisesRegex(ValueError, "finite positive z score"):
            wilson_interval(1, 2, z=math.nan)


if __name__ == "__main__":
    unittest.main()
