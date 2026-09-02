#!/usr/bin/env python3
"""
gitignore_audit.py -- is .gitignore hiding something that should be tracked?

WHY THIS EXISTS
---------------
A .gitignore mistake is uniquely expensive: an ignored file has no history, so at the
moment it matters that it was lost, there is nothing to restore. Two real instances on
2026-07-28/29 prompted this:

  * Router A/B results were written under `logs/`, which is ignored. The measurement was
    taken, reported, and then not preserved -- most of the way back to an unmeasured
    claim.
  * `*.jsonl` is load-bearing (pb_verdict_corpus.jsonl is 9.06 GB and GitHub rejects any
    file over 100 MB) but it is a blanket extension ban, so it also swallowed small
    authoritative files like pb_negative_signal.jsonl (47 KB) that are irreplaceable
    precisely BECAUSE they are ignored.

So the useful question is not "what is ignored" -- tens of thousands of build artifacts
are, correctly -- but "what is ignored that is SMALL, looks authored, and has no copy
anywhere else".

TWO CHECKS
----------
1. SUSPICIOUS IGNORES, grouped BY THE PATTERN doing the ignoring. That grouping is the
   whole point: `logs/` matching 24,000 files is one decision somebody made deliberately,
   while an extension ban reaching into an otherwise-tracked directory is the accident.
   Ungrouped, this check emits 25,000 undifferentiated lines, which is the same as no
   check. Advisory only -- `--guard` does not fail on these.

2. OVERSIZED NEGATIONS. Every `!path` un-ignore is size-checked. This one CAN fail:
   a negated file that grows past the ceiling turns a careful exception into a rejected
   push, or a repo carrying a blob it should not. `--guard` exits 1 on these.

Usage::

    python scripts/dev/gitignore_audit.py
    python scripts/dev/gitignore_audit.py --json out.json
    python scripts/dev/gitignore_audit.py --guard      # exit 1 on an oversized negation
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent.parent

# GitHub hard-rejects >100 MB. This ceiling is deliberately far lower: anything
# approaching it does not belong in a source repo even where git would accept it.
NEGATION_SIZE_CEILING = 5 * 1024 * 1024

# At or under this size, ignoring a file is more likely an accident than a decision.
SUSPICIOUS_MAX_BYTES = 2 * 1024 * 1024

AUTHORED_SUFFIXES = frozenset(
    {
        ".py",
        ".rs",
        ".ts",
        ".tsx",
        ".mjs",
        ".sh",
        ".ps1",
        ".md",
        ".toml",
        ".yaml",
        ".yml",
        ".json",
        ".jsonl",
        ".csv",
        ".tsv",
        ".txt",
    }
)

# Deliberately not the whole repo: scanning 10 GB is slow enough to discourage running
# the audit at all, which is worse than a narrower scan that actually gets run.
SCAN_ROOTS = (
    "scripts",
    "tests",
    "docs",
    "assurance",
    "locks",
    "corpus",
    "data",
    "bundler",
    "frontend/src",
    "frontend/src-tauri/src",
    "logs",
)

SKIP_PARTS = frozenset(
    {
        "node_modules",
        ".venv",
        "venv",
        "target",
        ".next",
        "out",
        "__pycache__",
        "site-packages",
        ".git",
        ".pytest_cache",
        "_pyinstaller_work",
        "dist",
        "build",
        "demo_workspaces",
        ".mypy_cache",
        ".ruff_cache",
        "repos",
        "locked",
    }
)


@dataclass
class Finding:
    path: str
    bytes: int
    pattern: str


@dataclass
class AuditResult:
    scanned: int = 0
    suspicious: list[Finding] = field(default_factory=list)
    oversized_negations: list[Finding] = field(default_factory=list)
    missing_negations: list[str] = field(default_factory=list)
    negations: list[str] = field(default_factory=list)

    def by_pattern(self) -> dict[str, list[Finding]]:
        out: dict[str, list[Finding]] = {}
        for f in self.suspicious:
            out.setdefault(f.pattern, []).append(f)
        return out

    def to_dict(self) -> dict:
        return {
            "scanned": self.scanned,
            "negations": self.negations,
            "missing_negations": self.missing_negations,
            "suspicious_count": len(self.suspicious),
            "oversized_negation_count": len(self.oversized_negations),
            "by_pattern": {
                pat: {
                    "files": len(items),
                    "bytes": sum(i.bytes for i in items),
                    "sample": [i.path for i in items[:5]],
                }
                for pat, items in sorted(self.by_pattern().items(), key=lambda kv: -len(kv[1]))
            },
            "oversized_negations": [f.__dict__ for f in self.oversized_negations],
            "blocked": bool(self.oversized_negations),
        }


def _negation_paths() -> list[str]:
    """Every `!path` line naming a concrete file (a glob cannot be size-checked)."""
    gi = _ROOT / ".gitignore"
    if not gi.is_file():
        return []
    out = []
    for line in gi.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line.startswith("!"):
            continue
        body = line[1:].strip()
        if not body or any(ch in body for ch in "*?["):
            continue
        out.append(body)
    return out


def _candidates() -> list[Path]:
    found: list[Path] = []
    for root in SCAN_ROOTS:
        base = _ROOT / root
        if not base.exists():
            continue
        for f in base.rglob("*"):
            if SKIP_PARTS & set(f.parts):
                continue
            try:
                if not f.is_file() or f.suffix.lower() not in AUTHORED_SUFFIXES:
                    continue
                if f.stat().st_size > SUSPICIOUS_MAX_BYTES:
                    continue
            except OSError:
                continue
            found.append(f)
    return found


def _ignored_with_pattern(paths: list[Path]) -> dict[str, str]:
    """path -> the .gitignore pattern that ignores it, via `check-ignore -v`."""
    out: dict[str, str] = {}
    rels = [str(p.relative_to(_ROOT)).replace("\\", "/") for p in paths]
    for i in range(0, len(rels), 300):
        chunk = "\n".join(rels[i : i + 300])
        try:
            r = subprocess.run(
                ["git", "check-ignore", "-v", "--stdin"],
                cwd=str(_ROOT),
                input=chunk.encode("utf-8"),
                capture_output=True,
                timeout=180,
            )
        except (OSError, subprocess.TimeoutExpired):
            continue
        for line in r.stdout.decode("utf-8", "replace").splitlines():
            if "\t" not in line:
                continue
            meta, path = line.rsplit("\t", 1)
            bits = meta.split(":")
            pattern = (bits[-1] if bits else "?").strip()
            # A NEGATION match means the file is explicitly NOT ignored. `-v` prints it
            # like any other match, and counting it as ignored inverted the report: right
            # after un-ignoring 1,094 vendored fixtures, the audit listed those same
            # 1,094 files as its top suspicious group. A tool that flags its own fix is
            # worse than no tool.
            if pattern.startswith("!"):
                continue
            out[path.strip().replace("\\", "/")] = pattern
    return out


def audit(negations_only: bool = False) -> AuditResult:
    res = AuditResult()

    # Cheap, and the only check that can fail -- do it first.
    for rel in _negation_paths():
        res.negations.append(rel)
        p = _ROOT / rel
        if not p.is_file():
            res.missing_negations.append(rel)
            continue
        sz = p.stat().st_size
        if sz > NEGATION_SIZE_CEILING:
            res.oversized_negations.append(Finding(rel, sz, "!negation over ceiling"))

    if negations_only:
        # --guard only fails on an oversized negation, and that check is O(negations).
        # Running the 57k-file candidate scan first made the gate take ~10 minutes and
        # time out, which is the same as not having a gate.
        return res

    cands = _candidates()
    res.scanned = len(cands)
    ignored = _ignored_with_pattern(cands)
    for p in cands:
        rel = str(p.relative_to(_ROOT)).replace("\\", "/")
        pat = ignored.get(rel)
        if pat:
            res.suspicious.append(Finding(rel, p.stat().st_size, pat))
    res.suspicious.sort(key=lambda f: -f.bytes)
    return res


def _is_dir_scope(pattern: str) -> bool:
    """A directory-scoped pattern is a deliberate 'this whole tree is output' call.
    An extension pattern reaching into a tracked tree is the thing worth reading."""
    return pattern.endswith("/") or ("/" in pattern and "*" not in pattern)


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--json", type=Path)
    ap.add_argument(
        "--guard",
        action="store_true",
        help="exit 1 if a negated (un-ignored) file exceeds the size ceiling. "
        "Fast: skips the advisory scan unless --json is also given.",
    )
    ap.add_argument("--samples", type=int, default=3)
    args = ap.parse_args()

    res = audit(negations_only=args.guard and not args.json)
    print(f"gitignore audit -- scanned {res.scanned} small authored files")
    print(f"  explicit negations   : {len(res.negations)}")
    print(f"  oversized negations  : {len(res.oversized_negations)}   <-- --guard fails on these")
    print(f"  suspicious ignores   : {len(res.suspicious)}   (advisory)")

    for f in res.oversized_negations:
        print(f"    OVERSIZED  {f.bytes:>12,}  {f.path}")
    for rel in res.missing_negations:
        print(f"    MISSING    negated in .gitignore but not on disk: {rel}")

    groups = res.by_pattern()
    ext = {p: i for p, i in groups.items() if not _is_dir_scope(p)}
    dirs = {p: i for p, i in groups.items() if _is_dir_scope(p)}

    if ext:
        print("\n  EXTENSION/GLOB patterns reaching into tracked trees -- read these:")
        for pat, items in sorted(ext.items(), key=lambda kv: -len(kv[1])):
            tops = sorted({i.path.split("/")[0] for i in items})
            print(f"    {pat:<26} {len(items):>6} file(s)  under: {', '.join(tops[:5])}")
            for i in items[: args.samples]:
                print(f"        {i.bytes:>10,}  {i.path}")
    if dirs:
        print("\n  directory-scoped patterns (deliberate 'this tree is output'):")
        for pat, items in sorted(dirs.items(), key=lambda kv: -len(kv[1])):
            print(f"    {pat:<26} {len(items):>6} file(s)")

    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(json.dumps(res.to_dict(), indent=2), encoding="utf-8")
        print(f"\nwrote {args.json}")
    return 1 if (args.guard and res.oversized_negations) else 0


if __name__ == "__main__":
    sys.exit(main())
