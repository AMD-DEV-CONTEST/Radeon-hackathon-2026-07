from __future__ import annotations

import copy
import unittest

from prooflaunch_remix.gtm_mechanism_abstraction import (
    MechanismAbstractionError,
    compile_mechanism_abstraction_register,
    verify_mechanism_abstraction_register,
)


def case(case_id: str, industry: str, **overrides: object) -> dict[str, object]:
    value: dict[str, object] = {
        "case_id": case_id,
        "source_uri": f"https://example.com/cases/{case_id}",
        "source_sha256": ("a" if case_id == "case-a" else "b") * 64,
        "observed_at": "2026-07-30T12:00:00Z",
        "rights_status": "public_measurement",
        "named_reviewer": "reviewer-001",
        "outcome_class": "relative_breakout_candidate",
        "causal_chain": {
            "trigger_background": "a decision became urgent after a workflow change",
            "audience_tension": "the buyer needed proof without a long implementation commitment",
            "hook_mechanism": "show the unresolved decision before the product",
            "proof_mechanism": "make one source-bound operational claim inspectable",
            "format_mechanism": "question-to-evidence-card sequence",
            "distribution_mechanism": "standalone expert contribution in a concentrated audience",
            "conversion_path": "qualified objection to manual evidence review",
        },
        "applicability": {
            "industry": industry,
            "company_scale": "startup",
            "budget": "zero_to_small",
            "market": "English-speaking",
            "platform": "professional community",
            "lifecycle": "launch",
        },
        "counterfactual": {
            "without_brand_budget_or_celebrity": "weakens",
            "rationale": "the mechanism retains decision value but loses some initial reach",
        },
        "originality_similarity": {
            "semantic": 0.31,
            "structure": 0.42,
            "visual": 0.27,
            "shot": 0.35,
        },
        "strategy_tags": ["community_contribution", "long_term_brand_asset"],
    }
    value.update(overrides)
    return value


class MechanismAbstractionTests(unittest.TestCase):
    def test_empty_runtime_register_is_honest_and_non_mutating(self) -> None:
        receipt = compile_mechanism_abstraction_register(())
        self.assertEqual(receipt["case_count"], 0)
        self.assertEqual(receipt["operational_state"], "awaiting_named_human_case_abstraction")
        self.assertFalse(receipt["automatic_strategy_mutation_executed"])
        self.assertFalse(receipt["automatic_training_admission_executed"])
        verify_mechanism_abstraction_register(receipt)

    def test_cases_create_causal_failure_boundary_conflict_and_originality_records(self) -> None:
        successful = case("case-a", "manufacturing")
        failed = case(
            "case-b",
            "professional services",
            outcome_class="high_attention_low_conversion",
            strategy_tags=["premium_trust", "aggressive_discount"],
        )
        first = compile_mechanism_abstraction_register((successful, failed))
        source_ids = [row["mechanism_id"] for row in first["cases"]]
        receipt = compile_mechanism_abstraction_register(
            (successful, failed),
            recombinations=(
                {
                    "source_mechanism_ids": source_ids,
                    "owner_proof_id": "claim-001",
                },
            ),
        )

        self.assertEqual(receipt["failure_case_count"], 1)
        self.assertEqual(receipt["strategy_conflict_case_count"], 1)
        self.assertEqual(receipt["originality_gate_pass_count"], 2)
        self.assertEqual(receipt["recombination_count"], 1)
        self.assertFalse(receipt["recombinations"][0]["creative_expression_copied"])
        self.assertTrue(receipt["recombinations"][0]["cross_industry_gate_passed"])
        self.assertTrue(all(not row["training_admitted"] for row in receipt["cases"]))
        verify_mechanism_abstraction_register(receipt)

    def test_raw_expression_and_tampering_fail_closed(self) -> None:
        with self.assertRaises(MechanismAbstractionError):
            compile_mechanism_abstraction_register(({**case("case-a", "SaaS"), "raw_text": "copied campaign"},))

        receipt = compile_mechanism_abstraction_register((case("case-a", "SaaS"),))
        tampered = copy.deepcopy(receipt)
        tampered["automatic_strategy_mutation_executed"] = True
        with self.assertRaises(MechanismAbstractionError):
            verify_mechanism_abstraction_register(tampered)


if __name__ == "__main__":
    unittest.main()
