from __future__ import annotations

import copy
import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from prooflaunch_remix.gtm_production_pack import ProductionPackCompiler
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
from prooflaunch_remix.gtm_text_challenger import CANDIDATE_SCHEMA
from prooflaunch_remix.gtm_text_challenger_runner import (
    TEXT_BLIND_HUMAN_ATTESTATION,
    TextChallengerRunError,
    aggregate_text_blind_reviews,
    build_text_blind_review_bundle,
    execute_text_challenger_plan,
    execute_text_craft_quality_loop,
    text_blind_review_digest,
    validate_text_blind_review,
    verify_text_blind_review_bundle,
    verify_text_challenger_execution,
    write_text_challenger_bundle,
)
from prooflaunch_remix.inference_gateway import GatewayResult


NOW = "2026-08-02T12:00:00Z"
PROOF = "In the frozen owner study, 82% completed the setup task."


def _pack():
    request = CampaignStrategyInput(
        org_id="org-001",
        project_id="project-001",
        campaign_id="campaign-runner",
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
    return ProductionPackCompiler().compile(request, strategy)


def _request_sha(messages) -> str:
    return hashlib.sha256(
        json.dumps(
            list(messages), ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
    ).hexdigest()


def _candidate(messages) -> str:
    user = json.loads(messages[1]["content"])
    context = user["context"]
    territory = user["territory"]["territory_id"]
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
            "cultural_tension": "Revenue operators receive polished promises while fragmented campaign evidence remains unresolved in committee review.",
            "organizing_idea": "Proof First opens with the frozen study and delays every product promise until objections are named.",
            "participation_mechanism": "Reviewers annotate whether the study resolves their objection before seeing the evidence-review offer.",
            "share_trigger": "An annotated evidence card helps another buying committee preserve both proof and limitation.",
            "proof_role": "The approved study controls the reveal sequence and earns the right to introduce ProofLaunch after scrutiny.",
            "falsifier": "Reject Proof First if leading with evidence does not produce more specific objections from reviewers.",
        },
        "voluntary_relay": {
            "cultural_tension": "Revenue operators need to compare fragmented campaign evidence without forwarding another branded sales pitch.",
            "organizing_idea": "The Relay Card makes committee review portable through one evidence question that needs no endorsement.",
            "participation_mechanism": "A recipient adapts the question, records one limiting condition, and passes the revised card to a relevant peer.",
            "share_trigger": "The card saves a peer preparation time because evidence, objection and open condition travel together.",
            "proof_role": "The approved study anchors the card while ProofLaunch remains secondary to the peer's decision utility.",
            "falsifier": "Reject the Relay Card if recipients discuss it only when the brand or evidence-review offer remains attached.",
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
    first_hook, first_body, second_hook, second_body = channel_copy[territory]
    channels = [
        {
            "channel": context["channels"][0]["channel"],
            "native_format": context["channels"][0]["native_format"],
            "hook": first_hook,
            "body": [
                context["approved_proof"],
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
                context["approved_proof"],
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
    return json.dumps(
        {
            "schema": CANDIDATE_SCHEMA,
            "territory_id": territory,
            "strategy_id": context["strategy_id"],
            "proof_claim_id": context["proof_claim_id"],
            **profiles[territory],
            "factual_claims": [context["approved_proof"]],
            "channels": channels,
        }
    )


class FakeGateway:
    def __init__(self, *, route: str = "official_tokenfactory", fail_at: int | None = None, mismatch: bool = False):
        self.route = route
        self.fail_at = fail_at
        self.mismatch = mismatch
        self.calls = []

    def complete(self, messages, **kwargs):
        self.calls.append((messages, kwargs))
        call_number = len(self.calls)
        content = "not-json" if self.fail_at == call_number else _candidate(messages)
        request_sha = "f" * 64 if self.mismatch else _request_sha(messages)
        if self.route == "official_tokenfactory":
            receipt = {
                "schema": "ProofLaunchResilientInferenceGatewayV1",
                "status": "passed",
                "route": self.route,
                "official": {"request_sha256": request_sha},
                "third_party_attempts": [],
            }
            provider = "amd_radeon_token_factory"
            model = "Qwen3.6-35B-A3B"
        else:
            receipt = {
                "schema": "ProofLaunchResilientInferenceGatewayV1",
                "status": "passed",
                "route": self.route,
                "official": {"status": "blocked"},
                "third_party_attempts": [
                    {"status": "passed", "request_sha256": request_sha}
                ],
            }
            provider = "approved_fallback"
            model = "fallback-model"
        return GatewayResult(
            provider=provider,
            model=model,
            route=self.route,
            content=content,
            response_id=f"response-{call_number}",
            finish_reason="stop",
            usage={"total_tokens": 100},
            receipt=receipt,
        )


class CraftReviewGateway:
    def __init__(self):
        self.calls = []

    def complete(self, messages, **kwargs):
        self.calls.append((messages, kwargs))
        user = json.loads(messages[1]["content"])
        contract = user["output_contract"]
        content = json.dumps(
            {
                **contract,
                "decision": "pass",
                "blocking_findings": [],
                "repair_instructions": [],
            }
        )
        request_sha = _request_sha(messages)
        return GatewayResult(
            provider="amd_radeon_token_factory",
            model="Qwen3.6-35B-A3B",
            route="official_tokenfactory",
            response_id=f"review-{len(self.calls)}",
            finish_reason="stop",
            content=content,
            usage={"total_tokens": 100},
            receipt={
                "schema": "ProofLaunchResilientInferenceGatewayV1",
                "status": "passed",
                "route": "official_tokenfactory",
                "official": {"request_sha256": request_sha},
                "third_party_attempts": [],
            },
        )


class TextCreativeChallengerRunnerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.pack = _pack()
        self.plan = self.pack.text_creative_challenger_plan
        self.channel_copy = self.pack.artifact_payloads()["channel-copy.json"]

    def test_official_execution_runs_exactly_three_calls_and_selects_no_winner(self) -> None:
        gateway = FakeGateway()
        receipt = execute_text_challenger_plan(self.plan, gateway)
        verify_text_challenger_execution(receipt)
        self.assertEqual(receipt["status"], "generated_validated_unreviewed")
        self.assertEqual(receipt["candidate_count"], 3)
        self.assertEqual(len(gateway.calls), 3)
        self.assertTrue(all(row[1]["scope"].value == "development_core" for row in gateway.calls))
        self.assertFalse(receipt["radeon_local_inference_observed"])
        self.assertFalse(receipt["winner_selected"])
        self.assertFalse(receipt["external_publish_executed"])

    def test_craft_quality_loop_runs_three_independent_reviews_per_territory(self) -> None:
        execution = execute_text_challenger_plan(self.plan, FakeGateway())
        gateway = CraftReviewGateway()
        quality = execute_text_craft_quality_loop(self.plan, execution, gateway)
        self.assertEqual(quality["territory_count"], 3)
        self.assertEqual(quality["craft_quality_call_count"], 9)
        self.assertLessEqual(
            quality["craft_quality_call_count"],
            quality["maximum_craft_quality_calls"],
        )
        self.assertTrue(quality["all_territories_advisory_pass"])
        verify_text_challenger_execution(quality["human_review_execution"])
        self.assertTrue(
            all(
                row["status"] == "advisory_pass_pending_human_review"
                and len(row["initial_reviews"]) == 3
                and row["repair"] is None
                and row["human_release_granted"] is False
                for row in quality["records"]
            )
        )
        self.assertFalse(quality["winner_selected"])
        self.assertFalse(quality["external_publish_executed"])

    def test_candidate_contract_failure_stops_remaining_calls_and_blocks_blind_review(self) -> None:
        gateway = FakeGateway(fail_at=2)
        receipt = execute_text_challenger_plan(self.plan, gateway)
        self.assertEqual(receipt["status"], "blocked_partial_or_no_generation")
        self.assertEqual(receipt["completed_call_count"], 1)
        self.assertEqual(len(gateway.calls), 2)
        self.assertEqual(receipt["failure"]["error_code"], "candidate_contract_failed")
        with self.assertRaisesRegex(TextChallengerRunError, "requires three"):
            build_text_blind_review_bundle(
                self.plan,
                receipt,
                self.channel_copy,
                randomization_secret="s" * 32,
            )

    def test_gateway_request_digest_mismatch_fails_closed(self) -> None:
        receipt = execute_text_challenger_plan(self.plan, FakeGateway(mismatch=True))
        self.assertEqual(receipt["completed_call_count"], 0)
        self.assertEqual(receipt["failure"]["error_code"], "candidate_contract_failed")

    def test_approved_fallback_remains_non_competition_and_non_radeon_evidence(self) -> None:
        receipt = execute_text_challenger_plan(
            self.plan, FakeGateway(route="third_party_fallback")
        )
        self.assertEqual(receipt["candidate_count"], 3)
        self.assertTrue(all(row["route"] == "third_party_fallback" for row in receipt["candidates"]))
        self.assertTrue(all(row["competition_core_eligible"] is False for row in receipt["candidates"]))
        self.assertFalse(receipt["radeon_local_inference_observed"])

    def test_blind_bundle_has_six_role_hidden_pairs_and_thirty_empty_human_tasks(self) -> None:
        execution = execute_text_challenger_plan(self.plan, FakeGateway())
        bundle = build_text_blind_review_bundle(
            self.plan,
            execution,
            self.channel_copy,
            randomization_secret="launch-secret-not-persisted-000001",
        )
        public = bundle["public_packet"]
        private = bundle["private_mapping"]
        verify_text_blind_review_bundle(public, private)
        self.assertEqual(public["pair_count"], 6)
        self.assertEqual(public["review_task_count"], 30)
        self.assertFalse(public["candidate_identity_exposed"])
        self.assertFalse(public["automatic_scoring_executed"])
        self.assertTrue(all(task["choice"] is None for task in public["review_tasks"]))
        serialized_public = json.dumps(public, sort_keys=True)
        for forbidden in (
            "decision_xray",
            "proof_before_promise",
            "voluntary_relay",
            "amd_radeon_token_factory",
            "Qwen3.6-35B-A3B",
            "candidate_side",
        ):
            self.assertNotIn(forbidden, serialized_public)
        self.assertNotIn("launch-secret-not-persisted", json.dumps(bundle))

    def test_public_or_private_tamper_and_wrong_baseline_fail(self) -> None:
        execution = execute_text_challenger_plan(self.plan, FakeGateway())
        bundle = build_text_blind_review_bundle(
            self.plan,
            execution,
            self.channel_copy,
            randomization_secret="z" * 32,
        )
        public = copy.deepcopy(bundle["public_packet"])
        public["pairs"][0]["left"]["hook"] = "tampered"
        with self.assertRaisesRegex(TextChallengerRunError, "public blind bundle digest"):
            verify_text_blind_review_bundle(public, bundle["private_mapping"])

        wrong_baseline = copy.deepcopy(self.channel_copy)
        wrong_baseline["primary"]["hook"] = "changed baseline"
        with self.assertRaisesRegex(TextChallengerRunError, "planned digest"):
            build_text_blind_review_bundle(
                self.plan,
                execution,
                wrong_baseline,
                randomization_secret="z" * 32,
            )

    def test_writer_emits_content_addressed_private_files_without_secret(self) -> None:
        execution = execute_text_challenger_plan(self.plan, FakeGateway())
        bundle = build_text_blind_review_bundle(
            self.plan,
            execution,
            self.channel_copy,
            randomization_secret="x" * 32,
        )
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "challenger"
            hashes = write_text_challenger_bundle(
                output,
                plan=self.plan,
                execution=execution,
                public_packet=bundle["public_packet"],
                private_mapping=bundle["private_mapping"],
            )
            self.assertEqual(len(hashes), 4)
            for name, digest in hashes.items():
                path = output / name
                self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), digest)
                self.assertEqual(path.stat().st_mode & 0o777, 0o600)
                self.assertNotIn("x" * 32, path.read_text(encoding="utf-8"))

    def _completed_reviews(self, public, private, *, all_candidate: bool = False):
        mapping = {row["pair_id"]: row for row in private["pairs"]}
        reviews = []
        territory_seen = {territory: 0 for territory in ("decision_xray", "proof_before_promise", "voluntary_relay")}
        for task in public["review_tasks"]:
            hidden = mapping[task["pair_id"]]
            territory = hidden["candidate_territory_id"]
            territory_seen[territory] += 1
            choose_candidate = all_candidate or (
                territory == "decision_xray"
                or (territory == "proof_before_promise" and territory_seen[territory] > 1)
                or (territory == "voluntary_relay" and territory_seen[territory] > 2)
            )
            candidate_side = hidden["candidate_side"]
            choice = candidate_side if choose_candidate else ("right" if candidate_side == "left" else "left")
            review = dict(task)
            review.update(
                {
                    "reviewer_pseudonym": f"human-reviewer-{task['reviewer_slot']}",
                    "human_attestation": TEXT_BLIND_HUMAN_ATTESTATION,
                    "choice": choice,
                    "reason": "The selected side is clearer, more native, and more useful before the ask.",
                    "critical_failure": False,
                    "reviewed_at": "2026-08-02T13:00:00Z",
                }
            )
            review["review_content_sha256"] = text_blind_review_digest(review)
            reviews.append(review)
        return reviews

    def test_completed_human_reviews_recommend_unique_leader_but_do_not_select_or_publish(self) -> None:
        execution = execute_text_challenger_plan(self.plan, FakeGateway())
        bundle = build_text_blind_review_bundle(
            self.plan,
            execution,
            self.channel_copy,
            randomization_secret="human-review-secret-0000000000001",
        )
        reviews = self._completed_reviews(bundle["public_packet"], bundle["private_mapping"])
        self.assertEqual(validate_text_blind_review(reviews[0], bundle["public_packet"]), ())
        aggregate = aggregate_text_blind_reviews(
            bundle["public_packet"], bundle["private_mapping"], reviews
        )
        self.assertTrue(aggregate["review_complete"])
        self.assertEqual(aggregate["reviewer_identity_count"], 5)
        self.assertEqual(aggregate["recommended_territory_id"], "decision_xray")
        self.assertTrue(aggregate["human_selection_eligible"])
        self.assertFalse(aggregate["automatic_winner_selection_enabled"])
        self.assertFalse(aggregate["winner_selected"])
        self.assertFalse(aggregate["external_publish_executed"])

    def test_tied_human_preference_produces_no_recommendation(self) -> None:
        execution = execute_text_challenger_plan(self.plan, FakeGateway())
        bundle = build_text_blind_review_bundle(
            self.plan,
            execution,
            self.channel_copy,
            randomization_secret="human-review-secret-0000000000002",
        )
        reviews = self._completed_reviews(
            bundle["public_packet"], bundle["private_mapping"], all_candidate=True
        )
        aggregate = aggregate_text_blind_reviews(
            bundle["public_packet"], bundle["private_mapping"], reviews
        )
        self.assertTrue(aggregate["review_complete"])
        self.assertIsNone(aggregate["recommended_territory_id"])
        self.assertFalse(aggregate["human_selection_eligible"])

    def test_bad_human_attestation_or_identity_drift_blocks_review_completion(self) -> None:
        execution = execute_text_challenger_plan(self.plan, FakeGateway())
        bundle = build_text_blind_review_bundle(
            self.plan,
            execution,
            self.channel_copy,
            randomization_secret="human-review-secret-0000000000003",
        )
        reviews = self._completed_reviews(bundle["public_packet"], bundle["private_mapping"])
        reviews[0]["human_attestation"] = "model filled this review"
        reviews[0]["review_content_sha256"] = text_blind_review_digest(reviews[0])
        reviews[1]["reviewer_pseudonym"] = "identity-drift"
        reviews[1]["review_content_sha256"] = text_blind_review_digest(reviews[1])
        aggregate = aggregate_text_blind_reviews(
            bundle["public_packet"], bundle["private_mapping"], reviews
        )
        self.assertFalse(aggregate["review_complete"])
        self.assertIsNone(aggregate["recommended_territory_id"])
        self.assertGreater(aggregate["failure_count"], 0)


if __name__ == "__main__":
    unittest.main()
