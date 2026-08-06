from __future__ import annotations

import hashlib
import io
import json
import unittest
from zipfile import ZipFile

from prooflaunch_remix.gtm_production_observation_kit import (
    ProductionObservationKitError,
    compile_production_observation_field_kit,
)


class ProductionObservationFieldKitTests(unittest.TestCase):
    def test_kit_is_deterministic_bound_and_credential_free(self) -> None:
        experiment = {
            "schema": "fixture",
            "attribution": {
                "experiment_id": "experiment-fixture-001",
                "utm_source": "linkedin",
                "utm_medium": "organic",
                "utm_campaign": "campaign-fixture-001",
                "utm_content": "hero-deadbeef",
            },
            "metrics": [
                {"metric": "qualified_action_rate", "minimum_sample": 125},
                {"metric": "evidence_engagement_rate", "minimum_sample": 200},
            ],
        }
        kwargs = {
            "run_id": "run-0123456789abcdef01234567",
            "campaign_id": "campaign-fixture-001",
            "product_name": "Fixture product",
            "experiment": experiment,
            "strategy_plan_sha256": "a" * 64,
            "budget_contract": "zero",
            "generated_at": "2026-08-02T00:00:00Z",
        }
        first, first_manifest = compile_production_observation_field_kit(**kwargs)
        second, second_manifest = compile_production_observation_field_kit(**kwargs)
        self.assertEqual(first, second)
        self.assertEqual(first_manifest, second_manifest)
        self.assertTrue(first.startswith(b"PK"))
        with ZipFile(io.BytesIO(first)) as archive:
            self.assertEqual(
                archive.namelist(),
                sorted(
                    [
                        "README.md",
                        "attribution-plan.json",
                        "attribution-tags.csv",
                        "binding.json",
                        "capture.html",
                        "economics-template.json",
                        "experiment.json",
                        "manifest.json",
                        "metrics-template.csv",
                        "observation-template.json",
                    ]
                ),
            )
            manifest = json.loads(archive.read("manifest.json"))
            binding = json.loads(archive.read("binding.json"))
            attribution = json.loads(archive.read("attribution-plan.json"))
            attribution_tags = archive.read("attribution-tags.csv").decode("utf-8")
            capture = archive.read("capture.html").decode("utf-8")
            all_bytes = b"".join(archive.read(name) for name in archive.namelist())
        self.assertEqual(binding["registered_minimum_sample"], 200)
        self.assertTrue(binding["zero_budget"])
        self.assertEqual(binding["strategy_plan_sha256"], "a" * 64)
        attribution_core = {
            key: value
            for key, value in attribution.items()
            if key != "attribution_plan_sha256"
        }
        self.assertEqual(
            attribution["attribution_plan_sha256"],
            hashlib.sha256(
                (
                    json.dumps(
                        attribution_core,
                        ensure_ascii=False,
                        sort_keys=True,
                        indent=2,
                        allow_nan=False,
                    )
                    + "\n"
                ).encode("utf-8")
            ).hexdigest(),
        )
        self.assertEqual(
            binding["attribution_plan_sha256"],
            attribution["attribution_plan_sha256"],
        )
        self.assertEqual(attribution["arms"]["candidate"]["pl_arm"], "candidate")
        self.assertEqual(attribution["arms"]["baseline"]["pl_arm"], "baseline")
        self.assertNotEqual(
            attribution["arms"]["candidate"]["utm_content"],
            attribution["arms"]["baseline"]["utm_content"],
        )
        self.assertEqual(
            {item["aggregate_metric"] for item in attribution["event_taxonomy"]},
            {
                "eligible_reach",
                "qualified_actions",
                "evidence_engagements",
                "complaints",
                "conversions",
            },
        )
        self.assertIn("user_id", attribution["prohibited_export_fields"])
        self.assertFalse(attribution["person_level_export_allowed"])
        self.assertFalse(attribution["tracking_pixel_included"])
        self.assertIn("candidate,linkedin,organic", attribution_tags)
        self.assertIn("baseline,linkedin,organic", attribution_tags)
        self.assertFalse(manifest["source_files_included"])
        self.assertFalse(manifest["credentials_included"])
        self.assertTrue(manifest["human_submission_required"])
        self.assertIn('crypto.subtle.digest("SHA-256"', capture)
        self.assertIn("connect-src 'none'", capture)
        self.assertIn("attribution-tags.csv", capture)
        self.assertIn("file not uploaded", capture)
        self.assertNotIn("fetch(", capture)
        self.assertNotIn(b"X-ProofLaunch-Approval-Token", all_bytes)
        self.assertNotIn(b"Authorization: Bearer", all_bytes)
        self.assertEqual(len(hashlib.sha256(first).hexdigest()), 64)

    def test_unsafe_or_incomplete_attribution_fails_before_html_generation(self) -> None:
        experiment = {
            "attribution": {
                "experiment_id": "experiment-fixture-001",
                "utm_source": "linkedin<script>",
                "utm_medium": "organic",
                "utm_campaign": "campaign-fixture-001",
                "utm_content": "hero-deadbeef",
            },
            "metrics": [
                {"metric": "qualified_action_rate", "minimum_sample": 125}
            ],
        }
        with self.assertRaisesRegex(
            ProductionObservationKitError, "attribution.utm_source is invalid"
        ):
            compile_production_observation_field_kit(
                run_id="run-0123456789abcdef01234567",
                campaign_id="campaign-fixture-001",
                product_name="Fixture product",
                experiment=experiment,
                strategy_plan_sha256="a" * 64,
                budget_contract="zero",
                generated_at="2026-08-02T00:00:00Z",
            )


if __name__ == "__main__":
    unittest.main()
