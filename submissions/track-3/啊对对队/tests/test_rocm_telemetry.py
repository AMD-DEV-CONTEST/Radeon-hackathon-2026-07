import unittest

from parcel_sorter.rocm_telemetry import parse_rocm_smi, summarize_rocm_samples


class RocmTelemetryTests(unittest.TestCase):
    def test_parses_radeon_json_without_treating_na_as_zero(self) -> None:
        parsed = parse_rocm_smi(
            {
                "card0": {
                    "Average Graphics Package Power (W)": "120.5",
                    "GPU use (%)": "81",
                    "GPU Memory Allocated (VRAM%)": "20",
                    "GPU Memory Read/Write Activity (%)": "N/A",
                }
            }
        )
        self.assertEqual(parsed["card0"]["power_w"], 120.5)
        self.assertIsNone(parsed["card0"]["memory_activity_percent"])

    def test_integrates_trapezoidal_energy_and_vram_growth(self) -> None:
        samples = [
            {
                "monotonic_seconds": timestamp,
                "gpus": {
                    "card0": {
                        "power_w": power,
                        "gpu_use_percent": 50.0,
                        "vram_allocated_percent": vram,
                    }
                },
            }
            for timestamp, power, vram in (
                (0.0, 100.0, 20.0),
                (1.0, 200.0, 21.0),
                (2.0, 100.0, 22.0),
            )
        ]
        result = summarize_rocm_samples(samples)
        self.assertAlmostEqual(result["energy_wh"], 300.0 / 3600.0)
        self.assertAlmostEqual(result["mean_package_power_w"], 150.0)
        self.assertEqual(result["vram_growth_percentage_points"], 2.0)

    def test_requires_two_valid_power_samples(self) -> None:
        with self.assertRaises(ValueError):
            summarize_rocm_samples(
                [{"monotonic_seconds": 0.0, "gpus": {"card0": {"power_w": None}}}]
            )


if __name__ == "__main__":
    unittest.main()
