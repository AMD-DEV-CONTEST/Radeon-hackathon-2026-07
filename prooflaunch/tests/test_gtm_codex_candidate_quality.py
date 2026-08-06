from __future__ import annotations

import copy
import unittest

from prooflaunch_remix.gtm_codex_candidate_quality import (
    CRITIC_IDS,
    CodexCandidateQualityError,
    candidate_content_sha256,
    compile_codex_candidate_quality_audit,
    sha256_json,
    verify_codex_candidate_quality_audit,
)


def _sign(candidate: dict[str, object]) -> dict[str, object]:
    candidate.pop("content_sha256", None)
    candidate["content_sha256"] = candidate_content_sha256(candidate)
    return candidate


def valid_candidate() -> dict[str, object]:
    approved = (
        "RelayArc converts an owner-supplied handoff brief into a review-ready "
        "stakeholder map with evidence fields and a named next-decision owner."
    )
    candidate: dict[str, object] = {
        "schema": "ProofLaunchCodexDirectCampaignCandidateV1",
        "work_order_id": "codex-work-order-b2b-saas-pre-pmf-zero-001",
        "work_order_sha256": "a" * 64,
        "protocol_sha256": "b" * 64,
        "selector": {
            "industry_archetype": "b2b_saas",
            "business_model": "b2b",
            "lifecycle": "pre_pmf",
            "budget": "zero",
        },
        "fixture": {
            "brand_name": "RelayArc",
            "product_name": "RelayArc Decision Trace",
            "audience": (
                "Founder-led B2B SaaS teams whose first design-partner handoff has "
                "no named economic decision owner."
            ),
            "jtbd": (
                "Turn one ambiguous account handoff into an inspectable next decision "
                "without treating early pipeline as product-market fit."
            ),
            "offer": (
                "Bring one stalled handoff and inspect a source-bound decision map "
                "before deciding whether another working session is warranted."
            ),
            "approved_claim": approved,
            "prohibited_claims": [
                "RelayArc shortens sales cycles or increases win rate.",
                "RelayArc has validated adoption or commercial impact.",
            ],
            "voice": ["founder-to-founder", "evidence-first", "specific without bravado"],
        },
        "campaign_system": {
            "name": "The Meeting After the Yes",
            "human_tension": (
                "A champion says yes while nobody has named the proof or person that "
                "owns the next consequential decision."
            ),
            "category_enemy": (
                "Pipeline theater that upgrades friendly enthusiasm into buying intent "
                "before a decision unit exists."
            ),
            "organizing_idea": (
                "Every promising yes owes the team one explicit next-decision owner."
            ),
            "proof_spine": "The only approved product fact is: " + approved,
            "promise_hypothesis": (
                "If a founder can locate the missing owner in one handoff, the map may "
                "deserve a bounded follow-up evaluation; no outcome is asserted."
            ),
            "falsifier": (
                "Reject the route if the map turns an inferred stakeholder into a claimed "
                "buyer or produces no different next question."
            ),
            "growth_loop": (
                "Publish one useful teardown, invite a private five-field test, and turn "
                "recurring anonymous gaps into the next educational lesson."
            ),
        },
        "channel_decision": {
            "primary_surface": "linkedin",
            "secondary_surface": "google_search",
            "excluded_surfaces": ["paid_social", "automated_cold_email"],
            "reason": (
                "Pre-PMF founder attention is concentrated in peer operating notes and "
                "active diagnostic search while the zero budget excludes paid reach."
            ),
        },
        "platform_assets": [
            {
                "surface_id": "linkedin",
                "native_format": "founder field-note with a saveable five-line diagnostic",
                "audience_state": (
                    "The founder has several warm conversations but cannot name the next "
                    "decision owner."
                ),
                "hook": "A positive demo can still end one decision too early.",
                "full_copy": (
                    "A friendly user names a real problem, so the founder records strong "
                    "interest and schedules another broad demo. Pause first. Write the weekly "
                    "user, functional champion, economic consequence owner, missing evidence, "
                    "and next-decision owner. Mark each answer supplied, inferred, or unknown. "
                    "If the fifth line is blank, discovery is the next move rather than a claim "
                    "that the account is advancing."
                ),
                "cta": "Run the five-line owner test on one active account.",
                "participation": (
                    "Copy the five fields into a private note and circle the first answer "
                    "that rests on an assumption."
                ),
                "proof_and_limitation": (
                    "The owner-approved product fact remains unchanged; this internal draft "
                    "does not establish adoption or commercial performance."
                ),
                "event_name": "stalled_handoff_owner_test_completed",
                "release_state": "draft_pending_human_review",
            },
            {
                "surface_id": "google_search",
                "native_format": "direct-answer educational page for founder-intent search",
                "audience_state": (
                    "The founder is actively searching for a practical explanation of why "
                    "a design-partner conversation has not progressed."
                ),
                "hook": "A design-partner conversation needs an owner, proof gap, and next decision.",
                "full_copy": (
                    "Start with the person who feels the problem each week. Then locate the "
                    "functional champion, the owner of the economic consequence, the evidence "
                    "each role requires, and the person accountable for the next decision. "
                    "Label every field supplied, inferred, or unknown. An empty last field means "
                    "the responsible action is focused discovery, not another generic feature "
                    "tour or an unsupported upgrade from user enthusiasm to buying intent."
                ),
                "cta": "Apply the handoff test before requesting another demonstration.",
                "participation": (
                    "Write the five fields for one current account and label the first unknown "
                    "that must be resolved."
                ),
                "proof_and_limitation": (
                    "The source-bound method is an internal capability draft and does not "
                    "establish a commercial result."
                ),
                "event_name": "design_partner_handoff_test_started",
                "release_state": "draft_pending_human_review",
            },
        ],
        "email": {
            "trigger": "A founder explicitly requests the private stalled-handoff worksheet.",
            "delay": "10 minutes",
            "segment": (
                "Founder or GTM owner at a pre-PMF B2B SaaS team with one active "
                "design-partner conversation."
            ),
            "subject": "Before the next demo, name the next decision",
            "preview": "Five fields separate friendly interest from an actionable handoff.",
            "body": (
                "Take the account you are most tempted to call promising. Write the weekly "
                "user, functional champion, economic consequence owner, missing evidence, and "
                "next-decision owner. Mark each answer supplied, inferred, or unknown. If the "
                "last field is blank, ask the question that locates responsibility before "
                "sending another broad demonstration invitation."
            ),
            "cta": "Complete the five fields privately before requesting review.",
            "suppression": (
                "Do not send without an explicit worksheet request; suppress opted-out, "
                "duplicate, internal, and ineligible recipients."
            ),
            "exit": (
                "End after this message unless the recipient explicitly asks a named human "
                "to inspect one handoff."
            ),
        },
        "seo_page": {
            "query": "why design partner deals stall after a positive demo",
            "slug": "/guides/design-partner-next-decision-owner",
            "title": "Why Design-Partner Deals Stall After a Positive Demo",
            "meta": (
                "Use a five-field decision-owner test to distinguish friendly enthusiasm "
                "from an actionable B2B handoff without overstating buying intent."
            ),
            "hero": "The next demo is not the next decision.",
            "outline": [
                "The difference between user enthusiasm and buying motion",
                "The five fields every design-partner handoff needs",
                "How to label supplied facts, inference, and unknowns",
            ],
            "schema_types": ["Article", "FAQPage"],
            "internal_links": [
                "/templates/stalled-handoff-test",
                "/guides/design-partner-evidence",
            ],
            "cta": "Use the private worksheet on one current account.",
            "rejection_condition": (
                "Reject the page if it treats an inferred stakeholder as a buyer or "
                "presents pipeline as an observed result."
            ),
        },
        "geo_answer": {
            "question": "How should a pre-PMF founder move a positive design-partner conversation forward?",
            "direct_answer": (
                "Name the weekly user, functional champion, economic consequence owner, "
                "missing evidence, and owner of the next decision; label each field supplied, "
                "inferred, or unknown before proposing another meeting."
            ),
            "entity_statement": (
                "RelayArc Decision Trace is an internal capability fixture bounded to one "
                "owner-approved product fact."
            ),
            "evidence_boundary": (
                "The supplied records do not establish buyer identification, adoption, or "
                "commercial performance."
            ),
            "required_sources": [
                "The owner-approved RelayArc product-fact record and validity window",
                "The founder-supplied account handoff brief used for this review",
            ],
            "nonfit": (
                "Do not infer undisclosed stakeholders or bypass security, procurement, "
                "legal, privacy, or human review."
            ),
            "cta": "Run the five-field test and request human review only for a located gap.",
        },
        "video_script": {
            "duration_seconds": 15,
            "shots": [
                {
                    "start": 0,
                    "end": 4,
                    "visual": "A synthetic CRM note sits beside an unwanted second-demo invite.",
                    "audio": "A friendly yes is not a next decision.",
                    "caption": "INTEREST IS NOT OWNERSHIP",
                    "acceptance_test": (
                        "A muted reviewer distinguishes interest from decision ownership "
                        "within four seconds."
                    ),
                },
                {
                    "start": 4,
                    "end": 10,
                    "visual": (
                        "Five handwritten fields appear while the final next-owner field "
                        "remains visibly blank."
                    ),
                    "audio": "Name the user, champion, consequence owner, proof, and decision owner.",
                    "caption": "THE FIFTH LINE CHANGES THE QUESTION",
                    "acceptance_test": (
                        "A reviewer repeats all five fields and locates the blank owner "
                        "without narration."
                    ),
                },
                {
                    "start": 10,
                    "end": 15,
                    "visual": (
                        "The generic invite slides away and a focused discovery question "
                        "remains beside the internal-fixture disclosure."
                    ),
                    "audio": "If the owner is blank, discover before demonstrating again.",
                    "caption": "INTERNAL DRAFT — HUMAN REVIEW PENDING",
                    "acceptance_test": (
                        "A source-hidden reviewer states the next action and infers no "
                        "commercial result."
                    ),
                },
            ],
        },
        "experiment": {
            "hypothesis": (
                "A five-field diagnostic may produce more evidence-qualified review "
                "requests than a generic demonstration invitation."
            ),
            "primary_metric": "evidence-qualified review request rate",
            "numerator": "Eligible founders who complete five fields and request one named review",
            "denominator": "Eligible complete asset exposures excluding bots, duplicates, and internal traffic",
            "baseline": "A recent authorized generic demonstration-invitation route frozen before exposure",
            "minimum_sample_rule": (
                "Require at least 100 eligible exposures per route in the preregistered "
                "window before comparing the primary metric."
            ),
            "success_rule": (
                "Advance only when the frozen threshold is met and named review confirms "
                "that each request contains a real account and an unknown field."
            ),
            "kill_rule": (
                "Stop if the route creates generic curiosity, encourages sensitive data "
                "disclosure, or presents an inferred buyer as fact."
            ),
            "causal_claim_allowed": False,
        },
        "release_state": "pending_human_review",
        "release_eligible": False,
        "human_review_completed": False,
        "preference_observed": False,
        "external_publish_executed": False,
        "automatic_publish_enabled": False,
        "automatic_send_enabled": False,
        "automatic_spend_enabled": False,
        "paid_media_spend_usd": 0,
        "production_effect_observed": False,
        "causal_effect_claim_allowed": False,
        "causal_revenue_effect_proven": False,
        "four_a_claim_eligible": False,
        "top1_claim_eligible": False,
        "truth_boundary": (
            "Internal clean-room capability fixture pending named human review. It does not "
            "prove publication readiness, preference, market effect, commercial performance, "
            "causal lift, or product superiority."
        ),
    }
    return _sign(candidate)


