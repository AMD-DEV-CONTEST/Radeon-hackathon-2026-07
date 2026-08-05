"""
pb_uncap.py — Remove collection caps from compile.sh in ProgramBench tarballs.

Strict rules:
  1. Remove ONLY del items[N:] lines — nothing else changes.
  2. Replace keyword-based TUI filter with semantic classification.
  3. Verify result contains no del items[N:] patterns before writing.
  4. Repack tarball with only compile.sh modified.

Output: corpus/programbench/pending_unlock/{tool}/submission_uncapped.tar.gz
        corpus/programbench/pending_unlock/{tool}/uncap_diff.txt
"""

from __future__ import annotations

import sys

# Force UTF-8 output on Windows so box-drawing chars print cleanly
if sys.stdout.encoding and sys.stdout.encoding.lower() not in ("utf-8", "utf8"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

import argparse
import io
import re
import tarfile
from difflib import unified_diff
from pathlib import Path

ROOT = Path(__file__).parent.parent
PB_DIR = ROOT / "corpus" / "programbench"
LOCKED_BASE = PB_DIR / "locked"
PENDING_BASE = PB_DIR / "pending_unlock"

# Pattern: del items[N:] — any integer, with optional whitespace
CAP_PATTERN = re.compile(r"^\s*del\s+items\s*\[\s*\d+\s*:\s*\]\s*$", re.MULTILINE)

# Old keyword-based TUI filter pattern to detect
KEYWORD_FILTER_PATTERN = re.compile(
    r"if any\(s in nodeid for s in \([^)]*(?:tmux|interactive|libtmux|pexpect|test_pty)[^)]*\)\)",
    re.IGNORECASE,
)

SEMANTIC_TUI_FILTER = """    # Semantic TUI classification — filter on file structure and imports, not name
    import ast as _ast, pathlib as _pathlib
    def _is_tui_test(item):
        fpath = str(getattr(item, 'fspath', '') or '')
        if any(pat in fpath.lower() for pat in (
                'test_tui', 'test_tmux', 'test_pty',
                'test_interactive', 'test_pexpect', 'test_curses')):
            return True
        try:
            src = _pathlib.Path(fpath).read_text(errors='replace')
            tree = _ast.parse(src)
            tui_mods = {'pexpect', 'libtmux', 'curses', 'pty', 'termios', 'tty', 'blessed', 'urwid'}
            for node in _ast.walk(tree):
                if isinstance(node, (_ast.Import, _ast.ImportFrom)):
                    names = [a.name for a in getattr(node, 'names', [])]
                    mod = getattr(node, 'module', '') or ''
                    if any(t in names or t in mod for t in tui_mods):
                        return True
        except Exception:
            pass
        return False
    items[:] = [item for item in items if not _is_tui_test(item)]"""


def find_tarball(tool_slug: str) -> Path | None:
    """Find the submission tarball in locked/ or pending_unlock/ dirs."""
    # Check pending_unlock priority dirs first
    for pri in ("priority_1_under100", "priority_2_under300", "priority_3_over300"):
        p = PENDING_BASE / pri / tool_slug / "submission.tar.gz"
        if p.exists():
            return p
    # Check flat pending
    p = PENDING_BASE / tool_slug / "submission.tar.gz"
    if p.exists():
        return p
    # Check locked flat dirs
    p = LOCKED_BASE / tool_slug / "submission.tar.gz"
    if p.exists():
        return p
    # Fuzzy match in locked
    for d in LOCKED_BASE.iterdir():
        if d.is_dir() and tool_slug in d.name:
            t = d / "submission.tar.gz"
            if t.exists():
                return t
    return None


def remove_caps(compile_sh: str) -> tuple[str, int]:
    """Remove all del items[N:] lines (and optional/dangling enclosing if statement). Returns (modified, count_removed)."""
    # 1. Match the combined block: 'if len(items) > N:' followed by 'del items[N:]'
    pat_combined = re.compile(
        r"(?:^\s*if\s+len\s*\(\s*items\s*\)\s*>\s*\d+\s*:\s*\r?\n)?^\s*del\s+items\s*\[\s*\d+\s*:\s*\]\s*\r?\n",
        re.MULTILINE,
    )
    compile_sh, count = pat_combined.subn("", compile_sh)

    # 2. Match any leftover dangling 'if len(items) > N:' statements
    pat_dangling = re.compile(
        r"^\s*if\s+len\s*\(\s*items\s*\)\s*>\s*\d+\s*:\s*\r?\n+(?=\s*(?:CONFTEST_EOF|def\s|class\s|done|true|^\S))",
        re.MULTILINE,
    )
    compile_sh, count_dangling = pat_dangling.subn("", compile_sh)

    return compile_sh, count + count_dangling


def apply_semantic_filter(compile_sh: str) -> tuple[str, bool]:
    """Replace keyword-based TUI filter with semantic classification if present."""
    # Find the block: from "if any(s in nodeid" through "items[:] = keep"
    # We look for the broader pattern of the keyword filter block
    block_pattern = re.compile(
        r"(\s*)(?:keep\s*=\s*\[\]\s*\n\s*for item in items:\s*\n\s*nodeid[^\n]*\n\s*"
        r"if any\(s in nodeid[^\n]*\n[^\n]*\n\s*continue\s*\n\s*keep\.append[^\n]*\n"
        r"\s*items\[:?\]\s*=\s*keep)",
        re.DOTALL,
    )
    # Simpler replacement: if the keyword filter one-liner is present
    old_oneliner = re.compile(
        r'\s*nodeid\s*=\s*\(getattr\(item,\s*[\'"]nodeid[\'"],[^\n]*\)\.lower\(\)\s*\n'
        r"\s*if any\(s in nodeid for s in[^\n]+\):\s*\n"
        r"\s*continue\s*\n",
        re.MULTILINE,
    )

    if not KEYWORD_FILTER_PATTERN.search(compile_sh):
        return compile_sh, False

    # Replace the entire keep=[]/for/if/continue/append block
    full_block = re.compile(
        r"(\n\s*keep\s*=\s*\[\]\s*\n"
        r"\s*for item in items:\s*\n"
        r"(?:[^\n]*\n)*?"
        r"\s*items\[:?\]\s*=\s*keep)",
        re.MULTILINE,
    )
    new, n = full_block.subn("\n" + SEMANTIC_TUI_FILTER, compile_sh)
    if n == 0:
        # Try the simpler replacement just for the nodeid/if/continue block
        new = old_oneliner.sub("", compile_sh)

    return new, True


def uncap_tool(tool_slug: str, output_dir: Path | None = None) -> bool:
    tarball = find_tarball(tool_slug)
    if tarball is None:
        print(f"  ERROR: No tarball found for '{tool_slug}'", file=sys.stderr)
        return False

    print(f"\n{'─' * 60}")
    print(f"  Uncapping: {tool_slug}")
    print(f"  Source:    {tarball}")

    # Determine output location
    if output_dir is None:
        # Find pending_unlock location or use locked dir
        for pri in ("priority_1_under100", "priority_2_under300", "priority_3_over300"):
            d = PENDING_BASE / pri / tool_slug
            if d.exists():
                output_dir = d
                break
        if output_dir is None:
            output_dir = PENDING_BASE / tool_slug
            output_dir.mkdir(parents=True, exist_ok=True)

    out_tarball = output_dir / "submission_uncapped.tar.gz"
    diff_file = output_dir / "uncap_diff.txt"

    # Read the tarball, find compile.sh
    try:
        with tarfile.open(tarball, "r:gz") as tf:
            members = tf.getmembers()
            compile_member = None
            for m in members:
                if m.name.endswith("compile.sh"):
                    compile_member = m
                    break

            if compile_member is None:
                print("  ERROR: No compile.sh found in tarball", file=sys.stderr)
                return False

            f = tf.extractfile(compile_member)
            original_sh = f.read().decode("utf-8", errors="replace")
    except Exception as ex:
        print(f"  ERROR reading tarball: {ex}", file=sys.stderr)
        return False

    # Apply modifications
    modified_sh, caps_removed = remove_caps(original_sh)
    modified_sh, semantic_applied = apply_semantic_filter(modified_sh)

    # Verify: no del items[N:] remains
    remaining_caps = CAP_PATTERN.findall(modified_sh)
    if remaining_caps:
        print("  ERROR: Cap removal incomplete — still found:", file=sys.stderr)
        for cap in remaining_caps:
            print(f"    {cap.strip()}", file=sys.stderr)
        return False

    if caps_removed == 0:
        print(f"  WARNING: No collection cap found in {tool_slug}/compile.sh")
        print("           (may already be uncapped or cap is in a different format)")

    # Generate diff
    diff_lines = list(
        unified_diff(
            original_sh.splitlines(keepends=True),
            modified_sh.splitlines(keepends=True),
            fromfile="compile.sh (original)",
            tofile="compile.sh (uncapped)",
        )
    )
    diff_text = "".join(diff_lines)
    diff_file.write_text(diff_text, encoding="utf-8")

    # Repack tarball with modified compile.sh
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as out_tf:
        with tarfile.open(tarball, "r:gz") as in_tf:
            for m in in_tf.getmembers():
                if m.name == compile_member.name:
                    # Replace with modified version
                    encoded = modified_sh.encode("utf-8")
                    info = tarfile.TarInfo(name=m.name)
                    info.size = len(encoded)
                    info.mode = m.mode
                    info.mtime = m.mtime
                    out_tf.addfile(info, io.BytesIO(encoded))
                else:
                    f = in_tf.extractfile(m)
                    if f is not None:
                        out_tf.addfile(m, f)
                    else:
                        out_tf.addfile(m)

    out_tarball.write_bytes(buf.getvalue())

    print(f"  Caps removed: {caps_removed}")
    print(f"  Semantic TUI filter applied: {semantic_applied}")
    print(f"  Output tarball: {out_tarball} ({out_tarball.stat().st_size:,} bytes)")
    print(f"  Diff: {diff_file}")
    print()

    # Show diff summary
    if diff_text:
        add = sum(1 for l in diff_lines if l.startswith("+") and not l.startswith("+++"))
        rem = sum(1 for l in diff_lines if l.startswith("-") and not l.startswith("---"))
        print(f"  Diff: +{add} lines added, -{rem} lines removed")
        # Show just the cap/filter removals
        for line in diff_lines:
            if line.startswith(("-", "+")) and not line.startswith(("---", "+++")):
                if "del items[" in line or "nodeid" in line or "keep" in line:
                    print(f"    {line}", end="")
    else:
        print("  No changes made to compile.sh")

    return True


def get_pending_tools(priority: int | None = None) -> list[str]:
    """Return tool slugs from pending_unlock, optionally filtered by priority."""
    tools = []
    pri_map = {1: "priority_1_under100", 2: "priority_2_under300", 3: "priority_3_over300"}

    if priority is not None:
        dirs_to_scan = [PENDING_BASE / pri_map[priority]]
    else:
        dirs_to_scan = [PENDING_BASE / d for d in pri_map.values()]

    for pri_dir in dirs_to_scan:
        if not pri_dir.exists():
            continue
        for tool_dir in sorted(pri_dir.iterdir()):
            if tool_dir.is_dir():
                tools.append(tool_dir.name)
    return tools


def main():
    parser = argparse.ArgumentParser(description="Remove collection caps from PB submissions")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--tool", help="Process a single tool by slug")
    group.add_argument(
        "--all-priority-1", action="store_true", help="Process all priority-1 (not_run < 100) tools"
    )
    group.add_argument(
        "--all-priority-2",
        action="store_true",
        help="Process all priority-2 (not_run 100-300) tools",
    )
    group.add_argument("--all", action="store_true", help="Process all pending_unlock tools")
    args = parser.parse_args()

    if args.tool:
        tools = [args.tool]
    elif args.all_priority_1:
        tools = get_pending_tools(priority=1)
    elif args.all_priority_2:
        tools = get_pending_tools(priority=2)
    else:
        tools = get_pending_tools()

    if not tools:
        print("No tools found to process.")
        return 1

    print(f"Processing {len(tools)} tool(s)...")
    success = 0
    failed = []
    for slug in tools:
        if uncap_tool(slug):
            success += 1
        else:
            failed.append(slug)

    print(f"\n{'=' * 60}")
    print(f"Completed: {success}/{len(tools)} succeeded")
    if failed:
        print(f"Failed: {', '.join(failed)}")
    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(main())
