#!/usr/bin/env python3
"""
pb_parity_claim_guard.py — CI guard: ProgramBench parity framing compliance.

Scans tracked docs for:
1. BANNED framings (single blended lock count, dismissive language about skipped tests)
2. REQUIRED multi-line format for any combined count claim
3. Correct parity/ceiling separation from strict count

Exit 1 if violations found. Safe to run as pre-commit or CI gate.

Usage:
  python scripts/pb_parity_claim_guard.py           # scan all docs
  python scripts/pb_parity_claim_guard.py --verbose  # show matched lines
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

SCAN_PATHS = [
    REPO_ROOT / "README.md",
    REPO_ROOT / "CHANGELOG.md",
    REPO_ROOT / "CLAUDE.md",
    REPO_ROOT / "docs" / "papers" / "WHITE_PAPER.md",
    REPO_ROOT / "docs" / "papers" / "PROGRAMBENCH.md",
    REPO_ROOT / "docs" / "programs" / "programbench" / "NEAR_LOCK_REGISTRY.md",
]

SCAN_DIRS = [
    REPO_ROOT / "docs" / "papers",
    REPO_ROOT / "docs" / "programs" / "programbench",
]

SKIP_PATHS = {
    REPO_ROOT / "docs" / "handoffs",
    REPO_ROOT / "docs" / "audits",
    REPO_ROOT / "corpus",
    REPO_ROOT / "scripts",
    REPO_ROOT / "logs",
}

# Banned framings — these dismiss the legitimacy of upstream-disabled tests
BANNED_PATTERNS = [
    (
        re.compile(r"\brings?\b", re.IGNORECASE),
        "banned: 'ringers' — dismisses valid upstream-disabled tests",
    ),
    (
        re.compile(r"\bred\s+herring", re.IGNORECASE),
        "banned: 'red herring' — dismisses valid upstream-disabled tests",
    ),
    (
        re.compile(r"\bunfair\s+test", re.IGNORECASE),
        "banned: 'unfair tests' — dismisses valid upstream-disabled tests",
    ),
    (
        re.compile(r"\b(\d+)\s*/\s*200\s*=\s*[\d.]+\s*%\s+(?:strict\s+)?locks?\b", re.IGNORECASE),
        "banned: single blended count must be multi-line format (strict / parity / ceiling)",
    ),
]

# Single-blended-count pattern: "N locks" or "N full-suite" where N >= 63 (strict+parity combined)
# Only flags explicit "locks" language without strict qualifier — prevents "63/200 locks" misleading claim
BLENDED_LOCK_PATTERN = re.compile(
    r"\b6[3-9]\s*/\s*200\b.{0,50}\blocks?\b",
    re.IGNORECASE,
)

HISTORICAL_MARKERS = [
    "historical",
    "pre-audit",
    "old metric",
    "subset metric",
    "2026-05-",
    "2026-04-",
]


def is_historical(line: str) -> bool:
    ll = line.lower()
    return any(m in ll for m in HISTORICAL_MARKERS)


def collect_files() -> list[Path]:
    files: set[Path] = set()
    for f in SCAN_PATHS:
        if f.exists():
            files.add(f)
    for d in SCAN_DIRS:
        if d.is_dir():
            for f in d.rglob("*.md"):
                skip = False
                for sp in SKIP_PATHS:
                    try:
                        f.relative_to(sp)
                        skip = True
                        break
                    except ValueError:
                        pass
                if not skip:
                    files.add(f)
    return sorted(files)


def check_file(path: Path, verbose: bool) -> list[str]:
    violations: list[str] = []
    try:
        text = path.read_text(encoding="utf-8")
    except Exception:
        return violations

    in_code = False
    for i, line in enumerate(text.splitlines(), 1):
        if line.strip().startswith("```"):
            in_code = not in_code
        if in_code or is_historical(line):
            continue

        for pat, desc in BANNED_PATTERNS:
            if pat.search(line):
                rel = path.relative_to(REPO_ROOT)
                violations.append(f"BANNED {rel}:{i}  {desc}")
                if verbose:
                    violations.append(f"  {line.strip()}")

        # Blended count check: "63+/200 locks" without strict qualifier
        m = BLENDED_LOCK_PATTERN.search(line)
        if m:
            context = line.lower()
            if "strict" not in context and "parity" not in context and "functional" not in context:
                rel = path.relative_to(REPO_ROOT)
                violations.append(
                    f"BLENDED-COUNT {rel}:{i}  {m.group(0)!r} — "
                    f"use multi-line: 'N/200 strict / +M reference-parity'"
                )
                if verbose:
                    violations.append(f"  {line.strip()}")

    return violations


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--verbose", "-v", action="store_true")
    args = parser.parse_args()

    files = collect_files()
    print(f"pb_parity_claim_guard: scanning {len(files)} files...")

    all_violations: list[str] = []
    for f in files:
        all_violations.extend(check_file(f, args.verbose))

    if all_violations:
        print(f"\nFAIL: {len(all_violations)} parity framing violation(s):")
        for v in all_violations:
            print(f"  {v}")
        return 1

    print("OK: no parity framing violations found.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
