#!/usr/bin/env python3
"""
ProgramBench Override Scanner — Layer 2 enforcement.

Scans per_tool_overrides and locked submission tarballs, categorizing each
compile.sh into:
  build_only     — changes build flags, module paths, binary wrapping only.
                   Allowed. Logged in board.
  eval_override  — changes which tests get collected or counted (collection
                   caps, ignore globs, modifyitems filters). FORBIDDEN for
                   any official_full_suite_resolved=true claim.

Usage:
  python scripts/pb_override_scan.py                  # scan all overrides
  python scripts/pb_override_scan.py --locked-only    # scan locked tools only
  python scripts/pb_override_scan.py --eval-only      # print only eval_overrides
  python scripts/pb_override_scan.py --guard          # exit 1 if any locked tool
                                                       #   has eval_override

The --guard flag is designed for CI integration: it prevents any new lock
archival from using a capped or filtered eval.
"""

import json
import re
import sys
import tarfile
from pathlib import Path

OVERRIDES_DIR = Path("corpus/programbench/per_tool_overrides")
LOCKED_DIR = Path("corpus/programbench/locked")
BOARD_PATH = Path("logs/programbench_lock_board.json")

# Patterns that constitute an eval_override (forbidden for lock claims).
#
# NOT flagged (permitted):
#  - collect_ignore_glob with only unambiguous TUI filenames (test_tui*, test_tmux*,
#    test_pty*, test_pexpect*, test_curses*) — these cannot be false positives.
#  - pytest_collection_modifyitems that scans module SOURCE for TUI library imports
#    (_TUI_IMPORTS / re.compile(... pexpect|libtmux|curses|pty ...)) — accurate, not
#    keyword-in-nodeid suppression.
#
# Flagged (forbidden):
#  - del items[N:] collection cap — hides tests from the total count.
#  - collect_ignore_glob that includes "test_interactive" — over-broad, was the source
#    of the quickjs false-positive regression.
#  - modifyitems filter that uses nodeid/name string keywords (old pattern: checks if
#    "interactive" appears in the nodeid string) — risky, catches non-TUI tests.
EVAL_OVERRIDE_PATTERNS: list[tuple[str, re.Pattern]] = [
    ("collection_cap", re.compile(r"del items\[\d+:\]")),
    (
        "collect_ignore_glob_interactive",
        re.compile(r"collect_ignore_glob\s*=.*?test_interactive", re.DOTALL),
    ),
    (
        "modifyitems_nodeid_keyword_filter",
        re.compile(
            r'nodeid.*?["\']interactive["\']|["\']interactive["\'].*?nodeid|'
            r'any\(.*?["\']interactive["\'].*?\bin\b.*?nodeid',
            re.DOTALL | re.IGNORECASE,
        ),
    ),
    ("skipif_platform", re.compile(r"pytest\.mark\.skipif.*platform")),
    # RED behavioral patterns (output-rewrite / fixture-tamper / result-XML edit) --
    # these make a "behavioral fix" a cheat. Mirrors determinex_pb_integrity._RED_TRANSFORM.
    ("skip_injection", re.compile(r"add_marker\([^)]*skip|item\.add_marker\(.*skip")),
    (
        "results_xml_failure_edit",
        re.compile(r"results?\.xml[\s\S]{0,200}?(<failure|remove.*testcase|del .*testcase)"),
    ),
    (
        "golden_fixture_write",
        re.compile(r"\.golden['\"][^)]*['\"]w['\"]|write_text\([^)]*golden|expected\.write"),
    ),
]


def _is_red_output_rewrite(content: str) -> list[str]:
    """A YELLOW output normalizer is RED if it maps SPECIFIC literals to SPECIFIC
    golden values (memorizing the answer) instead of normalizing volatile CLASSES."""
    subst = re.findall(r"""\.replace\(\s*['"][^'"]{2,}['"]\s*,\s*['"][^'"]{2,}['"]""", content)
    volatile = re.search(
        r"/tmp/|pytest-|\\r\\n|x1b\[|0-9a-f\]\{7|strip\(\)|rstrip|expandtabs|sub\(r", content
    )
    return ["red_literal_output_substitution"] if (subst and not volatile) else []


def _broken_conftest_reasons(content: str) -> list[str]:
    """A conftest that does not PARSE means pytest never loads -> no results.xml ->
    PB reports results_read_failed -> score 0, with the SyntaxError hidden. Catch it
    here so the guard SEES a broken artifact instead of letting it masquerade as a lock
    (the corpus-corruption blind spot: orphaned cap `if`, stray list commas)."""
    import ast as _ast

    out = []
    for m in re.finditer(r"<<\s*'?(\w+)'?\n(.*?)\n\1", content, re.DOTALL):
        body = m.group(2)
        if not ("def pytest_" in body or "collect_ignore" in body or "pytest_collection" in body):
            continue
        try:
            _ast.parse(body)
        except SyntaxError as e:
            out.append(f"broken_conftest_syntax ({e.msg} @L{e.lineno})")
    return out


