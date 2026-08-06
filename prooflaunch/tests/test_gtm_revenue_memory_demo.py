from __future__ import annotations

import hashlib
import json
import unittest
from pathlib import Path
from zipfile import ZipFile

from prooflaunch_remix.gtm_learning_memory import validate_project_learning_context
from prooflaunch_remix.ledger import canonical_json


ROOT = Path(__file__).resolve().parents[1]
RECEIPT = ROOT / "evidence/v10/gtm-revenue-memory-demo.json"


class RevenueMemoryEndToEndDemoTests(unittest.TestCase):
    def setUp(self) -> None:
        self.receipt = json.loads(RECEIPT.read_text(encoding="utf-8"))

    def test_receipt_and_every_output_artifact_are_content_addressed(self) -> None:
        payload = dict(self.receipt)
        claimed = payload.pop("content_sha256")
        self.assertEqual(
            hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest(),
            claimed,
        )
        for item in self.receipt["artifacts"]:
            path = ROOT / item["path"]
            self.assertTrue(path.is_file())
            self.assertEqual(len(path.read_bytes()), item["bytes"])
            self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), item["sha256"])

    def test_demo_closes_mechanics_without_promoting_synthetic_effect(self) -> None:
        self.assertEqual(self.receipt["data_class"], "synthetic")
        self.assertEqual(self.receipt["external_api_calls"], 0)
        self.assertEqual(self.receipt["paid_media_spend_usd"], 0)
        self.assertFalse(self.receipt["external_publish_executed"])
        self.assertEqual(self.receipt["device_a"]["release_status"], "bundle_ready")
        self.assertRegex(
            self.receipt["device_a"]["manual_publication_receipt_sha256"],
            r"^[0-9a-f]{64}$",
        )
        self.assertFalse(
            self.receipt["device_a"]["publication_performed_by_prooflaunch"]
        )
        self.assertFalse(self.receipt["device_a"]["platform_delivery_verified"])
        self.assertTrue(self.receipt["device_a"]["revenue_positive_feedback_ready"])
        self.assertFalse(self.receipt["device_a"]["pipeline_counted_as_revenue"])
        self.assertFalse(self.receipt["device_a"]["causal_revenue_claim_allowed"])
        self.assertEqual(
            self.receipt["device_a"]["final_cockpit_next_action_ids"],
            ["decide_next_cycle"],
        )
        self.assertEqual(self.receipt["device_b"]["staged_status"], "pending_review")
        self.assertEqual(self.receipt["device_b"]["pending_context_memory_count"], 0)
        self.assertEqual(self.receipt["device_b"]["reviewed_status"], "approved")
        self.assertEqual(self.receipt["device_b"]["frozen_context_memory_count"], 1)
        self.assertEqual(self.receipt["device_b"]["prepared_status"], "awaiting_release")
        self.assertEqual(
            self.receipt["device_b"]["next_cycle_workspace_artifact_count"], 9
        )
        self.assertEqual(
            self.receipt["device_b"]["next_cycle_inherited_memory_count"], 1
        )
        self.assertEqual(
            self.receipt["device_b"]["next_cycle_eligible_memory_count"], 1
        )
        self.assertEqual(
            self.receipt["device_b"]["next_cycle_memory_application_status"],
            "eligible_pending_human_application",
        )
        self.assertEqual(
            self.receipt["device_b"]["next_cycle_memory_conflict_count"], 0
        )
        self.assertTrue(
            self.receipt["device_b"][
                "next_cycle_memory_human_application_required"
            ]
        )
        self.assertRegex(
            self.receipt["device_b"]["next_cycle_memory_decision_sha256"],
            r"^[0-9a-f]{64}$",
        )
        self.assertEqual(
            self.receipt["device_b"]["next_cycle_cockpit_next_action_ids"],
            ["review_campaign_workspace", "approve_or_reject_release"],
        )
        self.assertFalse(self.receipt["gates"]["pending_import_applied"])
        self.assertFalse(self.receipt["gates"]["synthetic_revenue_is_production_evidence"])
        self.assertFalse(self.receipt["gates"]["four_a_effect_claim_eligible"])
        self.assertFalse(
            self.receipt["gates"]["publication_performed_by_prooflaunch"]
        )
        self.assertFalse(self.receipt["gates"]["platform_delivery_verified"])

    def test_bundle_and_portable_context_are_real_and_reviewable(self) -> None:
        bundle = ROOT / "artifacts/gtm-revenue-memory-demo-v1/approved-campaign-bundle.zip"
        with ZipFile(bundle) as archive:
            self.assertIn("bundle-manifest.json", archive.namelist())
            self.assertIn("revenue-economics.json", archive.namelist())
            self.assertIn("effect-observations.json", archive.namelist())
        context = json.loads(
            (
                ROOT
                / "artifacts/gtm-revenue-memory-demo-v1/device-b-approved-learning-context.json"
            ).read_text(encoding="utf-8")
        )
        admitted = validate_project_learning_context(context)
        self.assertEqual(admitted["memory_count"], 1)
        self.assertFalse(admitted["automatic_strategy_mutation_executed"])

        final_cockpit = json.loads(
            (
                ROOT
                / "artifacts/gtm-revenue-memory-demo-v1/device-a-final-gtm-cockpit.json"
            ).read_text(encoding="utf-8")
        )
        next_cockpit = json.loads(
            (
                ROOT
                / "artifacts/gtm-revenue-memory-demo-v1/device-b-next-cycle-gtm-cockpit.json"
            ).read_text(encoding="utf-8")
        )
        self.assertEqual(final_cockpit["run_status"], "delivered")
        self.assertEqual(
            final_cockpit["effect_and_revenue"][
                "manual_publication_receipt_count"
            ],
            1,
        )
        self.assertEqual(
            final_cockpit["capability_effect_matrix"]["capability_count"], 11
        )
        self.assertEqual(
            final_cockpit["capability_effect_matrix"][
                "production_effect_attributed_count"
            ],
            0,
        )
        self.assertEqual(
            final_cockpit["effect_and_revenue"][
                "positive_feedback_observation_count"
            ],
            1,
        )
        self.assertEqual(next_cockpit["run_status"], "awaiting_release")
        self.assertEqual(
            next_cockpit["cross_device_memory"]["inherited_memory_count"], 1
        )
        self.assertEqual(
            next_cockpit["cross_device_memory"]["eligible_memory_count"], 1
        )
        self.assertEqual(
            next_cockpit["cross_device_memory"]["application_status"],
            "eligible_pending_human_application",
        )
        self.assertEqual(next_cockpit["cross_device_memory"]["conflict_count"], 0)
        self.assertTrue(
            next_cockpit["cross_device_memory"]["human_application_required"]
        )
        self.assertFalse(
            next_cockpit["cross_device_memory"][
                "automatic_strategy_mutation_executed"
            ]
        )
        self.assertTrue(next_cockpit["campaign_workspace"]["available"])
        self.assertEqual(
            next_cockpit["capability_effect_matrix"]["capability_count"], 11
        )


if __name__ == "__main__":
    unittest.main()
