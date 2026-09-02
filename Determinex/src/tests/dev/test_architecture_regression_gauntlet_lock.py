"""Tests for DETERMINEX_ARCHITECTURE_REGRESSION_GAUNTLET_LOCK_001.

The gauntlet itself is an integration runner that shells out to many
subprocesses; the bulk of its assertions are the runtime checks in
``scripts/dev/architecture_regression_gauntlet.py``. These tests exercise
the gauntlet's *machinery* — status-token closure, mutation detection,
report shape — and pin the lock manifest against the live module.
"""

from __future__ import annotations

import hashlib
import importlib
import json
import sys
from pathlib import Path
from typing import Any

import pytest

# Ensure scripts/ is importable
_REPO_ROOT = Path(__file__).resolve().parents[2]
_SCRIPTS_DIR = _REPO_ROOT / "scripts"
for _p in (_REPO_ROOT, _SCRIPTS_DIR):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

gauntlet = importlib.import_module("scripts.dev.architecture_regression_gauntlet")


# ---------------------------------------------------------------------------
# Module-level invariants
# ---------------------------------------------------------------------------


def test_gauntlet_module_imports():
    assert gauntlet.run_gauntlet is not None
    assert callable(gauntlet.run_gauntlet)
    assert callable(gauntlet.main)


def test_status_tokens_are_closed_set():
    """The set of status tokens must be frozen — drift here means the lock
    manifest's enumeration is out of date."""
    expected = {
        "ARCH_GAUNTLET_PASSED",
        "ARCH_GAUNTLET_FAILED",
        "CLI_COMMAND_AVAILABLE",
        "CLI_COMMAND_FAILED",
        "LEGACY_SCRIPT_COMPATIBLE",
        "LEGACY_SCRIPT_BROKEN",
        "READ_ONLY_COMMAND_MUTATED_EVIDENCE",
        "READ_ONLY_COMMAND_PRESERVED_EVIDENCE",
        "PATH_PORTABILITY_CONFIRMED",
        "PATH_PORTABILITY_FAILED",
        "UNSAFE_DEFAULT_BLOCKED",
        "UNSAFE_DEFAULT_OPEN",
        "JUST_RUNNER_PRESENT",
        "JUST_RUNNER_MISSING_SKIPPED",
    }
    assert set(gauntlet.STATUS_TOKENS) == expected


def test_repo_root_resolution_points_at_repo():
    assert (gauntlet.REPO_ROOT / "pyproject.toml").is_file()
    assert (gauntlet.SCRIPTS_DIR / "determinex_cli.py").is_file()


# ---------------------------------------------------------------------------
# Hash helpers — mutation-detection foundation
# ---------------------------------------------------------------------------


def test_hash_path_returns_none_for_missing(tmp_path: Path):
    assert gauntlet._hash_path(tmp_path / "does_not_exist") is None


def test_hash_path_detects_change(tmp_path: Path):
    p = tmp_path / "x.txt"
    p.write_text("hello", encoding="utf-8")
    h1 = gauntlet._hash_path(p)
    p.write_text("hello world", encoding="utf-8")
    h2 = gauntlet._hash_path(p)
    assert h1 is not None and h2 is not None and h1 != h2


def test_hash_path_matches_sha256(tmp_path: Path):
    p = tmp_path / "payload.bin"
    p.write_bytes(b"\x00\x01\x02\x03")
    assert gauntlet._hash_path(p) == hashlib.sha256(b"\x00\x01\x02\x03").hexdigest()


# ---------------------------------------------------------------------------
# Individual checks — fast, isolated
# ---------------------------------------------------------------------------


def test_check_cli_version_returns_known_token():
    status, detail = gauntlet.check_cli_version()
    assert status in {"CLI_COMMAND_AVAILABLE", "CLI_COMMAND_FAILED"}
    assert isinstance(detail, dict)
    assert "result" in detail


def test_check_cli_config_doctor_returns_known_token():
    status, _ = gauntlet.check_cli_config_doctor()
    assert status in {"CLI_COMMAND_AVAILABLE", "CLI_COMMAND_FAILED"}


def test_check_just_runner_returns_known_token():
    status, _ = gauntlet.check_just_runner()
    assert status in {"JUST_RUNNER_PRESENT", "JUST_RUNNER_MISSING_SKIPPED"}


def test_check_legacy_evidence_index_returns_known_token():
    status, _ = gauntlet.check_legacy_evidence_index()
    assert status in {"LEGACY_SCRIPT_COMPATIBLE", "LEGACY_SCRIPT_BROKEN"}


