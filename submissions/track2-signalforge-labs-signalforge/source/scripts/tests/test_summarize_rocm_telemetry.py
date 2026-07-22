import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


MODULE_PATH = Path(__file__).parents[1] / "summarize_rocm_telemetry.py"
SPEC = importlib.util.spec_from_file_location("rocm_summary", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


class ROCmTelemetrySummaryTests(unittest.TestCase):
    def test_summarizes_numeric_samples_and_statuses(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "telemetry.jsonl"
            samples = [
                {"monotonic_seconds": 10, "observed_at": "a", "gfx_activity_percent": 0,
                 "vram_used_mb": 100, "process_tree_rss_bytes": 1000,
                 "throttle_status": "UNTHROTTLED"},
                {"monotonic_seconds": 12, "observed_at": "b", "gfx_activity_percent": 100,
                 "vram_used_mb": 200, "process_tree_rss_bytes": 3000,
                 "throttle_status": "THROTTLED"},
            ]
            path.write_text("\n".join(json.dumps(sample) for sample in samples) + "\n")
            result = MODULE.summarize(path)
        self.assertEqual(result["sample_count"], 2)
        self.assertEqual(result["sampled_duration_seconds"], 2)
        self.assertEqual(result["metrics"]["gfx_activity_percent"]["p50"], 50)
        self.assertEqual(result["metrics"]["vram_used_mb"]["maximum"], 200)
        self.assertEqual(result["metrics"]["process_tree_rss_bytes"]["p50"], 2000)
        self.assertEqual(result["throttle_status_counts"]["THROTTLED"], 1)


if __name__ == "__main__":
    unittest.main()
