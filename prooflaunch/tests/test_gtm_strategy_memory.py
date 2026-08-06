from __future__ import annotations

import unittest
from dataclasses import replace

from prooflaunch_remix.gtm_memory import (
    ApprovalStatus,
    CrossCampaignGrant,
    MemoryEntry,
    MemoryKind,
    MemoryPolicyError,
    MemoryScope,
    MemorySource,
    ProjectMemory,
    ScopeLevel,
)
from prooflaunch_remix.gtm_strategy import (
    AudienceICP,
    BrandConstitution,
    BudgetTier,
    BusinessModel,
    CampaignStrategyInput,
    Channel,
    ClaimEvidence,
    EvidenceRights,
    IndustryRisk,
    LifecycleStage,
    StrategyCompiler,
    StrategyContractError,
    strategy_digest,
)


NOW = "2026-08-02T12:00:00Z"
SHA = "a" * 64


def claim(**overrides: object) -> ClaimEvidence:
    values: dict[str, object] = {
        "claim_id": "claim-001",
        "text": "In the frozen owner study, 82% completed the setup task.",
        "evidence_uri": "project://evidence/study.json#result",
        "evidence_sha256": SHA,
        "rights": EvidenceRights.OWNED,
        "rights_reference": "owner-record-001",
        "valid_from": "2026-01-01T00:00:00Z",
        "valid_until": "2027-01-01T00:00:00Z",
        "approved_by": "claim-owner-001",
    }
    values.update(overrides)
    return ClaimEvidence(**values)  # type: ignore[arg-type]


def strategy_input(
    *,
    business_model: BusinessModel = BusinessModel.B2B,
    lifecycle: LifecycleStage = LifecycleStage.LAUNCH,
    budget: BudgetTier = BudgetTier.ZERO,
    risk: IndustryRisk = IndustryRisk.STANDARD,
    evidence: tuple[ClaimEvidence, ...] | None = None,
    campaign_id: str = "campaign-001",
    objective: str | None = None,
) -> CampaignStrategyInput:
    return CampaignStrategyInput(
        org_id="org-001",
        project_id="project-001",
        campaign_id=campaign_id,
        owner="gtm-owner-001",
        industry="enterprise software" if business_model == BusinessModel.B2B else "consumer wellness",
        lifecycle=lifecycle,
        budget=budget,
        industry_risk=risk,
        brand=BrandConstitution(
            brand_name="ProofLaunch",
            purpose="Help teams test useful ideas without inventing proof.",
            customer_promise="A traceable launch decision.",
            voice_principles=("specific", "calm", "evidence-first"),
            prohibited_tactics=("spam", "fabricated testimonials"),
        ),
        audience=AudienceICP(
            audience_id="icp-001",
            name="revenue operations leaders" if business_model == BusinessModel.B2B else "busy new parents",
            business_model=business_model,
            core_problem="campaign evidence is fragmented",
            desired_outcome="make a defensible launch decision",
            buying_context="committee review" if business_model == BusinessModel.B2B else "self-serve research",
        ),
        objective=objective or (
            "request a qualified pilot"
            if business_model == BusinessModel.B2B
            else "join the owned waitlist"
        ),
        offer="a seven-day evidence review",
        landing_url="https://example.test/proof",
        claims=evidence or (claim(),),
    )


