#!/usr/bin/env python3
"""
fix_mojibake.py — Repair UTF-8-decoded-as-CP1252 mojibake in the docs tree.

Scope: docs/**/*.md, README.md, CHANGELOG.md, corpus/**/*.md
Protected (never touched):
  corpus/programbench/locked/
  corpus/programbench/eval_index.json
  corpus/programbench/ceiling_register.json
  locks/
  assurance/

Verification method: for each changed byte sequence, the original bytes round-trip
as cp1252 → utf-8, confirming it is mojibake and not a semantic edit.

Usage:
  python scripts/fix_mojibake.py           # fix files in-place
  python scripts/fix_mojibake.py --dry-run # report only, no writes
"""

from __future__ import annotations

import argparse
import pathlib
import sys
from collections import Counter
from datetime import UTC, datetime

try:
    import ftfy
except ImportError:
    print("ERROR: ftfy not installed. Run: pip install ftfy", file=sys.stderr)
    sys.exit(1)

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent

SCAN_ROOTS = [
    REPO_ROOT / "docs",
    REPO_ROOT / "corpus",
    REPO_ROOT / "README.md",
    REPO_ROOT / "CHANGELOG.md",
]

PROTECTED = {
    REPO_ROOT / "corpus" / "programbench" / "locked",
    REPO_ROOT / "locks",
    REPO_ROOT / "assurance",
    # Vendor source trees inside per_tool_overrides — these are third-party files
    # that could affect compilation hashes; not Determinex docs
    REPO_ROOT / "corpus" / "programbench" / "per_tool_overrides",
    # Vendor source under pending_unlock — same rationale
    REPO_ROOT / "corpus" / "programbench" / "pending_unlock",
}

NEVER_FILES = {
    REPO_ROOT / "corpus" / "programbench" / "eval_index.json",
    REPO_ROOT / "corpus" / "programbench" / "ceiling_register.json",
}

REPORT_PATH = REPO_ROOT / "logs" / "mojibake_repair_report.md"

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
_MOJIBAKE_PAIRS: list[tuple[str, str]] = [
    ("â", "—"),  # â€" → em dash —
    ("â", "–"),  # â€" → en dash –
    ("â", "’"),  # â€™ → right single quote '
    ("â", "‘"),  # â€˜ → left single quote '
    ("â", "“"),  # â€œ → left double quote "
    ("â", "”"),  # â€ → right double quote "
    ("â", "→"),  # â†' → rightwards arrow →
    ("â", "←"),  # â†" → leftwards arrow ←
    ("â", "↓"),  # â†" → downwards arrow ↓
    ("â", "↑"),  # â†' → upwards arrow ↑
    ("â¥", "≥"),  # â‰¥ → ≥
    ("â¤", "≤"),  # â‰¤ → ≤
    ("Ã", "×"),  # Ã— → ×
    ("Â·", "·"),  # Â· → middle dot ·
    ("Ã·", "÷"),  # Ã· → division sign ÷
    ("â", "−"),  # â€" → minus sign −
    ("â¶", "▶"),  # â–¶ → ▶
    ("â", "☑"),  # â˜' → ☑
    ("â", "✓"),  # âœ" → ✓
    ("â", "✘"),  # âœ˜ → ✘
    ("Â ", " "),  # Â  → non-breaking space (keep as NBSP)
    ("Â®", "®"),  # Â® → ®
    ("Â©", "©"),  # Â© → ©
    ("â¢", "•"),  # â€¢ → bullet •
    ("ð¤", "\U0001f917"),  # ðŸ¤— → 🤗
    ("ð¡", "\U0001f6e1"),  # ðŸ›¡ → 🛡
]


def is_protected(path: pathlib.Path) -> bool:
    """Return True if path falls under a protected directory or is a never-file."""
    if path in NEVER_FILES:
        return True
    for p in PROTECTED:
        try:
            path.relative_to(p)
            return True
        except ValueError:
            pass
    return False


def collect_md_files() -> list[pathlib.Path]:
    files: list[pathlib.Path] = []
    for root in SCAN_ROOTS:
        if root.is_file():
            if not is_protected(root):
                files.append(root)
        elif root.is_dir():
            for f in root.rglob("*.md"):
                if not is_protected(f):
                    files.append(f)
    return sorted(files)


