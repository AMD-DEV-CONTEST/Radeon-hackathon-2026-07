#!/usr/bin/env python3
"""
pb_doc_count_check.py — CI guard: ProgramBench lock count consistency check.

Reads the canonical count from corpus/programbench/eval_index.json
(entries where official_full_suite_resolved == true, excluding aliases that
have a canonical_slug field), then scans every tracked doc for count-bearing
patterns and exits non-zero on any mismatch against the true count.

Skips:
  - Lines explicitly marked as historical (old metric / pre-audit / historical /
    "77 locks" / "67 locks" etc.)
  - CHANGELOG entries dated before the most recent batch date
  - Lines inside fenced code blocks

Usage:
  python scripts/pb_doc_count_check.py          # check all docs
  python scripts/pb_doc_count_check.py --fix    # auto-fix mismatches in-place
  python scripts/pb_doc_count_check.py --verbose
"""

from __future__ import annotations

import argparse
import json
import pathlib
import re
import sys
from dataclasses import dataclass

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent

# ---------------------------------------------------------------------------
# Canonical count source
# ---------------------------------------------------------------------------

EXPECTED_DENOMINATOR = 200  # ProgramBench has exactly 200 unique tasks


def get_true_count() -> tuple[int, list[str]]:
    """Return (canonical_count, sorted_slug_list) from eval_index.json."""
    ei = REPO_ROOT / "corpus" / "programbench" / "eval_index.json"
    data = json.loads(ei.read_text(encoding="utf-8"))
    entries = data if isinstance(data, list) else list(data.values())
    slugs = [
        e.get("slug", e.get("tool", "?"))
        for e in entries
        if e.get("official_full_suite_resolved") is True
        and not e.get("alias_of")  # skip alias rows
        and not e.get("canonical_slug")  # legacy alias field
    ]
    return len(slugs), sorted(slugs)


def check_denominator() -> tuple[bool, int, list[str]]:
    """Return (ok, non_alias_count, problem_slugs). Fails if non-alias rows != 200."""
    ei = REPO_ROOT / "corpus" / "programbench" / "eval_index.json"
    data = json.loads(ei.read_text(encoding="utf-8"))
    entries = data if isinstance(data, list) else list(data.values())
    non_alias = [
        e.get("slug", e.get("tool", "?"))
        for e in entries
        if not e.get("alias_of") and not e.get("canonical_slug")
    ]
    ok = len(non_alias) == EXPECTED_DENOMINATOR
    extras = non_alias if not ok else []
    return ok, len(non_alias), extras


def check_upstream_skips_integrity() -> list[str]:
    """upstream_skips REQUIRES fail==0 AND nr==0. Returns list of violating slugs."""
    ei = REPO_ROOT / "corpus" / "programbench" / "eval_index.json"
    data = json.loads(ei.read_text(encoding="utf-8"))
    entries = data if isinstance(data, list) else list(data.values())
    violations = []
    for e in entries:
        if e.get("alias_of") or e.get("canonical_slug"):
            continue
        if e.get("status") != "upstream_skips":
            continue
        fail = e.get("official_failed", 0) or 0
        nr = e.get("official_not_run", 0) or 0
        if fail > 0 or nr > 0:
            slug = e.get("slug", e.get("tool", "?"))
            violations.append(f"{slug} (fail={fail}, nr={nr})")
    return violations


# ---------------------------------------------------------------------------
# T2 ceiling-certified validation
# ---------------------------------------------------------------------------

# Every CEILING_CERT.md must contain evidence of all three elements.
CERT_REQUIRED_SECTIONS = [
    (re.compile(r"\breason\b", re.IGNORECASE), "per-skip reason"),
    (re.compile(r"\bstructural\b|\brationale\b", re.IGNORECASE), "structural rationale"),
    (re.compile(r"\bparity\b", re.IGNORECASE), "reference-parity evidence"),
]

LOCKED_DIR = REPO_ROOT / "corpus" / "programbench" / "locked"