class StrategyStageCoverageTests(unittest.TestCase):
    def assert_stage_strategy(
        self, model: BusinessModel, stage: LifecycleStage
    ) -> None:
        result = StrategyCompiler().compile(
            strategy_input(business_model=model, lifecycle=stage), at=NOW
        )
        self.assertNotEqual(result.primary_channel, result.secondary_channel)
        self.assertEqual(len(result.seven_day_content), 7)

    def test_b2b_pre_pmf(self) -> None:
        self.assert_stage_strategy(BusinessModel.B2B, LifecycleStage.PRE_PMF)

    def test_b2b_launch(self) -> None:
        result = StrategyCompiler().compile(strategy_input(), at=NOW)
        self.assertEqual(result.primary_channel, Channel.LINKEDIN_ORGANIC)

    def test_b2b_growth(self) -> None:
        self.assert_stage_strategy(BusinessModel.B2B, LifecycleStage.GROWTH)

    def test_b2b_mature(self) -> None:
        self.assert_stage_strategy(BusinessModel.B2B, LifecycleStage.MATURE)

    def test_b2c_pre_pmf(self) -> None:
        self.assert_stage_strategy(BusinessModel.B2C, LifecycleStage.PRE_PMF)

    def test_b2c_launch(self) -> None:
        result = StrategyCompiler().compile(
            strategy_input(business_model=BusinessModel.B2C), at=NOW
        )
        self.assertEqual(result.primary_channel, Channel.SHORT_VIDEO_ORGANIC)

    def test_b2c_growth(self) -> None:
        self.assert_stage_strategy(BusinessModel.B2C, LifecycleStage.GROWTH)

    def test_b2c_mature(self) -> None:
        self.assert_stage_strategy(BusinessModel.B2C, LifecycleStage.MATURE)

    def test_full_discrete_strategy_matrix_compiles_48_governed_contracts(self) -> None:
        observed = 0
        for business_model in BusinessModel:
            for lifecycle in LifecycleStage:
                for budget in BudgetTier:
                    for risk in IndustryRisk:
                        with self.subTest(
                            business_model=business_model.value,
                            lifecycle=lifecycle.value,
                            budget=budget.value,
                            risk=risk.value,
                        ):
                            evidence = (
                                claim(specialist_approved_by="regulated-reviewer-001"),
                            ) if risk is IndustryRisk.HIGH_REGULATION else (claim(),)
                            result = StrategyCompiler().compile(
                                strategy_input(
                                    business_model=business_model,
                                    lifecycle=lifecycle,
                                    budget=budget,
                                    risk=risk,
                                    evidence=evidence,
                                    campaign_id=(
                                        f"matrix-{business_model.value}-{lifecycle.value}-"
                                        f"{budget.value}-{risk.value}"
                                    ),
                                ),
                                at=NOW,
                            )
                            self.assertEqual(len(result.seven_day_content), 7)
                            self.assertNotEqual(
                                result.primary_channel, result.secondary_channel
                            )
                            self.assertFalse(
                                any(
                                    constraint.automated_publish_allowed
                                    for constraint in result.channel_constraints
                                )
                            )
                            if budget is BudgetTier.SCALED:
                                self.assertTrue(result.primary_channel.paid)
                                self.assertFalse(result.secondary_channel.paid)
                            else:
                                self.assertFalse(result.primary_channel.paid)
                                self.assertFalse(result.secondary_channel.paid)
                            observed += 1
        self.assertEqual(observed, 48)


