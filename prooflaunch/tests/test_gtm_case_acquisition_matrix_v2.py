from __future__ import annotations

import copy
import json
from pathlib import Path
import unittest

from prooflaunch_remix.gtm_case_acquisition_matrix_v2 import (
    GTMCaseAcquisitionMatrixError,
    build_case_acquisition_matrix,
    verify_case_acquisition_matrix,
)


ROOT = Path(__file__).resolve().parents[1]


class GTMCaseAcquisitionMatrixV2Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.standard = json.loads(
            (ROOT / "evidence/v10/gtm-case-evidence-funnel-v2/standard.json").read_text(encoding="utf-8")
        )
        cls.discovery = json.loads(
            (ROOT / "evidence/v10/gtm-gold-case-discovery-v2.json").read_text(encoding="utf-8")
        )

    def test_builds_exact_81_by_200_zero_credit_matrix(self) -> None:
        payload = build_case_acquisition_matrix(self.standard, self.discovery)
        verify_case_acquisition_matrix(payload)
        self.assertEqual(payload["slot_count"], 16_200)
        self.assertEqual(payload["query_task_count"], 48_600)
        self.assertEqual(payload["formal_candidate_count"], 0)
        self.assertEqual(payload["provisional_discovery_lead_count"], 220)
        self.assertEqual(payload["provisional_discovery_route_count"], 238)
        self.assertTrue(all(row["formal_candidate_gap"] == 200 for row in payload["subverticals"]))

    def test_every_subvertical_has_exact_marginals_and_twelve_platform_lanes(self) -> None:
        payload = build_case_acquisition_matrix(self.standard, self.discovery)
        self.assertTrue(all(sum(row["platform_search_lane_quotas"].values()) == 200 for row in payload["subverticals"]))
        self.assertTrue(all(len(row["platform_search_lane_quotas"]) == 12 for row in payload["subverticals"]))
        self.assertTrue(all(row["joint_target_profile_count"] >= 150 for row in payload["subverticals"]))

    def test_build_is_deterministic(self) -> None:
        first = build_case_acquisition_matrix(self.standard, self.discovery)
        second = build_case_acquisition_matrix(self.standard, self.discovery)
        self.assertEqual(first["content_sha256"], second["content_sha256"])
        self.assertEqual(first["slots"], second["slots"])

    def test_resealed_quota_credit_tamper_fails(self) -> None:
        payload = build_case_acquisition_matrix(self.standard, self.discovery)
        tampered = copy.deepcopy(payload)
        tampered["slots"][0]["candidate_quota_credit"] = 1
        unsigned = dict(tampered)
        unsigned.pop("content_sha256")
        import hashlib
        tampered["content_sha256"] = hashlib.sha256(
            json.dumps(unsigned, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
        ).hexdigest()
        with self.assertRaises(GTMCaseAcquisitionMatrixError):
            verify_case_acquisition_matrix(tampered)


if __name__ == "__main__":
    unittest.main()
