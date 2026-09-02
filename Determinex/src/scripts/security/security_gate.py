#!/usr/bin/env python3
"""security_gate.py -- single pass/fail artifact over all security scanners.

Runs secret_scan, dependency_scan, verify_lockfiles, verify_installed,
license_scan, and container_scan (generate_sbom is informational, not a gate --
it has nothing to pass/fail, it just produces an inventory) and produces ONE
consolidated result instead of several scripts each interpreted separately.

verify_installed was added 2026-07-28: verify_lockfiles checks the requirement
FILES, and nothing checked the ENVIRONMENT, so 42 HIGH CVEs whose fixes were all
already declared in requirements.txt sat uninstalled -- including pip-audit
itself, which is why dependency_scan could only report "No scanner available". Matches the
pb_board_guard.py / pb_override_scan.py --guard convention: exit 0 = clean,
exit 1 = blocked, human-readable summary either way.

Usage:
  python scripts/security/security_gate.py           # run all gates, print summary
  python scripts/security/security_gate.py --guard   # same, but exit 1 on any block (CI use)
  python scripts/security/security_gate.py --json out.json   # also write machine-readable result
"""

from __future__ import annotations

import argparse
import contextlib
import io
import json
import sys
from contextlib import redirect_stdout
from datetime import UTC, datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts" / "security"))


@contextlib.contextmanager
def _bare_argv():
    """Each sub-scanner's main() calls argparse.parse_args() with no explicit
    argv, so it inherits THIS script's own --guard/--json flags and crashes.
    Sandbox sys.argv to just the program name for the duration of the call."""
    saved = sys.argv
    sys.argv = [saved[0]]
    try:
        yield
    finally:
        sys.argv = saved


def _run_secret_scan() -> tuple[bool, str]:
    import secret_scan  # type: ignore[import-not-found]

    buf = io.StringIO()
    with _bare_argv(), redirect_stdout(buf):
        code = secret_scan.main()
    lines = buf.getvalue().strip().splitlines()
    return (code == 0), (lines[-1] if lines else "no output")


def _run_dependency_scan() -> tuple[bool, str]:
    import dependency_scan  # type: ignore[import-not-found]

    r = dependency_scan.run()
    detail = f"{r.total_packages} packages, {len(r.vulnerabilities)} vulns ({r.critical_count} critical, {r.high_count} high)"
    if r.scan_error:
        detail = f"SCAN DID NOT RUN: {r.scan_error}"
    return (not r.blocked), detail


def _run_verify_lockfiles() -> tuple[bool, str]:
    import verify_lockfiles  # type: ignore[import-not-found]

    r = verify_lockfiles.run()
    return r.passed, f"{len(r.files_checked)} files checked, {r.critical_count} critical violations"


# Determinex's own declared license. Kept as a named constant so the exemption
# below is a statement about a specific license, not a blanket "ignore the repo
# root". See docs/policy and the LICENSE grant notice: AGPL-3.0-or-later, no
# carve-out.
_REPO_LICENSE_SPDX = "AGPL-3.0-or-later"


def _run_license_scan() -> tuple[bool, str]:
    import license_scan  # type: ignore[import-not-found]

    out_path = REPO_ROOT / "assurance" / "licenses" / "license_inventory.json"
    with _bare_argv():
        license_scan.main()
    data = json.loads(out_path.read_text(encoding="utf-8"))
    blocked = data.get("blocked_count", 0)
    # The repo's OWN license is not a third-party ingest finding -- license_scan's
    # red bucket means "do not train on this without legal review", which cannot
    # apply to Determinex's own source.
    #
    # The old exemption keyed on source == "none", written when the project shipped
    # a custom Source-Available LICENSE that carried no SPDX id. The project is now
    # AGPL-3.0-or-later with a real LICENSE file, so `source` is that file's path
    # and the exemption stopped matching -- the gate blocked on Determinex's own
    # correctly-licensed LICENSE (found live 2026-07-28, alongside the normalizer
    # bug that was separately reporting it as GPL-3.0-only).
    #
    # Keyed on the identifier rather than on having no source, so that swapping the
    # repo's license to something unexpected -- or failing to recognise it at all,
    # which yields spdx_id None -- still fails this gate rather than being waved
    # through as "the known false positive".
    real_blocks = [
        r
        for r in data.get("rows", [])
        if not (r.get("path") == str(REPO_ROOT) and r.get("spdx_id") == _REPO_LICENSE_SPDX)
    ]
    return (
        len(real_blocks) == 0
    ), f"{blocked} flagged ({len(real_blocks)} not the known repo-license false positive)"


