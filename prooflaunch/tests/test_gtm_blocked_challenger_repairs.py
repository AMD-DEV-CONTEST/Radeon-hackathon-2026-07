from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from prooflaunch_remix.files import sha256_file  # noqa: E402
from prooflaunch_remix.gtm_unified_offline_review import sha256_json  # noqa: E402


PACK = ROOT / "artifacts/gtm-last-mile-pk-v1/challenger-repairs-v1/manifest.json"


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def assert_sealed(test: unittest.TestCase, payload: dict) -> None:
    unsigned = dict(payload)
    supplied = unsigned.pop("content_sha256")
    test.assertEqual(supplied, sha256_json(unsigned))


class GTMBlockedChallengerRepairTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.manifest = load(PACK)
        cls.rows = {
            Path(item["path"]).name: load(ROOT / item["path"])
            for item in cls.manifest["artifacts"]
        }

    def test_seven_content_addressed_repairs_are_present(self) -> None:
        assert_sealed(self, self.manifest)
        self.assertEqual(self.manifest["repair_artifact_count"], 7)
        self.assertEqual(len(self.rows), 7)
        for item in self.manifest["artifacts"]:
            path = ROOT / item["path"]
            self.assertEqual(path.stat().st_size, item["bytes"])
            self.assertEqual(sha256_file(path), item["sha256"])
            assert_sealed(self, load(path))

    def test_memory_and_agent_event_chains_are_exact_and_fail_closed(self) -> None:
        for name in ("cross-device-memory-execution.json", "employee-agent-execution-trace.json"):
            payload = self.rows[name]
            previous = "0" * 64
            for index, event in enumerate(payload["events"], 1):
                self.assertEqual(event["sequence"], index)
                self.assertEqual(event["previous_event_sha256"], previous)
                unsigned = dict(event)
                supplied = unsigned.pop("event_sha256")
                self.assertEqual(supplied, sha256_json(unsigned))
                previous = supplied
            self.assertTrue(payload["hash_chain_valid"])
            self.assertFalse(payload["external_publish_executed"])
        agent = self.rows["employee-agent-execution-trace.json"]
        self.assertTrue(agent["forced_tool_failure_observed"])
        self.assertTrue(agent["recovery_trace_observed"])
        self.assertTrue(agent["approval_denial_observed"])
        self.assertFalse(agent["external_action_executed"])

    def test_decision_analytics_and_seo_repairs_preserve_unknown_effects(self) -> None:
        memo = self.rows["data-strategy-decision-memo.json"]
        self.assertIsNone(memo["forecast_uncertainty"]["interval"])
        self.assertFalse(memo["causal_claim_allowed"])
        analytics = self.rows["product-analytics-measurement-system.json"]
        self.assertTrue(analytics["randomized_holdout"]["sticky_assignment"])
        self.assertFalse(analytics["incrementality"]["observed"])
        self.assertFalse(analytics["incrementality"]["causal_claim_allowed"])
        seo = self.rows["seo-technical-execution.json"]
        self.assertIsNone(seo["measured_organic_delta"])
        self.assertFalse(seo["performance_audit"]["lighthouse_observed"])

    def test_advertising_has_three_routes_zero_spend_and_human_authority(self) -> None:
        advertising = self.rows["advertising-creative-system.json"]
        self.assertEqual(len(advertising["creative_routes"]), 3)
        self.assertEqual(len({item["route"] for item in advertising["creative_routes"]}), 3)
        self.assertEqual(advertising["budget"]["amount"], 0)
        self.assertFalse(advertising["budget"]["activation_authorized"])
        self.assertFalse(advertising["pacing"]["automatic_reallocation"])
        self.assertTrue(all(advertising["human_authority"].values()))

    def test_lifecycle_joins_real_assets_to_explicitly_synthetic_observation(self) -> None:
        lifecycle = self.rows["gtm-lifecycle-execution-dossier.json"]
        for item in [lifecycle["strategy_binding"], *lifecycle["asset_bindings"]]:
            path = ROOT / item["path"]
            self.assertEqual(sha256_file(path), item["sha256"])
        observation = lifecycle["experiment_observation"]
        self.assertEqual(observation["class"], "synthetic")
        self.assertFalse(observation["production_outcome"])
        self.assertFalse(observation["causal_claim_allowed"])
        self.assertFalse(lifecycle["four_a_quality_proven"])


if __name__ == "__main__":
    unittest.main()
