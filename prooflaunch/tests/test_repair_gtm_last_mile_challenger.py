from __future__ import annotations

import unittest

from scripts.repair_gtm_last_mile_challenger import repair
from prooflaunch_remix.gtm_last_mile_diagnostic import diagnose


class RepairGTMLastMileChallengerTests(unittest.TestCase):
    def test_repair_removes_known_critical_and_major_patterns(self) -> None:
        source = {
            "integrated_gtm_strategy": {"commercial_hypothesis": "This will generate qualified leads."},
            "organic_social_copy": {"body": ["Inspect the end-to-end evidence pack. Link in bio."], "cta": "[Link]"},
            "lifecycle_email": {"body": ["Request access to the evidence pack."], "cta": "[Link to Landing Page]"},
            "geo": {"question": "Question", "direct_answer": "Answer", "entity_statement": "Leaders in North America are actively seeking solutions."},
            "analytics": {"decision_rule": "If conversion rate exceeds 1%.", "stop_rules": []},
            "cross_device_memory": {"retrieve": "Retrieve user's LinkedIn profile information.", "privacy_rule": "Adhere to all relevant data privacy regulations."},
            "content_schedule": {"days": [{"asset": "Lifecycle Email to LinkedIn Engagers", "learning_question": "Does this generate qualified leads?"}]},
            "advertising": {"test_design": "A/B test copy."},
        }
        repaired, changes = repair(source)
        report = diagnose(repaired)
        self.assertTrue(changes)
        self.assertEqual(report["critical_finding_count"], 0)
        self.assertEqual(report["major_finding_count"], 0)
        self.assertTrue(report["blind_review_admission_allowed"])


if __name__ == "__main__":
    unittest.main()
