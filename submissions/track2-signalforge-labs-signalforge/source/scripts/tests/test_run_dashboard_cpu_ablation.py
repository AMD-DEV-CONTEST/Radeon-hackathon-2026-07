import importlib.util
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "run_dashboard_cpu_ablation.py"
SPEC = importlib.util.spec_from_file_location("run_dashboard_cpu_ablation", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(MODULE)


class DashboardCPUAbalationTests(unittest.TestCase):
    def test_process_ticks_handles_spaces_in_process_name(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            process = root / "42"
            process.mkdir()
            fields = ["S"] + ["0"] * 10 + ["120", "30"] + ["0"] * 20
            (process / "stat").write_text(
                "42 (local model server) " + " ".join(fields), encoding="utf-8"
            )
            self.assertEqual(MODULE.process_ticks(42, root), 150)

    def test_answer_hash_ignores_runner_owned_identities(self):
        first = {
            "result": {
                "answer": {
                    "answer_id": "answer-run-a",
                    "sections": [{"text": "Supported", "claim_refs": ["claim-request-a"]}],
                }
            }
        }
        second = {
            "result": {
                "answer": {
                    "answer_id": "answer-run-b",
                    "sections": [{"text": "Supported", "claim_refs": ["claim-request-b"]}],
                }
            }
        }
        self.assertEqual(
            MODULE.canonical_answer_hash(first, "run-a", "request-a"),
            MODULE.canonical_answer_hash(second, "run-b", "request-b"),
        )

    def test_summary_uses_paired_median_and_threshold(self):
        samples = [
            {"condition": "baseline", "pair": 1, "complete_journey_cpu_seconds": 100.0},
            {"condition": "dashboard", "pair": 1, "complete_journey_cpu_seconds": 100.5},
            {"condition": "dashboard", "pair": 2, "complete_journey_cpu_seconds": 201.0},
            {"condition": "baseline", "pair": 2, "complete_journey_cpu_seconds": 200.0},
            {"condition": "baseline", "pair": 3, "complete_journey_cpu_seconds": 300.0},
            {"condition": "dashboard", "pair": 3, "complete_journey_cpu_seconds": 302.4},
        ]
        summary = MODULE.summarize(samples, 1.0)
        self.assertEqual(summary["status"], "passed")
        self.assertAlmostEqual(summary["median_overhead_percent"], 0.5)

    def test_summary_rejects_overhead_equal_to_threshold(self):
        samples = [
            {"condition": "baseline", "pair": 1, "complete_journey_cpu_seconds": 100.0},
            {"condition": "dashboard", "pair": 1, "complete_journey_cpu_seconds": 101.0},
        ]
        summary = MODULE.summarize(samples, 1.0)
        self.assertEqual(summary["status"], "failed")

    def test_retry_policy_is_bounded(self):
        source = SCRIPT.read_text(encoding="utf-8")
        self.assertIn("--max-attempts", source)
        self.assertIn("args.max_attempts > 5", source)


if __name__ == "__main__":
    unittest.main()
