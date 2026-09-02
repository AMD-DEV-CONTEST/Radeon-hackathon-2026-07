import tempfile
import unittest
from pathlib import Path

from scripts.capture_dashboard_radeon_journey import build_journey


class CaptureDashboardRadeonJourneyTests(unittest.TestCase):
    def test_builds_aggregate_without_protected_bodies(self):
        with tempfile.TemporaryDirectory() as temporary:
            trace = Path(temporary) / "trace.json"
            trace.write_text("{}")
            journey = build_journey(
                run(),
                intelligence(),
                trace,
                "hybrid_radeon_api",
            )

        self.assertEqual(journey["status"], "completed")
        self.assertEqual(journey["intelligence"]["model_calls"], 2)
        self.assertEqual(journey["intelligence"]["input_tokens"], 300)
        self.assertEqual(journey["intelligence"]["routes"], ["local_rocm", "radeon_api"])
        self.assertFalse(journey["privacy"]["prompt_bodies_retained"])
        self.assertNotIn("result", journey)

    def test_rejects_cross_run_lineage(self):
        mismatched = intelligence()
        mismatched["run_id"] = "run-other"
        with tempfile.TemporaryDirectory() as temporary:
            trace = Path(temporary) / "trace.json"
            trace.write_text("{}")
            with self.assertRaisesRegex(ValueError, "run identity"):
                build_journey(run(), mismatched, trace, "hybrid_radeon_api")


def run():
    return {
        "run_id": "run-1",
        "trace_id": "trace-1",
        "status": "completed",
        "started_at": "2026-07-25T00:00:00Z",
        "completed_at": "2026-07-25T00:01:00Z",
        "execution_plan": {
            "schema_version": "signalforge/execution-plan/v1",
            "plan_id": "plan-1",
            "status": "passed",
            "total_steps": 2,
            "terminal_steps": 2,
            "progress_ratio": 1,
            "max_parallel_specialists": 4,
            "route_summary": ["radeon_api", "local_rocm"],
            "projection_sha256": "a" * 64,
            "phases": [{"phase_id": "context", "status": "passed"}],
        },
    }


def intelligence():
    return {
        "schema_version": "signalforge/intelligence-lineage/v1",
        "run_id": "run-1",
        "trace_id": "trace-1",
        "status": "completed",
        "capture": {"status": "disabled"},
        "release": {"status": "released"},
        "model_calls": [
            {
                "input_tokens": 100,
                "output_tokens": 10,
                "provider_id": "radeon-vllm",
                "route": "radeon_api",
                "role_id": "specialist/v1",
            },
            {
                "input_tokens": 200,
                "output_tokens": 20,
                "provider_id": "local-rocm",
                "route": "local_rocm",
                "role_id": "reviewer/v1",
            },
        ],
        "retrievals": [{}],
        "engine_calls": [{}, {}],
        "reviews": [{}],
    }


if __name__ == "__main__":
    unittest.main()
