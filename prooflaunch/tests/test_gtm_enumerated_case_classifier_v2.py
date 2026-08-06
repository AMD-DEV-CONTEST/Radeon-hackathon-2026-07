from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
import unittest

from prooflaunch_remix.gtm_enumerated_case_classifier_v2 import (
    GTMEnumeratedCaseClassificationError,
    classify_enumerated_cases,
    verify_enumerated_case_classification,
)


ROOT = Path(__file__).resolve().parents[1]


class GTMEnumeratedCaseClassifierV2Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.delta = json.loads((ROOT / "evidence/v10/gtm-public-case-enumeration-delta-v2.json").read_text())
        cls.capture = json.loads((ROOT / "evidence/v10/gtm-all-subvertical-wave7-enumerated-public-capture-v2.json").read_text())
        ontology = json.loads((ROOT / "evidence/v10/gtm-subvertical-ontology-v1.json").read_text())
        cls.allowed = {row["subvertical_id"] for row in ontology["subverticals"]}
        cls.payload = classify_enumerated_cases(cls.delta, cls.capture, cls.allowed)

    def test_live_batch_is_fully_partitioned_and_zero_credit(self) -> None:
        verify_enumerated_case_classification(self.payload, self.delta, self.capture, self.allowed)
        self.assertEqual(self.payload["input_count"], 1055)
        self.assertEqual(
            self.payload["provisional_route_suggestion_count"] + self.payload["classification_gap_count"],
            1055,
        )
        self.assertGreaterEqual(self.payload["provisional_route_suggestion_count"], 35)
        self.assertGreaterEqual(self.payload["represented_subvertical_count"], 15)
        self.assertEqual(self.payload["formal_candidate_quota_credit"], 0)

    def test_generic_vendor_nouns_do_not_route_without_subject_phrase(self) -> None:
        gap_urls = {row["source_url"] for row in self.payload["rejected_records"]}
        self.assertIn("https://stripe.com/customers/me-and-u-ttpoi", gap_urls)
        self.assertIn("https://stripe.com/customers/intercom", gap_urls)
        self.assertIn("https://stripe.com/customers/lg-electronics", gap_urls)
        self.assertIn("https://stripe.com/customers/cny-fertility", gap_urls)
        self.assertIn("https://stripe.com/customers/swimming-australia", gap_urls)

    def test_resealed_route_credit_tamper_fails(self) -> None:
        self.assertTrue(self.payload["records"])
        tampered = copy.deepcopy(self.payload)
        tampered["records"][0]["formal_candidate_quota_credit"] = 1
        unsigned = dict(tampered)
        unsigned.pop("content_sha256")
        tampered["content_sha256"] = hashlib.sha256(
            json.dumps(unsigned, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
        ).hexdigest()
        with self.assertRaises(GTMEnumeratedCaseClassificationError):
            verify_enumerated_case_classification(tampered, self.delta, self.capture, self.allowed)


if __name__ == "__main__":
    unittest.main()
