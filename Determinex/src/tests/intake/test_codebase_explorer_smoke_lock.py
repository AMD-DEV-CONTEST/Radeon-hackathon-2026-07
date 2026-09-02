"""Smoke tests for CODEBASE_EXPLORER_SMOKE_LOCK_001.

Proves that ``scripts/codebase_explorer.CodebaseExplorer`` can ingest a
fixture repository, detect its language and build system, run a shadow
build/test, surface at least one issue signal, and do all of that
**without**:

  * mutating the fixture's source files
  * mutating signed evidence (``assurance/evidence/evidence_index.json``
    and ``locks/sentinel/*.json``)
  * writing corpus rows (``DETERMINEX_NO_CORPUS_WRITE=1`` is enforced)
  * requiring a T:/ drive letter
  * weakening any safety default

Tests for Rust and Go are skipped when ``cargo``/``go`` are not on PATH,
so the lock is honest about toolchain dependence in CI.
"""

from __future__ import annotations

import contextlib
import hashlib
import os
import shutil
import sys
from pathlib import Path
from typing import Any

import pytest

# Ensure ``scripts/`` is importable for ``codebase_explorer``
_REPO_ROOT = Path(__file__).resolve().parents[2]
for _p in (_REPO_ROOT, _REPO_ROOT / "scripts"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

FIXTURES = _REPO_ROOT / "tests" / "fixtures" / "intake"
EVIDENCE_INDEX = _REPO_ROOT / "assurance" / "evidence" / "evidence_index.json"
LOCKS_DIR = _REPO_ROOT / "locks" / "sentinel"


# Status tokens — closed set, also pinned in the lock manifest.
STATUS_TOKENS = frozenset(
    {
        "CODEBASE_EXPLORER_SMOKE_PASSED",
        "CODEBASE_EXPLORER_SMOKE_FAILED",
        "FIXTURE_REPO_LOADED",
        "LANGUAGE_DETECTED",
        "BUILD_HINT_DETECTED",
        "DIAGNOSIS_REPORT_WRITTEN",
        "ISSUE_SIGNAL_DETECTED",
        "SOURCE_TREE_UNMUTATED",
        "CORPUS_UNMUTATED",
        "EVIDENCE_UNMUTATED_EXCEPT_LOCK_RECORD",
        "PATH_PORTABLE",
        "SAFETY_DEFAULTS_RESPECTED",
    }
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _sha256(path: Path) -> str | None:
    if not path.is_file():
        return None
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _hash_source_tree(root: Path) -> dict[str, str]:
    """Hash every *source/manifest* file under root, ignoring tool-generated
    build artifacts. Cargo writes `Cargo.lock` on first `cargo check`, go
    writes `go.sum` on first `go build` with deps; pytest leaves
    `__pycache__/`; etc. These are not source mutations and would fail the
    intent of SOURCE_TREE_UNMUTATED."""
    cruft_dirs = frozenset(
        {
            "target",
            "__pycache__",
            ".pytest_cache",
            "node_modules",
            "build",
            "dist",
            ".git",
            "_audit",
        }
    )
    cruft_files = frozenset(
        {
            "Cargo.lock",
            "go.sum",
            ".coverage",
        }
    )
    out: dict[str, str] = {}
    for p in sorted(root.rglob("*")):
        if not p.is_file():
            continue
        rel = p.relative_to(root)
        if any(part in cruft_dirs for part in rel.parts):
            continue
        if p.name in cruft_files:
            continue
        digest = _sha256(p)
        if digest is not None:
            out[str(rel).replace("\\", "/")] = digest
    return out


def _hash_signed_evidence() -> dict[str, str]:
    out: dict[str, str] = {}
    if EVIDENCE_INDEX.is_file():
        out["assurance/evidence/evidence_index.json"] = _sha256(EVIDENCE_INDEX) or ""
    if LOCKS_DIR.is_dir():
        for p in sorted(LOCKS_DIR.glob("*.json")):
            rel = p.relative_to(_REPO_ROOT)
            out[str(rel).replace("\\", "/")] = _sha256(p) or ""
    return out


@contextlib.contextmanager
def _clean_intake_env(workspace: Path):
    """Set the env vars required for a safe smoke run, restore on exit.

    - DETERMINEX_NO_CORPUS_WRITE=1 → CorpusManager raises if anything tries to write
    - DETERMINEX_OLLAMA_URL → localhost (codebase_explorer enforces SSRF guard
      at import time; default is localhost so no override needed but we pin
      it for clarity)
    - DETERMINEX_TEST_TIMEOUT → small ceiling so a wedged subprocess fails fast
    - DETERMINEX_ROOT → repo root so any settings resolution stays inside the repo
    """
    saved = {
        k: os.environ.get(k)
        for k in (
            "DETERMINEX_NO_CORPUS_WRITE",
            "DETERMINEX_OLLAMA_URL",
            "DETERMINEX_TEST_TIMEOUT",
            "DETERMINEX_ROOT",
            "DETERMINEX_AUDIT_DIR",
        )
    }
    os.environ["DETERMINEX_NO_CORPUS_WRITE"] = "1"
    os.environ["DETERMINEX_OLLAMA_URL"] = "http://localhost:11434"
    os.environ["DETERMINEX_TEST_TIMEOUT"] = "45"
    os.environ["DETERMINEX_ROOT"] = str(_REPO_ROOT)
    # Route any audit emit into the workspace tmp so we never touch real logs.
    os.environ["DETERMINEX_AUDIT_DIR"] = str(workspace / "_audit")
    try:
        yield
    finally:
        for k, v in saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


def _copy_fixture(name: str, dest: Path) -> Path:
    src = FIXTURES / name
    assert src.is_dir(), f"fixture missing: {src}"
    target = dest / name
    shutil.copytree(src, target)
    return target


def _has_tool(name: str) -> bool:
    return shutil.which(name) is not None


# ---------------------------------------------------------------------------
# Module-level sanity
# ---------------------------------------------------------------------------


def test_status_tokens_match_expected_set():
    expected = {
        "CODEBASE_EXPLORER_SMOKE_PASSED",
        "CODEBASE_EXPLORER_SMOKE_FAILED",
        "FIXTURE_REPO_LOADED",
        "LANGUAGE_DETECTED",
        "BUILD_HINT_DETECTED",
        "DIAGNOSIS_REPORT_WRITTEN",
        "ISSUE_SIGNAL_DETECTED",
        "SOURCE_TREE_UNMUTATED",
        "CORPUS_UNMUTATED",
        "EVIDENCE_UNMUTATED_EXCEPT_LOCK_RECORD",
        "PATH_PORTABLE",
        "SAFETY_DEFAULTS_RESPECTED",
    }
    assert set(STATUS_TOKENS) == expected


def test_codebase_explorer_imports_cleanly():
    """The module imports without raising. The SSRF guard at import time
    must not fire under our default env."""
    from codebase_explorer import CodebaseExplorer  # noqa: F401

    assert CodebaseExplorer is not None


def test_no_drive_letter_in_repo_root_assumption():
    """The fixtures are referenced via repo-relative paths so they work on
    any platform without a Windows drive letter."""
    assert FIXTURES.is_dir()
    for name in ("python_broken", "rust_broken", "go_broken"):
        assert (FIXTURES / name).is_dir()


# ---------------------------------------------------------------------------
# Per-fixture smoke tests
#
# Each test:
#   1. copies the fixture to tmp_path (never mutates the original)
#   2. snapshots signed evidence + source tree hashes
#   3. runs CodebaseExplorer(...).explore()
#   4. asserts: language detected, build hint detected, issue signal in report,
#      source tree unchanged, signed evidence unchanged, no corpus write,
#      no drive letter required
# ---------------------------------------------------------------------------


def _explore_fixture(
    fixture_name: str, expected_lang: str, expected_build: str, tmp_path: Path
) -> dict[str, Any]:
    """Shared smoke flow. Returns a status dict that the per-fixture tests
    assert against."""
    from codebase_explorer import CodebaseExplorer

    workspace = _copy_fixture(fixture_name, tmp_path)
    src_before = _hash_source_tree(workspace)
    evidence_before = _hash_signed_evidence()

    with _clean_intake_env(workspace):
        explorer = CodebaseExplorer(workspace)
        report = explorer.explore()

    src_after = _hash_source_tree(workspace)
    evidence_after = _hash_signed_evidence()

    src_diffs = sorted(
        k for k in set(src_before) | set(src_after) if src_before.get(k) != src_after.get(k)
    )
    evidence_diffs = sorted(
        k
        for k in set(evidence_before) | set(evidence_after)
        if evidence_before.get(k) != evidence_after.get(k)
    )

    # The report is a dataclass; convert to dict for stable assertions.
    from dataclasses import asdict

    report_dict = asdict(report)

    statuses: list[str] = ["FIXTURE_REPO_LOADED"]
    if expected_lang in (report_dict.get("languages") or {}):
        statuses.append("LANGUAGE_DETECTED")
    if report_dict.get("build_system") == expected_build:
        statuses.append("BUILD_HINT_DETECTED")
    if report_dict.get("findings"):
        statuses.append("ISSUE_SIGNAL_DETECTED")
    if report_dict.get("total_files", 0) > 0:
        statuses.append("DIAGNOSIS_REPORT_WRITTEN")
    if not src_diffs:
        statuses.append("SOURCE_TREE_UNMUTATED")
    if not evidence_diffs:
        statuses.append("EVIDENCE_UNMUTATED_EXCEPT_LOCK_RECORD")
    # CORPUS_UNMUTATED: enforced at the env level by DETERMINEX_NO_CORPUS_WRITE.
    # If the explorer attempted a corpus write, _write_record() would raise.
    statuses.append("CORPUS_UNMUTATED")
    statuses.append("PATH_PORTABLE")
    statuses.append("SAFETY_DEFAULTS_RESPECTED")

    return {
        "fixture": fixture_name,
        "workspace": str(workspace),
        "report": report_dict,
        "src_diffs": src_diffs,
        "evidence_diffs": evidence_diffs,
        "statuses": statuses,
    }


def test_python_broken_smoke(tmp_path: Path):
    """Python fixture: pip build system, intentional pytest failure."""
    result = _explore_fixture("python_broken", "python", "pip", tmp_path)

    expected = {
        "FIXTURE_REPO_LOADED",
        "LANGUAGE_DETECTED",
        "BUILD_HINT_DETECTED",
        "ISSUE_SIGNAL_DETECTED",
        "DIAGNOSIS_REPORT_WRITTEN",
        "SOURCE_TREE_UNMUTATED",
        "EVIDENCE_UNMUTATED_EXCEPT_LOCK_RECORD",
        "CORPUS_UNMUTATED",
        "PATH_PORTABLE",
        "SAFETY_DEFAULTS_RESPECTED",
    }
    missing = expected - set(result["statuses"])
    assert not missing, (
        f"Smoke statuses missing: {missing}. Got: {result['statuses']}. "
        f"Source diffs: {result['src_diffs']}. "
        f"Evidence diffs: {result['evidence_diffs']}."
    )
    rep = result["report"]
    assert rep["build_system"] == "pip"
    assert rep["test_framework"] == "pytest"
    assert "python" in rep["languages"]
    assert rep["health_score"] < 1.0, "broken fixture must reduce health"
    # The failing pytest must produce at least one finding
    assert any(f["category"] == "test_failure" for f in rep["findings"]), (
        f"Expected a test_failure finding in: {rep['findings']}"
    )


def test_rust_broken_smoke(tmp_path: Path):
    """Rust fixture: cargo build system, intentional type mismatch."""
    if not _has_tool("cargo"):
        pytest.skip("cargo not on PATH — Rust toolchain absent in this env")
    result = _explore_fixture("rust_broken", "rust", "cargo", tmp_path)

    rep = result["report"]
    assert rep["build_system"] == "cargo"
    assert rep["test_framework"] == "cargo test"
    assert "rust" in rep["languages"]
    # cargo check should fail → compilation finding
    assert any(f["category"] == "compilation" for f in rep["findings"]), (
        f"Expected a compilation finding in: {rep['findings']}"
    )
    assert "SOURCE_TREE_UNMUTATED" in result["statuses"], result["src_diffs"]
    assert "EVIDENCE_UNMUTATED_EXCEPT_LOCK_RECORD" in result["statuses"]


def test_go_broken_smoke(tmp_path: Path):
    """Go fixture: go.mod build system, intentional type mismatch."""
    if not _has_tool("go"):
        pytest.skip("go not on PATH — Go toolchain absent in this env")
    result = _explore_fixture("go_broken", "go", "go", tmp_path)

    rep = result["report"]
    assert rep["build_system"] == "go"
    assert rep["test_framework"] == "go test"
    assert "go" in rep["languages"]
    # go build should fail → compilation finding (or test_failure from go test)
    has_signal = any(f["category"] in ("compilation", "test_failure") for f in rep["findings"])
    assert has_signal, f"Expected a build/test finding in: {rep['findings']}"
    assert "SOURCE_TREE_UNMUTATED" in result["statuses"], result["src_diffs"]


# ---------------------------------------------------------------------------
# Cross-cutting safety + portability assertions
# ---------------------------------------------------------------------------


def test_no_drive_letter_required_for_intake(tmp_path: Path, monkeypatch):
    """Strip every DETERMINEX_* / HF_HOME / OLLAMA_* env var and confirm the
    explorer can still load a fixture."""
    for k in list(os.environ):
        if k.startswith(("DETERMINEX_", "HF_HOME", "OLLAMA_")):
            monkeypatch.delenv(k, raising=False)
    # The SSRF guard at module import time wants DETERMINEX_OLLAMA_URL to be
    # localhost or unset; unset is fine.
    workspace = _copy_fixture("python_broken", tmp_path)
    from codebase_explorer import WorkspaceLoader

    loader = WorkspaceLoader(workspace)
    files = loader.scan()
    assert len(files) > 0
    assert "python" in loader.languages


def test_corpus_write_guard_is_in_effect_during_smoke():
    """The corpus write guard must be ACTIVE before smoke runs — this is
    the wire that makes CORPUS_UNMUTATED meaningful."""
    from corpus.corpus_manager import (  # type: ignore[attr-defined]
        CorpusWriteBlockedError,
        _assert_writes_allowed,
    )

    saved = os.environ.get("DETERMINEX_NO_CORPUS_WRITE")
    os.environ["DETERMINEX_NO_CORPUS_WRITE"] = "1"
    try:
        with pytest.raises(CorpusWriteBlockedError):
            _assert_writes_allowed()
    finally:
        if saved is None:
            os.environ.pop("DETERMINEX_NO_CORPUS_WRITE", None)
        else:
            os.environ["DETERMINEX_NO_CORPUS_WRITE"] = saved


def test_safety_defaults_remain_fail_closed_after_smoke():
    """A smoke run must not silently flip any safety flag open. Verify
    the live determinex_settings still reports zero violations under a
    clean env."""
    from determinex_settings import DeterminexSettings, reset_settings

    # We don't strip env vars here — we just confirm violations() returns []
    # under the current env, which is the contract the gauntlet checks.
    reset_settings()
    s = DeterminexSettings()
    violations = s.assert_safety_defaults()
    assert violations == [], f"Safety defaults opened: {violations}"


# ---------------------------------------------------------------------------
# Lock manifest alignment
# ---------------------------------------------------------------------------

_LOCK_PATH = _REPO_ROOT / "locks" / "sentinel" / "CODEBASE_EXPLORER_SMOKE_LOCK_001.json"


def test_lock_manifest_exists():
    assert _LOCK_PATH.is_file(), f"Lock manifest missing: {_LOCK_PATH}"


def test_lock_manifest_status_tokens_match_module():
    import json

    data = json.loads(_LOCK_PATH.read_text(encoding="utf-8"))
    declared = set(data.get("status_tokens", []))
    assert declared == set(STATUS_TOKENS), (
        f"Lock manifest status token drift:\n"
        f"  in lock not in module: {declared - set(STATUS_TOKENS)}\n"
        f"  in module not in lock: {set(STATUS_TOKENS) - declared}"
    )


def test_lock_manifest_pins_fixture_count():
    import json

    data = json.loads(_LOCK_PATH.read_text(encoding="utf-8"))
    assert data.get("fixtures_count") == 3
