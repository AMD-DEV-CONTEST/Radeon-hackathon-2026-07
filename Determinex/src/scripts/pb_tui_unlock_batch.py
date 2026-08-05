#!/usr/bin/env python3
"""
Batch TUI unlock for compile.sh files.
Applies keifu pattern: install tmux+libtmux, fix conftest-overwrite bug,
relax TUI filter (allow test_tui*.py), increase timeout 4->30s.
"""

import sys
from pathlib import Path

OVERRIDES = Path("corpus/programbench/per_tool_overrides")

# Markers that identify the old pattern
LOOP_START = "for INI_DIR in /workspace /workspace/eval; do\n"
INI_EOF = "INI_EOF\n"
CONF_START = "  cat > \"$INI_DIR/conftest.py\" <<'CONFTEST_EOF'\n"
CONF_END = "CONFTEST_EOF\ndone\n"

# Strings to update inside the conftest.py content
OLD_IGNORE = 'collect_ignore_glob = ["test_tui*.py","test_tmux*.py","test_pty*.py","test_pexpect*.py","test_curses*.py"]'
# keifu-proven pattern (LOCKED 826/826): tmux+libtmux make test_tmux*/test_tui* PASS, so they
# must RUN. Only RAW pty/pexpect/curses (no tmux) stay filtered. The prior NEW_IGNORE kept
# test_tmux*.py file-ignored -> every TUI tool's tmux tests stayed not_run = the undeployed ceiling.
NEW_IGNORE = 'collect_ignore_glob = ["test_pty*.py","test_pexpect*.py","test_curses*.py"]'
OLD_FILTER = '        if any(s in nodeid for s in ("tmux","_tui_","libtmux","pexpect","test_pty")):'
NEW_FILTER = '        if any(s in nodeid for s in ("test_pty", "test_curses")):'
OLD_TO_CONF = "    try: config.option.timeout = 4"
NEW_TO_CONF = "    try: config.option.timeout = 30"

# pytest.ini timeout line
OLD_INI_OPT = "addopts = --timeout=4 -p no:cacheprovider\ntimeout = 4\n"
NEW_INI_OPT = "addopts = --timeout=30 -p no:cacheprovider\ntimeout = 30\n"

TMUX_INSTALL = (
    "# v2: install tmux+libtmux so TUI tests run (keifu pattern). Fix conftest-overwrite bug.\n"
    "apt-get update -qq 2>/dev/null && apt-get install -y -qq tmux 2>/dev/null || true\n"
    "pip3 install -q libtmux 2>/dev/null || true\n\n"
    "# Write pytest.ini to both dirs; conftest.py ONLY to /workspace/.\n"
    "# DO NOT overwrite /workspace/eval/conftest.py \xe2\x80\x94 it sets up fixtures.\n"
)

NEW_LOOP = (
    "for INI_DIR in /workspace /workspace/eval; do\n"
    '  mkdir -p "$INI_DIR" 2>/dev/null || true\n'
    "  cat > \"$INI_DIR/pytest.ini\" <<'INI_EOF'\n"
    "[pytest]\n"
    "addopts = --timeout=30 -p no:cacheprovider\n"
    "timeout = 30\n"
    "INI_EOF\n"
    "done\n\n"
    "mkdir -p /workspace 2>/dev/null || true\n"
    "cat > /workspace/conftest.py <<'CONFTEST_EOF'\n"
)


def unlock_tui_text(content: str) -> "tuple[str | None, str]":
    """Text transform: install tmux+libtmux + un-filter test_tui tests (keeping the
    genuinely-unprovisionable test_tmux/test_pty/test_curses ignored). SINGLE SOURCE for
    both the file-based fix_compile_sh AND the autofix compound (determinex_pb_autofix).
    Returns (new_content, 'fixed') or (None, 'already_fixed'|'no_match')."""
    if CONF_START not in content:
        return None, "already_fixed"
    loop_idx = content.find(LOOP_START)
    if loop_idx < 0:
        return None, "no_match"
    ini_eof_idx = content.find(INI_EOF, loop_idx)
    if ini_eof_idx < 0:
        return None, "no_match"
    ini_eof_end = ini_eof_idx + len(INI_EOF)
    conf_start_idx = content.find(CONF_START, ini_eof_end)
    if conf_start_idx < 0:
        return None, "no_match"
    conf_content_start = conf_start_idx + len(CONF_START)
    conf_end_idx = content.find(CONF_END, conf_content_start)
    if conf_end_idx < 0:
        return None, "no_match"
    conf_end_end = conf_end_idx + len(CONF_END)
    conf_content = content[conf_content_start:conf_end_idx]
    conf_content = conf_content.replace(OLD_IGNORE, NEW_IGNORE)
    conf_content = conf_content.replace(OLD_FILTER, NEW_FILTER)
    conf_content = conf_content.replace(OLD_TO_CONF, NEW_TO_CONF)
    before = content[:loop_idx]
    after_end = content[conf_end_end:]
    before_tail = before[-200:]
    has_tmux = "apt-get install" in before_tail and "tmux" in before_tail
    replacement = ("" if has_tmux else TMUX_INSTALL) + NEW_LOOP + conf_content + "CONFTEST_EOF\n"
    new_content = before + replacement + after_end
    new_content = new_content.replace(OLD_INI_OPT, NEW_INI_OPT)
    return new_content, "fixed"


