from __future__ import annotations

import copy
import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from prooflaunch_remix.gtm_challenger_dossier import (  # noqa: E402
    ChallengerDossierError,
    admitted_dossier_for_category,
    compile_challenger_dossiers,
    validate_challenger_admission,
)
from prooflaunch_remix.gtm_unified_offline_review import seal  # noqa: E402


LEDGER = ROOT / "evidence/v10/gtm-concrete-product-effect-pk-ledger-v1.json"
CANONICAL = ROOT / "artifacts/gtm-last-mile-pk-v1/named-product-challenger-dossiers-v3/manifest.json"


class GTMChallengerDossierTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.temporary = tempfile.TemporaryDirectory(dir=ROOT)
        cls.output = Path(cls.temporary.name) / "dossiers"
        cls.report = compile_challenger_dossiers(
            project_root=ROOT,
            ledger_path=LEDGER,
            output_root=cls.output,
        )
        cls.ledger = json.loads(LEDGER.read_text(encoding="utf-8"))

    @classmethod
    def tearDownClass(cls) -> None:
        cls.temporary.cleanup()

    def test_all_thirteen_dossiers_are_self_contained_and_deterministic(self) -> None:
        self.assertEqual(self.report["dossier_count"], 13)
        self.assertEqual(self.report["admitted_category_count"], 13)
        self.assertEqual(self.report["blocked_category_count"], 0)
        canonical = json.loads(CANONICAL.read_text(encoding="utf-8"))
        observed = {item["category_id"]: item["dossier"]["sha256"] for item in self.report["categories"]}
        expected = {item["category_id"]: item["dossier"]["sha256"] for item in canonical["categories"]}
        self.assertEqual(observed, expected)
        self.assertFalse(self.report["automatic_pairing_enabled"])
        self.assertFalse(self.report["automatic_pk_promotion_enabled"])
        self.assertFalse(self.report["four_a_quality_proven"])

    def test_source_paths_and_role_identity_are_not_exposed_in_review_html(self) -> None:
        image = next(item for item in self.report["categories"] if item["category_id"] == "image_generation_editing")
        body = (ROOT / image["dossier"]["project_relative_path"]).read_text(encoding="utf-8")
        self.assertIn("data:image/png;base64,", body)
        self.assertNotIn("prooflaunch-hero-4k.png", body)
        self.assertNotIn("evidence/v10/", body)
        self.assertNotIn("Midjourney", body)

    def test_only_materially_complete_categories_can_enter_pair_preparation(self) -> None:
        admitted = admitted_dossier_for_category(
            self.report,
            category_id="content_scheduling_operations",
            project_root=ROOT,
        )
        self.assertTrue(admitted.is_file())
        simulated = copy.deepcopy(self.report)
        cross = next(item for item in simulated["categories"] if item["category_id"] == "cross_device_memory")
        cross["named_product_pk_preparation_admitted"] = False
        cross["blocking_gap_count"] = 1
        cross["blocking_gaps"] = ["located synthetic repair regression"]
        with self.assertRaisesRegex(ChallengerDossierError, "unresolved same-brief material gaps"):
            admitted_dossier_for_category(
                simulated,
                category_id="cross_device_memory",
                project_root=ROOT,
            )

    def test_report_rejects_dossier_binding_tamper(self) -> None:
        core = copy.deepcopy(self.report)
        core.pop("content_sha256")
        core["categories"][0]["dossier"]["sha256"] = "0" * 64
        tampered = seal(core)
        with self.assertRaisesRegex(ChallengerDossierError, "dossier binding drifted"):
            validate_challenger_admission(tampered, ledger=self.ledger, project_root=ROOT)

    def test_all_located_repairs_are_present_but_do_not_establish_4a(self) -> None:
        self.assertTrue(all(item["blocking_gap_count"] == 0 for item in self.report["categories"]))
        repaired = {
            "cross_device_memory": "cross-device-memory-execution.json",
            "data_strategy_intelligence": "data-strategy-decision-memo.json",
            "product_marketing_analytics": "product-analytics-measurement-system.json",
            "seo_operations": "seo-technical-execution.json",
            "employee_agent_platforms": "employee-agent-execution-trace.json",
            "advertising_activation": "advertising-creative-system.json",
            "gtm_lifecycle_orchestration": "gtm-lifecycle-execution-dossier.json",
        }
        for category_id, filename in repaired.items():
            category = next(item for item in self.report["categories"] if item["category_id"] == category_id)
            self.assertTrue(any(item["path"].endswith(filename) for item in category["source_artifacts"]))
        self.assertFalse(self.report["four_a_quality_proven"])

    def test_claim_trial_runtime_and_caption_are_reviewable_text_evidence(self) -> None:
        video = next(item for item in self.report["categories"] if item["category_id"] == "video_generation_production")
        employee = next(item for item in self.report["categories"] if item["category_id"] == "employee_agent_platforms")
        self.assertTrue(any(item["extension"] == ".vtt" for item in video["source_artifacts"]))
        self.assertTrue(any(item["extension"] == ".mjs" for item in employee["source_artifacts"]))
        video_html = (ROOT / video["dossier"]["project_relative_path"]).read_text(encoding="utf-8")
        employee_html = (ROOT / employee["dossier"]["project_relative_path"]).read_text(encoding="utf-8")
        self.assertIn("WEBVTT", video_html)
        self.assertIn("function tryClaim", employee_html)


if __name__ == "__main__":
    unittest.main()