class StrategySafetyAndExperimentTests(unittest.TestCase):
    def test_cta_normalizes_sentence_case_and_terminal_punctuation(self) -> None:
        result = StrategyCompiler().compile(
            strategy_input(objective="Earn qualified design-partner conversations."),
            at=NOW,
        )
        self.assertEqual(
            result.call_to_action,
            "Review the evidence, then decide whether to earn qualified design-partner conversations.",
        )
        self.assertNotIn("..", result.call_to_action)
        self.assertNotIn("to Earn", result.call_to_action)

    def test_cta_preserves_initial_acronym(self) -> None:
        result = StrategyCompiler().compile(
            strategy_input(objective="ROI-review the pilot?"), at=NOW
        )
        self.assertEqual(
            result.call_to_action,
            "Review the evidence, then decide whether to ROI-review the pilot.",
        )

    def test_zero_budget_excludes_paid_spam_and_automated_publish(self) -> None:
        result = StrategyCompiler().compile(strategy_input(), at=NOW)
        self.assertFalse(result.primary_channel.paid)
        self.assertFalse(result.secondary_channel.paid)
        for constraint in result.channel_constraints:
            self.assertIn("paid_placement", constraint.prohibited_actions)
            self.assertIn("spam", constraint.prohibited_actions)
            self.assertFalse(constraint.automated_publish_allowed)
            self.assertTrue(constraint.human_release_required)

    def test_scaled_budget_has_one_paid_and_one_organic_channel(self) -> None:
        result = StrategyCompiler().compile(
            strategy_input(budget=BudgetTier.SCALED), at=NOW
        )
        self.assertTrue(result.primary_channel.paid)
        self.assertFalse(result.secondary_channel.paid)

    def test_content_schedule_is_exactly_seven_human_released_days(self) -> None:
        result = StrategyCompiler().compile(strategy_input(), at=NOW)
        self.assertEqual([item.day for item in result.seven_day_content], list(range(1, 8)))
        self.assertTrue(
            all(
                item.release_mode == "human_review_then_manual_publish"
                for item in result.seven_day_content
            )
        )

    def test_seo_geo_intents_are_questions_not_keyword_stuffing(self) -> None:
        result = StrategyCompiler().compile(strategy_input(), at=NOW)
        self.assertEqual(len(result.seo_geo_question_intents), 4)
        self.assertTrue(all(item.endswith("?") for item in result.seo_geo_question_intents))

    def test_expired_claim_blocks_strategy(self) -> None:
        expired = claim(valid_until="2026-06-01T00:00:00Z")
        with self.assertRaisesRegex(StrategyContractError, "evidence_expired"):
            StrategyCompiler().compile(strategy_input(evidence=(expired,)), at=NOW)

    def test_unapproved_claim_blocks_strategy(self) -> None:
        unapproved = claim(approved_by=None)
        with self.assertRaisesRegex(StrategyContractError, "claim_not_approved"):
            StrategyCompiler().compile(strategy_input(evidence=(unapproved,)), at=NOW)

    def test_restricted_rights_block_strategy(self) -> None:
        restricted = claim(rights=EvidenceRights.RESTRICTED)
        with self.assertRaisesRegex(StrategyContractError, "evidence_rights_restricted"):
            StrategyCompiler().compile(strategy_input(evidence=(restricted,)), at=NOW)

    def test_high_regulation_requires_specialist_approval(self) -> None:
        with self.assertRaisesRegex(StrategyContractError, "specialist_approval_required"):
            StrategyCompiler().compile(
                strategy_input(risk=IndustryRisk.HIGH_REGULATION), at=NOW
            )

    def test_high_regulation_compiles_with_specialist_approval_and_stop_rule(self) -> None:
        regulated = claim(specialist_approved_by="licensed-reviewer-001")
        result = StrategyCompiler().compile(
            strategy_input(
                risk=IndustryRisk.HIGH_REGULATION, evidence=(regulated,)
            ),
            at=NOW,
        )
        self.assertTrue(any("specialist approval" in rule for rule in result.stop_rules))

    def test_unsupported_viral_or_revenue_guarantee_is_rejected(self) -> None:
        unsafe = claim(text="This will go viral and will drive revenue.")
        with self.assertRaisesRegex(StrategyContractError, "unsupported_outcome_guarantee"):
            StrategyCompiler().compile(strategy_input(evidence=(unsafe,)), at=NOW)

    def test_strategy_is_deterministic_and_content_addressable(self) -> None:
        compiler = StrategyCompiler()
        request = strategy_input()
        first = compiler.compile(request, at=NOW)
        second = compiler.compile(request, at=NOW)
        self.assertEqual(first, second)
        self.assertEqual(strategy_digest(first), strategy_digest(second))

    def test_campaign_identity_changes_experiment_and_utm(self) -> None:
        compiler = StrategyCompiler()
        first = compiler.compile(strategy_input(campaign_id="alpha"), at=NOW)
        second = compiler.compile(strategy_input(campaign_id="beta"), at=NOW)
        self.assertNotEqual(first.attribution.experiment_id, second.attribution.experiment_id)
        self.assertNotEqual(first.attribution.utm_campaign, second.attribution.utm_campaign)

    def test_metrics_are_preregistered_and_attribution_is_noncausal(self) -> None:
        result = StrategyCompiler().compile(strategy_input(), at=NOW)
        self.assertTrue(all(metric.pre_registered_before_launch for metric in result.metrics))
        self.assertFalse(result.causal_outcome_claim_allowed)
        self.assertIn("not a causal revenue claim", result.attribution.interpretation)

    def test_proof_preserves_source_digest_and_brand_prohibitions(self) -> None:
        result = StrategyCompiler().compile(strategy_input(), at=NOW)
        self.assertEqual(result.proof_evidence_uri, "project://evidence/study.json#result")
        self.assertEqual(result.proof_evidence_sha256, SHA)
        self.assertTrue(
            all(
                "fabricated testimonials" in constraint.prohibited_actions
                for constraint in result.channel_constraints
            )
        )

    def test_evidence_change_rotates_strategy_identity(self) -> None:
        compiler = StrategyCompiler()
        first = compiler.compile(strategy_input(), at=NOW)
        updated = claim(evidence_sha256="b" * 64)
        second = compiler.compile(strategy_input(evidence=(updated,)), at=NOW)
        self.assertNotEqual(first.strategy_id, second.strategy_id)

    def test_unsafe_offer_cannot_enter_generated_copy(self) -> None:
        request = replace(strategy_input(), offer="guaranteed ROI program")
        with self.assertRaisesRegex(StrategyContractError, "unsupported outcome"):
            StrategyCompiler().compile(request, at=NOW)


