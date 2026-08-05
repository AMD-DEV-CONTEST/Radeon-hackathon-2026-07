"""A dependency scan that could not run must not erase one that did.

WHY THIS EXISTS
---------------
Found by diffing an uncommitted working-tree change on 2026-07-28. The artifact
`assurance/security/dependency_scan.json` had recorded a real run on 2026-07-23 --
383 packages, 5 HIGH CVEs, each enumerated. A later run on a machine whose venv
has no `pip_audit` module replaced the whole thing with zeros and an empty
vulnerability list.

The blocking decision itself was already correct: `ScanReport.blocked` returns
True whenever `scan_error` is set, with a comment recording that exact
false-confidence bug. So it was not a silent PASS. But the *evidence* of 5 known
HIGH vulnerabilities was destroyed by a run that scanned nothing, and the artifact
gave no clue why every count had gone to zero -- `scan_error` was not serialised.

The protection mirrors the ProgramBench eval path's `_persist_best`: a starved or
failed re-run never clobbers a good result.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
for p in (str(REPO_ROOT), str(REPO_ROOT / "scripts")):
    if p not in sys.path:
        sys.path.insert(0, p)

from security.dependency_scan import ScanReport, Vulnerability, _merge_over_previous  # noqa: E402

_REAL_SCAN = {
    "scanner": "pip-audit",
    "timestamp": "2026-07-23T16:14:44.418859+00:00",
    "total_packages": 383,
    "critical_count": 0,
    "high_count": 5,
    "blocked": True,
    "vulnerability_count": 5,
    "vulnerabilities": [
        {
            "id": "PYSEC-2026-2335",
            "package": "aider-chat",
            "version": "0.86.2",
            "fixed": "",
            "severity": "HIGH",
            "waived": False,
        }
    ],
}

_CLEAN_SCAN = {
    **_REAL_SCAN,
    "high_count": 0,
    "blocked": False,
    "vulnerability_count": 0,
    "vulnerabilities": [],
}


def _failed_attempt() -> dict:
    return ScanReport(
        scanner="none",
        timestamp="2026-07-28T21:29:29.894668+00:00",
        total_packages=0,
        scan_error="No scanner available. Install pip-audit: pip install pip-audit",
    ).to_dict()


def _write(tmp_path: Path, payload: dict) -> Path:
    out = tmp_path / "dependency_scan.json"
    out.write_text(json.dumps(payload), encoding="utf-8")
    return out


# ── the destructive case ─────────────────────────────────────────────────────


def test_a_failed_scan_preserves_the_previous_findings(tmp_path):
    out = _write(tmp_path, _REAL_SCAN)
    merged = _merge_over_previous(_failed_attempt(), out)

    assert merged["vulnerability_count"] == 5, "the 5 HIGH findings were erased"
    assert merged["vulnerabilities"], "the enumerated vulnerabilities were erased"
    assert merged["total_packages"] == 383
    assert merged["scanner"] == "pip-audit"


def test_the_preserved_record_is_marked_stale_and_explains_itself(tmp_path):
    out = _write(tmp_path, _REAL_SCAN)
    merged = _merge_over_previous(_failed_attempt(), out)

    assert merged["stale"] is True
    assert "pip-audit" in merged["scan_error"]
    # `timestamp` must still name when the findings were OBSERVED, with the failed
    # attempt recorded separately -- otherwise stale findings read as fresh.
    assert merged["timestamp"] == _REAL_SCAN["timestamp"]
    assert merged["last_attempt_timestamp"] == "2026-07-28T21:29:29.894668+00:00"


def test_a_stale_clean_record_still_blocks(tmp_path):
    """The false-confidence case. If the last real scan found nothing and the
    scanner is now missing, "clean five days ago and unscannable today" is not
    clearance -- keeping blocked=False would be exactly the silent PASS this
    whole path exists to prevent."""
    out = _write(tmp_path, _CLEAN_SCAN)
    merged = _merge_over_previous(_failed_attempt(), out)

    assert merged["blocked"] is True, "a stale clean scan was reported as passing"
    assert merged["stale"] is True


# ── the cases that must NOT be merged ────────────────────────────────────────


def test_a_real_scan_replaces_the_previous_record_outright(tmp_path):
    """Retention applies only to failures. A scan that ran is the new truth,
    including when it finds fewer vulnerabilities than before -- otherwise fixed
    CVEs would haunt the artifact forever."""
    out = _write(tmp_path, _REAL_SCAN)
    fresh = ScanReport(
        scanner="pip-audit",
        timestamp="2026-07-29T00:00:00+00:00",
        total_packages=390,
        vulnerabilities=[],
    ).to_dict()

    merged = _merge_over_previous(fresh, out)
    assert merged["vulnerability_count"] == 0
    assert merged["total_packages"] == 390
    assert merged["blocked"] is False
    assert "stale" not in merged


def test_findings_survive_a_SECOND_consecutive_failed_scan(tmp_path):
    """The bug the first version of this fix shipped with.

    A record that _merge_over_previous has already preserved carries a real
    scanner name AND a scan_error. The first implementation used scan_error to
    mean "the previous run did not scan either", so the second failed run in a row
    discarded the findings the first one had just protected -- the protection
    survived exactly one failure.

    Missed by test_two_consecutive_failures_do_not_invent_findings below because
    that one uses a BARE failure as the previous record. Found instead by running
    security_gate.py against the committed artifact and watching 5 HIGH findings
    become 0 again.
    """
    out = _write(tmp_path, _REAL_SCAN)
    once = _merge_over_previous(_failed_attempt(), out)
    out.write_text(json.dumps(once), encoding="utf-8")

    twice = _merge_over_previous(_failed_attempt(), out)
    assert twice["vulnerability_count"] == 5, (
        "the second consecutive failed scan erased findings the first one preserved"
    )
    assert twice["blocked"] is True and twice["stale"] is True
    assert twice["timestamp"] == _REAL_SCAN["timestamp"], (
        "the observation date drifted; it must keep naming when the findings were actually seen"
    )


def test_two_consecutive_failures_do_not_invent_findings(tmp_path):
    out = _write(tmp_path, _failed_attempt())
    merged = _merge_over_previous(_failed_attempt(), out)
    assert merged["vulnerability_count"] == 0
    assert merged["blocked"] is True
    assert merged["scanner"] == "none"


def test_a_missing_or_corrupt_previous_file_is_not_fatal(tmp_path):
    merged = _merge_over_previous(_failed_attempt(), tmp_path / "absent.json")
    assert merged["scanner"] == "none" and merged["blocked"] is True

    corrupt = tmp_path / "corrupt.json"
    corrupt.write_text("{not json", encoding="utf-8")
    merged = _merge_over_previous(_failed_attempt(), corrupt)
    assert merged["scanner"] == "none" and merged["blocked"] is True


# ── the artifact must be readable on its own ─────────────────────────────────


def test_scan_error_is_serialised_so_zero_counts_are_explainable():
    """`blocked: true` with every count at 0 and no scan_error field is
    unreadable: nothing distinguishes "scanned clean, blocked for another reason"
    from "never scanned at all"."""
    d = _failed_attempt()
    assert "scan_error" in d and d["scan_error"]

    real = ScanReport(
        scanner="pip-audit",
        timestamp="t",
        total_packages=1,
        vulnerabilities=[
            Vulnerability(
                vuln_id="X",
                package="p",
                installed_version="1",
                fixed_version="2",
                severity="HIGH",
                description="d",
            )
        ],
    ).to_dict()
    assert real["scan_error"] is None
    assert real["blocked"] is True and real["high_count"] == 1
