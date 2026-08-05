"""Declared requirements vs the environment that is actually installed.

WHY THIS EXISTS
---------------
On 2026-07-28 the first real pip-audit run in five days found 42 HIGH CVEs across 7
packages. Every available fix was ALREADY DECLARED in requirements.txt --
`aiohttp>=3.14.1`, `cryptography>=48.0.1`, `pillow>=12.3.0`, `setuptools>=83.0.0`,
each with its CVE id in a trailing comment -- while the venv still held aiohttp
3.13.5, cryptography 48.0.0, pillow 12.2.0 and setuptools 81.0.0.

The tool that would have caught it was in exactly the same state: `pip-audit>=2.7.0`
was declared at requirements.txt:24 and `pip_audit` was not installed, so
dependency_scan.py reported "No scanner available" rather than 42 CVEs, and the
security gate blocked on a scan that could not run.

`verify_lockfiles.py` inspects the requirement FILES -- pinning style, known-bad
patterns, unpinned VCS refs -- and never looks at the environment, so nothing
anywhere compared declared against installed. A declared floor that is not installed
is a fiction; these tests are what make that fiction fail loudly.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
for p in (str(REPO_ROOT), str(REPO_ROOT / "scripts"), str(REPO_ROOT / "scripts" / "security")):
    if p not in sys.path:
        sys.path.insert(0, p)

verify_installed = pytest.importorskip("verify_installed")
pytest.importorskip("packaging")


# ── the parser decides what is even checkable ────────────────────────────────


@pytest.mark.parametrize(
    "line,expected_name",
    [
        ("aiohttp>=3.14.1  # 11 CVEs, fixed 2026-06-30", "aiohttp"),
        ("torch>=2.13.0", "torch"),
        ("pillow==12.3.0", "pillow"),
        ("python-multipart>=0.0.31", "python-multipart"),
    ],
)
def test_pinned_requirements_are_parsed(line, expected_name):
    parsed = verify_installed._parse_requirement_line(line)
    assert parsed is not None, f"{line!r} should be checkable"
    assert parsed[0] == expected_name


@pytest.mark.parametrize(
    "line",
    [
        "",
        "   ",
        "# just a comment",
        "-r other-requirements.txt",
        "-e .",
        "--extra-index-url https://example.invalid/simple",
        "requests",  # unpinned: nothing to verify
        "torch @ https://example.invalid/torch.whl",  # direct URL
    ],
)
def test_unverifiable_lines_are_skipped(line):
    assert verify_installed._parse_requirement_line(line) is None


def test_a_cve_in_the_comment_marks_the_line_as_a_security_floor():
    """This is what makes the difference between CRITICAL and HIGH. A floor written
    to close a CVE, and then not installed, is the exact failure this module exists
    for -- it reads as fixed and is not."""
    for comment, want in (
        ("# CVE-2026-54273", ["CVE-2026-54273"]),
        ("# PYSEC-2026-2447", ["PYSEC-2026-2447"]),
        ("# GHSA-537c-gmf6-5ccf", ["GHSA-537c-gmf6-5ccf"]),
        ("# just a normal note", []),
    ):
        _, _, ids = verify_installed._parse_requirement_line(f"aiohttp>=3.14.1  {comment}")
        assert [i.upper() for i in ids] == [w.upper() for w in want], comment


# ── severity, which is the whole point ───────────────────────────────────────


def _drift(**kw):
    base = dict(
        package="pkg",
        declared=">=2.0",
        installed="1.0",
        severity="HIGH",
        source_file="requirements.txt",
        security_ids=[],
    )
    base.update(kw)
    return verify_installed.Drift(**base)


def test_an_unapplied_security_floor_blocks_but_a_merely_absent_package_does_not():
    """Blocking on absence would make this gate noise: plenty of declared packages
    are optional extras that a given environment legitimately lacks. Blocking on an
    unapplied SECURITY floor is the entire reason the check exists."""
    crit = verify_installed.to_dict([_drift(severity="CRITICAL", security_ids=["CVE-2026-1"])])
    assert crit["critical_count"] == 1 and crit["blocked"] is True

    absent = verify_installed.to_dict([_drift(severity="MEDIUM", installed=None)])
    assert absent["missing_count"] == 1 and absent["blocked"] is False

    below = verify_installed.to_dict([_drift(severity="HIGH")])
    assert below["high_count"] == 1 and below["blocked"] is False


def test_the_describe_line_names_both_versions():
    d = _drift(
        package="aiohttp", declared=">=3.14.1", installed="3.13.5", security_ids=["CVE-2026-54273"]
    )
    text = d.describe()
    assert "aiohttp" in text and ">=3.14.1" in text and "3.13.5" in text
    assert "CVE-2026-54273" in text


def test_a_missing_package_says_so_rather_than_showing_a_version():
    assert "NOT INSTALLED" in _drift(installed=None).describe()


# ── the live environment ─────────────────────────────────────────────────────


def test_this_environment_has_no_unapplied_security_floor():
    """The regression guard for the original incident. If this goes red, some
    requirement line closing a CVE is declared and not installed -- run
    `python scripts/security/verify_installed.py` to see which, then install it.
    """
    payload = verify_installed.run(write=False)
    offenders = [d for d in payload["drifts"] if d["severity"] == "CRITICAL"]
    assert not offenders, "declared security floors are not installed: " + "; ".join(
        f"{d['package']} declared {d['declared']}, have {d['installed']}" for d in offenders
    )


def test_pip_audit_itself_is_installed():
    """Called out separately because it is the one absence that hid all the others:
    dependency_scan.py cannot scan without it and reports 'No scanner available',
    which is not distinguishable from 'clean' unless someone reads the field."""
    pytest.importorskip(
        "pip_audit",
        reason="pip-audit is declared in requirements.txt and must be installed, or "
        "dependency_scan cannot run at all",
    )
