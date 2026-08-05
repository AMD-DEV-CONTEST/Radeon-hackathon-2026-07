"""
Installed-vs-declared verifier — does this environment actually satisfy requirements?

WHY THIS EXISTS
---------------
On 2026-07-28 a real pip-audit run found 42 HIGH CVEs across 7 packages. Every one
of the fixes was ALREADY DECLARED in requirements.txt -- `aiohttp>=3.14.1`,
`cryptography>=48.0.1`, `pillow>=12.3.0`, `setuptools>=83.0.0`, each with the CVE id
in a trailing comment -- while the venv still held aiohttp 3.13.5, cryptography
48.0.0, pillow 12.2.0 and setuptools 81.0.0. The floors had been written and never
installed.

Worse, the one tool that would have caught it was itself only declared:
`pip-audit>=2.7.0` sat in requirements.txt while `pip_audit` was absent from the
venv, so `dependency_scan.py` reported "No scanner available" and the security gate
was blocked on a scan that could not run. Nothing anywhere compared what was
DECLARED against what was INSTALLED.

`verify_lockfiles.py` is the neighbouring check and does not cover this: it inspects
the requirement FILES (pinning style, known-bad patterns, unpinned VCS refs) and
never looks at the environment. A declared floor that is not installed is a fiction,
and this module is what makes that fiction fail loudly.

SEVERITY
--------
CRITICAL when the requirement line mentions a CVE / PYSEC / GHSA id, because that is
a security floor and an unapplied security floor is the exact failure above.
Otherwise HIGH for a version below the floor, and MEDIUM for a declared package that
is not installed at all (which may be an optional extra).

Usage::

    python scripts/security/verify_installed.py
    python scripts/security/verify_installed.py --json
    python scripts/security/verify_installed.py --strict   # exit 1 on CRITICAL
"""

from __future__ import annotations

import argparse
import json
import logging
import re
import sys
from dataclasses import dataclass, field
from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as installed_version
from pathlib import Path

log = logging.getLogger(__name__)

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_OUTPUT = _REPO_ROOT / "assurance" / "security" / "installed_drift.json"

# Only the runtime requirement sets. Dev/bench extras are intentionally excluded:
# they are not expected to be present in every environment, so reporting them as
# drift would be noise that trains people to ignore this check.
_REQUIREMENTS_FILES = ["requirements.txt", "scripts/requirements.txt"]

# A requirement line whose comment names a vulnerability id is a SECURITY floor.
_SECURITY_ID = re.compile(r"\b(CVE-\d{4}-\d+|PYSEC-\d{4}-\d+|GHSA-[\w-]+)\b", re.I)


@dataclass
class Drift:
    package: str
    declared: str
    installed: str | None
    severity: str  # CRITICAL | HIGH | MEDIUM
    source_file: str
    security_ids: list[str] = field(default_factory=list)

    def describe(self) -> str:
        where = f"{self.source_file}"
        if self.installed is None:
            return f"{self.package}: declared {self.declared} in {where}, NOT INSTALLED"
        ids = f" [{', '.join(self.security_ids)}]" if self.security_ids else ""
        return (
            f"{self.package}: declared {self.declared} in {where}, installed {self.installed}{ids}"
        )


def _parse_requirement_line(line: str) -> tuple[str, str, list[str]] | None:
    """-> (name, specifier, security_ids) for a line worth checking, else None."""
    raw = line.rstrip("\n")
    body, _, comment = raw.partition("#")
    body = body.strip()
    if not body or body.startswith("-"):  # blank, comment-only, -r/-e/--flag
        return None
    if "://" in body:  # direct URL / VCS reference
        return None
    try:
        from packaging.requirements import Requirement

        req = Requirement(body)
    except Exception:
        return None
    if not str(req.specifier):
        return None  # unpinned: nothing to verify
    return req.name, str(req.specifier), _SECURITY_ID.findall(comment)


def _installed(name: str) -> str | None:
    try:
        return installed_version(name)
    except PackageNotFoundError:
        return None


def scan() -> list[Drift]:
    from packaging.specifiers import SpecifierSet
    from packaging.version import InvalidVersion, Version

    out: list[Drift] = []
    seen: set[str] = set()
    for rel in _REQUIREMENTS_FILES:
        path = _REPO_ROOT / rel
        if not path.is_file():
            continue
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            parsed = _parse_requirement_line(line)
            if parsed is None:
                continue
            name, spec, sec_ids = parsed
            key = name.lower()
            if key in seen:
                # First declaration wins. scripts/requirements.txt carries looser
                # floors for the same packages (torch>=2.0.0 vs torch>=2.13.0), and
                # reporting against the looser one would hide a real gap.
                continue
            seen.add(key)

            have = _installed(name)
            if have is None:
                out.append(Drift(name, spec, None, "MEDIUM", rel, sec_ids))
                continue
            try:
                ok = Version(have) in SpecifierSet(spec, prereleases=True)
            except InvalidVersion:
                continue
            if not ok:
                # A security floor that is not applied is the failure this module
                # exists for -- it reads as fixed and is not.
                sev = "CRITICAL" if sec_ids else "HIGH"
                out.append(Drift(name, spec, have, sev, rel, sec_ids))
    return out


def to_dict(drifts: list[Drift]) -> dict:
    import datetime

    counts = {s: sum(1 for d in drifts if d.severity == s) for s in ("CRITICAL", "HIGH", "MEDIUM")}
    return {
        "checker": "verify_installed",
        "timestamp": datetime.datetime.now(datetime.UTC).isoformat(),
        "files_checked": _REQUIREMENTS_FILES,
        "critical_count": counts["CRITICAL"],
        "high_count": counts["HIGH"],
        "missing_count": counts["MEDIUM"],
        "blocked": counts["CRITICAL"] > 0,
        "drifts": [
            {
                "package": d.package,
                "declared": d.declared,
                "installed": d.installed,
                "severity": d.severity,
                "source": d.source_file,
                "security_ids": d.security_ids,
            }
            for d in drifts
        ],
    }


def run(write: bool = True) -> dict:
    payload = to_dict(scan())
    if write:
        _OUTPUT.parent.mkdir(parents=True, exist_ok=True)
        _OUTPUT.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return payload


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--json", action="store_true")
    ap.add_argument(
        "--strict",
        action="store_true",
        help="exit 1 when a declared SECURITY floor is not installed",
    )
    ap.add_argument("--no-write", action="store_true")
    args = ap.parse_args()

    payload = run(write=not args.no_write)
    if args.json:
        print(json.dumps(payload, indent=2))
    else:
        print(f"Declared vs installed — {len(payload['drifts'])} drift(s)")
        print(f"  CRITICAL (unapplied security floor): {payload['critical_count']}")
        print(f"  HIGH     (below declared floor):     {payload['high_count']}")
        print(f"  MEDIUM   (declared, not installed):  {payload['missing_count']}")
        for d in payload["drifts"]:
            ids = f" [{', '.join(d['security_ids'])}]" if d["security_ids"] else ""
            got = d["installed"] or "NOT INSTALLED"
            print(
                f"    {d['severity']:8} {d['package']:22} declared {d['declared']:16} have {got}{ids}"
            )
    return 1 if (args.strict and payload["blocked"]) else 0


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    sys.exit(main())