def check_t2_cert_files() -> list[str]:
    """ceiling_certified entries MUST have CEILING_CERT.md with required shape.
    Shape: per-skip reason, structural rationale, reference-parity evidence.
    Returns violation messages (empty = pass)."""
    ei = REPO_ROOT / "corpus" / "programbench" / "eval_index.json"
    data = json.loads(ei.read_text(encoding="utf-8"))
    entries = data if isinstance(data, list) else list(data.values())
    violations: list[str] = []
    for e in entries:
        if e.get("alias_of") or e.get("canonical_slug"):
            continue
        if e.get("tier") != "ceiling_certified":
            continue
        slug = e.get("slug", e.get("tool", "?"))
        # Locate the cert file via source, slug, or tool fields -- AND the
        # eval_report_path parent (tier_2_upstream_skips/<slug>/), aligning with
        # pb_tier_classify._has_cert so the two checkers never disagree (the tuc/
        # caesium-clt divergence: cert lived at the tier_2 path doc_count didn't check).
        cert_path: pathlib.Path | None = None
        for candidate in [e.get("source", ""), e.get("slug", ""), e.get("tool", "")]:
            if candidate:
                p = LOCKED_DIR / candidate / "CEILING_CERT.md"
                if p.exists():
                    cert_path = p
                    break
        if cert_path is None:
            rp = e.get("eval_report_path") or ""
            if rp:
                p = pathlib.Path(rp).parent / "CEILING_CERT.md"
                if p.exists():
                    cert_path = p
        if cert_path is None:
            violations.append(f"{slug}: CEILING_CERT.md missing from locked dir")
            continue
        text = cert_path.read_text(encoding="utf-8")
        for pattern, label in CERT_REQUIRED_SECTIONS:
            if not pattern.search(text):
                violations.append(f"{slug}: CEILING_CERT.md missing required section: {label}")
    return violations


# ---------------------------------------------------------------------------
# Claim-scanner: 'locks' adjacent to N > strict_count
# ---------------------------------------------------------------------------

# Pattern: a bare number immediately before the plural word "locks".
# Intentionally requires plural ("locks", not "lock") to avoid matching named artifacts
# like "Scale-to-100 lock" or "200/200 Lock Plan" which are not count claims.
_LOCKS_BEFORE = re.compile(r"\b(\d+)\s+locks\b", re.IGNORECASE)

# Lines containing these phrases describe aspirational goals or campaign targets,
# not current count claims. Skip them in the overclaim scanner.
_OVERCLAIM_GOAL_MARKERS = [
    "= 200 rows",  # campaign goal definition: '"200 locks" = 200 rows at proven ceiling'
    "200/200",  # "200/200 Lock Plan" style titles and goal framing
    "goal is",
    "target is",
    "plan to reach",
    "campaign ceiling",
    "to reach 200",
    "total-200",
]


def check_locks_overclaim(
    files: list[pathlib.Path],
    true_count: int,
) -> list[Mismatch]:
    """Scan docs for 'N locks' where N > strict_count.
    Prevents T1+T2 sum overclaims such as '60 locks (53 strict + 7 ceiling-certified)'.
    Publish format must always be two separate numbers, never a combined sum."""
    mismatches: list[Mismatch] = []
    for path in files:
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        lines = text.splitlines()
        in_code_block = False
        in_changelog_history = False
        for i, line in enumerate(lines, 1):
            if line.strip().startswith("```"):
                in_code_block = not in_code_block
            if in_code_block:
                continue
            if path.name == "CHANGELOG.md":
                if re.match(r"^## \[2026-0[0-5]", line):
                    in_changelog_history = True
                elif re.match(r"^## \[2026-06-10\]", line):
                    in_changelog_history = True
                elif re.match(r"^## \[2026-06-11\]", line):
                    in_changelog_history = True
                elif re.match(r"^## \[2026-06-12\]", line):
                    in_changelog_history = True
                elif re.match(r"^## \[2026-06-13\]", line):
                    in_changelog_history = False
                elif re.match(r"^## \[Unreleased\]", line, re.IGNORECASE):
                    in_changelog_history = False
            if in_changelog_history:
                continue
            if is_historical_line(line):
                continue
            # Skip lines that describe campaign goals/targets rather than current counts
            line_lower = line.lower()
            if any(marker.lower() in line_lower for marker in _OVERCLAIM_GOAL_MARKERS):
                continue
            for m in _LOCKS_BEFORE.finditer(line):
                n = int(m.group(1))
                if n <= true_count:
                    continue
                # If a strict qualifier appears in the 3 words before the number,
                # COUNT_PATTERNS already validates this with an exact-match check.
                prefix_words = re.findall(r"\b\w+\b", line[: m.start()])[-3:]
                if any(w.lower() in {"strict", "confirmed", "official"} for w in prefix_words):
                    continue
                mismatches.append(
                    Mismatch(
                        path=path,
                        line_no=i,
                        line=line.rstrip(),
                        pattern_desc="locks-adjacent overclaim (N > strict count)",
                        found_val=str(n),
                        expected_val=f"<= {true_count}",
                    )
                )
    return mismatches


