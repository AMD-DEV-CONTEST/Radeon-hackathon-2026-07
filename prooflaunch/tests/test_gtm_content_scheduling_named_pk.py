from __future__ import annotations

import copy
import hashlib
import json
import unittest
from pathlib import Path

from prooflaunch_remix.gtm_content_scheduling_named_pk import ContentSchedulingNamedPKError, compile_schedule, verify_schedule


ROOT = Path(__file__).resolve().parents[1]


class ContentSchedulingNamedPKTests(unittest.TestCase):
    def setUp(self) -> None:
        self.config = json.loads((ROOT / "config/codex-content-scheduling-named-pk-super-challenger-v1.json").read_text(encoding="utf-8"))

    def test_compiles_seven_distinct_human_gated_jobs(self) -> None:
        result = compile_schedule(self.config, source_candidate_sha256="a" * 64)
        verify_schedule(result)
        self.assertEqual(result["slot_count"], 7)
        self.assertEqual(len(result["opponent_stress_tests"]), 10)
        self.assertEqual(len({row["hook"] for row in result["slots"]}), 7)
        self.assertTrue(all(row["external_activation_executed"] is False for row in result["slots"]))
        self.assertEqual(result["source_artifact_count"], 4)
        self.assertTrue(all(row["source_artifact_sha256"] == "a" * 64 for row in result["slots"]))

    def test_fails_closed_on_duplicate_hook_or_auto_publish(self) -> None:
        duplicate = copy.deepcopy(self.config)
        duplicate["slots"][1]["hook"] = duplicate["slots"][0]["hook"]
        with self.assertRaises(ContentSchedulingNamedPKError):
            compile_schedule(duplicate, source_candidate_sha256="a" * 64)

    def test_compiled_calendar_binds_each_slot_to_a_real_source_file(self) -> None:
        calendar = json.loads(
            (
                ROOT
                / "artifacts/gtm-last-mile-pk-v1/content-scheduling-super-challenger-v1/content-calendar.json"
            ).read_text(encoding="utf-8")
        )
        self.assertEqual(calendar["source_artifact_count"], 4)
        for row in calendar["slots"]:
            source_path = str(row["source_asset"]).split("#", 1)[0]
            target = ROOT / source_path
            self.assertTrue(target.is_file(), source_path)
            self.assertEqual(row["source_artifact_sha256"], hashlib.sha256(target.read_bytes()).hexdigest())

    def test_v2_uses_seven_distinct_audience_jobs_without_spray_and_pray(self) -> None:
        config = json.loads(
            (ROOT / "config/codex-content-scheduling-named-pk-super-challenger-v2.json").read_text(encoding="utf-8")
        )
        result = compile_schedule(config, source_candidate_sha256="b" * 64)
        verify_schedule(result)
        self.assertEqual(result["channel_slot_counts"], config["expected_channel_counts"])
        self.assertEqual(result["channel_slot_counts"]["linkedin_organic"], 2)
        self.assertEqual(len(result["channel_slot_counts"]), 6)
        self.assertEqual(result["slots"][0]["channel"], "owned_interactive")
        self.assertIn("false rejection", result["slots"][2]["intended_learning"])
        self.assertIn("silent watch", result["slots"][3]["intended_learning"])
        self.assertIn("Suppress", result["slots"][5]["decision_rule"])
        self.assertEqual(result["completed_named_product_pk_count"], 0)
        self.assertEqual(result["candidate_win_count"], 0)


if __name__ == "__main__":
    unittest.main()
