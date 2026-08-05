import unittest

from scripts.stability_check import run_stability_check


class StabilityCheckTests(unittest.TestCase):
    def test_repeated_local_workflow_preserves_memory_and_exposes_failure(self):
        result = run_stability_check(iterations=5)

        self.assertTrue(result["software_only"])
        self.assertEqual(result["iterations"], 5)
        self.assertEqual(result["successful_requests"], 5)
        self.assertEqual(result["provider_failures_visible"], 1)
        self.assertEqual(result["silent_fallbacks"], 0)
        self.assertTrue(result["memory_persisted"])
        self.assertEqual(result["audit_entries"], 6)
        self.assertTrue(result["all_passed"])

    def test_rejects_non_positive_iteration_count(self):
        with self.assertRaisesRegex(ValueError, "positive"):
            run_stability_check(iterations=0)


if __name__ == "__main__":
    unittest.main()
