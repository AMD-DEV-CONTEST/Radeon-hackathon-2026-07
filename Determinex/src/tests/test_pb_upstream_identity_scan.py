"""Tests for pb_upstream_identity_scan.py -- the source-identity (8th provenance dimension)
check: does a "locked" submission's source carry manifest fields or copyright headers that
identify it as the real upstream project, rather than a model reimplementation?

Tier 1 tests use synthetic files (no network). Tier 2 tests use a REAL local git repo built
in a tmp dir (git clone of a local path is fast and needs no network) so the diff logic is
exercised against real git behavior, not mocked.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import pb_upstream_identity_scan as scan  # noqa: E402

# ---------- Tier 1: manifest scan ----------


def test_tier1_manifest_scan_catches_cargo_toml_repository_match(tmp_path):
    (tmp_path / "Cargo.toml").write_text(
        '[package]\nname = "dirble"\nrepository = "https://github.com/nccgroup/dirble"\n',
        encoding="utf-8",
    )
    result = scan.tier1_manifest_scan(tmp_path, "nccgroup/dirble")
    assert result["match_count"] == 1
    assert result["hits"][0]["field"] == "repository"


def test_tier1_manifest_scan_catches_go_mod_module_match(tmp_path):
    (tmp_path / "go.mod").write_text(
        "module github.com/mikefarah/yq/v4\n\ngo 1.21\n", encoding="utf-8"
    )
    result = scan.tier1_manifest_scan(tmp_path, "mikefarah/yq")
    assert result["match_count"] == 1
    assert result["hits"][0]["field"] == "module"


def test_tier1_manifest_scan_no_match_for_genuine_reimpl(tmp_path):
    (tmp_path / "Cargo.toml").write_text(
        '[package]\nname = "my-reimpl"\nauthors = ["Some Model <model@example.com>"]\n',
        encoding="utf-8",
    )
    result = scan.tier1_manifest_scan(tmp_path, "nccgroup/dirble")
    assert result["match_count"] == 0


def test_tier1_manifest_scan_ignores_manifests_outside_search(tmp_path):
    result = scan.tier1_manifest_scan(tmp_path, "nccgroup/dirble")
    assert result == {"hits": [], "match_count": 0}


# ---------- Tier 1: copyright header scan ----------


def test_tier1_header_scan_catches_verbatim_upstream_copyright(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    (src / "main.rs").write_text(
        "// This file is part of Dirble - https://www.github.com/nccgroup/dirble\n"
        "// Copyright (C) 2019 Izzy Whistlecroft\n"
        "fn main() {}\n",
        encoding="utf-8",
    )
    result = scan.tier1_header_scan(tmp_path, "nccgroup/dirble")
    assert result["match_count"] == 1


def test_tier1_header_scan_ignores_unrelated_copyright(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    (src / "vendored_zlib.h").write_text(
        "// Copyright (C) 1995-2024 Jean-loup Gailly and Mark Adler\n", encoding="utf-8"
    )
    result = scan.tier1_header_scan(tmp_path, "nccgroup/dirble")
    # header exists (recorded) but does not match this task's upstream identity
    assert result["match_count"] == 0
    assert len(result["hits"]) == 1
    assert result["hits"][0]["matches_upstream_identity"] is False


def test_tier1_header_scan_only_scans_known_source_extensions(tmp_path):
    (tmp_path / "README.md").write_text(
        "Copyright (C) 2019 Izzy Whistlecroft, part of nccgroup/dirble\n", encoding="utf-8"
    )
    result = scan.tier1_header_scan(tmp_path, "nccgroup/dirble")
    assert result == {"hits": [], "match_count": 0}


# ---------- verdict logic ----------


def test_verdict_header_match_is_proven():
    v = scan.compute_verdict({"match_count": 0}, {"match_count": 1}, {})
    assert v == "UPSTREAM_SOURCE_PROVEN"


def test_verdict_manifest_match_alone_is_strong_evidence():
    v = scan.compute_verdict({"match_count": 1}, {"match_count": 0}, {})
    assert v == "UPSTREAM_SOURCE_STRONG_EVIDENCE"


def test_verdict_high_tier2_overlap_is_strong_evidence():
    v = scan.compute_verdict(
        {"match_count": 0}, {"match_count": 0}, {"pct_identical_of_compared": 87.5}
    )
    assert v == "UPSTREAM_SOURCE_STRONG_EVIDENCE"


def test_verdict_low_tier2_overlap_is_likely_genuine():
    v = scan.compute_verdict(
        {"match_count": 0}, {"match_count": 0}, {"pct_identical_of_compared": 5.0}
    )
    assert v == "LIKELY_GENUINE_REIMPL"


def test_verdict_no_signal_at_all_is_inconclusive():
    v = scan.compute_verdict({"match_count": 0}, {"match_count": 0}, {})
    assert v == "INCONCLUSIVE"


def test_verdict_mid_range_tier2_overlap_is_inconclusive():
    v = scan.compute_verdict(
        {"match_count": 0}, {"match_count": 0}, {"pct_identical_of_compared": 40.0}
    )
    assert v == "INCONCLUSIVE"


# ---------- Tier 2: real local-git diff (no network) ----------


def _init_git_repo(path: Path, files: dict[str, str]) -> str:
    path.mkdir(parents=True, exist_ok=True)
    for rel, content in files.items():
        p = path / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        # newline="" disables Python's universal-newline translation on write -- without it,
        # Windows silently mangles an already-CRLF fixture string ("\r\n") into "\r\r\n".
        p.write_text(content, encoding="utf-8", newline="")
    subprocess.run(["git", "init", "-q"], cwd=path, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=path, check=True)
    subprocess.run(["git", "config", "user.name", "test"], cwd=path, check=True)
    subprocess.run(["git", "add", "-A"], cwd=path, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "init"], cwd=path, check=True)
    rev = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=path, capture_output=True, text=True, check=True
    )
    return rev.stdout.strip()


def test_tier2_upstream_diff_identical_files_score_100_percent(tmp_path, monkeypatch):
    upstream_src = tmp_path / "upstream_origin"
    commit = _init_git_repo(
        upstream_src, {"main.rs": "fn main() {}\n", "lib.rs": "pub fn x() {}\n"}
    )

    submission = tmp_path / "submission"
    submission.mkdir()
    (submission / "main.rs").write_text("fn main() {}\n", encoding="utf-8")
    (submission / "lib.rs").write_text("pub fn x() {}\n", encoding="utf-8")

    # Point the clone URL at a local path instead of github.com -- `git clone <path>` works
    # identically to a remote clone, letting this test run with no network.
    monkeypatch.setattr(scan, "_clone_url", lambda repository: str(upstream_src))
    result = scan.tier2_upstream_diff(submission, "unused/repo", commit, network=True)
    assert result.get("error") is None
    assert result["compared_file_count"] == 2
    assert result["identical_file_count"] == 2
    assert result["pct_identical_of_compared"] == 100.0


def test_tier2_upstream_diff_crlf_only_difference_still_counts_identical(tmp_path, monkeypatch):
    upstream_src = tmp_path / "upstream_origin"
    commit = _init_git_repo(
        upstream_src, {"main.rs": 'fn main() {\r\n    println!("hi");\r\n}\r\n'}
    )

    submission = tmp_path / "submission"
    submission.mkdir()
    (submission / "main.rs").write_text(
        'fn main() {\n    println!("hi");\n}\n', encoding="utf-8", newline=""
    )

    monkeypatch.setattr(scan, "_clone_url", lambda repository: str(upstream_src))
    result = scan.tier2_upstream_diff(submission, "unused/repo", commit, network=True)
    assert result.get("error") is None
    assert result["identical_file_count"] == 1
    assert result["differing_file_count"] == 0
    assert result["pct_identical_of_compared"] == 100.0


def test_tier2_upstream_diff_genuinely_different_content_scores_low(tmp_path, monkeypatch):
    upstream_src = tmp_path / "upstream_origin"
    commit = _init_git_repo(upstream_src, {"main.rs": "fn main() { real_upstream_logic(); }\n"})

    submission = tmp_path / "submission"
    submission.mkdir()
    (submission / "main.rs").write_text(
        "fn main() { totally_different_reimpl(); }\n", encoding="utf-8"
    )

    monkeypatch.setattr(scan, "_clone_url", lambda repository: str(upstream_src))
    result = scan.tier2_upstream_diff(submission, "unused/repo", commit, network=True)
    assert result.get("error") is None
    assert result["identical_file_count"] == 0
    assert result["differing_file_count"] == 1
    assert result["pct_identical_of_compared"] == 0.0


def test_tier2_upstream_diff_no_network_skips_cleanly(tmp_path):
    result = scan.tier2_upstream_diff(tmp_path, "some/repo", "deadbeef", network=False)
    assert result == {"skipped": True, "reason": "--no-network"}


def test_tier2_upstream_diff_bad_commit_reports_error(tmp_path):
    upstream_src = tmp_path / "upstream_origin"
    _init_git_repo(upstream_src, {"main.rs": "fn main() {}\n"})
    submission = tmp_path / "submission"
    submission.mkdir()
    result = scan.tier2_upstream_diff(submission, str(upstream_src), "0" * 40, network=True)
    assert "error" in result


# ---------- guard() reads the cache correctly ----------


def test_guard_flags_provable_upstream_and_strong_evidence(tmp_path, monkeypatch):
    verified_locks = tmp_path / "verified_locks.json"
    verified_locks.write_text('{"locks": {"a": {}, "b": {}, "c": {}, "d": {}}}', encoding="utf-8")
    cache_path = tmp_path / "cache.json"
    cache_path.write_text(
        '{"results": {'
        '"a": {"verdict": "UPSTREAM_SOURCE_PROVEN"}, '
        '"b": {"verdict": "UPSTREAM_SOURCE_STRONG_EVIDENCE"}, '
        '"c": {"verdict": "LIKELY_GENUINE_REIMPL"}, '
        '"d": {"error": "no submission.tar.gz"}'
        "}}",
        encoding="utf-8",
    )
    monkeypatch.setattr(scan, "VERIFIED_LOCKS", verified_locks)
    monkeypatch.setattr(scan, "SCAN_CACHE", cache_path)
    import contextlib
    import io

    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = scan.guard()
    assert rc == 1
    import json

    out = json.loads(buf.getvalue())
    flagged = {v["slug"] for v in out["violations"]}
    assert flagged == {"a", "b", "d"}  # c (genuine reimpl evidence) is NOT a violation


def test_guard_passes_clean_when_all_locks_are_genuine(tmp_path, monkeypatch):
    verified_locks = tmp_path / "verified_locks.json"
    verified_locks.write_text('{"locks": {"a": {}}}', encoding="utf-8")
    cache_path = tmp_path / "cache.json"
    cache_path.write_text(
        '{"results": {"a": {"verdict": "LIKELY_GENUINE_REIMPL"}}}', encoding="utf-8"
    )
    monkeypatch.setattr(scan, "VERIFIED_LOCKS", verified_locks)
    monkeypatch.setattr(scan, "SCAN_CACHE", cache_path)
    assert scan.guard() == 0


def test_guard_flags_never_scanned_entries(tmp_path, monkeypatch):
    verified_locks = tmp_path / "verified_locks.json"
    verified_locks.write_text('{"locks": {"never_scanned": {}}}', encoding="utf-8")
    cache_path = tmp_path / "cache.json"
    cache_path.write_text('{"results": {}}', encoding="utf-8")
    monkeypatch.setattr(scan, "VERIFIED_LOCKS", verified_locks)
    monkeypatch.setattr(scan, "SCAN_CACHE", cache_path)
    assert scan.guard() == 1


# ---------- corpus API integration (no filesystem crawling) ----------


def test_scan_slug_reports_error_when_corpus_has_no_provenance_entry(monkeypatch):
    monkeypatch.setattr(scan.corpus_api, "task_provenance", lambda q: None)
    result = scan.scan_slug("not-a-real-task", network=False)
    assert "error" in result
    assert "corpus API" in result["error"]


def test_live_scan_uses_corpus_api_not_filesystem_for_dirble():
    """Real integration smoke test: confirms task_provenance() (backed by the already-built
    canonical_tasks.json, not a fresh T:/Dev/ProgramBench filesystem crawl) resolves dirble's
    real repository+commit -- the exact fact this scanner's data path was built to stop
    re-deriving by hand."""
    import determinex_corpus_api as corpus_api

    prov = corpus_api.task_provenance("isona__dirble.e2dea9f")
    assert prov is not None
    assert prov.repository == "Isona/dirble"
    assert prov.commit == "e2dea9f16dee2ba208b455f6fa61ca109bf9de2b"
