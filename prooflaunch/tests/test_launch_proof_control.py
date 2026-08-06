from __future__ import annotations

import copy
import unittest

from prooflaunch_remix.launch_proof_control import (
    GATE_IDS,
    LaunchProofControlError,
    compile_launch_proof_control,
    validate_launch_proof_control,
)


def readiness(*, external: bool) -> dict[str, object]:
    return {
        "schema": "ProofLaunchAug3ProductReadinessV1",
        "verification": {
            "product_critical_regression": {"passed": True},
            "production_trace_remote_required_check_observed": external,
            "lifecycle_closure_production_outcomes_observed": 12 if external else 0,
            "gtm_cockpit_four_a_effect_claim_eligible": external,
            "revenue_feedback_causal_revenue_claim_allowed": external,
        },
    }


def portfolio(*, passed: bool) -> dict[str, object]:
    return {
        "schema": "ProofLaunchPortfolioBlindReviewQueueStatusV1",
        "submitted_review_count": 270 if passed else 0,
        "expected_review_count": 270,
        "review_complete": passed,
        "portfolio_promotion_passed": passed,
        "human_preference_observed": passed,
    }


def judge(*, passed: bool) -> dict[str, object]:
    return {
        "schema": "ProofLaunchJudgeCalibrationStatusV1",
        "submitted_review_count": 300 if passed else 0,
        "expected_review_count": 300,
        "review_complete": passed,
        "judge_calibrated": passed,
    }


def guardrails(*, deployed: bool) -> dict[str, object]:
    return {
        "schema": "ProofLaunchProductionGuardrailStatusV1",
        "event_count": 400 if deployed else 8,
        "blocked_event_count": 4 if deployed else 0,
        "production_deployment_observed": deployed,
        "hash_chain_valid": True,
        "raw_content_retained": False,
    }


def traces(*, deployed: bool) -> dict[str, object]:
    return {
        "schema": "ProofLaunchProductionTraceStatusV1",
        "request_trace_count": 400 if deployed else 10,
        "production_deployment_observed": deployed,
        "retention_days": 90,
        "hash_chain_valid": True,
        "raw_content_retained": False,
    }


def radeon(*, passed: bool) -> dict[str, object]:
    return {
        "schema": "ProofLaunchRadeonLivePreflightV1",
        "radeon_runtime_observed": passed,
        "preflight_passed": passed,
        "model_inference_observed": passed,
    }


class LaunchProofControlTests(unittest.TestCase):
    def test_current_local_state_remains_blocked_with_exact_actions(self) -> None:
        receipt = compile_launch_proof_control(
            product_readiness=readiness(external=False),
            portfolio_status=portfolio(passed=False),
            judge_status=judge(passed=False),
            guardrail_status=guardrails(deployed=False),
            trace_status=traces(deployed=False),
            radeon_receipt=None,
        )
        validate_launch_proof_control(receipt)
        self.assertEqual(tuple(gate["gate_id"] for gate in receipt["gates"]), GATE_IDS)
        self.assertEqual(receipt["passed_gate_count"], 1)
        self.assertEqual(receipt["blocked_gate_count"], 8)
        self.assertEqual(receipt["launch_decision"], "blocked_pending_external_evidence")
        self.assertEqual(len(receipt["next_actions"]), 8)
        self.assertFalse(receipt["four_a_claim_allowed"])
        self.assertFalse(receipt["top1_claim_allowed"])
        self.assertFalse(receipt["causal_revenue_claim_allowed"])

    def test_all_external_evidence_can_pass_without_granting_automatic_authority(self) -> None:
        receipt = compile_launch_proof_control(
            product_readiness=readiness(external=True),
            portfolio_status=portfolio(passed=True),
            judge_status=judge(passed=True),
            guardrail_status=guardrails(deployed=True),
            trace_status=traces(deployed=True),
            radeon_receipt=radeon(passed=True),
        )
        self.assertEqual(receipt["passed_gate_count"], 9)
        self.assertEqual(receipt["blocked_gate_count"], 0)
        self.assertEqual(receipt["launch_decision"], "production_promotion_eligible")
        self.assertEqual(receipt["next_actions"], [])
        self.assertTrue(receipt["four_a_claim_allowed"])
        self.assertTrue(receipt["causal_revenue_claim_allowed"])
        self.assertFalse(receipt["top1_claim_allowed"])
        self.assertFalse(receipt["automatic_publish_enabled"])
        self.assertFalse(receipt["automatic_spend_enabled"])

    def test_tamper_and_wrong_source_schema_fail_closed(self) -> None:
        receipt = compile_launch_proof_control(
            product_readiness=readiness(external=False),
            portfolio_status=portfolio(passed=False),
            judge_status=judge(passed=False),
            guardrail_status=guardrails(deployed=False),
            trace_status=traces(deployed=False),
            radeon_receipt=None,
        )
        tampered = copy.deepcopy(receipt)
        tampered["gates"][1]["passed"] = True
        with self.assertRaisesRegex(LaunchProofControlError, "digest"):
            validate_launch_proof_control(tampered)
        invalid = readiness(external=False)
        invalid["schema"] = "Unknown"
        with self.assertRaisesRegex(LaunchProofControlError, "product readiness"):
            compile_launch_proof_control(
                product_readiness=invalid,
                portfolio_status=portfolio(passed=False),
                judge_status=judge(passed=False),
                guardrail_status=guardrails(deployed=False),
                trace_status=traces(deployed=False),
                radeon_receipt=None,
            )


if __name__ == "__main__":
    unittest.main()
