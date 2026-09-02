#!/usr/bin/env python3
"""Inject the determinex_subprocess_guard pytest11 plugin into per-tool compile.sh.

WHY: a hung tool invocation (e.g. a CLI reading stdin with no EOF) defeats PB's pytest-timeout
(`--timeout-method=signal` can raise in the test thread but canNOT kill the hung child) -> the eval
hangs and the tool can never be scored. The guard monkeypatches subprocess to kill the child's
group on any timeout/exit, so the hanging test fails fast and the eval COMPLETES. Installing it in
compile.sh (as a pytest11 plugin, like the bidir/hermetic plugins) makes the eval robust to hung
children for ANY tool -- the "any code" hang fix.

Idempotent (skips if already present). Usage:
  determinex_pb_inject_guard.py <tool>     # one tool (substring match ok)
  determinex_pb_inject_guard.py --all      # every per_tool_overrides tool
"""

from __future__ import annotations

import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
OVR = ROOT / "corpus" / "programbench" / "per_tool_overrides"
GUARD = (ROOT / "scripts" / "determinex_subprocess_guard.py").read_text(encoding="utf-8")
MARKER = "determinex_subproc_guard"

BLOCK = (
    "\n# --- determinex subprocess guard: a hung tool invocation can't hang the eval "
    "(pytest-timeout signal-method can't kill a hung child -- the lz4 hang) ---\n"
    "mkdir -p /opt/determinex_subproc_guard\n"
    "cat > /opt/determinex_subproc_guard/determinex_subprocess_guard.py <<'DETERMINEX_GUARD_EOF'\n"
    + GUARD.rstrip("\n")
    + "\nDETERMINEX_GUARD_EOF\n"
    "cat > /opt/determinex_subproc_guard/setup.py <<'DETERMINEX_GUARD_SETUP'\n"
    "from setuptools import setup\n"
    "setup(name='determinex_subprocess_guard', version='1.0', py_modules=['determinex_subprocess_guard'],\n"
    "      entry_points={'pytest11': ['determinex_subprocess_guard = determinex_subprocess_guard']})\n"
    "DETERMINEX_GUARD_SETUP\n"
    "( cd /opt/determinex_subproc_guard && pip3 install -q . 2>/dev/null || pip install -q . 2>/dev/null || true )\n"
    "# --- end determinex subprocess guard ---\n"
)


_START = "# --- determinex subprocess guard:"
_END = "# --- end determinex subprocess guard ---"


def inject(d: pathlib.Path) -> str:
    cs = d / "compile.sh"
    if not cs.exists():
        return "no-compile.sh"
    txt = cs.read_text(encoding="utf-8", errors="replace")
    if _START in txt and _END in txt:  # UPDATE the existing block in place (idempotent re-inject)
        i = txt.index(_START)
        j = txt.index(_END) + len(_END)
        new = txt[:i].rstrip("\n") + "\n" + BLOCK.strip("\n") + "\n" + txt[j:].lstrip("\n")
        if new == txt:
            return "already-current"
        cs.write_text(new, encoding="utf-8", newline="\n")
        return "updated"
    cs.write_text(txt.rstrip("\n") + "\n" + BLOCK, encoding="utf-8", newline="\n")
    return "injected"


def main() -> int:
    arg = sys.argv[1] if len(sys.argv) > 1 else "--all"
    if arg == "--all":
        res: dict[str, int] = {}
        for d in sorted(OVR.iterdir()):
            if d.is_dir():
                r = inject(d)
                res[r] = res.get(r, 0) + 1
        print("inject-all:", res)
        return 0
    d = OVR / arg
    if not d.is_dir():
        cands = [x for x in OVR.iterdir() if x.is_dir() and arg in x.name]
        if cands:
            d = cands[0]
    print(d.name, "->", inject(d))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
