from __future__ import annotations

import copy
import hashlib
import json
import unittest
from pathlib import Path

from prooflaunch_remix.gtm_codex_campaign_work_order import (
    CodexCampaignWorkOrderError,
    SURFACE_IDS,
    verify_codex_campaign_adaptation_matrix,
)
from scripts.compile_gtm_codex_campaign_adaptation_matrix import compile_from_files
from prooflaunch_remix.v10_submission_production_api import (
    load_verified_codex_campaign_adaptation_summary,
)


ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = ROOT / "evidence/v10/gtm-codex-campaign-adaptation-matrix-v1.json"


def _digest(value: object) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    ).hexdigest()


class CodexCampaignWorkOrderTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.matrix = compile_from_files()

    def test_sealed_matrix_matches_the_compiler(self) -> None:
        self.assertEqual(
            json.loads(EVIDENCE.read_text(encoding="utf-8")),
            self.matrix,
        )

    def test_all_456_valid_scenario_bindings_compile(self) -> None:
        payload = self.matrix
        self.assertEqual(payload["industry_archetype_count"], 20)
        self.assertEqual(payload["business_model_count"], 2)
        self.assertEqual(payload["lifecycle_count"], 4)
        self.assertEqual(payload["budget_count"], 3)
        self.assertEqual(payload["case_count"], 456)
        self.assertEqual(payload["work_order_count"], 456)
        self.assertEqual(payload["zero_budget_work_order_count"], 152)
        self.assertEqual(payload["regulated_work_order_count"], 72)
        self.assertEqual(payload["distinct_primary_channel_count"], 8)
        self.assertEqual(payload["overlapping_platform_work_order_count"], 304)
        self.assertEqual(
            payload["fully_overlapping_channel_surface_work_order_count"], 76
        )
        self.assertEqual(
            payload["empty_secondary_platform_surface_work_order_count"], 0
        )
        self.assertEqual(len({row["work_order_id"] for row in payload["work_orders"]}), 456)
        combinations = {
            (
                row["immutable_brief"]["business_model"],
                row["immutable_brief"]["lifecycle"],
                row["immutable_brief"]["budget"],
            )
            for row in payload["work_orders"]
        }
        self.assertEqual(len(combinations), 24)

    def test_protocol_is_bounded_l2_not_an_unbounded_agent(self) -> None:
        protocol = self.matrix["generation_protocol"]
        self.assertEqual(
            protocol["autonomy_level"],
            "L2_deterministic_workflow_with_bounded_model_generation",
        )
        self.assertEqual(len(protocol["graph"]), 5)
        self.assertEqual(len(protocol["named_failure_modes"]), 10)
        self.assertEqual(protocol["termination_conditions"]["maximum_generation_attempts"], 2)
        self.assertEqual(protocol["termination_conditions"]["maximum_critic_repair_rounds"], 1)
        self.assertFalse(protocol["permissions"]["model_may_publish_send_spend_or_contact"])
        self.assertFalse(protocol["permissions"]["model_critic_may_release_or_promote"])
        self.assertTrue(protocol["permissions"]["named_human_release_required"])

    def test_public_summary_is_compact_digest_bound_and_truthful(self) -> None:
        summary = load_verified_codex_campaign_adaptation_summary(ROOT)
        self.assertEqual(
            summary["schema"],
            "ProofLaunchCodexCampaignAdaptationSummaryPublicV1",
        )
        self.assertEqual(summary["source_matrix_sha256"], self.matrix["content_sha256"])
        self.assertEqual(summary["case_count"], 456)
        self.assertEqual(len(summary["archetypes"]), 20)
        self.assertEqual(sum(row["work_order_count"] for row in summary["archetypes"]), 456)
        self.assertNotIn("work_orders", summary)
        self.assertEqual(summary["model_call_count"], 0)
        self.assertEqual(summary["candidate_output_count"], 0)
        self.assertEqual(summary["release_eligible_count"], 0)
        self.assertEqual(summary["production_effect_observed_count"], 0)

    def test_every_work_order_has_the_full_last_mile_contract(self) -> None:
        for work_order in self.matrix["work_orders"]:
            output = work_order["model_task"]["required_output_contract"]
            self.assertEqual(output["platform_native_assets"]["count"], 13)
            self.assertEqual(tuple(output["platform_native_assets"]["surface_ids"]), SURFACE_IDS)
            self.assertEqual(output["lifecycle_phases"]["count"], 4)
            self.assertEqual(output["email_sequence"]["count"], 4)
            self.assertEqual(output["production_directions"]["count"], 3)
            self.assertEqual(output["search_geo_nodes"]["count"], 7)
            self.assertEqual(output["seven_day_flight"]["count"], 7)
            self.assertEqual(output["experiment_registry"]["count"], 4)
            self.assertTrue(work_order["strategy_contract"]["primary_platform_surfaces"])
            self.assertTrue(work_order["strategy_contract"]["secondary_platform_surfaces"])
            overlap = set(work_order["strategy_contract"]["primary_platform_surfaces"]) & set(
                work_order["strategy_contract"]["secondary_platform_surfaces"]
            )
            self.assertEqual(
                sorted(overlap),
                work_order["strategy_contract"]["overlapping_platform_surfaces"],
            )
            self.assertEqual(
                bool(overlap),
                work_order["strategy_contract"][
                    "overlap_requires_distinct_content_jobs"
                ],
            )
            self.assertEqual(work_order["approved_evidence"]["selected_proof_exact_text"], work_order["approved_evidence"]["claims"][0]["exact_text"])

    def test_zero_budget_regulation_and_execution_truth_fail_closed(self) -> None:
        for work_order in self.matrix["work_orders"]:
            brief = work_order["immutable_brief"]
            strategy = work_order["strategy_contract"]
            state = work_order["execution_state"]
            if brief["budget"] == "zero":
                self.assertNotIn(strategy["primary_channel"], {"paid_search", "paid_social"})
                self.assertNotIn(strategy["secondary_channel"], {"paid_search", "paid_social"})
            if brief["industry_risk"] == "high_regulation":
                self.assertTrue(
                    all(
                        claim["specialist_approved_by"] == "named-licensed-specialist"
                        for claim in work_order["approved_evidence"]["claims"]
                    )
                )
            self.assertEqual(state["model_call_count"], 0)
            self.assertFalse(state["candidate_output_present"])
            self.assertFalse(state["named_human_review_completed"])
            self.assertFalse(state["release_eligible"])
            self.assertFalse(state["external_publish_executed"])
            self.assertFalse(state["production_effect_observed"])
            self.assertFalse(state["causal_effect_claim_allowed"])
            self.assertFalse(state["automatic_strategy_mutation_executed"])

    def test_digest_and_model_authority_tamper_are_rejected(self) -> None:
        tampered = copy.deepcopy(self.matrix)
        tampered["work_orders"][0]["execution_state"]["model_call_count"] = 1
        with self.assertRaisesRegex(CodexCampaignWorkOrderError, "digest"):
            verify_codex_campaign_adaptation_matrix(tampered)

        tampered = copy.deepcopy(self.matrix)
        protocol = tampered["generation_protocol"]
        protocol["permissions"]["model_may_publish_send_spend_or_contact"] = True
        protocol_unsigned = dict(protocol)
        protocol_unsigned.pop("content_sha256")
        protocol["content_sha256"] = _digest(protocol_unsigned)
        tampered["generation_protocol_sha256"] = protocol["content_sha256"]
        for work_order in tampered["work_orders"]:
            work_order["protocol_sha256"] = protocol["content_sha256"]
            work_order["harness"]["permissions"][
                "model_may_publish_send_spend_or_contact"
            ] = True
            work_order_unsigned = dict(work_order)
            work_order_unsigned.pop("content_sha256")
            work_order["content_sha256"] = _digest(work_order_unsigned)
        matrix_unsigned = dict(tampered)
        matrix_unsigned.pop("content_sha256")
        tampered["content_sha256"] = _digest(matrix_unsigned)
        with self.assertRaisesRegex(CodexCampaignWorkOrderError, "boundary"):
            verify_codex_campaign_adaptation_matrix(tampered)


if __name__ == "__main__":
    unittest.main()
