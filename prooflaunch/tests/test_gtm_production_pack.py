from __future__ import annotations

import json
import unittest
from dataclasses import replace

from prooflaunch_remix.gtm_production_pack import (
    EvidenceCitation,
    ProductionPackCompiler,
    ProductionPackError,
    TruthStatus,
    canonical_json,
    production_pack_digest,
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
)


NOW = "2026-08-02T12:00:00Z"
SHA = "a" * 64


def make_claim(**overrides: object) -> ClaimEvidence:
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
        "specialist_approved_by": None,
    }
    values.update(overrides)
    return ClaimEvidence(**values)  # type: ignore[arg-type]


def make_request(
    *,
    business_model: BusinessModel = BusinessModel.B2B,
    lifecycle: LifecycleStage = LifecycleStage.LAUNCH,
    budget: BudgetTier = BudgetTier.ZERO,
    risk: IndustryRisk = IndustryRisk.STANDARD,
    claim: ClaimEvidence | None = None,
    landing_url: str = "https://example.test/proof?ref=owner#details",
    industry: str | None = None,
) -> CampaignStrategyInput:
    evidence = claim or make_claim(
        specialist_approved_by=(
            "licensed-reviewer-001"
            if risk == IndustryRisk.HIGH_REGULATION
            else None
        )
    )
    return CampaignStrategyInput(
        org_id="org-001",
        project_id="project-001",
        campaign_id="campaign-001",
        owner="gtm-owner-001",
        industry=industry or ("enterprise software" if business_model == BusinessModel.B2B else "consumer care"),
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
            name=(
                "revenue operations leaders"
                if business_model == BusinessModel.B2B
                else "busy new parents"
            ),
            business_model=business_model,
            core_problem="campaign evidence is fragmented",
            desired_outcome="make a defensible launch decision",
            buying_context=(
                "committee review"
                if business_model == BusinessModel.B2B
                else "self-serve research"
            ),
        ),
        objective=(
            "request a qualified pilot"
            if business_model == BusinessModel.B2B
            else "join the owned waitlist"
        ),
        offer="a seven-day evidence review",
        landing_url=landing_url,
        claims=(evidence,),
    )


def compile_pack(**kwargs: object):
    request = make_request(**kwargs)  # type: ignore[arg-type]
    strategy = StrategyCompiler().compile(request, at=NOW)
    return request, strategy, ProductionPackCompiler().compile(request, strategy)


class ProductionPackMarketCoverageTests(unittest.TestCase):
    def test_b2b_launch_uses_linkedin_native_copy(self) -> None:
        _, _, pack = compile_pack()
        self.assertEqual(pack.primary_copy.channel, Channel.LINKEDIN_ORGANIC)
        self.assertEqual(pack.primary_copy.native_format, "LinkedIn text post")

    def test_b2c_launch_uses_short_video_native_copy(self) -> None:
        _, _, pack = compile_pack(business_model=BusinessModel.B2C)
        self.assertEqual(pack.primary_copy.channel, Channel.SHORT_VIDEO_ORGANIC)
        self.assertEqual(pack.primary_copy.native_format, "vertical short-video script")

    def test_b2b_pre_pmf_compiles(self) -> None:
        _, _, pack = compile_pack(lifecycle=LifecycleStage.PRE_PMF)
        self.assertEqual(pack.primary_copy.channel, Channel.FOUNDER_CONVERSATIONS)

    def test_b2c_growth_compiles(self) -> None:
        _, _, pack = compile_pack(
            business_model=BusinessModel.B2C,
            lifecycle=LifecycleStage.GROWTH,
        )
        self.assertEqual(pack.primary_copy.channel, Channel.SEARCH_EDUCATION)

    def test_mature_stage_compiles(self) -> None:
        _, _, pack = compile_pack(lifecycle=LifecycleStage.MATURE)
        self.assertEqual(pack.primary_copy.channel, Channel.CUSTOMER_EVIDENCE)

    def test_small_budget_stays_organic(self) -> None:
        _, _, pack = compile_pack(budget=BudgetTier.SMALL)
        self.assertFalse(pack.primary_copy.channel.paid)
        self.assertFalse(pack.secondary_copy.channel.paid)

    def test_scaled_b2b_has_paid_search_draft_but_manual_release(self) -> None:
        _, _, pack = compile_pack(budget=BudgetTier.SCALED)
        self.assertEqual(pack.primary_copy.channel, Channel.PAID_SEARCH)
        self.assertEqual(pack.manual_release.publish_mode, "manual_only")

    def test_scaled_b2c_has_paid_social_draft_but_no_external_release(self) -> None:
        _, _, pack = compile_pack(
            business_model=BusinessModel.B2C,
            budget=BudgetTier.SCALED,
        )
        self.assertEqual(pack.primary_copy.channel, Channel.PAID_SOCIAL)
        self.assertFalse(pack.manual_release.external_release_performed)


