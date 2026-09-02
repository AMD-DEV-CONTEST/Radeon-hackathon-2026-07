import copy
import unittest

from scripts.verify_dashboard_cpu_ablation import verify_report


def sample(pair: int, condition: str) -> dict:
    return {
        "condition": condition,
        "pair": pair,
        "accepted_attempt": 1,
        "excluded_attempts": [],
        "wall_seconds": 100.0,
        "orchestrator_cpu_seconds": 0.1,
        "model_cpu_seconds": 40.0,
        "complete_journey_cpu_seconds": 40.1,
        "model_calls": 10,
        "prompt_tokens": 1000,
        "completion_tokens": 100,
        "report_sha256": "a" * 64,
        "answer_sha256": "b" * 64,
        "execution_plan_sha256": "c" * 64 if condition == "dashboard" else None,
    }


def valid_report() -> dict:
    return {
        "schema_version": "signalforge/dashboard-cpu-ablation/v1",
        "measured_at": "2026-07-25T00:00:00Z",
        "environment": {
            "os": "linux",
            "architecture": "x86_64",
            "hostname_sha256": "d" * 64,
            "clock_ticks_per_second": 100,
            "model_pid": 123,
            "command_sha256": "e" * 64,
            "runner_sha256": "f" * 64,
            "workload_binary_sha256": "1" * 64,
        },
        "policy": {
            "measurement": "paired process CPU: orchestrator child plus local model server",
            "order": "alternating AB/BA",
            "protected_bodies_retained": False,
        },
        "samples": [
            sample(pair, condition)
            for pair in range(1, 4)
            for condition in ("baseline", "dashboard")
        ],
        "summary": {
            "pairs": 3,
            "paired_overhead_percent": [-0.4, 0.2, 0.8],
            "median_overhead_percent": 0.2,
            "threshold_percent": 1.0,
            "status": "passed",
        },
    }


class DashboardCPUAblationEvidenceTests(unittest.TestCase):
    def test_accepts_complete_passing_evidence(self) -> None:
        result = verify_report(valid_report())
        self.assertEqual(result["status"], "passed")
        self.assertEqual(result["samples"], 6)

    def test_rejects_failed_threshold(self) -> None:
        report = valid_report()
        report["summary"]["status"] = "failed"
        report["summary"]["median_overhead_percent"] = 1.1
        with self.assertRaisesRegex(ValueError, "did not pass"):
            verify_report(report)

    def test_rejects_missing_condition(self) -> None:
        report = valid_report()
        report["samples"] = report["samples"][:-1]
        with self.assertRaisesRegex(ValueError, "two samples per pair"):
            verify_report(report)

    def test_rejects_plan_hash_on_baseline(self) -> None:
        report = copy.deepcopy(valid_report())
        report["samples"][0]["execution_plan_sha256"] = "f" * 64
        with self.assertRaisesRegex(ValueError, "must not emit"):
            verify_report(report)

    def test_rejects_protected_body_retention(self) -> None:
        report = valid_report()
        report["policy"]["protected_bodies_retained"] = True
        with self.assertRaisesRegex(ValueError, "must not retain"):
            verify_report(report)


if __name__ == "__main__":
    unittest.main()
