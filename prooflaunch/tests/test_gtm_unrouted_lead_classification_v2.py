from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
import unittest

from prooflaunch_remix.gtm_unrouted_lead_classifier_v2 import (
    GTMUnroutedLeadClassificationError,
    classify_unrouted_leads,
    verify_unrouted_lead_classification,
)


ROOT = Path(__file__).resolve().parents[1]


class GTMUnroutedLeadClassificationV2Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.discovery = json.loads((ROOT / "evidence/v10/gtm-all-subvertical-discovery-pre-wave4-v2.json").read_text())
        cls.capture = json.loads((ROOT / "evidence/v10/gtm-all-subvertical-wave4-unrouted-public-capture-v2.json").read_text())
        ontology = json.loads((ROOT / "evidence/v10/gtm-subvertical-ontology-v1.json").read_text())
        cls.allowed = {row["subvertical_id"] for row in ontology["subverticals"]}
        cls.payload = json.loads((ROOT / "evidence/v10/gtm-unrouted-lead-classification-v2.json").read_text())

    def test_partitions_every_unrouted_lead_without_credit(self) -> None:
        rebuilt = classify_unrouted_leads(self.discovery, self.allowed, self.capture)
        verify_unrouted_lead_classification(rebuilt, self.discovery, self.allowed, self.capture)
        self.assertEqual(rebuilt, self.payload)
        self.assertEqual(rebuilt["unrouted_input_count"], 372)
        self.assertEqual(rebuilt["provisional_route_suggestion_count"], 31)
        self.assertEqual(rebuilt["classification_gap_count"], 341)
        self.assertEqual(rebuilt["formal_candidate_quota_credit"], 0)

    def test_public_capture_is_bounded_and_nearly_complete(self) -> None:
        self.assertEqual(self.capture["requested_unique_source_count"], 372)
        self.assertEqual(self.capture["status_counts"]["captured_metadata_only"], 368)
        self.assertEqual(self.capture["status_counts"]["capture_failed"], 4)
        self.assertTrue(all(row["raw_page_retained"] is False for row in self.capture["records"]))
        self.assertTrue(all(row["authentication_used"] is False for row in self.capture["records"]))
        self.assertTrue(all(row["captcha_bypass_used"] is False for row in self.capture["records"]))
        self.assertTrue(all(row["paywall_bypass_used"] is False for row in self.capture["records"]))

    def test_every_suggestion_has_one_captured_explainable_route(self) -> None:
        capture_by_url = {row["source_url"]: row for row in self.capture["records"]}
        for row in self.payload["records"]:
            self.assertEqual(len(row["provisional_subvertical_ids"]), 1)
            self.assertIn(row["provisional_subvertical_ids"][0], self.allowed)
            self.assertEqual(capture_by_url[row["source_url"]]["capture_status"], "captured_metadata_only")
            self.assertEqual(row["routing_capture_sha256"], capture_by_url[row["source_url"]]["content_sha256"])
            self.assertTrue(row["routing_evidence_terms"])
            self.assertTrue(row["human_classification_required"])
            self.assertEqual(row["formal_candidate_quota_credit"], 0)

    def test_known_substring_and_mechanism_false_routes_remain_gaps(self) -> None:
        routes = {row["company"]: row["provisional_subvertical_ids"][0] for row in self.payload["records"]}
        for company in ("Paytrail", "Lucanet", "Peakflo", "Apps Without Code", "Marq", "TimeLog"):
            self.assertNotIn(company, routes)
        self.assertEqual(routes["Triage Staffing"], "b2b.professional_services.managed_and_field_services")
        self.assertEqual(routes["Fresha"], "b2b.b2b_saas.vertical_saas")

    def test_capture_failure_and_ambiguous_leads_never_route(self) -> None:
        suggested = {row["lead_id"] for row in self.payload["records"]}
        rejected = {row["lead_id"]: row for row in self.payload["rejected_records"]}
        failed_urls = {row["source_url"] for row in self.capture["records"] if row["capture_status"] != "captured_metadata_only"}
        source = {row["lead_id"]: row for row in self.discovery["records"]}
        self.assertTrue(failed_urls)
        self.assertTrue(all(source[lead_id]["source_url"] not in failed_urls for lead_id in suggested))
        self.assertTrue(any(row["status"] == "public_capture_gap" for row in rejected.values()))

    def test_resealed_credit_or_route_tamper_fails(self) -> None:
        tampered = copy.deepcopy(self.payload)
        tampered["records"][0]["formal_candidate_quota_credit"] = 1
        unsigned = dict(tampered)
        unsigned.pop("content_sha256")
        tampered["content_sha256"] = hashlib.sha256(
            json.dumps(unsigned, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        with self.assertRaises(GTMUnroutedLeadClassificationError):
            verify_unrouted_lead_classification(tampered, self.discovery, self.allowed, self.capture)


if __name__ == "__main__":
    unittest.main()
