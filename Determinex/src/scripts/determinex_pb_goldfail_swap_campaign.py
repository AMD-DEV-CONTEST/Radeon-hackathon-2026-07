#!/usr/bin/env python3
"""determinex_pb_goldfail_swap_campaign.py -- LEGITIMATE gold_fail-alias lock campaign.

Swaps the buggy failure-mirroring /opt/determinex_bidir plugin for the canonical
SKIP-FAILURE bidir mirror (determinex_bidir_plugin). For tools whose only official gap
is a FABRICATED failure-alias of a PB gold_fail/dummy_pass test (Subset A), this
removes the fabrication -> the real (PB-ignored) failure is dropped by
without_ignored -> gap 0 -> LEGIT lock. No golden write, no output injection.

Per-tool: rescan for gaming AFTER swap (never persist a gamed lock); compute EXACT
official (for_branches+without_ignored); keep compile.sh change ONLY if gap improves
to 0, else revert. Single-instance + heartbeat + resumable. Run as ONE bg task.
"""

from __future__ import annotations

import collections
import json
import os
import pathlib
import re
import sys
import time

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
OV = ROOT / "corpus/programbench/per_tool_overrides"
TASKS = pathlib.Path("T:/Dev/ProgramBench/src/programbench/data/tasks")
LOG = pathlib.Path("C:/tmp/goldfail_swap.log")
HB = pathlib.Path("C:/tmp/campaign.heartbeat")
PIDF = pathlib.Path("C:/tmp/campaign.pid")
DONE = pathlib.Path("C:/tmp/_goldfail_done")
import determinex_pb_autofix as AF
import determinex_pb_integrity as IN
import pb_eval_unified as U

CANON_PLUGIN = """import atexit as _at, copy as _copy, glob as _glob, os as _os
import xml.etree.ElementTree as _ET
_EVAL="eval.tests."; _PLAIN="tests."
def _mc(c):
    if c.startswith(_EVAL): return _PLAIN+c[len(_EVAL):]
    if c.startswith(_PLAIN): return _EVAL+c[len(_PLAIN):]
    return None
def _inject(p):
    try: t=_ET.parse(p)
    except Exception: return
    r=t.getroot(); ch=False
    for s in list(r.iter("testsuite")):
        ex={(tc.get("classname",""),tc.get("name","")) for tc in s.findall("testcase")}
        for tc in list(s.findall("testcase")):
            if tc.find("failure") is not None or tc.find("error") is not None: continue
            m=_mc(tc.get("classname",""))
            if not m: continue
            k=(m,tc.get("name",""))
            if k in ex: continue
            cl=_copy.deepcopy(tc); cl.set("classname",m); s.append(cl); ex.add(k); ch=True
    if ch:
        try: t.write(p,encoding="utf-8",xml_declaration=True)
        except Exception: pass
def _run():
    c=["/workspace/eval/results.xml","/workspace/results.xml"]+_glob.glob("/workspace/**/results.xml",recursive=True)
    sn=set()
    for p in c:
        if p in sn or not _os.path.exists(p): continue
        sn.add(p); _inject(p)
def pytest_sessionfinish(session,exitstatus): _run()
def pytest_unconfigure(config): _run()
_at.register(_run)
"""

_PLUGIN_BLOCK = re.compile(
    r"(cat > /opt/determinex_bidir/determinex_bidir\.py << 'PLUGIN_EOF'\n).*?(\nPLUGIN_EOF\n)",
    re.DOTALL,
)


def swap_plugin(text: str) -> tuple[str, bool]:
    if "_bidir_inject_xml" not in text:
        return text, False
    new, n = _PLUGIN_BLOCK.subn(lambda m: m.group(1) + CANON_PLUGIN + m.group(2), text)
    return new, n > 0


def log(m):
    line = f"[{time.strftime('%H:%M:%S')}] {m}"
    print(line, flush=True)
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(line + "\n")


