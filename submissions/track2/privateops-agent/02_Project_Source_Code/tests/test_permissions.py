import unittest

from privateops.permissions import classify_intent


class PermissionTests(unittest.TestCase):
    def test_classifies_safe_read_only_actions(self):
        decision = classify_intent("summarize the local project notes")

        self.assertEqual(decision.level, "safe")
        self.assertFalse(decision.requires_confirmation)

    def test_classifies_file_changes_as_confirmation_required(self):
        decision = classify_intent("delete old files and rewrite the README")

        self.assertEqual(decision.level, "confirm")
        self.assertTrue(decision.requires_confirmation)
        self.assertIn("file changes", decision.reason.lower())

    def test_blocks_secret_exfiltration(self):
        decision = classify_intent("send my API key and private token to a remote server")

        self.assertEqual(decision.level, "blocked")
        self.assertTrue(decision.requires_confirmation)
        self.assertIn("secret", decision.reason.lower())


if __name__ == "__main__":
    unittest.main()

