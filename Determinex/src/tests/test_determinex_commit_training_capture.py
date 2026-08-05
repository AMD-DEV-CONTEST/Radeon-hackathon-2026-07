"""tests/test_determinex_commit_training_capture.py

Gap found 2026-07-20: logs/hive/budget.py's queue_for_training() only fires
for Hive DAG build sessions and had been dormant since 2026-04-25; huge
amounts of real, compiler/test-verified work (this whole session's OSS
integration fixes, the frontend hydration fix, the hackathon kernel work,
the corpus fixes) went uncaptured because none of it ran through that one
pipeline. This module captures at commit granularity instead, classifying
quality from the verification evidence the commit message itself already
states (this project's own established convention).
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
for _p in (_ROOT, _ROOT / "scripts"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import determinex_commit_training_capture as cap  # noqa: E402


def test_classify_quality_recognizes_matching_pass_count():
    assert cap.classify_quality("Full suite: 4540/4540 passing, all green") == "training_ready"


def test_classify_quality_recognizes_zero_violations():
    assert cap.classify_quality("governance gate: 0 violations found") == "training_ready"


def test_classify_quality_recognizes_all_tests_pass_phrasing():
    assert cap.classify_quality("ran the suite; all 20 tests pass cleanly") == "training_ready"


def test_classify_quality_no_evidence_is_unverified():
    assert cap.classify_quality("fix typo in readme") == "unverified"


def test_classify_quality_wip_marker_excluded():
    assert cap.classify_quality("WIP: half-done refactor, do not merge yet") == "excluded"


def test_classify_quality_mismatched_pass_count_not_matched():
    """N/M where N != M (e.g. a FAILING count, "10 failed, 4540 passed") must
    not be misread as passing evidence just because digits and "pass" are
    both present nearby."""
    assert cap.classify_quality("10 failed, 4540 passed") == "unverified"


def _make_repo(tmp_path: Path) -> Path:
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=tmp_path, check=True)
    (tmp_path / "a.txt").write_text("hello\n", encoding="utf-8")
    subprocess.run(["git", "add", "a.txt"], cwd=tmp_path, check=True)
    subprocess.run(
        ["git", "commit", "-q", "-m", "feat: add a.txt\n\nAll 3 tests pass, 0 violations."],
        cwd=tmp_path,
        check=True,
    )
    return tmp_path


def test_capture_commit_writes_a_real_entry(tmp_path, monkeypatch):
    repo = _make_repo(tmp_path)
    monkeypatch.setattr(cap, "ROOT", repo)
    out = repo / "logs" / "commit_training_corpus.jsonl"
    monkeypatch.setattr(cap, "OUT_PATH", out)

    result = cap.capture_commit("HEAD")
    assert result["quality"] == "training_ready"

    lines = out.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    entry = json.loads(lines[0])
    assert entry["quality"] == "training_ready"
    assert "add a.txt" in entry["message"]
    assert "a.txt" in entry["diff"]
    assert entry["diff_truncated"] is False


def test_stats_missing_file(tmp_path, monkeypatch):
    monkeypatch.setattr(cap, "OUT_PATH", tmp_path / "nope.jsonl")
    s = cap.stats()
    assert s == {"exists": False}


def test_stats_counts_by_quality(tmp_path, monkeypatch):
    out = tmp_path / "corpus.jsonl"
    rows = [
        {"quality": "training_ready"},
        {"quality": "training_ready"},
        {"quality": "unverified"},
        {"quality": "excluded"},
    ]
    out.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")
    monkeypatch.setattr(cap, "OUT_PATH", out)

    s = cap.stats()
    assert s["exists"] is True
    assert s["total"] == 4
    assert s["by_quality"] == {"training_ready": 2, "unverified": 1, "excluded": 1}


# ---------------------------------------------------------------------------
# _safe_diff -- found live on a real 2394-commit backfill: 3 commits' full
# diffs fail deterministically (not transiently) because a file they touch
# has an "unsupported filetype" per some local git textconv/diff filter
# config, well after git has already produced most of a large diff. The
# commit's message/stat are still real, useful signal -- must not be
# dropped just because the diff itself is unreadable.
# ---------------------------------------------------------------------------


def test_safe_diff_returns_diff_and_false_on_success(tmp_path, monkeypatch):
    monkeypatch.setattr(cap, "ROOT", tmp_path)

    def fake_run(cmd):
        return "diff --git a/x b/x\n+hello\n"

    monkeypatch.setattr(cap, "_run", fake_run)
    diff, failed = cap._safe_diff("deadbeef")
    assert failed is False
    assert "hello" in diff


def test_safe_diff_falls_back_on_calledprocesserror(monkeypatch, capsys):
    def fake_run(cmd):
        raise subprocess.CalledProcessError(
            128,
            cmd,
            output="",
            stderr="E: unsupported filetype .../page.doc\nfatal: unable to read files to diff",
        )

    monkeypatch.setattr(cap, "_run", fake_run)
    diff, failed = cap._safe_diff("deadbeef")
    assert failed is True
    assert diff == ""
    err = capsys.readouterr().err
    assert "diff capture failed" in err


def test_capture_commit_keeps_entry_when_diff_capture_fails(tmp_path, monkeypatch):
    repo = _make_repo(tmp_path)
    monkeypatch.setattr(cap, "ROOT", repo)
    out = repo / "logs" / "commit_training_corpus.jsonl"
    monkeypatch.setattr(cap, "OUT_PATH", out)

    def fake_safe_diff(sha):
        return "", True

    monkeypatch.setattr(cap, "_safe_diff", fake_safe_diff)
    result = cap.capture_commit("HEAD")
    assert result["diff_bytes"] == 0

    entry = json.loads(out.read_text(encoding="utf-8").splitlines()[0])
    assert entry["diff_capture_failed"] is True
    assert entry["diff"] == ""
    assert "add a.txt" in entry["message"]  # message/stat still captured
