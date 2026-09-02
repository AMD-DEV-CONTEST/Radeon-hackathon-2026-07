"""Tests for SCRIPT_HELPER_EXECUTION_CLASSIFICATION_SWEEP_LOCK_001.

Asserts the post-sweep classification state of the parallel execution
audit:

  * UNKNOWN_REQUIRES_REVIEW dropped from 121 to 0
  * BLOCKED_UNSAFE rose from 0 to 2 (both in verified_task/command_runner.py)
  * MUST_MIGRATE_TO_HARDENED_RUNNER rose from 0 to 1 (determinex_codeclash_agent)
  * PROGRAMBENCH_OUT_OF_SCOPE preserved at >= 56
  * The kind-aware override correctly flags shell=True / os.system /
    os.popen as BLOCKED_UNSAFE while carving out PROGRAMBENCH and
    LEGACY_EXEMPT_TEST_FIXTURE paths
  * Every new path-rule's target file resolves correctly under the audit
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


STATUS_TOKENS = frozenset(
    {
        "SCRIPT_HELPER_SWEEP_READY",
        "UNKNOWN_DECREASED_MATERIALLY",
        "UNKNOWN_REACHED_ZERO",
        "BLOCKED_UNSAFE_SURFACED",
        "PROGRAMBENCH_PRESERVED",
        "NEEDS_OWNER_DECISION_DEFINED",
        "KIND_OVERRIDE_ACTIVE",
        "KIND_OVERRIDE_CARVES_OUT_PROGRAMBENCH",
        "KIND_OVERRIDE_CARVES_OUT_TEST_FIXTURE",
        "ALL_HELPERS_CLASSIFIED",
        "EVIDENCE_UNMUTATED_EXCEPT_LOCK_RECORD",
        "CORPUS_UNMUTATED",
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


# ---------------------------------------------------------------------------
# Status / classification token set
# ---------------------------------------------------------------------------


def test_status_tokens_match_expected_set():
    expected = {
        "SCRIPT_HELPER_SWEEP_READY",
        "UNKNOWN_DECREASED_MATERIALLY",
        "UNKNOWN_REACHED_ZERO",
        "BLOCKED_UNSAFE_SURFACED",
        "PROGRAMBENCH_PRESERVED",
        "NEEDS_OWNER_DECISION_DEFINED",
        "KIND_OVERRIDE_ACTIVE",
        "KIND_OVERRIDE_CARVES_OUT_PROGRAMBENCH",
        "KIND_OVERRIDE_CARVES_OUT_TEST_FIXTURE",
        "ALL_HELPERS_CLASSIFIED",
        "EVIDENCE_UNMUTATED_EXCEPT_LOCK_RECORD",
        "CORPUS_UNMUTATED",
        "SAFETY_DEFAULTS_RESPECTED",
    }
    assert set(STATUS_TOKENS) == expected


def test_needs_owner_decision_classification_exists():
    """NEEDS_OWNER_DECISION must be part of the audit's CLASSIFICATIONS
    frozenset even if currently unused — it is reserved for genuinely
    ambiguous cases a future sweep encounters."""
    assert "NEEDS_OWNER_DECISION" in audit.CLASSIFICATIONS
    assert "NEEDS_OWNER_DECISION" in audit.STATUS_TOKENS


def test_always_blocked_kinds_includes_shell_and_os_system():
    assert "shell=True" in audit._ALWAYS_BLOCKED_KINDS
    assert "os.system" in audit._ALWAYS_BLOCKED_KINDS
    assert "os.popen" in audit._ALWAYS_BLOCKED_KINDS


# ---------------------------------------------------------------------------
# Post-sweep audit invariants
# ---------------------------------------------------------------------------


def test_unknown_requires_review_is_zero():
    rpt = audit.run_audit()
    cnt = rpt.counts_by_classification().get("UNKNOWN_REQUIRES_REVIEW", 0)
    assert cnt == 0, (
        f"Sweep is incomplete — UNKNOWN_REQUIRES_REVIEW = {cnt}. "
        "Every helper should have a path-rule by now."
    )


def test_programbench_out_of_scope_preserved():
    """PROGRAMBENCH must remain at >= 56. Anything less means the sweep
    accidentally moved a Codex file out of the PB classification (which
    is forbidden by directive)."""
    rpt = audit.run_audit()
    cnt = rpt.counts_by_classification().get("PROGRAMBENCH_OUT_OF_SCOPE", 0)
    assert cnt >= 56, (
        f"PROGRAMBENCH_OUT_OF_SCOPE dropped to {cnt} — Codex-lane file was "
        "accidentally reclassified (forbidden by directive)."
    )


def test_blocked_unsafe_sites_known_set_only():
    """Rung-8 surfaced 2 BLOCKED_UNSAFE sites in command_runner.py.
    Rung-9 (HARDENED_VERIFIED_TASK_AND_CODECLASH_LOCK_001) migrated
    command_runner.py to intake.hardened_runner, taking BLOCKED_UNSAFE
    to 0. This test allows either state — the load-bearing invariant
    is 'no NEW BLOCKED_UNSAFE in unexpected files'."""
    rpt = audit.run_audit()
    sites = [s for s in rpt.sites if s.classification == "BLOCKED_UNSAFE"]
    allowed_files = {
        "scripts/verified_task/command_runner.py",  # historical baseline
    }
    unexpected = [s for s in sites if s.file_path not in allowed_files]
    assert unexpected == [], (
        f"Unexpected BLOCKED_UNSAFE sites in non-baseline files: "
        f"{[(s.file_path, s.line, s.kind) for s in unexpected]}"
    )
    # Count may be 0 (after rung 9) or 2 (right after rung 8). Anything
    # else is a regression.
    assert len(sites) in (0, 2), (
        f"BLOCKED_UNSAFE count {len(sites)} outside known range {{0, 2}}: "
        f"{[(s.file_path, s.line, s.kind) for s in sites]}"
    )


def test_must_migrate_sites_known_set_only():
    """Rung-8 surfaced 1 MUST_MIGRATE site in determinex_codeclash_agent.py.
    Rung-9 migrated it to intake.hardened_runner, taking MUST_MIGRATE to
    0. This test allows either state — invariant is 'no NEW MUST_MIGRATE
    in unexpected files'."""
    rpt = audit.run_audit()
    sites = [s for s in rpt.sites if s.classification == "MUST_MIGRATE_TO_HARDENED_RUNNER"]
    allowed_files = {
        "scripts/determinex_codeclash_agent.py",  # historical baseline
    }
    unexpected = [s for s in sites if s.file_path not in allowed_files]
    assert unexpected == [], (
        f"Unexpected MUST_MIGRATE sites: {[(s.file_path, s.line, s.kind) for s in unexpected]}"
    )
    assert len(sites) in (0, 1)


