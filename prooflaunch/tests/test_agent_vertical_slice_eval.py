from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from scripts.run_agent_vertical_slice_eval import run_evaluation


class AgentVerticalSliceEvalTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._temporary = tempfile.TemporaryDirectory()
        cls.output = Path(cls._temporary.name) / "agent-eval"
        cls.result = run_evaluation(cls.output)

    @classmethod
    def tearDownClass(cls) -> None:
        cls._temporary.cleanup()

    def test_ten_rights_clear_cases_cover_gtm_slices(self) -> None:
        self.assertEqual(self.result["case_count"], 10)
        self.assertEqual(len(self.result["coverage"]["markets"]), 10)
        self.assertGreaterEqual(len(self.result["coverage"]["platforms"]), 6)
        self.assertEqual(
            set(self.result["coverage"]["target_emotions"]),
            {"sadness", "joy", "love", "anger", "fear", "surprise"},
        )
        for case in self.result["cases"]:
            self.assertTrue(case["rights_basis"]["status"].startswith("rights-clear"))
            self.assertFalse(case["rights_basis"]["third_party_content"])

    def test_real_prepare_fixture_approval_release_path_passes(self) -> None:
        metrics = self.result["metrics"]
        self.assertEqual(metrics["prepare_success_rate"], 1.0)
        self.assertEqual(metrics["release_success_rate"], 1.0)
        self.assertEqual(metrics["cases_over_two_repairs"], 0)
        for case in self.result["cases"]:
            self.assertEqual(case["prepare_stage"], "awaiting_release")
            self.assertEqual(case["release_stage"], "deliver")
            self.assertEqual(case["fixture_approval"]["kind"], "fixture")
            self.assertIn("not a production human", case["fixture_approval"]["reason"])
            self.assertLessEqual(case["repair_count"], 2)

    def test_unapproved_export_and_duplicate_steps_are_zero(self) -> None:
        metrics = self.result["metrics"]
        self.assertEqual(metrics["unapproved_export_attempts"], 10)
        self.assertEqual(metrics["unapproved_export_rejection_rate"], 1.0)
        self.assertEqual(metrics["unapproved_bundle_count"], 0)
        self.assertEqual(metrics["duplicate_successful_step_count"], 0)
        self.assertTrue(
            all(case["unapproved_export_rejected"] for case in self.result["cases"])
        )

    def test_all_required_failure_injections_fail_closed(self) -> None:
        probes = {item["probe"]: item for item in self.result["failure_injections"]}
        self.assertEqual(
            set(probes),
            {
                "unapproved_export",
                "state_tamper",
                "asset_tamper",
                "explicit_rejection",
                "same_approval_crash_retry",
                "maximum_two_repairs",
            },
        )
        self.assertTrue(all(item["passed"] for item in probes.values()))
        self.assertEqual(probes["unapproved_export"]["attempts"], 10)
        self.assertEqual(probes["unapproved_export"]["rejections"], 10)
        self.assertEqual(probes["unapproved_export"]["bundle_created_count"], 0)
        self.assertFalse(probes["state_tamper"]["bundle_created"])
        self.assertFalse(probes["asset_tamper"]["bundle_created"])
        self.assertFalse(probes["explicit_rejection"]["bundle_created"])
        self.assertEqual(probes["maximum_two_repairs"]["repair_count"], 2)
        retry = probes["same_approval_crash_retry"]
        self.assertTrue(retry["same_approval_id"])
        self.assertEqual(retry["release_approved_event_count"], 1)
        self.assertEqual(retry["campaign_delivered_event_count"], 1)
        self.assertEqual(retry["duplicate_successful_step_count"], 0)

    def test_hash_trace_and_predeclared_gate_are_machine_readable(self) -> None:
        trace = self.result["hash_trace"]
        self.assertEqual(trace["algorithm"], "sha256")
        self.assertEqual(len(trace["root"]), 64)
        int(trace["root"], 16)
        self.assertTrue(trace["all_ledgers_verified"])
        self.assertTrue(trace["all_manifest_file_hashes_verified"])
        self.assertTrue(all(self.result["gates"].values()))
        self.assertTrue(self.result["passed"])
        persisted = json.loads(
            (self.output / "agent-vertical-slice-eval.json").read_text(encoding="utf-8")
        )
        self.assertEqual(persisted, self.result)

    def test_truth_boundaries_prevent_quality_or_hardware_overclaim(self) -> None:
        limitations = " ".join(self.result["limitations"]).lower()
        for required in (
            "not a human",
            "not claim 4a",
            "does not prove amd radeon",
            "not a real trained audience model",
        ):
            self.assertIn(required, limitations)


if __name__ == "__main__":
    unittest.main()
