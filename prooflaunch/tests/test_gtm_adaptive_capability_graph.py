from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from prooflaunch_remix.gtm_adaptive_capability_graph import (
    AdaptiveCapabilityGraphError,
    AdaptiveContext,
    compile_adaptive_capability_graph_matrix,
    compile_context,
    distribution_operating_floor,
)
from prooflaunch_remix.gtm_strategy import (
    BudgetTier,
    BusinessModel,
    CompanyScale,
    ContentCapacity,
    DistributionStrength,
    IndustryRisk,
    LifecycleStage,
    SalesMotion,
)


ROOT = Path(__file__).resolve().parents[1]


class GTMAdaptiveCapabilityGraphTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.payload = compile_adaptive_capability_graph_matrix(
            hybrid_path=ROOT / "evidence/v10/gtm-hybrid-quality-control-v1.json",
            radar_path=ROOT / "config/gtm_open_source_capability_radar_v1.json",
            candidate_registry_path=ROOT / "config/gtm_adaptive_oss_skill_candidates_v1.json",
        )

    def test_covers_all_6912_contexts_and_exactly_thirteen_lanes_each(self) -> None:
        self.assertEqual(self.payload["coverage"]["context_count"], 6912)
        self.assertEqual(self.payload["coverage"]["lane_decision_count"], 89856)
        self.assertTrue(all(len(row["lane_states"]) == 13 for row in self.payload["contexts"]))
        self.assertTrue(all(sum(state == "FOCUS" for state in row["lane_states"].values()) == 4 for row in self.payload["contexts"]))
        self.assertGreaterEqual(self.payload["coverage"]["distinct_lane_state_profiles"], 400)
        self.assertGreaterEqual(self.payload["coverage"]["distinct_focus_profiles"], 35)

    def test_zero_budget_and_regulation_gates_are_mechanical(self) -> None:
        zero = [row for row in self.payload["contexts"] if row["dimensions"]["budget"] == "zero"]
        regulated = [row for row in self.payload["contexts"] if row["dimensions"]["industry_risk"] == "high_regulation"]
        self.assertTrue(zero)
        self.assertTrue(regulated)
        self.assertTrue(all(row["lane_states"]["advertising_activation"] == "EXCLUDED" for row in zero))
        self.assertTrue(all(row["paid_activation_candidate_count"] == 0 for row in zero))
        self.assertTrue(all(row["specialist_approval_required"] for row in regulated))

    def test_paid_candidate_requires_budget_stage_distribution_and_still_cannot_execute(self) -> None:
        eligible = [
            row for row in self.payload["contexts"]
            if row["paid_activation_eligible_for_human_review"]
        ]
        self.assertTrue(eligible)
        self.assertTrue(all(row["dimensions"]["budget"] != "zero" for row in eligible))
        self.assertTrue(all(row["dimensions"]["lifecycle"] in {"growth", "mature"} for row in eligible))
        self.assertTrue(all(row["dimensions"]["distribution_strength"] in {"established", "strong"} for row in eligible))
        self.assertTrue(all(row["paid_activation_candidate_count"] == 1 for row in eligible))
        self.assertTrue(all(row["automatic_external_actions"] == 0 for row in eligible))

    def test_every_failure_signal_has_a_bounded_counterfactual_repair_adapter(self) -> None:
        for lane in self.payload["lane_execution_contracts"].values():
            self.assertEqual(len(lane["repair_adapters"]), len(lane["failure_signals"]))
            for repair in lane["repair_adapters"]:
                self.assertTrue(repair["reason_code"])
                self.assertTrue(repair["next_counterfactual_evidence"])
                self.assertTrue(repair["incumbent_oss_project_ids"])
                self.assertFalse(repair["automatic_adapter_switch_allowed"])

    def test_all_loops_are_bounded_and_external_actions_remain_human_gated(self) -> None:
        self.assertLessEqual(self.payload["coverage"]["maximum_node_loop_iteration_cap"], 3)
        self.assertEqual(self.payload["coverage"]["automatic_external_action_count"], 0)
        self.assertFalse(self.payload["graph_loop_harness"]["global_harness"]["automatic_publish_send_spend_or_strategy_mutation"])
        self.assertTrue(all(row["human_release_required"] for row in self.payload["contexts"]))

    def test_lifecycle_and_distribution_materially_change_the_plan(self) -> None:
        base = dict(
            business_model=BusinessModel.B2C,
            budget=BudgetTier.SMALL,
            industry_risk=IndustryRisk.STANDARD,
            company_scale=CompanyScale.STARTUP,
            content_capacity=ContentCapacity.STANDARD,
            sales_motion=SalesMotion.HYBRID,
        )
        cold = compile_context(AdaptiveContext(
            lifecycle=LifecycleStage.PRE_PMF,
            distribution_strength=DistributionStrength.NONE,
            **base,
        ))
        scaled = compile_context(AdaptiveContext(
            lifecycle=LifecycleStage.GROWTH,
            distribution_strength=DistributionStrength.STRONG,
            **base,
        ))
        self.assertNotEqual(cold["plan_sha256"], scaled["plan_sha256"])
        self.assertNotEqual(cold["lane_states"], scaled["lane_states"])
        self.assertNotEqual(cold["primary_growth_route"], scaled["primary_growth_route"])

    def test_runtime_distribution_floor_cannot_hide_one_missing_distribution_link(self) -> None:
        self.assertEqual(
            distribution_operating_floor(
                DistributionStrength.STRONG,
                DistributionStrength.ESTABLISHED,
                DistributionStrength.NONE,
                DistributionStrength.STRONG,
            ),
            DistributionStrength.NONE,
        )
        with self.assertRaisesRegex(AdaptiveCapabilityGraphError, "four typed strengths"):
            distribution_operating_floor(DistributionStrength.STRONG)

    def test_hardware_and_vendor_metadata_do_not_change_context_plan_identity(self) -> None:
        first = compile_adaptive_capability_graph_matrix(
            hybrid_path=ROOT / "evidence/v10/gtm-hybrid-quality-control-v1.json",
            radar_path=ROOT / "config/gtm_open_source_capability_radar_v1.json",
            candidate_registry_path=ROOT / "config/gtm_adaptive_oss_skill_candidates_v1.json",
            executor_metadata={"hardware": "Apple GPU", "provider": "local"},
        )
        second = compile_adaptive_capability_graph_matrix(
            hybrid_path=ROOT / "evidence/v10/gtm-hybrid-quality-control-v1.json",
            radar_path=ROOT / "config/gtm_open_source_capability_radar_v1.json",
            candidate_registry_path=ROOT / "config/gtm_adaptive_oss_skill_candidates_v1.json",
            executor_metadata={"hardware": "cloud GPU", "provider": "replaceable"},
        )
        self.assertEqual(
            [row["plan_sha256"] for row in first["contexts"]],
            [row["plan_sha256"] for row in second["contexts"]],
        )

    def test_skills_and_trace_training_fail_closed_until_individually_admitted(self) -> None:
        candidates = {row["id"]: row for row in self.payload["shadow_candidate_registry"]["candidates"]}
        self.assertFalse(self.payload["shadow_candidate_registry"]["automatic_skill_script_execution_enabled"])
        self.assertFalse(self.payload["shadow_candidate_registry"]["automatic_online_training_enabled"])
        self.assertIn("individual skill license is explicit", candidates["anthropic_skills"]["admission_gates"])
        self.assertIn("individual skill and asset license is explicit", candidates["openai_skills"]["admission_gates"])
        self.assertIn("trajectory and output rights are explicit", candidates["agent_lightning"]["admission_gates"])
        self.assertIn("human labels or verifiable rewards are admitted", candidates["agent_lightning"]["admission_gates"])

    def test_candidate_registry_tampering_fails_closed(self) -> None:
        registry = json.loads((ROOT / "config/gtm_adaptive_oss_skill_candidates_v1.json").read_text())
        registry["policy"]["automatic_skill_script_execution_enabled"] = True
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "candidates.json"
            path.write_text(json.dumps(registry), encoding="utf-8")
            with self.assertRaisesRegex(AdaptiveCapabilityGraphError, "automatic mutation"):
                compile_adaptive_capability_graph_matrix(
                    hybrid_path=ROOT / "evidence/v10/gtm-hybrid-quality-control-v1.json",
                    radar_path=ROOT / "config/gtm_open_source_capability_radar_v1.json",
                    candidate_registry_path=path,
                )


if __name__ == "__main__":
    unittest.main()
