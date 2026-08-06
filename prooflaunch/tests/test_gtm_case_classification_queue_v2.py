from __future__ import annotations

import copy
import unittest

from prooflaunch_remix.gtm_case_classification_queue_v2 import (
    GTMCaseClassificationQueueError,
    TASK_TEMPLATES,
    compile_case_classification_queue,
    verify_case_classification_queue,
)
from prooflaunch_remix.gtm_wave1_discovery_leads_v2 import compile_wave1_discovery_leads


def _discovery() -> dict:
    leads = [{
        "lead_id": "lead-1", "company": "Example", "provisional_subvertical_id": "b2b.industrial_climate.manufacturing",
        "discovery_rationale": "A source requiring exact classification.", "source_url": "https://example.com/case", "source_class": "official_platform",
    }]
    capture = {"content_sha256": "a" * 64, "records": [{"source_url": "https://example.com/case", "capture_status": "captured_metadata_only", "content_sha256": "b" * 64, "title": "Case"}]}
    return compile_wave1_discovery_leads(leads, capture)


class GTMCaseClassificationQueueV2Tests(unittest.TestCase):
    def test_every_lead_gets_twelve_zero_credit_tasks(self) -> None:
        payload = compile_case_classification_queue(_discovery())
        verify_case_classification_queue(payload)
        self.assertEqual(payload["tasks_per_lead"], 12)
        self.assertEqual(payload["work_item_count"], len(TASK_TEMPLATES))
        self.assertTrue(all(row["quota_credit"] == 0 for row in payload["items"]))

    def test_tampered_credit_fails_closed(self) -> None:
        payload = compile_case_classification_queue(_discovery())
        broken = copy.deepcopy(payload)
        broken["items"][0]["quota_credit"] = 1
        broken.pop("content_sha256")
        import hashlib, json
        broken["content_sha256"] = hashlib.sha256(json.dumps(broken, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()
        with self.assertRaisesRegex(GTMCaseClassificationQueueError, "minted"):
            verify_case_classification_queue(broken)


if __name__ == "__main__":
    unittest.main()