def source(*, storage_allowed: bool = True) -> MemorySource:
    return MemorySource(
        uri="project://evidence/source.json#item",
        sha256=SHA,
        owner="evidence-owner-001",
        storage_allowed=storage_allowed,
    )


def scope(campaign: str | None = "campaign-a", project: str | None = "project-001") -> MemoryScope:
    return MemoryScope(org_id="org-001", project_id=project, campaign_id=campaign)


def entry(entry_id: str = "memory-001", **overrides: object) -> MemoryEntry:
    values: dict[str, object] = {
        "entry_id": entry_id,
        "key": "audience.primary_objection",
        "value": {"text": "Needs source-level proof"},
        "kind": MemoryKind.APPROVED_FACT,
        "scope": scope(),
        "source": source(),
        "owner": "memory-owner-001",
        "valid_from": "2026-01-01T00:00:00Z",
        "valid_until": "2027-01-01T00:00:00Z",
        "approval_status": ApprovalStatus.APPROVED,
        "approved_by": "memory-approver-001",
    }
    values.update(overrides)
    return MemoryEntry(**values)  # type: ignore[arg-type]


def grant(**overrides: object) -> CrossCampaignGrant:
    values: dict[str, object] = {
        "org_id": "org-001",
        "project_id": "project-001",
        "source_campaign_id": "campaign-a",
        "target_campaign_id": "campaign-b",
        "approved_by": "data-owner-001",
        "valid_from": "2026-01-01T00:00:00Z",
        "valid_until": "2027-01-01T00:00:00Z",
    }
    values.update(overrides)
    return CrossCampaignGrant(**values)  # type: ignore[arg-type]


class ProjectMemoryScopeTests(unittest.TestCase):
    def test_scope_levels_are_org_project_campaign(self) -> None:
        self.assertEqual(MemoryScope("org").level, ScopeLevel.ORG)
        self.assertEqual(MemoryScope("org", "project").level, ScopeLevel.PROJECT)
        self.assertEqual(MemoryScope("org", "project", "campaign").level, ScopeLevel.CAMPAIGN)

    def test_org_fact_is_visible_to_descendant_campaign(self) -> None:
        memory = ProjectMemory()
        item = entry(scope=MemoryScope("org-001"))
        memory.remember(item, actor="writer")
        self.assertEqual(memory.get(item.entry_id, target_scope=scope(), at=NOW), item)

    def test_project_fact_is_visible_to_its_campaign(self) -> None:
        memory = ProjectMemory()
        item = entry(scope=MemoryScope("org-001", "project-001"))
        memory.remember(item, actor="writer")
        self.assertEqual(memory.get(item.entry_id, target_scope=scope(), at=NOW), item)

    def test_project_fact_is_not_visible_to_another_project(self) -> None:
        memory = ProjectMemory()
        item = entry(scope=MemoryScope("org-001", "project-001"))
        memory.remember(item, actor="writer")
        with self.assertRaisesRegex(MemoryPolicyError, "access denied"):
            memory.get(
                item.entry_id,
                target_scope=MemoryScope("org-001", "project-002", "campaign-x"),
                at=NOW,
            )

    def test_same_campaign_read_is_allowed(self) -> None:
        memory = ProjectMemory()
        item = entry()
        memory.remember(item, actor="writer")
        self.assertEqual(memory.read(item.key, target_scope=scope(), at=NOW), (item,))

    def test_cross_campaign_read_without_grant_is_denied(self) -> None:
        memory = ProjectMemory()
        item = entry()
        memory.remember(item, actor="writer")
        with self.assertRaisesRegex(MemoryPolicyError, "access denied"):
            memory.get(item.entry_id, target_scope=scope("campaign-b"), at=NOW)

    def test_cross_campaign_read_with_explicit_current_grant_is_allowed(self) -> None:
        memory = ProjectMemory()
        item = entry()
        memory.remember(item, actor="writer")
        self.assertEqual(
            memory.get(
                item.entry_id,
                target_scope=scope("campaign-b"),
                at=NOW,
                grants=(grant(),),
            ),
            item,
        )

    def test_expired_cross_campaign_grant_is_denied(self) -> None:
        memory = ProjectMemory()
        item = entry()
        memory.remember(item, actor="writer")
        expired = grant(valid_until="2026-06-01T00:00:00Z")
        with self.assertRaisesRegex(MemoryPolicyError, "access denied"):
            memory.get(
                item.entry_id,
                target_scope=scope("campaign-b"),
                at=NOW,
                grants=(expired,),
            )


