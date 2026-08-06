from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
import unittest

from prooflaunch_remix.gtm_all_subvertical_discovery_v2 import (
    GTMAllSubverticalDiscoveryError,
    build_all_subvertical_discovery,
    verify_all_subvertical_discovery,
)


ROOT = Path(__file__).resolve().parents[1]


class GTMAllSubverticalDiscoveryV2Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.standard = json.loads((ROOT / "evidence/v10/gtm-case-evidence-funnel-v2/standard.json").read_text())
        cls.acquisition = json.loads((ROOT / "evidence/v10/gtm-case-acquisition-matrix-v2.json").read_text())
        cls.gold = json.loads((ROOT / "evidence/v10/gtm-gold-case-discovery-v2.json").read_text())
        source_path = ROOT / "data/gtm_case_funnel_v2/all-subvertical-public-leads-wave1-v2.json"
        wave2_path = ROOT / "data/gtm_case_funnel_v2/all-subvertical-public-leads-wave2-b2b-v2.json"
        wave3_path = ROOT / "data/gtm_case_funnel_v2/all-subvertical-public-leads-wave3-b2c-v2.json"
        wave4_path = ROOT / "data/gtm_case_funnel_v2/all-subvertical-public-leads-wave4-classified-v2.json"
        wave5_path = ROOT / "data/gtm_case_funnel_v2/all-subvertical-public-leads-wave5-indexes-v2.json"
        wave5_rendered_path = ROOT / "data/gtm_case_funnel_v2/all-subvertical-public-leads-wave5-rendered-indexes-v2.json"
        wave6_path = ROOT / "data/gtm_case_funnel_v2/all-subvertical-public-leads-wave6-sitemaps-v2.json"
        wave7_path = ROOT / "data/gtm_case_funnel_v2/all-subvertical-public-leads-wave7-classified-v2.json"
        wave8_path = ROOT / "data/gtm_case_funnel_v2/high-transparency-public-leads-wave8-v2.json"
        cls.wave = json.loads(source_path.read_text())
        cls.wave2 = json.loads(wave2_path.read_text())
        cls.wave3 = json.loads(wave3_path.read_text())
        cls.wave4 = json.loads(wave4_path.read_text())
        cls.wave5 = json.loads(wave5_path.read_text())
        cls.wave5_rendered = json.loads(wave5_rendered_path.read_text())
        cls.wave6 = json.loads(wave6_path.read_text())
        cls.wave7 = json.loads(wave7_path.read_text())
        cls.wave8 = json.loads(wave8_path.read_text())
        cls.payload = build_all_subvertical_discovery(
            cls.standard,
            cls.acquisition,
            cls.gold,
            [
                (str(source_path.relative_to(ROOT)), cls.wave["records"]),
                (str(wave2_path.relative_to(ROOT)), cls.wave2["records"]),
                (str(wave3_path.relative_to(ROOT)), cls.wave3["records"]),
                (str(wave4_path.relative_to(ROOT)), cls.wave4["records"]),
                (str(wave5_path.relative_to(ROOT)), cls.wave5["records"]),
                (str(wave5_rendered_path.relative_to(ROOT)), cls.wave5_rendered["records"]),
                (str(wave6_path.relative_to(ROOT)), cls.wave6["records"]),
                (str(wave7_path.relative_to(ROOT)), cls.wave7["records"]),
                (str(wave8_path.relative_to(ROOT)), cls.wave8["records"]),
            ],
        )

    def test_compiles_cross_81_discovery_without_candidate_credit(self) -> None:
        verify_all_subvertical_discovery(self.payload)
        self.assertEqual(len(self.payload["subverticals"]), 81)
        self.assertEqual(self.payload["formal_candidate_count"], 0)
        self.assertEqual(self.payload["formal_candidate_gap"], 16_200)
        self.assertTrue(all(row["formal_candidate_gap"] == 200 for row in self.payload["subverticals"]))

    def test_new_professional_service_routes_are_preserved(self) -> None:
        counts = {row["subvertical_id"]: row["provisional_discovery_route_count"] for row in self.payload["subverticals"]}
        self.assertGreaterEqual(counts["b2b.professional_services.legal_accounting"], 5)
        self.assertGreaterEqual(counts["b2b.professional_services.managed_and_field_services"], 1)

    def test_wave_two_establishes_a_provisional_route_for_every_b2b_subvertical(self) -> None:
        b2b = [row for row in self.payload["subverticals"] if row["business_model"] == "b2b"]
        self.assertEqual(len(b2b), 41)
        self.assertTrue(all(row["provisional_discovery_route_count"] >= 1 for row in b2b))
        self.assertTrue(all(row["formal_candidate_count"] == 0 for row in b2b))

    def test_wave_three_establishes_a_provisional_route_for_all_eighty_one_subverticals(self) -> None:
        self.assertEqual(self.payload["subverticals_with_provisional_routes"], 81)
        self.assertEqual(self.payload["subverticals_without_provisional_routes"], 0)
        self.assertTrue(all(row["provisional_discovery_route_count"] >= 1 for row in self.payload["subverticals"]))
        self.assertTrue(all(row["formal_candidate_count"] == 0 for row in self.payload["subverticals"]))

    def test_waves_four_to_eight_deepen_discovery_without_minting_credit(self) -> None:
        self.assertEqual(self.payload["unique_discovery_lead_count"], 1741)
        self.assertEqual(self.payload["provisionally_routed_lead_count"], 382)
        self.assertEqual(self.payload["provisional_route_assignment_count"], 401)
        self.assertEqual(self.payload["formal_candidate_count"], 0)

    def test_canonical_url_deduplication_merges_routes(self) -> None:
        duplicate = copy.deepcopy(self.wave["records"][0])
        duplicate["source_url"] += "/#fragment"
        duplicate["provisional_subvertical_ids"] = ["b2b.industrial_climate.manufacturing"]
        payload = build_all_subvertical_discovery(
            self.standard,
            self.acquisition,
            self.gold,
            [("fixture", [*self.wave["records"], duplicate])],
        )
        verify_all_subvertical_discovery(payload)
        matches = [row for row in payload["records"] if "seo-case-study-cnc" in row["source_url"]]
        self.assertEqual(len(matches), 1)
        self.assertEqual(len(matches[0]["provisional_subvertical_ids"]), 2)

    def test_duplicate_enrichment_preserves_resolved_company_and_capture_bound_excerpt(self) -> None:
        base = copy.deepcopy(self.wave5["records"][0])
        enriched = copy.deepcopy(base)
        enriched["company"] = "Named Example"
        enriched["title"] = "Named Example public customer story with exact subject metadata"
        enriched["source_excerpt"] = "Capture-bound high-precision subject classification evidence."
        enriched["directory_industry"] = "public_case_metadata_strong_subject_phrase"
        enriched["provisional_subvertical_ids"] = ["b2c.beauty_fashion.beauty"]
        payload = build_all_subvertical_discovery(
            self.standard,
            self.acquisition,
            self.gold,
            [("base", [base]), ("enriched", [enriched])],
        )
        verify_all_subvertical_discovery(payload)
        row = next(item for item in payload["records"] if item["source_url"] == base["source_url"].rstrip("/"))
        self.assertEqual(row["company"], "Named Example")
        self.assertEqual(row["directory_industry"], "public_case_metadata_strong_subject_phrase")
        self.assertIn("Capture-bound", row["source_excerpt"])

    def test_resealed_quota_credit_tamper_fails(self) -> None:
        tampered = copy.deepcopy(self.payload)
        tampered["records"][0]["formal_candidate_quota_credit"] = 1
        unsigned = dict(tampered)
        unsigned.pop("content_sha256")
        tampered["content_sha256"] = hashlib.sha256(
            json.dumps(unsigned, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
        ).hexdigest()
        with self.assertRaises(GTMAllSubverticalDiscoveryError):
            verify_all_subvertical_discovery(tampered)


if __name__ == "__main__":
    unittest.main()
