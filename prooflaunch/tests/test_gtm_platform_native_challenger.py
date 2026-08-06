from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]

from prooflaunch_remix.gtm_human_capability_kernel import SURFACE_PLAYBOOKS
from prooflaunch_remix.gtm_platform_native_challenger import (
    CANDIDATE_SCHEMA,
    GTMPlatformNativeChallengerError,
    adapt_platform_native_candidate,
    build_concept_anchored_draft_prompt,
    build_platform_native_concept_prompt,
    build_platform_native_challenger_plan,
    candidate_failures,
    compile_platform_native_receipt,
    extract_platform_native_concept,
    platform_native_concept_failures,
    verify_platform_native_challenger_plan,
    verify_platform_native_receipt,
)


def _briefs() -> list[dict[str, object]]:
    return json.loads(
        (ROOT / "config/platform-native-challenger-briefs-v1.json").read_text(
            encoding="utf-8"
        )
    )["briefs"]


def _parsed(plan: dict[str, object], request: dict[str, object]) -> dict[str, object]:
    claim = plan["brief"]["approved_claim"]
    surface = request["surface_id"]
    return {
        "schema": CANDIDATE_SCHEMA,
        "campaign_platform": f"The {surface} proof turn",
        "hook": f"What if the strongest {surface} claim is the one a reader can try to disprove?",
        "progression": [
            "Name the familiar promise that currently asks the audience to trust too early.",
            "Reveal the one operating decision hidden behind that polished category language.",
            "Put the approved product fact beside the unresolved condition it cannot settle.",
            "Give the audience a useful way to mark the missing proof before considering the offer.",
        ],
        "body": [
            "Most category pages polish the answer before the buyer has agreed on the real question.",
            "This route reverses that order: expose the decision, show the bounded proof, then invite one precise objection.",
            "The resulting artifact remains useful even when the product name and call to action are removed.",
        ],
        "cta": "Mark the one unresolved condition that would change your next decision.",
        "participation_mechanism": "Readers rewrite the decision question and retain the resulting proof card for their own review.",
        "proof_integration": f"The inspectable anchor is exact and bounded: {claim} It opens the review rather than closing the sale.",
        "falsifier": "Stop this route if qualified reviewers cannot name a sharper decision after using the proof card.",
    }


