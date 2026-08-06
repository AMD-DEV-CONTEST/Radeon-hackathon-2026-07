from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]

from prooflaunch_remix.gtm_platform_generation_quality import (
    compile_platform_generation_trace_audit,
    compile_platform_generation_quality_audit,
    generation_quality_failures,
    verify_platform_generation_quality_audit,
    verify_platform_generation_trace_audit,
)
from prooflaunch_remix.gtm_platform_native_challenger import (
    SURFACE_GENERATION_BLUEPRINTS,
    adapt_platform_native_candidate,
    candidate_failures,
    digest,
)


class GTMPlatformGenerationQualityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        root = ROOT / "artifacts/gtm-last-mile-pk-v1/platform-native-challengers-v1"
        cls.plan = json.loads((root / "b2b-plan.json").read_text(encoding="utf-8"))
        cls.receipt = json.loads(
            (root / "b2b-publication-repaired-receipt.json").read_text(encoding="utf-8")
        )

    def test_existing_mechanical_drafts_fail_the_stricter_pre_human_gate(self) -> None:
        audit = compile_platform_generation_quality_audit(
            plan=self.plan, receipt=self.receipt
        )
        verify_platform_generation_quality_audit(audit)
        self.assertEqual(audit["surface_count"], 13)
        self.assertLess(audit["pre_human_quality_pass_count"], 13)
        self.assertEqual(audit["human_craft_review_completed_count"], 0)
        self.assertFalse(audit["production_effect_observed"])

    def test_surface_blueprint_is_required_even_when_base_contract_passes(self) -> None:
        candidate = self.receipt["accepted_candidates"][0]
        request = self.plan["requests"][0]
        failures = generation_quality_failures(
            candidate, plan=self.plan, request=request
        )
        self.assertTrue(
            any(item.startswith("missing_surface_blueprint_markers:") for item in failures)
        )

    def test_fabricated_first_person_timeline_is_blocked_before_human_review(self) -> None:
        candidate = copy.deepcopy(self.receipt["accepted_candidates"][0])
        candidate["hook"] = (
            "I recently rejected a previous campaign after it was flagged internally."
        )
        request = self.plan["requests"][0]
        failures = generation_quality_failures(
            candidate, plan=self.plan, request=request
        )
        self.assertIn("unbound_first_person_or_timeline_anecdote", failures)

    def test_explicit_synthetic_case_shows_capability_without_becoming_real_evidence(self) -> None:
        candidate = copy.deepcopy(self.receipt["accepted_candidates"][0])
        candidate.update(
            {
                "campaign_platform": "Decision Labels Before Release",
                "hook": "SYNTHETIC SCENARIO: I rejected a draft because its source boundary could not be reconstructed.",
                "progression": [
                    "Name the fictional release decision before presenting any product or category claim.",
                    "Separate the synthetic input from the approved evidence and unresolved human judgment.",
                    "Demonstrate the review mechanism without reporting a customer or market outcome.",
                    "Give the reader one audit they can apply to a real internal handoff.",
                ],
                "body": [
                    "OPERATING TENSION: The explicitly synthetic reviewer receives a polished draft with no inspectable source boundary.",
                    "DECISION RULE: Reject the synthetic draft whenever the approved evidence and editorial inference cannot be separated.",
                    "PROOF BOUNDARY: This fictional case demonstrates review logic only and reports no production result or customer response.",
                    "PRACTITIONER ACTION: Apply the same source-boundary audit to one real internal asset before considering any cohort.",
                    "FAILS WHEN: Stop the route when readers mistake the labeled synthetic decision for observed product or market evidence.",
                ],
                "cta": "Inspect the review rule, then consider the cohort only if it exposes a real internal gap.",
                "participation_mechanism": "Audit one current asset and mark the first source boundary your reviewer cannot reconstruct from the record.",
                "proof_integration": self.plan["brief"]["approved_claim"],
                "falsifier": "Stop this route when qualified readers mistake the labeled fictional decision for a production or customer outcome.",
            }
        )
        request = self.plan["requests"][0]
        failures = generation_quality_failures(
            candidate, plan=self.plan, request=request
        )
        self.assertNotIn("unbound_first_person_or_timeline_anecdote", failures)

    def test_unlabeled_synthetic_paths_are_blocked_but_labeled_paths_are_admissible(self) -> None:
        candidate = copy.deepcopy(self.receipt["accepted_candidates"][6])
        request = self.plan["requests"][6]
        candidate["body"] = [
            "DIRECT ANSWER: Path A rejects the bounded option while Path B proceeds to a named human review.",
            "DECISION CRITERIA: Both paths use the same frozen brief and differ only in the unresolved release condition.",
            "WHEN NOT TO USE: Reject either path when the evidence owner cannot reconstruct the stated decision boundary.",
            "EVIDENCE BOUNDARY: These paths demonstrate decision mechanics and do not report a customer or market result.",
            "NEXT STEP: Compare Path A with Path B and mark the evidence condition that changes the decision.",
        ]
        failures = generation_quality_failures(
            candidate, plan=self.plan, request=request
        )
        self.assertIn("synthetic_capability_scenario_disclosure_missing", failures)
        candidate["body"][0] = "DIRECT ANSWER: SYNTHETIC SCENARIO — " + candidate["body"][0].split(": ", 1)[1]
        labeled_failures = generation_quality_failures(
            candidate, plan=self.plan, request=request
        )
        self.assertNotIn(
            "synthetic_capability_scenario_disclosure_missing", labeled_failures
        )

    def test_dangling_comparison_duplicate_action_and_unshootable_video_are_blocked(self) -> None:
        candidate = copy.deepcopy(self.receipt["accepted_candidates"][1])
        request = self.plan["requests"][1]
        candidate["hook"] = "Compare the two responses presented below before choosing a route."
        candidate["cta"] = (
            "Inspect the current handoff and compare every missing decision before considering the cohort."
        )
        candidate["participation_mechanism"] = candidate["cta"]
        candidate["body"] = [
            "0:00 VISUAL: " + " ".join(["visible"] * 40),
            "0:02 VO: " + " ".join(["spoken"] * 30),
            "0:06 PROOF: " + " ".join(["bounded"] * 40),
            "0:12 ACTION: " + " ".join(["inspect"] * 30),
        ]
        failures = generation_quality_failures(
            candidate, plan=self.plan, request=request
        )
        self.assertIn("artifact_references_content_that_is_not_present", failures)
        self.assertIn(
            "cta_duplicates_participation_instead_of_advancing_the_offer", failures
        )
        self.assertIn("tiktok_beat_exceeds_shootable_runtime_budget", failures)

    def test_unsupported_effect_synonyms_do_not_escape_the_truth_gate(self) -> None:
        candidate = copy.deepcopy(self.receipt["accepted_candidates"][0])
        candidate["hook"] = (
            "This route safeguards launch quality and fosters more predictable execution."
        )
        request = self.plan["requests"][0]
        failures = generation_quality_failures(
            candidate, plan=self.plan, request=request
        )
        self.assertIn("unsupported_effect_language_outside_frozen_truth", failures)

    def test_product_reference_cannot_expand_the_claim_outside_proof_field(self) -> None:
        candidate = copy.deepcopy(self.receipt["accepted_candidates"][0])
        candidate["hook"] = (
            "The approved product fact offers a system that makes execution more predictable."
        )
        request = self.plan["requests"][0]
        failures = generation_quality_failures(
            candidate, plan=self.plan, request=request
        )
        self.assertIn("product_reference_adds_claim_outside_frozen_truth", failures)

    def test_structurally_specific_linkedin_candidate_can_pass_row_gate(self) -> None:
        request = self.plan["requests"][0]
        candidate = copy.deepcopy(self.receipt["accepted_candidates"][0])
        candidate.update(
            {
                "campaign_platform": "The Brief-to-Asset Decision Debt Ledger",
                "hook": "The most expensive GTM handoff is the decision nobody can reconstruct.",
                "progression": [
                    "Name the point where a brief stops carrying its original decision context.",
                    "Separate approved evidence from the unrecorded editorial inference introduced later.",
                    "Place the bounded product fact beside the unresolved human release decision.",
                    "Apply the same decision rule to one live internal handoff before considering the cohort.",
                ],
                "body": [
                    "OPERATING TENSION: The final asset can look polished while the production chain no longer carries the strategic assumption that justified the work.",
                    "DECISION RULE: A review-ready asset must expose its source brief, approved proof, editorial inference, named approver and release state in one trace.",
                    "Most teams inspect the final copy but cannot reconstruct which strategic assumption survived each handoff or who accepted the remaining uncertainty.",
                    "PROOF BOUNDARY: The useful distinction is not human versus AI. It is inspectable decision versus unattributed transformation across strategy, generation and review.",
                    "PRACTITIONER ACTION: Place the approved product fact beside one unresolved condition, then ask the named approver whether the evidence supports release for this audience and surface.",
                    "FAILS WHEN: A reviewer cannot recover the original intent, evidence boundary and owner decision from the artifact without interviewing the production team.",
                ],
                "cta": "Inspect one brief-to-asset trace; consider the cohort only if the missing decision becomes obvious.",
                "participation_mechanism": "Apply the five-field trace to one internal handoff and retain the missing field as the next review question.",
                "proof_integration": self.plan["brief"]["approved_claim"],
                "falsifier": "Stop this route when senior operators cannot identify a missing decision or change a review question after applying the trace.",
            }
        )
        candidate.pop("content_sha256", None)
        candidate["content_sha256"] = digest(candidate)
        self.assertEqual(
            generation_quality_failures(candidate, plan=self.plan, request=request),
            (),
        )

    def test_every_surface_has_a_distinct_executable_blueprint(self) -> None:
        self.assertEqual(len(SURFACE_GENERATION_BLUEPRINTS), 13)
        marker_sets = [
            tuple(value["body_markers"])
            for value in SURFACE_GENERATION_BLUEPRINTS.values()
        ]
        self.assertEqual(len(marker_sets), len(set(marker_sets)))

    def test_every_surface_row_gate_has_a_constructive_passing_path(self) -> None:
        requests = {row["surface_id"]: row for row in self.plan["requests"]}
        claim = self.plan["brief"]["approved_claim"]
        for surface_id, blueprint in SURFACE_GENERATION_BLUEPRINTS.items():
            affiliation = (
                "We built ProofLaunch Cortex-X; this operator note discloses that affiliation and keeps the release decision with a named reviewer."
                if surface_id == "reddit"
                else "This surface artifact names the operating decision, the evidence boundary, the unresolved condition and the human owner without claiming an observed outcome."
            )
            body = [
                f"{marker} {affiliation} The reader can apply this labeled step to one internal handoff and retain the unresolved condition for review."
                for marker in blueprint["body_markers"]
            ]
            if surface_id == "tiktok":
                body = [
                    "0:00 VISUAL: Five labeled cards sit on a desk; the release card is visibly missing.",
                    "0:02 VO: The asset exists, but one accountable decision disappeared during the handoff.",
                    "0:06 PROOF: Brief, approved fact, editorial inference and named reviewer remain visibly separate.",
                    "0:12 ACTION: Compare these cards with one current handoff and mark the missing decision.",
                ]
            parsed = {
                "campaign_platform": f"{surface_id} decision evidence route",
                "hook": f"The {surface_id} artifact earns attention by exposing one decision the production chain cannot reconstruct.",
                "progression": [
                    f"Name the {surface_id} operating tension before introducing the product or an offer.",
                    "Separate the approved product fact from the editorial inference and unresolved release condition.",
                    "Place the bounded proof beside the named human decision without reporting an unobserved result.",
                    f"Give the {surface_id} reader one self-contained action that remains useful without a click or reply.",
                ],
                "body": body,
                "cta": f"Inspect the {surface_id} evidence boundary before considering the design-partner cohort.",
                "participation_mechanism": f"Apply the {surface_id} labeled sequence to one internal brief and keep the missing decision as the next review question.",
                "proof_integration": claim,
                "falsifier": f"Stop the {surface_id} route when qualified reviewers cannot identify a missing decision or refine the release question after reading it.",
            }
            request = requests[surface_id]
            candidate = adapt_platform_native_candidate(
                parsed, plan=self.plan, request=request
            )
            self.assertEqual(
                candidate_failures(candidate, plan=self.plan, request=request),
                (),
                surface_id,
            )
            self.assertEqual(
                generation_quality_failures(
                    candidate, plan=self.plan, request=request
                ),
                (),
                surface_id,
            )

    def test_partial_local_trace_gets_truthful_thirteen_surface_progress_audit(self) -> None:
        root = ROOT / "artifacts/gtm-last-mile-pk-v1/platform-native-challengers-v2"
        plan = json.loads((root / "b2b-plan.json").read_text(encoding="utf-8"))
        trace = json.loads(
            (root / "b2b-local-gemma3-quality-v2-receipt.private-trace.json").read_text(
                encoding="utf-8"
            )
        )
        audit = compile_platform_generation_trace_audit(plan=plan, trace=trace)
        verify_platform_generation_trace_audit(audit)
        self.assertEqual(audit["surface_count"], 13)
        self.assertEqual(audit["traced_surface_count"], 13)
        self.assertEqual(audit["human_craft_review_completed_count"], 0)
        self.assertFalse(audit["production_effect_observed"])


if __name__ == "__main__":
    unittest.main()