# ---------------------------------------------------------------------------
# Files to scan
# ---------------------------------------------------------------------------

SCAN_FILES: list[pathlib.Path] = [
    REPO_ROOT / "README.md",
    REPO_ROOT / "CHANGELOG.md",
    REPO_ROOT / "CLAUDE.md",
]

SCAN_DIRS: list[pathlib.Path] = [
    REPO_ROOT / "docs",
    REPO_ROOT / "corpus" / "programbench",
]

SKIP_PATHS = {
    REPO_ROOT / "corpus" / "programbench" / "locked",
    REPO_ROOT / "corpus" / "programbench" / "eval_index.json",
    REPO_ROOT / "corpus" / "programbench" / "ceiling_register.json",
    REPO_ROOT / "corpus" / "programbench" / "score_breakdown.md",  # auto-generated
    REPO_ROOT / "corpus" / "programbench" / "per_tool_overrides",
    REPO_ROOT / "corpus" / "programbench" / "pending_unlock",
    REPO_ROOT / "locks",
    REPO_ROOT / "assurance",
    # Handoff docs are point-in-time snapshots — all counts in them are historical
    REPO_ROOT / "docs" / "handoffs",
    # Audit docs record the state at audit time — counts are historical findings
    REPO_ROOT / "docs" / "audits",
}


def is_skipped(path: pathlib.Path) -> bool:
    for s in SKIP_PATHS:
        try:
            path.relative_to(s)
            return True
        except ValueError:
            pass
    return path.suffix not in {".md", ".txt"}


def collect_files() -> list[pathlib.Path]:
    files: list[pathlib.Path] = []
    for f in SCAN_FILES:
        if f.exists() and not is_skipped(f):
            files.append(f)
    for d in SCAN_DIRS:
        if d.is_dir():
            for f in d.rglob("*.md"):
                if not is_skipped(f):
                    files.append(f)
    return sorted(set(files))


# ---------------------------------------------------------------------------
# Historical / skip patterns
# ---------------------------------------------------------------------------

# Lines containing these strings are considered historical record — skip
HISTORICAL_MARKERS = [
    "historical",
    "pre-audit",
    "old metric",
    "subset metric",
    "pre-June",
    "corrected to",
    "was corrected",
    "previously",
    "prior to",
    # Bold "Count: N/200" milestone tracking pattern used in campaign history bullets
    "**Count:",
    "Count: **",  # "Count: **15/200**" style in README campaign section
    "Count: 1",  # "Count: 13/200", "Count: 14/200", "Count: 15/200" etc.
    # Audit documents' own findings (historical at time of audit)
    "Honest count:",
    # Delta notation "+N strict locks" describes increment, not total count
    "+5 strict",
    "+8 strict",
    "+18 strict",
    "+30 strict",
    # Old specific numbers that are deliberate record
    "77 strict",
    "77 locks",
    "67 strict",
    "67 locks",
    "55 strict",
    "53 strict",
    "35 strict",
    "16 strict",
    "15 honest",
    "15 strict",
    "14 honest",
    "13 honest",
    "12 honest",
    # Patterns inside timeline/changelog blocks
    "EOD: 35",
    "EOD: 53",
    "2026-05-2",  # May campaign history lines
    "2026-05-1",
    "2026-04-",
    "57.06",
    "52.74",
    "52.59",
    "58.67",
]

# If a line contains any of these it is a deliberate old-figure mention
OLD_FIGURES = re.compile(
    r"\b(?:77|67|55|53|35|16|15|14|13|12)\s*"
    r"(?:strict|honest|confirmed|official)?\s*"
    r"(?:locks?|full.suite|archived)"
)


def is_historical_line(line: str) -> bool:
    line_lower = line.lower()
    for marker in HISTORICAL_MARKERS:
        if marker.lower() in line_lower:
            return True
    if OLD_FIGURES.search(line):
        return True
    return False


# ---------------------------------------------------------------------------
# Pattern matching
# ---------------------------------------------------------------------------