class GTMPlatformNativeChallengerTests(unittest.TestCase):
    @staticmethod
    def _concept() -> dict[str, str]:
        return {
            "organizing_idea": "The Missing Decision Card",
            "thesis": "A polished campaign asset can conceal the one release decision nobody actually recorded.",
            "editorial_mechanism": "Turn each hidden handoff into a labeled content beat, then leave the unresolved human judgment visibly incomplete.",
            "reader_action": "Audit one current campaign handoff and mark the first decision your team cannot reconstruct from its existing record.",
            "stop_condition": "Stop this route when qualified operators cannot identify a missing decision or change a release question after applying the audit.",
        }

    def test_plans_cover_thirteen_distinct_surfaces_for_b2b_and_b2c(self) -> None:
        for brief in _briefs():
            plan = build_platform_native_challenger_plan(
                brief, business_model=str(brief["business_model"])
            )
            verify_platform_native_challenger_plan(plan)
            self.assertEqual(plan["surface_count"], 13)
            self.assertEqual(
                [row["surface_id"] for row in plan["requests"]],
                list(SURFACE_PLAYBOOKS),
            )
            self.assertEqual(
                len({row["edge_play"]["edge_play_card_id"] for row in plan["requests"]}),
                13,
            )
            self.assertFalse(
                plan["execution_policy"]["automatic_external_publish_enabled"]
            )
            for request in plan["requests"]:
                prompt = request["prompt"]
                self.assertIn("EXACT_JSON_SHAPE=", prompt)
                self.assertIn("complete factual product whitelist", prompt)
                self.assertIn("no nested objects", prompt)

    def test_concept_first_pipeline_separates_editorial_choice_from_rendering(self) -> None:
        brief = _briefs()[0]
        plan = build_platform_native_challenger_plan(brief, business_model="b2b")
        request = plan["requests"][0]
        concept_prompt = build_platform_native_concept_prompt(
            plan=plan, request=request
        )
        self.assertIn("private concept card", concept_prompt)
        self.assertNotIn(brief["approved_claim"], concept_prompt)
        concept = self._concept()
        self.assertEqual(
            platform_native_concept_failures(
                concept, plan=plan, request=request
            ),
            (),
        )
        draft_prompt = build_concept_anchored_draft_prompt(
            plan=plan, request=request, concept=concept
        )
        self.assertIn(brief["approved_claim"], draft_prompt)
        self.assertIn("OPERATING TENSION:", draft_prompt)
        self.assertNotIn("NON_CONSENSUS_EDGE_PLAY", draft_prompt)

    def test_concept_extractor_recovers_nested_model_fields_without_writing_copy(self) -> None:
        source = self._concept()
        raw = json.dumps(
            {
                "SURFACE_ID": "linkedin",
                "FACT_WHITELIST": {"product_name": "ProofLaunch"},
                "OUTPUT_SHAPE": source,
            }
        )
        self.assertEqual(extract_platform_native_concept(raw), source)

    def test_concept_first_pipeline_rejects_generic_invented_or_metric_led_routes(self) -> None:
        brief = _briefs()[0]
        plan = build_platform_native_challenger_plan(brief, business_model="b2b")
        request = plan["requests"][0]
        concept = self._concept()
        concept.update(
            {
                "organizing_idea": "Autonomous GTM Workflow",
                "editorial_mechanism": "Show our new dashboard and decision matrix in a screen recording with two responses.",
                "stop_condition": "Stop if conversion fails to increase 20% within two weeks.",
            }
        )
        failures = platform_native_concept_failures(
            concept, plan=plan, request=request
        )
        self.assertIn("concept_organizing_idea_is_generic", failures)
        self.assertIn("concept_invents_unbound_asset_or_product_detail", failures)
        self.assertIn("concept_stop_condition_invents_threshold", failures)
        self.assertIn("concept_asserts_unsupported_outcome", failures)
        with self.assertRaises(GTMPlatformNativeChallengerError):
            build_concept_anchored_draft_prompt(
                plan=plan, request=request, concept=concept
            )

    def test_candidate_is_bound_to_surface_proof_and_human_review(self) -> None:
        brief = _briefs()[0]
        plan = build_platform_native_challenger_plan(brief, business_model="b2b")
        request = plan["requests"][0]
        candidate = adapt_platform_native_candidate(
            _parsed(plan, request), plan=plan, request=request
        )
        self.assertEqual(candidate_failures(candidate, plan=plan, request=request), ())
        self.assertEqual(
            candidate["release_state"], "draft_pending_source_hidden_human_review"
        )
        self.assertFalse(candidate["external_publish_executed"])

    def test_generic_or_unapproved_claim_fails_closed(self) -> None:
        brief = _briefs()[0]
        plan = build_platform_native_challenger_plan(brief, business_model="b2b")
        request = plan["requests"][0]
        parsed = _parsed(plan, request)
        parsed["hook"] = "Unlock the power of AI with this game changer"
        parsed["proof_integration"] = "Trust us; conversion improved 42%."
        candidate = adapt_platform_native_candidate(parsed, plan=plan, request=request)
        failures = candidate_failures(candidate, plan=plan, request=request)
        self.assertTrue(any("generic copy marker" in item for item in failures))
        self.assertTrue(any("unsupported outcome" in item for item in failures))

    def test_adapter_normalizes_structure_and_restores_only_immutable_claim(self) -> None:
        brief = _briefs()[0]
        plan = build_platform_native_challenger_plan(brief, business_model="b2b")
        request = plan["requests"][0]
        parsed = _parsed(plan, request)
        parsed["progression"] = {
            "tension": parsed["progression"][0],
            "reveal": parsed["progression"][1],
            "proof": parsed["progression"][2],
            "action": parsed["progression"][3],
        }
        parsed["body"] = "\n\n".join(parsed["body"])
        parsed["proof_integration"] = "Use the approved product fact as an opening inspection object."
        candidate = adapt_platform_native_candidate(
            parsed, plan=plan, request=request
        )
        self.assertEqual(candidate_failures(candidate, plan=plan, request=request), ())
        self.assertEqual(len(candidate["progression"]), 4)
        self.assertEqual(len(candidate["body"]), 3)
        self.assertIn(brief["approved_claim"], candidate["proof_integration"])
        self.assertFalse(
            candidate["serialization_normalization"][
                "creative_language_synthesized_by_adapter"
            ]
        )

    def test_adapter_repairs_trailing_commas_and_object_beats_without_new_copy(self) -> None:
        brief = _briefs()[0]
        plan = build_platform_native_challenger_plan(brief, business_model="b2b")
        request = plan["requests"][1]
        parsed = _parsed(plan, request)
        parsed["progression"] = [
            {"tension": parsed["progression"][0]},
            {"reveal": parsed["progression"][1]},
            {"proof": parsed["progression"][2]},
            {"action": parsed["progression"][3]},
        ]
        raw = json.dumps(parsed, ensure_ascii=False).replace("}]", "},]")
        from prooflaunch_remix.gtm_platform_native_challenger import extract_first_json_object

        candidate = adapt_platform_native_candidate(
            extract_first_json_object(raw), plan=plan, request=request
        )
        self.assertEqual(candidate_failures(candidate, plan=plan, request=request), ())
        self.assertEqual(
            candidate["serialization_normalization"]["json_syntax"],
            "trailing_commas_removed",
        )

    def test_receipt_requires_all_candidates_to_remain_unreleased(self) -> None:
        brief = _briefs()[1]
        plan = build_platform_native_challenger_plan(brief, business_model="b2c")
        attempts = {
            request["surface_id"]: [
                {
                    "raw_output": json.dumps(_parsed(plan, request)),
                    "source": "fixture",
                    "elapsed_seconds": 0,
                    "generated_token_count": 1,
                }
            ]
            for request in plan["requests"]
        }
        receipt = compile_platform_native_receipt(
            plan=plan,
            model={"provider": "fixture", "network_download_performed": False},
            attempts_by_surface=attempts,
        )
        verify_platform_native_receipt(receipt, plan=plan)
        self.assertEqual(receipt["accepted_surface_count"], 13)
        self.assertFalse(receipt["human_review_completed"])
        tampered = copy.deepcopy(receipt)
        tampered["external_publish_executed"] = True
        with self.assertRaises(GTMPlatformNativeChallengerError):
            verify_platform_native_receipt(tampered, plan=plan)

    def test_tiktok_allows_spoken_native_short_body_beats(self) -> None:
        brief = _briefs()[0]
        plan = build_platform_native_challenger_plan(brief, business_model="b2b")
        request = next(
            row for row in plan["requests"] if row["surface_id"] == "tiktok"
        )
        parsed = _parsed(plan, request)
        parsed["body"] = ["Stop guessing.", "Show the trace.", "Name the missing proof."]
        candidate = adapt_platform_native_candidate(
            parsed, plan=plan, request=request
        )
        self.assertEqual(candidate_failures(candidate, plan=plan, request=request), ())

    def test_explicit_negation_is_not_misread_as_an_outcome_claim(self) -> None:
        brief = _briefs()[0]
        plan = build_platform_native_challenger_plan(brief, business_model="b2b")
        request = next(
            row for row in plan["requests"] if row["surface_id"] == "claude_answers"
        )
        parsed = _parsed(plan, request)
        parsed["body"][0] = (
            "We are not claiming this system eliminates risk; the artifact exposes the evidence and unresolved condition for review."
        )
        candidate = adapt_platform_native_candidate(
            parsed, plan=plan, request=request
        )
        self.assertEqual(candidate_failures(candidate, plan=plan, request=request), ())

    def test_case_only_claim_variation_is_normalized_in_place(self) -> None:
        brief = _briefs()[0]
        plan = build_platform_native_challenger_plan(brief, business_model="b2b")
        request = plan["requests"][0]
        parsed = _parsed(plan, request)
        parsed["proof_integration"] = (
            "ProofLaunch Cortex-X compiles a rights-bound brief into review-ready GTM assets. It opens the inspection."
        )
        candidate = adapt_platform_native_candidate(
            parsed, plan=plan, request=request
        )
        self.assertEqual(candidate_failures(candidate, plan=plan, request=request), ())
        self.assertEqual(
            candidate["serialization_normalization"]["proof_integration"],
            "immutable_approved_claim_case_normalized_in_place",
        )
        self.assertNotIn(
            "Compiles a rights-bound brief into review-ready GTM assets. ProofLaunch",
            candidate["proof_integration"],
        )


if __name__ == "__main__":
    unittest.main()
