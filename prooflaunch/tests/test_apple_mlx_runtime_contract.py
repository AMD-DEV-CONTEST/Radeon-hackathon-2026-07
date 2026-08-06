from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import tempfile
import tomllib
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class AppleMLXRuntimeContractTests(unittest.TestCase):
    def test_project_declares_reproducible_apple_local_runtime(self) -> None:
        project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
        dependencies = project["project"]["dependencies"]
        for pin in (
            "huggingface-hub==1.26.0",
            "mlx==0.32.0",
            "mlx-lm==0.31.3",
            "transformers==5.14.1",
        ):
            matches = [item for item in dependencies if item.startswith(pin + ";")]
            self.assertEqual(len(matches), 1, pin)
            self.assertIn("sys_platform == 'darwin'", matches[0])
            self.assertIn("platform_machine == 'arm64'", matches[0])

    def test_preflight_imports_mlx_lm_entrypoint(self) -> None:
        source = (ROOT / "scripts/verify_apple_mlx_runtime.py").read_text(
            encoding="utf-8"
        )
        self.assertIn("import mlx_lm", source)
        self.assertIn('getattr(mlx_lm, "load", None)', source)

    def test_preflight_can_check_package_contract_without_opening_metal(self) -> None:
        completed = subprocess.run(
            [
                sys.executable,
                str(ROOT / "scripts/verify_apple_mlx_runtime.py"),
                "--skip-metal",
            ],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertIn("ProofLaunchAppleMLXRuntimePreflightV1", completed.stdout)
        self.assertIn(completed.returncode, {0, 2})

    def test_preflight_can_seal_an_in_project_receipt(self) -> None:
        with tempfile.TemporaryDirectory(dir=ROOT) as temporary:
            output = Path(temporary) / "preflight.json"
            completed = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "scripts/verify_apple_mlx_runtime.py"),
                    "--skip-metal",
                    "--output",
                    str(output),
                ],
                cwd=ROOT,
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertIn(completed.returncode, {0, 2})
            payload = json.loads(output.read_text(encoding="utf-8"))
            unsigned = dict(payload)
            supplied = unsigned.pop("content_sha256")
            expected = hashlib.sha256(
                json.dumps(
                    unsigned,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                    allow_nan=False,
                )
                .encode("utf-8")
            ).hexdigest()
            self.assertEqual(supplied, expected)


if __name__ == "__main__":
    unittest.main()