class ProductionPackSpineAndCopyTests(unittest.TestCase):
    def test_big_idea_is_explicitly_a_hypothesis(self) -> None:
        _, strategy, pack = compile_pack()
        self.assertTrue(pack.big_idea.hypothesis.startswith("Hypothesis:"))
        self.assertEqual(pack.big_idea.hypothesis, strategy.hero_hypothesis)

    def test_message_hierarchy_preserves_strategy_spine(self) -> None:
        _, strategy, pack = compile_pack()
        self.assertEqual(pack.message_hierarchy.evidenced_proof, strategy.proof)
        self.assertEqual(pack.message_hierarchy.call_to_action, strategy.call_to_action)

    def test_primary_and_secondary_copy_are_not_verbatim_duplicates(self) -> None:
        _, _, pack = compile_pack()
        self.assertNotEqual(
            pack.primary_copy.rendered_text,
            pack.secondary_copy.rendered_text,
        )
        self.assertNotEqual(pack.primary_copy.native_format, pack.secondary_copy.native_format)

    def test_channel_copy_contains_exact_approved_proof(self) -> None:
        _, strategy, pack = compile_pack()
        self.assertIn(strategy.proof, pack.primary_copy.rendered_text)
        self.assertIn(strategy.proof, pack.secondary_copy.rendered_text)

    def test_channel_copy_is_always_draft_only_and_human_released(self) -> None:
        _, _, pack = compile_pack()
        for draft in (pack.primary_copy, pack.secondary_copy):
            self.assertEqual(draft.truth_status, TruthStatus.DRAFT_ONLY)
            self.assertTrue(draft.human_release_required)
            self.assertFalse(draft.automated_publish_allowed)

    def test_schedule_has_seven_contiguous_manual_days(self) -> None:
        _, _, pack = compile_pack()
        self.assertEqual([item.day for item in pack.seven_day_schedule], list(range(1, 8)))
        self.assertTrue(
            all(
                item.release_mode == "human_review_then_manual_publish"
                for item in pack.seven_day_schedule
            )
        )

    def test_schedule_references_the_matching_channel_copy(self) -> None:
        _, _, pack = compile_pack()
        draft_ids = {
            pack.primary_copy.channel: pack.primary_copy.draft_id,
            pack.secondary_copy.channel: pack.secondary_copy.draft_id,
        }
        for item in pack.seven_day_schedule:
            self.assertEqual(item.source_draft_id, draft_ids[item.channel])


