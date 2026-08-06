import subprocess
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class ScriptEntrypointTests(unittest.TestCase):
    def test_runtime_evidence_script_can_import_project_package(self) -> None:
        result = subprocess.run(
            [sys.executable, "scripts/write-runtime-evidence.py", "--help"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Write sanitized Radeon runtime evidence", result.stdout)


if __name__ == "__main__":
    unittest.main()