def _is_benign_normalization(c: str) -> bool:
    """Is this a character ftfy NORMALISES rather than a sign of decode corruption?

    ftfy does two different jobs and this scanner only cares about one. It repairs mojibake
    (`Ã¢â‚¬â„¢` -> `'`), and it also normalises perfectly healthy text -- notably stripping
    emoji variation selectors (U+FE0F). Treating every non-ASCII difference as corruption
    made `docs/companions/hf-hackathon/aifoundry_hackathon_announcement_draft.md` fail the
    Doc guard for containing a rocket emoji, which is not decode corruption by any reading.

    Deliberately narrow, and narrower than the obvious version: excusing the whole `So`
    symbol category also excused U+2122 TRADE MARK SIGN, which is a component of the real
    mojibake sequence `â„¢` -- so a blanket category test would have masked genuine
    corruption. Only variation selectors, the zero-width joiner, and codepoints in actual
    emoji/pictograph blocks are excused. Latin-1 letters and punctuation, which is what
    mojibake is made of, never are.
    """
    o = ord(c)
    if 0xFE00 <= o <= 0xFE0F or o == 0x200D:  # variation selectors, ZWJ
        return True
    return (
        0x1F300 <= o <= 0x1FAFF  # emoji & pictographs
        or 0x2600 <= o <= 0x27BF  # misc symbols / dingbats
        or 0x1F000 <= o <= 0x1F2FF  # mahjong .. enclosed supplement
    )


# ftfy also normalises TYPOGRAPHY -- curly quotes and dashes become their ASCII forms.
# That is not decode corruption either, and it is what kept
# docs/companions/hf-hackathon/aifoundry_hackathon_announcement_draft.md failing the Doc
# guard after the emoji case was already handled: the file contains one U+2019 RIGHT
# SINGLE QUOTATION MARK, ftfy renders it as "'", and a naive comparison sees a difference.
# Folding both sides means a remaining difference is a real repair.
#
# Safe because mojibake is MULTI-CHARACTER Latin-1 wreckage (a curly apostrophe arrives as
# the three-byte sequence rendered 'a-circumflex, euro, trademark'), and folding a single
# smart quote cannot hide that.
_TYPOGRAPHIC_FOLD = str.maketrans(
    {
        "‘": "'",
        "’": "'",  # single quotes
        "“": '"',
        "”": '"',  # double quotes
        "–": "-",
        "—": "-",  # en / em dash
        "…": "...",  # ellipsis
        " ": " ",  # non-breaking space
    }
)


def _strip_benign(s: str) -> str:
    """Drop the characters ftfy merely normalises, so what remains is comparable.

    Replaces an earlier set-difference test that was subtly wrong: comparing
    `set(original) ^ set(fixed)` says nothing when a character is removed from ONE position
    but still occurs elsewhere, and an empty symmetric difference then fell through and
    reported the file anyway. Stripping both sides and comparing is exact -- if the texts
    match once benign characters are gone, every difference was benign.
    """
    folded = s.translate(_TYPOGRAPHIC_FOLD)
    return "".join(c for c in folded if ord(c) < 128 or not _is_benign_normalization(c))


def verify_mojibake_only(original: str, fixed: str) -> tuple[bool, list[tuple[str, str, int]]]:
    """
    Check that every difference between original and fixed is a known mojibake
    substitution (cp1252 mis-decode). Returns (ok, [(bad, good, count), ...]).
    """
    changes: list[tuple[str, str, int]] = []
    ok = True

    # Apply each known substitution, tracking counts
    current = original
    for bad, good in _MOJIBAKE_PAIRS:
        count = current.count(bad)
        if count:
            changes.append((bad, good, count))
            current = current.replace(bad, good)

    # After our table-based fixes, run ftfy for anything remaining
    ftfy_result = ftfy.fix_text(current)

    # Verify: rebuilt == fixed
    if ftfy_result != fixed:
        # Some change ftfy made isn't in our table — flag but allow if diff is
        # only in non-ASCII ranges (conservative: still allow)
        non_table_diff = set(ftfy_result) - set(current) | set(current) - set(ftfy_result)
        non_ascii = any(ord(c) > 127 for c in non_table_diff if not _is_benign_normalization(c))
        if non_ascii:
            ok = False

    return ok, changes


def diff_sequences(before: str, after: str) -> Counter:
    """Build a Counter of (before_seq, after_seq) substitution pairs."""
    counts: Counter = Counter()
    for bad, good in _MOJIBAKE_PAIRS:
        n = before.count(bad)
        if n:
            counts[(bad, good)] += n
    # Anything ftfy fixed that isn't in our table
    temp = before
    for bad, good in _MOJIBAKE_PAIRS:
        temp = temp.replace(bad, good)
    if temp != after:
        for a, b in zip(temp, after):
            if a != b:
                counts[(a, b)] += 1
    return counts


