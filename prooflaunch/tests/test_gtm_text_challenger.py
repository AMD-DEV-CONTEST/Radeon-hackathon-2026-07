from __future__ import annotations

import copy
import hashlib
import json
import unittest

from prooflaunch_remix.gtm_production_pack import ProductionPackCompiler
from prooflaunch_remix.gtm_genome_learning_memory import compile_genome_learning_memory
from prooflaunch_remix.gtm_named_capability_distillation import compile_named_capability_distillation
from prooflaunch_remix.gtm_strategy import (
    AudienceICP,
    BrandConstitution,
    BudgetTier,
    BusinessModel,
    CampaignStrategyInput,
    ClaimEvidence,
    EvidenceRights,
    IndustryRisk,
    LifecycleStage,
    StrategyCompiler,
)
from prooflaunch_remix.gtm_text_challenger import (
    CANDIDATE_SCHEMA,
    LEGACY_PLAN_SCHEMA,
    PLAN_SCHEMA,
    TextChallengerError,
    build_text_challenger_receipt,
    validate_text_candidate,
    verify_text_challenger_plan,
)


NOW = "2026-08-02T12:00:00Z"
PROOF = "In the frozen owner study, 82% completed the setup task."


def _pack(*, genome_learning_memory=None, named_capability_distillation=None):
    request = CampaignStrategyInput(
        org_id="org-001",
        project_id="project-001",
        campaign_id="campaign-creative-challenger",
        owner="gtm-owner-001",
        industry="enterprise software",
        lifecycle=LifecycleStage.LAUNCH,
        budget=BudgetTier.ZERO,
        industry_risk=IndustryRisk.STANDARD,
        brand=BrandConstitution(
            brand_name="ProofLaunch",
            purpose="Help teams make evidence-bound launch decisions.",
            customer_promise="A traceable next step.",
            voice_principles=("specific", "calm", "evidence-first"),
            prohibited_tactics=("spam", "fabricated testimonials"),
        ),
        audience=AudienceICP(
            audience_id="audience-001",
            name="revenue operators",
            business_model=BusinessModel.B2B,
            core_problem="campaign evidence is fragmented",
            desired_outcome="make a defensible launch decision",
            buying_context="committee review",
        ),
        objective="request a qualified pilot",
        offer="a seven-day evidence review",
        landing_url="https://example.test/proof",
        claims=(
            ClaimEvidence(
                claim_id="claim-001",
                text=PROOF,
                evidence_uri="project://evidence/study.json#result",
                evidence_sha256="a" * 64,
                rights=EvidenceRights.OWNED,
                rights_reference="owner-record-001",
                valid_from="2026-01-01T00:00:00Z",
                valid_until="2027-01-01T00:00:00Z",
                approved_by="claim-owner-001",
            ),
        ),
    )
    strategy = StrategyCompiler().compile(request, at=NOW)
    return ProductionPackCompiler().compile(
        request, strategy, genome_learning_memory=genome_learning_memory,
        named_capability_distillation=named_capability_distillation,
    )


