# -*- coding: utf-8 -*-
"""Focused tests for scripts/build_submission.py (S01 submission builder).

Covers: allowlist-first selection, explicit carve-outs, tracked-only
candidates, path traversal / symlink protection, sensitive-content scanning
(no self-hits, no blanket IPv4 bans), dual LICENSE guard, dry-run, strict
mode, non-empty target refusal, force rebuilds, FILES.txt / BUILD_RECEIPT.json
/ MANIFEST.sha256 outputs and --check verification.
"""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
BUILDER_PATH = REPO_ROOT / "scripts" / "build_submission.py"


def load_builder():
    """Import scripts/build_submission.py as a module (dataclass-safe)."""
    spec = importlib.util.spec_from_file_location("build_submission", BUILDER_PATH)
    module = importlib.util.module_from_spec(spec)
    sys.modules["build_submission"] = module
    spec.loader.exec_module(module)
    return module


bsub = load_builder()


def git(repo: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )


# Held references so a TemporaryDirectory created by make_repo() is not garbage
# collected (and recursively deleted) before the test that uses it has run.
_TEMP_DIRS: list = []


def make_repo(files: dict[str, str]) -> Path:
    """Create a temp git repo containing ``files`` (relpath -> text)."""
    tmp = tempfile.TemporaryDirectory(prefix="s01-test-")
    _TEMP_DIRS.append(tmp)
    repo = Path(tmp.name)
    for rel, text in files.items():
        target = repo / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")
    git(repo, "init", "-q")
    git(repo, "config", "user.email", "s01@example.com")
    git(repo, "config", "user.name", "S01 Test")
    git(repo, "add", "-A")
    proc = git(repo, "commit", "-q", "-m", "init")
    if proc.returncode != 0:
        raise RuntimeError(f"test repo commit failed: {proc.stderr}")
    return repo


def _cleanup_temp_dirs() -> None:
    """Release module-level temp repos after the last test has run."""
    while _TEMP_DIRS:
        _TEMP_DIRS.pop().cleanup()


unittest.addModuleCleanup(_cleanup_temp_dirs)


