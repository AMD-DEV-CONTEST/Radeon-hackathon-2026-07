from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
import unittest


ROOT = Path(__file__).resolve().parent.parent


class SmokeTestScriptTests(unittest.TestCase):
    def test_unconfigured_server_requires_provider_without_writing_audit(self):
        result = subprocess.run(
            [sys.executable, "scripts/smoke_test.py"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=30,
        )

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(
            json.loads(result.stdout),
            {
                "status": "ok",
                "provider": "deterministic-local",
                "provider_required": True,
                "audit_unchanged": True,
            },
        )


if __name__ == "__main__":
    unittest.main()