def _candidate(plan: dict[str, object], territory_id: str) -> dict[str, object]:
    request = next(
        row for row in plan["requests"] if row["territory_id"] == territory_id  # type: ignore[index]
    )
    context = json.loads(request["messages"][1]["content"])["context"]
    profiles = {
        "decision_xray": {
            "cultural_tension": "Revenue operators face committee review while campaign evidence is fragmented across the tools they are expected to trust.",
            "organizing_idea": "Decision X-Ray makes every unresolved proof gap visible before the pilot discussion begins.",
            "participation_mechanism": "Each operator marks the one missing condition that would change the committee decision.",
            "share_trigger": "The marked decision card helps a peer prepare for committee review without endorsing ProofLaunch.",
            "proof_role": "The approved study becomes the first inspected layer of the decision map, not a closing decoration.",
            "falsifier": "Reject Decision X-Ray if reviewers cannot identify a clearer next question after inspecting the evidence map.",
        },
        "proof_before_promise": {
            "cultural_tension": "Revenue operators are offered polished promises even though campaign evidence is fragmented at the moment of committee review.",
            "organizing_idea": "Proof First opens the discussion with the frozen study and delays every product promise until objections are named.",
            "participation_mechanism": "Reviewers annotate whether the study resolves their objection before they see the seven-day evidence review offer.",
            "share_trigger": "An annotated evidence card is useful to another buying committee because it preserves both proof and limitation.",
            "proof_role": "The approved study controls the reveal sequence and earns the right to introduce ProofLaunch only after scrutiny.",
            "falsifier": "Reject Proof First if showing the evidence before the offer does not produce more specific objections from reviewers.",
        },
        "voluntary_relay": {
            "cultural_tension": "Revenue operators need a useful way to compare fragmented campaign evidence without forwarding another branded sales pitch.",
            "organizing_idea": "The Relay Card turns committee review into a portable evidence question that works without a product endorsement.",
            "participation_mechanism": "A recipient adapts the decision question, records one limiting condition, and passes the revised card to one relevant peer.",
            "share_trigger": "The card saves a peer preparation time because the evidence, objection and open condition travel together.",
            "proof_role": "The approved study anchors the reusable card while ProofLaunch remains secondary to the peer's decision utility.",
            "falsifier": "Reject the Relay Card if recipients will discuss it only when the brand or seven-day evidence review offer is attached.",
        },
    }
    channel_copy = {
        "decision_xray": (
            "Revenue operators: which missing condition would stop this evidence from surviving committee review?",
            "Comment with the unresolved condition, not a verdict; the strongest question becomes the next evidence card.",
            "Bring one fragmented campaign claim to the partner roundtable and let peers test its weakest boundary.",
            "Use the committee-review card to record the objection that a seven-day evidence review must resolve before any introduction.",
        ),
        "proof_before_promise": (
            "Before another promise enters the feed, inspect the frozen setup evidence available to revenue operators.",
            "Read the study first, then name the objection it leaves open before considering the evidence-review offer.",
            "Open the partner discussion with the evidence card face up and the ProofLaunch offer temporarily hidden.",
            "Annotate one limitation during committee review; reveal the offer only after the group agrees on the unresolved question.",
        ),
        "voluntary_relay": (
            "Would this committee decision card still deserve a save if the ProofLaunch name disappeared?",
            "Rewrite one question for a revenue operator, add its limiting condition, and relay it only to a relevant peer.",
            "Take the unbranded evidence card into a peer exchange and challenge someone to improve its decision question.",
            "Keep the study and objection together; attach the seven-day review only when a recipient asks what produced the card.",
        ),
    }
    first_hook, first_body, second_hook, second_body = channel_copy[territory_id]
    channels = [
        {
            "channel": context["channels"][0]["channel"],
            "native_format": context["channels"][0]["native_format"],
            "hook": first_hook,
            "body": [
                PROOF,
                first_body,
            ],
            "cta": context["exact_cta"],
            "disclosure": "draft_pending_human_review",
        },
        {
            "channel": context["channels"][1]["channel"],
            "native_format": context["channels"][1]["native_format"],
            "hook": second_hook,
            "body": [
                PROOF,
                second_body,
            ],
            "cta": context["exact_cta"],
            "disclosure": "draft_pending_human_review",
        },
    ]
    for channel, marker in zip(
        channels,
        (
            "LinkedIn text post execution.",
            "Partner community discussion execution.",
        ),
        strict=True,
    ):
        channel["body"][1] += f" {marker}"
    return {
        "schema": CANDIDATE_SCHEMA,
        "territory_id": territory_id,
        "strategy_id": plan["strategy_id"],
        "proof_claim_id": plan["proof_claim_id"],
        **profiles[territory_id],
        "factual_claims": [PROOF],
        "channels": channels,
    }


class TextCreativeChallengerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.plan = _pack().text_creative_challenger_plan

    def test_named_human_learning_memory_reaches_real_model_requests(self) -> None:
        baseline_brief = self.plan["generative_execution_kernel"]["brief"]
        memory = compile_genome_learning_memory([
            {
                "record_id": "approved-hook-prior-001",
                "genome_id": "c" * 64,
                "verdict": "promote",
                "business_model": baseline_brief["business_model"],
                "platform": baseline_brief["platform"],
                "category": baseline_brief["category"],
                "axis_pairs": ["hook:category_inversion"],
                "evidence_sha256": "d" * 64,
                "approved_by": "named-human-creative-owner",
                "human_approved": True,
            }
        ])
        learned_plan = _pack(genome_learning_memory=memory).text_creative_challenger_plan
        verify_text_challenger_plan(learned_plan)
        kernel = learned_plan["generative_execution_kernel"]
        self.assertEqual(kernel["generalization_contract"]["learning_memory_sha256"], memory["content_sha256"])
        self.assertEqual(kernel["creative_genome"]["applicable_learning_record_count"], 1)
        self.assertGreater(kernel["candidate_blueprints"][0]["learning_prior_score"], 0)
        for territory, request in zip(learned_plan["territories"], learned_plan["requests"], strict=True):
            prompt = json.loads(request["messages"][1]["content"])
            assigned = territory["assigned_genome_blueprint"]
            self.assertEqual(prompt["territory"]["assigned_genome_blueprint"]["genome_id"], assigned["genome_id"])
            self.assertEqual(assigned["matched_learning_record_ids"], ["approved-hook-prior-001"])

    def test_named_product_distillation_reaches_production_pack_multimodal_factory(self) -> None:
        root = __import__("pathlib").Path(__file__).resolve().parents[1]
        ledger = json.loads((root / "evidence/v10/gtm-concrete-product-effect-pk-ledger-v1.json").read_text(encoding="utf-8"))
        distillation = compile_named_capability_distillation(ledger)
        plan = _pack(named_capability_distillation=distillation).text_creative_challenger_plan
        verify_text_challenger_plan(plan)
        factory = plan["multimodal_breakout_factory"]
        self.assertEqual(factory["named_capability_distillation_sha256"], distillation["content_sha256"])
        self.assertEqual(factory["active_named_product_stress_count"], 120)
        self.assertEqual(factory["model_call_budget"], {"text": 3, "image": 3, "video": 3, "total": 9})
        self.assertEqual(
            [row["genome_id"] for row in factory["candidate_campaigns"]],
            [row["assigned_genome_blueprint"]["genome_id"] for row in plan["territories"]],
        )

    def test_plan_has_three_distinct_official_first_draft_only_territories(self) -> None:
        verify_text_challenger_plan(self.plan)
        self.assertEqual(self.plan["schema"], PLAN_SCHEMA)
        self.assertEqual(
            self.plan["creative_alpha_plan"]["schema"],
            "ProofLaunchCreativeAlphaPlanV1",
        )
        self.assertEqual(
            [item["territory_id"] for item in self.plan["territories"]],
            ["decision_xray", "proof_before_promise", "voluntary_relay"],
        )
        self.assertEqual(
            len(
                {
                    item["assigned_style"]["style_id"]
                    for item in self.plan["territories"]
                }
            ),
            3,
        )
        self.assertEqual(
            [item["assigned_style"] for item in self.plan["territories"]],
            self.plan["creative_alpha_plan"]["style_portfolio"][:3],
        )
        kernel = self.plan["generative_execution_kernel"]
        self.assertEqual(len(kernel["candidate_blueprints"]), 24)
        self.assertGreater(kernel["creative_genome"]["blueprint_design_space"], 1_000_000)
        self.assertEqual(
            [item["assigned_genome_blueprint"]["genome_id"] for item in self.plan["territories"]],
            [item["genome_id"] for item in kernel["candidate_blueprints"][:3]],
        )
        self.assertTrue(self.plan["official_first_required"])
        self.assertEqual(self.plan["maximum_model_calls"], 3)
        self.assertEqual(self.plan["maximum_craft_quality_calls"], 21)
        self.assertEqual(len(self.plan["craft_handoff_plans"]), 3)
        self.assertTrue(
            all(row["work_order_count"] == 9 for row in self.plan["craft_handoff_plans"])
        )
        self.assertEqual(self.plan["execution_policy"]["mode"], "sequential_fail_fast")
        self.assertEqual(self.plan["execution_policy"]["maximum_concurrency"], 1)
        self.assertEqual(self.plan["execution_policy"]["default_retry_rounds"], 0)
        self.assertFalse(self.plan["third_party_competition_core_eligible"])
        self.assertFalse(self.plan["winner_selected"])
        self.assertFalse(self.plan["external_publish_executed"])
        serialized_requests = json.dumps(self.plan["requests"], sort_keys=True)
        self.assertNotIn("nonblank string", serialized_requests)
        self.assertIn("do not copy this instruction", serialized_requests)
        self.assertNotIn("https://www.salesforce.com/platform/agentforce", serialized_requests)
        first_user = json.loads(self.plan["requests"][0]["messages"][1]["content"])
        self.assertEqual(
            first_user["context"]["creative_alpha"]["creative_alpha_plan_sha256"],
            self.plan["creative_alpha_plan"]["content_sha256"],
        )
        self.assertEqual(
            first_user["context"]["creative_alpha"]["assigned_genome_blueprint"]["genome_id"],
            self.plan["territories"][0]["assigned_genome_blueprint"]["genome_id"],
        )
        self.assertEqual(first_user["craft_handoff"]["work_order_count"], 9)

    def test_legacy_v1_plan_remains_read_only_compatible(self) -> None:
        legacy = copy.deepcopy(self.plan)
        legacy["schema"] = LEGACY_PLAN_SCHEMA
        legacy.pop("creative_alpha_plan")
        legacy.pop("craft_handoff_plans")
        legacy.pop("maximum_craft_quality_calls")
        for row in legacy["requests"]:
            request_payload = json.loads(row["messages"][1]["content"])
            request_payload["context"].pop("creative_alpha", None)
            request_payload["context"].pop("creative_alpha_plan_sha256", None)
            request_payload.pop("craft_handoff", None)
            row["messages"][1]["content"] = json.dumps(
                request_payload,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )
            row["request_sha256"] = hashlib.sha256(
                json.dumps(
                    row["messages"],
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode("utf-8")
            ).hexdigest()
        legacy.pop("content_sha256")
        legacy["content_sha256"] = hashlib.sha256(
            json.dumps(
                legacy,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()

        verify_text_challenger_plan(legacy)

    def test_v2_plan_fails_closed_without_creative_alpha(self) -> None:
        tampered = copy.deepcopy(self.plan)
        tampered.pop("creative_alpha_plan")
        tampered.pop("content_sha256")
        tampered["content_sha256"] = hashlib.sha256(
            json.dumps(
                tampered,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
        with self.assertRaisesRegex(TextChallengerError, "lacks a creative-alpha plan"):
            verify_text_challenger_plan(tampered)

    def test_request_message_tamper_fails_even_if_outer_digest_is_stale(self) -> None:
        tampered = copy.deepcopy(self.plan)
        tampered["requests"][0]["messages"][0]["content"] += " changed"
        with self.assertRaisesRegex(TextChallengerError, "digest"):
            verify_text_challenger_plan(tampered)

    def test_valid_candidate_is_sealed_pending_blind_review(self) -> None:
        candidate = validate_text_candidate(
            json.dumps(_candidate(self.plan, "decision_xray")),
            self.plan,
            territory_id="decision_xray",
        )
        self.assertEqual(len(candidate["candidate_content_sha256"]), 64)
        self.assertFalse(candidate["winner_selected"])
        self.assertFalse(candidate["blind_review_completed"])
        self.assertFalse(candidate["external_publish_executed"])
        self.assertTrue(candidate["creative_quality_gate"]["passed"])
        self.assertGreaterEqual(
            candidate["creative_quality_gate"]["context_anchor_count"], 2
        )

    def test_markdown_wrapper_or_extra_field_is_rejected(self) -> None:
        raw = json.dumps(_candidate(self.plan, "decision_xray"))
        with self.assertRaisesRegex(TextChallengerError, "strict JSON"):
            validate_text_candidate(f"```json\n{raw}\n```", self.plan, territory_id="decision_xray")
        extra = _candidate(self.plan, "decision_xray")
        extra["unreviewed_score"] = 100
        with self.assertRaisesRegex(TextChallengerError, "closed contract"):
            validate_text_candidate(json.dumps(extra), self.plan, territory_id="decision_xray")

    def test_new_factual_claim_numeric_hallucination_and_cta_drift_fail(self) -> None:
        claim = _candidate(self.plan, "decision_xray")
        claim["factual_claims"].append("Customers doubled revenue.")
        with self.assertRaisesRegex(TextChallengerError, "factual claim"):
            validate_text_candidate(json.dumps(claim), self.plan, territory_id="decision_xray")

        numeric = _candidate(self.plan, "decision_xray")
        numeric["channels"][0]["body"].append(
            "The campaign supposedly improved qualified decisions by 99% after launch."
        )
        with self.assertRaisesRegex(TextChallengerError, "numeric claim"):
            validate_text_candidate(json.dumps(numeric), self.plan, territory_id="decision_xray")

        cta = _candidate(self.plan, "decision_xray")
        cta["channels"][0]["cta"] = "Buy now"
        with self.assertRaisesRegex(TextChallengerError, "CTA drifted"):
            validate_text_candidate(json.dumps(cta), self.plan, territory_id="decision_xray")

    def test_cross_channel_verbatim_duplicate_fails(self) -> None:
        candidate = _candidate(self.plan, "decision_xray")
        candidate["channels"][1]["hook"] = candidate["channels"][0]["hook"]
        candidate["channels"][1]["body"] = candidate["channels"][0]["body"]
        with self.assertRaisesRegex(TextChallengerError, "duplicated"):
            validate_text_candidate(json.dumps(candidate), self.plan, territory_id="decision_xray")

    def test_placeholder_shallow_and_context_free_strategy_fail_closed(self) -> None:
        placeholder = _candidate(self.plan, "decision_xray")
        placeholder["cultural_tension"] = "nonblank string"
        with self.assertRaisesRegex(TextChallengerError, "shallow|placeholder"):
            validate_text_candidate(
                json.dumps(placeholder), self.plan, territory_id="decision_xray"
            )

        shallow = _candidate(self.plan, "decision_xray")
        shallow["organizing_idea"] = "Show proof first."
        with self.assertRaisesRegex(TextChallengerError, "too shallow"):
            validate_text_candidate(
                json.dumps(shallow), self.plan, territory_id="decision_xray"
            )

        context_free = _candidate(self.plan, "decision_xray")
        for field in (
            "cultural_tension",
            "organizing_idea",
            "participation_mechanism",
            "share_trigger",
            "proof_role",
            "falsifier",
        ):
            context_free[field] = (
                f"A sufficiently detailed but generic creative statement for {field} "
                "that avoids every supplied organization and audience phrase."
            )
        context_free["channels"][0]["hook"] = (
            "Which missing condition would change an otherwise uncertain decision today?"
        )
        context_free["channels"][0]["body"][1] = (
            "Name the unresolved limitation and compare it with a relevant peer before acting."
        )
        context_free["channels"][1]["hook"] = (
            "Bring one disputed claim into a trusted discussion and test its weakest boundary."
        )
        context_free["channels"][1]["body"][1] = (
            "Record the strongest objection on a reusable card before making any introduction."
        )
        with self.assertRaisesRegex(TextChallengerError, "context anchors"):
            validate_text_candidate(
                json.dumps(context_free), self.plan, territory_id="decision_xray"
            )

    def test_superficial_channel_difference_and_body_cta_repetition_fail(self) -> None:
        superficial = _candidate(self.plan, "decision_xray")
        superficial["channels"][1]["hook"] = (
            "Partner channel: " + superficial["channels"][0]["hook"]
        )
        superficial["channels"][1]["body"] = list(
            superficial["channels"][0]["body"]
        )
        with self.assertRaisesRegex(TextChallengerError, "reused|superficially"):
            validate_text_candidate(
                json.dumps(superficial), self.plan, territory_id="decision_xray"
            )

        repeated_cta = _candidate(self.plan, "decision_xray")
        repeated_cta["channels"][0]["body"].append(
            repeated_cta["channels"][0]["cta"]
        )
        with self.assertRaisesRegex(TextChallengerError, "CTA inside"):
            validate_text_candidate(
                json.dumps(repeated_cta), self.plan, territory_id="decision_xray"
            )

    def test_portfolio_gate_rejects_three_relabelled_territories(self) -> None:
        source = _candidate(self.plan, "decision_xray")
        results = []
        for territory_id in (
            "decision_xray",
            "proof_before_promise",
            "voluntary_relay",
        ):
            relabelled = copy.deepcopy(source)
            relabelled["territory_id"] = territory_id
            results.append(
                validate_text_candidate(
                    json.dumps(relabelled), self.plan, territory_id=territory_id
                )
            )
        with self.assertRaisesRegex(TextChallengerError, "duplicated|distinct"):
            build_text_challenger_receipt(self.plan, results)

    def test_portfolio_gate_rejects_distinct_strategies_with_reused_channel_system(self) -> None:
        results = [
            validate_text_candidate(
                json.dumps(_candidate(self.plan, territory_id)),
                self.plan,
                territory_id=territory_id,
            )
            for territory_id in ("decision_xray", "proof_before_promise", "voluntary_relay")
        ]
        source_channels = copy.deepcopy(results[0]["channels"])
        tampered = []
        for result in results:
            unsigned = copy.deepcopy(result)
            unsigned["channels"] = copy.deepcopy(source_channels)
            unsigned.pop("candidate_content_sha256")
            unsigned["candidate_content_sha256"] = __import__("hashlib").sha256(
                json.dumps(
                    unsigned,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode("utf-8")
            ).hexdigest()
            tampered.append(unsigned)
        with self.assertRaisesRegex(TextChallengerError, "channel creative system"):
            build_text_challenger_receipt(self.plan, tampered)

    def test_receipt_binds_all_three_candidates_and_rejects_tamper(self) -> None:
        results = [
            validate_text_candidate(
                json.dumps(_candidate(self.plan, territory_id)),
                self.plan,
                territory_id=territory_id,
            )
            for territory_id in ("decision_xray", "proof_before_promise", "voluntary_relay")
        ]
        receipt = build_text_challenger_receipt(self.plan, results)
        self.assertEqual(receipt["candidate_count"], 3)
        self.assertFalse(receipt["winner_selected"])
        results[0]["organizing_idea"] = "Tampered after validation"
        with self.assertRaisesRegex(TextChallengerError, "digest does not match"):
            build_text_challenger_receipt(self.plan, results)


if __name__ == "__main__":
    unittest.main()
