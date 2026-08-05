"""Tests for SAFE_PATCH_DIFF_ROLLBACK_LOCK_001.

Asserts the SafePatchWorkspace contract:

  * patches are applied only to a temp copy under a caller-supplied root
  * the original repo is never written (sha256 before == sha256 after)
  * path traversal blocked (PATCH_BLOCKED_PATH_ESCAPE)
  * symlink escape blocked (PATCH_BLOCKED_SYMLINK_ESCAPE)
  * binary content blocked (PATCH_BLOCKED_BINARY_CONTENT)
  * unified diff captured from baseline → temp
  * verifier callable is invoked on the temp workspace
  * verifier failure rolls back when rollback_on_failure=True
  * the lock/evidence/index entries all validate
"""

from __future__ import annotations

import hashlib
import importlib
import json
import os
import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
for _p in (_REPO_ROOT, _REPO_ROOT / "scripts"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

sp_mod = importlib.import_module("repair.safe_patch_workspace")
rec_mod = importlib.import_module("repair.safe_patch_record")

SafePatchWorkspace = sp_mod.SafePatchWorkspace
FilePatch = sp_mod.FilePatch
VerifierResult = sp_mod.VerifierResult
SAFE_PATCH_STATUS_TOKENS = sp_mod.SAFE_PATCH_STATUS_TOKENS
stub_verifier_pass = sp_mod.stub_verifier_pass
stub_verifier_fail = sp_mod.stub_verifier_fail

LOCK_PATH = _REPO_ROOT / "locks" / "sentinel" / "SAFE_PATCH_DIFF_ROLLBACK_LOCK_001.json"
EVIDENCE_DIR = _REPO_ROOT / "assurance" / "evidence" / "safe_patch_diff_rollback"
EVIDENCE_INDEX = _REPO_ROOT / "assurance" / "evidence" / "evidence_index.json"


STATUS_TOKENS = frozenset(SAFE_PATCH_STATUS_TOKENS)


def _hash_tree(root: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    if not root.is_dir():
        return out
    for p in sorted(root.rglob("*")):
        if not p.is_file():
            continue
        try:
            out[p.relative_to(root).as_posix()] = hashlib.sha256(p.read_bytes()).hexdigest()
        except (OSError, PermissionError):
            continue
    return out


def _seed_repo(root: Path) -> Path:
    """Create a minimal source tree under ``root``."""
    (root / "src").mkdir(parents=True, exist_ok=True)
    (root / "src" / "lib.py").write_text("def add(a, b):\n    return a + b\n", encoding="utf-8")
    (root / "README.md").write_text("orig\n", encoding="utf-8")
    return root


@pytest.fixture
def repos(tmp_path: Path) -> tuple[Path, Path]:
    original = tmp_path / "original"
    temp_root = tmp_path / "temp_root"
    _seed_repo(original)
    temp_root.mkdir(parents=True, exist_ok=True)
    return original, temp_root


# ---------------------------------------------------------------------------
# Status / closed set
# ---------------------------------------------------------------------------


def test_status_tokens_match_expected_set():
    expected = {
        "PATCH_APPLIED_TO_TEMP_WORKSPACE",
        "PATCH_REJECTED",
        "PATCH_BLOCKED_PATH_ESCAPE",
        "PATCH_BLOCKED_SYMLINK_ESCAPE",
        "PATCH_BLOCKED_BINARY_CONTENT",
        "PATCH_VERIFIER_FAILED",
        "PATCH_VERIFIER_PASSED_TEMP_ONLY",
        "PATCH_VERIFIER_SKIPPED",
        "PATCH_ROLLED_BACK",
        "SOURCE_MUTATION_BLOCKED",
    }
    assert set(STATUS_TOKENS) == expected


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


def test_apply_patch_writes_only_to_temp(repos):
    original, temp_root = repos
    before = _hash_tree(original)
    sp = SafePatchWorkspace(original, temp_root)
    res = sp.apply_and_verify(
        [FilePatch("src/lib.py", "def add(a, b):\n    return a + b + 0\n")],
        verifier=None,
    )
    assert res.status == "PATCH_APPLIED_TO_TEMP_WORKSPACE"
    assert res.original_unchanged is True
    assert _hash_tree(original) == before
    # Temp workspace exists with the new content.
    assert (sp.temp_workspace / "src" / "lib.py").read_text(encoding="utf-8").endswith("+ 0\n")


def test_unified_diff_captures_change(repos):
    original, temp_root = repos
    sp = SafePatchWorkspace(original, temp_root)
    res = sp.apply_and_verify(
        [FilePatch("README.md", "patched\n")],
    )
    assert "-orig" in res.unified_diff
    assert "+patched" in res.unified_diff
    assert "--- a/README.md" in res.unified_diff
    assert "+++ b/README.md" in res.unified_diff


def test_verifier_pass_status_set(repos):
    original, temp_root = repos
    sp = SafePatchWorkspace(original, temp_root)
    res = sp.apply_and_verify(
        [FilePatch("src/lib.py", "x = 1\n")],
        verifier=stub_verifier_pass,
    )
    assert res.verifier_status == "PATCH_VERIFIER_PASSED_TEMP_ONLY"
    assert res.is_verifier_pass


def test_verifier_fail_triggers_rollback_when_requested(repos):
    original, temp_root = repos
    sp = SafePatchWorkspace(original, temp_root)
    res = sp.apply_and_verify(
        [FilePatch("src/lib.py", "x = 1\n")],
        verifier=stub_verifier_fail,
        rollback_on_failure=True,
    )
    assert res.status == "PATCH_ROLLED_BACK"
    assert res.verifier_status == "PATCH_VERIFIER_FAILED"
    assert res.rolled_back is True
    assert not sp.temp_workspace.exists(), "Temp must be deleted on rollback"
    # Original unchanged.
    assert res.original_unchanged is True


def test_verifier_fail_no_rollback_when_disabled(repos):
    original, temp_root = repos
    sp = SafePatchWorkspace(original, temp_root)
    res = sp.apply_and_verify(
        [FilePatch("src/lib.py", "x = 1\n")],
        verifier=stub_verifier_fail,
        rollback_on_failure=False,
    )
    assert res.status == "PATCH_APPLIED_TO_TEMP_WORKSPACE"
    assert res.verifier_status == "PATCH_VERIFIER_FAILED"
    assert res.rolled_back is False
    assert sp.temp_workspace.exists()


def test_verifier_skipped_when_none(repos):
    original, temp_root = repos
    sp = SafePatchWorkspace(original, temp_root)
    res = sp.apply_and_verify([FilePatch("src/lib.py", "x = 1\n")])
    assert res.verifier_status == "PATCH_VERIFIER_SKIPPED"


# ---------------------------------------------------------------------------
# Path traversal / escape
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "bad_path",
    [
        "../etc/passwd",
        "..\\..\\windows\\system32",
        "/absolute/path",
        "C:/abs",
        "foo/../bar",
        "",
        "/etc/shadow",
    ],
)
def test_path_traversal_blocked(repos, bad_path):
    original, temp_root = repos
    sp = SafePatchWorkspace(original, temp_root)
    res = sp.apply_and_verify(
        [FilePatch(bad_path, "x\n")],
        rollback_on_failure=True,
    )
    assert res.status == "PATCH_BLOCKED_PATH_ESCAPE", (
        f"path {bad_path!r} should block, got {res.status}"
    )
    assert res.original_unchanged is True


# ---------------------------------------------------------------------------
# Symlink escape
# ---------------------------------------------------------------------------


@pytest.mark.skipif(
    not hasattr(os, "symlink"),
    reason="os.symlink not available",
)
def test_symlink_escape_blocked(repos, tmp_path, monkeypatch):
    """If a patch attempts to write through a symlink to escape the workspace, refuse."""
    if not hasattr(os, "symlink"):
        pytest.skip("os.symlink not available")
    original, temp_root = repos
    sp = SafePatchWorkspace(original, temp_root)
    sp.stage()
    outside = tmp_path / "outside"
    outside.mkdir()
    link = sp.temp_workspace / "src" / "evil_link"
    try:
        os.symlink(outside, link)
    except (OSError, NotImplementedError):
        link.mkdir()
        orig_resolve = Path.resolve

        def mock_resolve(self, strict=False):
            self_abs = str(self.absolute())
            link_abs = str(link.absolute())
            if self_abs == link_abs:
                return outside.resolve(strict=strict)
            elif self_abs.startswith(link_abs + os.sep):
                remainder = self_abs[len(link_abs) + 1 :]
                return outside.resolve(strict=strict) / remainder
            return orig_resolve(self, strict=strict)

        monkeypatch.setattr(Path, "resolve", mock_resolve)

        orig_is_symlink = Path.is_symlink

        def mock_is_symlink(self):
            if str(self.absolute()) == str(link.absolute()):
                return True
            return orig_is_symlink(self)

        monkeypatch.setattr(Path, "is_symlink", mock_is_symlink)

        orig_os_islink = os.path.islink

        def mock_os_islink(path):
            if str(Path(path).absolute()) == str(link.absolute()):
                return True
            return orig_os_islink(path)

        monkeypatch.setattr(os.path, "islink", mock_os_islink)
    # Now try to patch through the symlink.
    res = sp.apply_and_verify(
        [FilePatch("src/evil_link/bad.txt", "x\n")],
        rollback_on_failure=False,
    )
    # On Windows without Developer Mode, the symlink may not be a directory
    # link and the resolve check may still reject path escape — either
    # rejection token is acceptable.
    assert res.status in ("PATCH_BLOCKED_SYMLINK_ESCAPE", "PATCH_BLOCKED_PATH_ESCAPE")
    assert res.original_unchanged is True


def test_symlink_target_as_file_blocked(repos, tmp_path, monkeypatch):
    """If the patch's target *itself* is a symlink, refuse."""
    if not hasattr(os, "symlink"):
        pytest.skip("os.symlink not available")
    original, temp_root = repos
    sp = SafePatchWorkspace(original, temp_root)
    sp.stage()
    outside = tmp_path / "outside.txt"
    outside.write_text("payload\n", encoding="utf-8")
    link = sp.temp_workspace / "README.md"
    link.unlink()
    try:
        os.symlink(outside, link)
    except (OSError, NotImplementedError):
        link.write_text("mock", encoding="utf-8")
        orig_resolve = Path.resolve

        def mock_resolve(self, strict=False):
            self_abs = str(self.absolute())
            link_abs = str(link.absolute())
            if self_abs == link_abs:
                return outside.resolve(strict=strict)
            return orig_resolve(self, strict=strict)

        monkeypatch.setattr(Path, "resolve", mock_resolve)

        orig_is_symlink = Path.is_symlink

        def mock_is_symlink(self):
            if str(self.absolute()) == str(link.absolute()):
                return True
            return orig_is_symlink(self)

        monkeypatch.setattr(Path, "is_symlink", mock_is_symlink)

        orig_os_islink = os.path.islink

        def mock_os_islink(path):
            if str(Path(path).absolute()) == str(link.absolute()):
                return True
            return orig_os_islink(path)

        monkeypatch.setattr(os.path, "islink", mock_os_islink)
    res = sp.apply_and_verify(
        [FilePatch("README.md", "patched\n")],
        rollback_on_failure=False,
    )
    assert res.status == "PATCH_BLOCKED_SYMLINK_ESCAPE"
    # outside.txt MUST be untouched.
    assert outside.read_text(encoding="utf-8") == "payload\n"


# ---------------------------------------------------------------------------
# Binary content
# ---------------------------------------------------------------------------


def test_binary_content_blocked(repos):
    original, temp_root = repos
    sp = SafePatchWorkspace(original, temp_root)
    res = sp.apply_and_verify(
        [FilePatch("src/lib.py", "good\x00bad\n")],
        rollback_on_failure=True,
    )
    assert res.status == "PATCH_BLOCKED_BINARY_CONTENT"
    assert res.original_unchanged is True
    assert not sp.temp_workspace.exists()


# ---------------------------------------------------------------------------
# Original immutability assertion under rollback paths
# ---------------------------------------------------------------------------


def test_original_unchanged_after_every_rejection(repos):
    original, temp_root = repos
    before = _hash_tree(original)
    sp = SafePatchWorkspace(original, temp_root)
    for bad in ("../escape.txt", "foo/../bar", "/abs"):
        try:
            sp.apply_and_verify(
                [FilePatch(bad, "x\n")],
                rollback_on_failure=True,
            )
        except Exception:
            pass
        # Re-init for a fresh stage attempt each loop.
        sp = SafePatchWorkspace(original, temp_root, workspace_id=f"x{hash(bad) & 0xFFFF:04x}")
    assert _hash_tree(original) == before


def test_rollback_idempotent(repos):
    original, temp_root = repos
    sp = SafePatchWorkspace(original, temp_root)
    sp.stage()
    assert sp.temp_workspace.exists()
    sp.rollback()
    assert not sp.temp_workspace.exists()
    sp.rollback()  # idempotent
    assert not sp.temp_workspace.exists()


# ---------------------------------------------------------------------------
# Module hygiene
# ---------------------------------------------------------------------------


def test_module_does_not_import_subprocess_or_urllib():
    for fname in ("safe_patch_workspace.py", "safe_patch_record.py"):
        src = (_REPO_ROOT / "scripts" / "repair" / fname).read_text(encoding="utf-8")
        assert "import subprocess" not in src
        assert "from subprocess" not in src
        assert "import urllib" not in src
        assert "from urllib" not in src
        assert "import socket" not in src
        assert "import http" not in src


def test_result_is_json_serializable(repos):
    original, temp_root = repos
    sp = SafePatchWorkspace(original, temp_root)
    res = sp.apply_and_verify([FilePatch("src/lib.py", "x = 1\n")])
    parsed = json.loads(res.to_json())
    assert parsed["status"] == "PATCH_APPLIED_TO_TEMP_WORKSPACE"
    assert parsed["original_unchanged"] is True
    assert parsed["training_eligible"] is False


# ---------------------------------------------------------------------------
# Lock + evidence + index
# ---------------------------------------------------------------------------


def test_lock_manifest_exists_and_validates():
    assert LOCK_PATH.is_file(), f"Missing lock: {LOCK_PATH}"
    blob = json.loads(LOCK_PATH.read_text(encoding="utf-8"))
    assert blob["lock_id"] == "SAFE_PATCH_DIFF_ROLLBACK_LOCK_001"
    assert set(blob.get("status_tokens", [])).issubset(STATUS_TOKENS)
    assert blob["scope_discipline"]["user_source_mutated"] is False


def test_evidence_artifact_present():
    candidates = sorted(EVIDENCE_DIR.glob("run_*.json"))
    assert candidates, f"No evidence in {EVIDENCE_DIR}"
    blob = json.loads(candidates[-1].read_text(encoding="utf-8"))
    assert blob["lock_id"] == "SAFE_PATCH_DIFF_ROLLBACK_LOCK_001"


def test_evidence_index_entry_present():
    idx = json.loads(EVIDENCE_INDEX.read_text(encoding="utf-8"))
    ids = {e.get("evidence_id") for e in idx.get("entries", [])}
    assert "SAFE_PATCH_DIFF_ROLLBACK_LOCK_001" in ids
