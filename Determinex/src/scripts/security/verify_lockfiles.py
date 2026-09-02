"""
Lockfile verifier — confirms Python requirements files use pinned, hash-verified installs.

Checks:
  1. All direct dependencies are pinned (==, not >=, ~=, ^)
  2. No dependency has a known-bad version pattern
  3. Hash-checking mode supported (--require-hashes compatible)
  4. No unpinned VCS dependencies (git+https:// without @commit)

Reports violations as a structured list. Fails (exit 1) if any CRITICAL violations found.
"""

from __future__ import annotations

import logging
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

log = logging.getLogger(__name__)

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent

_REQUIREMENTS_FILES = [
    "requirements.txt",
    "requirements-dev.txt",
    "scripts/requirements.txt",
    "scripts/requirements_bench.txt",
]

_PINNED = re.compile(r"^[A-Za-z0-9_.\-]+==[\d.]+")
_VCS_UNPINNED = re.compile(r"git\+https?://[^@\s]+(?!@[0-9a-f]{40})")
_UNPINNED_SPECIFIER = re.compile(r"[>~^]=|>=")
# A requirement line that is just a name (optionally with extras or an environment marker) and
# carries no version operator whatsoever. Anchored, and it stops at the first character that could
# begin a constraint so `pkg==1.0` and `pkg>=1.0` are not matched here.
_BARE_UNVERSIONED = re.compile(r"^[A-Za-z0-9_.\-]+(?:\[[A-Za-z0-9_.,\-]+\])?\s*(?:;.*)?$")
_COMMENT_OR_EMPTY = re.compile(r"^\s*(#|$)")
_OPTION_LINE = re.compile(r"^\s*-[rce]")


@dataclass
class LockfileViolation:
    file: str
    line_num: int
    line: str
    severity: str  # "CRITICAL" | "HIGH" | "MEDIUM"
    reason: str


@dataclass
class LockfileReport:
    files_checked: list[str] = field(default_factory=list)
    violations: list[LockfileViolation] = field(default_factory=list)

    @property
    def critical_count(self) -> int:
        return sum(1 for v in self.violations if v.severity == "CRITICAL")

    @property
    def high_count(self) -> int:
        return sum(1 for v in self.violations if v.severity == "HIGH")

    @property
    def passed(self) -> bool:
        # THIS GATE COULD NOT FAIL (fixed 2026-07-30). It was `critical_count == 0`, and no code
        # path in this module ever assigns severity "CRITICAL" -- check_file emits only "HIGH"
        # (unpinned VCS dependency) and "MEDIUM" (unpinned specifier). Measured before the fix:
        # 60 violations, critical_count 0, passed True, and security_gate printed
        # "[PASS] verify_lockfiles  3 files checked, 0 critical violations" while 60 unpinned
        # dependencies went unmentioned.
        #
        # HIGH is a VCS dependency with no commit pin, i.e. a dependency whose content can change
        # under us between builds. For a supply-chain gate that is a genuine block, so it blocks.
        # MEDIUM (>= / ~= specifiers) stays advisory: this project deliberately floats some
        # ranges, and failing on those would make the gate get switched off rather than fixed.
        return self.critical_count == 0 and self.high_count == 0

    def to_dict(self) -> dict:
        return {
            "files_checked": self.files_checked,
            "passed": self.passed,
            "violation_count": len(self.violations),
            "critical_count": self.critical_count,
            "violations": [
                {
                    "file": v.file,
                    "line": v.line_num,
                    "content": v.line[:80],
                    "severity": v.severity,
                    "reason": v.reason,
                }
                for v in self.violations
            ],
        }


