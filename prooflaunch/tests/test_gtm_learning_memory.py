from __future__ import annotations

import unittest

from prooflaunch_remix.gtm_learning_memory import (
    LearningMemoryError,
    compile_project_learning_context,
    compile_strategy_memory_application,
    compile_strategy_memory_decision,
    compile_strategy_memory_resolution_context,
    promoted_memory_payload,
    strategy_memory_resolution_payload,
    validate_project_learning_context,
    validate_strategy_memory_application,
    validate_strategy_memory_decision,
    validate_strategy_memory_resolution,
    validate_strategy_memory_resolution_context,
)


def observation(**overrides: object) -> dict[str, object]:
    value: dict[str, object] = {
        "observation_id": "obs-001",
        "observation_sha256": "a" * 64,
        "experiment_id": "exp-001",
        "strategy_plan_sha256": "b" * 64,
        "channel": "short_video_organic",
        "derived_rates": {
            "qualified_action_rate": 0.12,
            "evidence_engagement_rate": 0.3,
            "unsubscribe_or_complaint_rate": 0.01,
        },
        "baseline_derived_rates": {
            "qualified_action_rate": 0.08,
            "evidence_engagement_rate": 0.2,
            "unsubscribe_or_complaint_rate": 0.01,
        },
        "evidence_class": "observational_attribution",
        "next_cycle_decision": "continue_candidate_for_human_review",
        "observed_sample_gate_passed": True,
        "baseline_sample_gate_passed": True,
        "comparison_ready": True,
        "zero_budget_contract_breach": False,
    }
    value.update(overrides)
    return value


