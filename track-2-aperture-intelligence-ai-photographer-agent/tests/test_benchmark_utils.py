from __future__ import annotations

import unittest

from scripts.benchmark_agent import _percentile, _summary


class BenchmarkUtilsTests(unittest.TestCase):
    def test_percentile_interpolation(self) -> None:
        self.assertEqual(_percentile([1.0, 2.0, 3.0], 0.5), 2.0)
        self.assertEqual(_percentile([1.0, 2.0], 0.95), 1.95)
        self.assertIsNone(_percentile([], 0.95))

    def test_summary_counts_stability_signals(self) -> None:
        results = [
            {
                "status": "pass",
                "total_agent_seconds": 10.0,
                "peak_vram_gib": 8.0,
                "model_reused": False,
                "pose_source": "vlm",
                "tool_failures": 0,
                "permission_denials": 0,
            },
            {
                "status": "pass",
                "total_agent_seconds": 8.0,
                "peak_vram_gib": 7.0,
                "model_reused": True,
                "pose_source": "vlm+validated_fallback",
                "tool_failures": 0,
                "permission_denials": 0,
            },
        ]
        summary = _summary(results, 2)
        self.assertEqual(summary["success_rate"], 1.0)
        self.assertTrue(summary["model_reused_after_first"])
        self.assertEqual(summary["validated_fallback_runs"], 1)


if __name__ == "__main__":
    unittest.main()
