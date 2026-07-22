import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


MODULE_PATH = Path(__file__).parents[1] / "summarize_benchmark.py"
SPEC = importlib.util.spec_from_file_location("benchmark_summary", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


class BenchmarkSummaryTests(unittest.TestCase):
    def test_reports_wall_clock_throughput_and_concurrency(self):
        report = {
            "run_id": "run-1",
            "benchmark_id": "suite-1",
            "model_id": "model-1",
            "cases_sha256": "abc",
            "started_at": "2026-07-22T12:00:00Z",
            "completed_at": "2026-07-22T12:00:02Z",
            "repetitions": 1,
            "warmup_repetitions": 1,
            "concurrency": 4,
            "observations": [
                {
                    "row": {
                        "success": True,
                        "duration_ms": 1000,
                        "workload_class": "test",
                        "runtime": {
                            "ttft_ms": 100,
                            "prompt_tokens": 100,
                            "completion_tokens": 20,
                            "decode_tokens_per_second": 25,
                        },
                    }
                },
                {
                    "row": {
                        "success": True,
                        "duration_ms": 1500,
                        "workload_class": "test",
                        "runtime": {
                            "ttft_ms": 120,
                            "prompt_tokens": 200,
                            "completion_tokens": 40,
                            "decode_tokens_per_second": 30,
                        },
                    }
                },
            ],
        }
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "benchmark.json"
            path.write_text(json.dumps(report), encoding="utf-8")
            summary = MODULE.summarize(path)

        self.assertEqual(summary["concurrency"], 4)
        self.assertEqual(summary["warmup_repetitions"], 1)
        self.assertEqual(summary["aggregate"]["measured_wall_seconds"], 2)
        self.assertEqual(summary["aggregate"]["requests_per_second"], 1)
        self.assertEqual(summary["aggregate"]["prompt_tokens_per_wall_second"], 150)
        self.assertEqual(summary["aggregate"]["completion_tokens_per_wall_second"], 30)


if __name__ == "__main__":
    unittest.main()
