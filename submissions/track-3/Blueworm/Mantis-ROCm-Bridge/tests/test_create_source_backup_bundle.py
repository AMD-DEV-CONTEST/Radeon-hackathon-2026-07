from __future__ import annotations

import json
import tarfile
import tempfile
import unittest
from pathlib import Path

from tools.create_source_backup_bundle import create_bundle, inventory


class SourceBackupBundleTests(unittest.TestCase):
    def _project(self, root: Path) -> Path:
        project = root / "project"
        (project / "src").mkdir(parents=True)
        (project / "receipts/terminal").mkdir(parents=True)
        (project / "src/main.py").write_text("print('ok')\n", encoding="utf-8")
        (project / "src/__pycache__").mkdir()
        (project / "src/__pycache__/main.pyc").write_bytes(b"cache")
        (project / "README.md").write_text("readme\n", encoding="utf-8")
        (project / "receipts/terminal/terminal.json").write_text(
            "{}\n", encoding="utf-8"
        )
        return project

    def test_inventory_is_allowlisted_and_excludes_cache(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            project = self._project(Path(temporary))
            records = inventory(project, ["src", "README.md", "receipts/terminal"])
            self.assertEqual(
                [item["path"] for item in records],
                ["README.md", "receipts/terminal/terminal.json", "src/main.py"],
            )

    def test_bundle_is_deterministic_and_verifiable(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            project = self._project(root)
            first = root / "first"
            second = root / "second"
            allowlist = ["src", "README.md", "receipts/terminal"]
            one = create_bundle(
                project,
                first,
                allowlist=allowlist,
                work_package_id="WP-TEST-001",
            )
            two = create_bundle(
                project,
                second,
                allowlist=allowlist,
                work_package_id="WP-TEST-001",
            )
            self.assertEqual(one["archive"]["sha256"], two["archive"]["sha256"])
            self.assertEqual(one["work_package_id"], "WP-TEST-001")
            self.assertEqual(
                (first / "SOURCE_FILES.json").read_bytes(),
                (second / "SOURCE_FILES.json").read_bytes(),
            )
            with tarfile.open(first / "mantis-rocm-bridge-source.tar") as archive:
                self.assertEqual(
                    sorted(archive.getnames()),
                    [
                        "mantis-rocm-bridge/README.md",
                        "mantis-rocm-bridge/receipts/terminal/terminal.json",
                        "mantis-rocm-bridge/src/main.py",
                    ],
                )
            manifest = json.loads((first / "SOURCE_FILES.json").read_text())
            self.assertEqual(manifest["file_count"], 3)
            self.assertEqual(manifest["work_package_id"], "WP-TEST-001")

    def test_existing_output_is_never_overwritten(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            project = self._project(root)
            output = root / "output"
            output.mkdir()
            sentinel = output / "keep"
            sentinel.write_text("keep", encoding="utf-8")
            with self.assertRaises(FileExistsError):
                create_bundle(
                    project,
                    output,
                    allowlist=["src", "README.md", "receipts/terminal"],
                )
            self.assertEqual(sentinel.read_text(encoding="utf-8"), "keep")

    def test_symlink_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            project = self._project(root)
            (project / "src/link").symlink_to(project / "README.md")
            with self.assertRaises(ValueError):
                inventory(project, ["src"])


if __name__ == "__main__":
    unittest.main()
