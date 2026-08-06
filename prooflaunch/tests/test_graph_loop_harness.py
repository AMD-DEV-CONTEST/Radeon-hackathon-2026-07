from __future__ import annotations

import unittest

from prooflaunch_remix.contracts import Stage
from prooflaunch_remix.graph_loop_harness import (
    GraphLoopHarnessError,
    production_graph_loop_harness,
)


class GraphLoopHarnessContractTests(unittest.TestCase):
    def test_fixed_graph_allows_only_declared_business_flow(self) -> None:
        contract = production_graph_loop_harness(
            maximum_actions=12, maximum_cost_usd=0
        )
        self.assertTrue(contract.allows_transition(Stage.EVIDENCE, Stage.PLAN))
        self.assertTrue(contract.allows_transition(Stage.AUDIT, Stage.REPAIR))
        self.assertTrue(contract.allows_transition(Stage.REPAIR, Stage.AUDIT))
        self.assertTrue(contract.allows_transition(Stage.AUDIT, Stage.AWAITING_RELEASE))
        with self.assertRaisesRegex(GraphLoopHarnessError, "forbidden"):
            contract.require_transition(Stage.CREATE, Stage.DELIVER)

    def test_loop_is_bounded_and_non_retryable_failures_fail_closed(self) -> None:
        contract = production_graph_loop_harness(
            maximum_actions=12, maximum_cost_usd=0
        )
        self.assertEqual(contract.loop_node, "repair")
        self.assertEqual(contract.loop_max_iterations, 2)
        self.assertIn("rights_failure", contract.no_retry_failures)
        self.assertIn("permission_denied", contract.no_retry_failures)

    def test_harness_has_no_publish_send_spend_or_delete_authority(self) -> None:
        receipt = production_graph_loop_harness(
            maximum_actions=12, maximum_cost_usd=0
        ).receipt()
        harness = receipt["harness"]
        self.assertTrue(harness["fail_closed"])
        self.assertTrue(harness["model_backend_independent"])
        self.assertEqual(harness["maximum_cost_usd"], 0)
        for action in (
            "external_publish",
            "outbound_message",
            "media_spend",
            "destructive_delete",
        ):
            self.assertIn(action, harness["prohibited_effects"])
        self.assertRegex(receipt["contract_sha256"], r"^[0-9a-f]{64}$")

    def test_under_budget_request_is_rejected_instead_of_silently_overspending(self) -> None:
        with self.assertRaisesRegex(GraphLoopHarnessError, r"\[5, 24\]"):
            production_graph_loop_harness(maximum_actions=4, maximum_cost_usd=0)


if __name__ == "__main__":
    unittest.main()