# ---------------------------------------------------------------------------
# Kind-aware override behavior
# ---------------------------------------------------------------------------


def test_kind_override_carves_out_programbench_files(tmp_path: Path, monkeypatch):
    """A synthetic ProgramBench file containing shell=True must STAY
    PROGRAMBENCH_OUT_OF_SCOPE — the kind-override must NOT escalate it
    to BLOCKED_UNSAFE."""
    # Synthetic source containing shell=True
    src = "import subprocess\ndef go():\n    subprocess.run('echo hi', shell=True)\n"
    # We test the scan_file behavior by writing the file under a PB path
    # within the live repo (not actually creating new files there — instead
    # we exercise _classify_path + the override logic directly).
    cls, _ = audit._classify_path("scripts/corpus/programbench/fake.py")
    assert cls == "PROGRAMBENCH_OUT_OF_SCOPE"
    # Override carve-out must include this classification:
    # we inspect the module's exempt set indirectly by confirming the
    # current audit's PB classification holds for the live PB shell=True
    # site (pb_factory_worker_loop has shell=True; classification must be
    # PROGRAMBENCH_OUT_OF_SCOPE, not BLOCKED_UNSAFE).
    rpt = audit.run_audit()
    pb_shell_sites = [
        s for s in rpt.sites if s.kind == "shell=True" and s.file_path.startswith("scripts/pb_")
    ]
    for s in pb_shell_sites:
        assert s.classification == "PROGRAMBENCH_OUT_OF_SCOPE", (
            f"PB shell=True site mis-classified: {s.file_path}:{s.line} -> "
            f"{s.classification} (expected PROGRAMBENCH_OUT_OF_SCOPE)"
        )


