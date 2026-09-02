"""Tests for CLAUDE_CONFIG_ROOT_ALLOWLIST_LOCK_001."""

from __future__ import annotations

import importlib
import json
import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
for _p in (_REPO_ROOT, _REPO_ROOT / "scripts"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

cra = importlib.import_module("ide.config_root_allowlist")
cra_rec = importlib.import_module("ide.config_root_allowlist_record")

LOCK_PATH = _REPO_ROOT / "locks" / "sentinel" / ("CLAUDE_CONFIG_ROOT_ALLOWLIST_LOCK_001.json")
EVIDENCE_DIR = _REPO_ROOT / "assurance" / "evidence" / ("claude_config_root_allowlist")
EVIDENCE_INDEX = _REPO_ROOT / "assurance" / "evidence" / "evidence_index.json"


# ---------------------------------------------------------------------------
# Status tokens
# ---------------------------------------------------------------------------
def test_status_tokens_exact():
    assert set(cra_rec.CONFIG_ROOT_ALLOWLIST_STATUS_TOKENS) == {
        "CONFIG_ROOT_ALLOWLIST_PASSED",
        "CONFIG_ROOT_BLOCKED_DISALLOWED_ROOT",
        "CONFIG_ROOT_BLOCKED_PATH_TRAVERSAL",
        "CONFIG_ROOT_BLOCKED_UNTRUSTED_CONFIG",
        "CONFIG_ROOT_BLOCKED_MALFORMED_PATH",
    }


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------
def test_root_inside_allowed_parent_passes(tmp_path):
    parent = tmp_path / "trusted"
    parent.mkdir()
    candidate = parent / "configs"
    candidate.mkdir()
    rec = cra.verify(candidate, allowed_parents=[parent])
    assert rec.is_passed, rec.notes
    assert rec.source_mutation_authorized is False
    assert rec.training_eligible is False


def test_root_equal_to_allowed_parent_passes(tmp_path):
    p = tmp_path / "trusted"
    p.mkdir()
    rec = cra.verify(p, allowed_parents=[p])
    assert rec.is_passed


# ---------------------------------------------------------------------------
# Empty / malformed
# ---------------------------------------------------------------------------
def test_empty_root_blocks():
    rec = cra.verify("", allowed_parents=[Path("c:/tmp")])
    assert rec.decision == "CONFIG_ROOT_BLOCKED_MALFORMED_PATH"


def test_none_root_blocks():
    rec = cra.verify(None, allowed_parents=[Path("c:/tmp")])
    assert rec.decision == "CONFIG_ROOT_BLOCKED_MALFORMED_PATH"


def test_nul_in_root_blocks(tmp_path):
    rec = cra.verify(str(tmp_path) + "\x00bad", allowed_parents=[tmp_path])
    assert rec.decision == "CONFIG_ROOT_BLOCKED_MALFORMED_PATH"


# ---------------------------------------------------------------------------
# Path traversal
# ---------------------------------------------------------------------------
def test_path_traversal_blocks_even_if_resolved_lands_inside(tmp_path):
    parent = tmp_path / "trusted"
    parent.mkdir()
    candidate = f"{parent}/../trusted/configs"
    # Even though this resolves back into 'trusted', the traversal
    # syntax in the input is refused.
    rec = cra.verify(candidate, allowed_parents=[parent])
    assert rec.decision == "CONFIG_ROOT_BLOCKED_PATH_TRAVERSAL"


def test_double_dotdot_blocks(tmp_path):
    rec = cra.verify(f"{tmp_path}/../../somewhere", allowed_parents=[tmp_path])
    assert rec.decision == "CONFIG_ROOT_BLOCKED_PATH_TRAVERSAL"


# ---------------------------------------------------------------------------
# Dangerous roots
# ---------------------------------------------------------------------------
@pytest.mark.skipif(
    not (sys.platform.startswith("win") or sys.platform == "cygwin"), reason="windows path"
)
def test_windows_system_root_blocks(tmp_path):
    # Even with c:\\ in allowed_parents (caller bug), c:\\windows
    # itself is a system root the verifier refuses.
    rec = cra.verify("C:\\Windows", allowed_parents=[Path("C:\\")])
    assert rec.decision == "CONFIG_ROOT_BLOCKED_DISALLOWED_ROOT"


def test_posix_system_root_blocks(monkeypatch):
    monkeypatch.setattr(cra, "_is_windows", lambda: False)
    orig_resolve = Path.resolve

    def mock_resolve(self, strict=False):
        if str(self) == "/etc" or str(self) == "/":
            return self
        return orig_resolve(self, strict=strict)

    monkeypatch.setattr(Path, "resolve", mock_resolve)

    # Force posix path checking by pretending we're given posix strings
    # The verifier checks path strings directly in its disallow list.
    rec = cra.verify("/etc", allowed_parents=[Path("/")])
    assert rec.decision == "CONFIG_ROOT_BLOCKED_DISALLOWED_ROOT"


# ---------------------------------------------------------------------------
# Untrusted root
# ---------------------------------------------------------------------------
def test_root_outside_allowed_parents_blocks(tmp_path):
    parent_a = tmp_path / "trusted"
    parent_a.mkdir()
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    rec = cra.verify(elsewhere, allowed_parents=[parent_a])
    assert rec.decision == "CONFIG_ROOT_BLOCKED_UNTRUSTED_CONFIG"


def test_empty_allowed_parents_blocks_everything(tmp_path):
    rec = cra.verify(tmp_path, allowed_parents=[])
    assert rec.decision == "CONFIG_ROOT_BLOCKED_UNTRUSTED_CONFIG"


def test_multiple_allowed_parents_first_match_passes(tmp_path):
    parent_a = tmp_path / "trusted-a"
    parent_a.mkdir()
    parent_b = tmp_path / "trusted-b"
    parent_b.mkdir()
    candidate = parent_b / "configs"
    candidate.mkdir()
    rec = cra.verify(candidate, allowed_parents=[parent_a, parent_b])
    assert rec.is_passed
    assert str(parent_b) in rec.allowed_parent


# ---------------------------------------------------------------------------
# Defensive guarantees
# ---------------------------------------------------------------------------
def test_pass_does_not_authorize_source_mutation_or_training(tmp_path):
    parent = tmp_path / "trusted"
    parent.mkdir()
    rec = cra.verify(parent, allowed_parents=[parent])
    assert rec.is_passed
    assert rec.source_mutation_authorized is False
    assert rec.training_eligible is False


def test_pass_does_not_create_root(tmp_path):
    """Verifier never creates the requested directory."""
    parent = tmp_path / "trusted"
    parent.mkdir()
    candidate = parent / "does-not-exist-yet"
    rec = cra.verify(candidate, allowed_parents=[parent])
    # path resolution does not require existence; the verifier passes
    # because it's inside the allowed parent.
    assert rec.is_passed
    assert not candidate.exists()


# ---------------------------------------------------------------------------
# Cannot bypass via wrapping in allow-list
# ---------------------------------------------------------------------------
def test_root_drive_root_in_allowed_parents_does_not_unblock_system_root():
    """Even if a caller puts c:\\ in allowed_parents (effectively
    'allow everything on C:'), the verifier still refuses a
    dangerous-root resolution like c:\\Windows."""
    if sys.platform.startswith("win") or sys.platform == "cygwin":
        rec = cra.verify("C:\\Windows\\System32", allowed_parents=[Path("C:\\")])
        # Resolves to a path INSIDE allowed_parent c:\\, but
        # c:\\windows is a dangerous parent; check the resolved root.
        # If resolved root does not exactly equal c:\\windows, the
        # dangerous-root check won't fire — that's an honest limit;
        # the path-traversal/system-root denylist mostly handles
        # exact prefix matches. The test asserts at minimum it
        # doesn't pass.
        assert not rec.is_passed
    else:
        rec = cra.verify("/etc/passwd", allowed_parents=[Path("/")])
        assert not rec.is_passed


# ---------------------------------------------------------------------------
# Lock / evidence / index
# ---------------------------------------------------------------------------
def test_lock_manifest_exists_and_validates():
    assert LOCK_PATH.is_file()
    blob = json.loads(LOCK_PATH.read_text(encoding="utf-8"))
    assert blob["lock_id"] == "CLAUDE_CONFIG_ROOT_ALLOWLIST_LOCK_001"
    sd = blob["scope_discipline"]
    assert sd["source_mutation_authorized"] is False
    assert sd["training_eligible"] is False


def test_evidence_artifact_present():
    candidates = sorted(EVIDENCE_DIR.glob("run_*.json"))
    assert candidates


def test_evidence_index_entry_present():
    idx = json.loads(EVIDENCE_INDEX.read_text(encoding="utf-8"))
    ids = {e.get("evidence_id") for e in idx.get("entries", [])}
    assert "CLAUDE_CONFIG_ROOT_ALLOWLIST_LOCK_001" in ids