class ProductionPackChannelPortfolioTests(unittest.TestCase):
    def test_full_48_scenario_matrix_covers_every_channel_with_bounded_focus(self) -> None:
        scenario_count = 0
        for business_model in BusinessModel:
            for lifecycle in LifecycleStage:
                for budget in BudgetTier:
                    for risk in IndustryRisk:
                        _, strategy, pack = compile_pack(
                            business_model=business_model,
                            lifecycle=lifecycle,
                            budget=budget,
                            risk=risk,
                        )
                        scenario_count += 1
                        portfolio = pack.channel_portfolio
                        entries = portfolio["portfolio"]
                        self.assertEqual(
                            {item["channel"] for item in entries},
                            {channel.value for channel in Channel},
                        )
                        focus = [
                            item["channel"]
                            for item in entries
                            if item["activation_state"] == "focus"
                        ]
                        tests = [
                            item["channel"]
                            for item in entries
                            if item["activation_state"] == "test"
                        ]
                        self.assertEqual(
                            focus,
                            [strategy.primary_channel.value, strategy.secondary_channel.value],
                        )
                        self.assertEqual(len(tests), 2)
                        self.assertTrue(
                            all(item["external_activation_executed"] is False for item in entries)
                        )
        self.assertEqual(scenario_count, 48)

    def test_zero_budget_hard_excludes_every_paid_channel(self) -> None:
        _, _, pack = compile_pack(budget=BudgetTier.ZERO)
        paid = [item for item in pack.channel_portfolio["portfolio"] if item["paid_channel"]]
        self.assertEqual({item["channel"] for item in paid}, {"paid_search", "paid_social"})
        self.assertTrue(all(item["activation_state"] == "excluded" for item in paid))
        self.assertTrue(all(item["score"] == 0 for item in paid))

    def test_business_model_changes_the_expansion_portfolio(self) -> None:
        _, _, b2b = compile_pack(business_model=BusinessModel.B2B)
        _, _, b2c = compile_pack(business_model=BusinessModel.B2C)
        self.assertNotEqual(
            b2b.channel_portfolio["test_channels"],
            b2c.channel_portfolio["test_channels"],
        )

    def test_portfolio_digest_tampering_fails_pack_construction(self) -> None:
        _, _, pack = compile_pack()
        tampered = dict(pack.channel_portfolio)
        tampered["test_channels"] = []
        with self.assertRaisesRegex(ProductionPackError, "channel portfolio is invalid"):
            replace(pack, channel_portfolio=tampered)


class ProductionPackEvidenceTests(unittest.TestCase):
    def test_root_citation_preserves_claim_uri_and_digest(self) -> None:
        _, _, pack = compile_pack()
        self.assertEqual(pack.citation.proof_claim_id, "claim-001")
        self.assertEqual(pack.citation.evidence_uri, "project://evidence/study.json#result")
        self.assertEqual(pack.citation.evidence_sha256, SHA)

    def test_every_faq_answer_contains_proof_and_citation(self) -> None:
        _, strategy, pack = compile_pack()
        self.assertEqual(len(pack.seo_geo_faqs), 4)
        for faq in pack.seo_geo_faqs:
            self.assertIn(strategy.proof, faq.answer_draft)
            self.assertEqual(faq.citation, pack.citation)

    def test_video_evidence_card_preserves_claim_and_digest(self) -> None:
        _, _, pack = compile_pack()
        evidence_shots = [shot for shot in pack.video_brief.shot_list if shot.proof_claim_id]
        self.assertEqual(len(evidence_shots), 1)
        self.assertEqual(evidence_shots[0].proof_claim_id, pack.citation.proof_claim_id)
        self.assertEqual(evidence_shots[0].evidence_sha256, pack.citation.evidence_sha256)

    def test_unknown_strategy_claim_is_rejected(self) -> None:
        request = make_request()
        strategy = StrategyCompiler().compile(request, at=NOW)
        with self.assertRaisesRegex(ProductionPackError, "absent from the request"):
            ProductionPackCompiler().compile(
                request,
                replace(strategy, proof_claim_id="unknown-claim"),
            )

    def test_mismatched_strategy_proof_text_is_rejected(self) -> None:
        request = make_request()
        strategy = StrategyCompiler().compile(request, at=NOW)
        with self.assertRaisesRegex(ProductionPackError, "does not match"):
            ProductionPackCompiler().compile(request, replace(strategy, proof="Invented proof"))

    def test_mismatched_strategy_evidence_digest_is_rejected(self) -> None:
        request = make_request()
        strategy = StrategyCompiler().compile(request, at=NOW)
        with self.assertRaisesRegex(ProductionPackError, "does not match"):
            ProductionPackCompiler().compile(
                request,
                replace(strategy, proof_evidence_sha256="b" * 64),
            )

    def test_tampered_faq_citation_is_rejected(self) -> None:
        _, _, pack = compile_pack()
        bad = replace(pack.seo_geo_faqs[0].citation, evidence_sha256="b" * 64)
        faqs = (replace(pack.seo_geo_faqs[0], citation=bad), *pack.seo_geo_faqs[1:])
        with self.assertRaisesRegex(ProductionPackError, "every factual draft"):
            replace(pack, seo_geo_faqs=faqs)