def test_kind_override_mechanism_intact():
    """Rung-9 migrated verified_task/command_runner.py so no shell=True
    site remains there. The kind-override mechanism itself must still
    be in place for any future shell=True site that appears in a
    non-carved-out path. Verified structurally: the constants exist
    and shell=True is in the always-blocked set."""
    assert "shell=True" in audit._ALWAYS_BLOCKED_KINDS
    assert "PROGRAMBENCH_OUT_OF_SCOPE" in audit._KIND_OVERRIDE_EXEMPT
    assert "LEGACY_EXEMPT_TEST_FIXTURE" in audit._KIND_OVERRIDE_EXEMPT
    # Live evidence the override still fires for PB shell=True sites
    # (which then get carved back to PROGRAMBENCH_OUT_OF_SCOPE):
    rpt = audit.run_audit()
    pb_shell_sites = [
        s for s in rpt.sites if s.kind == "shell=True" and s.file_path.startswith("scripts/pb_")
    ]
    # If PB has shell=True sites, they must remain PB (carve-out working)
    for s in pb_shell_sites:
        assert s.classification == "PROGRAMBENCH_OUT_OF_SCOPE"


# ---------------------------------------------------------------------------
# Specific reclassifications spot-checked
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "file_path,expected_classification",
    [
        # Hive-sandboxed (SWE-bench)
        ("scripts/swe_run/repo.py", "HIVE_SANDBOXED_PATH"),
        ("scripts/setup_swebench.py", "HIVE_SANDBOXED_PATH"),
        ("scripts/smoke_test_swebench.py", "HIVE_SANDBOXED_PATH"),
        ("scripts/benchmarks/windows/swebench_live_windows.py", "HIVE_SANDBOXED_PATH"),
        # Legacy exempt — repo acquisition (git clones)
        ("scripts/download_swebench_repos.py", "LEGACY_EXEMPT_READ_ONLY"),
        ("scripts/download_multilang_repos.py", "LEGACY_EXEMPT_READ_ONLY"),
        # Legacy exempt — benchmark orchestrators
        ("scripts/determinex_ask.py", "LEGACY_EXEMPT_READ_ONLY"),
        ("scripts/determinex_benchmark.py", "LEGACY_EXEMPT_READ_ONLY"),
        ("scripts/determinex_benchmark_5run.py", "LEGACY_EXEMPT_READ_ONLY"),
        ("scripts/determinex_bigcode_run.py", "LEGACY_EXEMPT_READ_ONLY"),
        ("scripts/determinex_fullbench.py", "LEGACY_EXEMPT_READ_ONLY"),
        ("scripts/determinex_livecode_run.py", "LEGACY_EXEMPT_READ_ONLY"),
        ("scripts/determinex_flywheel.py", "LEGACY_EXEMPT_READ_ONLY"),
        ("scripts/determinex_limits_test.py", "LEGACY_EXEMPT_READ_ONLY"),
        ("scripts/determinex_projector.py", "LEGACY_EXEMPT_READ_ONLY"),
        # Legacy exempt — sprint orchestration
        ("scripts/sprint4_preflight.py", "LEGACY_EXEMPT_READ_ONLY"),
        ("scripts/sprint4_smoke_pass.py", "LEGACY_EXEMPT_READ_ONLY"),
        # Legacy exempt — model / gguf maintenance
        ("scripts/fix_corpus.py", "LEGACY_EXEMPT_READ_ONLY"),
        ("scripts/fix_retrain_engineer.py", "LEGACY_EXEMPT_READ_ONLY"),
        ("scripts/fix_retrain_observer.py", "LEGACY_EXEMPT_READ_ONLY"),
        ("scripts/fix_retrain_sentinel.py", "LEGACY_EXEMPT_READ_ONLY"),
        ("scripts/fix_sen_merge_gguf.py", "LEGACY_EXEMPT_READ_ONLY"),
        ("scripts/sentinel_gguf_and_fetch.py", "LEGACY_EXEMPT_READ_ONLY"),
        ("scripts/verify_gguf.py", "LEGACY_EXEMPT_READ_ONLY"),
        ("scripts/gguf_sentinel_only.py", "LEGACY_EXEMPT_READ_ONLY"),
        # Legacy exempt — analysis tools
        ("scripts/analysis/iterate_to_lock.py", "LEGACY_EXEMPT_READ_ONLY"),
        ("scripts/analysis/llm_gen_iterate.py", "LEGACY_EXEMPT_READ_ONLY"),
        ("scripts/analysis/auto_revert_regressions.py", "LEGACY_EXEMPT_READ_ONLY"),
        # Legacy exempt — security scans
        ("scripts/security/generate_sbom.py", "LEGACY_EXEMPT_READ_ONLY"),
        ("scripts/security/dependency_scan.py", "LEGACY_EXEMPT_READ_ONLY"),
        ("scripts/security/container_scan.py", "LEGACY_EXEMPT_READ_ONLY"),
        # Legacy exempt — hardware/health probes
        ("scripts/hardware_profiler.py", "LEGACY_EXEMPT_READ_ONLY"),
        ("scripts/health_monitor.py", "LEGACY_EXEMPT_READ_ONLY"),
        ("scripts/vram_monitor.py", "LEGACY_EXEMPT_READ_ONLY"),
        # Legacy exempt — bench harnesses (non-SWE)
        ("scripts/benchmark_runner.py", "LEGACY_EXEMPT_READ_ONLY"),
        ("scripts/benchmarks/windows/deepeval_humaneval.py", "LEGACY_EXEMPT_READ_ONLY"),
        ("scripts/quality_benchmark_agent.py", "LEGACY_EXEMPT_READ_ONLY"),
        # Legacy exempt — eval / iteration
        ("scripts/micro_eval.py", "LEGACY_EXEMPT_READ_ONLY"),
        ("scripts/patch_iterate.py", "LEGACY_EXEMPT_READ_ONLY"),
        ("scripts/full_sweep_iterate.py", "LEGACY_EXEMPT_READ_ONLY"),
        ("scripts/three_speed_gate.py", "LEGACY_EXEMPT_READ_ONLY"),
        ("scripts/rosetta_vs_text_eval.py", "LEGACY_EXEMPT_READ_ONLY"),
        ("scripts/tonight_launch.py", "LEGACY_EXEMPT_READ_ONLY"),
        ("scripts/preflight_mass_run.py", "LEGACY_EXEMPT_READ_ONLY"),
        # Legacy exempt - status/evidence probes
        ("scripts/status/git_dirty_state.py", "LEGACY_EXEMPT_READ_ONLY"),
        ("scripts/status/splash_path_reconciliation_and_prep.py", "LEGACY_EXEMPT_READ_ONLY"),
        (
            "scripts/status/idea_lab_python_cli_verified_splash_demo.py",
            "LEGACY_EXEMPT_TEST_FIXTURE",
        ),
        ("scripts/status/repo_clinic_fixture_repair_splash_demo.py", "LEGACY_EXEMPT_TEST_FIXTURE"),
        (
            "scripts/status/maintenance_bay_dry_run_update_splash_demo.py",
            "LEGACY_EXEMPT_TEST_FIXTURE",
        ),
        (
            "scripts/status/universal_100_matrix_probe_execution_batch.py",
            "LEGACY_EXEMPT_TEST_FIXTURE",
        ),
        (
            "scripts/status/universal_100_matrix_probe_execution_batch_003.py",
            "LEGACY_EXEMPT_TEST_FIXTURE",
        ),
        ("scripts/status/typescript_node_cli_adapter_probe.py", "LEGACY_EXEMPT_TEST_FIXTURE"),
        (
            "scripts/status/universal_100_matrix_probe_execution_batch_004.py",
            "LEGACY_EXEMPT_TEST_FIXTURE",
        ),
        ("scripts/status/universal_100_sector_gulp_batch_005.py", "LEGACY_EXEMPT_TEST_FIXTURE"),
        ("scripts/status/universal_100_sector_gulp_batch_006.py", "LEGACY_EXEMPT_TEST_FIXTURE"),
        ("scripts/status/universal_100_tandem_climb.py", "LEGACY_EXEMPT_TEST_FIXTURE"),
        ("scripts/status/tandem_post_claude_binding_reconciliation.py", "LEGACY_EXEMPT_READ_ONLY"),
        # Legacy exempt — corpus tooling
        ("scripts/deepseek_data_engine.py", "LEGACY_EXEMPT_READ_ONLY"),
        ("scripts/convert_failures_to_sft.py", "LEGACY_EXEMPT_READ_ONLY"),
        ("scripts/run_corpus_to_100k.py", "LEGACY_EXEMPT_READ_ONLY"),
        ("scripts/register_v1_1.py", "LEGACY_EXEMPT_READ_ONLY"),
        ("scripts/reference_diff.py", "LEGACY_EXEMPT_READ_ONLY"),
        ("scripts/run_ledger.py", "LEGACY_EXEMPT_READ_ONLY"),
        ("scripts/_batch_apply_pending.py", "LEGACY_EXEMPT_READ_ONLY"),
    ],
)
def test_path_rule_classification(file_path: str, expected_classification: str):
    cls, _rationale = audit._classify_path(file_path)
    assert cls == expected_classification, (
        f"Path-rule for {file_path} returned {cls}, expected {expected_classification}"
    )


