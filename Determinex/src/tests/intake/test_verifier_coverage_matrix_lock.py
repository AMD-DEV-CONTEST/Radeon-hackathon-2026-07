"""Tests for VERIFIER_COVERAGE_MATRIX_LOCK_001.

Asserts that the honest verifier coverage matrix matches the lock manifest,
that every BuildAdapter output maps to a coverage entry, that unsupported
combinations fail closed as UNKNOWN, that docs/VERIFIER_COVERAGE_MATRIX.md
is byte-identical to the matrix's ``to_markdown()`` output, and that
runtime use of the lookup table mutates neither source, corpus, nor
signed evidence.
"""

from __future__ import annotations

import hashlib
import importlib
import json
import os
import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
for _p in (_REPO_ROOT, _REPO_ROOT / "scripts"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

vcm = importlib.import_module("intake.verifier_coverage_matrix")
adapters_mod = importlib.import_module("intake.build_adapters")
registry_mod = importlib.import_module("intake.build_adapter_registry")

LOCKS_DIR = _REPO_ROOT / "locks" / "sentinel"
EVIDENCE_INDEX = _REPO_ROOT / "assurance" / "evidence" / "evidence_index.json"
DOC_PATH = _REPO_ROOT / "docs" / "VERIFIER_COVERAGE_MATRIX.md"


STATUS_TOKENS = frozenset(
    {
        "VERIFIER_COVERAGE_MATRIX_READY",
        "VERIFIER_COVERAGE_BACKED",
        "VERIFIER_COVERAGE_PARTIAL",
        "VERIFIER_COVERAGE_MISSING",
        "VERIFIER_COVERAGE_UNKNOWN",
        "UNSUPPORTED_COMBINATION_FAILS_CLOSED",
        "COVERAGE_DOCS_GENERATED",
        "COVERAGE_DOCS_MATCH_MATRIX",
        "ADAPTER_OUTPUTS_MAPPED",
        "CLAIMS_GUARD_READY",
    }
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# Module sanity / status tokens
# ---------------------------------------------------------------------------


def test_status_tokens_match_expected_set():
    expected = {
        "VERIFIER_COVERAGE_MATRIX_READY",
        "VERIFIER_COVERAGE_BACKED",
        "VERIFIER_COVERAGE_PARTIAL",
        "VERIFIER_COVERAGE_MISSING",
        "VERIFIER_COVERAGE_UNKNOWN",
        "UNSUPPORTED_COMBINATION_FAILS_CLOSED",
        "COVERAGE_DOCS_GENERATED",
        "COVERAGE_DOCS_MATCH_MATRIX",
        "ADAPTER_OUTPUTS_MAPPED",
        "CLAIMS_GUARD_READY",
    }
    assert set(STATUS_TOKENS) == expected


def test_module_imports_and_exposes_public_api():
    assert vcm.COVERAGE_MATRIX
    assert vcm.CoverageStatus.BACKED.value == "backed"
    assert vcm.CoverageStatus.PARTIAL.value == "partial"
    assert vcm.CoverageStatus.MISSING.value == "missing"
    assert vcm.CoverageStatus.UNKNOWN.value == "unknown"
    assert callable(vcm.lookup)
    assert callable(vcm.classify_for_build_test)
    assert callable(vcm.summary)
    assert callable(vcm.to_markdown)


def test_matrix_entries_have_required_fields():
    for e in vcm.COVERAGE_MATRIX:
        assert e.language
        assert e.build_system_id
        assert e.test_framework_id
        assert e.oracle_path, f"oracle_path empty for {e}"
        assert isinstance(e.status, vcm.CoverageStatus)
        # backed rows MUST mention a wiring point (defensive — no empty claims)
        if e.status == vcm.CoverageStatus.BACKED:
            assert any(
                token in e.oracle_path
                for token in ("run_shadow_build", "run_tests", "RepairPipeline", "ShadowCompiler")
            ), f"BACKED row lacks wiring evidence in oracle_path: {e}"


# ---------------------------------------------------------------------------
# Per-row classification — backed
# ---------------------------------------------------------------------------


def test_python_pip_pytest_is_backed():
    e = vcm.lookup("Python", "pip", "pytest")
    assert e.status == vcm.CoverageStatus.BACKED


def test_rust_cargo_is_backed():
    e = vcm.lookup("Rust", "cargo", "cargo test")
    assert e.status == vcm.CoverageStatus.BACKED


def test_go_is_backed():
    e = vcm.lookup("Go", "go", "go test")
    assert e.status == vcm.CoverageStatus.BACKED


def test_java_maven_is_backed():
    e = vcm.lookup("Java", "maven", "maven test")
    assert e.status == vcm.CoverageStatus.BACKED


def test_java_gradle_is_backed():
    e = vcm.lookup("Java", "gradle", "gradle test")
    assert e.status == vcm.CoverageStatus.BACKED


# ---------------------------------------------------------------------------
# Per-row classification — partial (honest about weak links)
# ---------------------------------------------------------------------------


def test_typescript_jest_is_partial():
    e = vcm.lookup("TypeScript", "npm", "jest")
    assert e.status == vcm.CoverageStatus.PARTIAL


def test_typescript_vitest_is_partial():
    e = vcm.lookup("TypeScript", "npm", "vitest")
    assert e.status == vcm.CoverageStatus.PARTIAL


def test_kotlin_gradle_junit_is_partial():
    e = vcm.lookup("Kotlin", "gradle", "junit")
    assert e.status == vcm.CoverageStatus.PARTIAL
    # Specifically: must call out that compileJava (not compileKotlin) runs
    assert "compileKotlin" in e.oracle_path or "Kotlin" in e.oracle_path


# ---------------------------------------------------------------------------
# Per-row classification — missing
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "build,test",
    [
        ("cmake", "ctest"),
        ("make", "make test"),
        ("mix", "exunit"),
        ("dotnet", "xunit"),
        ("composer", "phpunit"),
        ("bundler", "rspec"),
        ("sbt", "scalatest"),
        ("swiftpm", "XCTest"),
        ("npm", "mocha"),
    ],
)
def test_missing_combinations_classified_missing(build, test):
    e = vcm.lookup("", build, test)
    assert e.status == vcm.CoverageStatus.MISSING, (
        f"expected MISSING for ({build}, {test}); got {e.status.value}"
    )


# ---------------------------------------------------------------------------
# Per-row classification — unknown + fail-closed guarantee
# ---------------------------------------------------------------------------


def test_unknown_combination_is_unknown():
    e = vcm.lookup("(any)", "unknown", "unknown")
    assert e.status == vcm.CoverageStatus.UNKNOWN


def test_unsupported_combination_fails_closed_to_unknown():
    """The single most important guard: any (build, test) not in the
    matrix MUST return UNKNOWN, never BACKED or PARTIAL."""
    e = vcm.lookup("fake-lang", "fake-build", "fake-test")
    assert e.status == vcm.CoverageStatus.UNKNOWN
    # Synthetic entry must carry the input as evidence and the fail-closed note
    assert e.build_system_id == "fake-build"
    assert e.test_framework_id == "fake-test"
    assert "fails closed" in e.notes.lower()


def test_classify_for_build_test_shortcut_agrees_with_lookup():
    for e in vcm.COVERAGE_MATRIX:
        assert vcm.classify_for_build_test(e.build_system_id, e.test_framework_id) == e.status


# ---------------------------------------------------------------------------
# Every adapter registry output maps to a coverage entry
# ---------------------------------------------------------------------------


def test_every_adapter_static_output_is_covered():
    """For each builtin adapter, the canonical (build_system_id,
    test_framework_id) tuple MUST appear in the matrix. NodeAdapter's
    refinements (vitest/mocha) are tested separately."""
    reg = registry_mod.default_registry()
    for adapter in reg._adapters:  # type: ignore[attr-defined]
        e = vcm.lookup("", adapter.build_system_id, adapter.test_framework_id)
        # Every adapter output MUST have a non-empty entry. Unknown adapter's
        # entry is itself UNKNOWN — that's allowed and correct.
        assert e.oracle_path != "no entry in coverage matrix", (
            f"adapter {adapter.name} (build_id={adapter.build_system_id}, "
            f"test_id={adapter.test_framework_id}) has no coverage matrix entry"
        )


def test_node_adapter_refinements_are_covered():
    """NodeAdapter can refine test_framework_id to vitest or mocha based on
    package.json devDeps. The matrix MUST have explicit entries for all
    three (jest/vitest/mocha) — none may silently fall through to UNKNOWN."""
    for tf in ("jest", "vitest", "mocha"):
        e = vcm.lookup("TypeScript", "npm", tf)
        assert e.oracle_path != "no entry in coverage matrix", (
            f"npm/{tf} silently falls through to UNKNOWN — matrix gap"
        )


# ---------------------------------------------------------------------------
# Summary counts
# ---------------------------------------------------------------------------


def test_summary_counts_are_non_zero_in_each_meaningful_tier():
    """We expect at least one entry in each of backed, partial, missing,
    unknown — otherwise the matrix isn't meaningful as a coverage map."""
    counts = vcm.summary()
    assert counts["backed"] >= 1
    assert counts["partial"] >= 1
    assert counts["missing"] >= 1
    assert counts["unknown"] >= 1


def test_summary_counts_sum_to_matrix_length():
    assert sum(vcm.summary().values()) == len(vcm.COVERAGE_MATRIX)


def test_entries_by_status_round_trips():
    for s in vcm.CoverageStatus:
        rows = vcm.entries_by_status(s)
        for r in rows:
            assert r.status == s


# ---------------------------------------------------------------------------
# Docs and matrix agree byte-for-byte
# ---------------------------------------------------------------------------


def test_doc_file_exists():
    assert DOC_PATH.is_file(), f"missing: {DOC_PATH}"


def test_doc_matches_matrix_to_markdown_output():
    """Strongest claim: the on-disk Markdown is exactly what to_markdown()
    produces. If anyone hand-edits the doc or updates the matrix without
    regenerating, this test flips red."""
    on_disk = DOC_PATH.read_text(encoding="utf-8").replace("\r\n", "\n")
    generated = vcm.to_markdown().replace("\r\n", "\n")
    if on_disk != generated:
        # Surface a useful diff in the failure message
        from difflib import unified_diff

        diff = "\n".join(
            unified_diff(
                generated.splitlines(),
                on_disk.splitlines(),
                fromfile="<to_markdown()>",
                tofile=str(DOC_PATH),
                lineterm="",
            )[:60]
        )
        pytest.fail(f"doc drift detected:\n{diff}")


def test_doc_lists_every_matrix_entry():
    on_disk = DOC_PATH.read_text(encoding="utf-8")
    for e in vcm.COVERAGE_MATRIX:
        # Quick spot-check: every entry's build_system_id appears in the doc
        assert f"`{e.build_system_id}`" in on_disk, (
            f"build_system_id `{e.build_system_id}` not in doc"
        )


# ---------------------------------------------------------------------------
# Cross-cutting safety
# ---------------------------------------------------------------------------


def test_no_drive_letter_required(monkeypatch):
    """Strip DETERMINEX_*/HF_HOME/OLLAMA_* env vars, confirm lookup still works."""
    for k in list(os.environ):
        if k.startswith(("DETERMINEX_", "HF_HOME", "OLLAMA_")):
            monkeypatch.delenv(k, raising=False)
    e = vcm.lookup("Python", "pip", "pytest")
    assert e.status == vcm.CoverageStatus.BACKED


def test_lookup_does_not_mutate_signed_evidence():
    """The matrix is a pure read-only data structure. Exercise lookup and
    to_markdown(); confirm no signed evidence file changed."""
    before = _hash_signed_evidence()
    for e in vcm.COVERAGE_MATRIX:
        vcm.lookup(e.language, e.build_system_id, e.test_framework_id)
    _ = vcm.to_markdown()
    _ = vcm.summary()
    after = _hash_signed_evidence()
    diffs = sorted(k for k in set(before) | set(after) if before.get(k) != after.get(k))
    assert diffs == [], diffs


def test_corpus_write_guard_active():
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


def test_safety_defaults_remain_fail_closed():
    from determinex_settings import DeterminexSettings, reset_settings

    reset_settings()
    s = DeterminexSettings()
    assert s.assert_safety_defaults() == []


# ---------------------------------------------------------------------------
# Lock manifest alignment
# ---------------------------------------------------------------------------

_LOCK_PATH = _REPO_ROOT / "locks" / "sentinel" / "VERIFIER_COVERAGE_MATRIX_LOCK_001.json"


def test_lock_manifest_exists():
    assert _LOCK_PATH.is_file(), f"missing: {_LOCK_PATH}"


def test_lock_manifest_status_tokens_match_module():
    data = json.loads(_LOCK_PATH.read_text(encoding="utf-8"))
    declared = set(data.get("status_tokens", []))
    assert declared == set(STATUS_TOKENS), (
        f"status token drift:\n"
        f"  in lock not in module: {declared - set(STATUS_TOKENS)}\n"
        f"  in module not in lock: {set(STATUS_TOKENS) - declared}"
    )


def test_lock_manifest_counts_match_runtime_summary():
    data = json.loads(_LOCK_PATH.read_text(encoding="utf-8"))
    pinned = data["counts"]
    actual = vcm.summary()
    assert pinned == actual, f"counts drift: lock={pinned} vs module={actual}"


def test_lock_manifest_pins_entry_count():
    data = json.loads(_LOCK_PATH.read_text(encoding="utf-8"))
    assert data.get("entries_count") == len(vcm.COVERAGE_MATRIX)
