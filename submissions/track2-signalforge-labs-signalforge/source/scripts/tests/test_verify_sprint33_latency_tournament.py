from __future__ import annotations

import copy
import importlib.util
import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "verify_sprint33_latency_tournament.py"
EVIDENCE = ROOT / "evidence" / "sprint33-latency-tournament.json"
SPEC = importlib.util.spec_from_file_location("verify_sprint33_latency_tournament", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class Sprint33LatencyTournamentTests(unittest.TestCase):
    def setUp(self) -> None:
        self.payload = json.loads(EVIDENCE.read_text(encoding="utf-8"))

    def test_frozen_public_aggregate_passes(self) -> None:
        self.assertEqual(MODULE.verify(self.payload)["status"], "passed")

    def test_metric_tampering_fails(self) -> None:
        payload = copy.deepcopy(self.payload)
        payload["comparisons"]["local4_vs_baseline"]["aggregate_speedup"] = 9.9999
        report = MODULE.verify(payload)
        self.assertEqual(report["status"], "failed")
        self.assertTrue(any("aggregate_speedup" in item for item in report["failures"]))

    def test_raw_or_per_case_fields_fail(self) -> None:
        payload = copy.deepcopy(self.payload)
        payload["modes"]["local_context_concurrency_4"]["case_metrics"] = [
            {"journey_id": "must-not-publish"}
        ]
        report = MODULE.verify(payload)
        self.assertEqual(report["status"], "failed")
        self.assertTrue(any("forbidden" in item for item in report["failures"]))


if __name__ == "__main__":
    unittest.main()
