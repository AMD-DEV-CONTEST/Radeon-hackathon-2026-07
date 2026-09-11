from __future__ import annotations

from pathlib import Path
import unittest

from scripts.audit_grasp_memory_v3_cv_protocol import audit_protocol


PROJECT_ROOT = Path(__file__).resolve().parents[1]
PROTOCOL = PROJECT_ROOT / "configs/grasp_memory_v3_cv.toml"


class GraspMemoryV3CvProtocolTests(unittest.TestCase):
    def test_frozen_protocol_and_implementation_hashes_pass(self) -> None:
        result = audit_protocol(PROTOCOL)

        self.assertEqual(result["status"], "protocol_valid")
        self.assertEqual(result["fold_count"], 4)
        self.assertEqual(len(result["candidate_names"]), 6)
        self.assertTrue(result["development_forbidden"])
        self.assertTrue(result["holdout_forbidden"])
        self.assertFalse(result["dataset_observed"])


if __name__ == "__main__":
    unittest.main()