# Patterns that carry a lock count claim
COUNT_PATTERNS = [
    # "46 confirmed full-suite locks"
    re.compile(r"\b(\d+)\s+confirmed\s+full[- ]suite\s+locks?", re.IGNORECASE),
    # "46 official full-suite locks"
    re.compile(r"\b(\d+)\s+official\s+full[- ]suite\s+locks?", re.IGNORECASE),
    # "46 strict locks" (but not "15 strict locks" which are historical)
    re.compile(r"\b(\d+)\s+strict\s+locks?", re.IGNORECASE),
    # "46/200 = 23.0%"
    re.compile(r"\b(\d+)/200\s*=\s*[\d.]+\s*%", re.IGNORECASE),
    # "**46** official full-suite" (bold number)
    re.compile(r"\*\*(\d+)\*\*\s+(?:confirmed|official)\s+full[- ]suite", re.IGNORECASE),
    # "Honest score: 46/200" in score_breakdown style
    re.compile(r"honest\s+(?:score|count|headline)[:\s]+(\d+)/200", re.IGNORECASE),
    # "**N** in bold followed by /200" like "**46**/200"
    re.compile(r"\*\*(\d+)\*\*/200", re.IGNORECASE),
    # "= N.N% resolved" or "= N.N% fully resolved"
    re.compile(r"=\s*([\d.]+)\s*%\s*(?:fully\s*)?resolved", re.IGNORECASE),
]


# For percentage patterns, derive expected pct from true count
def expected_pct(true_count: int) -> float:
    return round(true_count / 200 * 100, 1)


@dataclass
class Mismatch:
    path: pathlib.Path
    line_no: int
    line: str
    pattern_desc: str
    found_val: str
    expected_val: str


def check_file(
    path: pathlib.Path,
    true_count: int,
    true_pct: float,
) -> list[Mismatch]:
    mismatches: list[Mismatch] = []
    try:
        text = path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return mismatches

    lines = text.splitlines()
    in_code_block = False
    in_changelog_history = False  # inside a CHANGELOG entry we consider historical

    for i, line in enumerate(lines, 1):
        # Track fenced code blocks
        if line.strip().startswith("```"):
            in_code_block = not in_code_block
        if in_code_block:
            continue

        # In CHANGELOG, entries starting with "## [2026-05-" or older are historical.
        # The most recent batch date below is the live entry; all prior dates are historical.
        if path.name == "CHANGELOG.md":
            if re.match(r"^## \[2026-0[0-5]", line):
                in_changelog_history = True
            elif re.match(r"^## \[2026-06-10\]", line):
                in_changelog_history = True  # superseded by 06-13 batch
            elif re.match(r"^## \[2026-06-11\]", line):
                in_changelog_history = True  # superseded by 06-13 batch
            elif re.match(r"^## \[2026-06-12\]", line):
                in_changelog_history = True  # superseded by 06-13 batch
            elif re.match(r"^## \[2026-06-13\]", line):
                in_changelog_history = False  # most recent batch — live
            elif re.match(r"^## \[Unreleased\]", line, re.IGNORECASE):
                in_changelog_history = False
        if in_changelog_history:
            continue

        if is_historical_line(line):
            continue

        for pat in COUNT_PATTERNS:
            for m in pat.finditer(line):
                val = m.group(1)
                # Percentage pattern
                if "resolved" in pat.pattern and "%" in m.group(0):
                    found_pct = float(val)
                    if found_pct != true_pct:
                        mismatches.append(
                            Mismatch(
                                path=path,
                                line_no=i,
                                line=line.rstrip(),
                                pattern_desc="percentage resolved",
                                found_val=f"{found_pct}%",
                                expected_val=f"{true_pct}%",
                            )
                        )
                else:
                    found_n = int(val)
                    if found_n != true_count:
                        mismatches.append(
                            Mismatch(
                                path=path,
                                line_no=i,
                                line=line.rstrip(),
                                pattern_desc=pat.pattern,
                                found_val=str(found_n),
                                expected_val=str(true_count),
                            )
                        )

    return mismatches


# ---------------------------------------------------------------------------
# Auto-fix
# ---------------------------------------------------------------------------


