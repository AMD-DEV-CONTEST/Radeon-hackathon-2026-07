"""tests/test_determinex_setup_git_hooks.py — install_git_hooks().

Found 2026-07-20: the repo's git hooks (the pre-existing eval_index.json
integrity gate, and a new post-commit hook that keeps the corpus semantic
embeddings cache in sync) only ever existed as untracked files in
.git/hooks/ -- never survived a fresh clone. scripts/git-hooks/ is now the
tracked source of truth; install_git_hooks() copies it into .git/hooks/
with the executable bit set.
"""

from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
for _p in (_ROOT, _ROOT / "scripts"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import determinex_setup as setup  # noqa: E402


def test_install_git_hooks_copies_tracked_hooks(tmp_path, monkeypatch):
    src_dir = tmp_path / "git-hooks"
    src_dir.mkdir()
    (src_dir / "pre-commit").write_text("#!/bin/sh\necho pre\n", encoding="utf-8")
    (src_dir / "post-commit").write_text("#!/bin/sh\necho post\n", encoding="utf-8")

    dst_dir = tmp_path / ".git" / "hooks"
    dst_dir.mkdir(parents=True)

    monkeypatch.setattr(setup, "_SCRIPTS_DIR", tmp_path)
    monkeypatch.setattr(setup, "_ROOT", tmp_path / ".git" / "..")

    installed = setup.install_git_hooks()

    assert set(installed) == {"pre-commit", "post-commit"}
    assert (dst_dir / "pre-commit").read_text(encoding="utf-8") == "#!/bin/sh\necho pre\n"
    assert (dst_dir / "post-commit").read_text(encoding="utf-8") == "#!/bin/sh\necho post\n"


def test_install_git_hooks_sets_executable_bit(tmp_path, monkeypatch):
    """os.chmod's POSIX execute bit is meaningful on Linux/macOS; Windows has
    no real equivalent and silently no-ops it (confirmed live: chmod 0o755
    on this platform does not set 0o100 in stat().st_mode). The function's
    job is just to attempt it without crashing -- verified via the mocked
    os.chmod call itself, not the OS's actual (platform-dependent) result."""
    src_dir = tmp_path / "git-hooks"
    src_dir.mkdir()
    (src_dir / "pre-commit").write_text("#!/bin/sh\necho pre\n", encoding="utf-8")

    dst_dir = tmp_path / ".git" / "hooks"
    dst_dir.mkdir(parents=True)

    monkeypatch.setattr(setup, "_SCRIPTS_DIR", tmp_path)
    monkeypatch.setattr(setup, "_ROOT", tmp_path / ".git" / "..")

    chmod_calls = []
    real_chmod = setup.os.chmod

    def spy_chmod(path, mode):
        chmod_calls.append((Path(path).name, mode))
        return real_chmod(path, mode)

    monkeypatch.setattr(setup.os, "chmod", spy_chmod)
    setup.install_git_hooks()

    assert ("pre-commit", 0o755) in chmod_calls


def test_install_git_hooks_missing_source_dir_is_a_noop(tmp_path, monkeypatch):
    dst_dir = tmp_path / ".git" / "hooks"
    dst_dir.mkdir(parents=True)
    monkeypatch.setattr(setup, "_SCRIPTS_DIR", tmp_path / "no-such-scripts-dir")
    monkeypatch.setattr(setup, "_ROOT", tmp_path / ".git" / "..")

    installed = setup.install_git_hooks()
    assert installed == []


def test_install_git_hooks_overwrites_existing_hook(tmp_path, monkeypatch):
    src_dir = tmp_path / "git-hooks"
    src_dir.mkdir()
    (src_dir / "pre-commit").write_text("#!/bin/sh\necho new\n", encoding="utf-8")

    dst_dir = tmp_path / ".git" / "hooks"
    dst_dir.mkdir(parents=True)
    (dst_dir / "pre-commit").write_text("#!/bin/sh\necho stale-local-version\n", encoding="utf-8")

    monkeypatch.setattr(setup, "_SCRIPTS_DIR", tmp_path)
    monkeypatch.setattr(setup, "_ROOT", tmp_path / ".git" / "..")

    setup.install_git_hooks()

    assert (dst_dir / "pre-commit").read_text(encoding="utf-8") == "#!/bin/sh\necho new\n"


def test_real_tracked_hooks_directory_exists_and_matches_installed():
    """Sanity check against the real repo state, not just synthetic fixtures."""
    src_dir = _ROOT / "scripts" / "git-hooks"
    assert src_dir.is_dir()
    assert (src_dir / "pre-commit").is_file()
    assert (src_dir / "post-commit").is_file()
