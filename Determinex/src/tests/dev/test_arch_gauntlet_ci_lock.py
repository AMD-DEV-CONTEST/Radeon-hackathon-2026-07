"""Tests for ARCH_GAUNTLET_CI_LOCK_001.

Static assertions over the CI workflow file. The Claude rung that landed
this is responsible for ensuring the architecture gauntlet runs on
Linux/Ubuntu in CI alongside the focused per-rung test files. These tests
do NOT spawn an actual CI run — they verify the workflow structure so
drift between the workflow and the gauntlet's invariants is caught
locally (and by the python-tests CI job itself).
"""

from __future__ import annotations

import hashlib
import json
import re
import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
for _p in (_REPO_ROOT, _REPO_ROOT / "scripts"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

WORKFLOW_PATH = _REPO_ROOT / ".github" / "workflows" / "test.yml"
LOCKS_DIR = _REPO_ROOT / "locks" / "sentinel"
EVIDENCE_INDEX = _REPO_ROOT / "assurance" / "evidence" / "evidence_index.json"


STATUS_TOKENS = frozenset(
    {
        "ARCH_GAUNTLET_CI_WIRED",
        "WORKFLOW_PRESENT",
        "JOB_RUNS_ON_UBUNTU",
        "PYTHON_VERSION_PINNED",
        "GAUNTLET_INVOKED_STRICT",
        "EVIDENCE_VALIDATED_IN_CI",
        "FOCUSED_TESTS_INVOKED",
        "NO_DOCKER_PULLS",
        "NO_T_DRIVE_DEPENDENCY",
        "CORPUS_WRITE_GUARD_ACTIVE_IN_CI",
        "GAUNTLET_ARTIFACT_UPLOADED",
        "PROGRAMBENCH_UNTOUCHED",
        "SAFETY_DEFAULTS_RESPECTED",
    }
)


# Focused test files the CI job must invoke. Pinned here so a future
# rung addition that forgets to wire its file into CI is caught.
REQUIRED_FOCUSED_TESTS = (
    "tests/dev/test_architecture_regression_gauntlet_lock.py",
    "tests/dev/test_parallel_execution_layer_audit_lock.py",
    "tests/intake/test_codebase_explorer_smoke_lock.py",
    "tests/intake/test_build_adapter_registry_lock.py",
    "tests/intake/test_verifier_coverage_matrix_lock.py",
    "tests/intake/test_hardened_intake_execution_runner_lock.py",
    "tests/repair/test_hardened_repair_pipeline_executors_lock.py",
)


def _workflow_text() -> str:
    return WORKFLOW_PATH.read_text(encoding="utf-8")


def _sha256(p: Path) -> str | None:
    if not p.is_file():
        return None
    h = hashlib.sha256()
    with p.open("rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


# ---------------------------------------------------------------------------
# Status / closed set
# ---------------------------------------------------------------------------


def test_status_tokens_match_expected_set():
    expected = {
        "ARCH_GAUNTLET_CI_WIRED",
        "WORKFLOW_PRESENT",
        "JOB_RUNS_ON_UBUNTU",
        "PYTHON_VERSION_PINNED",
        "GAUNTLET_INVOKED_STRICT",
        "EVIDENCE_VALIDATED_IN_CI",
        "FOCUSED_TESTS_INVOKED",
        "NO_DOCKER_PULLS",
        "NO_T_DRIVE_DEPENDENCY",
        "CORPUS_WRITE_GUARD_ACTIVE_IN_CI",
        "GAUNTLET_ARTIFACT_UPLOADED",
        "PROGRAMBENCH_UNTOUCHED",
        "SAFETY_DEFAULTS_RESPECTED",
    }
    assert set(STATUS_TOKENS) == expected


# ---------------------------------------------------------------------------
# Workflow file presence + shape
# ---------------------------------------------------------------------------


def test_workflow_file_exists():
    assert WORKFLOW_PATH.is_file(), f"missing: {WORKFLOW_PATH}"


def test_workflow_defines_arch_gauntlet_job():
    """The job's YAML key is `arch-gauntlet:`. Match on the indented key
    line specifically so the assertion is not accidentally satisfied by
    a comment."""
    text = _workflow_text()
    assert re.search(r"^\s*arch-gauntlet:\s*$", text, re.MULTILINE), (
        "arch-gauntlet job not found in test.yml"
    )


def test_arch_gauntlet_runs_on_ubuntu():
    """Linux witness is the whole point of this rung. Ubuntu must be
    explicitly named."""
    text = _workflow_text()
    # After the job key, the runs-on directive must be ubuntu-latest.
    match = re.search(
        r"^\s*arch-gauntlet:\s*$.*?^\s*runs-on:\s*ubuntu-latest",
        text,
        re.MULTILINE | re.DOTALL,
    )
    assert match, "arch-gauntlet job must use runs-on: ubuntu-latest"


def test_arch_gauntlet_pins_python_3_11():
    """The job MUST pin Python 3.11 so the gauntlet runs against the same
    interpreter version the locks were issued against."""
    text = _workflow_text()
    # Pin appears as `python-version: "3.11"` somewhere after the job key
    after_job = text.split("arch-gauntlet:", 1)[1]
    assert 'python-version: "3.11"' in after_job, (
        'arch-gauntlet job must pin python-version: "3.11"'
    )


def test_arch_gauntlet_invokes_gauntlet_with_strict():
    """The gauntlet must run in --strict mode so non-PASSED rollups fail
    the CI job (exit 1)."""
    text = _workflow_text()
    after_job = text.split("arch-gauntlet:", 1)[1]
    # Tolerate either single-line or multi-line invocation; just require
    # the script path AND the --strict flag both appear after the job key.
    assert "scripts/dev/architecture_regression_gauntlet.py" in after_job
    assert "--strict" in after_job, (
        "Gauntlet must be invoked with --strict so non-PASSED rollups fail CI"
    )


def test_arch_gauntlet_invokes_evidence_validate():
    """`determinex evidence validate` must be wired into the same job —
    not just the standalone evidence-validate job — so a gauntlet run
    proves evidence stayed intact through the focused-test execution."""
    text = _workflow_text()
    after_job = text.split("arch-gauntlet:", 1)[1]
    assert "determinex evidence validate" in after_job


@pytest.mark.parametrize("test_path", REQUIRED_FOCUSED_TESTS)
def test_arch_gauntlet_invokes_each_focused_test_file(test_path: str):
    """Every architecture/intake/repair focused test file from rungs 1-6
    must be explicitly invoked by the CI job. If a future rung adds a
    new file and forgets to wire it here, the lock manifest test
    `test_lock_manifest_lists_all_required_focused_tests` will catch
    the gap; this test catches the workflow-side mirror."""
    text = _workflow_text()
    after_job = text.split("arch-gauntlet:", 1)[1]
    assert test_path in after_job, (
        f"arch-gauntlet job does not invoke required focused test: {test_path}"
    )


def test_arch_gauntlet_sets_corpus_write_guard():
    """DETERMINEX_NO_CORPUS_WRITE=1 must be set in the job env so any
    accidental corpus write during the gauntlet flow raises rather than
    silently mutating CI state."""
    text = _workflow_text()
    after_job = text.split("arch-gauntlet:", 1)[1]
    assert 'DETERMINEX_NO_CORPUS_WRITE: "1"' in after_job, (
        'arch-gauntlet job must set DETERMINEX_NO_CORPUS_WRITE="1" in env'
    )


def test_arch_gauntlet_sets_determinex_root_to_workspace():
    text = _workflow_text()
    after_job = text.split("arch-gauntlet:", 1)[1]
    assert "DETERMINEX_ROOT: ${{ github.workspace }}" in after_job


def test_arch_gauntlet_uploads_artifact():
    text = _workflow_text()
    after_job = text.split("arch-gauntlet:", 1)[1]
    assert "actions/upload-artifact" in after_job, (
        "arch-gauntlet job must upload the gauntlet JSON as an artifact"
    )
    assert "architecture_regression_gauntlet.json" in after_job


# ---------------------------------------------------------------------------
# No prohibited operations
# ---------------------------------------------------------------------------


def test_arch_gauntlet_does_not_pull_docker_images():
    """The job MUST NOT contain `docker pull` or `docker run` or other
    container-runtime invocations — by directive."""
    text = _workflow_text()
    after_job = text.split("arch-gauntlet:", 1)[1]
    for forbidden in (
        "docker pull",
        "docker run",
        "docker compose ",
        "docker-compose ",
        "podman pull",
        "podman run",
    ):
        assert forbidden not in after_job, f"arch-gauntlet job must not include `{forbidden}`"


def test_arch_gauntlet_does_not_reference_t_drive():
    """No T:/ drive letter in the job — environment portability is the
    whole point."""
    text = _workflow_text()
    after_job = text.split("arch-gauntlet:", 1)[1]
    # Allow case-insensitive match on both forward and back slash spellings
    assert not re.search(r"[Tt]:[/\\]", after_job), (
        "arch-gauntlet job must not reference a T:/ drive path"
    )


def test_arch_gauntlet_does_not_run_programbench():
    """The job MUST NOT invoke ProgramBench or its helpers — by directive."""
    text = _workflow_text()
    after_job = text.split("arch-gauntlet:", 1)[1]
    for forbidden in (
        "programbench eval",
        "pb_factory_",
        "pb_hetzner_",
        "scripts/determinex_programbench",
        "scripts/pb_",
        "tests/corpus/programbench/",
    ):
        assert forbidden not in after_job, (
            f"arch-gauntlet job must not invoke ProgramBench: `{forbidden}`"
        )


def test_arch_gauntlet_does_not_install_unpinned_packages():
    """Pip installs must come from requirements.txt or `pip install -e
    .[dev]` — not unpinned `pip install <package>` lines that drift."""
    text = _workflow_text()
    after_job = (
        text.split("arch-gauntlet:", 1)[1].split("\n\n", 1)[0]
        if "\n\n" in text.split("arch-gauntlet:", 1)[1]
        else text.split("arch-gauntlet:", 1)[1]
    )
    # Permitted forms: `pip install -r requirements.txt`, `pip install -e .[dev]`,
    # `pip install -e .`, `pip install --upgrade pip`.
    # Forbidden: bare `pip install <name>` with no version spec.
    for line in after_job.splitlines():
        stripped = line.strip()
        if not stripped.startswith("pip install"):
            continue
        # Strip the prefix and inspect arguments
        args = stripped[len("pip install") :].strip()
        if args.startswith("-r ") or args.startswith("-e ") or args.startswith("--upgrade"):
            continue
        # If we got here it's a bare `pip install <something>`. Flag it.
        pytest.fail(f"Unpinned pip install in arch-gauntlet job: {stripped}")


# ---------------------------------------------------------------------------
# Mirror tests: ensure the focused tests the job invokes actually exist
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("test_path", REQUIRED_FOCUSED_TESTS)
def test_required_focused_test_file_exists(test_path: str):
    p = _REPO_ROOT / test_path
    assert p.is_file(), f"missing required focused test file: {p}"


# ---------------------------------------------------------------------------
# Lock manifest alignment
# ---------------------------------------------------------------------------

_LOCK_PATH = _REPO_ROOT / "locks" / "sentinel" / "ARCH_GAUNTLET_CI_LOCK_001.json"


def test_lock_manifest_exists():
    assert _LOCK_PATH.is_file(), f"missing: {_LOCK_PATH}"


def test_lock_manifest_status_tokens_match_module():
    data = json.loads(_LOCK_PATH.read_text(encoding="utf-8"))
    declared = set(data.get("status_tokens", []))
    assert declared == set(STATUS_TOKENS)


def test_lock_manifest_lists_all_required_focused_tests():
    """The lock manifest's pinned `focused_tests_invoked` list must match
    the module's REQUIRED_FOCUSED_TESTS and the workflow file. Drift
    between any of the three is caught here."""
    data = json.loads(_LOCK_PATH.read_text(encoding="utf-8"))
    pinned = set(data.get("focused_tests_invoked", []))
    assert pinned == set(REQUIRED_FOCUSED_TESTS), (
        f"focused_tests_invoked drift:\n"
        f"  in lock not in module: {pinned - set(REQUIRED_FOCUSED_TESTS)}\n"
        f"  in module not in lock: {set(REQUIRED_FOCUSED_TESTS) - pinned}"
    )


def test_lock_manifest_pins_python_version():
    data = json.loads(_LOCK_PATH.read_text(encoding="utf-8"))
    assert data.get("python_version") == "3.11"


def test_lock_manifest_pins_runs_on():
    data = json.loads(_LOCK_PATH.read_text(encoding="utf-8"))
    assert data.get("runs_on") == "ubuntu-latest"


# ---------------------------------------------------------------------------
# Cross-cutting safety (local — no CI environment needed)
# ---------------------------------------------------------------------------


def test_corpus_write_guard_active():
    import os

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


def test_workflow_modification_does_not_mutate_signed_evidence():
    """The test loads the workflow file but does not write anything.
    Verify signed evidence sha-256 is unchanged after a full read."""
    before = {}
    for p in sorted(LOCKS_DIR.glob("*.json")):
        rel = p.relative_to(_REPO_ROOT)
        before[str(rel).replace("\\", "/")] = _sha256(p) or ""
    _ = _workflow_text()
    after = {}
    for p in sorted(LOCKS_DIR.glob("*.json")):
        rel = p.relative_to(_REPO_ROOT)
        after[str(rel).replace("\\", "/")] = _sha256(p) or ""
    diffs = sorted(k for k in set(before) | set(after) if before.get(k) != after.get(k))
    assert diffs == []