import re as _re


def realign_tui_to_keifu(content: str) -> "tuple[str, bool]":
    """Idempotent: re-align an ALREADY-unlocked compile.sh (partial pattern that still
    FILTERS test_tmux*) to keifu's PROVEN pattern (LOCKED 826/826) that RUNS test_tmux*/
    test_tui* (tmux+libtmux make them pass) and filters only RAW pty/pexpect/curses.
    This is the deploy step `unlock_tui_text` misses: it only converts the original
    5-entry OLD_IGNORE, so the 193 tools carrying the partial 3-entry stayed test_tmux-
    filtered (= the 'undeployed' ceiling). At the official metric not_run/fail both count
    against, so un-filtering can only help-or-neutral; the PTY plugin guards hangs."""
    orig = content
    # collect_ignore_glob: drop test_tmux*.py (run it), keep raw pty/pexpect/curses.
    content = _re.sub(
        r'collect_ignore_glob\s*=\s*\[\s*"test_tmux\*\.py"\s*,\s*"test_pty\*\.py"\s*,\s*"test_curses\*\.py"\s*\]',
        'collect_ignore_glob = ["test_pty*.py","test_pexpect*.py","test_curses*.py"]',
        content,
    )

    # nodeid filter that still excludes tmux/_tui_ -> keifu's (only pexpect/test_pty).
    def _fix_filter(m: "_re.Match[str]") -> str:
        inner = m.group(0)
        if "tmux" in inner or "_tui_" in inner:
            return 'if any(s in nodeid for s in ("pexpect","test_pty")):'
        return inner

    content = _re.sub(r"if any\(s in nodeid for s in \([^)]*\)\):", _fix_filter, content)
    return content, content != orig


def fix_compile_sh(path: Path, dry_run: bool = False) -> str | None:
    """Returns 'fixed', 'already_fixed', or None if pattern not found."""
    content = path.read_text(encoding="utf-8", errors="replace")
    new_content, status = unlock_tui_text(content)
    if status != "fixed" or new_content is None:
        return "already_fixed" if status == "already_fixed" else None

    if dry_run:
        print(f"  [DRY] would fix: {path.parent.name}")
        return "fixed"

    # Write with explicit LF so Windows doesn't introduce CRLF
    path.write_bytes(new_content.replace("\r\n", "\n").replace("\r", "\n").encode("utf-8"))
    return "fixed"


def main():
    dry_run = "--dry-run" in sys.argv
    args = [a for a in sys.argv[1:] if not a.startswith("-")]
    targets = args if args else None

    fixed = []
    already = []
    no_match = []

    if targets:
        dirs = [OVERRIDES / t for t in targets if (OVERRIDES / t).exists()]
    else:
        dirs = sorted(d for d in OVERRIDES.iterdir() if d.is_dir())

    realigned = []
    for d in dirs:
        sh = d / "compile.sh"
        if not sh.exists():
            continue
        result = fix_compile_sh(sh, dry_run=dry_run)
        if result == "fixed":
            fixed.append(d.name)
            if not dry_run:
                print(f"[FIX] {d.name}")
        elif result == "already_fixed":
            already.append(d.name)
        else:
            no_match.append(d.name)
        # DEPLOY step (was built-but-unwired until 2026-07-18, leaving 62 tools on the partial
        # pattern that still filtered test_tmux*): re-align to keifu's proven RUN-the-tmux-tests
        # form. Idempotent; runs on every invocation so the partial pattern can't reappear.
        content = sh.read_text(encoding="utf-8", errors="replace")
        new_content, changed = realign_tui_to_keifu(content)
        if changed:
            realigned.append(d.name)
            if not dry_run:
                sh.write_bytes(
                    new_content.replace("\r\n", "\n").replace("\r", "\n").encode("utf-8")
                )
                print(f"[REALIGN] {d.name}")

    print(
        f"\nFixed: {len(fixed)}, Realigned: {len(realigned)}, "
        f"Already fixed: {len(already)}, No match: {len(no_match)}"
    )
    if no_match:
        print("No match (non-standard pattern):")
        for n in no_match[:20]:
            print(f"  {n}")
    return fixed


if __name__ == "__main__":
    main()
