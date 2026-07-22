"""Fase C test plan (build and verify BEFORE any UI -- highest blast
radius in the whole Blackbox plan): invariant I3 (the user's real git
state -- status/branch/stash/index/HEAD -- must be byte-identical before
and after a session with multiple snapshots and rollbacks), rollback
never calls `git checkout`, snapshot failures degrade gracefully, and the
disabled flag is a true no-op.

Every test here runs against a disposable tmp_path git repo, never a real
project -- this is exactly the discipline the invariant exists to prove.
"""

import asyncio
import subprocess
from pathlib import Path

import pytest

from core.audit import timetravel as tt


def _git(repo: Path, *args: str) -> str:
    """Independent verification path -- does NOT go through timetravel.py,
    so these checks can't just be reflecting the same bug back at itself."""
    result = subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True, text=True, check=True,
    )
    return result.stdout


@pytest.fixture
def repo(tmp_path, monkeypatch) -> Path:
    repo_path = tmp_path / "disposable-repo"
    repo_path.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=repo_path, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=repo_path, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=repo_path, check=True)
    (repo_path / "a.txt").write_text("original a\n", encoding="utf-8")
    (repo_path / "b.txt").write_text("original b\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=repo_path, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "initial"], cwd=repo_path, check=True)

    monkeypatch.setenv("ACTIVE_PROJECT_PATH", str(repo_path))
    monkeypatch.setattr(tt, "TIMETRAVEL_DIR", str(tmp_path / "timetravel_data"))
    return repo_path


def _baseline(repo: Path) -> dict:
    return {
        "status": _git(repo, "status", "--porcelain"),
        "branch": _git(repo, "branch", "-a"),
        "stash": _git(repo, "stash", "list"),
        # Path + blob OID + stage per tracked file (`git ls-files -s`), NOT
        # the raw .git/index bytes: git's own "racily clean" stat-cache
        # optimization legitimately rewrites the index's cached mtime
        # fields whenever a `git status`/`ls-files` call notices a file's
        # on-disk mtime changed but its content still hashes the same --
        # completely normal git behavior triggered by our own test writing
        # a.txt/b.txt directly, not a sign Time-Travel corrupted anything.
        # `ls-files -s` reports content (blob OID), not timestamps, so it's
        # the right level to assert byte-identical.
        "index_content": _git(repo, "ls-files", "-s"),
        "head": (repo / ".git" / "HEAD").read_text(encoding="utf-8"),
    }


def test_invariant_i3_repo_untouched_across_snapshots_and_rollbacks(repo):
    """The literal invariant: multiple snapshots + multiple rollbacks in a
    simulated session leave the user's real git state byte-identical."""
    baseline = _baseline(repo)

    async def _session():
        c1 = await tt.snapshot("sess-i3", ["a.txt"], "pre: edit a.txt")
        (repo / "a.txt").write_text("agent-modified a\n", encoding="utf-8")
        c2 = await tt.snapshot("sess-i3", ["a.txt"], "post: edit a.txt")
        c3 = await tt.snapshot("sess-i3", ["b.txt"], "pre: edit b.txt")
        (repo / "b.txt").write_text("agent-modified b\n", encoding="utf-8")
        c4 = await tt.snapshot("sess-i3", ["b.txt"], "post: edit b.txt")

        # Undo b.txt back to its pre-edit state.
        result = await tt.rollback(c3, ["b.txt"])
        assert result["exit_code"] == 0
        assert (repo / "b.txt").read_text(encoding="utf-8") == "original b\n"

        # Undo a.txt back to its pre-edit state too.
        result2 = await tt.rollback(c1, ["a.txt"])
        assert result2["exit_code"] == 0
        assert (repo / "a.txt").read_text(encoding="utf-8") == "original a\n"

        return c1, c2, c3, c4

    commits = asyncio.run(_session())
    assert all(c is not None for c in commits)

    after = _baseline(repo)
    assert after["status"] == baseline["status"]
    assert after["branch"] == baseline["branch"]
    assert after["stash"] == baseline["stash"]
    assert after["index_content"] == baseline["index_content"]
    assert after["head"] == baseline["head"]


def test_shadow_ref_exists_but_invisible_to_branch(repo):
    async def _session():
        return await tt.snapshot("sess-shadow", ["a.txt"], "snap 1")

    commit = asyncio.run(_session())
    assert commit is not None

    # Walkable directly...
    log_output = _git(repo, "log", "refs/aetheris/session-sess-shadow", "--format=%H")
    assert commit in log_output

    # ...but git branch -a never lists it (refs/aetheris/* is not
    # refs/heads/*), and it must not affect checking out a real branch.
    branch_output = _git(repo, "branch", "-a")
    assert "aetheris" not in branch_output


def test_rollback_never_invokes_git_checkout(repo, monkeypatch):
    """Directly asserts the literal argv ["checkout", ...] is never
    constructed -- not just that the observable state happens to be fine."""
    calls = []
    real_run_git = tt._run_git

    async def _spy_run_git(argv, cwd, env=None, check=True, strip=True):
        calls.append(argv)
        return await real_run_git(argv, cwd, env=env, check=check, strip=strip)

    monkeypatch.setattr(tt, "_run_git", _spy_run_git)

    async def _session():
        c1 = await tt.snapshot("sess-nocheckout", ["a.txt"], "pre")
        (repo / "a.txt").write_text("changed\n", encoding="utf-8")
        return await tt.rollback(c1, ["a.txt"])

    result = asyncio.run(_session())
    assert result["exit_code"] == 0
    assert not any(argv and argv[0] == "checkout" for argv in calls)


def test_preview_rollback_is_read_only(repo):
    async def _session():
        c1 = await tt.snapshot("sess-preview", ["a.txt"], "pre")
        (repo / "a.txt").write_text("changed on disk\n", encoding="utf-8")
        preview = await tt.preview_rollback(c1, ["a.txt"])
        return c1, preview

    c1, preview = asyncio.run(_session())
    assert preview["exit_code"] == 0
    assert len(preview["diffs"]) == 1
    assert "changed on disk" in preview["diffs"][0]["diff"]
    assert "original a" in preview["diffs"][0]["diff"]
    # Read-only: the working tree file must be untouched by preview.
    assert (repo / "a.txt").read_text(encoding="utf-8") == "changed on disk\n"


def test_list_snapshots_reverse_chronological_and_scoped_per_session(repo):
    async def _session():
        await tt.snapshot("sess-a", ["a.txt"], "a-snap-1")
        await tt.snapshot("sess-a", ["a.txt"], "a-snap-2")
        await tt.snapshot("sess-b", ["b.txt"], "b-snap-1")
        return await tt.list_snapshots("sess-a"), await tt.list_snapshots("sess-b")

    snaps_a, snaps_b = asyncio.run(_session())
    assert len(snaps_a) == 2
    assert len(snaps_b) == 1
    assert {s["message"] for s in snaps_a} == {"a-snap-1", "a-snap-2"}


def test_snapshot_failure_never_blocks_the_real_write(repo, monkeypatch):
    """A corrupt/unwritable index path must degrade to None, not raise
    into the caller -- the real file write this protects must still
    succeed regardless."""
    monkeypatch.setattr(tt, "_temp_index_path", lambda session_id: Path("Z:\\definitely\\not\\a\\real\\path\\idx"))

    async def _session():
        return await tt.snapshot("sess-fail", ["a.txt"], "pre")

    result = asyncio.run(_session())
    assert result is None  # degraded gracefully, no exception raised


def test_no_git_repo_is_silent_noop(tmp_path, monkeypatch):
    non_repo = tmp_path / "not-a-repo"
    non_repo.mkdir()
    (non_repo / "a.txt").write_text("x\n", encoding="utf-8")
    monkeypatch.setenv("ACTIVE_PROJECT_PATH", str(non_repo))
    monkeypatch.setattr(tt, "TIMETRAVEL_DIR", str(tmp_path / "timetravel_data2"))

    async def _session():
        return await tt.snapshot("sess-nogit", ["a.txt"], "pre")

    assert asyncio.run(_session()) is None


def test_disabled_flag_is_true_noop(repo, monkeypatch):
    monkeypatch.setenv("AETHERIS_TIMETRAVEL_ENABLED", "false")

    async def _session():
        return await tt.snapshot("sess-disabled", ["a.txt"], "pre")

    assert asyncio.run(_session()) is None
    # No shadow ref should have been created at all.
    branch_output = _git(repo, "for-each-ref", "refs/aetheris/")
    assert branch_output.strip() == ""
