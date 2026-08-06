import tempfile
import unittest
from pathlib import Path

from incident_commander.agent import AgentError
from incident_commander.store import SessionStore


class SessionStoreTests(unittest.TestCase):
    def test_snapshot_survives_new_store_instance(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            first = SessionStore(root)
            first.save({"id": "session-1", "version": 1})

            second = SessionStore(root)
            self.assertEqual(second.load("session-1")["version"], 1)

    def test_corrupt_snapshot_is_quarantined(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            store = SessionStore(root)
            (root / "sessions" / "broken.json").write_text("{", encoding="utf-8")

            with self.assertRaisesRegex(AgentError, "corrupt") as error:
                store.load("broken")

            self.assertEqual(error.exception.status, 500)
            self.assertFalse((root / "sessions" / "broken.json").exists())
            self.assertTrue(list((root / "quarantine").glob("broken-*.json")))


if __name__ == "__main__":
    unittest.main()
