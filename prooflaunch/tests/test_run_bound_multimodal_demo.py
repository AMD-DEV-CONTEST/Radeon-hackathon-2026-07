from __future__ import annotations

import hashlib
import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RECEIPT = ROOT / "artifacts/run-bound-multimodal-demo-v1/demo-receipt.json"


def _digest(payload: object) -> str:
    return hashlib.sha256(
        json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    ).hexdigest()


class RunBoundMultimodalDemoTests(unittest.TestCase):
    def setUp(self) -> None:
        self.payload = json.loads(RECEIPT.read_text(encoding="utf-8"))

    def test_receipt_binds_real_artifacts_and_keeps_subjective_effect_gates_false(self) -> None:
        payload = self.payload
        unsigned = dict(payload)
        supplied = unsigned.pop("content_sha256")
        self.assertEqual(supplied, _digest(unsigned))
        self.assertEqual(payload["schema"], "ProofLaunchRunBoundMultimodalDemoV1")
        self.assertEqual(
            payload["evidence_class"],
            "mixed_real_artifacts_synthetic_control_plane",
        )
        self.assertEqual(payload["run_status"], "delivered")
        self.assertEqual(payload["real_artifact_count"], 3)
        self.assertEqual(payload["registered_multimodal_deliverable_count"], 2)
        self.assertEqual(payload["registered_capability_deliverable_count"], 8)
        self.assertEqual(payload["registered_run_bound_deliverable_count"], 10)
        self.assertEqual(payload["persisted_production_document_count"], 21)
        self.assertEqual(payload["named_human_quality_count"], 0)
        self.assertEqual(payload["production_effect_attributed_count"], 0)
        boundary = payload["authority_boundary"]
        self.assertTrue(boundary["synthetic_control_plane_approval_used"])
        for key in (
            "real_named_human_media_review_observed",
            "external_publish_executed",
            "automatic_publish_enabled",
            "automatic_spend_enabled",
            "production_effect_proven",
            "four_a_quality_proven",
            "top1_standing_proven",
        ):
            self.assertFalse(boundary[key])

        for artifact in payload["artifacts"]:
            path = ROOT / artifact["path"]
            body = path.read_bytes()
            self.assertEqual(len(body), artifact["bytes"])
            self.assertEqual(hashlib.sha256(body).hexdigest(), artifact["sha256"])
        for item in payload["evidence_files"]:
            path = ROOT / item["path"]
            self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), item["sha256"])
        roles = {item["artifact_role"] for item in payload["production_deliverables"]}
        self.assertEqual(
            roles,
            {
                "brief-intelligence.json",
                "product-evidence-register.json",
                "creative-strategy-kernel.json",
                "editorial-quality-receipt.json",
                "multimodal-direction-receipt.json",
                "distribution-operations.json",
                "revenue-journey-operations.json",
                "mechanism-abstraction-register.json",
                "promotion-governance.json",
                "gtm-strategy.json",
                "big-idea-and-message-hierarchy.json",
                "content-calendar.json",
                "channel-copy.json",
                "landing-page-draft.json",
                "lifecycle-email-draft.json",
                "analytics-plan.json",
                "seo-geo-faq-drafts.json",
                "seo-geo-questions.json",
                "graph-loop-harness.json",
                "channel-portfolio.json",
                "approved-learning-context.json",
            },
        )
        for item in payload["production_deliverables"]:
            path = ROOT / item["path"]
            body = path.read_bytes()
            self.assertEqual(len(body), item["bytes"])
            self.assertEqual(hashlib.sha256(body).hexdigest(), item["sha256"])

    def test_production_copy_has_specific_audience_and_no_placeholder_grammar(self) -> None:
        by_role = {
            item["artifact_role"]: ROOT / item["path"]
            for item in self.payload["production_deliverables"]
        }
        inspected = "\n".join(
            by_role[name].read_text(encoding="utf-8")
            for name in (
                "gtm-strategy.json",
                "channel-copy.json",
                "landing-page-draft.json",
                "lifecycle-email-draft.json",
                "seo-geo-faq-drafts.json",
            )
        )
        self.assertIn("GTM leaders and founder-led growth teams", inspected)
        for defect in (
            "intended audience",
            "owner context not supplied",
            "this decision may occur in",
            "before choosing review",
            "to address needs reliable evidence",
        ):
            self.assertNotIn(defect, inspected)

    def test_cockpit_counts_ten_run_bound_deliverables_but_no_human_or_effect_result(self) -> None:
        cockpit_path = ROOT / next(
            item["path"]
            for item in self.payload["evidence_files"]
            if item["path"].endswith("gtm-cockpit.json")
        )
        cockpit = json.loads(cockpit_path.read_text(encoding="utf-8"))
        unsigned = dict(cockpit)
        supplied = unsigned.pop("content_sha256")
        self.assertEqual(supplied, _digest(unsigned))
        matrix = cockpit["capability_effect_matrix"]
        self.assertEqual(matrix["capability_count"], 11)
        self.assertEqual(matrix["contract_connected_count"], 11)
        self.assertEqual(matrix["generated_deliverable_count"], 10)
        self.assertEqual(matrix["named_human_quality_count"], 0)
        self.assertEqual(matrix["production_effect_attributed_count"], 0)
        self.assertFalse(matrix["all_capability_effects_proven"])
        rows = {row["capability_id"]: row for row in matrix["capabilities"]}
        for capability_id in ("audio_generation", "video_generation"):
            row = rows[capability_id]
            self.assertEqual(row["evidence_stage"], "generated_unreviewed")
            self.assertTrue(row["generated_deliverable_observed"])
            self.assertFalse(row["named_human_quality_observed"])
            self.assertFalse(row["production_effect_attributed"])
            self.assertRegex(row["deliverable_sha256"], r"^[0-9a-f]{64}$")
            self.assertRegex(row["execution_receipt_sha256"], r"^[0-9a-f]{64}$")
            self.assertIn("frozen", row["next_gate"])
        for capability_id in (
            "data_strategy",
            "content_scheduling",
            "text_generation",
            "data_analysis",
            "geo_visibility",
            "seo_operations",
            "employee_agent",
            "advertising",
        ):
            row = rows[capability_id]
            self.assertEqual(row["evidence_stage"], "generated_unreviewed")
            self.assertTrue(row["generated_deliverable_observed"])
            self.assertFalse(row["named_human_quality_observed"])
            self.assertFalse(row["production_effect_attributed"])
            self.assertRegex(row["deliverable_sha256"], r"^[0-9a-f]{64}$")
            self.assertRegex(row["execution_receipt_sha256"], r"^[0-9a-f]{64}$")
            self.assertTrue(row["artifact_role"].endswith(".json"))
        memory = rows["cross_device_memory"]
        self.assertFalse(memory["generated_deliverable_observed"])
        self.assertFalse(cockpit["four_a_effect_claim_eligible"])
        self.assertFalse(cockpit["top1_claim_eligible"])

    def test_execution_receipts_preserve_local_cloud_and_radeon_boundaries(self) -> None:
        source = self.payload["source_execution"]
        self.assertTrue(source["local_model_inference_observed"])
        self.assertTrue(source["provider_api_generation_observed"])
        self.assertEqual(source["provider_api_call_count"], 1)
        self.assertEqual(source["new_model_calls_executed_by_this_demo"], 0)
        self.assertEqual(source["new_downloads_executed_by_this_demo"], 0)
        self.assertFalse(source["radeon_execution_observed"])
        registrations = {
            item["capability_id"]: item
            for item in self.payload["multimodal_registrations"]
        }
        self.assertEqual(set(registrations), {"audio_generation", "video_generation"})
        self.assertEqual(
            registrations["audio_generation"]["payload"]["source_kind"],
            "local_model_inference",
        )
        self.assertEqual(
            registrations["video_generation"]["payload"]["source_kind"],
            "provider_api_generation",
        )
        for registration in registrations.values():
            self.assertTrue(registration["generated_deliverable_observed"])
            self.assertFalse(registration["named_human_quality_observed"])
            self.assertFalse(registration["production_effect_proven"])
            self.assertFalse(registration["four_a_quality_proven"])
        capability_registrations = {
            item["capability_id"]: item
            for item in self.payload["capability_registrations"]
        }
        self.assertEqual(len(capability_registrations), 8)
        for registration in capability_registrations.values():
            self.assertEqual(
                registration["payload"]["source_kind"], "deterministic_compiler"
            )
            self.assertTrue(registration["generated_deliverable_observed"])
            self.assertFalse(registration["named_human_quality_observed"])
            self.assertFalse(registration["production_effect_proven"])
            self.assertFalse(registration["four_a_quality_proven"])


if __name__ == "__main__":
    unittest.main()