class ProductionPackMediaTruthTests(unittest.TestCase):
    def test_video_is_a_production_brief_not_a_rendered_video(self) -> None:
        _, _, pack = compile_pack()
        self.assertEqual(pack.video_brief.truth_status, TruthStatus.PRODUCTION_BRIEF_ONLY)
        self.assertFalse(hasattr(pack.video_brief, "rendered_video_uri"))

    def test_video_delivery_spec_is_true_4k_geometry(self) -> None:
        _, _, pack = compile_pack()
        self.assertIn("4K", pack.video_brief.delivery_spec)
        self.assertIn("3840x2160", pack.video_brief.delivery_spec)

    def test_video_identity_lock_disallows_invented_product_assets(self) -> None:
        _, _, pack = compile_pack()
        joined = " ".join(pack.video_brief.identity_lock)
        self.assertIn("owner-supplied", joined)
        self.assertIn("invented UI", joined)

    def test_audio_is_a_production_brief_not_a_rendered_track(self) -> None:
        _, _, pack = compile_pack()
        self.assertEqual(pack.audio_brief.truth_status, TruthStatus.PRODUCTION_BRIEF_ONLY)
        self.assertFalse(hasattr(pack.audio_brief, "rendered_audio_uri"))

    def test_audio_mix_and_rights_are_explicit(self) -> None:
        _, _, pack = compile_pack()
        self.assertIn("48 kHz", pack.audio_brief.mix_spec)
        self.assertIn("-14 LUFS", pack.audio_brief.mix_spec)
        self.assertTrue(any("licensed" in line for line in pack.audio_brief.rights_instructions))


