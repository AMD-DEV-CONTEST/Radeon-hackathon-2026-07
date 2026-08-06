from __future__ import annotations

import hashlib
import os
from pathlib import Path
import shutil
import subprocess
import tarfile
import tempfile
import unittest


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPOSITORY_ROOT / "scripts" / "build_release_package.sh"
VERSION = "v0.1.2-amd-hackathon-final"


class ReleasePackagingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name) / "AlphaNoah-A1-Edge-Agent-Public"
        self._create_minimal_repository()
        self._git("init", "-q")
        self._git("add", ".")
        env = {
            **os.environ,
            "GIT_AUTHOR_NAME": "Release Test",
            "GIT_AUTHOR_EMAIL": "release-test@example.invalid",
            "GIT_COMMITTER_NAME": "Release Test",
            "GIT_COMMITTER_EMAIL": "release-test@example.invalid",
        }
        subprocess.run(
            ["git", "commit", "-q", "-m", "test release input"],
            cwd=self.root,
            env=env,
            check=True,
        )
        self.commit = self._git("rev-parse", "HEAD").stdout.strip()

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_build_derives_identity_and_checksum_from_explicit_inputs(self) -> None:
        result = self._build(VERSION, self.commit)
        self.assertEqual(result.returncode, 0, result.stderr)

        name = f"AlphaNoah-A1-Edge-Agent-{VERSION}-linux-x86_64"
        archive = self.root / "dist" / f"{name}.tar.gz"
        checksums = self.root / "dist" / "SHA256SUMS"
        self.assertTrue(archive.is_file())
        expected_digest, expected_name = checksums.read_text().split()
        self.assertEqual(expected_name, archive.name)
        self.assertEqual(
            expected_digest,
            hashlib.sha256(archive.read_bytes()).hexdigest(),
        )

        with tarfile.open(archive, "r:gz") as package:
            release_info = package.extractfile(f"{name}/RELEASE_INFO.txt")
            self.assertIsNotNone(release_info)
            metadata = release_info.read().decode("utf-8")
        self.assertIn(f"Release: {VERSION}", metadata)
        self.assertIn(f"Source Commit: {self.commit}", metadata)
        self.assertIn(f"Packaging Commit: {self.commit}", metadata)
        self.assertIn("Source State: clean", metadata)

    def test_wrong_commit_and_dirty_tree_fail_loudly(self) -> None:
        mismatch = self._build(VERSION, "0" * 40)
        self.assertNotEqual(mismatch.returncode, 0)
        self.assertIn("Source commit mismatch", mismatch.stderr)

        (self.root / "README_LOCAL.md").write_text("dirty\n")
        dirty = self._build(VERSION, self.commit)
        self.assertNotEqual(dirty.returncode, 0)
        self.assertIn("Refusing to package a dirty repository", dirty.stderr)

    def _build(self, version: str, commit: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [str(self.root / "scripts" / SCRIPT.name), version, commit],
            cwd=self.root,
            text=True,
            capture_output=True,
            check=False,
        )

    def _git(self, *arguments: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["git", *arguments],
            cwd=self.root,
            text=True,
            capture_output=True,
            check=True,
        )

    def _create_minimal_repository(self) -> None:
        (self.root / "scripts").mkdir(parents=True)
        shutil.copy2(SCRIPT, self.root / "scripts" / SCRIPT.name)
        for name in (
            "common.sh",
            "install.sh",
            "configure.sh",
            "start.sh",
            "stop.sh",
            "restart.sh",
            "status.sh",
            "healthcheck.sh",
            "reset_demo.sh",
            "provider_probe.py",
        ):
            path = self.root / "scripts" / name
            path.write_text("#!/usr/bin/env bash\n", encoding="utf-8")
        (self.root / "src" / "alphanoah_a1").mkdir(parents=True)
        (self.root / "src" / "alphanoah_a1" / "__init__.py").write_text("")
        (self.root / "examples").mkdir()
        (self.root / "examples" / "knowledge.json").write_text("{}\n")
        (self.root / "frontend" / "dist").mkdir(parents=True)
        (self.root / "frontend" / "dist" / "index.html").write_text(
            "<html></html>\n"
        )
        (self.root / "config").mkdir()
        (self.root / "config" / "alphanoah.env.example").write_text("\n")
        (self.root / "config" / "provider.example.env").write_text("\n")
        for name in (
            "pyproject.toml",
            "requirements.txt",
            "README_LOCAL.md",
            "PROVIDER_SETUP.md",
            "DEMO_GUIDE_LOCAL.md",
            "SECURITY_AND_PRIVACY.md",
        ):
            (self.root / name).write_text(f"synthetic {name}\n")


if __name__ == "__main__":
    unittest.main()
