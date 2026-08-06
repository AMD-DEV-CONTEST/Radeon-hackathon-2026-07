from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from mantis_rocm_bridge.contracts import ContractError
from mantis_rocm_bridge.ops import begin_run, finish_run, get_run_status


class RunMarkerTests(unittest.TestCase):
    def test_markers_are_idempotent_and_non_overwriting(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            self.assertEqual(get_run_status(root, "eval-001"), "missing")
            begin_run(root, "eval-001", {"git_revision": "abc"})
            self.assertEqual(get_run_status(root, "eval-001"), "started")
            with self.assertRaises(ContractError):
                begin_run(root, "eval-001", {"git_revision": "different"})
            finish_run(root, "eval-001", "completed", {"episodes": 10})
            self.assertEqual(get_run_status(root, "eval-001"), "completed")
            with self.assertRaises(ContractError):
                finish_run(root, "eval-001", "failed")
            self.assertTrue((Path(root) / "eval-001" / "started.json").is_file())

    def test_terminal_marker_requires_start(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            with self.assertRaises(ContractError):
                finish_run(root, "eval-002", "failed")


if __name__ == "__main__":
    unittest.main()