def classify_compile_sh(content: str) -> tuple[str, list[str]]:
    """Returns (category, [matched_reasons]) where category is 'eval_override' or 'build_only'.
    `content` should be compile.sh + any behavioral/clock plugin bodies concatenated, so
    RED behavioral cheats (output-rewrite / skip-injection / fixture-edit) are caught too."""
    reasons: list[str] = []
    for name, pattern in EVAL_OVERRIDE_PATTERNS:
        if pattern.search(content):
            reasons.append(name)
    reasons += _is_red_output_rewrite(content)
    reasons += _broken_conftest_reasons(content)  # a non-parsing conftest is a masked 0
    if reasons:
        return "eval_override", reasons
    return "build_only", []


def _bundle_content(read_file) -> str:
    """Concatenate compile.sh + the behavioral/clock plugin files for a complete scan.
    `read_file(name) -> str|None`."""
    parts = []
    for n in (
        "compile.sh",
        "determinex_behavioral.py",
        "determinex_bidir.py",
        "determinex_faketime.go",
    ):
        c = read_file(n)
        if c:
            parts.append(c)
    return "\n".join(parts)


def scan_tarball(tf_path: Path) -> tuple[str, list[str]] | None:
    """Scan compile.sh inside a submission.tar.gz. Returns (category, reasons) or None."""
    try:
        with tarfile.open(tf_path, "r:gz") as tf:
            names = tf.getnames()
            if not any(n.endswith("compile.sh") for n in names):
                return None

            def _read(base):
                n = next((x for x in names if x.endswith("/" + base) or x.endswith(base)), None)
                if not n:
                    return None
                try:
                    fobj = tf.extractfile(n)
                    return fobj.read().decode("utf-8", errors="replace") if fobj else None
                except Exception:
                    return None

            return classify_compile_sh(_bundle_content(_read))
    except Exception as e:
        return ("error", [str(e)])


def scan_override_dir(tool_dir: Path) -> tuple[str, list[str]] | None:
    """Scan compile.sh + behavioral/clock plugins in a per_tool_overrides directory."""
    if not (tool_dir / "compile.sh").exists():
        return None

    def _read(base):
        p = tool_dir / base
        return p.read_text(encoding="utf-8", errors="replace") if p.exists() else None

    return classify_compile_sh(_bundle_content(_read))