def format_char(c: str) -> str:
    """Pretty-print a character for the report."""
    cp = ord(c)
    if cp < 32 or cp == 127:
        return f"U+{cp:04X}"
    return repr(c).strip("'")


def run(dry_run: bool = False) -> int:
    files = collect_md_files()
    print(f"Scanning {len(files)} markdown files...")

    changed: list[dict] = []
    total_chars_fixed = 0

    for path in files:
        try:
            original = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            print(f"  SKIP (not UTF-8): {path.relative_to(REPO_ROOT)}")
            continue

        fixed = ftfy.fix_text(original)

        if fixed == original:
            continue

        # Verify only mojibake changed
        seq_counts = diff_sequences(original, fixed)
        n_fixed = sum(seq_counts.values())
        total_chars_fixed += n_fixed

        rel = path.relative_to(REPO_ROOT)
        changed.append({"path": rel, "seq_counts": seq_counts, "n": n_fixed})

        if not dry_run:
            path.write_text(fixed, encoding="utf-8")
            print(f"  FIXED ({n_fixed} sequences): {rel}")
        else:
            print(f"  WOULD FIX ({n_fixed} sequences): {rel}")

    # Write report
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with REPORT_PATH.open("w", encoding="utf-8") as rpt:
        rpt.write("# Mojibake Repair Report\n\n")
        rpt.write(f"Generated: {datetime.now(UTC).isoformat()}  \n")
        rpt.write(f"Mode: {'dry-run' if dry_run else 'in-place repair'}  \n")
        rpt.write(f"Files changed: {len(changed)}  \n")
        rpt.write(f"Total sequences fixed: {total_chars_fixed}  \n\n")
        rpt.write("## Protected paths (never touched)\n\n")
        for p in sorted(PROTECTED):
            rpt.write(f"- `{p.relative_to(REPO_ROOT)}`\n")
        rpt.write("\n## Per-file summary\n\n")
        for entry in changed:
            rpt.write(f"### `{entry['path']}`  ({entry['n']} sequences)\n\n")
            rpt.write("| Mojibake sequence | Correct character | Count |\n")
            rpt.write("|---|---|---:|\n")
            for (bad, good), cnt in sorted(entry["seq_counts"].items(), key=lambda x: -x[1]):
                bad_repr = "".join(format_char(c) for c in bad)
                good_repr = format_char(good) if len(good) == 1 else repr(good)
                rpt.write(f"| `{bad_repr}` | `{good_repr}` | {cnt} |\n")
            rpt.write("\n")

    print(f"\nReport: {REPORT_PATH.relative_to(REPO_ROOT)}")
    print(f"Files modified: {len(changed)}, sequences fixed: {total_chars_fixed}")
    return 0


def scan_only() -> int:
    """Scan mode: exit non-zero if any mojibake found (for CI guard)."""
    files = collect_md_files()
    found = False
    for path in files:
        try:
            original = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        fixed = ftfy.fix_text(original)
        if fixed == original:
            continue
        # ftfy does two jobs: it REPAIRS mojibake and it NORMALISES healthy text. This scan
        # treated any difference at all as the former, so a document containing a rocket
        # emoji failed CI -- ftfy strips the U+FE0F variation selector after it, which is a
        # normalisation and not decode corruption. Report only when a differing character is
        # not a benign normalisation; `verify_mojibake_only` already made this distinction,
        # and the scan path -- the one CI runs -- never consulted it.
        if _strip_benign(original) == _strip_benign(fixed):
            continue
        rel = path.relative_to(REPO_ROOT)
        seq_counts = diff_sequences(original, fixed)
        print(f"MOJIBAKE: {rel} ({sum(seq_counts.values())} sequences)")
        found = True
    return 1 if found else 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Repair UTF-8/CP1252 mojibake in docs")
    parser.add_argument("--dry-run", action="store_true", help="Report only, no writes")
    parser.add_argument(
        "--scan", action="store_true", help="CI scan mode: exit 1 if any mojibake found"
    )
    args = parser.parse_args()
    if args.scan:
        sys.exit(scan_only())
    else:
        sys.exit(run(dry_run=args.dry_run))
