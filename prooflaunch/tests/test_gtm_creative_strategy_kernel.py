from __future__ import annotations

import copy
import unittest

from prooflaunch_remix.gtm_creative_strategy_kernel import (
    CreativeStrategyKernelError,
    verify_creative_strategy_kernel,
)
from prooflaunch_remix.gtm_strategy import BudgetTier
from tests.test_gtm_production_pack import compile_pack


class CreativeStrategyKernelTests(unittest.TestCase):
    def test_production_pack_contains_three_distinct_evidence_bound_territories(self) -> None:
        _, _, pack = compile_pack()
        kernel = pack.creative_strategy_kernel

        self.assertEqual(kernel["creative_territory_count"], 3)
        self.assertEqual(
            len({row["hook_family"] for row in kernel["creative_territories"]}),
            3,
        )
        self.assertEqual(
            {row["proof_role"].split(" ")[2] for row in kernel["creative_territories"]},
            {pack.citation.proof_claim_id},
        )
        self.assertEqual(kernel["selected_territory_id"], None)
        self.assertTrue(kernel["named_human_selection_required"])
        verify_creative_strategy_kernel(kernel)

    def test_zero_budget_never_enables_paid_amplification_or_automatic_spend(self) -> None:
        _, _, pack = compile_pack(budget=BudgetTier.ZERO)
        gate = pack.creative_strategy_kernel["paid_amplification_gate"]

        self.assertFalse(gate["paid_amplification_allowed"])
        self.assertFalse(gate["automatic_spend_allowed"])
        self.assertFalse(gate["conditions_currently_observed"])
        self.assertEqual(
            {row["lever"] for row in pack.creative_strategy_kernel["zero_budget_growth_mix"]},
            {
                "product_utility",
                "founder_expertise",
                "customer_evidence",
                "community",
                "partner",
                "tool_content",
            },
        )

    def test_message_layers_do_not_collapse_and_artifact_carries_territories(self) -> None:
        _, _, pack = compile_pack()
        layers = pack.creative_strategy_kernel["message_hierarchy"]
        self.assertEqual(len(set(value.casefold() for value in layers.values())), 4)

        artifacts = pack.artifact_payloads()
        self.assertIn("creative-strategy-kernel.json", artifacts)
        self.assertEqual(
            artifacts["big-idea-and-message-hierarchy.json"]["creative_territories"],
            pack.creative_strategy_kernel["creative_territories"],
        )

    def test_tampering_fails_closed(self) -> None:
        _, _, pack = compile_pack()
        tampered = copy.deepcopy(pack.creative_strategy_kernel)
        tampered["paid_amplification_gate"]["automatic_spend_allowed"] = True
        with self.assertRaises(CreativeStrategyKernelError):
            verify_creative_strategy_kernel(tampered)


if __name__ == "__main__":
    unittest.main()
