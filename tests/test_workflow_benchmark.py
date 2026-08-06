import json
import tempfile
import unittest
from pathlib import Path

from incident_commander.agent import InvestigationService
from incident_commander.store import SessionStore
from incident_commander.workflow_benchmark import benchmark_workflows, summarize_runs


SAMPLE = Path(__file__).parent.parent / "samples" / "checkout-latency.json"


class OfflineClient:
    def choose_tool(self, *args, **kwargs):
        raise RuntimeError("offline")

    def complete(self, *args, **kwargs):
        raise RuntimeError("offline")


class WorkflowBenchmarkTests(unittest.TestCase):
    def test_ten_run_gate_checks_tools_citations_remote_requests_and_p95(self) -> None:
        incident = json.loads(SAMPLE.read_text(encoding="utf-8"))
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)

            def factory(run_root: Path) -> InvestigationService:
                return InvestigationService(
                    SessionStore(run_root),
                    client=OfflineClient(),
                    runtime={"mode": "offline-safe", "degraded": False},
                )

            result = benchmark_workflows(factory, root, incident, iterations=10, warmups=2, p95_limit_ms=30_000)

        self.assertEqual(result["aggregate"]["completed_workflows"], 10)
        self.assertEqual(result["aggregate"]["three_tool_workflows"], 10)
        self.assertEqual(result["aggregate"]["unknown_citations"], 0)
        self.assertEqual(result["aggregate"]["remote_core_requests"], 0)
        self.assertTrue(result["gate"]["passed"])

    def test_summary_fails_each_acceptance_dimension(self) -> None:
        runs = [
            {
                "completed": False,
                "distinct_tools": ["get_deployments"],
                "unknown_citations": 1,
                "remote_core_requests": 1,
                "latency_ms": 31_000.0,
            }
        ]

        result = summarize_runs(runs, p95_limit_ms=30_000)

        self.assertFalse(result["gate"]["passed"])
        self.assertEqual(
            set(result["gate"]["failures"]),
            {"completion", "three_tools", "unknown_citations", "remote_core_requests", "p95_latency"},
        )


if __name__ == "__main__":
    unittest.main()