class CodexCandidateQualityTests(unittest.TestCase):
    def test_valid_candidate_passes_and_receipt_is_candidate_bound(self) -> None:
        candidate = valid_candidate()
        receipt = compile_codex_candidate_quality_audit(candidate)
        self.assertTrue(receipt["passed"])
        self.assertEqual(receipt["level_1"]["critical_failure_count"], 0)
        self.assertEqual(receipt["candidate_sha256"], candidate["content_sha256"])
        self.assertEqual(
            verify_codex_candidate_quality_audit(receipt, candidate=candidate),
            receipt,
        )

    def test_single_character_x_surface_and_explicit_nonproof_markers_are_valid(self) -> None:
        candidate = valid_candidate()
        candidate["channel_decision"]["primary_surface"] = "x"
        candidate["platform_assets"][0]["surface_id"] = "x"
        candidate["truth_boundary"] = (
            "Clean-room candidate not authorized for release and not publishable. "
            "It contains no verified effect, preference, revenue, or superiority evidence."
        )
        _sign(candidate)
        receipt = compile_codex_candidate_quality_audit(candidate)
        self.assertTrue(receipt["passed"], receipt["located_failures"])

    def test_eval_plan_predeclares_all_required_coverage_and_critic_boundaries(self) -> None:
        plan = compile_codex_candidate_quality_audit(valid_candidate())["eval_plan"]
        self.assertEqual(plan["dataset"]["smoke_case_count"], 24)
        self.assertEqual(plan["dataset"]["heldout_case_count"], 60)
        self.assertEqual(plan["dataset"]["regulated_case_count"], 72)
        self.assertEqual(plan["dataset"]["mechanical_case_count"], 456)
        critics = plan["level_2_model_critics"]
        self.assertEqual(tuple(critics["critic_ids"]), CRITIC_IDS)
        self.assertEqual(critics["human_labelled_cases_per_critic"], 100)
        self.assertEqual(critics["minimum_tpr_exclusive"], 0.8)
        self.assertEqual(critics["minimum_tnr_exclusive"], 0.8)
        self.assertEqual(critics["minimum_tpr_wilson_lower_95_exclusive"], 0.7)
        self.assertEqual(critics["minimum_tnr_wilson_lower_95_exclusive"], 0.7)
        self.assertFalse(critics["counts_in_preference_denominator"])
        self.assertFalse(critics["may_promote_or_release"])
        human = plan["level_3_human_development_gate"]
        self.assertEqual(human["heldout_case_count"], 12)
        self.assertEqual(human["independent_humans_per_case"], 5)

    def test_ten_single_fault_mutations_fail_at_the_located_gate(self) -> None:
        mutations = {
            "approved_claim_exact_binding": lambda row: row["campaign_system"].__setitem__(
                "proof_spine",
                "A deliberately long replacement proof sentence contains no approved product fact.",
            ),
            "channel_surface_binding": lambda row: row["platform_assets"][1].__setitem__(
                "surface_id", "youtube"
            ),
            "cross_asset_diversity": lambda row: [
                row["platform_assets"][1].__setitem__(key, row["platform_assets"][0][key])
                for key in ("hook", "full_copy", "cta", "participation", "proof_and_limitation")
            ],
            "forbidden_effect_claims": lambda row: row["platform_assets"][0].__setitem__(
                "hook", "This guaranteed viral route delivers revenue growth and Top 1 status."
            ),
            "release_state_pending": lambda row: row["platform_assets"][0].__setitem__(
                "release_state", "approved"
            ),
            "video_timeline_contract": lambda row: row["video_script"]["shots"][1].__setitem__(
                "start", 5
            ),
            "seo_contract": lambda row: row["seo_page"].__setitem__("slug", "/Guides/Bad Slug"),
            "geo_contract": lambda row: row["geo_answer"].__setitem__("required_sources", []),
            "experiment_contract": lambda row: row["experiment"].__setitem__(
                "minimum_sample_rule", "A named analyst may choose a floor later."
            ),
            "authority_effect_boundary": lambda row: row.__setitem__(
                "external_publish_executed", True
            ),
        }
        for expected_gate, mutate in mutations.items():
            with self.subTest(expected_gate=expected_gate):
                candidate = valid_candidate()
                mutate(candidate)
                _sign(candidate)
                receipt = compile_codex_candidate_quality_audit(candidate)
                observed = {
                    item["gate_id"] for item in receipt["level_1"]["located_failures"]
                }
                self.assertFalse(receipt["passed"])
                self.assertIn(expected_gate, observed)
                self.assertFalse(receipt["release_eligible"])
                self.assertFalse(receipt["external_publish_executed"])
                self.assertFalse(receipt["production_effect_observed"])

    def test_candidate_digest_tamper_is_located_and_fails_closed(self) -> None:
        candidate = valid_candidate()
        candidate["email"]["body"] += " Changed after signing."
        receipt = compile_codex_candidate_quality_audit(candidate)
        self.assertFalse(receipt["passed"])
        self.assertIn(
            "candidate_digest",
            {item["gate_id"] for item in receipt["level_1"]["located_failures"]},
        )

    def test_receipt_tamper_and_resealed_authority_leak_are_rejected(self) -> None:
        candidate = valid_candidate()
        receipt = compile_codex_candidate_quality_audit(candidate)
        tampered = copy.deepcopy(receipt)
        tampered["release_eligible"] = True
        with self.assertRaisesRegex(CodexCandidateQualityError, "digest"):
            verify_codex_candidate_quality_audit(tampered)

        tampered = copy.deepcopy(receipt)
        tampered["release_eligible"] = True
        unsigned = dict(tampered)
        unsigned.pop("content_sha256")
        tampered["content_sha256"] = sha256_json(unsigned)
        with self.assertRaisesRegex(CodexCandidateQualityError, "authority"):
            verify_codex_candidate_quality_audit(tampered)

    def test_passing_receipt_never_grants_preference_release_or_effect_authority(self) -> None:
        receipt = compile_codex_candidate_quality_audit(valid_candidate())
        self.assertEqual(receipt["release_state"], "pending_human_review")
        for field in (
            "release_eligible",
            "human_preference_observed",
            "model_critic_vote_counted_in_preference",
            "model_critic_promotion_authority",
            "automatic_publish_enabled",
            "automatic_send_enabled",
            "automatic_spend_enabled",
            "external_publish_executed",
            "production_effect_observed",
            "causal_effect_claim_allowed",
            "causal_revenue_effect_proven",
            "four_a_quality_proven",
            "top1_claim_eligible",
        ):
            self.assertFalse(receipt[field], field)
        self.assertEqual(receipt["external_action_count"], 0)


if __name__ == "__main__":
    unittest.main()
