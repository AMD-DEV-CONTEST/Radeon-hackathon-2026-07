from __future__ import annotations

import hashlib
import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]

from prooflaunch_remix.gtm_platform_generation_quality import (
    compile_platform_generation_quality_audit,
)
from prooflaunch_remix.gtm_platform_native_challenger import (
    CREATIVE_FIELDS,
    compile_platform_native_receipt,
)


class GTMPlatformGoldReferenceTests(unittest.TestCase):
    def test_editorial_war_room_overlay_passes_all_thirteen_pre_human_rows(self) -> None:
        plan = json.loads(
            (ROOT / "artifacts/gtm-last-mile-pk-v1/platform-native-challengers-v6/b2b-plan.json").read_text(encoding="utf-8")
        )
        reference_path = ROOT / "config/platform-native-b2b-gold-reference-v1.json"
        reference = json.loads(reference_path.read_text(encoding="utf-8"))
        overlay = json.loads(
            (ROOT / "config/platform-native-b2b-codex-capability-overlay-v3.json").read_text(encoding="utf-8")
        )
        self.assertEqual(overlay["base_reference_sha256"], hashlib.sha256(reference_path.read_bytes()).hexdigest())
        overrides = {row["surface_id"]: row for row in overlay["overrides"]}
        self.assertEqual(set(overrides), {"linkedin", "reddit", "youtube", "google_search", "chatgpt_answers"})
        candidates = [overrides.get(row["surface_id"], row) for row in reference["candidates"]]
        attempts = {
            row["surface_id"]: [{
                "raw_output": json.dumps({field: row[field] for field in CREATIVE_FIELDS}, ensure_ascii=False),
                "source": "codex_editorial_war_room_v3",
                "elapsed_seconds": 0,
                "generated_token_count": 0,
            }]
            for row in candidates
        }
        receipt = compile_platform_native_receipt(
            plan=plan,
            model={"provider": "codex_workspace_clean_room_reference_authoring", "reference_only": True},
            attempts_by_surface=attempts,
        )
        audit = compile_platform_generation_quality_audit(plan=plan, receipt=receipt)
        self.assertEqual(receipt["accepted_surface_count"], 13)
        self.assertEqual(audit["pre_human_quality_pass_count"], 13)
        self.assertEqual(audit["blocked_count"], 0)
        self.assertEqual(audit["cross_surface_duplicate_pairs"], [])
        self.assertFalse(audit["four_a_claim_eligible"])
        self.assertFalse(audit["top1_claim_eligible"])

    def test_original_reference_passes_all_pre_human_rows_without_effect_claim(self) -> None:
        plan = json.loads(
            (
                ROOT
                / "artifacts/gtm-last-mile-pk-v1/platform-native-challengers-v6/b2b-plan.json"
            ).read_text(encoding="utf-8")
        )
        reference = json.loads(
            (ROOT / "config/platform-native-b2b-gold-reference-v1.json").read_text(
                encoding="utf-8"
            )
        )
        attempts = {
            row["surface_id"]: [
                {
                    "raw_output": json.dumps(
                        {field: row[field] for field in CREATIVE_FIELDS}
                    ),
                    "source": "fixture_original_reference",
                    "elapsed_seconds": 0,
                    "generated_token_count": 0,
                }
            ]
            for row in reference["candidates"]
        }
        receipt = compile_platform_native_receipt(
            plan=plan,
            model={"provider": "fixture", "reference_only": True},
            attempts_by_surface=attempts,
        )
        audit = compile_platform_generation_quality_audit(
            plan=plan, receipt=receipt
        )
        self.assertEqual(receipt["accepted_surface_count"], 13)
        self.assertEqual(audit["pre_human_quality_pass_count"], 13)
        self.assertEqual(audit["cross_surface_duplicate_pairs"], [])
        self.assertEqual(audit["human_craft_review_completed_count"], 0)
        self.assertFalse(audit["production_effect_observed"])
        self.assertFalse(audit["four_a_claim_eligible"])
        self.assertFalse(audit["top1_claim_eligible"])

    def test_codex_capability_overlay_is_digest_bound_visible_and_truth_safe(self) -> None:
        plan = json.loads(
            (
                ROOT
                / "artifacts/gtm-last-mile-pk-v1/platform-native-challengers-v6/b2b-plan.json"
            ).read_text(encoding="utf-8")
        )
        reference_path = ROOT / "config/platform-native-b2b-gold-reference-v1.json"
        reference_bytes = reference_path.read_bytes()
        reference = json.loads(reference_bytes)
        overlay = json.loads(
            (
                ROOT / "config/platform-native-b2b-codex-capability-overlay-v2.json"
            ).read_text(encoding="utf-8")
        )
        self.assertEqual(
            overlay["base_reference_sha256"],
            hashlib.sha256(reference_bytes).hexdigest(),
        )
        self.assertEqual(overlay["schema"], "ProofLaunchPlatformNativeCodexOverlayV1")
        self.assertFalse(overlay["named_product_baseline"])
        self.assertFalse(overlay["human_review_completed"])
        self.assertFalse(overlay["production_effect_observed"])

        overrides = {row["surface_id"]: row for row in overlay["overrides"]}
        self.assertEqual(set(overrides), {"linkedin", "tiktok", "google_search"})
        for row in overrides.values():
            capability_text = json.dumps(row, ensure_ascii=False).lower()
            self.assertTrue(
                any(
                    label in capability_text
                    for label in ("synthetic scenario", "hypothetical", "composite")
                )
            )

        merged_candidates = [
            overrides.get(row["surface_id"], row) for row in reference["candidates"]
        ]
        attempts = {
            row["surface_id"]: [
                {
                    "raw_output": json.dumps(
                        {field: row[field] for field in CREATIVE_FIELDS},
                        ensure_ascii=False,
                    ),
                    "source": (
                        "codex_clean_room_capability_overlay"
                        if row["surface_id"] in overrides
                        else "original_clean_room_workspace_reference"
                    ),
                    "elapsed_seconds": 0,
                    "generated_token_count": 0,
                }
            ]
            for row in merged_candidates
        }
        receipt = compile_platform_native_receipt(
            plan=plan,
            model={
                "provider": "codex_workspace_clean_room_reference_authoring",
                "reference_only": True,
                "local_inference_claimed": False,
                "training_observed": False,
            },
            attempts_by_surface=attempts,
        )
        audit = compile_platform_generation_quality_audit(plan=plan, receipt=receipt)
        self.assertEqual(receipt["accepted_surface_count"], 13)
        self.assertEqual(audit["pre_human_quality_pass_count"], 13)
        self.assertEqual(audit["blocked_count"], 0)
        self.assertEqual(audit["cross_surface_duplicate_pairs"], [])
        self.assertEqual(audit["human_craft_review_completed_count"], 0)
        self.assertFalse(audit["production_effect_observed"])
        self.assertFalse(audit["four_a_claim_eligible"])
        self.assertFalse(audit["top1_claim_eligible"])

    def test_b2c_codex_reference_passes_craft_but_stays_permanently_unpublishable(self) -> None:
        plan = json.loads(
            (
                ROOT
                / "artifacts/gtm-last-mile-pk-v1/platform-native-challengers-v6/b2c-plan.json"
            ).read_text(encoding="utf-8")
        )
        reference = json.loads(
            (
                ROOT / "config/platform-native-b2c-codex-reference-v1.json"
            ).read_text(encoding="utf-8")
        )
        attempts = {
            row["surface_id"]: [
                {
                    "raw_output": json.dumps(
                        {field: row[field] for field in CREATIVE_FIELDS},
                        ensure_ascii=False,
                    ),
                    "source": "codex_clean_room_b2c_capability_reference",
                    "elapsed_seconds": 0,
                    "generated_token_count": 0,
                }
            ]
            for row in reference["candidates"]
        }
        receipt = compile_platform_native_receipt(
            plan=plan,
            model={
                "provider": "codex_workspace_clean_room_reference_authoring",
                "reference_only": True,
                "capability_reference_only": True,
                "local_inference_claimed": False,
                "training_observed": False,
            },
            attempts_by_surface=attempts,
        )
        publication_conflated_audit = compile_platform_generation_quality_audit(
            plan=plan, receipt=receipt
        )
        capability_audit = compile_platform_generation_quality_audit(
            plan=plan,
            receipt=receipt,
            capability_reference_only=True,
        )
        self.assertEqual(receipt["accepted_surface_count"], 13)
        self.assertEqual(publication_conflated_audit["pre_human_quality_pass_count"], 0)
        self.assertEqual(capability_audit["pre_human_quality_pass_count"], 13)
        self.assertEqual(capability_audit["blocked_count"], 0)
        self.assertEqual(capability_audit["cross_surface_duplicate_pairs"], [])
        self.assertTrue(capability_audit["capability_reference_only"])
        self.assertEqual(capability_audit["mechanically_publication_ready_count"], 0)
        self.assertEqual(capability_audit["publication_blocked_count"], 13)
        self.assertTrue(
            all(
                "synthetic_benchmark_is_not_publishable_product_content"
                in row["publication_blockers"]
                for row in capability_audit["rows"]
            )
        )
        self.assertEqual(capability_audit["human_craft_review_completed_count"], 0)
        self.assertFalse(capability_audit["production_effect_observed"])
        self.assertFalse(capability_audit["four_a_claim_eligible"])
        self.assertFalse(capability_audit["top1_claim_eligible"])


if __name__ == "__main__":
    unittest.main()
