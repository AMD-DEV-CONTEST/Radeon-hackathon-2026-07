import tempfile
import unittest

from privateops.benchmark import BenchmarkStore


class BenchmarkTests(unittest.TestCase):
    def test_verified_run_requires_real_amd_and_rocm_proof(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = BenchmarkStore(tmp)

            with self.assertRaisesRegex(ValueError, "AMD Radeon"):
                store.record(
                    {
                        "label": "cloud",
                        "provider_mode": "rocm-local",
                        "verified": True,
                        "gpu_name": "NVIDIA RTX 3050",
                        "rocm_version": "7.0",
                        "rocminfo_excerpt": "gfx1100",
                        "latency_ms": 500,
                        "tokens_per_second": 22.0,
                    }
                )

    def test_development_run_cannot_claim_verified_gpu_proof(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = BenchmarkStore(tmp)

            with self.assertRaisesRegex(ValueError, "Development"):
                store.record(
                    {
                        "label": "local",
                        "provider_mode": "development",
                        "verified": True,
                        "latency_ms": 30,
                        "tokens_per_second": 0,
                    }
                )

    def test_compare_reports_literal_speedup_from_recorded_runs(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = BenchmarkStore(tmp)
            store.record(
                {
                    "label": "CPU baseline",
                    "provider_mode": "development",
                    "verified": False,
                    "latency_ms": 2000,
                    "tokens_per_second": 5.0,
                }
            )
            store.record(
                {
                    "label": "Radeon Cloud",
                    "provider_mode": "rocm-local",
                    "verified": True,
                    "gpu_name": "AMD Radeon RX 7900 XTX",
                    "rocm_version": "7.0.2",
                    "rocminfo_excerpt": "Name: gfx1100",
                    "latency_ms": 500,
                    "tokens_per_second": 20.0,
                }
            )

            comparison = store.compare()

            self.assertEqual(comparison["latency_speedup"], 4.0)
            self.assertEqual(comparison["throughput_speedup"], 4.0)


if __name__ == "__main__":
    unittest.main()