class GovernedLearningMemoryTests(unittest.TestCase):
    @staticmethod
    def applicability(**overrides: str) -> dict[str, str]:
        value = {
            "industry": "developer tools",
            "business_model": "b2b",
            "lifecycle": "launch",
            "budget": "zero",
            "industry_risk": "standard",
            "market": "united states",
        }
        value.update(overrides)
        return value

    def memory_record(
        self,
        memory_id: str,
        *,
        decision: str = "continue_candidate_for_human_review",
        applicability: dict[str, str] | None = None,
        channel: str = "short_video_organic",
        approved_at: str = "2026-08-02T00:00:00Z",
    ) -> dict[str, object]:
        payload = promoted_memory_payload(
            observation(next_cycle_decision=decision, channel=channel),
            applicability_context=(
                self.applicability() if applicability is None else applicability
            ),
        )
        return {
            "memory_id": memory_id,
            "memory_sha256": ("a" if memory_id.endswith("1") else "b") * 64,
            "source_run_id": f"run-{memory_id}",
            "observation_id": f"obs-{memory_id}",
            "approved_at": approved_at,
            "payload": payload,
        }

    def test_promoted_memory_retains_aggregate_learning_not_raw_content(self) -> None:
        payload = promoted_memory_payload(observation())
        self.assertEqual(payload["source_observation_id"], "obs-001")
        self.assertFalse(payload["automatic_strategy_mutation_executed"])
        self.assertNotIn("metrics", payload)
        self.assertNotIn("source_uri", payload)
        self.assertNotIn("content", payload)

    def test_low_sample_or_budget_breach_cannot_enter_learning_memory(self) -> None:
        with self.assertRaisesRegex(LearningMemoryError, "sample"):
            promoted_memory_payload(observation(comparison_ready=False))
        with self.assertRaisesRegex(LearningMemoryError, "zero-budget"):
            promoted_memory_payload(observation(zero_budget_contract_breach=True))

    def test_reported_revenue_requires_bound_unit_economics(self) -> None:
        revenue_observation = observation(
            metrics={"conversions": 1, "revenue_usd": 10.0}
        )
        with self.assertRaisesRegex(LearningMemoryError, "unit-economics"):
            promoted_memory_payload(revenue_observation)

    def test_project_context_is_stable_sorted_and_human_reviewed(self) -> None:
        payload = promoted_memory_payload(observation())
        context = compile_project_learning_context(
            [
                {
                    "memory_id": "learning-002",
                    "memory_sha256": "d" * 64,
                    "source_run_id": "run-002",
                    "observation_id": "obs-002",
                    "approved_at": "2026-08-02T00:00:00Z",
                    "payload": {**payload, "source_observation_id": "obs-002"},
                },
                {
                    "memory_id": "learning-001",
                    "memory_sha256": "c" * 64,
                    "source_run_id": "run-001",
                    "observation_id": "obs-001",
                    "approved_at": "2026-08-01T00:00:00Z",
                    "payload": payload,
                },
            ]
        )
        self.assertEqual(
            [item["memory_id"] for item in context["memories"]],
            ["learning-001", "learning-002"],
        )
        self.assertTrue(context["human_promoted_only"])
        self.assertFalse(context["automatic_strategy_mutation_executed"])
        self.assertRegex(context["context_sha256"], r"^[0-9a-f]{64}$")
        self.assertEqual(validate_project_learning_context(context), context)
        tampered = {**context, "memory_count": 9}
        with self.assertRaises(LearningMemoryError):
            validate_project_learning_context(tampered)

    def test_strategy_memory_decision_ranks_only_contextual_human_learning(self) -> None:
        context = compile_project_learning_context([self.memory_record("memory-1")])
        decision = compile_strategy_memory_decision(
            context,
            operating_context=self.applicability(),
            selected_channels=("short_video_organic", "search_education"),
        )
        self.assertEqual(decision["status"], "eligible_pending_human_application")
        self.assertEqual(decision["eligible_memory_count"], 1)
        self.assertEqual(
            decision["recommended_directives"][0]["memory_id"], "memory-1"
        )
        self.assertGreaterEqual(
            decision["recommended_directives"][0]["applicability_score"], 8
        )
        self.assertTrue(decision["human_application_required"])
        self.assertFalse(decision["automatic_strategy_mutation_executed"])
        self.assertRegex(decision["decision_sha256"], r"^[0-9a-f]{64}$")
        self.assertEqual(validate_strategy_memory_decision(decision), decision)
        tampered = {**decision, "eligible_memory_count": 0}
        with self.assertRaisesRegex(LearningMemoryError, "eligible count"):
            validate_strategy_memory_decision(tampered)

    def test_paid_memory_cannot_flow_into_zero_budget_run(self) -> None:
        context = compile_project_learning_context(
            [
                self.memory_record(
                    "memory-1",
                    applicability=self.applicability(budget="scaled"),
                )
            ]
        )
        decision = compile_strategy_memory_decision(
            context,
            operating_context=self.applicability(budget="zero"),
            selected_channels=("short_video_organic",),
        )
        self.assertEqual(decision["status"], "no_applicable_human_memory")
        self.assertEqual(decision["eligible_memory_count"], 0)
        self.assertIn(
            "paid_or_mixed_learning_cannot_enter_zero_budget",
            decision["candidates"][0]["hard_blockers"],
        )

    def test_conflicting_applicable_directives_fail_closed(self) -> None:
        context = compile_project_learning_context(
            [
                self.memory_record("memory-1"),
                self.memory_record(
                    "memory-2",
                    decision="revise_one_variable_then_retest",
                    approved_at="2026-08-03T00:00:00Z",
                ),
            ]
        )
        decision = compile_strategy_memory_decision(
            context,
            operating_context=self.applicability(),
            selected_channels=("short_video_organic",),
        )
        self.assertEqual(decision["status"], "blocked_conflicting_human_memories")
        self.assertEqual(decision["conflict_count"], 1)
        self.assertEqual(decision["recommended_directives"], [])
        self.assertEqual(
            decision["conflicts"][0]["resolution_required"],
            "named_human_arbitration",
        )

        empty_resolutions = compile_strategy_memory_resolution_context([])
        blocked = compile_strategy_memory_application(
            decision,
            empty_resolutions,
        )
        self.assertEqual(
            blocked["status"], "blocked_pending_named_human_resolution"
        )
        self.assertEqual(blocked["selected_directives"], [])
        self.assertEqual(
            blocked["unresolved_conflict_channels"], ["short_video_organic"]
        )
        self.assertFalse(blocked["source_run_mutated"])

        resolution = strategy_memory_resolution_payload(
            decision,
            source_run_id="run-conflict",
            channel="short_video_organic",
            winner_memory_id="memory-2",
            resolved_by="Named GTM Owner",
            reason="The later controlled experiment has stronger aggregate evidence.",
            resolved_at="2026-08-03T01:00:00.000000Z",
        )
        self.assertEqual(validate_strategy_memory_resolution(resolution), resolution)
        resolution_context = compile_strategy_memory_resolution_context(
            [resolution]
        )
        self.assertEqual(
            validate_strategy_memory_resolution_context(resolution_context),
            resolution_context,
        )
        application = compile_strategy_memory_application(
            decision,
            resolution_context,
        )
        self.assertEqual(
            application["status"], "resolved_pending_named_human_application"
        )
        self.assertEqual(application["resolved_conflict_count"], 1)
        self.assertEqual(application["unresolved_conflict_channels"], [])
        self.assertEqual(
            application["selected_directives"][0]["memory_id"], "memory-2"
        )
        self.assertEqual(
            validate_strategy_memory_application(application), application
        )

        tampered = {
            **resolution,
            "winner_memory_id": "memory-1",
        }
        with self.assertRaisesRegex(LearningMemoryError, "integrity"):
            validate_strategy_memory_resolution(tampered)

    def test_resolution_cannot_select_ineligible_or_unrelated_memory(self) -> None:
        context = compile_project_learning_context(
            [
                self.memory_record("memory-1"),
                self.memory_record(
                    "memory-2",
                    decision="revise_one_variable_then_retest",
                ),
            ]
        )
        decision = compile_strategy_memory_decision(
            context,
            operating_context=self.applicability(),
            selected_channels=("short_video_organic",),
        )
        with self.assertRaisesRegex(LearningMemoryError, "outside"):
            strategy_memory_resolution_payload(
                decision,
                source_run_id="run-conflict",
                channel="short_video_organic",
                winner_memory_id="memory-unrelated",
                resolved_by="Named GTM Owner",
                reason="This must fail closed.",
                resolved_at="2026-08-03T01:00:00.000000Z",
            )

    def test_non_conflicting_recommendation_still_requires_named_application(self) -> None:
        context = compile_project_learning_context([self.memory_record("memory-1")])
        decision = compile_strategy_memory_decision(
            context,
            operating_context=self.applicability(),
            selected_channels=("short_video_organic",),
        )
        application = compile_strategy_memory_application(
            decision,
            compile_strategy_memory_resolution_context([]),
        )
        self.assertEqual(
            application["status"], "eligible_pending_named_human_application"
        )
        self.assertEqual(
            application["selected_directives"][0]["selection_basis"],
            "deterministic_contextual_ranking",
        )
        self.assertTrue(application["human_application_required"])
        self.assertFalse(application["automatic_strategy_mutation_executed"])

    def test_cross_industry_transfer_is_disclosed_but_high_risk_is_blocked(self) -> None:
        context = compile_project_learning_context(
            [
                self.memory_record(
                    "memory-1",
                    applicability=self.applicability(industry="consumer electronics"),
                )
            ]
        )
        cross_industry = compile_strategy_memory_decision(
            context,
            operating_context=self.applicability(industry="developer tools"),
            selected_channels=("short_video_organic",),
        )
        self.assertEqual(
            cross_industry["status"], "eligible_pending_human_application"
        )
        self.assertIn(
            "industry", cross_industry["candidates"][0]["mismatched_dimensions"]
        )
        self.assertNotIn(
            "industry", cross_industry["candidates"][0]["matched_dimensions"]
        )

        regulated = compile_strategy_memory_decision(
            context,
            operating_context=self.applicability(
                industry="developer tools", industry_risk="high_regulation"
            ),
            selected_channels=("short_video_organic",),
        )
        self.assertEqual(regulated["status"], "no_applicable_human_memory")
        self.assertIn(
            "standard_risk_learning_cannot_enter_high_regulation",
            regulated["candidates"][0]["hard_blockers"],
        )

    def test_business_model_mismatch_is_never_recommended(self) -> None:
        context = compile_project_learning_context([self.memory_record("memory-1")])
        decision = compile_strategy_memory_decision(
            context,
            operating_context=self.applicability(business_model="b2c"),
            selected_channels=("short_video_organic",),
        )
        self.assertEqual(decision["status"], "no_applicable_human_memory")
        self.assertIn(
            "business_model_mismatch", decision["candidates"][0]["hard_blockers"]
        )


if __name__ == "__main__":
    unittest.main()