class ProductionPackSafetyTests(unittest.TestCase):
    def test_string_channel_cannot_bypass_enum_contract(self) -> None:
        _, _, pack = compile_pack()
        with self.assertRaisesRegex(ProductionPackError, "channel must be a Channel"):
            replace(pack.primary_copy, channel="linkedin_organic")  # type: ignore[arg-type]

    def test_string_truth_status_cannot_bypass_enum_contract(self) -> None:
        _, _, pack = compile_pack()
        with self.assertRaisesRegex(ProductionPackError, "truth_status"):
            replace(pack.video_brief, truth_status="production_brief_only")  # type: ignore[arg-type]

    def test_boolean_schedule_day_is_rejected(self) -> None:
        _, _, pack = compile_pack()
        with self.assertRaisesRegex(ProductionPackError, "schedule day"):
            replace(pack.seven_day_schedule[0], day=True)

    def test_string_budget_cannot_bypass_pack_contract(self) -> None:
        _, _, pack = compile_pack()
        with self.assertRaisesRegex(ProductionPackError, "budget must be a BudgetTier"):
            replace(pack, budget="zero")  # type: ignore[arg-type]

    def test_zero_budget_explicitly_bans_paid_spam_and_autopublish(self) -> None:
        _, _, pack = compile_pack()
        required = {"paid_placement", "media_spend", "spam", "automated_publish"}
        self.assertTrue(required.issubset(set(pack.safety_constraints)))
        self.assertFalse(pack.primary_copy.channel.paid)
        self.assertFalse(pack.secondary_copy.channel.paid)

    def test_viral_promise_in_strategy_is_rejected(self) -> None:
        request = make_request()
        strategy = StrategyCompiler().compile(request, at=NOW)
        with self.assertRaisesRegex(ProductionPackError, "unsupported effect"):
            ProductionPackCompiler().compile(
                request,
                replace(strategy, hero_hypothesis="Hypothesis: this will go viral."),
            )

    def test_revenue_promise_in_strategy_is_rejected(self) -> None:
        request = make_request()
        strategy = StrategyCompiler().compile(request, at=NOW)
        with self.assertRaisesRegex(ProductionPackError, "unsupported effect"):
            ProductionPackCompiler().compile(
                request,
                replace(strategy, call_to_action="This will drive revenue."),
            )

    def test_self_declared_4a_quality_is_rejected(self) -> None:
        request = make_request()
        strategy = StrategyCompiler().compile(request, at=NOW)
        with self.assertRaisesRegex(ProductionPackError, "unsupported effect"):
            ProductionPackCompiler().compile(
                request,
                replace(strategy, hero_hypothesis="Hypothesis: a 4A-grade campaign."),
            )

    def test_unsafe_brand_voice_cannot_enter_audio_brief(self) -> None:
        request = make_request()
        request = replace(
            request,
            brand=replace(request.brand, voice_principles=("best-in-class",)),
        )
        strategy = StrategyCompiler().compile(request, at=NOW)
        with self.assertRaisesRegex(ProductionPackError, "unsupported effect"):
            ProductionPackCompiler().compile(request, strategy)

    def test_zero_budget_cannot_be_paired_with_paid_strategy(self) -> None:
        request = make_request()
        strategy = StrategyCompiler().compile(request, at=NOW)
        with self.assertRaisesRegex(ProductionPackError, "zero-budget strategy"):
            ProductionPackCompiler().compile(
                request,
                replace(strategy, primary_channel=Channel.PAID_SEARCH),
            )

    def test_regulated_pack_retains_named_specialist_gate(self) -> None:
        _, _, pack = compile_pack(risk=IndustryRisk.HIGH_REGULATION)
        self.assertTrue(pack.manual_release.specialist_gate_required)
        self.assertEqual(
            pack.manual_release.specialist_approvers,
            ("licensed-reviewer-001",),
        )
        self.assertTrue(any("specialist" in line for line in pack.manual_release.ordered_checks))

    def test_regulated_request_without_specialist_is_rejected_at_pack_boundary(self) -> None:
        approved_request = make_request(risk=IndustryRisk.HIGH_REGULATION)
        strategy = StrategyCompiler().compile(approved_request, at=NOW)
        unreviewed_claim = replace(approved_request.claims[0], specialist_approved_by=None)
        unreviewed_request = replace(approved_request, claims=(unreviewed_claim,))
        with self.assertRaisesRegex(ProductionPackError, "specialist approval"):
            ProductionPackCompiler().compile(unreviewed_request, strategy)

    def test_manual_release_never_claims_external_publish(self) -> None:
        _, _, pack = compile_pack()
        self.assertEqual(pack.manual_release.publish_mode, "manual_only")
        self.assertFalse(pack.manual_release.external_release_performed)


