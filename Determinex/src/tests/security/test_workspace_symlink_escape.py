"""
tests/security/test_workspace_symlink_escape.py — Workspace path-escape prevention.

Verifies that resolve_workspace_path() and assert_inside_workspace() block:
  - symlink escapes pointing outside the workspace
  - junction / nested-link escapes (Windows)
  - path traversal (../) that crosses the workspace boundary

All tests use pytest's tmp_path fixture — no real filesystem state is modified.
Symlink creation is skipped gracefully when the OS requires elevated privileges
(Windows without Developer Mode enabled).
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

_SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from hive.workspace import assert_inside_workspace, resolve_workspace_path

# ---------------------------------------------------------------------------
# Basic containment tests (no symlinks required)
# ---------------------------------------------------------------------------


def test_file_inside_workspace_is_allowed(tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    target = workspace / "src" / "main.rs"
    target.parent.mkdir()
    target.write_text("fn main() {}")
    resolved = resolve_workspace_path(target, workspace)
    assert resolved == target.resolve()


def test_nested_dir_inside_workspace_is_allowed(tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    nested = workspace / "a" / "b" / "c" / "file.txt"
    nested.parent.mkdir(parents=True)
    nested.write_text("ok")
    resolved = resolve_workspace_path(nested, workspace)
    assert resolved == nested.resolve()


def test_dotdot_traversal_that_stays_inside_is_allowed(tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "subdir").mkdir()
    inner = workspace / "file.txt"
    inner.write_text("safe")
    # workspace/subdir/../file.txt normalizes to workspace/file.txt — still inside
    dotdot_path = workspace / "subdir" / ".." / "file.txt"
    resolved = resolve_workspace_path(dotdot_path, workspace)
    assert resolved == inner.resolve()


def test_dotdot_traversal_that_escapes_is_blocked(tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    # workspace/../outside.txt escapes to tmp_path/outside.txt
    escaping = workspace / ".." / "outside.txt"
    with pytest.raises(ValueError, match="escape"):
        resolve_workspace_path(escaping, workspace)


def test_absolute_path_outside_workspace_is_blocked(tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    outside = tmp_path / "not_in_workspace.txt"
    outside.write_text("classified")
    with pytest.raises(ValueError, match="escape"):
        resolve_workspace_path(outside, workspace)


def test_assert_inside_workspace_passes_for_contained(tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    inner = workspace / "src" / "lib.rs"
    inner.parent.mkdir()
    inner.write_text("// ok")
    assert_inside_workspace(inner, workspace)  # must not raise


def test_assert_inside_workspace_raises_for_escaped(tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    outside = tmp_path / "secret.txt"
    outside.write_text("secret")
    with pytest.raises(ValueError):
        assert_inside_workspace(outside, workspace)


# ---------------------------------------------------------------------------
# Symlink escape tests (skipped if symlink creation unavailable)
# ---------------------------------------------------------------------------


def _try_symlink(link: Path, target: Path, monkeypatch) -> bool:
    """Return True if symlink was created, or fallback to mock."""
    try:
        link.symlink_to(target)
        return True
    except (OSError, NotImplementedError):
        # Fallback for Windows without symlink privileges
        if not target.exists():
            # If target doesn't exist, just touch link
            link.touch()
        elif target.is_dir():
            link.mkdir()
        else:
            link.write_text("mock", encoding="utf-8")

        orig_resolve = Path.resolve

        def mock_resolve(self, strict=False):
            self_abs = str(self.absolute())
            link_abs = str(link.absolute())
            if self_abs == link_abs:
                return target.resolve(strict=strict)
            elif self_abs.startswith(link_abs + os.sep):
                remainder = self_abs[len(link_abs) + 1 :]
                return target.resolve(strict=strict) / remainder
            return orig_resolve(self, strict=strict)

        monkeypatch.setattr(Path, "resolve", mock_resolve)
        return True


def test_symlink_to_outside_file_is_blocked(tmp_path, monkeypatch):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    outside = tmp_path / "outside_secret.txt"
    outside.write_text("classified")
    link = workspace / "innocent_link.txt"
    if not _try_symlink(link, outside, monkeypatch):
        pytest.skip("symlink creation not available (Developer Mode or admin required)")
    with pytest.raises(ValueError, match="escape"):
        resolve_workspace_path(link, workspace)


def test_symlink_to_outside_dir_is_blocked(tmp_path, monkeypatch):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    outside_dir = tmp_path / "outside_dir"
    outside_dir.mkdir()
    (outside_dir / "secret.txt").write_text("classified")
    link = workspace / "link_to_outside"
    if not _try_symlink(link, outside_dir, monkeypatch):
        pytest.skip("symlink creation not available")
    target = link / "secret.txt"
    with pytest.raises(ValueError, match="escape"):
        resolve_workspace_path(target, workspace)


def test_nested_symlink_chain_escape_is_blocked(tmp_path, monkeypatch):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "layer1").mkdir()
    outside = tmp_path / "private"
    outside.mkdir()
    (outside / "key.pem").write_text("PRIVATE")
    link = workspace / "layer1" / "link_to_private"
    if not _try_symlink(link, outside, monkeypatch):
        pytest.skip("symlink creation not available")
    with pytest.raises(ValueError, match="escape"):
        resolve_workspace_path(link / "key.pem", workspace)


def test_symlink_inside_workspace_pointing_inside_is_allowed(tmp_path, monkeypatch):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    real_file = workspace / "real.rs"
    real_file.write_text("fn main() {}")
    link = workspace / "alias.rs"
    if not _try_symlink(link, real_file, monkeypatch):
        pytest.skip("symlink creation not available")
    # symlink within workspace → target within workspace: OK
    resolved = resolve_workspace_path(link, workspace)
    assert resolved == real_file.resolve()
