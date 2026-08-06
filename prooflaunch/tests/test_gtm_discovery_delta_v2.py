from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
import unittest

from prooflaunch_remix.gtm_discovery_delta_v2 import (
    GTMDiscoveryDeltaError,
    build_discovery_delta,
    verify_discovery_delta,
)


ROOT = Path(__file__).resolve().parents[1]


class GTMDiscoveryDeltaV2Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.current = json.loads((ROOT / "evidence/v10/gtm-all-subvertical-discovery-pre-wave7-classification-v2.json").read_text())
        cls.baseline = json.loads((ROOT / "evidence/v10/gtm-all-subvertical-discovery-pre-wave4-v2.json").read_text())
        cls.payload = build_discovery_delta(cls.current, cls.baseline)

    def test_exact_new_url_partition_is_zero_credit(self) -> None:
        verify_discovery_delta(self.payload, self.current, self.baseline)
        self.assertEqual(self.payload["baseline_unique_lead_count"], 676)
        self.assertEqual(self.payload["current_unique_lead_count"], 1731)
        self.assertEqual(self.payload["new_unique_lead_count"], 1055)
        self.assertEqual(self.payload["formal_candidate_quota_credit"], 0)
        self.assertTrue(all(row["human_classification_required"] for row in self.payload["records"]))

    def test_resealed_lead_credit_tamper_fails(self) -> None:
        tampered = copy.deepcopy(self.payload)
        tampered["records"][0]["formal_candidate_quota_credit"] = 1
        unsigned = dict(tampered)
        unsigned.pop("content_sha256")
        tampered["content_sha256"] = hashlib.sha256(
            json.dumps(unsigned, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
        ).hexdigest()
        with self.assertRaises(GTMDiscoveryDeltaError):
            verify_discovery_delta(tampered, self.current, self.baseline)


if __name__ == "__main__":
    unittest.main()