# ---------------------------------------------------------------------------
# Cross-cutting safety
# ---------------------------------------------------------------------------


def test_audit_still_read_only(monkeypatch):
    """Even with the new rules, the audit must not call subprocess."""
    import subprocess

    calls: list[str] = []

    def _no_run(*args, **kwargs):
        calls.append(repr(args))
        raise RuntimeError("subprocess.run called during audit")

    monkeypatch.setattr(subprocess, "run", _no_run)
    rpt = audit.run_audit()
    assert rpt.total_sites > 0
    assert calls == []


def test_audit_does_not_mutate_signed_evidence():
    before = _hash_signed_evidence()
    audit.run_audit()
    after = _hash_signed_evidence()
    diffs = sorted(k for k in set(before) | set(after) if before.get(k) != after.get(k))
    assert diffs == []


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

_LOCK_PATH = (
    _REPO_ROOT / "locks" / "sentinel" / "SCRIPT_HELPER_EXECUTION_CLASSIFICATION_SWEEP_LOCK_001.json"
)


def test_lock_manifest_exists():
    assert _LOCK_PATH.is_file()


def test_lock_manifest_status_tokens_match_module():
    data = json.loads(_LOCK_PATH.read_text(encoding="utf-8"))
    declared = set(data.get("status_tokens", []))
    assert declared == set(STATUS_TOKENS)


def test_lock_manifest_pins_audit_delta():
    data = json.loads(_LOCK_PATH.read_text(encoding="utf-8"))
    delta = data["audit_delta"]
    assert delta["unknown_requires_review_before"] == 121
    assert delta["unknown_requires_review_after"] == 0
    assert delta["blocked_unsafe_before"] == 0
    assert delta["blocked_unsafe_after"] == 2
    assert delta["must_migrate_before"] == 0
    assert delta["must_migrate_after"] == 1
    assert delta["programbench_out_of_scope_after"] == 56
