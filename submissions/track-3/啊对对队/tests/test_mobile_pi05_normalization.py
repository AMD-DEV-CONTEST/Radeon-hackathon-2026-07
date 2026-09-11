import unittest

from parcel_sorter.mobile_pi05_normalization import (
    constant_dimensions,
    stabilize_quantile_stats,
    unsafe_quantile_dimensions,
)


class MobilePI05NormalizationTests(unittest.TestCase):
    def test_repairs_variable_dimension_with_collapsed_merged_quantiles(self) -> None:
        stats = {
            "min": [-1.0, 0.0],
            "max": [1.0, 0.0],
            "q01": [-0.4216629657, 0.0],
            "q99": [-0.4216629657, 0.0],
        }
        self.assertEqual(unsafe_quantile_dimensions(stats, ("mode", "base")), ("mode",))

        repaired, fallback = stabilize_quantile_stats(stats, ("mode", "base"))

        self.assertEqual(fallback, ("mode",))
        self.assertEqual(repaired["q01"], [-1.0, 0.0])
        self.assertEqual(repaired["q99"], [1.0, 0.0])
        self.assertEqual(unsafe_quantile_dimensions(repaired, ("mode", "base")), ())

    def test_keeps_true_constant_dimension_without_inventing_variation(self) -> None:
        stats = {
            "min": [0.0],
            "max": [0.0],
            "q01": [0.0],
            "q99": [0.0],
        }
        repaired, fallback = stabilize_quantile_stats(stats, ("base_vx",))
        self.assertEqual(fallback, ())
        self.assertEqual(repaired, stats)
        self.assertEqual(constant_dimensions(repaired, ("base_vx",)), ("base_vx",))

    def test_rejects_malformed_stats(self) -> None:
        stats = {"min": [0.0], "max": [1.0], "q01": [0.0], "q99": []}
        with self.assertRaisesRegex(ValueError, "length mismatch"):
            unsafe_quantile_dimensions(stats, ("action",))


if __name__ == "__main__":
    unittest.main()