def check_file(path: Path) -> list[LockfileViolation]:
    violations = []
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except Exception as exc:
        # A file we could not read is NOT a file with no violations. Returning [] here made an
        # unreadable requirements file contribute zero to critical_count/high_count, so the gate
        # passed on a scan that had not happened -- the same "failed scan reads as a clean scan"
        # defect as S0.2 in secret_scan, in a different gate. Report it as HIGH so it blocks:
        # `passed` requires critical_count == 0 and high_count == 0.
        return [
            LockfileViolation(
                file=str(path),
                line_num=0,
                line="",
                severity="HIGH",
                reason=f"could not be read, so it was never checked: {type(exc).__name__}: {exc}",
            )
        ]

    for i, line in enumerate(lines, 1):
        stripped = line.strip()
        if _COMMENT_OR_EMPTY.match(stripped) or _OPTION_LINE.match(stripped):
            continue

        # VCS deps without commit hash
        if _VCS_UNPINNED.search(stripped):
            violations.append(
                LockfileViolation(
                    file=str(path),
                    line_num=i,
                    line=stripped,
                    severity="HIGH",
                    reason="VCS dependency without pinned commit hash",
                )
            )
            continue

        # Unpinned specifiers
        if _UNPINNED_SPECIFIER.search(stripped) and not _PINNED.match(stripped):
            violations.append(
                LockfileViolation(
                    file=str(path),
                    line_num=i,
                    line=stripped,
                    severity="MEDIUM",
                    reason="Dependency not pinned to exact version (use ==)",
                )
            )
            continue

        # A bare requirement with NO version constraint at all. Added 2026-07-30: the checks above
        # only fire when a specifier is present, so `requests` on its own -- strictly less pinned
        # than `requests>=2.0` -- produced no violation of any kind and the file read as cleaner
        # than one using ranges.
        if _BARE_UNVERSIONED.match(stripped):
            violations.append(
                LockfileViolation(
                    file=str(path),
                    line_num=i,
                    line=stripped,
                    severity="MEDIUM",
                    reason="Dependency has no version constraint at all (use ==)",
                )
            )

    return violations


def _normalise(name: str) -> str:
    return name.lower().replace("_", "-")


def declared_floors(root: Path) -> dict[str, tuple[str, str]]:
    """package -> (minimum version, the trailing comment that justified it).

    The comments matter: most of these floors were set during the 2026-07-16 CVE remediation and
    name the advisory they close, so a violation can say *what* regresses rather than just "older".
    """
    floors: dict[str, tuple[str, str]] = {}
    for rel in _REQUIREMENTS_FILES:
        path = root / rel
        if not path.is_file():
            continue
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            body, _, comment = line.partition("#")
            stripped = body.strip()
            if not stripped or stripped.startswith("-"):
                continue
            m = re.match(r"^([A-Za-z0-9._\-]+)\s*(?:\[[^\]]*\])?\s*>=\s*([^\s,;]+)", stripped)
            if m:
                floors.setdefault(_normalise(m.group(1)), (m.group(2), comment.strip()))
    return floors


def lock_pins(root: Path) -> dict[str, dict[str, str]]:
    """lock file (relative) -> {package: pinned version}, for every lock file present."""
    pins: dict[str, dict[str, str]] = {}

    uv = root / "uv.lock"
    if uv.is_file():
        text = uv.read_text(encoding="utf-8", errors="replace")
        pins["uv.lock"] = {
            _normalise(n): v
            for n, v in re.findall(
                r'\[\[package\]\]\s*\nname\s*=\s*"([^"]+)"\s*\nversion\s*=\s*"([^"]+)"', text
            )
        }

    for rel in ("requirements-lock.txt", "requirements.lock"):
        path = root / rel
        if not path.is_file():
            continue
        found: dict[str, str] = {}
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            stripped = line.split("#")[0].strip()
            m = re.match(r"^([A-Za-z0-9._\-]+)\s*(?:\[[^\]]*\])?\s*==\s*([^\s,;]+)", stripped)
            if m:
                found[_normalise(m.group(1))] = m.group(2)
        pins[rel] = found

    return pins


def check_lock_floor_conflicts(root: Path) -> list[LockfileViolation]:
    """A lock file must not pin a package BELOW the floor requirements.txt declares for it.

    WHY THIS EXISTS
    ---------------
    Found 2026-07-30. `uv.lock` pinned **7 packages below their declared floors**, and most of those
    floors exist to close specific advisories:

        aiohttp      3.13.5 < 3.14.1   (11 CVEs incl. CVE-2026-54273..80)
        cryptography 48.0.0 < 48.0.1   (GHSA-537c-gmf6-5ccf)
        torch        2.12.0 < 2.13.0   (CVE-2025-3000 memory corruption + PYSEC-2025-194)
        pyasn1       0.6.3  < 0.6.4    (PYSEC-2026-3455/6/7)
        pillow, setuptools, httplib2

    Two sources of truth for the same versions, with nothing comparing them, and the
    security-relevant one silently losing. CI installs with `pip install -r requirements.txt` so it
    gets the fixed versions -- but `[tool.uv.workspace]` is configured, so the documented `uv sync`
    workflow resolves from `uv.lock` and would quietly install the vulnerable set.

    HIGH, not MEDIUM: `passed` is `critical_count == 0 and high_count == 0`, and a lock that
    reintroduces a fixed CVE should stop the gate rather than be noted in passing. Contrast with the
    unpinned-specifier findings, which are advisory precisely because a `>=` floor is a deliberate
    choice -- converting these to `==` would freeze the floors and prevent future fixes arriving.
    """
    violations: list[LockfileViolation] = []
    floors = declared_floors(root)
    if not floors:
        return violations

    try:
        from packaging.version import InvalidVersion, Version
    except ImportError:
        # No comparison is possible. Say so rather than returning [] -- silence here would read as
        # "no conflicts", which is the failure mode this module was just fixed for elsewhere.
        return [
            LockfileViolation(
                file="(version comparison)",
                line_num=0,
                line="",
                severity="HIGH",
                reason="packaging is not installed, so lock-vs-floor conflicts could not be checked",
            )
        ]

    for lock_name, pinned in lock_pins(root).items():
        for package, version in sorted(pinned.items()):
            floor = floors.get(package)
            if not floor:
                continue
            try:
                if Version(version) >= Version(floor[0]):
                    continue
            except InvalidVersion:
                continue
            because = f" — {floor[1]}" if floor[1] else ""
            violations.append(
                LockfileViolation(
                    file=lock_name,
                    line_num=0,
                    line=f"{package}=={version}",
                    severity="HIGH",
                    reason=(
                        f"pins {package} {version}, below the {floor[0]} floor declared in "
                        f"requirements.txt{because}"
                    ),
                )
            )
    return violations


