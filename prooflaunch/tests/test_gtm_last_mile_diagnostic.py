from __future__ import annotations

import unittest

from prooflaunch_remix.gtm_last_mile_diagnostic import diagnose


class GTMLastMileDiagnosticTests(unittest.TestCase):
    def test_unsafe_generated_challenger_is_blocked(self) -> None:
        report = diagnose(
            {
                "geo": {"claim": "Leaders in North America are actively seeking solutions."},
                "cross_device_memory": {"retrieve": "Retrieve user's LinkedIn profile information."},
                "content_schedule": {"asset": "Lifecycle Email to LinkedIn Engagers"},
                "integrated_gtm_strategy": {"claim": "This will generate qualified leads."},
            }
        )
        self.assertGreaterEqual(report["critical_finding_count"], 4)
        self.assertFalse(report["blind_review_admission_allowed"])
        self.assertFalse(report["automatic_promotion_allowed"])

    def test_clean_mechanical_result_never_becomes_aesthetic_proof(self) -> None:
        report = diagnose({"organic_social_copy": {"hook": "Inspect the proof boundary."}})
        self.assertEqual(report["critical_finding_count"], 0)
        self.assertTrue(report["blind_review_admission_allowed"])
        self.assertFalse(report["aesthetic_score_assigned"])
        self.assertFalse(report["automatic_promotion_allowed"])


if __name__ == "__main__":
    unittest.main()
