"""Tests for BUILD_ADAPTER_REGISTRY_LOCK_001.

Proves the BuildAdapter protocol + BuildAdapterRegistry:
  * Each builtin adapter detects its own rung-1 fixture
  * Registry selection is deterministic on single-match and multi-match
  * Unknown / empty workspace returns UnknownAdapter explicitly (not a crash)
  * The new adapter contract preserves the legacy
    ``codebase_explorer.detect_build_system`` return shape for the rung-1
    fixtures (CodebaseExplorer.explore() compatibility)
  * Source tree, corpus, and signed evidence remain unmutated
  * No T:/ drive letter required; safety defaults stay fail-closed
"""

from __future__ import annotations

import hashlib
import os
import shutil
import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
for _p in (_REPO_ROOT, _REPO_ROOT / "scripts"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

FIXTURES = _REPO_ROOT / "tests" / "fixtures" / "intake"
EVIDENCE_INDEX = _REPO_ROOT / "assurance" / "evidence" / "evidence_index.json"
LOCKS_DIR = _REPO_ROOT / "locks" / "sentinel"


STATUS_TOKENS = frozenset(
    {
        "BUILD_ADAPTER_REGISTRY_READY",
        "BUILD_ADAPTER_DETECTED",
        "BUILD_ADAPTER_UNKNOWN",
        "BUILD_ADAPTER_MULTI_MATCH",
        "TEST_DISCOVERY_READY",
        "SHADOW_BUILD_READY",
        "FAILURE_PARSE_READY",
        "CODEBASE_EXPLORER_COMPAT_PRESERVED",
        "SOURCE_TREE_UNMUTATED",
        "CORPUS_UNMUTATED",
        "EVIDENCE_UNMUTATED_EXCEPT_LOCK_RECORD",
        "PATH_PORTABLE",
        "SAFETY_DEFAULTS_RESPECTED",
    }
)


def _sha256(p: Path) -> str | None:
    if not p.is_file():
        return None
    h = hashlib.sha256()
    with p.open("rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _hash_signed_evidence() -> dict[str, str]:
    out: dict[str, str] = {}
    if EVIDENCE_INDEX.is_file():
        out["assurance/evidence/evidence_index.json"] = _sha256(EVIDENCE_INDEX) or ""
    for p in sorted(LOCKS_DIR.glob("*.json")):
        rel = p.relative_to(_REPO_ROOT)
        out[str(rel).replace("\\", "/")] = _sha256(p) or ""
    return out


def _hash_source_tree(root: Path) -> dict[str, str]:
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
    cruft_files = frozenset({"Cargo.lock", "go.sum", ".coverage"})
    out: dict[str, str] = {}
    for p in sorted(root.rglob("*")):
        if not p.is_file():
            continue
        rel = p.relative_to(root)
        if any(part in cruft_dirs for part in rel.parts):
            continue
        if p.name in cruft_files:
            continue
        d = _sha256(p)
        if d is not None:
            out[str(rel).replace("\\", "/")] = d
    return out


def _has_tool(name: str) -> bool:
    return shutil.which(name) is not None


# ---------------------------------------------------------------------------
# Status token closure + module-level sanity
# ---------------------------------------------------------------------------


def test_status_tokens_match_expected_set():
    expected = {
        "BUILD_ADAPTER_REGISTRY_READY",
        "BUILD_ADAPTER_DETECTED",
        "BUILD_ADAPTER_UNKNOWN",
        "BUILD_ADAPTER_MULTI_MATCH",
        "TEST_DISCOVERY_READY",
        "SHADOW_BUILD_READY",
        "FAILURE_PARSE_READY",
        "CODEBASE_EXPLORER_COMPAT_PRESERVED",
        "SOURCE_TREE_UNMUTATED",
        "CORPUS_UNMUTATED",
        "EVIDENCE_UNMUTATED_EXCEPT_LOCK_RECORD",
        "PATH_PORTABLE",
        "SAFETY_DEFAULTS_RESPECTED",
    }
    assert set(STATUS_TOKENS) == expected


def test_registry_imports_and_lists_all_builtin_adapters():
    from intake.build_adapter_registry import default_registry

    reg = default_registry()
    names = reg.list_adapters()
    ids = reg.list_build_system_ids()
    assert "Rust" in names
    assert "Go" in names
    assert "Python" in names
    assert "Node/TypeScript" in names
    assert "Java/Maven" in names
    assert "Java/Gradle" in names
    assert "Unknown" in names
    # ids must contain the historical strings that detect_build_system returns
    assert {"cargo", "go", "pip", "npm", "maven", "gradle", "unknown"} <= set(ids)


# ---------------------------------------------------------------------------
# Per-adapter detect() against the rung-1 fixtures
# ---------------------------------------------------------------------------


def test_python_adapter_detects_python_broken_fixture():
    from intake.build_adapters import PythonAdapter

    r = PythonAdapter.detect(FIXTURES / "python_broken")
    assert r.matched
    assert r.confidence > 0.5
    assert "pyproject.toml" in r.evidence_files


def test_rust_adapter_detects_rust_broken_fixture():
    from intake.build_adapters import RustAdapter

    r = RustAdapter.detect(FIXTURES / "rust_broken")
    assert r.matched
    assert r.confidence == 1.0
    assert r.evidence_files == ["Cargo.toml"]


def test_go_adapter_detects_go_broken_fixture():
    from intake.build_adapters import GoAdapter

    r = GoAdapter.detect(FIXTURES / "go_broken")
    assert r.matched
    assert r.confidence == 1.0
    assert r.evidence_files == ["go.mod"]


def test_cross_adapter_no_false_positives():
    """No adapter should match a fixture belonging to a different language."""
    from intake.build_adapters import GoAdapter, PythonAdapter, RustAdapter

    assert not RustAdapter.detect(FIXTURES / "python_broken").matched
    assert not GoAdapter.detect(FIXTURES / "python_broken").matched
    assert not PythonAdapter.detect(FIXTURES / "rust_broken").matched
    assert not GoAdapter.detect(FIXTURES / "rust_broken").matched
    assert not PythonAdapter.detect(FIXTURES / "go_broken").matched
    assert not RustAdapter.detect(FIXTURES / "go_broken").matched


# ---------------------------------------------------------------------------
# Registry selection: single-match, unknown, multi-match
# ---------------------------------------------------------------------------


def test_select_python_fixture_is_single_match_python():
    from intake.build_adapter_registry import default_registry
    from intake.build_adapters import PythonAdapter

    sel = default_registry().select(FIXTURES / "python_broken")
    assert sel.primary is PythonAdapter
    assert sel.multi_match is False
    assert len(sel.matched) == 1


def test_select_rust_fixture_is_single_match_rust():
    from intake.build_adapter_registry import default_registry
    from intake.build_adapters import RustAdapter

    sel = default_registry().select(FIXTURES / "rust_broken")
    assert sel.primary is RustAdapter
    assert sel.multi_match is False


def test_select_go_fixture_is_single_match_go():
    from intake.build_adapter_registry import default_registry
    from intake.build_adapters import GoAdapter

    sel = default_registry().select(FIXTURES / "go_broken")
    assert sel.primary is GoAdapter
    assert sel.multi_match is False


def test_select_empty_workspace_returns_unknown_explicitly(tmp_path: Path):
    """An empty / no-manifest folder must NOT crash and MUST return
    UnknownAdapter with multi_match=False."""
    (tmp_path / "README.md").write_text("just a readme, no manifest", encoding="utf-8")
    from intake.build_adapter_registry import default_registry
    from intake.build_adapters import UnknownAdapter

    sel = default_registry().select(tmp_path)
    assert sel.primary is UnknownAdapter
    assert sel.multi_match is False
    assert "no build manifest" in sel.note


def test_select_multi_match_polyglot_workspace_picks_higher_priority(tmp_path: Path):
    """Synthetic polyglot fixture: Cargo.toml AND go.mod AND pyproject.toml
    in the same dir. Registry must pick the highest-priority adapter
    deterministically (Rust > Go > Python by built-in priority) and mark
    multi_match=True."""
    (tmp_path / "Cargo.toml").write_text(
        '[package]\nname="p"\nversion="0.0.0"\nedition="2021"\n', encoding="utf-8"
    )
    (tmp_path / "go.mod").write_text("module example.com/p\ngo 1.21\n", encoding="utf-8")
    (tmp_path / "pyproject.toml").write_text('[project]\nname="p"\nversion="0"\n', encoding="utf-8")

    from intake.build_adapter_registry import default_registry
    from intake.build_adapters import RustAdapter

    sel = default_registry().select(tmp_path)
    assert sel.multi_match is True, "polyglot fixture must trigger multi_match"
    assert sel.primary is RustAdapter, f"Highest-priority adapter must win; got {sel.primary.name}"
    # All three adapters must appear in the matched list
    ids = {a.build_system_id for a, _ in sel.matched}
    assert {"cargo", "go", "pip"} <= ids


def test_selection_is_deterministic_across_invocations(tmp_path: Path):
    """Two select() calls on the same workspace must produce the same
    primary and the same matched ordering (deterministic tie-break)."""
    (tmp_path / "Cargo.toml").write_text(
        '[package]\nname="p"\nversion="0"\nedition="2021"\n', encoding="utf-8"
    )
    (tmp_path / "go.mod").write_text("module example.com/p\ngo 1.21\n", encoding="utf-8")
    from intake.build_adapter_registry import default_registry

    a = default_registry().select(tmp_path)
    b = default_registry().select(tmp_path)
    assert a.primary is b.primary
    assert [x[0].build_system_id for x in a.matched] == [x[0].build_system_id for x in b.matched]


# ---------------------------------------------------------------------------
# discover_tests / parse_failure
# ---------------------------------------------------------------------------


def test_python_adapter_discover_tests_includes_pytest():
    from intake.build_adapters import PythonAdapter

    out = PythonAdapter.discover_tests(FIXTURES / "python_broken")
    assert any("pytest" in s for s in out), out


def test_rust_adapter_discover_tests_includes_cargo_test():
    from intake.build_adapters import RustAdapter

    out = RustAdapter.discover_tests(FIXTURES / "rust_broken")
    assert any("cargo test" in s for s in out), out


def test_go_adapter_discover_tests_includes_go_test():
    from intake.build_adapters import GoAdapter

    out = GoAdapter.discover_tests(FIXTURES / "go_broken")
    assert any("go test" in s for s in out), out


def test_unknown_adapter_discover_tests_is_empty(tmp_path: Path):
    from intake.build_adapters import UnknownAdapter

    assert UnknownAdapter.discover_tests(tmp_path) == []


def test_rust_parse_failure_extracts_error_line():
    from intake.build_adapters import RustAdapter

    sample = (
        "error[E0308]: mismatched types\n"
        "  --> src/lib.rs:6:5\n"
        "   |\n"
        '6  |     "not an integer"\n'
        "   |     ^^^^^^^^^^^^^^^^ expected `i32`, found `&str`\n"
    )
    findings = RustAdapter.parse_failure(sample)
    assert len(findings) >= 1
    assert findings[0].category == "compilation"
    assert "E0308" in findings[0].message
    # location should be picked up from the --> line
    assert findings[0].file == "src/lib.rs"
    assert findings[0].line == 6


def test_go_parse_failure_extracts_error_line():
    from intake.build_adapters import GoAdapter

    sample = (
        "# example.com/p/calc\n"
        'calc/calc.go:9:9: cannot use "oops" (untyped string constant) as int value\n'
    )
    findings = GoAdapter.parse_failure(sample)
    assert len(findings) >= 1
    assert findings[0].category == "compilation"
    assert findings[0].file == "calc/calc.go"
    assert findings[0].line == 9


def test_python_parse_failure_extracts_pytest_failed():
    from intake.build_adapters import PythonAdapter

    sample = (
        "============================= test session starts =============================\n"
        "tests/test_calc.py F                                                       [100%]\n"
        "============================== FAILED ===============================\n"
        "FAILED tests/test_calc.py::test_add_two_plus_three_equals_five - assert -1 == 5\n"
    )
    findings = PythonAdapter.parse_failure(sample)
    assert any(f.category == "test_failure" for f in findings)


# ---------------------------------------------------------------------------
# run_shadow_build — gracefully skips when toolchain absent
# ---------------------------------------------------------------------------


def test_python_run_shadow_build_against_python_fixture(tmp_path: Path):
    from intake.build_adapters import PythonAdapter

    workspace = tmp_path / "py"
    shutil.copytree(FIXTURES / "python_broken", workspace)
    r = PythonAdapter.run_shadow_build(workspace, timeout=30)
    assert r.ran  # py_compile always available
    # The fixture has no syntax errors → build succeeds even though the
    # test FAILS. ShadowBuildResult.success here reflects compilation only.
    assert r.success, f"Python fixture should syntax-compile: {r.output}"


def test_rust_run_shadow_build_against_rust_fixture(tmp_path: Path):
    if not _has_tool("cargo"):
        pytest.skip("cargo not on PATH")
    from intake.build_adapters import RustAdapter

    workspace = tmp_path / "rs"
    shutil.copytree(FIXTURES / "rust_broken", workspace)
    r = RustAdapter.run_shadow_build(workspace, timeout=90)
    assert r.ran
    assert not r.success, "rust_broken fixture must fail cargo check"
    assert "error" in r.output.lower()


def test_go_run_shadow_build_against_go_fixture(tmp_path: Path):
    if not _has_tool("go"):
        pytest.skip("go not on PATH")
    from intake.build_adapters import GoAdapter

    workspace = tmp_path / "go"
    shutil.copytree(FIXTURES / "go_broken", workspace)
    r = GoAdapter.run_shadow_build(workspace, timeout=60)
    assert r.ran
    assert not r.success, "go_broken fixture must fail go build"


def test_run_shadow_build_reports_missing_tool_explicitly(tmp_path: Path):
    """When the underlying toolchain isn't on PATH, run_shadow_build must
    return tool_missing=True rather than raising."""
    from intake.build_adapters import _run

    r = _run(["__definitely_not_a_real_binary_xyz__"], tmp_path, timeout=5)
    assert r.tool_missing is True
    assert r.ran is False


# ---------------------------------------------------------------------------
# Codebase_explorer compatibility: detect_build_system must still return
# exactly the legacy strings for the three rung-1 fixtures.
# ---------------------------------------------------------------------------


def test_codebase_explorer_detect_build_system_compat_python():
    from codebase_explorer import detect_build_system

    bs, tf = detect_build_system(FIXTURES / "python_broken")
    assert bs == "pip"
    assert tf == "pytest"


def test_codebase_explorer_detect_build_system_compat_rust():
    from codebase_explorer import detect_build_system

    bs, tf = detect_build_system(FIXTURES / "rust_broken")
    assert bs == "cargo"
    assert tf == "cargo test"


def test_codebase_explorer_detect_build_system_compat_go():
    from codebase_explorer import detect_build_system

    bs, tf = detect_build_system(FIXTURES / "go_broken")
    assert bs == "go"
    assert tf == "go test"


def test_codebase_explorer_detect_build_system_compat_unknown(tmp_path: Path):
    (tmp_path / "README.md").write_text("nothing", encoding="utf-8")
    from codebase_explorer import detect_build_system

    bs, tf = detect_build_system(tmp_path)
    assert bs == "unknown"
    assert tf == "unknown"


def test_codebase_explorer_explore_still_works_on_python_fixture(tmp_path: Path):
    """End-to-end: CodebaseExplorer.explore() against the python fixture
    still produces the same shape it did before the migration."""
    os.environ["DETERMINEX_NO_CORPUS_WRITE"] = "1"
    os.environ["DETERMINEX_AUDIT_DIR"] = str(tmp_path / "_audit")
    try:
        workspace = tmp_path / "py"
        shutil.copytree(FIXTURES / "python_broken", workspace)
        from codebase_explorer import CodebaseExplorer

        rep = CodebaseExplorer(workspace).explore()
        assert rep.build_system == "pip"
        assert rep.test_framework == "pytest"
        assert "python" in rep.languages
        assert rep.health_score < 1.0
    finally:
        os.environ.pop("DETERMINEX_NO_CORPUS_WRITE", None)
        os.environ.pop("DETERMINEX_AUDIT_DIR", None)


# ---------------------------------------------------------------------------
# Cross-cutting safety
# ---------------------------------------------------------------------------


def test_registry_select_does_not_mutate_source_tree(tmp_path: Path):
    workspace = tmp_path / "rs"
    shutil.copytree(FIXTURES / "rust_broken", workspace)
    before = _hash_source_tree(workspace)
    from intake.build_adapter_registry import default_registry

    default_registry().select(workspace)
    after = _hash_source_tree(workspace)
    diffs = sorted(k for k in set(before) | set(after) if before.get(k) != after.get(k))
    assert diffs == [], diffs


def test_registry_select_does_not_mutate_signed_evidence(tmp_path: Path):
    """select() over multiple fixtures must not change evidence_index.json
    or any locks/sentinel/*.json."""
    before = _hash_signed_evidence()
    from intake.build_adapter_registry import default_registry

    reg = default_registry()
    for fixture in ("python_broken", "rust_broken", "go_broken"):
        reg.select(FIXTURES / fixture)
    reg.select(tmp_path)  # unknown
    after = _hash_signed_evidence()
    diffs = sorted(k for k in set(before) | set(after) if before.get(k) != after.get(k))
    assert diffs == [], diffs


def test_corpus_write_guard_active_during_registry_use():
    """Set DETERMINEX_NO_CORPUS_WRITE=1 and confirm the guard raises if any
    code path attempts a corpus write. (The registry itself never writes,
    but this proves the guard is in effect during the test session.)"""
    from corpus.corpus_manager import (  # type: ignore[attr-defined]
        CorpusWriteBlockedError,
        _assert_writes_allowed,
    )

    os.environ["DETERMINEX_NO_CORPUS_WRITE"] = "1"
    try:
        with pytest.raises(CorpusWriteBlockedError):
            _assert_writes_allowed()
    finally:
        os.environ.pop("DETERMINEX_NO_CORPUS_WRITE", None)


def test_no_drive_letter_required(monkeypatch):
    """Strip every DETERMINEX_* / HF_HOME / OLLAMA_* env var and confirm the
    registry still selects correctly against the python fixture."""
    for k in list(os.environ):
        if k.startswith(("DETERMINEX_", "HF_HOME", "OLLAMA_")):
            monkeypatch.delenv(k, raising=False)
    from intake.build_adapter_registry import default_registry
    from intake.build_adapters import PythonAdapter

    sel = default_registry().select(FIXTURES / "python_broken")
    assert sel.primary is PythonAdapter


def test_safety_defaults_remain_fail_closed():
    from determinex_settings import DeterminexSettings, reset_settings

    reset_settings()
    s = DeterminexSettings()
    assert s.assert_safety_defaults() == []


# ---------------------------------------------------------------------------
# Lock manifest alignment
# ---------------------------------------------------------------------------

_LOCK_PATH = _REPO_ROOT / "locks" / "sentinel" / "BUILD_ADAPTER_REGISTRY_LOCK_001.json"


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


def test_lock_manifest_pins_adapter_count():
    import json

    data = json.loads(_LOCK_PATH.read_text(encoding="utf-8"))
    assert data.get("adapters_count") == 7  # Rust+Go+Python+Node+Maven+Gradle+Unknown
