from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path

from prooflaunch_remix.gtm_strategy_portfolio import (
    GTMStrategyPortfolioError,
    build_task_prompt,
    compile_strategy_portfolio_receipt,
    compile_strategy_portfolio_quality_audit,
    load_portfolio_cases,
    validate_strategy_portfolio_receipt,
    validate_strategy_portfolio_quality_audit,
)


ROOT = Path(__file__).resolve().parents[1]
CASES_PATH = ROOT / "config/local-gemma3-zero-budget-strategy-portfolio-v1.json"


def candidate(case: dict[str, str]) -> dict[str, object]:
    return {
        "scenario_binding": {
            field: case[field]
            for field in (
                "business_model",
                "case_id",
                "icp",
                "industry",
                "industry_risk",
                "lifecycle",
                "market",
                "product_name",
                "required_primary_channel",
            )
        },
        "strategy": (
            f"For {case['icp']}, position {case['product_name']} around its supplied product "
            "characteristic and invite a bounded workflow review without promising an outcome."
        ),
        "primary_channel": case["required_primary_channel"],
        "channel_rationale": "The supplied audience already exchanges workflow examples in practitioner communities, which can be investigated without a performance claim.",
        "zero_budget_loop": [
            "Co-create a diagnostic worksheet with two practitioners and preserve each source permission.",
            "Publish the worksheet in one relevant community and invite evidence-bound replies.",
            "Share a partner teardown that records limitations and routes interested readers to the same review.",
            "Log qualified conversations in the ledger, review objections, and stop if the preregistered rule is not met.",
        ],
        "experiment": {
            "treatment": "Send the diagnostic worksheet and review invitation to the assigned treatment accounts.",
            "comparable_baseline": "Randomly split the same eligible account pool 50/50 into a same-window treatment and holdout.",
            "observation_window_days": 14,
            "primary_metric": "qualified_conversations",
            "decision_rule": "Continue only after at least 20 qualified conversations are logged and the predeclared comparison is reviewable.",
        },
        "human_gate": {
            "role": "Product Marketing Lead",
            "decision": "approve_or_reject",
            "artifact": "Rights log, treatment assignment, and qualified-conversation ledger",
        },
        "unsupported_claims": ["No conversion, revenue, ROI, or market-leadership result has been observed."],
    }


class GTMStrategyPortfolioTests(unittest.TestCase):
    def setUp(self) -> None:
        self.cases = load_portfolio_cases(json.loads(CASES_PATH.read_text(encoding="utf-8")))

    def test_frozen_cases_cover_business_model_lifecycle_and_risk_axes(self) -> None:
        self.assertEqual(len(self.cases), 8)
        self.assertEqual({case["business_model"] for case in self.cases}, {"b2b", "b2c"})
        self.assertEqual(
            {case["lifecycle"] for case in self.cases},
            {"pre_pmf", "launch", "growth", "mature"},
        )
        self.assertEqual(
            {case["industry_risk"] for case in self.cases},
            {"standard", "high_regulation"},
        )
        self.assertEqual(
            {case["required_primary_channel"] for case in self.cases},
            {"LinkedIn", "community", "partner", "owned"},
        )

    def test_prompt_binds_exact_scenario_and_zero_budget_effect_rules(self) -> None:
        prompt = build_task_prompt(self.cases[0])
        self.assertIn(self.cases[0]["product_name"], prompt)
        self.assertIn(self.cases[0]["icp"], prompt)
        self.assertIn(
            f"primary_channel: exactly {self.cases[0]['required_primary_channel']}", prompt
        )
        self.assertIn("same-window treatment and holdout", prompt)
        self.assertIn("must not imply that any result has already occurred", prompt)

    def test_cross_case_binding_is_rejected(self) -> None:
        attempts = {
            case["case_id"]: [
                {
                    "raw_output": json.dumps(
                        candidate(self.cases[1] if case == self.cases[0] else case)
                    )
                }
            ]
            for case in self.cases
        }
        receipt = compile_strategy_portfolio_receipt(
            model_id="mlx-community/gemma-3-12b-it-4bit",
            model_revision="revision-123",
            model_manifest_sha256="a" * 64,
            device_family="Apple Metal",
            cases=self.cases,
            case_attempts=attempts,
        )
        self.assertEqual(receipt["accepted_case_count"], 7)
        self.assertFalse(receipt["results"][0]["accepted"])

    def test_complete_receipt_validates_and_retains_truth_boundaries(self) -> None:
        attempts = {
            case["case_id"]: [{"raw_output": json.dumps(candidate(case))}]
            for case in self.cases
        }
        receipt = compile_strategy_portfolio_receipt(
            model_id="mlx-community/gemma-3-12b-it-4bit",
            model_revision="revision-123",
            model_manifest_sha256="a" * 64,
            device_family="Apple Metal",
            cases=self.cases,
            case_attempts=attempts,
        )
        validate_strategy_portfolio_receipt(receipt)
        self.assertTrue(receipt["all_cases_accepted"])
        self.assertFalse(receipt["any_industry_generalization_claim_eligible"])
        self.assertFalse(receipt["four_a_claim_eligible"])
        self.assertFalse(receipt["causal_effect_claim_eligible"])

    def test_receipt_tampering_fails_closed(self) -> None:
        attempts = {
            case["case_id"]: [{"raw_output": json.dumps(candidate(case))}]
            for case in self.cases
        }
        receipt = compile_strategy_portfolio_receipt(
            model_id="model",
            model_revision="revision",
            model_manifest_sha256="b" * 64,
            device_family="Apple Metal",
            cases=self.cases,
            case_attempts=attempts,
        )
        tampered = copy.deepcopy(receipt)
        tampered["results"][0]["scenario"]["market"] = "Other"
        with self.assertRaisesRegex(GTMStrategyPortfolioError, "digest"):
            validate_strategy_portfolio_receipt(tampered)

    def test_quality_audit_rejects_channel_balanced_but_boilerplate_strategies(self) -> None:
        attempts = {
            case["case_id"]: [{"raw_output": json.dumps(candidate(case))}]
            for case in self.cases
        }
        receipt = compile_strategy_portfolio_receipt(
            model_id="model",
            model_revision="revision",
            model_manifest_sha256="c" * 64,
            device_family="Apple Metal",
            cases=self.cases,
            case_attempts=attempts,
        )
        audit = compile_strategy_portfolio_quality_audit(receipt)
        validate_strategy_portfolio_quality_audit(audit, receipt)
        self.assertTrue(audit["channel_diversity_gate_passed"])
        self.assertEqual(audit["channel_distribution"], {
            "LinkedIn": 2,
            "community": 2,
            "owned": 2,
            "partner": 2,
        })
        self.assertEqual(audit["unique_strategy_count"], 8)
        self.assertFalse(audit["distinctiveness_gate_passed"])
        self.assertFalse(audit["portfolio_quality_gate_passed"])
        self.assertFalse(audit["human_preference_observed"])


if __name__ == "__main__":
    unittest.main()
