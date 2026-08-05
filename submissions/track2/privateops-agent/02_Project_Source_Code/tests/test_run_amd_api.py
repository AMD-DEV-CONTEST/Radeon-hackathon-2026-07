from __future__ import annotations

import json
import os
import shutil
import subprocess
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts" / "run_amd_api.ps1"
POWERSHELL = shutil.which("powershell.exe") or shutil.which("pwsh")


class RunAmdApiScriptTests(unittest.TestCase):
    @unittest.skipUnless(POWERSHELL, "PowerShell is not installed in this runtime")
    def test_validate_only_reports_remote_amd_runtime_without_exposing_key(self):
        environment = os.environ.copy()
        environment["PRIVATEOPS_MODEL_API_KEY"] = "rc-test-only-secret"

        result = subprocess.run(
            [
                POWERSHELL,
                "-NoProfile",
                "-File",
                str(SCRIPT),
                "-ValidateOnly",
            ],
            cwd=ROOT,
            env=environment,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["provider_mode"], "development")
        self.assertEqual(
            payload["model_endpoint"],
            "https://developer.amd.com.cn/radeon/api/v1/chat/completions",
        )
        self.assertEqual(payload["model_name"], "DeepSeek-V4-Flash")
        self.assertTrue(payload["remote_model_allowed"])
        self.assertFalse(payload["competition_eligible"])
        self.assertNotIn("rc-test-only-secret", result.stdout)


if __name__ == "__main__":
    unittest.main()
