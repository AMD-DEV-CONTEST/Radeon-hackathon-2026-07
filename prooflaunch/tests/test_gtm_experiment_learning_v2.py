from __future__ import annotations

import copy
import unittest

from prooflaunch_remix.gtm_experiment_learning_v2 import GTMExperimentLearningError, compile_experiment_learning_bundle, verify_experiment_learning_bundle


MONITOR = {key: 1 for key in ("creative_fatigue", "excessive_frequency", "negative_feedback", "audience_overlap", "cac_increase", "retention_decline")}


def experiment(factors=None, factorial=None, design="randomized_holdout") -> dict:
    return {"experiment_id": "exp-1", "mechanism_id": "mech-1", "audience_id": "aud-1", "hypothesis": "Proof consumption should increase under the selected mechanism.", "primary_metric": "proof consumption", "guardrails": ["negative feedback"], "duration_days": 14, "sample_plan": "two eligible comparison cells", "cost_ceiling_usd": 0, "stop_rule": "Stop on guardrail breach or duration end.", "factors_changed": factors or ["creative"], "factorial_design": factorial, "attribution_design": design, "causal_claim_planned": design != "descriptive_multi_touch", "monitoring_thresholds": MONITOR}


def outcome(verified=True) -> dict:
    return {"experiment_id": "exp-1", "result_status": "failed", "failure_reason": "Qualified proof consumption did not improve.", "evidence_status": "observed", "primary_metric_effect": -0.1, "confidence_interval": [-.2, 0], "negative_signals": [{"signal_type": "lost_deal", "summary": "Buyer could not verify the implementation boundary.", "required_next_test": "Test an implementation-boundary artifact."}], "human_verified": verified}


def matrix() -> list[dict]:
    return [{"mechanism_id": "mech-1", "subvertical_id": "b2b.test", "company_scale": "small", "lifecycle_state": "launch", "budget_tier": "zero_paid", "market": "north_america", "effect_metric": "proof consumption", "effect_estimate": -.1, "ci_lower": -.2, "ci_upper": 0, "evidence_status": "observed"}]


def allocation() -> list[dict]:
    return [{"mechanism_id": "mech-1", "exploration_share": .3, "exploitation_share": .7, "platform_shares": {"linkedin": .5, "owned": .5}, "creative_family_shares": {"proof": .5, "tool": .5}}]


class GTMExperimentLearningV2Tests(unittest.TestCase):
    def test_failure_eval_task_and_human_approved_memory_are_preserved(self) -> None:
        memory = [{"experiment_id": "exp-1", "memory_statement": "The implementation boundary must be explicit for this audience.", "human_approval": {"decision": "approved_for_long_term_memory", "approver_name": "Taylor Kim"}}]
        payload = compile_experiment_learning_bundle([experiment()], [outcome()], memory, matrix(), allocation()); verify_experiment_learning_bundle(payload)
        self.assertEqual(len(payload["evaluation_tasks_from_negative_signals"]), 1)
        self.assertEqual(payload["promoted_memory_count"], 1)
        self.assertEqual(len(payload["unified_outcome_chain"]), 8)

    def test_unverified_memory_never_promotes(self) -> None:
        memory = [{"experiment_id": "exp-1", "memory_statement": "Unverified model judgment remains only a candidate.", "human_approval": {"decision": "approved_for_long_term_memory", "approver_name": "Taylor Kim"}}]
        payload = compile_experiment_learning_bundle([experiment()], [outcome(False)], memory, matrix(), allocation())
        self.assertEqual(payload["promoted_memory_count"], 0)

    def test_multifactor_without_factorial_descriptive_causality_and_correlation_fail(self) -> None:
        with self.assertRaises(GTMExperimentLearningError): compile_experiment_learning_bundle([experiment(["creative", "channel"])], [], [], [], [])
        with self.assertRaises(GTMExperimentLearningError): compile_experiment_learning_bundle([experiment(design="descriptive_multi_touch") | {"causal_claim_planned": True}], [], [], [], [])
        bad_allocation = allocation(); bad_allocation[0]["platform_shares"] = {"linkedin": .8, "owned": .2}
        with self.assertRaises(GTMExperimentLearningError): compile_experiment_learning_bundle([experiment()], [], [], [], bad_allocation)

    def test_tampering_fails(self) -> None:
        payload = compile_experiment_learning_bundle([experiment()], [outcome()], [], matrix(), allocation()); broken = copy.deepcopy(payload); broken["policy"]["external_experiment_execution_allowed"] = True
        with self.assertRaises(Exception): verify_experiment_learning_bundle(broken)


if __name__ == "__main__": unittest.main()
