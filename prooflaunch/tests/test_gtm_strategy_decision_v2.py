from __future__ import annotations

import copy
import unittest

from scripts.compile_gtm_strategy_decision_v2 import brief
from prooflaunch_remix.gtm_strategy_decision_v2 import GTMStrategyDecisionError, compile_strategy_decision_pack, verify_strategy_decision_pack


class GTMStrategyDecisionV2Tests(unittest.TestCase):
    def test_b2b_pack_has_seven_role_committee_five_wedges_and_four_rejections(self) -> None:
        payload = compile_strategy_decision_pack(brief("b2b"))
        verify_strategy_decision_pack(payload)
        self.assertEqual(payload["influence_graph"]["graph_type"], "buying_committee")
        self.assertEqual(len(payload["influence_graph"]["nodes"]), 7)
        self.assertEqual(len(payload["strategic_wedges"]), 5)
        self.assertEqual(len(payload["rejected_alternatives"]), 4)
        self.assertEqual(payload["decision_binding"]["primary_channel_count"], 1)
        self.assertEqual(payload["decision_binding"]["enhancing_channel_count"], 1)

    def test_b2c_pack_has_seven_role_influence_graph(self) -> None:
        payload = compile_strategy_decision_pack(brief("b2c"))
        self.assertEqual(payload["influence_graph"]["graph_type"], "consumer_influence")
        self.assertEqual({row["role"] for row in payload["influence_graph"]["nodes"]}, {"user", "payer", "household", "peer", "creator", "reviewer", "repeat_buyer"})

    def test_missing_entry_points_five_wedges_or_distinct_channels_fails(self) -> None:
        raw = brief("b2b"); raw["category_entry_points"] = []
        with self.assertRaises(GTMStrategyDecisionError): compile_strategy_decision_pack(raw)
        raw = brief("b2b"); raw["strategic_wedges"] = raw["strategic_wedges"][:4]
        with self.assertRaises(GTMStrategyDecisionError): compile_strategy_decision_pack(raw)
        raw = brief("b2b"); raw["strategic_wedges"][0]["enhancing_channel"] = raw["strategic_wedges"][0]["primary_channel"]
        with self.assertRaises(GTMStrategyDecisionError): compile_strategy_decision_pack(raw)

    def test_tampering_fails(self) -> None:
        payload = compile_strategy_decision_pack(brief("b2b"))
        broken = copy.deepcopy(payload); broken["external_publish_or_spend_allowed"] = True
        with self.assertRaises(GTMStrategyDecisionError): verify_strategy_decision_pack(broken)


if __name__ == "__main__":
    unittest.main()
