from __future__ import annotations

import copy
import hashlib
import json
import unittest
from dataclasses import replace
from pathlib import Path

from prooflaunch_remix.gtm_strategy import BusinessModel, LifecycleStage, ProductSurface
from prooflaunch_remix.gtm_team_capability_os import (
    GTMTeamCapabilityError,
    ROLE_REGISTRY,
    compile_gtm_team_capability_contract,
    verify_gtm_team_capability_contract,
)
from scripts.compile_gtm_market_language_matrix import _template
from scripts.compile_gtm_team_capability_matrix import compile_gtm_team_capability_matrix


ROOT = Path(__file__).resolve().parents[1]


class GTMTeamCapabilityTests(unittest.TestCase):
    def test_registry_decomposes_twenty_two_crafts_into_ten_skills_each(self) -> None:
        self.assertEqual(len(ROLE_REGISTRY), 22)
        self.assertTrue(
            all(len(item["atomic_skill_ids"]) == 10 for item in ROLE_REGISTRY.values())
        )
        self.assertEqual(
            sum(len(item["atomic_skill_ids"]) for item in ROLE_REGISTRY.values()),
            220,
        )

    def test_b2b_and_b2c_staff_different_specialists(self) -> None:
        template = _template()
        b2b = compile_gtm_team_capability_contract(
            replace(
                template,
                product_category="software_ai_data",
                product_surface=ProductSurface.WEB_AGENT,
                audience_role="internal_champion",
                distribution_platform="linkedin",
            )
        )
        b2c = compile_gtm_team_capability_contract(
            replace(
                template,
                audience=replace(template.audience, business_model=BusinessModel.B2C),
                product_category="productivity_tools",
                product_surface=ProductSurface.MOBILE_APP,
                audience_role="new_user",
                distribution_platform="tiktok",
            )
        )
        b2b_roles = {item["role_id"] for item in b2b["active_virtual_team"]["roles"]}
        b2c_roles = {item["role_id"] for item in b2c["active_virtual_team"]["roles"]}
        self.assertIn("sales_enablement_revops_lead", b2b_roles)
        self.assertNotIn("sales_enablement_revops_lead", b2c_roles)
        self.assertIn("product_led_growth_lead", b2c_roles)
        self.assertIn("short_video_director", b2c_roles)

    def test_growth_adds_lifecycle_specialist_and_targets_remain_baseline_bound(self) -> None:
        contract = compile_gtm_team_capability_contract(
            replace(_template(), lifecycle=LifecycleStage.GROWTH)
        )
        roles = {item["role_id"] for item in contract["active_virtual_team"]["roles"]}
        self.assertIn("lifecycle_crm_strategist", roles)
        organic_kr = next(
            item
            for item in contract["team_okr_contract"]["key_results"]
            if item["id"] == "kr_organic_quality"
        )
        self.assertIsNone(organic_kr["target"])
        self.assertIn("requires_28_day_baseline", organic_kr["target_status"])
        self.assertFalse(contract["team_okr_contract"]["vanity_views_are_key_results"])
        self.assertFalse(contract["team_okr_contract"]["pipeline_is_revenue"])

    def test_reference_cohorts_are_public_non_ranked_and_do_not_infer_org_charts(self) -> None:
        contract = compile_gtm_team_capability_contract(_template())
        cohort = contract["reference_cohort_contract"]
        self.assertEqual(cohort["company_count"], 10)
        self.assertFalse(cohort["selection_is_authoritative_ranking"])
        self.assertFalse(cohort["internal_org_chart_or_private_performance_inferred"])
        self.assertTrue(all(item["official_url"].startswith("https://") for item in cohort["companies"]))

    def test_tamper_and_automatic_training_fail_closed(self) -> None:
        contract = compile_gtm_team_capability_contract(_template())
        tampered = copy.deepcopy(contract)
        tampered["failure_curriculum_contract"][
            "failed_output_becomes_automatic_training_data"
        ] = True
        with self.assertRaisesRegex(GTMTeamCapabilityError, "digest"):
            verify_gtm_team_capability_contract(tampered)

    def test_sealed_staffing_matrix_covers_all_roles_and_contexts(self) -> None:
        matrix = compile_gtm_team_capability_matrix()
        coverage = matrix["coverage"]
        self.assertEqual(coverage["staffing_context_count"], 144)
        self.assertEqual(coverage["distinct_contract_count"], 144)
        self.assertEqual(coverage["activated_role_count"], 22)
        self.assertEqual(coverage["unactivated_role_ids"], [])
        self.assertEqual(coverage["automatic_external_action_count"], 0)
        artifact = json.loads(
            (ROOT / "evidence/v10/gtm-team-capability-matrix-v1.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(artifact, matrix)
        unsigned = dict(matrix)
        supplied = unsigned.pop("content_sha256")
        self.assertEqual(
            supplied,
            hashlib.sha256(
                json.dumps(
                    unsigned,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode("utf-8")
            ).hexdigest(),
        )


if __name__ == "__main__":
    unittest.main()