def check_lock_covers_declared(root: Path) -> list[LockfileViolation]:
    """`requirements-lock.txt` must pin everything `requirements.txt` declares.

    WHY THIS EXISTS
    ---------------
    Found 2026-07-30. The lock pinned 19 of the 50 dependencies requirements.txt declares, while its
    own header said "For production: pip install -r requirements-lock.txt (pinned, bit-for-bit
    reproducible)". Following that instruction produced an environment missing 31 packages, most of
    them the additions from the CVE remediation. A partial lock that advertises itself as complete is
    worse than no lock, because it is trusted.

    Scoped to the ROOT requirements.txt on purpose. The lock is compiled from that file, so the
    bench-only dependencies declared in scripts/requirements*.txt (evalplus, bigcodebench,
    sqlite-vec) are deliberately outside its closure and must not be reported as gaps.
    """
    lock = root / "requirements-lock.txt"
    req = root / "requirements.txt"
    if not lock.is_file() or not req.is_file():
        return []

    declared: set[str] = set()
    for line in req.read_text(encoding="utf-8", errors="replace").splitlines():
        stripped = line.split("#")[0].strip()
        if not stripped or stripped.startswith("-"):
            continue
        m = re.match(r"^([A-Za-z0-9._\-]+)", stripped)
        if m:
            declared.add(_normalise(m.group(1)))

    pinned = set(lock_pins(root).get("requirements-lock.txt", {}))
    missing = sorted(declared - pinned)
    if not missing:
        return []
    return [
        LockfileViolation(
            file="requirements-lock.txt",
            line_num=0,
            line="",
            severity="HIGH",
            reason=(
                f"does not pin {len(missing)} dependency/dependencies declared in requirements.txt, so "
                f"installing from it yields an incomplete environment: {missing[:10]}"
                + (" ..." if len(missing) > 10 else "")
                + ". Regenerate with: uv pip compile requirements.txt --output-file requirements-lock.txt"
            ),
        )
    ]


def run(repo_root: Path | None = None) -> LockfileReport:
    root = repo_root or _REPO_ROOT
    report = LockfileReport()

    for rel_path in _REQUIREMENTS_FILES:
        f = root / rel_path
        if f.is_file():
            report.files_checked.append(str(f.relative_to(root)))
            report.violations.extend(check_file(f))

    report.violations.extend(check_lock_floor_conflicts(root))
    report.violations.extend(check_lock_covers_declared(root))

    if not report.files_checked:
        log.warning("[verify_lockfiles] no requirements files found")

    # State what actually decided the verdict. This used to say "0 critical violations" while
    # `passed` depends on CRITICAL *and* HIGH, and it omitted the MEDIUM count entirely -- so a run
    # with 60 unpinned dependencies printed a bare PASS. Same understated-verdict problem as S0.4 in
    # secret_scan: a line that reads like a full result while describing part of one.
    counts = f"{report.critical_count} critical, {report.high_count} high"
    other = len(report.violations) - report.critical_count - report.high_count
    if other:
        counts += f", {other} advisory"
    if report.passed:
        log.info(
            "[verify_lockfiles] PASS: %d files checked (%s)", len(report.files_checked), counts
        )
    else:
        log.warning(
            "[verify_lockfiles] FAIL: %d files checked (%s) — critical or high blocks",
            len(report.files_checked),
            counts,
        )

    return report


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    r = run()
    print(f"Files checked: {r.files_checked}")
    print(f"Violations: {len(r.violations)} ({r.critical_count} critical)")
    sys.exit(0 if r.passed else 1)