def _run_container_scan() -> tuple[bool, str]:
    import container_scan  # type: ignore[import-not-found]

    out_path = REPO_ROOT / "assurance" / "security" / "container_scan.json"
    with _bare_argv():
        container_scan.main()
    data = json.loads(out_path.read_text(encoding="utf-8"))
    unpinned = data.get("unpinned_count", 0)
    # container_scan is inventory + advisory (docstring: "does not perform a
    # CVE scan by itself"), not a hard gate -- unpinned tags are a finding to
    # know about, not something that should block every commit. That part is a
    # deliberate design choice and stays.
    #
    # What was NOT honest (fixed 2026-07-30): when Docker is absent the result dict carries no
    # image_count, so `.get(..., 0)` rendered "0 images, 0 unpinned tags" and the row printed
    # [PASS] for a scanner that never ran. A scan that could not run and a scan that found nothing
    # produced identical output -- the same shape as the secret scanner that had never scanned.
    # Still non-blocking, but it now says which of the two happened.
    if "image_count" not in data or data.get("scan_error"):
        reason = str(data.get("scan_error") or data.get("error") or "docker unavailable")
        return True, f"DID NOT RUN ({reason}) -- no image inventory (advisory, non-blocking)"
    return (
        True,
        f"{data.get('image_count', 0)} images, {unpinned} unpinned tags (advisory, non-blocking)",
    )


def _run_verify_installed() -> tuple[bool, str]:
    """Does this environment actually satisfy the declared requirements?

    Added 2026-07-28 after a real pip-audit run found 42 HIGH CVEs whose fixes were
    ALL already declared in requirements.txt and none of them installed. Nothing
    compared declared against installed, so the floors read as applied for weeks.
    The tool that would have caught it -- pip-audit itself -- was in the same state:
    declared at requirements.txt:24, absent from the venv, which is why
    dependency_scan reported "No scanner available" instead of 42 CVEs.

    verify_lockfiles (above) inspects the requirement FILES and never the
    environment, so this is a genuinely separate property, not a duplicate check.
    """
    import verify_installed  # type: ignore[import-not-found]

    with _bare_argv():
        payload = verify_installed.run()
    crit, high, missing = (
        payload["critical_count"],
        payload["high_count"],
        payload["missing_count"],
    )
    detail = (
        f"{crit} unapplied security floor(s), {high} below declared floor, "
        f"{missing} declared-but-absent"
    )
    # Only an unapplied SECURITY floor blocks. A package that is simply absent is
    # usually an optional extra, and blocking on that would make this gate noise.
    return crit == 0, detail


GATES = [
    ("secret_scan", _run_secret_scan),
    ("dependency_scan", _run_dependency_scan),
    ("verify_lockfiles", _run_verify_lockfiles),
    ("verify_installed", _run_verify_installed),
    ("license_scan", _run_license_scan),
    ("container_scan", _run_container_scan),
]


def run_all() -> dict:
    results = []
    for name, fn in GATES:
        try:
            passed, detail = fn()
        except Exception as e:  # a gate crashing is a block, never a silent pass
            passed, detail = False, f"GATE CRASHED: {e}"
        results.append({"gate": name, "passed": passed, "detail": detail})
    overall = all(r["passed"] for r in results)
    return {
        "schema": "determinex-security-gate-v1",
        "generated_at": datetime.now(UTC).isoformat(),
        "overall_passed": overall,
        "gates": results,
    }


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    p.add_argument("--guard", action="store_true", help="exit 1 if any gate blocked (CI mode)")
    p.add_argument("--json", type=Path, help="also write the machine-readable result here")
    args = p.parse_args(argv)

    result = run_all()

    print("=== Determinex Security Gate ===")
    for g in result["gates"]:
        status = "PASS" if g["passed"] else "BLOCKED"
        print(f"  [{status:7s}] {g['gate']:20s} {g['detail']}")
    print()
    print(f"Overall: {'PASS' if result['overall_passed'] else 'BLOCKED'}")

    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(json.dumps(result, indent=2), encoding="utf-8")
        print(f"Wrote: {args.json}")

    if args.guard and not result["overall_passed"]:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
