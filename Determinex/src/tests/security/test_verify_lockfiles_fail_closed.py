"""An unreadable requirements file is not a clean requirements file.

WHY THIS EXISTS
---------------
`verify_lockfiles.check_file` opened each requirements file inside a broad `try` and returned `[]` on
any failure. `[]` means "no violations", so a file that could not be read contributed **zero** to
`critical_count` and `high_count` -- and `passed` is `critical_count == 0 and high_count == 0`. So the
gate reported a pass for a file it had never inspected.

This is the same defect as S0.2 in `secret_scan` ("a failed scan read as a clean scan"), in a
different gate, found 2026-07-30 by scanning for broad exception handlers that return a success-ish
value. The pattern is worth naming because it keeps recurring here: the failure path and the
everything-is-fine path being represented by the same value.

Note the contrast with `dependency_scan._load_waivers`, which also returns `[]` on error and is
CORRECT to do so: empty waivers means nothing is excused, which is stricter rather than laxer. The
test for "does a broad handler matter?" is always "does the returned value read as pass or as fail?".
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
for _p in (ROOT, ROOT / "scripts", ROOT / "scripts" / "security"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import verify_lockfiles  # noqa: E402


def test_an_unreadable_requirements_file_is_reported_not_silently_passed(tmp_path, monkeypatch):
    """THE regression. A read failure must produce a blocking violation, not an empty list."""
    target = tmp_path / "requirements.txt"
    target.write_text("requests==2.32.3\n", encoding="utf-8")

    def boom(*_a, **_k):
        raise PermissionError("locked by another process")

    monkeypatch.setattr(Path, "read_text", boom)

    violations = verify_lockfiles.check_file(target)
    assert violations, (
        "an unreadable requirements file produced zero violations, so the gate would pass on a file "
        "it never checked"
    )
    assert any(v.severity in {"CRITICAL", "HIGH"} for v in violations), (
        f"the unreadable-file violation is not severe enough to block; `passed` only considers "
        f"CRITICAL and HIGH, so a MEDIUM here would still pass: {[v.severity for v in violations]}"
    )
    assert any(
        "never checked" in v.reason or "could not be read" in v.reason for v in violations
    ), (
        "the violation does not say the file was unread, so a reader would think it found a real "
        "pinning problem"
    )


def test_a_readable_clean_file_still_produces_no_violations(tmp_path):
    """The obvious counterpart: over-reporting would make the gate useless and get switched off."""
    target = tmp_path / "requirements.txt"
    target.write_text(
        "# a comment\n\nrequests==2.32.3\nurllib3==2.2.2\n",
        encoding="utf-8",
    )
    assert verify_lockfiles.check_file(target) == []


def test_the_pass_verdict_requires_both_critical_and_high_to_be_zero():
    """Pins the property the fix above relies on. If `passed` ever narrowed back to
    `critical_count == 0`, a HIGH unreadable-file violation would stop blocking and this whole fix
    would go quiet -- which is how S1.4 originally happened (no code path emitted CRITICAL at all, so
    the gate could not fail)."""
    report = verify_lockfiles.LockfileReport()
    report.violations.append(
        verify_lockfiles.LockfileViolation(
            file="x", line_num=0, line="", severity="HIGH", reason="unreadable"
        )
    )
    assert report.critical_count == 0
    assert report.high_count == 1
    data = report.to_dict() if hasattr(report, "to_dict") else None
    if data is not None and "passed" in data:
        assert data["passed"] is False, (
            "a HIGH violation does not fail the report, so the unreadable-file case cannot block"
        )
    else:  # pragma: no cover - shape changed
        pytest.skip("LockfileReport no longer exposes a passed verdict via to_dict()")


def test_no_lock_file_pins_below_a_declared_security_floor():
    """THE regression, and it was live.

    On 2026-07-30 `uv.lock` pinned 7 packages below the floors requirements.txt declares, and
    `requirements-lock.txt` -- whose own header said "For production ... bit-for-bit reproducible" --
    pinned 3, including cryptography 43.0.3 against a 48.0.1 floor (GHSA-537c-gmf6-5ccf) and torch
    2.5.1 against 2.13.0 (CVE-2025-3000 memory corruption). So the documented production install path
    installed known-vulnerable versions of packages the CVE remediation had already fixed.

    Two sources of truth for the same versions with nothing comparing them, and the security-relevant
    one silently losing. CI happened to be safe because it installs from requirements.txt, but
    `[tool.uv.workspace]` is configured so `uv sync` resolves from uv.lock.

    Both are now clean. This keeps them that way -- it is the only thing standing between a routine
    `uv lock` and a silent CVE regression.
    """
    conflicts = verify_lockfiles.check_lock_floor_conflicts(ROOT)
    assert not conflicts, (
        "a lock file pins below a floor declared in requirements.txt, which reintroduces the CVE that "
        "floor exists to close:\n  "
        + "\n  ".join(f"[{c.file}] {c.line} — {c.reason}" for c in conflicts)
        + "\nFix with: uv lock --upgrade-package <name>   (or pip-compile for requirements-lock.txt)"
    )


def test_floor_conflicts_are_blocking_not_advisory():
    """A MEDIUM here would be noted and ignored: `passed` only considers CRITICAL and HIGH. The
    unpinned-specifier findings are deliberately advisory because a `>=` floor is a considered choice
    -- converting those to `==` would freeze the floors and stop future fixes arriving. A lock
    *contradicting* a floor is categorically different and must block."""
    import inspect

    src = inspect.getsource(verify_lockfiles.check_lock_floor_conflicts)
    assert 'severity="HIGH"' in src, (
        "lock-vs-floor conflicts are no longer HIGH, so they cannot fail the gate"
    )


def test_the_floor_parser_reads_the_justifying_comment():
    """Violations should name the advisory, not just say "older". The floors were set during the
    CVE remediation and the comment is where that context lives."""
    floors = verify_lockfiles.declared_floors(ROOT)
    assert floors, "no >= floors parsed from requirements.txt"
    with_reasons = [n for n, (_v, comment) in floors.items() if comment]
    assert with_reasons, (
        "no floor carries its trailing comment, so a conflict cannot explain which advisory regresses"
    )


def test_the_lock_pins_everything_requirements_declares():
    """A partial lock that advertises itself as complete is worse than no lock, because it is trusted.

    On 2026-07-30 requirements-lock.txt pinned 19 of the 50 dependencies requirements.txt declares
    while its header read "For production: pip install -r requirements-lock.txt (pinned, bit-for-bit
    reproducible)". Following that instruction produced an environment missing 31 packages -- aiohttp,
    mcp, pillow, pyasn1, pygments, setuptools, urllib3 among them, largely the CVE-remediation
    additions. It now resolves the full transitive closure (148 pins) via
    `uv pip compile requirements.txt`.
    """
    gaps = verify_lockfiles.check_lock_covers_declared(ROOT)
    assert not gaps, "\n  ".join(g.reason for g in gaps)


def test_the_coverage_check_ignores_bench_only_requirements():
    """Scoped to the ROOT requirements.txt deliberately. The lock is compiled from that file, so
    evalplus / bigcodebench / sqlite-vec -- declared in scripts/requirements*.txt -- are outside its
    closure by design and must not be reported as gaps. Without this scoping the check would fail
    permanently and get switched off, which is how S1.4 happened."""
    import inspect

    src = inspect.getsource(verify_lockfiles.check_lock_covers_declared)
    assert '"requirements.txt"' in src, "the coverage check no longer scopes to the root file"
    assert "_REQUIREMENTS_FILES" not in src, (
        "the coverage check now iterates every requirements file, which would report the bench-only "
        "dependencies as missing from a lock that is not supposed to contain them"
    )