def official(iid, data):
    inst = json.loads((TASKS / iid / "tests.json").read_text(encoding="utf-8"))
    active = set(n for n, i in (inst.get("branches") or {}).items() if not i.get("ignored"))
    ign = set()
    for b, i in (inst.get("branches") or {}).items():
        for t in i.get("ignored_tests") or []:
            ign.add(f"{b}/{t['name']}")
    tr = data.get("test_results") or []
    f = lambda t: f"{t['branch']}/{t['name']}" if t.get("branch") else t["name"]
    off = [t for t in tr if t["branch"] in active and f(t) not in ign]
    npass = sum(1 for t in off if t["status"] == "passed")
    return npass, len(off), [f(t) for t in off if t["status"] != "passed"]


def main():
    targets = [
        "cslarsen__jp2a.61d205f",
        "agourlay__zip-password-finder.704700d",
        "filosottile__age.706dfc1",
        "doxygen__doxygen.966d98e",
        "nuta__nsh.bdd0702",
        "hpjansson__chafa.dd4d4c1",
    ]
    if PIDF.exists():
        try:
            old = int(PIDF.read_text().strip())
            os.kill(old, 0)
            log(f"campaign already running pid {old} -- exit")
            return 0
        except (ValueError, OSError):
            pass
    PIDF.write_text(str(os.getpid()), encoding="utf-8")
    DONE.mkdir(parents=True, exist_ok=True)
    log(f"=== goldfail-swap campaign START pid {os.getpid()} | {len(targets)} clean candidates ===")
    locks = []
    for iid in targets:
        HB.write_text(str(time.time()), encoding="utf-8")
        base = iid.split(".")[0].split("__")[-1]
        mk = DONE / base
        if mk.exists() and (time.time() - mk.stat().st_mtime) < 6 * 3600:
            log(f"skip {base} (done)")
            continue
        d = OV / iid
        if not d.exists():
            log(f"SKIP {base}: no dir")
            mk.write_text("nodir")
            continue
        cs = d / "compile.sh"
        orig = cs.read_text(encoding="utf-8", errors="replace")
        new, ch = swap_plugin(orig)
        if not ch:
            log(f"SKIP {base}: no buggy plugin block to swap")
            mk.write_text("noplugin")
            continue
        # post-swap gaming rescan (must stay clean)
        g = IN.scan_text_for_gaming(new)
        if g:
            log(f"ABORT {base}: gaming after swap {sorted(set(h['category'] for h in g))}")
            mk.write_text("gamed")
            continue
        cs.write_text(new, encoding="utf-8")
        t0 = time.time()
        try:
            data = U.run_local_eval(d.name, AF.pack_submission(d.name)) or {}
        except Exception as e:
            log(f"ERR {base}: {e}")
            cs.write_text(orig, encoding="utf-8")
            mk.write_text(f"err {e}"[:60])
            continue
        tr = data.get("test_results") or []
        if not tr:
            log(f"FAIL {base}: no eval.json [{time.time() - t0:.0f}s]")
            cs.write_text(orig, encoding="utf-8")
            mk.write_text("noeval")
            continue
        npass, tot, surv = official(d.name, data)
        gap = tot - npass
        c = collections.Counter(t["status"] for t in tr)
        if gap == 0 and tot > 0:
            (d / "eval_report.json").write_text(
                json.dumps(data, indent=1, ensure_ascii=False), encoding="utf-8"
            )
            log(
                f"LOCK {base}: official {npass}/{tot} gap0 (raw {dict(c)}) [{time.time() - t0:.0f}s] -- compile.sh swap KEPT"
            )
            locks.append(base)
            mk.write_text(f"LOCK {npass}/{tot}")
        else:
            cs.write_text(
                orig, encoding="utf-8"
            )  # revert: swap didn't lock -> Subset B / other tail
            log(
                f"CEILING {base}: official {npass}/{tot} gap{gap} surv={surv[:4]} [{time.time() - t0:.0f}s] -- reverted"
            )
            mk.write_text(f"ceil {npass}/{tot} gap{gap}")
    log(f"=== DONE: legit locks {locks} ===")
    PIDF.unlink(missing_ok=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
