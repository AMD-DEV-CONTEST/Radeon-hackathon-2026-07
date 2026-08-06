from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/run_local_gemma3_text_craft_quality.py"
SPEC = importlib.util.spec_from_file_location("local_gemma3_text_craft_quality", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class LocalGemma3TextCraftQualityRunnerTests(unittest.TestCase):
    def test_extracts_first_complete_json_without_semantic_repair(self) -> None:
        parsed, normalized = MODULE.extract_first_json_object(
            'prefix {"decision":"pass","items":[]} trailing'
        )
        self.assertEqual(parsed, {"decision": "pass", "items": []})
        self.assertEqual(normalized, '{"decision":"pass","items":[]}')

    def test_incomplete_json_is_left_for_fail_closed_validator(self) -> None:
        parsed, normalized = MODULE.extract_first_json_object('{"decision":"pass"')
        self.assertIsNone(parsed)
        self.assertEqual(normalized, '{"decision":"pass"')

    def test_non_object_json_is_not_admitted(self) -> None:
        parsed, normalized = MODULE.extract_first_json_object('["pass"]')
        self.assertIsNone(parsed)
        self.assertEqual(normalized, '["pass"]')

    def test_review_wrapper_preserves_source_and_closes_top_level_shape(self) -> None:
        source = [
            {"role": "system", "content": "review"},
            {"role": "user", "content": "source-contract"},
        ]
        effective = MODULE.effective_messages_for_purpose(
            source, "independent_gtm_craft_advisory_review"
        )
        self.assertEqual(source[-1]["content"], "source-contract")
        self.assertIn("every acceptance criterion", effective[-1]["content"])
        self.assertIn("preserve your decision and wording", effective[-1]["content"])

    def test_repair_prompt_uses_only_an_immutable_binding_wrapper(self) -> None:
        source = [{"role": "user", "content": "repair"}]
        effective = MODULE.effective_messages_for_purpose(
            source, "bounded_gtm_craft_repair"
        )
        self.assertEqual(source[-1]["content"], "repair")
        self.assertIn("creative text must be your work", effective[-1]["content"])
        self.assertIn("immutable schema", effective[-1]["content"])

    def test_natural_review_adapter_preserves_revise_and_specific_wording(self) -> None:
        messages = [
            {"role": "system", "content": "review"},
            {
                "role": "user",
                "content": MODULE._canonical(
                    {
                        "work_order": {
                            "required_output_fields": ["native_fit", "community_fit"]
                        },
                        "output_contract": {
                            "schema": "ProofLaunchGTMCraftAdvisoryReviewV1",
                            "work_order_id": "review-platform",
                            "territory_id": "decision_xray",
                            "strategy_id": "strategy-1",
                            "candidate_content_sha256": "a" * 64,
                        },
                    }
                ),
            },
        ]
        adapted, applied = MODULE.adapt_natural_craft_review(
            {
                "work_order_id": "review-platform",
                "native_fit": "LinkedIn opening is generic rather than operator-specific.",
                "community_fit": "The partner-community version asks before contributing utility.",
                "decision": "revise",
                "repair_instruction": "Rewrite each opening for the named channel behavior.",
            },
            messages,
        )
        self.assertTrue(applied)
        self.assertEqual(adapted["decision"], "revise")
        self.assertEqual(len(adapted["blocking_findings"]), 2)
        self.assertEqual(
            adapted["repair_instructions"],
            ["Rewrite each opening for the named channel behavior."],
        )

    def test_natural_review_adapter_never_fabricates_missing_repair(self) -> None:
        messages = [
            {"role": "system", "content": "review"},
            {
                "role": "user",
                "content": MODULE._canonical(
                    {
                        "work_order": {"required_output_fields": ["native_fit"]},
                        "output_contract": {"schema": "x"},
                    }
                ),
            },
        ]
        adapted, applied = MODULE.adapt_natural_craft_review(
            {"native_fit": "fails", "decision": "revise", "repair_instruction": ""},
            messages,
        )
        self.assertIsNone(adapted)
        self.assertFalse(applied)

    def test_block_accepts_empty_control_repair_but_preserves_assessment(self) -> None:
        messages = [
            {"role": "system", "content": "review"},
            {
                "role": "user",
                "content": MODULE._canonical(
                    {
                        "work_order": {
                            "required_output_fields": [
                                "decision",
                                "rights_boundary",
                                "repair_instruction",
                            ]
                        },
                        "output_contract": {
                            "schema": "ProofLaunchGTMCraftAdvisoryReviewV1",
                            "work_order_id": "review-rights",
                            "territory_id": "decision_xray",
                            "strategy_id": "strategy-1",
                            "candidate_content_sha256": "b" * 64,
                        },
                    }
                ),
            },
        ]
        adapted, applied = MODULE.adapt_natural_craft_review(
            {
                "decision": "block",
                "rights_boundary": "The source permission is not established.",
                "repair_instruction": "",
            },
            messages,
        )
        self.assertTrue(applied)
        self.assertEqual(adapted["decision"], "block")
        self.assertEqual(len(adapted["blocking_findings"]), 1)
        self.assertEqual(adapted["repair_instructions"], [])

    def test_repair_adapter_clamps_bindings_but_keeps_generated_creative(self) -> None:
        source_candidate = {
            "schema": MODULE.CANDIDATE_SCHEMA,
            "territory_id": "decision_xray",
            "strategy_id": "strategy-1",
            "proof_claim_id": "claim-1",
            "factual_claims": ["approved proof"],
            "cultural_tension": "source tension",
            "organizing_idea": "source idea",
            "participation_mechanism": "source mechanism",
            "share_trigger": "source trigger",
            "proof_role": "source proof role",
            "falsifier": "source falsifier",
            "channels": [
                {
                    "channel": "linkedin_organic",
                    "native_format": "text post",
                    "hook": "old",
                    "body": ["old", "approved proof"],
                    "cta": "Review the evidence.",
                    "disclosure": "draft_pending_human_review",
                },
                {
                    "channel": "partner_communities",
                    "native_format": "partner discussion",
                    "hook": "old two",
                    "body": ["old two", "approved proof"],
                    "cta": "Review the evidence.",
                    "disclosure": "draft_pending_human_review",
                },
            ],
        }
        messages = [
            {"role": "system", "content": "repair"},
            {
                "role": "user",
                "content": MODULE._canonical({"candidate": source_candidate}),
            },
        ]
        generated = {
            "schema": "wrong",
            "territory_id": "wrong",
            "strategy_id": "wrong",
            "proof_claim_id": "wrong",
            "cultural_tension": "new tension",
            "organizing_idea": "new idea",
            "participation_mechanism": "new mechanism",
            "share_trigger": "new trigger",
            "proof_role": "new proof role",
            "falsifier": "new falsifier",
            "factual_claims": ["invented"],
            "channels": [
                {
                    "channel": "wrong",
                    "native_format": "wrong",
                    "hook": "new hook",
                    "body": ["new body", "approved proof"],
                    "cta": "wrong",
                    "disclosure": "wrong",
                },
                {
                    "channel": "wrong",
                    "native_format": "wrong",
                    "hook": "new hook two",
                    "body": ["new body two", "approved proof"],
                    "cta": "wrong",
                    "disclosure": "wrong",
                },
            ],
        }
        adapted, applied, removed, clamped, markers = (
            MODULE.adapt_bounded_craft_repair(generated, messages)
        )
        self.assertTrue(applied)
        self.assertEqual(removed, 0)
        self.assertEqual(clamped, 6)
        self.assertEqual(markers, [])
        self.assertEqual(adapted["territory_id"], "decision_xray")
        self.assertEqual(adapted["factual_claims"], ["approved proof"])
        self.assertEqual(adapted["organizing_idea"], "source idea")
        self.assertEqual(adapted["channels"][0]["hook"], "new hook")
        self.assertEqual(adapted["channels"][0]["cta"], "Review the evidence.")

    def test_repair_adapter_trims_only_later_exact_nonproof_duplicate(self) -> None:
        source = {
            "schema": MODULE.CANDIDATE_SCHEMA,
            "territory_id": "decision_xray",
            "strategy_id": "strategy-1",
            "proof_claim_id": "claim-1",
            "factual_claims": ["approved proof"],
            "cultural_tension": "source tension",
            "organizing_idea": "source idea",
            "participation_mechanism": "source mechanism",
            "share_trigger": "source trigger",
            "proof_role": "source proof role",
            "falsifier": "source falsifier",
            "channels": [
                {
                    "channel": "linkedin_organic",
                    "native_format": "text post",
                    "cta": "Review the evidence.",
                    "disclosure": "draft_pending_human_review",
                },
                {
                    "channel": "partner_communities",
                    "native_format": "partner discussion",
                    "cta": "Review the evidence.",
                    "disclosure": "draft_pending_human_review",
                },
            ],
        }
        messages = [
            {"role": "system", "content": "repair"},
            {"role": "user", "content": MODULE._canonical({"candidate": source})},
        ]
        common = "This exact non-proof block appears in both channel drafts."
        generated = {
            "cultural_tension": "tension",
            "organizing_idea": "idea",
            "participation_mechanism": "mechanism",
            "share_trigger": "trigger",
            "proof_role": "proof role",
            "falsifier": "falsifier",
            "channels": [
                {
                    "hook": "first hook",
                    "body": [common, "first unique block", "approved proof"],
                },
                {
                    "hook": "second hook",
                    "body": [common, "second unique block", "approved proof"],
                },
            ],
        }
        adapted, applied, removed, clamped, markers = (
            MODULE.adapt_bounded_craft_repair(generated, messages)
        )
        self.assertTrue(applied)
        self.assertEqual(removed, 1)
        self.assertEqual(clamped, 6)
        self.assertEqual(markers, [])
        self.assertIn(common, adapted["channels"][0]["body"])
        self.assertNotIn(common, adapted["channels"][1]["body"])
        self.assertEqual(len(adapted["channels"][1]["body"]), 2)

    def test_repair_adapter_injects_only_allowed_missing_native_marker(self) -> None:
        source = {
            "schema": MODULE.CANDIDATE_SCHEMA,
            "territory_id": "decision_xray",
            "strategy_id": "strategy-1",
            "proof_claim_id": "claim-1",
            "factual_claims": ["approved proof"],
            "cultural_tension": "source tension",
            "organizing_idea": "source idea",
            "participation_mechanism": "source mechanism",
            "share_trigger": "source trigger",
            "proof_role": "source proof role",
            "falsifier": "source falsifier",
            "channels": [
                {
                    "channel": "linkedin_organic",
                    "native_format": "LinkedIn text post",
                    "cta": "Review the evidence.",
                    "disclosure": "draft_pending_human_review",
                },
                {
                    "channel": "partner_communities",
                    "native_format": "partner discussion",
                    "cta": "Review the evidence.",
                    "disclosure": "draft_pending_human_review",
                },
            ],
        }
        messages = [
            {"role": "system", "content": "repair"},
            {
                "role": "user",
                "content": MODULE._canonical(
                    {
                        "candidate": source,
                        "context": {
                            "channels": [
                                {"required_native_markers": ["linkedin", "text post"]},
                                {"required_native_markers": ["partner discussion"]},
                            ]
                        },
                    }
                ),
            },
        ]
        generated = {
            "cultural_tension": "generated tension",
            "organizing_idea": "generated idea",
            "participation_mechanism": "generated mechanism",
            "share_trigger": "generated trigger",
            "proof_role": "generated proof role",
            "falsifier": "generated falsifier",
            "channels": [
                {
                    "hook": "A decision question without a platform label",
                    "body": ["A sufficiently long unique body block.", "approved proof"],
                },
                {
                    "hook": "A partner discussion starts with one disputed condition",
                    "body": ["Another sufficiently long unique body block.", "approved proof"],
                },
            ],
        }
        adapted, applied, removed, clamped, markers = (
            MODULE.adapt_bounded_craft_repair(generated, messages)
        )
        self.assertTrue(applied)
        self.assertEqual(removed, 0)
        self.assertEqual(clamped, 6)
        self.assertEqual(markers, ["linkedin"])
        self.assertTrue(adapted["channels"][0]["hook"].startswith("Linkedin — "))
        self.assertEqual(
            adapted["channels"][1]["hook"],
            generated["channels"][1]["hook"],
        )


if __name__ == "__main__":
    unittest.main()
