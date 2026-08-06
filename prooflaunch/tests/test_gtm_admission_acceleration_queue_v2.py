from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
import unittest

from prooflaunch_remix.gtm_admission_acceleration_queue_v2 import GTMAdmissionAccelerationQueueError, build_admission_acceleration_queue, verify_admission_acceleration_queue


ROOT = Path(__file__).resolve().parents[1]


class GTMAdmissionAccelerationQueueV2Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.ledger = json.loads((ROOT / "evidence/v10/gtm-all-subvertical-unified-review-ledger-v2.json").read_text())
        cls.queue = json.loads((ROOT / "evidence/v10/gtm-admission-acceleration-queue-v2.json").read_text())

    def test_exactly_covers_all_247_ready_packets(self) -> None:
        rebuilt = build_admission_acceleration_queue(self.ledger)
        self.assertEqual(rebuilt, self.queue)
        verify_admission_acceleration_queue(self.queue, self.ledger)
        self.assertEqual(self.queue["task_count"], 247)
        self.assertEqual(self.queue["priority_lane_counts"]["p0_high_transparency"], 10)
        self.assertEqual(self.queue["formal_candidate_quota_credit"], 0)

    def test_resealed_quota_minting_fails(self) -> None:
        broken = copy.deepcopy(self.queue)
        broken["records"][0]["formal_candidate_quota_credit"] = 1
        unsigned = dict(broken)
        unsigned.pop("content_sha256")
        broken["content_sha256"] = hashlib.sha256(json.dumps(unsigned, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        with self.assertRaises(GTMAdmissionAccelerationQueueError):
            verify_admission_acceleration_queue(broken, self.ledger)


if __name__ == "__main__":
    unittest.main()
