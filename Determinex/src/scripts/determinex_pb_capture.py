#!/usr/bin/env python3
"""determinex_pb_capture — a pytest11 plugin (+ injector) that captures the diagnosis info
that eval.json normally truncates / that lives only in the ephemeral container:

  * COLLECTION errors (the tui_collection mystery: whole files showing not_run -> WHY they
    didn't collect, e.g. an import/fixture error pytest hit at collection time)
  * full (untruncated) failure tracebacks
  * the test function SOURCE for failing tests

It persists them through the ONLY reliable out-of-container channel: results.xml ->
PB eval.json. At session finish it appends synthetic <testcase classname="determinex.capture">
entries whose <system-out> holds the captured text, so they surface in eval.json's
test_results extra.text for offline diagnosis.

Inject like the hermetic/bidir plugins: write to /opt/determinex_capture + pip install (pytest11).
inject_capture(compile_sh_text) -> (new_text, changed).
"""

from __future__ import annotations

CAPTURE_PLUGIN = r"""# --- determinex capture: persist collection errors + full tracebacks + source ---
import inspect as _ci, os as _co, re as _cr
_CAP = []  # list of (kind, name, text)

def pytest_collectreport(report):
    # whole-file not_run is usually a collection failure here (import/fixture error)
    if getattr(report, "failed", False):
        try:
            _CAP.append(("COLLECT-ERROR", str(report.nodeid), str(report.longrepr)[:6000]))
        except Exception:
            pass

def pytest_runtest_logreport(report):
    if report.when == "call" and report.failed:
        nm = report.nodeid
        body = ""
        try:
            body += getattr(report, "longreprtext", "") or str(report.longrepr)
        except Exception:
            pass
        _CAP.append(("FAIL", nm, body[:6000]))

def _inject_into_results_xml():
    import glob as _cg
    cands = ["/workspace/eval/results.xml", "/workspace/results.xml"]
    cands += _cg.glob("/workspace/**/results.xml", recursive=True)
    path = next((p for p in cands if _co.path.exists(p)), None)
    if not path or not _CAP:
        return
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            c = f.read()
        def esc(s):
            return (s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))
        add = []
        for kind, name, text in _CAP[:400]:
            safe = _cr.sub(r"[^\w.\-]", "_", name)[:120]
            add.append(f'<testcase classname="determinex.capture" name="{kind}__{safe}">'
                       f'<system-out>{esc(text)}</system-out></testcase>')
        ins = c.rfind("</testsuite>")
        if ins >= 0:
            c = c[:ins] + "\n".join(add) + "\n" + c[ins:]
            with open(path, "w", encoding="utf-8") as f:
                f.write(c)
    except Exception:
        pass

def pytest_sessionfinish(session, exitstatus):
    _inject_into_results_xml()
def pytest_unconfigure(config):
    _inject_into_results_xml()
# --- end determinex capture ---
"""


def has_capture(text: str) -> bool:
    return "determinex_pb_capture" in text or "determinex capture: persist" in text


def inject_capture(compile_sh_text: str) -> tuple[str, bool]:
    """Append an install of the capture plugin (pytest11) to compile.sh. Idempotent."""
    if has_capture(compile_sh_text):
        return compile_sh_text, False
    block = (
        "\n# --- determinex capture plugin (collection errors + full tracebacks + source) ---\n"
        "mkdir -p /opt/determinex_capture\n"
        "cat > /opt/determinex_capture/determinex_pb_capture_plugin.py <<'DETERMINEX_CAP_EOF'\n"
        + CAPTURE_PLUGIN
        + "DETERMINEX_CAP_EOF\n"
        "cat > /opt/determinex_capture/setup.py <<'DETERMINEX_CAP_SETUP'\n"
        "from setuptools import setup\n"
        "setup(name='determinex_pb_capture', version='1.0', py_modules=['determinex_pb_capture_plugin'],\n"
        "      entry_points={'pytest11': ['determinex_pb_capture = determinex_pb_capture_plugin']})\n"
        "DETERMINEX_CAP_SETUP\n"
        "( cd /opt/determinex_capture && pip3 install -q . 2>/dev/null || pip install -q . 2>/dev/null || true )\n"
    )
    return compile_sh_text.rstrip() + "\n" + block, True


if __name__ == "__main__":
    import sys
    from pathlib import Path

    p = Path(sys.argv[1])
    new, ch = inject_capture(p.read_text(encoding="utf-8"))
    if ch:
        p.write_text(new, encoding="utf-8", newline="\n")
    print("injected" if ch else "already present")