class ProductionPackAnalyticsAndReceiptTests(unittest.TestCase):
    def test_tracked_url_preserves_owner_query_and_adds_utm(self) -> None:
        _, strategy, pack = compile_pack()
        self.assertIn("ref=owner", pack.analytics.tracked_landing_url)
        self.assertIn(f"utm_source={strategy.attribution.utm_source}", pack.analytics.tracked_landing_url)
        self.assertTrue(pack.analytics.tracked_landing_url.endswith("#details"))

    def test_analytics_remains_noncausal_and_has_stop_rules(self) -> None:
        _, _, pack = compile_pack()
        self.assertIn("not a causal", pack.analytics.interpretation)
        self.assertGreaterEqual(len(pack.analytics.stop_rules), 4)

    def test_digest_is_stable_for_identical_inputs(self) -> None:
        _, _, first = compile_pack()
        _, _, second = compile_pack()
        self.assertEqual(first, second)
        self.assertEqual(production_pack_digest(first), production_pack_digest(second))

    def test_evidence_change_rotates_pack_digest(self) -> None:
        _, _, first = compile_pack()
        _, _, second = compile_pack(claim=make_claim(evidence_sha256="b" * 64))
        self.assertNotEqual(first.content_sha256, second.content_sha256)
        self.assertNotEqual(first.pack_id, second.pack_id)

    def test_canonical_json_is_round_trippable_and_compact(self) -> None:
        _, _, pack = compile_pack()
        encoded = pack.canonical_json()
        self.assertEqual(json.loads(encoded)["content_sha256"], pack.content_sha256)
        self.assertTrue(encoded.startswith("{") and encoded.endswith("}"))
        self.assertEqual(encoded, canonical_json(pack.to_dict()))

    def test_tampered_digest_is_rejected(self) -> None:
        _, _, pack = compile_pack()
        with self.assertRaisesRegex(ProductionPackError, "does not match"):
            replace(pack, content_sha256="b" * 64)

    def test_artifact_payloads_include_required_bundle_members(self) -> None:
        _, _, pack = compile_pack()
        payloads = pack.artifact_payloads()
        required = {
            "channel-copy.json",
            "landing-page-draft.json",
            "lifecycle-email-draft.json",
            "channel-portfolio.json",
            "breakout-growth-loop.json",
            "text-creative-challenger-plan.json",
            "industry-gtm-profile.json",
            "creative-strategy-kernel.json",
            "editorial-quality-receipt.json",
            "multimodal-direction-receipt.json",
            "video-production-brief.json",
            "audio-production-brief.json",
            "analytics-plan.json",
        }
        self.assertTrue(required.issubset(payloads))
        self.assertTrue(all(isinstance(value, dict) for value in payloads.values()))

        landing = payloads["landing-page-draft.json"]
        email = payloads["lifecycle-email-draft.json"]
        self.assertEqual(landing["schema"], "ProofLaunchLandingPageDraftV1")
        self.assertEqual(email["schema"], "ProofLaunchLifecycleEmailDraftV1")
        self.assertEqual(landing["citation"], email["citation"])
        self.assertTrue(landing["human_release_required"])
        self.assertFalse(landing["automated_publish_allowed"])
        self.assertTrue(email["human_release_required"])
        self.assertFalse(email["automated_send_allowed"])

    def test_to_artifacts_returns_deterministic_canonical_bytes(self) -> None:
        _, _, first = compile_pack()
        _, _, second = compile_pack()
        artifacts = first.to_artifacts()
        self.assertEqual(artifacts, second.to_artifacts())
        self.assertTrue(all(isinstance(value, bytes) for value in artifacts.values()))
        for name, value in artifacts.items():
            self.assertEqual(value, (canonical_json(first.artifact_payloads()[name]) + "\n").encode())

    def test_artifact_copy_retains_citation_and_safety_constraints(self) -> None:
        _, _, pack = compile_pack()
        copy_artifact = pack.artifact_payloads()["channel-copy.json"]
        self.assertEqual(
            copy_artifact["primary"]["citation"]["evidence_sha256"],
            SHA,
        )
        self.assertIn("automated_publish", copy_artifact["safety_constraints"])

    def test_breakout_loop_is_bound_to_the_same_strategy_and_experiment(self) -> None:
        _, strategy, pack = compile_pack()
        breakout = pack.breakout_growth_loop
        self.assertEqual(breakout["strategy_id"], strategy.strategy_id)
        self.assertEqual(
            breakout["primary_experiment"]["experiment_id"],
            strategy.attribution.experiment_id,
        )
        self.assertEqual(
            breakout["source_strategy_sha256"],
            pack.source_strategy_sha256,
        )
        self.assertFalse(breakout["external_action_performed"])

    def test_text_challenger_is_evidence_bound_and_not_claimed_as_output(self) -> None:
        _, strategy, pack = compile_pack()
        challenger = pack.text_creative_challenger_plan
        self.assertEqual(challenger["strategy_id"], strategy.strategy_id)
        self.assertEqual(challenger["proof_claim_id"], strategy.proof_claim_id)
        self.assertEqual(challenger["territory_count"], 3)
        self.assertTrue(challenger["official_first_required"])
        self.assertFalse(challenger["winner_selected"])
        self.assertFalse(challenger["external_publish_executed"])


if __name__ == "__main__":
    unittest.main()
