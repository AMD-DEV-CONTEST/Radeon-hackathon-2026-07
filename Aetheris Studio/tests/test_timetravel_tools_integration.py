"""Fase C.2 integration check: _run_write_file/_run_edit_file actually
create Time-Travel snapshots when called with a real session_id, against
a disposable git repo (not just timetravel.py's own unit tests)."""

import asyncio
import subprocess
from pathlib import Path

import pytest

from core.audit import timetravel as tt
from core.utils import tools


@pytest.fixture
def repo(tmp_path, monkeypatch) -> Path:
    repo_path = tmp_path / "disposable-repo"
    repo_path.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=repo_path, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=repo_path, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=repo_path, check=True)
    (repo_path / "existing.py").write_text("x = 1\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=repo_path, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "initial"], cwd=repo_path, check=True)

    monkeypatch.setenv("ACTIVE_PROJECT_PATH", str(repo_path))
    monkeypatch.setattr(tt, "TIMETRAVEL_DIR", str(tmp_path / "timetravel_data"))
    return repo_path


def test_write_file_creates_snapshots_and_is_undoable(repo):
    async def _run():
        result = await tools._run_write_file(
            "existing.py\ny = 2\n", owner="tester", session_id="sess-integ",
        )
        assert result["exit_code"] == 0
        snapshots = await tt.list_snapshots("sess-integ")
        return snapshots

    snapshots = asyncio.run(_run())
    assert len(snapshots) == 2
    # git log lists newest-first: post (the later commit) comes before pre.
    assert snapshots[0]["message"].startswith("post:")
    assert snapshots[1]["message"].startswith("pre:")
    pre_commit = snapshots[1]["commit"]

    # The pre-snapshot must restore the file to its state BEFORE this write.
    async def _undo():
        return await tt.rollback(pre_commit, ["existing.py"])

    result = asyncio.run(_undo())
    assert result["exit_code"] == 0
    assert (repo / "existing.py").read_text(encoding="utf-8") == "x = 1\n"


def test_edit_file_creates_snapshots(repo):
    async def _run():
        content = "existing.py\n<<<FIND>>>\nx = 1\n<<<REPLACE>>>\nx = 99\n<<<END>>>"
        result = await tools._run_edit_file(content, owner="tester", session_id="sess-edit")
        assert result["exit_code"] == 0
        return await tt.list_snapshots("sess-edit")

    snapshots = asyncio.run(_run())
    assert len(snapshots) == 2
    assert (repo / "existing.py").read_text(encoding="utf-8") == "x = 99\n"


def test_rollback_action_tool_end_to_end(repo):
    async def _run():
        await tools._run_write_file("existing.py\ny = 2\n", owner="tester", session_id="sess-rb")
        snapshots = await tt.list_snapshots("sess-rb")
        pre_commit = next(s["commit"] for s in snapshots if s["message"].startswith("pre:"))
        rollback_content = f"{pre_commit}\nexisting.py"
        return await tools._run_rollback_action(rollback_content, owner="tester", session_id="sess-rb")

    result = asyncio.run(_run())
    assert result["exit_code"] == 0
    assert (repo / "existing.py").read_text(encoding="utf-8") == "x = 1\n"


def test_write_file_without_session_id_skips_snapshots_but_still_writes(repo):
    """No session_id (e.g. an unscoped/legacy caller) must still perform
    the real write -- Time-Travel is additive, never a hard dependency."""
    async def _run():
        return await tools._run_write_file("existing.py\nz = 3\n", owner="tester", session_id=None)

    result = asyncio.run(_run())
    assert result["exit_code"] == 0
    assert (repo / "existing.py").read_text(encoding="utf-8") == "z = 3\n"
