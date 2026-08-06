from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path

from prooflaunch_remix.gtm_human_capability_kernel import (
    EXPECTED_EVAL_CHECK_COUNT,
    EXPECTED_PROFESSIONAL_AXIS_COUNT,
    EXPECTED_SKILL_CARD_COUNT,
    GTMHumanCapabilityKernelError,
    PROFESSIONAL_AXIS_IDS,
    compile_gtm_human_capability_kernel,
    verify_gtm_human_capability_kernel,
)
from scripts.compile_gtm_human_capability_kernel import compile_from_files


ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = ROOT / "evidence/v10/gtm-human-capability-kernel-v2.json"


class GTMHumanCapabilityKernelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.kernel = compile_from_files()
        cls.radar = json.loads(
            (ROOT / "config/gtm_open_source_capability_radar_v1.json").read_text(
                encoding="utf-8"
            )
        )

    def test_twenty_two_roles_expand_to_two_hundred_twenty_professional_cards(self) -> None:
        coverage = self.kernel["coverage"]
        self.assertEqual(coverage["role_count"], 22)
        self.assertEqual(coverage["skills_per_role"], 10)
        self.assertEqual(
            coverage["professional_skill_card_count"], EXPECTED_SKILL_CARD_COUNT
        )
        self.assertEqual(len(self.kernel["role_okrs"]), 22)
        self.assertEqual(len(self.kernel["functional_squads"]), 8)

    def test_ten_x_detail_is_exact_execution_and_eval_coverage(self) -> None:
        coverage = self.kernel["coverage"]
        self.assertEqual(
            coverage["professional_axis_count"], EXPECTED_PROFESSIONAL_AXIS_COUNT
        )
        self.assertEqual(coverage["detail_expansion_factor_over_skill_name_inventory"], 10)
        self.assertEqual(coverage["eval_check_count"], EXPECTED_EVAL_CHECK_COUNT)
        self.assertEqual(coverage["eval_checks_per_skill"], 10)
        for card in self.kernel["professional_skill_cards"]:
            self.assertEqual(
                [row["axis_id"] for row in card["professional_contract_axes"]],
                list(PROFESSIONAL_AXIS_IDS),
            )
            self.assertEqual(
                sum(len(rows) for rows in card["evaluation_pyramid"].values()),
                10,
            )

    def test_b2b_and_b2c_reference_cohorts_do_not_invent_internal_org_charts(self) -> None:
        cohort = self.kernel["public_reference_cohorts"]
        self.assertEqual(cohort["b2b_company_count"], 10)
        self.assertEqual(cohort["b2c_company_count"], 10)
        self.assertFalse(cohort["authoritative_global_rank_claimed"])
        self.assertFalse(cohort["internal_org_chart_inferred"])
        self.assertFalse(cohort["performance_parity_claimed"])
        self.assertTrue(
            all(row["official_url"].startswith("https://") for row in cohort["companies"])
        )

    def test_thirteen_surfaces_have_four_distinct_professional_lenses(self) -> None:
        surfaces = self.kernel["surface_operating_system"]
        self.assertEqual(surfaces["surface_count"], 13)
        self.assertEqual(surfaces["social_surface_count"], 6)
        self.assertEqual(surfaces["search_surface_count"], 2)
        self.assertEqual(surfaces["geo_answer_surface_count"], 5)
        self.assertEqual(surfaces["specialist_lens_count"], 52)
        per_surface: dict[str, set[str]] = {}
        for row in surfaces["specialist_council"]:
            per_surface.setdefault(row["surface_id"], set()).add(
                row["professional_lens"]
            )
            self.assertFalse(row["hidden_algorithm_or_ranking_inference_allowed"])
        self.assertTrue(all(len(lenses) == 4 for lenses in per_surface.values()))
        edge = surfaces["unconventional_edge_play_contract"]
        self.assertEqual(edge["card_count"], 26)
        self.assertTrue(edge["unconventional_not_deceptive"])
        self.assertEqual(
            len({row["edge_play_card_id"] for row in edge["cards"]}), 26
        )
        for row in edge["cards"]:
            self.assertFalse(row["external_activation_allowed"])
            self.assertTrue(row["recent_3_to_6_month_baseline_required"])
            self.assertGreaterEqual(len(row["prohibited_tactics"]), 8)

    def test_every_oss_adapter_is_pinned_but_never_auto_promoted(self) -> None:
        projects = self.radar["projects"]
        referenced = self.kernel["open_source_composition"][
            "referenced_project_ids"
        ]
        self.assertTrue(set(referenced) <= set(projects))
        for card in self.kernel["professional_skill_cards"]:
            for adapter in card["oss_composition"]:
                self.assertEqual(len(adapter["revision"]), 40)
                self.assertFalse(adapter["automatic_admission"])

    def test_all_skill_cards_enter_at_least_one_staffing_context(self) -> None:
        coverage = self.kernel["coverage"]
        self.assertEqual(coverage["staffing_context_count"], 144)
        self.assertEqual(
            coverage["activated_skill_card_count"], EXPECTED_SKILL_CARD_COUNT
        )
        b2b = next(
            row
            for row in self.kernel["staffing_manifests"]
            if row["business_model"] == "b2b"
        )
        b2c = next(
            row
            for row in self.kernel["staffing_manifests"]
            if row["business_model"] == "b2c"
        )
        self.assertIn("demand_generation_lead", b2b["active_role_ids"])
        self.assertNotIn("demand_generation_lead", b2c["active_role_ids"])
        self.assertIn("product_led_growth_lead", b2c["active_role_ids"])

    def test_permissions_and_effect_claims_fail_closed(self) -> None:
        verify_gtm_human_capability_kernel(
            self.kernel, open_source_radar=self.radar
        )
        tampered = copy.deepcopy(self.kernel)
        tampered["professional_skill_cards"][0]["permissions"][
            "may_publish_send_spend_or_contact"
        ] = True
        with self.assertRaisesRegex(GTMHumanCapabilityKernelError, "digest"):
            verify_gtm_human_capability_kernel(
                tampered, open_source_radar=self.radar
            )

    def test_sealed_evidence_matches_the_compiler(self) -> None:
        self.assertTrue(EVIDENCE.is_file(), "run compile_gtm_human_capability_kernel.py")
        self.assertEqual(
            json.loads(EVIDENCE.read_text(encoding="utf-8")), self.kernel
        )


if __name__ == "__main__":
    unittest.main()
