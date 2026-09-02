import json
import tempfile
import unittest
from pathlib import Path

from scripts.build_dashboard_cpu_evidence import build_report


class DashboardCPUEvidenceTests(unittest.TestCase):
    def write_inputs(self, root: Path, cpu_seconds: float = 200.0) -> tuple[Path, Path]:
        benchmark = root / "benchmark.txt"
        benchmark.write_text(
            "\n".join(
                [
                    "BenchmarkExecutionDashboardCPUOverhead/baseline-16 300 10000000 ns/op",
                    "BenchmarkExecutionDashboardCPUOverhead/baseline-16 300 11000000 ns/op",
                    "BenchmarkExecutionDashboardCPUOverhead/baseline-16 300 12000000 ns/op",
                    "BenchmarkExecutionDashboardCPUOverhead/dashboard-16 80 40000000 ns/op",
                    "BenchmarkExecutionDashboardCPUOverhead/dashboard-16 80 41000000 ns/op",
                    "BenchmarkExecutionDashboardCPUOverhead/dashboard-16 80 42000000 ns/op",
                ]
            )
            + "\n",
            encoding="utf-8",
        )
        workload = root / "workload.json"
        workload.write_text(
            json.dumps(
                {
                    "schema_version": "signalforge/dashboard-workload-cpu/v1",
                    "policy": {"protected_bodies_retained": False},
                    "sample": {
                        "condition": "dashboard",
                        "accepted_attempt": 1,
                        "excluded_attempts": [],
                        "complete_journey_cpu_seconds": cpu_seconds,
                        "model_calls": 10,
                        "prompt_tokens": 1000,
                        "completion_tokens": 100,
                    },
                }
            ),
            encoding="utf-8",
        )
        return benchmark, workload

    def test_builds_passing_upper_bound(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            benchmark, workload = self.write_inputs(Path(temporary))
            report = build_report(benchmark, workload)
        self.assertEqual(report["decision"]["status"], "passed")
        self.assertEqual(report["projection_benchmark"]["incremental_median_ns_per_op"], 30_000_000)
        self.assertAlmostEqual(report["decision"]["measured_upper_bound_percent"], 0.015)

    def test_rejects_protected_workload(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            benchmark, workload = self.write_inputs(Path(temporary))
            payload = json.loads(workload.read_text(encoding="utf-8"))
            payload["policy"]["protected_bodies_retained"] = True
            workload.write_text(json.dumps(payload), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "protected bodies"):
                build_report(benchmark, workload)

    def test_rejects_incomplete_benchmark(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            benchmark, workload = self.write_inputs(Path(temporary))
            benchmark.write_text(
                "BenchmarkExecutionDashboardCPUOverhead/baseline-16 1 1 ns/op\n",
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ValueError, "at least three"):
                build_report(benchmark, workload)


if __name__ == "__main__":
    unittest.main()