class ProjectMemoryValidityTests(unittest.TestCase):
    def test_unapproved_memory_is_rejected_before_durable_write(self) -> None:
        memory = ProjectMemory()
        pending = entry(
            approval_status=ApprovalStatus.PENDING,
            approved_by=None,
        )
        with self.assertRaisesRegex(MemoryPolicyError, "explicitly approved"):
            memory.remember(pending, actor="writer")
        self.assertEqual(memory.durable_count, 0)

    def test_expired_memory_fails_closed_on_get(self) -> None:
        memory = ProjectMemory()
        expired = entry(valid_until="2026-06-01T00:00:00Z")
        memory.remember(expired, actor="writer")
        with self.assertRaisesRegex(MemoryPolicyError, "not currently valid"):
            memory.get(expired.entry_id, target_scope=scope(), at=NOW)

    def test_conflicting_approved_values_fail_closed(self) -> None:
        memory = ProjectMemory()
        first = entry("memory-a")
        second = entry("memory-b", value={"text": "Prefers a live demo"})
        memory.remember(first, actor="writer")
        memory.remember(second, actor="writer")
        with self.assertRaisesRegex(MemoryPolicyError, "conflicting approved memory"):
            memory.read(first.key, target_scope=scope(), at=NOW)

    def test_approved_supersession_resolves_conflict(self) -> None:
        memory = ProjectMemory()
        first = entry("memory-a")
        second = entry(
            "memory-b",
            value={"text": "Prefers a live demo"},
            valid_from="2026-07-01T00:00:00Z",
            supersedes=(first.entry_id,),
        )
        memory.remember(first, actor="writer")
        memory.remember(second, actor="writer")
        self.assertEqual(memory.read(first.key, target_scope=scope(), at=NOW), (second,))
        with self.assertRaisesRegex(MemoryPolicyError, "superseded"):
            memory.get(first.entry_id, target_scope=scope(), at=NOW)

    def test_expired_superseding_truth_does_not_revive_old_truth(self) -> None:
        memory = ProjectMemory()
        first = entry("memory-a")
        second = entry(
            "memory-b",
            valid_from="2026-05-01T00:00:00Z",
            valid_until="2026-06-01T00:00:00Z",
            supersedes=(first.entry_id,),
        )
        memory.remember(first, actor="writer")
        memory.remember(second, actor="writer")
        with self.assertRaisesRegex(MemoryPolicyError, "no current approved"):
            memory.read(first.key, target_scope=scope(), at=NOW)

    def test_supersession_cannot_change_semantic_key(self) -> None:
        memory = ProjectMemory()
        first = entry("memory-a")
        memory.remember(first, actor="writer")
        replacement = entry(
            "memory-b", key="brand.voice", supersedes=(first.entry_id,)
        )
        with self.assertRaisesRegex(MemoryPolicyError, "semantic key"):
            memory.remember(replacement, actor="writer")

    def test_hidden_reasoning_is_never_admitted(self) -> None:
        with self.assertRaisesRegex(MemoryPolicyError, "hidden reasoning"):
            entry(value={"chain_of_thought": "private trace"})

    def test_durable_memory_is_isolated_from_mutable_caller_payload(self) -> None:
        memory = ProjectMemory()
        payload = {"text": "Original approved value"}
        item = entry(value=payload)
        memory.remember(item, actor="writer")
        payload["text"] = "Mutated after write"
        resolved = memory.get(item.entry_id, target_scope=scope(), at=NOW)
        self.assertEqual(resolved.value["text"], "Original approved value")

    def test_blank_actor_cannot_partially_write_memory(self) -> None:
        memory = ProjectMemory()
        with self.assertRaisesRegex(MemoryPolicyError, "actor is required"):
            memory.remember(entry(), actor="")
        self.assertEqual(memory.durable_count, 0)


