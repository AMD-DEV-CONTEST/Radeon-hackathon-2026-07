from __future__ import annotations

import json
import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RADAR = ROOT / "config/gtm_open_source_capability_radar_v1.json"
SHA_PATTERN = re.compile(r"^[0-9a-f]{40}$")


class GTMOpenSourceCapabilityRadarTests(unittest.TestCase):
    def setUp(self) -> None:
        self.payload = json.loads(RADAR.read_text(encoding="utf-8"))

    def test_inventory_is_pinned_and_license_state_is_explicit(self) -> None:
        projects = self.payload["projects"]
        self.assertEqual(len(projects), self.payload["selection_counts"]["pinned_projects"])
        self.assertGreaterEqual(len(projects), 85)
        for project_id, project in projects.items():
            with self.subTest(project_id=project_id):
                self.assertRegex(project["revision"], SHA_PATTERN)
                self.assertEqual(project["url"], f"https://github.com/{project['repo']}")
                self.assertTrue(project["license"])
                self.assertTrue(project["decision"])
        deadline_projects = [
            project
            for project in projects.values()
            if project["decision"].startswith(("adopt", "primary"))
        ]
        self.assertEqual(
            len(deadline_projects),
            self.payload["selection_counts"][
                "deadline_adopt_or_primary_project_count"
            ],
        )

    def test_all_product_lanes_have_algorithms_projects_and_effect_gates(self) -> None:
        lanes = self.payload["capability_lanes"]
        projects = self.payload["projects"]
        self.assertEqual(len(lanes), self.payload["selection_counts"]["capability_lanes"])
        self.assertGreaterEqual(len(lanes), 45)
        self.assertEqual(len({lane["id"] for lane in lanes}), len(lanes))
        for lane in lanes:
            with self.subTest(lane=lane["id"]):
                self.assertGreaterEqual(len(lane["algorithms"]), 3)
                self.assertTrue(lane["outcome"])
                self.assertTrue(lane["decision"])
                self.assertTrue(lane["effect_gate"])
                self.assertTrue(lane["projects"])
                self.assertFalse(set(lane["projects"]) - set(projects))

    def test_deadline_path_stays_bounded_and_claims_stay_evidence_gated(self) -> None:
        text = json.dumps(self.payload, ensure_ascii=False).lower()
        self.assertFalse(self.payload["selection_counts"]["automatic_external_publish_enabled"])
        self.assertFalse(self.payload["selection_counts"]["automatic_strategy_mutation_enabled"])
        self.assertIn("stepfun-ai/step-audio", text)
        self.assertIn("no longer maintained", text)
        self.assertIn("minimax h3", text)
        self.assertIn("unverified", text)
        self.assertIn("ltx-2.3 as unconditional commercial default", text)
        self.assertIn("legal clearance", text)
        self.assertIn("captcha", text)
        self.assertIn("no 4a", text)
        self.assertIn("radeon", text)

    def test_adapted_models_have_explicit_admission_evidence(self) -> None:
        routes = self.payload["adapted_models"]
        self.assertGreaterEqual(len(routes), 15)
        self.assertEqual(len({route["role"] for route in routes}), len(routes))
        for route in routes:
            self.assertTrue(route["route"])
            self.assertTrue(route["admission"])

    def test_full_scenario_extension_covers_cross_cutting_product_systems(self) -> None:
        lanes = {lane["id"]: lane for lane in self.payload["capability_lanes"]}
        required = {
            "31_data_contracts_lineage_and_features",
            "32_enterprise_knowledge_and_document_intelligence",
            "33_customer_lifetime_value_and_retention",
            "34_personalization_and_next_best_action",
            "35_offer_pricing_and_choice",
            "36_virality_community_and_influence",
            "37_forecasting_anomaly_and_capacity",
            "38_multimodal_quality_evaluation",
            "39_privacy_policy_and_agent_firewall",
            "40_asset_provenance_rights_and_authenticity",
            "41_creative_workflow_and_human_annotation",
            "42_local_analytics_and_executive_intelligence",
            "43_customer_profile_and_identity_resolution",
            "44_seo_geo_and_answer_visibility_operations",
            "45_optimization_observability_and_change_control",
        }
        self.assertFalse(required - set(lanes))

        text = json.dumps(self.payload, ensure_ascii=False).lower()
        for token in (
            "point-in-time",
            "future leakage",
            "citation span",
            "cold-start",
            "change-point",
            "c2pa",
            "human-selection provenance",
            "no autonomous price change",
            "no_self_modification",
        ):
            with self.subTest(token=token):
                self.assertIn(token, text)

    def test_second_pass_closes_employee_execution_and_revenue_lanes(self) -> None:
        lanes = {lane["id"]: lane for lane in self.payload["capability_lanes"]}
        required = {
            "46_desktop_browser_and_computer_use",
            "47_sales_crm_abm_and_pipeline",
            "48_lifecycle_messaging_and_customer_success",
            "49_marketing_automation_and_connector_fabric",
            "50_localization_transcreation_and_accessibility",
            "51_landing_page_cro_and_web_experience",
            "52_brand_governance_claims_and_consistency",
            "53_competitive_product_and_market_intelligence",
            "54_creator_influencer_pr_and_partnerships",
            "55_creative_documents_slides_and_sales_collateral",
            "56_multiagent_scaling_and_durable_execution",
            "57_agent_environment_training_and_benchmarking",
            "58_unit_economics_revenue_and_margin_feedback",
            "59_multimodal_memory_and_cross_session_skill_reuse",
            "60_unified_multimodal_creation_and_editing",
        }
        self.assertFalse(required - set(lanes))
        self.assertGreaterEqual(len(self.payload["projects"]), 110)
        text = json.dumps(self.payload, ensure_ascii=False).lower()
        for token in (
            "playwright",
            "browsergym",
            "ui-tars",
            "showui",
            "presentbench",
            "refund",
            "contribution margin",
            "pipeline excluded",
            "exact deletion",
            "no access-control bypass",
        ):
            with self.subTest(token=token):
                self.assertIn(token, text)

    def test_new_model_routes_remain_evidence_gated(self) -> None:
        routes = {route["role"]: route for route in self.payload["adapted_models"]}
        for role in (
            "multimodal_model_evaluation",
            "document_understanding",
            "multireference_image_editing",
            "joint_video_audio_generation",
            "personalization_and_recommendation",
            "gui_computer_use",
            "unified_multimodal_research",
            "multimodal_memory_retrieval",
            "professional_collateral_evaluation",
        ):
            self.assertIn(role, routes)
        self.assertIn("blind preference", routes["multireference_image_editing"]["admission"])
        self.assertIn("research challenger", routes["joint_video_audio_generation"]["route"])
        self.assertIn("randomized lift", routes["personalization_and_recommendation"]["admission"])


if __name__ == "__main__":
    unittest.main()
