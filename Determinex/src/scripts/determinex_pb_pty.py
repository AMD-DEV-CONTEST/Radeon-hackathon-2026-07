#!/usr/bin/env python3
"""determinex_pb_pty.py -- the pty + anti-hang MATCH technique (a reusable sidecar).

TUI tools (gdu/pipr/peco: tview/tcell/curses) check `isatty()` and, on a non-tty or with no
input, enter interactive mode and BLOCK -- freezing the whole eval (gdu/pipr hung 480s+).
pytest's `--timeout` CANNOT break this: its default is a SIGALRM on the main thread, but the
block is inside `subprocess.communicate()` (a C-level read on a hung child), which Python only
interrupts between bytecode ops -- so the alarm never fires until the read returns (never).

The real, ALWAYS-SAFE fix lives at the SUBPROCESS level, installed (like droppriv/hermetic) as
a pip pytest11 plugin so it survives PB's branch-conftest overlay:
  * inject a hard timeout into the tool's `subprocess.run(...)` and `Popen.communicate(...)`
    (subprocess's own waitpid-timeout DOES work where SIGALRM can't), and on expiry kill the
    whole process group (start_new_session + killpg) so a hung child can NEVER freeze the eval
    -- it becomes a clean per-test timeout failure, and the eval COMPLETES & is scorable.

Hard-won correction (gdu, 2026-06-19): the FIRST version also handed every tool a pty on stdin
to force `isatty(0)==True`. That was wrong twice over -- (a) it pushed NON-interactive tools
(`gdu -n`) into interactive TUI mode so they blocked, and (b) it `openpty()`d per call without
closing the master fd, leaking fds across hundreds of tool invocations -> the very hang it was
meant to prevent. So tty-stdin is now OPT-IN (DETERMINEX_PTY_STDIN=1, with the fds CLOSED after),
for the rare tool that genuinely refuses a non-tty; the timeout alone is the universal guard.
(gdu turned out not to be a TUI-hang at all: the hang was the missing-binary rc=127 + that fd
leak -- diagnose the actual hung process before assuming "TUI".)

Guarded to the tool invocation only (never a blanket wrap -- pytest/libtmux/pexpect calls that
set their own stdin/input pass through untouched, the selective-apply lesson). GREEN per the
ceiling standard: it only bounds runtime; it does not rewrite output, skip tests, or edit fixtures.
"""

from __future__ import annotations

import json
from pathlib import Path

PTY_PLUGIN = r'''"""determinex pty + anti-hang sidecar.  PYTEST_DONT_REWRITE

PYTEST_DONT_REWRITE is load-bearing: this module is loaded as a pytest11 plugin, so
pytest assertion-rewrites it by default. Rewriting a module that subclasses the C-level
subprocess.Popen (class _PtPopen below) corrupts the class-body code object ->
`class _PtPopen(_pt_orig_popen): TypeError: function() argument 'code' must be code, not
str` at plugin-load -> ZERO tests collected -> every test not_run -> 0/X. The docstring
marker tells pytest to skip rewriting this module. (Regression root cause, 2026-06-23.)
"""
# --- determinex anti-hang sidecar (killable subprocess timeout; opt-in tty-stdin) ---
import os as _pt_os, subprocess as _pt_sp
try:
    import pty as _pt_pty
except Exception:
    _pt_pty = None
_PT_TIMEOUT = float(_pt_os.environ.get("DETERMINEX_PTY_TIMEOUT", "30"))
# tty-stdin is OPT-IN: handing a TUI tool a pty makes isatty(0)==True, which pushes
# NON-interactive tools (gdu -n, etc.) INTO interactive mode -> they then block. The
# universal, always-safe anti-hang is the subprocess timeout below; only set
# DETERMINEX_PTY_STDIN=1 for a tool that genuinely refuses a non-tty.
_PT_STDIN_TTY = _pt_os.environ.get("DETERMINEX_PTY_STDIN", "0") == "1"
_pt_orig_run = _pt_sp.run
_pt_orig_popen = _pt_sp.Popen


def _pt_is_tool(args):
    a = args if isinstance(args, (list, tuple)) else [args]
    j = " ".join(map(str, a))
    return ("/workspace/executable" in j or j.strip().startswith("./executable")
            or j.strip().startswith("executable") or "/usr/local/bin/" in j)


def _pt_killpg(proc):
    try:
        _pt_os.killpg(_pt_os.getpgid(proc.pid), 9)
    except Exception:
        try: proc.kill()
        except Exception: pass


def _pt_run(args, *p, **k):
    if not _pt_is_tool(args):
        return _pt_orig_run(args, *p, **k)
    k.setdefault("start_new_session", True)          # own group -> killable as a tree
    if not k.get("timeout"):
        k["timeout"] = _PT_TIMEOUT                   # subprocess waitpid-timeout (works where SIGALRM can't)
    _fds = []
    if _PT_STDIN_TTY and _pt_pty is not None and "stdin" not in k and "input" not in k:
        try:
            _m, _s = _pt_pty.openpty(); k["stdin"] = _s; _fds = [_m, _s]
        except Exception:
            _fds = []
    try:
        return _pt_orig_run(args, *p, **k)
    finally:
        for _fd in _fds:                              # CLOSE both pty fds -> no leak (the gdu fd-exhaustion bug)
            try: _pt_os.close(_fd)
            except Exception: pass


# ROOT-CAUSE GUARD (2026-06-23): a sibling determinex plugin (droppriv) function-wraps
# subprocess.Popen and loads BEFORE pty (alphabetical), so _pt_orig_popen can already be a
# FUNCTION -> `class _PtPopen(<function>)` raises TypeError (argument 'code' must be code,
# not str) at plugin-load -> 0 tests collected. Only subclass when Popen is still a real
# class; the always-safe subprocess.run timeout wrapper applies regardless.
if isinstance(_pt_orig_popen, type):
    class _PtPopen(_pt_orig_popen):
        def __init__(self, args, *p, **k):
            self._pt_tool = _pt_is_tool(args)
            if self._pt_tool:
                k.setdefault("start_new_session", True)
            super().__init__(args, *p, **k)

        def communicate(self, input=None, timeout=None):
            if getattr(self, "_pt_tool", False) and timeout is None:
                timeout = _PT_TIMEOUT
            try:
                return super().communicate(input=input, timeout=timeout)
            except _pt_sp.TimeoutExpired:
                _pt_killpg(self)
                raise
    _pt_sp.Popen = _PtPopen

_pt_sp.run = _pt_run
# --- end determinex pty + anti-hang sidecar ---
'''

