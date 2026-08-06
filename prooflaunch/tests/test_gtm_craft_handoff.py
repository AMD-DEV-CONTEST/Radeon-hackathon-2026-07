from __future__ import annotations

import copy
import unittest
from dataclasses import replace

from prooflaunch_remix.gtm_craft_handoff import (
    GTMCraftHandoffError,
    compile_gtm_craft_handoff_plan,
    verify_gtm_craft_handoff_plan,
)
from prooflaunch_remix.gtm_creative_alpha import compile_creative_alpha_plan
from prooflaunch_remix.gtm_strategy import (
    BusinessModel,
    ProductSurface,
    StrategyCompiler,
)
from scripts.compile_gtm_market_language_matrix import _template


NOW = "2026-08-03T12:00:00Z"


def _compile(request, *, channel: str, secondary: str):
    strategy = StrategyCompiler().compile(request, at=NOW)
    alpha = compile_creative_alpha_plan(request, strategy)
    territory = {
        "territory_id": "decision_xray",
        "variant_id": "decision_xray:test",
        "assigned_style": alpha["style_portfolio"][0],
    }
    channels = [
        {"channel": channel, "native_format": f"{channel}-native"},
        {"channel": secondary, "native_format": f"{secondary}-native"},
    ]
    return compile_gtm_craft_handoff_plan(
        request,
        strategy,
        territory=territory,
        channels=channels,
        creative_alpha_plan=alpha,
    ), alpha


class GTMCraftHandoffTests(unittest.TestCase):
    def test_b2b_linkedin_assigns_real_specialists_and_independent_review(self) -> None:
        request = replace(
            _template(),
            product_category="software_ai_data",
            product_surface=ProductSurface.WEB_AGENT,
            audience_role="internal_champion",
            distribution_platform="linkedin",
        )
        plan, alpha = _compile(
            request,
            channel="linkedin_organic",
            secondary="partner_communities",
        )
        verify_gtm_craft_handoff_plan(
            plan, team_contract=alpha["gtm_team_capability_contract"]
        )
        self.assertEqual(plan["work_order_count"], 9)
        self.assertEqual(plan["harness"]["maximum_revision_rounds"], 1)
        self.assertEqual(plan["harness"]["automatic_external_action_count"], 0)
        producers = {
            row["role_id"] for row in plan["work_orders"] if row["stage"] == "produce"
        }
        reviewers = {
            row["role_id"] for row in plan["work_orders"] if row["stage"] == "review"
        }
        self.assertIn("senior_social_copywriter", producers)
        self.assertFalse(producers & reviewers)
        self.assertEqual(
            plan["model_execution_contract"]["maximum_total_model_calls_per_territory"],
            8,
        )
        for row in plan["work_orders"]:
            self.assertEqual(len(row["required_professional_axis_ids"]), 10)
            self.assertEqual(len(row["surface_specialist_lens_ids"]), 4)
            self.assertEqual(row["surface_id"], "linkedin")
            self.assertFalse(row["hidden_algorithm_or_ranking_inference_allowed"])
            self.assertEqual(
                row["unconventional_edge_play"]["edge_play_card_id"],
                "edge:linkedin:b2b",
            )
            self.assertFalse(
                row["unconventional_edge_play"]["external_activation_allowed"]
            )

    def test_b2c_tiktok_changes_producer_and_keeps_human_release(self) -> None:
        template = _template()
        request = replace(
            template,
            audience=replace(template.audience, business_model=BusinessModel.B2C),
            product_category="productivity_tools",
            product_surface=ProductSurface.MOBILE_APP,
            audience_role="new_user",
            distribution_platform="tiktok",
        )
        plan, _ = _compile(
            request,
            channel="short_video_organic",
            secondary="creator_community",
        )
        producers = [
            row for row in plan["work_orders"] if row["stage"] == "produce"
        ]
        self.assertEqual(producers[0]["role_id"], "short_video_director")
        self.assertIn("first_frame_direction", producers[0]["selected_atomic_skill_ids"])
        self.assertEqual(producers[0]["surface_id"], "tiktok")
        self.assertIn(
            "tiktok:senior_native_copy_editor",
            producers[0]["surface_specialist_lens_ids"],
        )
        self.assertEqual(
            producers[0]["unconventional_edge_play"]["pattern_name"],
            "choose_your_own_proof",
        )
        self.assertTrue(plan["harness"]["named_human_release_required"])
        self.assertFalse(plan["harness"]["automatic_publish_send_or_spend"])

    def test_tamper_or_unbounded_repair_fails_closed(self) -> None:
        request = replace(_template(), distribution_platform="linkedin")
        plan, alpha = _compile(
            request,
            channel="linkedin_organic",
            secondary="partner_communities",
        )
        tampered = copy.deepcopy(plan)
        tampered["harness"]["maximum_revision_rounds"] = 3
        with self.assertRaisesRegex(GTMCraftHandoffError, "digest"):
            verify_gtm_craft_handoff_plan(
                tampered, team_contract=alpha["gtm_team_capability_contract"]
            )

    def test_unspecified_platform_stays_internal_until_owner_selects_surface(self) -> None:
        request = replace(
            _template(), distribution_platform="owner_platform_unspecified"
        )
        plan, _ = _compile(
            request,
            channel="community_listening",
            secondary="owned_social",
        )
        self.assertTrue(
            plan["harness"][
                "platform_selection_required_before_named_human_release"
            ]
        )
        for row in plan["work_orders"]:
            self.assertEqual(row["surface_id"], "owner_platform_unspecified")
            self.assertTrue(row["platform_selection_required_before_release"])
