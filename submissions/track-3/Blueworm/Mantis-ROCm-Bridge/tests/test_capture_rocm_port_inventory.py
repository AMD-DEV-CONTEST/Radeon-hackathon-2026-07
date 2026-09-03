from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tools import capture_rocm_port_inventory


class RocmPortInventoryTests(unittest.TestCase):
    def test_missing_command_is_recorded_without_raising(self) -> None:
        result = capture_rocm_port_inventory._run(
            ["wp005-command-that-does-not-exist"]
        )
        self.assertEqual(result["argv"], ["wp005-command-that-does-not-exist"])
        self.assertEqual(result["error_type"], "FileNotFoundError")

    def test_main_writes_exclusively_and_preserves_existing_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "inventory.json"
            inventory = {
                "schema_version": 1,
                "kind": "wp_rocm_native_inventory",
            }
            argv = [
                "capture_rocm_port_inventory.py",
                "--output",
                str(output),
            ]
            with (
                mock.patch.object(sys, "argv", argv),
                mock.patch.object(
                    capture_rocm_port_inventory,
                    "capture",
                    return_value=inventory,
                ) as capture_mock,
            ):
                self.assertEqual(capture_rocm_port_inventory.main(), 0)
                self.assertEqual(json.loads(output.read_text()), inventory)
                self.assertEqual(capture_rocm_port_inventory.main(), 2)
                self.assertEqual(json.loads(output.read_text()), inventory)
                capture_mock.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