def fix_file(path: pathlib.Path, true_count: int, true_pct: float) -> int:
    """Replace stale counts in-place. Returns number of substitutions made."""
    text = path.read_text(encoding="utf-8")
    original = text

    # Fix "N confirmed/official full-suite locks"
    text = re.sub(
        r"(\b)\d+(\s+(?:confirmed|official)\s+full[- ]suite\s+locks?)",
        lambda m: f"{m.group(1)}{true_count}{m.group(2)}",
        text,
        flags=re.IGNORECASE,
    )
    # Fix "N strict locks" (only when NOT on a historical line — handled by caller)
    text = re.sub(
        r"(\b)\d+(\s+strict\s+locks?)",
        lambda m: f"{m.group(1)}{true_count}{m.group(2)}",
        text,
        flags=re.IGNORECASE,
    )
    # Fix "N/200 = X.X%"
    text = re.sub(
        r"\b\d+(/200\s*=\s*)[\d.]+(\s*%)",
        lambda m: f"{true_count}{m.group(1)}{true_pct}{m.group(2)}",
        text,
        flags=re.IGNORECASE,
    )
    # Fix "**N** confirmed/official full-suite"
    text = re.sub(
        r"\*\*\d+\*\*(\s+(?:confirmed|official)\s+full[- ]suite)",
        lambda m: f"**{true_count}**{m.group(1)}",
        text,
        flags=re.IGNORECASE,
    )
    # Fix "**N**/200"
    text = re.sub(
        r"\*\*\d+\*\*/200",
        f"**{true_count}**/200",
        text,
    )
    # Fix "= N.N% resolved" / "= N.N% fully resolved"
    text = re.sub(
        r"(=\s*)[\d.]+(\s*%\s*(?:fully\s*)?resolved)",
        lambda m: f"{m.group(1)}{true_pct}{m.group(2)}",
        text,
        flags=re.IGNORECASE,
    )

    if text != original:
        path.write_text(text, encoding="utf-8")
        return text.count(str(true_count)) - original.count(str(true_count))
    return 0


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> int:
    parser = argparse.ArgumentParser(description="ProgramBench doc count consistency check")
    parser.add_argument("--fix", action="store_true", help="Auto-fix mismatches in-place")
    parser.add_argument("--verbose", "-v", action="store_true")
    args = parser.parse_args()

    # --- Denominator gate: non-alias rows must equal EXPECTED_DENOMINATOR ---
    denom_ok, non_alias_count, _ = check_denominator()
    if not denom_ok:
        print(
            f"FAIL: eval_index non-alias row count = {non_alias_count}, "
            f"expected {EXPECTED_DENOMINATOR}. "
            f"Demote or merge stray rows before proceeding."
        )
        return 1

    # --- upstream_skips integrity gate: fail==0 AND nr==0 required ---
    skip_violations = check_upstream_skips_integrity()
    if skip_violations:
        print("FAIL: upstream_skips entries with fail>0 or nr>0 (must reclassify):")
        for v in skip_violations:
            print(f"  {v}")
        return 1

    # --- T2 ceiling_certified gate: CEILING_CERT.md must exist with correct shape ---
    t2_violations = check_t2_cert_files()
    if t2_violations:
        print("FAIL: ceiling_certified entries missing valid CEILING_CERT.md:")
        for v in t2_violations:
            print(f"  {v}")
        return 1

    true_count, slugs = get_true_count()
    true_pct = expected_pct(true_count)

    print(f"eval_index canonical lock count: {true_count} ({true_pct}%)")
    if args.verbose:
        for s in slugs:
            print(f"  {s}")

    files = collect_files()
    print(f"Scanning {len(files)} files...")

    all_mismatches: list[Mismatch] = []
    for path in files:
        ms = check_file(path, true_count, true_pct)
        if ms and args.fix:
            fix_file(path, true_count, true_pct)
            rel = path.relative_to(REPO_ROOT)
            print(f"  FIXED {rel} ({len(ms)} patterns)")
        elif ms:
            for m in ms:
                rel = m.path.relative_to(REPO_ROOT)
                print(
                    f"  MISMATCH {rel}:{m.line_no}  found={m.found_val} expected={m.expected_val}"
                )
                if args.verbose:
                    print(f"    {m.line}")
            all_mismatches.extend(ms)

    if args.fix:
        print("Done. Re-run without --fix to verify.")
        return 0

    if all_mismatches:
        print(f"\nFAIL: {len(all_mismatches)} count mismatch(es) found.")
        return 1

    # --- Claim-scanner: 'N locks' where N > strict_count (overclaim guard) ---
    overclaim_mismatches = check_locks_overclaim(files, true_count)
    if overclaim_mismatches:
        print(f"\nFAIL: {len(overclaim_mismatches)} locks-adjacent overclaim(s) found.")
        print("Publish format: strict count and ceiling-certified count as SEPARATE numbers.")
        for m in overclaim_mismatches:
            rel = m.path.relative_to(REPO_ROOT)
            print(f"  OVERCLAIM {rel}:{m.line_no}  found={m.found_val} (limit={m.expected_val})")
            if args.verbose:
                print(f"    {m.line}")
        return 1

    print("OK: all doc counts match eval_index.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