def test_read_only_guard_returns_preserved_on_clean_run():
    """Running the read-only guard against the live repo must report
    PRESERVED. If this ever flips, a regression has introduced a write
    side-effect to one of the inspection commands."""
    status, detail = gauntlet.check_read_only_preserves_evidence()
    assert status == "READ_ONLY_COMMAND_PRESERVED_EVIDENCE", (
        f"Inspection commands mutated signed evidence: {detail.get('mutated_files')}"
    )


def test_path_portability_confirmed_with_clean_env(tmp_path: Path):
    status, detail = gauntlet.check_path_portability(tmp_path)
    assert status == "PATH_PORTABILITY_CONFIRMED", detail


def test_unsafe_defaults_blocked_under_clean_env():
    status, detail = gauntlet.check_unsafe_defaults_fail_closed()
    assert status == "UNSAFE_DEFAULT_BLOCKED", detail


# ---------------------------------------------------------------------------
# Mutation detection — synthetic test
# ---------------------------------------------------------------------------


def test_hash_tree_detects_mutation(tmp_path: Path):
    """If a watched file is rewritten, _hash_tree must show a different
    digest. This proves the gauntlet's mutation detector is sensitive enough
    to flag a single-byte change."""
    (tmp_path / "a.json").write_text('{"v": 1}', encoding="utf-8")
    (tmp_path / "b.json").write_text('{"v": 2}', encoding="utf-8")
    before = gauntlet._hash_tree(tmp_path)
    # Mutate one byte
    (tmp_path / "a.json").write_text('{"v": 3}', encoding="utf-8")
    after = gauntlet._hash_tree(tmp_path)
    diffs = [k for k in before if before[k] != after.get(k)]
    assert diffs == ["a.json"], diffs


# ---------------------------------------------------------------------------
# Full gauntlet — end-to-end (slow-ish, ~30s; runs subprocess fleet)
# ---------------------------------------------------------------------------


@pytest.mark.slow
def test_full_gauntlet_passes_against_live_repo(tmp_path: Path):
    """The single end-to-end assertion: the gauntlet rolls up to PASSED
    against the live repo on the developer's machine and in CI."""
    report = gauntlet.run_gauntlet(tmp_root=tmp_path)
    assert report["rollup_status"] == "ARCH_GAUNTLET_PASSED", (
        "Gauntlet failed; details:\n"
        + json.dumps(
            [
                r
                for r in report["results"]
                if r["status"]
                in {
                    "CLI_COMMAND_FAILED",
                    "LEGACY_SCRIPT_BROKEN",
                    "READ_ONLY_COMMAND_MUTATED_EVIDENCE",
                    "PATH_PORTABILITY_FAILED",
                    "UNSAFE_DEFAULT_OPEN",
                    "ARCH_GAUNTLET_FAILED",
                }
            ],
            indent=2,
        )
    )
    # Shape assertions
    assert report["lock_id"] == "DETERMINEX_ARCHITECTURE_REGRESSION_GAUNTLET_LOCK_001"
    assert report["checks_run"] == 17
    assert report["checks_failed"] == 0


# ---------------------------------------------------------------------------
# Lock manifest alignment
# ---------------------------------------------------------------------------

_LOCK_PATH = (
    _REPO_ROOT / "locks" / "sentinel" / "DETERMINEX_ARCHITECTURE_REGRESSION_GAUNTLET_LOCK_001.json"
)


def test_lock_manifest_exists():
    assert _LOCK_PATH.is_file(), f"Lock manifest missing: {_LOCK_PATH}"


def test_lock_manifest_status_tokens_match_module():
    """The lock manifest's status token enumeration must equal the live
    module's STATUS_TOKENS. If they drift, either the lock or the code is
    stale."""
    data: dict[str, Any] = json.loads(_LOCK_PATH.read_text(encoding="utf-8"))
    declared = set(data.get("status_tokens", []))
    assert declared == set(gauntlet.STATUS_TOKENS), (
        f"Lock manifest status_tokens drift:\n"
        f"  in lock not in module: {declared - set(gauntlet.STATUS_TOKENS)}\n"
        f"  in module not in lock: {set(gauntlet.STATUS_TOKENS) - declared}"
    )


def test_lock_manifest_pins_checks_run():
    """The lock pins how many checks must run. If the number changes, both
    code and lock must be updated together."""
    data: dict[str, Any] = json.loads(_LOCK_PATH.read_text(encoding="utf-8"))
    assert data.get("checks_run") == 17