def main() -> None:
    locked_only = "--locked-only" in sys.argv
    eval_only = "--eval-only" in sys.argv
    guard_mode = "--guard" in sys.argv

    # Load board to know which tools are locked.
    #
    # A raw FileNotFoundError traceback here is the worst available outcome: it fails the
    # job (correct) while telling the reader nothing about WHY (not correct), and it looks
    # identical to the scanner crashing. Seen live in CI as
    # `FileNotFoundError: [Errno 2] No such file or directory:
    # 'logs/programbench_lock_board.json'` with a six-frame pathlib traceback above it.
    # This guard exists to stop a locked tool's compile.sh from suppressing test
    # collection; if it cannot read the board it is enforcing nothing, and it should say so
    # in one line.
    if not BOARD_PATH.is_file():
        print(
            f"GUARD CANNOT RUN: {BOARD_PATH} is missing, so no tool's lock status is "
            f"known and no compile.sh can be checked against it. This is not a pass.",
            file=sys.stderr,
        )
        sys.exit(1)
    board = json.loads(BOARD_PATH.read_text(encoding="utf-8"))
    locked_slugs = {e["base_slug"] for e in board if e.get("locked_archive")}
    # Only tools claiming official_full_suite_resolved=True are subject to the
    # GUARD FAILED check.  partial_eval_100 tools have locked_archive=True for
    # historical reference but do NOT claim an official lock — the guard must
    # not block them (they'll be re-evaluated with caps removed separately).
    official_slugs = {e["base_slug"] for e in board if e.get("official_full_suite_resolved")}
    slug_to_entry = {e["base_slug"]: e for e in board}

    results: list[dict] = []

    # Scan locked tool tarballs
    for tool_dir in sorted(LOCKED_DIR.iterdir()):
        if not tool_dir.is_dir():
            continue
        tf_path = tool_dir / "submission.tar.gz"
        if not tf_path.exists():
            continue
        category_result = scan_tarball(tf_path)
        if category_result is None:
            continue
        category, reasons = category_result

        # Find matching board entry
        slug = next(
            (s for s in locked_slugs if tool_dir.name in s or s.endswith(f"__{tool_dir.name}")),
            None,
        )
        is_locked = slug in locked_slugs if slug else False
        # is_official: only True for tools claiming official_full_suite_resolved.
        # Guard failure is restricted to official claims — partial_eval_100 tools
        # have locked archives but are NOT making a full-suite claim.
        is_official = slug in official_slugs if slug else False

        results.append(
            {
                "tool": tool_dir.name,
                "slug": slug,
                "source": "locked_tarball",
                "category": category,
                "reasons": reasons,
                "is_locked": is_locked,
                "is_official": is_official,
            }
        )

    # Scan per_tool_overrides (non-locked tools too)
    if not locked_only:
        for override_dir in sorted(OVERRIDES_DIR.iterdir()):
            if not override_dir.is_dir():
                continue
            # Skip if already covered by locked tarball scan
            tool_short = (
                override_dir.name.split(".")[0].split("__")[-1]
                if "__" in override_dir.name
                else override_dir.name
            )
            already_scanned = any(r["tool"] == tool_short for r in results)
            if already_scanned:
                continue
            category_result = scan_override_dir(override_dir)
            if category_result is None:
                continue
            category, reasons = category_result
            results.append(
                {
                    "tool": override_dir.name,
                    "slug": None,
                    "source": "per_tool_override",
                    "category": category,
                    "reasons": reasons,
                    "is_locked": False,
                    "is_official": False,
                }
            )

    # Filter and print
    eval_overrides = [r for r in results if r["category"] == "eval_override"]
    build_only = [r for r in results if r["category"] == "build_only"]
    locked_with_eval_override = [r for r in eval_overrides if r["is_locked"]]
    # Guard only blocks tools that are claiming official_full_suite_resolved=True.
    # partial_eval_100 tools have locked archives but are not making that claim.
    official_with_eval_override = [r for r in eval_overrides if r.get("is_official")]

    if not eval_only:
        print(f"Override scan results: {len(results)} tools scanned")
        print(f"  eval_override (FORBIDDEN for official lock claims): {len(eval_overrides)}")
        print(f"  build_only (allowed): {len(build_only)}")
        print()

    print("EVAL OVERRIDES (must be removed before tool can claim an official lock):")
    for r in sorted(eval_overrides, key=lambda x: x["tool"]):
        if r.get("is_official"):
            locked_flag = " [OFFICIAL LOCK — VIOLATION]"
        elif r["is_locked"]:
            locked_flag = " [partial_eval_100 archive — needs re-eval to claim lock]"
        else:
            locked_flag = ""
        print(f"  {r['tool']:<35} reasons: {', '.join(r['reasons'])}{locked_flag}")

    if not eval_only:
        print()
        print(
            f"Official locks with eval_override (GUARD violations): {len(official_with_eval_override)}"
        )
        for r in official_with_eval_override:
            print(f"  VIOLATION: {r['tool']} ({', '.join(r['reasons'])})")
        if locked_with_eval_override and not official_with_eval_override:
            n_partial = len(locked_with_eval_override)
            print(
                f"  ({n_partial} partial_eval_100 archives have overrides — not guard violations; require re-eval to convert)"
            )

    if guard_mode:
        if official_with_eval_override:
            print(
                "\nGUARD FAILED: official_full_suite_resolved tool(s) have eval_overrides. Fix before archiving."
            )
            sys.exit(1)
        # Say plainly when there was nothing to enforce (2026-07-30). The blocking set is derived
        # from official_full_suite_resolved, and after the provenance retraction NO board entry
        # carries that flag -- 210 entries, 100 with locked_archive, 0 official. So `is_official`
        # is always False and this guard is structurally incapable of failing, while still printing
        # "GUARD PASSED" after listing ~50 tools with collection_cap / nodeid-filter violations.
        # CLAUDE.md describes this as the CI gate that fails when a locked tool's compile.sh
        # contains collection-modifying patterns, so a bare "PASSED" reads as that check having
        # run. It has not. The exit code stays 0 -- there is genuinely no official claim to
        # protect -- but the message no longer implies a verdict it did not reach.
        if not official_slugs:
            print(
                "\nGUARD VACUOUS: no board entry claims official_full_suite_resolved, so this "
                "guard had nothing to enforce."
            )
            if locked_with_eval_override:
                print(
                    f"  ({len(locked_with_eval_override)} locked archive(s) DO contain "
                    f"eval_overrides -- they are simply not claimed as official locks. "
                    f"Re-check this guard the moment any tool claims one.)"
                )
            sys.exit(0)
        print("\nGUARD PASSED: no official_full_suite_resolved tool has eval_overrides.")
        sys.exit(0)


if __name__ == "__main__":
    main()
