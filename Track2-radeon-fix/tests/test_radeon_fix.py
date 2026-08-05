from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest

import radeon_fix


def _git(repo: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )


@pytest.fixture
def git_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "sample-repo"
    repo.mkdir()
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "test@example.com")
    _git(repo, "config", "user.name", "Test")
    (repo / "buggy.py").write_text("def clamp(value, lo, hi):\n    return hi\n", encoding="utf-8")
    _git(repo, "add", ".")
    _git(repo, "commit", "-q", "-m", "initial")
    return repo


class StubRunner:
    captured: dict = {}

    def __init__(self, **kwargs):
        self.kwargs = kwargs
        StubRunner.captured = kwargs

    def run_task(self, issue: str):
        return {
            "conversations": [],
            "completed": True,
            "api_calls": 3,
            "metadata": {
                "model": self.kwargs["model"],
                "context_variant": self.kwargs["context_variant"],
                "json_mode": self.kwargs["json_mode"],
                "controller_policy": self.kwargs["controller_policy"],
                "verifier_mode": self.kwargs["verifier_mode"],
                "edit_protocol": self.kwargs["edit_protocol"],
                "context_provider": "aider-repomap",
                "context_available": True,
                "context_refresh": ({"attempted": True, "available": True},),
                "final_patch": (
                    "diff --git a/buggy.py b/buggy.py\n"
                    "--- a/buggy.py\n+++ b/buggy.py\n"
                    "@@ -1 +1 @@\n-    return hi\n+    return min(max(value, lo), hi)\n"
                ),
                "changed_files": ["buggy.py"],
                "wall_time_ms": 1234.5,
                "api": {"usage": {"total_tokens": 1000}},
                "tool_calls": 4,
                "edit_attempts": 1,
                "replace_attempts": 1,
                "replace_successes": 1,
                "patch_apply_results": [True],
                "verifier": {"verdict": "accept", "mode": "V1R1"},
            },
        }


@pytest.fixture(autouse=True)
def _stub_dependencies(monkeypatch):
    monkeypatch.setattr(radeon_fix, "MiniSWERunner", StubRunner)
    monkeypatch.setattr(
        radeon_fix,
        "extract_context",
        lambda *a, **k: ("repo map", {"available": True, "chars": 8}),
    )
    monkeypatch.setattr(radeon_fix, "read_gpu_metrics", lambda: {})
    monkeypatch.setenv("TRACK2_BASE_URL", "http://127.0.0.1:8000/v1")
    monkeypatch.setenv("TRACK2_MODEL", "Qwen3-14B-BF16")


def test_help_and_version(capsys):
    assert radeon_fix.main(["--help"]) == 0
    assert radeon_fix.main(["--version"]) == 0
    assert "radeon-fix 0.1.0" in capsys.readouterr().out


def test_missing_issue_is_error(capsys):
    assert radeon_fix.main(["--repo", "/tmp"]) == 2
    assert "missing issue" in capsys.readouterr().err


def test_non_git_repo_is_error(tmp_path, capsys):
    assert radeon_fix.main(["--repo", str(tmp_path), "--issue", "fix it"]) == 2
    assert "not a git repository" in capsys.readouterr().err


def test_remote_endpoint_rejected(tmp_path, capsys):
    os.environ.pop("TRACK2_BASE_URL", None)
    assert (
        radeon_fix.main(
            [
                "--repo",
                str(tmp_path),
                "--issue",
                "fix it",
                "--base-url",
                "https://api.example.com/v1",
            ]
        )
        == 2
    )
    assert "local OpenAI-compatible endpoint" in capsys.readouterr().err


def test_run_produces_artifacts_and_leaves_repo_untouched(git_repo, tmp_path, capsys):
    output = tmp_path / "out"
    before = subprocess.run(
        ["git", "-C", str(git_repo), "status", "--porcelain"],
        check=True,
        stdout=subprocess.PIPE,
        text=True,
    ).stdout
    assert before == ""

    exit_code = radeon_fix.main(
        [
            "--repo",
            str(git_repo),
            "--issue",
            "clamp should preserve the lower bound",
            "--output-dir",
            str(output),
        ]
    )

    assert exit_code == 0
    assert (output / "patch.diff").exists()
    assert (output / "report.md").exists()
    assert (output / "trajectory.json").exists()
    assert (output / "run.json").exists()
    run_info = json.loads((output / "run.json").read_text(encoding="utf-8"))
    assert run_info["exit_code"] == 0
    assert "C1R1" in run_info["context"]
    assert "diff --git" in (output / "patch.diff").read_text(encoding="utf-8")
    after = subprocess.run(
        ["git", "-C", str(git_repo), "status", "--porcelain"],
        check=True,
        stdout=subprocess.PIPE,
        text=True,
    ).stdout
    assert after == ""
    assert StubRunner.captured["context_variant"] == "C1"
    assert StubRunner.captured["json_mode"] == "J3"
    assert StubRunner.captured["controller_policy"] == "A1"
    assert StubRunner.captured["verifier_mode"] == "V1R1"
    assert StubRunner.captured["edit_protocol"] == "replace-v2"


def test_no_patch_maps_to_exit_1(git_repo, tmp_path, monkeypatch):
    class EmptyRunner(StubRunner):
        def run_task(self, issue: str):
            result = super().run_task(issue)
            result["metadata"]["final_patch"] = ""
            return result

    monkeypatch.setattr(radeon_fix, "MiniSWERunner", EmptyRunner)
    assert (
        radeon_fix.main(
            ["--repo", str(git_repo), "--issue", "fix", "--output-dir", str(tmp_path / "out2")]
        )
        == 1
    )
