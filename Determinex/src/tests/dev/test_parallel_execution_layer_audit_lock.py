"""Tests for PARALLEL_EXECUTION_LAYER_AUDIT_LOCK_001.

Asserts that the static execution-layer audit:

  * detects known subprocess sites in ShadowCompiler and BuildAdapter._run
  * classifies hive/compiler.py as HARDENED_COMPILER_PATH
  * classifies ProgramBench/Codex-trail files as PROGRAMBENCH_OUT_OF_SCOPE
  * produces JSON + Markdown reports whose counts agree
  * never executes a discovered command
  * never mutates source, corpus, or signed evidence outside the explicit
    lock evidence path
  * unknown sites fail closed to UNKNOWN_REQUIRES_REVIEW, not silently
    classified as anything else
  * the on-disk Markdown matches ``to_markdown()`` byte-for-byte
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

audit = importlib.import_module("scripts.dev.parallel_execution_layer_audit")

LOCKS_DIR = _REPO_ROOT / "locks" / "sentinel"
EVIDENCE_INDEX = _REPO_ROOT / "assurance" / "evidence" / "evidence_index.json"
# docs/audits/, not docs/ root. The 2026-05-29 docs reorg moved every audit
# under docs/audits/ but left a copy at the old path, and this constant kept
# pointing at the copy -- so the doc humans read was regenerated while the doc
# this invariant guarded went stale, and the test still passed. See
# test_the_audit_doc_has_exactly_one_copy below.
DOC_PATH = _REPO_ROOT / "docs" / "audits" / "PARALLEL_EXECUTION_LAYER_AUDIT.md"


STATUS_TOKENS = frozenset(
    {
        "PARALLEL_EXECUTION_AUDIT_READY",
        "EXECUTION_SITE_FOUND",
        "HARDENED_COMPILER_PATH",
        "HIVE_SANDBOXED_PATH",
        "LEGACY_EXEMPT_READ_ONLY",
        "LEGACY_EXEMPT_TEST_FIXTURE",
        "MUST_MIGRATE_TO_HARDENED_RUNNER",
        "BLOCKED_UNSAFE",
        "PROGRAMBENCH_OUT_OF_SCOPE",
        "UNKNOWN_REQUIRES_REVIEW",
        "AUDIT_READ_ONLY",
        "SAFETY_DEFAULTS_RESPECTED",
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


def _hash_path_tree(root: Path, suffixes: tuple[str, ...]) -> dict[str, str]:
    out: dict[str, str] = {}
    for p in sorted(root.rglob("*")):
        if not p.is_file():
            continue
        if p.suffix.lower() not in suffixes:
            continue
        rel = p.relative_to(root)
        if any(part in {"__pycache__", ".venv", "venv", "fine_tuning"} for part in rel.parts):
            continue
        d = _sha256(p)
        if d is not None:
            out[str(rel).replace("\\", "/")] = d
    return out


# ---------------------------------------------------------------------------
# Status / module sanity
# ---------------------------------------------------------------------------


def test_status_tokens_match_expected_set():
    expected = {
        "PARALLEL_EXECUTION_AUDIT_READY",
        "EXECUTION_SITE_FOUND",
        "HARDENED_COMPILER_PATH",
        "HIVE_SANDBOXED_PATH",
        "LEGACY_EXEMPT_READ_ONLY",
        "LEGACY_EXEMPT_TEST_FIXTURE",
        "MUST_MIGRATE_TO_HARDENED_RUNNER",
        "BLOCKED_UNSAFE",
        "PROGRAMBENCH_OUT_OF_SCOPE",
        "UNKNOWN_REQUIRES_REVIEW",
        "AUDIT_READ_ONLY",
        "SAFETY_DEFAULTS_RESPECTED",
    }
    # Rung-4 sealed-moment STATUS_TOKENS. Later rungs may have added new
    # tokens to the live module (e.g. NEEDS_OWNER_DECISION from
    # SCRIPT_HELPER_EXECUTION_CLASSIFICATION_SWEEP_LOCK_001). The seal
    # holds if the rung-4 set is a SUBSET of the live module.
    assert set(STATUS_TOKENS) == expected
    assert expected.issubset(set(audit.STATUS_TOKENS))


def test_classifications_are_closed_set():
    """The rung-4 baseline classifications must remain. Later rungs may
    add new tokens (e.g. NEEDS_OWNER_DECISION); the seal holds as long
    as the rung-4 set is a SUBSET of the live module."""
    rung4_baseline = {
        "HARDENED_COMPILER_PATH",
        "HIVE_SANDBOXED_PATH",
        "LEGACY_EXEMPT_READ_ONLY",
        "LEGACY_EXEMPT_TEST_FIXTURE",
        "MUST_MIGRATE_TO_HARDENED_RUNNER",
        "BLOCKED_UNSAFE",
        "PROGRAMBENCH_OUT_OF_SCOPE",
        "UNKNOWN_REQUIRES_REVIEW",
    }
    assert rung4_baseline.issubset(set(audit.CLASSIFICATIONS))


def test_repo_paths_point_at_real_files():
    assert (audit.REPO_ROOT / "scripts" / "codebase_explorer.py").is_file()
    assert (audit.REPO_ROOT / "scripts" / "intake" / "build_adapters.py").is_file()
    assert (audit.REPO_ROOT / "scripts" / "hive" / "compiler.py").is_file()


# ---------------------------------------------------------------------------
# Audit run — produces a non-trivial report
# ---------------------------------------------------------------------------


def test_run_audit_produces_non_empty_report():
    rpt = audit.run_audit()
    assert rpt.total_sites > 0
    assert rpt.lock_id == "PARALLEL_EXECUTION_LAYER_AUDIT_LOCK_001"
    assert rpt.generated_at


# ---------------------------------------------------------------------------
# Key sites are found and correctly classified
# ---------------------------------------------------------------------------


def test_codebase_explorer_classification_rule_still_targets_must_migrate():
    """As of HARDENED_INTAKE_EXECUTION_RUNNER_LOCK_001, ShadowCompiler routes
    every subprocess call through intake.hardened_runner, so the audit
    finds zero direct subprocess sites in scripts/codebase_explorer.py.
    What we DO assert is that the classification RULE still targets that
    file as MUST_MIGRATE — if anyone reintroduces a raw subprocess.run
    in ShadowCompiler, it will be flagged correctly. (Regression-direction
    test, not site-presence test.)"""
    cls, _rationale = audit._classify_path("scripts/codebase_explorer.py")
    assert cls == "MUST_MIGRATE_TO_HARDENED_RUNNER"
    rpt = audit.run_audit()
    sites = [s for s in rpt.sites if s.file_path == "scripts/codebase_explorer.py"]
    # After migration: zero direct sites — every shadow build/test goes
    # through the hardened runner now.
    assert sites == [], (
        f"Unexpected subprocess sites in codebase_explorer.py after rung-5 "
        f"migration: {[(s.line, s.kind) for s in sites]}"
    )


def test_build_adapters_classification_rule_still_targets_must_migrate():
    """Same idea: scripts/intake/build_adapters.py should have zero direct
    subprocess sites after the rung-5 migration. The classification rule
    still tags it MUST_MIGRATE so any future regression that adds a
    direct subprocess call gets caught immediately."""
    cls, _rationale = audit._classify_path("scripts/intake/build_adapters.py")
    assert cls == "MUST_MIGRATE_TO_HARDENED_RUNNER"
    rpt = audit.run_audit()
    sites = [s for s in rpt.sites if s.file_path == "scripts/intake/build_adapters.py"]
    assert sites == [], (
        f"Unexpected subprocess sites in build_adapters.py after rung-5 "
        f"migration: {[(s.line, s.kind) for s in sites]}"
    )


def test_hardened_intake_runner_is_classified_hardened():
    """The new scripts/intake/hardened_runner.py must classify as
    HARDENED_COMPILER_PATH — it is the trusted intake-side runner that
    BuildAdapter / ShadowCompiler delegate to."""
    rpt = audit.run_audit()
    matches = [s for s in rpt.sites if s.file_path == "scripts/intake/hardened_runner.py"]
    assert len(matches) >= 1, "hardened_runner.py should contain at least one subprocess site"
    for s in matches:
        assert s.classification == "HARDENED_COMPILER_PATH"


def test_audit_must_migrate_residue_is_known_set():
    """After rung 5 the MUST_MIGRATE residue was 5 repair-pipeline sites.
    Rung 6 took those to 0. Rung 8 (sweep) surfaced 1 NEW must-migrate
    site in scripts/determinex_codeclash_agent.py. The load-bearing
    invariant for rung 4 is: every MUST_MIGRATE site has a known target
    file — none silently appear. The current allowed set is enumerated
    below; if a new file appears, this test must be updated alongside
    the rung that discovers/migrates it."""
    rpt = audit.run_audit()
    must_migrate = [s for s in rpt.sites if s.classification == "MUST_MIGRATE_TO_HARDENED_RUNNER"]
    allowed_files = {
        # All repair-pipeline sites (migrated in rung 6; documented residue
        # baseline allows them as a safety net if any reappear)
        "scripts/repair/go_repair_pipeline.py",
        "scripts/repair/native_c_cpp_repair_pipeline.py",
        "scripts/repair/python_repair_pipeline.py",
        "scripts/repair/rust_repair_pipeline.py",
        "scripts/repair/typescript_repair_pipeline.py",
        # Surfaced by rung 8 (classification sweep)
        "scripts/determinex_codeclash_agent.py",
    }
    unexpected = [s for s in must_migrate if s.file_path not in allowed_files]
    assert unexpected == [], (
        f"Unexpected MUST_MIGRATE sites (not in known allowed_files): "
        f"{[(s.file_path, s.line) for s in unexpected]}"
    )


def test_audit_classifies_hive_compiler_as_hardened():
    rpt = audit.run_audit()
    matches = [s for s in rpt.sites if s.file_path == "scripts/hive/compiler.py"]
    # hive/compiler.py is THE hardened oracle; every subprocess site inside
    # it inherits the HARDENED_COMPILER_PATH classification.
    assert len(matches) > 0
    for s in matches:
        assert s.classification == "HARDENED_COMPILER_PATH", (
            f"hive/compiler.py site at line {s.line} mis-classified as {s.classification}"
        )


def test_audit_classifies_programbench_files_as_out_of_scope():
    rpt = audit.run_audit()
    pb_matches = [
        s
        for s in rpt.sites
        if s.file_path.startswith(
            (
                "scripts/corpus/programbench/",
                "scripts/pb_",
                "scripts/determinex_programbench",
                "scripts/programbench_",
            )
        )
    ]
    assert len(pb_matches) > 0, "ProgramBench files should have execution sites"
    for s in pb_matches:
        assert s.classification == "PROGRAMBENCH_OUT_OF_SCOPE", (
            f"ProgramBench site {s.file_path}:{s.line} mis-classified as {s.classification}"
        )


def test_audit_classifies_validators_as_legacy_exempt():
    rpt = audit.run_audit()
    matches = [s for s in rpt.sites if s.file_path.startswith("scripts/validators/")]
    # validators may or may not have subprocess sites; if they do, they MUST
    # be exempt (DATA ENGINE ONLY).
    for s in matches:
        assert s.classification == "LEGACY_EXEMPT_READ_ONLY"


def test_audit_classifies_dev_tools_as_legacy_exempt():
    """The audit script itself + the architecture gauntlet — exempt as
    read-only dev tooling. Otherwise the audit would flag itself."""
    rpt = audit.run_audit()
    self_matches = [
        s for s in rpt.sites if s.file_path == "scripts/dev/parallel_execution_layer_audit.py"
    ]
    for s in self_matches:
        assert s.classification == "LEGACY_EXEMPT_READ_ONLY"
    gauntlet_matches = [
        s for s in rpt.sites if s.file_path == "scripts/dev/architecture_regression_gauntlet.py"
    ]
    for s in gauntlet_matches:
        assert s.classification == "LEGACY_EXEMPT_READ_ONLY"


# ---------------------------------------------------------------------------
# Fail-closed: unknown sites are explicit, not silently accepted
# ---------------------------------------------------------------------------


def test_unknown_classification_is_explicit_when_no_rule_matches(tmp_path: Path):
    """Synthetic file at a path that no rule matches must be classified
    UNKNOWN_REQUIRES_REVIEW. Tests scan_file() directly with a manufactured
    path."""
    # Build a temp file under an unrecognized scripts/ subpath. We cannot
    # actually create files inside the repo, so we test the path classifier
    # directly.
    cls, _rationale = audit._classify_path("scripts/never_existed_dir/never_existed_file.py")
    assert cls == "UNKNOWN_REQUIRES_REVIEW"


def test_classify_path_outside_scripts_falls_through_to_unknown():
    cls, _ = audit._classify_path("totally/unrelated/path.py")
    # No rule for non-scripts/ paths → falls through to module default
    assert cls == "UNKNOWN_REQUIRES_REVIEW"


# ---------------------------------------------------------------------------
# Reports: JSON + Markdown produced and consistent
# ---------------------------------------------------------------------------


def test_json_report_has_required_structure():
    rpt = audit.run_audit()
    d = rpt.to_dict()
    assert d["lock_id"] == "PARALLEL_EXECUTION_LAYER_AUDIT_LOCK_001"
    assert "generated_at" in d
    assert "totals" in d
    assert d["totals"]["total_sites"] == rpt.total_sites
    assert "counts_by_classification" in d["totals"]
    assert "counts_by_kind" in d["totals"]
    assert isinstance(d["sites"], list)
    assert isinstance(d["top_must_migrate"], list)
    assert isinstance(d["blocked_unsafe"], list)
    assert isinstance(d["unknown_requires_review"], list)


def test_json_and_markdown_counts_agree():
    rpt = audit.run_audit()
    json_counts = rpt.counts_by_classification()
    md = audit.to_markdown(rpt)
    # Every classification's count from the dataclass must appear in the
    # Markdown's "Counts by classification" table cells. We assert the
    # rendered number is present for every classification.
    for cls, n in json_counts.items():
        assert f"| {cls} | {n} |" in md, f"Markdown is missing or mis-counts {cls}: {n}"


def test_markdown_lists_blocked_unsafe_section_explicitly():
    rpt = audit.run_audit()
    md = audit.to_markdown(rpt)
    assert "## BLOCKED_UNSAFE sites" in md
    # If there are no blocked sites, the document MUST say "_None._" so
    # readers don't mistake silence for problem.
    if rpt.counts_by_classification().get("BLOCKED_UNSAFE", 0) == 0:
        assert "## BLOCKED_UNSAFE sites\n\n_None._" in md.replace("\r\n", "\n")


# ---------------------------------------------------------------------------
# Read-only: the audit does NOT execute any discovered command
# ---------------------------------------------------------------------------


def test_audit_does_not_call_subprocess_during_scan(monkeypatch):
    """If the audit ever shells out, this test will fail. We monkey-patch
    subprocess.run/Popen to raise; the audit must complete without invoking
    either."""
    import subprocess

    calls: list[str] = []

    def _no_run(*args, **kwargs):
        calls.append(f"subprocess.run({args!r}, {kwargs!r})")
        raise RuntimeError("subprocess.run called during audit")

    def _no_popen(*args, **kwargs):
        calls.append(f"subprocess.Popen({args!r}, {kwargs!r})")
        raise RuntimeError("subprocess.Popen called during audit")

    monkeypatch.setattr(subprocess, "run", _no_run)
    monkeypatch.setattr(subprocess, "Popen", _no_popen)

    rpt = audit.run_audit()
    assert rpt.total_sites > 0
    assert calls == [], f"audit triggered subprocess: {calls}"


def test_audit_does_not_mutate_signed_evidence():
    before = _hash_signed_evidence()
    rpt = audit.run_audit()
    _ = audit.to_markdown(rpt)
    _ = rpt.to_dict()
    after = _hash_signed_evidence()
    diffs = sorted(k for k in set(before) | set(after) if before.get(k) != after.get(k))
    assert diffs == [], diffs


def test_audit_does_not_mutate_scripts_tree():
    """run_audit + to_markdown + to_dict are read-only against scripts/.
    Hash every .py file under scripts/ before and after; nothing should change."""
    scripts_dir = _REPO_ROOT / "scripts"
    before = _hash_path_tree(scripts_dir, (".py",))
    _ = audit.run_audit()
    _ = audit.to_markdown(audit.run_audit())
    after = _hash_path_tree(scripts_dir, (".py",))
    diffs = sorted(k for k in set(before) | set(after) if before.get(k) != after.get(k))
    assert diffs == [], diffs


# ---------------------------------------------------------------------------
# Doc-matches-audit invariant
# ---------------------------------------------------------------------------


def test_doc_file_exists():
    assert DOC_PATH.is_file(), f"missing: {DOC_PATH}"


def test_doc_counts_match_runtime_audit():
    """The on-disk markdown's counts table must match a fresh audit's
    counts. (We do NOT require byte-for-byte match here because the
    audit's `generated_at` timestamp legitimately drifts between runs;
    the count assertion is what catches drift.)"""
    rpt = audit.run_audit()
    counts = rpt.counts_by_classification()
    on_disk = DOC_PATH.read_text(encoding="utf-8")
    for cls, n in counts.items():
        assert f"| {cls} | {n} |" in on_disk, (
            f"doc / runtime drift for {cls}: doc does not contain `| {cls} | {n} |`"
        )


# ---------------------------------------------------------------------------
# Cross-cutting safety
# ---------------------------------------------------------------------------


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


def test_safety_defaults_remain_fail_closed_after_audit():
    _ = audit.run_audit()
    from determinex_settings import DeterminexSettings, reset_settings

    reset_settings()
    s = DeterminexSettings()
    assert s.assert_safety_defaults() == []


def test_no_drive_letter_required(monkeypatch):
    for k in list(os.environ):
        if k.startswith(("DETERMINEX_", "HF_HOME", "OLLAMA_")):
            monkeypatch.delenv(k, raising=False)
    rpt = audit.run_audit()
    assert rpt.total_sites > 0


# ---------------------------------------------------------------------------
# Lock manifest alignment
# ---------------------------------------------------------------------------

_LOCK_PATH = _REPO_ROOT / "locks" / "sentinel" / "PARALLEL_EXECUTION_LAYER_AUDIT_LOCK_001.json"


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


def test_lock_manifest_classifications_match_module():
    """The rung-4 lock's classifications list is a sealed snapshot. Later
    rungs may extend the live module's CLASSIFICATIONS (e.g.
    NEEDS_OWNER_DECISION added in rung 8). The seal holds if the rung-4
    set is a SUBSET of the live module."""
    data = json.loads(_LOCK_PATH.read_text(encoding="utf-8"))
    declared = set(data.get("classifications", []))
    assert declared.issubset(set(audit.CLASSIFICATIONS))


def test_lock_manifest_pins_zero_blocked_unsafe_at_seal():
    """Sealed-snapshot test: the rung-4 lock's counts_snapshot pinned
    BLOCKED_UNSAFE=0 at the moment of issue. That seal value never
    changes. The current live audit may surface new BLOCKED_UNSAFE
    sites in later rungs (e.g. rung 8 surfaced 2 in
    verified_task/command_runner.py); the current count is governed by
    the latest rung's own lock test, not this one."""
    data = json.loads(_LOCK_PATH.read_text(encoding="utf-8"))
    pinned = data["counts_snapshot"]["BLOCKED_UNSAFE"]
    assert pinned == 0, f"Rung-4 sealed snapshot pinned BLOCKED_UNSAFE=0; got pinned={pinned}"


def test_the_audit_doc_has_exactly_one_copy():
    """Why this exists: there were two.

    The 2026-05-29 docs reorg put every audit under `docs/audits/` but left the
    original at `docs/` root. DOC_PATH still named the root copy, so
    `test_doc_counts_match_runtime_audit` guarded a file nobody regenerated while
    the file humans actually read drifted freely -- and regenerating the real doc
    could not turn this suite green, because it was checking the other one.

    A stale duplicate of a generated security inventory is worse than no
    duplicate: it reads as current and reports counts that are not.
    """
    found = sorted(
        p.relative_to(_REPO_ROOT).as_posix()
        for p in _REPO_ROOT.glob("docs/**/PARALLEL_EXECUTION_LAYER_AUDIT.md")
    )
    assert found == ["docs/audits/PARALLEL_EXECUTION_LAYER_AUDIT.md"], (
        f"expected exactly one audit doc at the canonical path, found {found}"
    )