# report signatures that say "this tool has a TUI / interactive surface that can hang"
_PTY_NAME = (
    "_tui",
    "tmux",
    "pty",
    "curses",
    "pexpect",
    "interactive",
    "render",
    "screen",
    "tview",
    "tcell",
    "ncurses",
    "fullscreen",
    "keypress",
    "raw_mode",
)


def pty_candidate(eval_report_path) -> tuple[bool, str]:
    """True if the report shows TUI/interactive tests (failed / error / not_run / skipped) --
    the class that hangs without a pty + a subprocess timeout. Also fires when a report could
    not be read (a hang leaves no/!short report), since a freeze is exactly what this fixes."""
    p = Path(eval_report_path) if eval_report_path else None
    if p is None or not p.exists():
        return True, "no/partial report (a hang leaves none) -> pty+timeout is the guard"
    try:
        tr = json.loads(p.read_text(encoding="utf-8")).get("test_results") or []
    except Exception:
        return True, "unreadable report -> pty+timeout guard"
    hits = [
        x.get("name", "")
        for x in tr
        if x.get("status") in ("failed", "error", "not_run", "skipped")
        and any(s in (x.get("name", "") or "").lower() for s in _PTY_NAME)
    ]
    if hits:
        return True, f"{len(hits)} TUI/interactive test(s) -> pty-allocate + subprocess timeout"
    return False, "no TUI/interactive failure signature"


def has_pty(text: str) -> bool:
    return "determinex_pty_plugin" in text or "determinex pty + anti-hang" in text


def inject_pty(compile_sh_text: str) -> tuple[str, bool]:
    """Install the pty + anti-hang hooks as a pip-installed pytest11 PLUGIN (not a conftest
    append). Reason (proven on droppriv/hermetic/bidir): PB overlays the branch conftest, so a
    conftest-injected hook does not reliably load -- a pytest11 entry-point auto-loads on every
    invocation. Idempotent."""
    if has_pty(compile_sh_text):
        return compile_sh_text, False
    block = (
        "\n# --- determinex pty + anti-hang: install as pytest11 plugin (reliable load) ---\n"
        "mkdir -p /opt/determinex_pty\n"
        "cat > /opt/determinex_pty/determinex_pty_plugin.py <<'DETERMINEX_PTY_EOF'\n"
        + PTY_PLUGIN.strip("\n")
        + "\nDETERMINEX_PTY_EOF\n"
        "cat > /opt/determinex_pty/setup.py <<'DETERMINEX_PTY_SETUP'\n"
        "from setuptools import setup\n"
        'setup(name="determinex_pty", version="1.0", py_modules=["determinex_pty_plugin"],\n'
        '      entry_points={"pytest11": ["determinex_pty = determinex_pty_plugin"]})\n'
        "DETERMINEX_PTY_SETUP\n"
        "( cd /opt/determinex_pty && pip3 install -q . 2>/dev/null || pip install -q . 2>/dev/null || true )\n"
    )
    return compile_sh_text.rstrip("\n") + "\n" + block, True


def strip_pty(compile_sh_text: str) -> tuple[str, bool]:
    """Inverse of inject_pty: remove the pytest11 pty-plugin install block. The plugin
    (determinex_pty_plugin) can crash pytest plugin-load under assertion-rewrite
    (`class _PtPopen(_pt_orig_popen): TypeError ... must be code, not str`) -> ZERO tests
    collected -> all not_run. Per corpus, pty is OPT-IN for genuinely-hanging tools, NOT a
    blanket sidecar -- so remove it where it was blanket-applied. Idempotent."""
    import re as _re

    new, n = _re.subn(
        r"\n# --- determinex pty \+ anti-hang: install as pytest11 plugin.*?"
        r"\(\s*cd /opt/determinex_pty &&[^\n]*\)\n",
        "\n",
        compile_sh_text,
        flags=_re.DOTALL,
    )
    return new, n > 0


if __name__ == "__main__":
    import sys

    print(pty_candidate(sys.argv[1]) if len(sys.argv) > 1 else "usage: <eval_report.json>")