class RepoTestCase(unittest.TestCase):
    """Base class: builds a temp repo + temp output dir, both cleaned up."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(prefix="s01-test-")
        self._root = Path(self._tmp.name)
        self.repo = self._root / "repo"
        self.out = self._root / "out"
        self.repo.mkdir()

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def run_build(self, *extra: str) -> int:
        return bsub.main(["--repo", str(self.repo), "--out", str(self.out), *extra])


class TestSelection(RepoTestCase):
    def test_allowlist_first_with_explicit_carveouts(self):
        self.repo = make_repo(
            {
                "README.md": "# Hi",
                "LICENSE": "MIT",
                "LICENSE-spritefusion-pixel-snapper": "Apache-2.0",
                "sprite_workshop/__init__.py": "",
                "frontend/renderer/index.html": "<html></html>",
                "AMD_BOX.md": "internal ops",
                "docs/luna-workpack/TASK_GRAPH.md": "internal plan",
                "BACKEND_CLI_PLAN.md": "plan",
                "PIXEL_TOOLING_RESEARCH.md": "research",
                "testdata/prompts/x.md": "fixture",
                "uv.lock": "lock",
                ".github/workflows/ci.yml": "ci",
                ".scratch-amd/shot.png": "\x89PNG\r\n\x1a\n" + "\x00" * 32,
                "private_notes/secrets.txt": "not in allowlist",
            }
        )
        self.run_build()
        payload = sorted((self.out / "FILES.txt").read_text(encoding="utf-8").splitlines())
        self.assertIn("README.md", payload)
        self.assertIn("LICENSE", payload)
        self.assertIn("LICENSE-spritefusion-pixel-snapper", payload)
        self.assertIn("sprite_workshop/__init__.py", payload)
        self.assertIn("frontend/renderer/index.html", payload)
        for excluded in (
            "AMD_BOX.md",
            "docs/luna-workpack/TASK_GRAPH.md",
            "BACKEND_CLI_PLAN.md",
            "PIXEL_TOOLING_RESEARCH.md",
            "testdata/prompts/x.md",
            "uv.lock",
            ".github/workflows/ci.yml",
            ".scratch-amd/shot.png",
            "private_notes/secrets.txt",
        ):
            self.assertNotIn(excluded, payload, excluded)
            self.assertFalse((self.out / excluded).exists())

    def test_untracked_files_are_not_candidates(self):
        self.repo = make_repo({"README.md": "# Hi", "LICENSE": "MIT"})
        (self.repo / "LICENSE-spritefusion-pixel-snapper").write_text("MIT", encoding="utf-8")
        untracked = self.repo / "untracked_extra.py"
        untracked.write_text("x = 1\n", encoding="utf-8")
        candidates = bsub.collect_candidates(str(self.repo))
        self.assertNotIn("untracked_extra.py", candidates)

    def test_real_repo_carve_outs(self):
        if not (REPO_ROOT / ".git").is_dir():
            self.skipTest("not a git checkout")
        candidates = bsub.collect_candidates(str(REPO_ROOT))
        payload, skipped = bsub.select_payload(candidates)
        for banned in (
            "AMD_BOX.md",
            "uv.lock",
            ".github/workflows/ci.yml",
            "BACKEND_CLI_PLAN.md",
            "PIXEL_TOOLING_RESEARCH.md",
            "testdata/prompts/README.md",
            ".scratch-amd/amd-verify.png",
            "frontend/.scratch-amd/01-stack.png",
        ):
            self.assertNotIn(banned, payload, banned)
            self.assertIn(banned, skipped)
        for required in ("LICENSE", "LICENSE-spritefusion-pixel-snapper"):
            self.assertIn(required, payload)
        self.assertFalse(bsub._license_guard(set(payload)))


class TestPathSafety(RepoTestCase):
    def test_relpath_validation_rejects_unsafe(self):
        for bad in (
            "",
            ".",
            "/",
            "../x",
            "a/../../x",
            "/etc/passwd",
            "C:\\Users\\x\\y",
            "a\\b",
            "a//b",
            "a/./b",
        ):
            with self.subTest(bad=bad):
                with self.assertRaises(bsub.BuildError):
                    bsub._validate_relpath(bad)
        for good in ("a/b.txt", "scripts/build_submission.py", "LICENSE-extra"):
            with self.subTest(good=good):
                self.assertEqual(bsub._validate_relpath(good), good)

    def test_output_path_escape_rejected(self):
        with self.assertRaises(bsub.BuildError):
            bsub._resolve_output_path(str(self.out), "../escape.txt")
        with self.assertRaises(bsub.BuildError):
            bsub._resolve_output_path(str(self.out), "a/../../escape.txt")

    def test_symlink_source_rejected(self):
        self.repo = make_repo({"README.md": "# Hi"})
        outside = self._root / "outside.txt"
        outside.write_text("secret", encoding="utf-8")
        link = self.repo / "evil_link.py"
        try:
            os.symlink(outside, link)
        except (OSError, NotImplementedError) as exc:  # pragma: no cover - platform
            self.skipTest(f"symlinks unavailable: {exc}")
        with self.assertRaises(bsub.BuildError):
            bsub._reject_symlink_sources(str(self.repo), ["evil_link.py"])


class TestScanner(RepoTestCase):
    def test_error_rules_detect_secrets(self):
        for text in (
            "AKIAIOSFODNN7EXAMPLE",
            "-----BEGIN OPENSSH PRIVATE KEY-----\nabc\n-----END OPENSSH PRIVATE KEY-----",
            'password = "hunter2secret"',
            "api_key: 'abcdef1234567890'",
            r"C:\Users\alice\secrets.txt",
            "/home/alice/.ssh/id_rsa",
        ):
            with self.subTest(text=text):
                hits = bsub.scan_text(text)
                self.assertTrue(any(h.severity == "error" for h in hits), text)

    def test_unquoted_dotenv_is_warning(self):
        hits = bsub.scan_text("token=abc12345def\n")
        self.assertTrue(any(h.rule_id == "secret-assignment-unquoted" for h in hits))
        self.assertFalse(any(h.severity == "error" for h in hits))

    def test_bare_public_ipv4_not_flagged(self):
        for text in (
            "The render server listens at 8.8.8.8.",
            "Example endpoint 203.0.113.5 is documented in README.",
            "host 1.2.3.4 is referenced in prose only",
        ):
            with self.subTest(text=text):
                self.assertEqual(bsub.scan_text(text), [], text)

    def test_private_and_loopback_ips_not_flagged(self):
        for text in (
            "ssh_host=127.0.0.1",
            "server=10.0.0.5",
            "host=192.168.1.10",
            "endpoint=172.16.0.1",
            "backend_url=169.254.1.1",
        ):
            with self.subTest(text=text):
                self.assertEqual(bsub.scan_text(text), [], text)

    def test_sensitive_ip_assignment_is_warning(self):
        hits = bsub.scan_text("ssh_host=8.8.8.8")
        flagged = [h for h in hits if h.rule_id == bsub.SENSITIVE_IP_RULE_ID]
        self.assertEqual(len(flagged), 1)
        self.assertEqual(flagged[0].severity, "warning")

    def test_scanner_does_not_self_hit(self):
        source = BUILDER_PATH.read_text(encoding="utf-8")
        self.assertEqual(bsub.scan_text(source), [])
        self.assertIn("scripts/build_submission.py", bsub.SELF_SKIP_PATHS)
        self.assertIn("tests/test_build_submission.py", bsub.SELF_SKIP_PATHS)

    def test_fixture_files_are_never_scanned_in_builds(self):
        # The tool's own implementation and test files must be skipped, so
        # rules/assertions inside them can never trip the scanner.
        pairs = [(p, str(REPO_ROOT / p)) for p in ("scripts/build_submission.py",)]
        hits, scanned = bsub.scan_files(pairs, skip=bsub.SELF_SKIP_PATHS)
        self.assertEqual(hits, [])
        self.assertEqual(scanned, 0)


class TestModes(RepoTestCase):
    def base_files(self) -> dict[str, str]:
        return {
            "README.md": "# Hi\n",
            "LICENSE": "MIT\n",
            "LICENSE-spritefusion-pixel-snapper": "Apache-2.0\n",
            "sprite_workshop/__init__.py": "x = 1\n",
        }

    def test_dry_run_writes_nothing(self):
        self.repo = make_repo(self.base_files())
        self.assertEqual(self.run_build("--dry-run"), 0)
        self.assertFalse(self.out.exists())

    def test_build_writes_meta_outputs(self):
        self.repo = make_repo(self.base_files())
        self.assertEqual(self.run_build(), 0)
        self.assertTrue((self.out / "FILES.txt").is_file())
        self.assertTrue((self.out / "BUILD_RECEIPT.json").is_file())
        self.assertTrue((self.out / "MANIFEST.sha256").is_file())
        receipt = json.loads((self.out / "BUILD_RECEIPT.json").read_text(encoding="utf-8"))
        self.assertEqual(receipt["tool"], bsub.TOOL_NAME)
        self.assertEqual(receipt["license_guard"]["status"], "pass")

    def test_manifest_hashes_everything_except_itself(self):
        self.repo = make_repo(self.base_files())
        self.assertEqual(self.run_build(), 0)
        manifest = (self.out / "MANIFEST.sha256").read_text(encoding="utf-8")
        self.assertIn("does NOT hash itself", manifest)
        entries = bsub.parse_manifest(str(self.out / "MANIFEST.sha256"))
        self.assertNotIn("MANIFEST.sha256", entries)
        payload = sorted(set(entries) - {"FILES.txt", "BUILD_RECEIPT.json"})
        for rel in payload:
            with self.subTest(rel=rel):
                path = self.out / rel
                self.assertTrue(path.is_file(), rel)
                self.assertEqual(
                    entries[rel], bsub.sha256_file(str(path)), rel
                )
        for meta in ("FILES.txt", "BUILD_RECEIPT.json"):
            self.assertEqual(
                entries[meta], bsub.sha256_file(str(self.out / meta)), meta
            )
        listed = (self.out / "FILES.txt").read_text(encoding="utf-8").splitlines()
        self.assertEqual(sorted(listed), sorted(payload))

    def test_check_ok_then_tamper_detected(self):
        self.repo = make_repo(self.base_files())
        self.assertEqual(self.run_build(), 0)
        self.assertEqual(self.run_build("--check"), 0)
        (self.out / "README.md").write_text("# Tampered\n", encoding="utf-8")
        self.assertEqual(self.run_build("--check"), 1)
        (self.out / "README.md").unlink()
        self.assertEqual(self.run_build("--check"), 1)

    def test_non_empty_target_refused_without_receipt(self):
        self.repo = make_repo(self.base_files())
        self.out.mkdir()
        (self.out / "user.txt").write_text("mine", encoding="utf-8")
        self.assertEqual(self.run_build(), 1)
        self.assertEqual(self.run_build("--force"), 1)

    def test_force_rebuild_over_receipt(self):
        self.repo = make_repo(self.base_files())
        self.assertEqual(self.run_build(), 0)
        (self.repo / "sprite_workshop").mkdir(exist_ok=True)
        (self.repo / "sprite_workshop" / "extra.py").write_text("y = 2\n", encoding="utf-8")
        git(self.repo, "add", "-A")
        git(self.repo, "commit", "-q", "-m", "add extra")
        self.assertEqual(self.run_build("--force"), 0)
        self.assertTrue((self.out / "sprite_workshop" / "extra.py").is_file())
        self.assertEqual(self.run_build("--check"), 0)

    def test_force_rebuild_refuses_stray_files(self):
        self.repo = make_repo(self.base_files())
        self.assertEqual(self.run_build(), 0)
        (self.out / "user_stray.txt").write_text("not owned", encoding="utf-8")
        self.assertEqual(self.run_build("--force"), 1)

    def test_license_guard_fails_build_and_check(self):
        files = self.base_files()
        del files["LICENSE-spritefusion-pixel-snapper"]
        self.repo = make_repo(files)
        self.assertEqual(self.run_build(), 1)
        # guard also rejects a valid build whose license was deleted
        self.repo = make_repo(self.base_files())
        self.assertEqual(self.run_build(), 0)
        (self.out / "LICENSE").unlink()
        self.assertEqual(self.run_build("--check"), 1)

    def test_strict_fails_on_warnings_only(self):
        files = self.base_files()
        files["sprite_workshop/warn.env"] = "token=abc12345def\n"
        self.repo = make_repo(files)
        self.assertEqual(self.run_build(), 0)  # warning tolerated by default
        self.assertEqual(self.run_build("--strict"), 1)
        self.assertEqual(self.run_build("--force", "--strict"), 1)

    def test_error_hits_fail_even_without_strict(self):
        files = self.base_files()
        files["sprite_workshop/leak.env"] = "AWS_KEY=AKIAIOSFODNN7EXAMPLE\n"
        self.repo = make_repo(files)
        self.assertEqual(self.run_build(), 1)

    def test_check_strict_fails_on_warnings(self):
        files = self.base_files()
        files["sprite_workshop/warn.env"] = "token=abc12345def\n"
        self.repo = make_repo(files)
        self.assertEqual(self.run_build(), 0)
        self.assertEqual(self.run_build("--check", "--strict"), 1)
        self.assertEqual(self.run_build("--check"), 0)

    def test_check_rejects_bad_manifest_and_traversal(self):
        self.repo = make_repo(self.base_files())
        self.assertEqual(self.run_build(), 0)
        manifest = self.out / "MANIFEST.sha256"
        manifest.write_text(
            bsub.MANIFEST_HEADER + "0" * 64 + "  ../escape.txt\n", encoding="utf-8"
        )
        self.assertEqual(self.run_build("--check"), 1)
        manifest.write_text(
            bsub.MANIFEST_HEADER
            + bsub.sha256_file(str(self.out / "README.md"))
            + "  README.md\n"
            + "0" * 64 + "  MANIFEST.sha256\n",
            encoding="utf-8",
        )
        self.assertEqual(self.run_build("--check"), 1)

    def test_check_rejects_combined_flags(self):
        self.repo = make_repo(self.base_files())
        self.assertEqual(self.run_build(), 0)
        self.assertEqual(self.run_build("--check", "--force"), 1)
        self.assertEqual(self.run_build("--check", "--dry-run"), 1)


class TestGlobs(RepoTestCase):
    def test_glob_matching(self):
        cases = [
            ("sprite_workshop/**", "sprite_workshop/generate/base.py", True),
            ("sprite_workshop/**", "sprite_workshop/__init__.py", True),
            ("sprite_workshop/**", "other/x.py", False),
            ("scripts/*", "scripts/build_submission.py", True),
            ("scripts/*", "scripts/sub/x.py", False),
            ("LICENSE-*", "LICENSE-spritefusion-pixel-snapper", True),
            ("LICENSE-*", "LICENSE", False),
            ("**/__pycache__/**", "sprite_workshop/__pycache__/x.pyc", True),
            ("frontend/**", "frontend/renderer/js/app.js", True),
        ]
        for pattern, rel, expected in cases:
            with self.subTest(pattern=pattern, rel=rel):
                self.assertEqual(bsub._matches(rel, [pattern]), expected)


if __name__ == "__main__":
    unittest.main()