class ProjectMemoryPromotionTests(unittest.TestCase):
    def test_temporary_run_memory_is_not_long_term_or_readable(self) -> None:
        memory = ProjectMemory()
        staged = entry(temporary_run_id="run-001")
        memory.stage_run(staged)
        self.assertEqual(memory.durable_count, 0)
        self.assertEqual(memory.temporary_count, 1)
        with self.assertRaisesRegex(MemoryPolicyError, "unavailable"):
            memory.get(staged.entry_id, target_scope=scope(), at=NOW)

    def test_approved_fact_can_be_promoted(self) -> None:
        memory = ProjectMemory()
        staged = entry(temporary_run_id="run-001")
        memory.stage_run(staged)
        promoted = memory.promote(staged.entry_id, actor="memory-owner")
        self.assertIsNone(promoted.temporary_run_id)
        self.assertEqual(memory.durable_count, 1)
        self.assertEqual(memory.temporary_count, 0)

    def test_observed_result_can_be_promoted_without_causal_relabeling(self) -> None:
        memory = ProjectMemory()
        staged = entry(
            kind=MemoryKind.OBSERVED_RESULT,
            value={"metric": "qualified_action_rate", "observed": 0.12},
            temporary_run_id="run-001",
        )
        memory.stage_run(staged)
        promoted = memory.promote(staged.entry_id, actor="analyst")
        self.assertEqual(promoted.kind, MemoryKind.OBSERVED_RESULT)
        self.assertEqual(promoted.value["observed"], 0.12)

    def test_working_note_cannot_be_promoted(self) -> None:
        memory = ProjectMemory()
        staged = entry(
            kind=MemoryKind.WORKING_NOTE,
            temporary_run_id="run-001",
        )
        memory.stage_run(staged)
        with self.assertRaisesRegex(MemoryPolicyError, "only approved facts"):
            memory.promote(staged.entry_id, actor="analyst")
        self.assertEqual(memory.temporary_count, 1)

    def test_generated_draft_cannot_be_written_directly(self) -> None:
        memory = ProjectMemory()
        draft = entry(kind=MemoryKind.GENERATED_DRAFT)
        with self.assertRaisesRegex(MemoryPolicyError, "only approved facts"):
            memory.remember(draft, actor="writer")

    def test_pending_fact_cannot_be_promoted(self) -> None:
        memory = ProjectMemory()
        staged = entry(
            approval_status=ApprovalStatus.PENDING,
            approved_by=None,
            temporary_run_id="run-001",
        )
        memory.stage_run(staged)
        with self.assertRaisesRegex(MemoryPolicyError, "explicitly approved"):
            memory.promote(staged.entry_id, actor="analyst")

    def test_source_without_storage_rights_cannot_be_promoted(self) -> None:
        memory = ProjectMemory()
        staged = entry(source=source(storage_allowed=False), temporary_run_id="run-001")
        memory.stage_run(staged)
        with self.assertRaisesRegex(MemoryPolicyError, "does not permit"):
            memory.promote(staged.entry_id, actor="analyst")

    def test_discard_run_removes_only_matching_temporary_entries(self) -> None:
        memory = ProjectMemory()
        first = entry("memory-a", temporary_run_id="run-a")
        second = entry("memory-b", temporary_run_id="run-b")
        memory.stage_run(first)
        memory.stage_run(second)
        self.assertEqual(memory.discard_run("run-a", actor="owner"), ("memory-a",))
        self.assertEqual(memory.temporary_count, 1)

    def test_events_preserve_promotion_actor_and_content_digest(self) -> None:
        memory = ProjectMemory()
        staged = entry(temporary_run_id="run-001")
        memory.stage_run(staged)
        promoted = memory.promote(staged.entry_id, actor="named-human")
        self.assertEqual(memory.events[-1].actor, "named-human")
        self.assertEqual(memory.events[-1].entry_sha256, promoted.content_sha256)


if __name__ == "__main__":
    unittest.main()
