from __future__ import annotations

import hashlib
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "build_runtime_license_bundle.sh"


class RuntimeLicenseBundleTests(unittest.TestCase):
    def test_bundle_contains_project_and_runtime_module_licenses(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "licenses"
            subprocess.run(
                ["sh", str(SCRIPT), str(output)],
                cwd=ROOT,
                check=True,
                capture_output=True,
                text=True,
            )

            for name in ("LICENSE", "NOTICE", "THIRD_PARTY_NOTICES.md"):
                generated = output / "project" / name
                self.assertTrue(generated.is_file())
                self.assertEqual(generated.read_bytes(), (ROOT / name).read_bytes())

            inventory = (output / "GO_MODULES.tsv").read_text(encoding="utf-8").splitlines()
            self.assertGreaterEqual(len(inventory), 30)
            self.assertEqual(inventory, sorted(inventory))

            for row in inventory:
                module, safe_module = row.split("\t")
                self.assertTrue(module)
                files = list((output / "go-modules" / safe_module).iterdir())
                self.assertTrue(files)
                self.assertTrue(all(path.is_file() and path.stat().st_size > 0 for path in files))

            sums = (output / "SHA256SUMS").read_text(encoding="utf-8").splitlines()
            self.assertTrue(sums)
            for row in sums:
                expected, relative = row.split("  ", 1)
                payload = (output / relative.removeprefix("./")).read_bytes()
                self.assertEqual(hashlib.sha256(payload).hexdigest(), expected)

    def test_bundle_rejects_missing_output_argument(self) -> None:
        result = subprocess.run(
            ["sh", str(SCRIPT)],
            cwd=ROOT,
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 2)
        self.assertIn("usage:", result.stderr)

    def test_bundle_rejects_relative_output_directory(self) -> None:
        result = subprocess.run(
            ["sh", str(SCRIPT), "relative-output"],
            cwd=ROOT,
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 2)
        self.assertIn("absolute", result.stderr)

    def test_bundle_rejects_nonempty_output_directory(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "licenses"
            output.mkdir()
            (output / "sentinel").write_text("preserve", encoding="utf-8")
            result = subprocess.run(
                ["sh", str(SCRIPT), str(output)],
                cwd=ROOT,
                capture_output=True,
                text=True,
            )
            self.assertEqual(result.returncode, 2)
            self.assertIn("empty", result.stderr)
            self.assertEqual((output / "sentinel").read_text(encoding="utf-8"), "preserve")

    def test_bundle_rejects_symlink_output_directory(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / "target"
            target.mkdir()
            output = root / "licenses"
            output.symlink_to(target, target_is_directory=True)
            result = subprocess.run(
                ["sh", str(SCRIPT), str(output)],
                cwd=ROOT,
                capture_output=True,
                text=True,
            )
            self.assertEqual(result.returncode, 2)
            self.assertIn("symbolic link", result.stderr)


if __name__ == "__main__":
    unittest.main()
