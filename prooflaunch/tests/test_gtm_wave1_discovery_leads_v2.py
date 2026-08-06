from __future__ import annotations

import copy
import unittest

from prooflaunch_remix.gtm_wave1_discovery_leads_v2 import (
    GTMWave1DiscoveryLeadError,
    compile_wave1_discovery_leads,
    verify_wave1_discovery_leads,
)


class GTMWave1DiscoveryLeadV2Tests(unittest.TestCase):
    def _capture(self) -> dict:
        return {"content_sha256": "a" * 64, "records": [{
            "source_url": "https://example.com/case",
            "capture_status": "captured_metadata_only",
            "content_sha256": "b" * 64,
            "title": "Example case",
        }]}

    def _lead(self) -> dict:
        return {
            "lead_id": "lead-1",
            "company": "Example",
            "provisional_subvertical_id": "b2b.industrial_climate.manufacturing",
            "discovery_rationale": "A public case lead that still requires exact classification.",
            "source_url": "https://example.com/case",
            "source_class": "official_platform",
        }

    def test_captured_discovery_lead_stays_zero_credit(self) -> None:
        payload = compile_wave1_discovery_leads([self._lead()], self._capture())
        verify_wave1_discovery_leads(payload)
        self.assertEqual(payload["captured_lead_count"], 1)
        self.assertEqual(payload["records"][0]["quota_credit"], 0)
        self.assertEqual(payload["records"][0]["budget_status"], "unresolved")

    def test_duplicate_url_fails_closed(self) -> None:
        second = {**self._lead(), "lead_id": "lead-2"}
        with self.assertRaisesRegex(GTMWave1DiscoveryLeadError, "URL"):
            compile_wave1_discovery_leads([self._lead(), second], self._capture())

    def test_tampered_credit_fails_closed(self) -> None:
        payload = compile_wave1_discovery_leads([self._lead()], self._capture())
        tampered = copy.deepcopy(payload)
        tampered["records"][0]["quota_credit"] = 1
        tampered.pop("content_sha256")
        import hashlib, json
        tampered["content_sha256"] = hashlib.sha256(json.dumps(tampered, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()
        with self.assertRaisesRegex(GTMWave1DiscoveryLeadError, "quota"):
            verify_wave1_discovery_leads(tampered)


if __name__ == "__main__":
    unittest.main()
