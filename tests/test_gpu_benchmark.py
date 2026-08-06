import unittest
from unittest.mock import patch

from incident_commander.gpu_benchmark import benchmark, collect_accelerator_info, percentile, summarize
from incident_commander.llm import StreamingLLMResult


class GPUDBenchmarkTests(unittest.TestCase):
    @patch("incident_commander.gpu_benchmark._run")
    def test_accelerator_manifest_is_sanitized(self, run) -> None:
        run.side_effect = [
            "7.2.1\n",
            """GPU: 0
    ASIC:
        ASIC_SERIAL: secret-serial
        NUM_COMPUTE_UNITS: 96
        TARGET_GRAPHICS_VERSION: gfx1100
    DRIVER:
        NAME: amdgpu
        VERSION: 6.16.13
    VRAM:
        SIZE: 49136 MB
""",
        ]

        manifest = collect_accelerator_info()

        self.assertEqual(manifest["architecture"], "gfx1100")
        self.assertEqual(manifest["vram_mb"], 49136)
        self.assertEqual(manifest["compute_units"], 96)
        self.assertEqual(manifest["driver_version"], "6.16.13")
        self.assertNotIn("secret-serial", str(manifest))

    def test_percentile_and_summary(self) -> None:
        samples = [10.0, 20.0, 30.0, 40.0]
        self.assertEqual(percentile(samples, 0.95), 40.0)
        self.assertEqual(summarize(samples)["p50"], 25.0)

    def test_benchmark_calculates_decode_rate(self) -> None:
        class StubClient:
            def stream_complete(self, system, user, max_tokens=256):
                return StreamingLLMResult("brief", 100.0, 1100.0, "stub", {"completion_tokens": 20})

        result = benchmark(StubClient(), "incident", iterations=2, max_tokens=64)

        self.assertEqual(result["model"], "stub")
        self.assertEqual(result["ttft_ms"]["mean"], 100.0)
        self.assertEqual(result["output_tokens_per_second"]["mean"], 20.0)


if __name__ == "__main__":
    unittest.main()
