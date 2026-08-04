import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from privateops.memory import LocalMemory


class MemoryTests(unittest.TestCase):
    def test_failed_replacement_preserves_previous_state(self):
        with tempfile.TemporaryDirectory() as tmp:
            memory = LocalMemory(tmp)
            memory.update({"demo_focus": "audit"})

            with patch.object(Path, "replace", side_effect=OSError("disk interruption")):
                with self.assertRaisesRegex(OSError, "disk interruption"):
                    memory.update({"model": "Qwen"})

            self.assertEqual(memory.load(), {"demo_focus": "audit"})


if __name__ == "__main__":
    unittest.main()
