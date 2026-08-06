from __future__ import annotations

import json
import unittest
from pathlib import Path

from prooflaunch_remix.gtm_frontier_cloud_agent import (
    FrontierGTMAgentError,
    _activate_capability_context,
    _runtime_capability_context,
    _validate_audit,
    execute_frontier_gtm_agent,
    normalize_frontier_brief,
)
from prooflaunch_remix.inference_gateway import GatewayResult


ROOT = Path(__file__).resolve().parents[1]


def brief() -> dict[str, str]:
    return {
        "brief_id": "fixture-b2b", "business_model": "b2b", "industry": "industrial software",
        "category": "reliability intelligence", "lifecycle": "launch", "product_surface": "web agent",
        "audience": "plant reliability leaders", "audience_problem": "unexplained downtime sequences",
        "audience_outcome": "make a bounded pilot decision", "product_truth": "Compiles one fault sequence into a review-ready replay.",
        "brand_voice": "forensic, direct and useful", "budget": "zero", "market": "North America",
        "primary_goal": "qualified design-partner reviews",
        "recent_organic_signal_context": "Three dated, rights-clear operator posts show demand for fault-sequence reconstruction.",
        "signal_provenance": "Owner-supplied public source register dated within the last 90 days.",
    }


class FakeFrontierClient:
    def __init__(self, responses: list[dict[str, object]], *, provider: str = "frontier_test") -> None:
        self.responses = iter(responses)
        self.provider = provider

    def complete(self, messages, **kwargs):
        content = json.dumps(next(self.responses))
        return GatewayResult(
            provider=self.provider, model="frontier-model", route="third_party_fallback",
            content=content, response_id="response", finish_reason="stop", usage={},
            receipt={"request_sha256": "0" * 64},
        )


class FrontierGTMAgentTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.distillation = json.loads(
            (ROOT / "evidence/v10/gtm-named-capability-distillation-v1.json").read_text(encoding="utf-8")
        )
        cls.human_kernel = json.loads(
            (ROOT / "evidence/v10/gtm-human-capability-kernel-v2.json").read_text(encoding="utf-8")
        )
        cls.signal_pack = json.loads(
            (ROOT / "evidence/v10/gtm-recent-organic-signal-pack-v2.json").read_text(encoding="utf-8")
        )

    def test_cloud_run_binds_all_130_named_products_and_never_uses_local(self) -> None:
        active_roles = next(
            row["active_role_ids"] for row in self.human_kernel["staffing_manifests"]
            if row["business_model"] == "b2b" and row["lifecycle"] == "launch"
            and row["budget"] == "zero" and row["distribution_platform"] == "linkedin"
        )
        channel = lambda surface: {
            "surface_id": surface, "native_asset": "finished draft", "why_native": "bound grammar",
            "proof_object": "source-bound replay", "qualified_metric": "qualified action",
            "release_state": "draft_for_human_review",
        }
        client = FakeFrontierClient([
            {
                "market_diagnosis": "bounded", "audience_decision": "pilot", "category_default_to_reject": "dashboard",
                "non_consensus_bet": "sequence", "zero_budget_wedge": "replay", "research_queries": [],
                "evidence_boundaries": [], "kill_conditions": [],
                "primary_distribution_surface": "linkedin", "secondary_distribution_surface": "youtube",
                "primary_search_surface": "google_search", "primary_geo_surface": "perplexity_answers",
                "surface_selection_reason": "decision makers need inspectable evidence",
            },
            {"territories": [
                {**{field: f"a-{field}" for field in __import__("prooflaunch_remix.gtm_frontier_cloud_agent", fromlist=["_TERRITORY_FIELDS"])._TERRITORY_FIELDS}, "territory_id": "a"},
                {**{field: f"b-{field}" for field in __import__("prooflaunch_remix.gtm_frontier_cloud_agent", fromlist=["_TERRITORY_FIELDS"])._TERRITORY_FIELDS}, "territory_id": "b"},
                {**{field: f"c-{field}" for field in __import__("prooflaunch_remix.gtm_frontier_cloud_agent", fromlist=["_TERRITORY_FIELDS"])._TERRITORY_FIELDS}, "territory_id": "c"},
            ]},
            {
                "selected_territory_id": "a", "selection_reason": "specific", "territory_verdicts": [],
                "blocking_defects": [], "mandatory_repairs": [], "rejected_patterns": [],
            },
            {
                "campaign_platform": "The Missing Sequence", "strategy_rationale": "bounded",
                "primary_native_text": {
                    "hook": "Compiles one fault sequence into a review-ready replay.", "body_blocks": [],
                    "first_comment": "evidence", "objection_replies": [], "participation": "review",
                    "cta": "inspect",
                },
                "image_system": {"key_visual": "sequence", "feed_4x5": {}, "story_9x16": {},
                    "editorial_16x9": {}, "overlay_copy": [], "negative_constraints": []},
                "video_system": {"15_to_30_second_script": {}, "six_shot_plan": [], "first_1500ms": "fault",
                    "voice": "forensic", "sound": "machine", "captions": [], "continuity": "sequence"},
                "search_and_geo": {"owned_search_page": {}, "answer_engine_unit": {}},
                "zero_budget_activation": {"primary": "linkedin", "secondary": "youtube",
                    "four_step_sequence": [], "relay_object": "review replay"},
                "measurement": {"frozen_baseline": {}, "primary_metric": "qualified review", "guardrails": [],
                    "seven_day_window": {}, "kill_rule": "stop"},
                "claim_inventory": [], "release_checklist": [],
                "channel_portfolio": {"primary_distribution": channel("linkedin"),
                    "secondary_distribution": channel("youtube"), "search": channel("google_search"),
                    "geo": channel("perplexity_answers")},
                "team_handoffs": [{"accountable_role_id": "market_intelligence_lead", "input": "brief",
                    "finished_work_product": "diagnosis", "receiving_role_id": "creative_strategy_director",
                    "acceptance_gate": "evidence bound"}] * 4,
                "skill_coverage_receipt": {"demonstrated_role_ids": active_roles,
                    "work_product_evidence": ["production pack"], "omitted_role_ids_with_reason": {}},
            },
            {
                "status": "pass", "direct_publishability": "ready_for_human_release_review", "blocking_defects": [],
                "claim_violations": [], "platform_mismatches": [], "generic_language": [],
                "cross_modal_breaks": [], "zero_budget_breaks": [], "exact_repair_orders": [],
                "skill_gate_failures": [], "surface_gate_failures": [], "evidence_gate_failures": [],
                "named_product_gap_summary": {"completed_named_product_pk_count": 0,
                    "mechanism_coverage_gaps": [], "effect_claim_boundary": "no superiority claim"},
            },
        ])
        result = execute_frontier_gtm_agent(
            brief(), client, named_capability_distillation=self.distillation,
            human_capability_kernel=self.human_kernel, recent_signal_pack=self.signal_pack,
        )
        self.assertEqual(result["cloud_model_call_count"], 5)
        self.assertEqual(result["local_model_call_count"], 0)
        self.assertEqual(result["named_product_stress_count"], 130)
        self.assertEqual(result["capability_category_count"], 13)
        self.assertGreaterEqual(result["activated_role_count"], 15)
        self.assertGreaterEqual(result["activated_skill_card_count"], 150)
        self.assertEqual(result["recent_signal_pack_sha256"], self.signal_pack["content_sha256"])
        self.assertIn("59 fall within 90 days", result["brief"]["recent_organic_signal_context"])
        self.assertIsNone(result["repair"])
        self.assertEqual(result["release_review_status"], "ready_for_named_human_release_review")
        self.assertFalse(result["learning_memory_mutated"])
        self.assertFalse(result["external_publish_executed"])

    def test_local_provider_is_rejected(self) -> None:
        client = FakeFrontierClient([{}], provider="ollama_local")
        with self.assertRaisesRegex(FrontierGTMAgentError, "forbids local-model fallback"):
            execute_frontier_gtm_agent(
                brief(), client, named_capability_distillation=self.distillation,
                human_capability_kernel=self.human_kernel,
            )

    def test_closed_brief_contract(self) -> None:
        payload = brief()
        payload.pop("product_truth")
        with self.assertRaises(FrontierGTMAgentError):
            normalize_frontier_brief(payload)

    def test_audit_cannot_self_report_pass_with_unresolved_defect(self) -> None:
        with self.assertRaisesRegex(FrontierGTMAgentError, "cannot pass"):
            _validate_audit({
                "status": "pass", "direct_publishability": "ready_for_human_release_review",
                "blocking_defects": ["generic hook"], "claim_violations": [],
                "platform_mismatches": [], "generic_language": [], "cross_modal_breaks": [],
                "zero_budget_breaks": [], "skill_gate_failures": [], "surface_gate_failures": [],
                "evidence_gate_failures": [], "exact_repair_orders": [],
                "named_product_gap_summary": {"completed_named_product_pk_count": 0},
            })

    def test_audit_cannot_invent_a_named_product_pk_win(self) -> None:
        with self.assertRaisesRegex(FrontierGTMAgentError, "zero completed PK"):
            _validate_audit({
                "status": "repair", "direct_publishability": "blocked", "blocking_defects": [],
                "claim_violations": [], "platform_mismatches": [], "generic_language": [],
                "cross_modal_breaks": [], "zero_budget_breaks": [], "skill_gate_failures": [],
                "surface_gate_failures": [], "evidence_gate_failures": [], "exact_repair_orders": [],
                "named_product_gap_summary": {"completed_named_product_pk_count": 1},
            })

    def test_frozen_b2b_and_b2c_briefs_activate_context_specific_teams(self) -> None:
        cases = (
            ("config/frontier-gtm-brief-b2b-frozen.json", "linkedin", "youtube", "perplexity_answers"),
            ("config/frontier-gtm-brief-b2c-frozen.json", "instagram", "tiktok", "gemini_answers"),
        )
        for relative, primary, secondary, geo in cases:
            frozen = normalize_frontier_brief(json.loads((ROOT / relative).read_text(encoding="utf-8")))
            runtime = _runtime_capability_context(self.human_kernel, frozen)
            activated = _activate_capability_context(runtime, frozen, {
                "primary_distribution_surface": primary,
                "secondary_distribution_surface": secondary,
                "primary_search_surface": "google_search",
                "primary_geo_surface": geo,
            })
            self.assertGreaterEqual(activated["active_role_count"], 15)
            self.assertEqual(
                activated["active_skill_card_count"], activated["active_role_count"] * 10
            )
            self.assertEqual(len(activated["selected_surface_playbooks"]), 4)


if __name__ == "__main__":
    unittest.main()
