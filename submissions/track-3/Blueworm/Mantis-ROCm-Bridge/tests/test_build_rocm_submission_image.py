from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class BuildRocmSubmissionImageTests(unittest.TestCase):
    def test_supervisor_has_no_clobber_and_claim_boundary(self) -> None:
        source = (ROOT / "tools/build_rocm_submission_image.py").read_text(
            encoding="utf-8"
        )
        self.assertIn("evidence path already exists", source)
        self.assertIn("saved image path already exists", source)
        self.assertIn("base_image_transport_override", source)
        self.assertIn("BASE_IMAGE=", source)
        self.assertIn("COMPLETE_BUILD_PROVENANCE", source)
        self.assertIn("strict_rocm_runtime_verified", source)
        self.assertIn("This does not prove", source)
        self.assertIn("final_evidence.SHA256SUMS", source)


if __name__ == "__main__":
    unittest.main()
