#!/usr/bin/env python3
"""determinex_pb_reeval_campaign.py -- re-eval the near-lock tail with the FIXED conftest.

Corpus: highest LOCK-yield = the ~95-99% near-lock tail. The bidir-MIRROR strip made LOCAL
evals accurate, so re-evaling reveals TRUE official scores (was understated). Eval runs in this
(plain) python via run_local_eval; OFFICIAL scoring shells out to `programbench info` (needs the
PB uv env). Sequential + logged so it's interrupt/resume safe.

Usage:
  python scripts/determinex_pb_reeval_campaign.py [--max N] [--targets FILE]
"""

from __future__ import annotations

import collections
import json
import pathlib
import re
import subprocess
import sys
import time

ROOT = pathlib.Path(__file__).resolve().parent.parent
OV = ROOT / "corpus" / "programbench" / "per_tool_overrides"
PB_LOCAL = pathlib.Path("T:/Dev/ProgramBench")
LOG = pathlib.Path("C:/tmp/reeval_campaign.log")
RUNROOT = pathlib.Path("C:/tmp/_camp_runs")
sys.path.insert(0, str(ROOT / "scripts"))


def log(msg: str) -> None:
    line = f"[{time.strftime('%H:%M:%S')}] {msg}"
    print(line, flush=True)
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with open(LOG, "a", encoding="utf-8") as fh:
        fh.write(line + "\n")


def official_score(iid: str, eval_json: pathlib.Path) -> tuple[int, int] | None:
    """Run `programbench info` on a one-tool run dir; return (n_resolved, len) parsed from output."""
    run = RUNROOT / iid
    run.mkdir(parents=True, exist_ok=True)
    dest = run.parent / iid / f"{iid}.eval.json"
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(eval_json.read_text(encoding="utf-8"), encoding="utf-8")
    try:
        r = subprocess.run(
            ["uv", "run", "programbench", "info", str(run.parent)],
            cwd=str(PB_LOCAL),
            capture_output=True,
            text=True,
            timeout=300,
            env={**__import__("os").environ, "PYTHONUTF8": "1"},
        )
        # parse "<iid>   <score>" — but score is a rounded %; we want exact gap, so recompute
    except Exception as e:
        log(f"  info-err {iid}: {e}")
        return None
    # exact: re-derive from the eval.json via the same drop rules is hard here; use rounded score
    m = re.search(re.escape(iid) + r"\s+(\d+)", r.stdout)
    return (int(m.group(1)), 100) if m else None


def main() -> int:
    args = sys.argv[1:]
    max_n = int(args[args.index("--max") + 1]) if "--max" in args else 8
    tf = args[args.index("--targets") + 1] if "--targets" in args else "C:/tmp/reeval_targets.txt"
    targets = [
        l.strip() for l in pathlib.Path(tf).read_text(encoding="utf-8").splitlines() if l.strip()
    ]
    import os

    # single-instance guard: if a live campaign already owns the PID file, exit (no duplicates)
    pidf = pathlib.Path("C:/tmp/campaign.pid")
    if pidf.exists():
        try:
            old = int(pidf.read_text().strip())
            os.kill(old, 0)  # raises if not alive
            log(f"campaign already running (pid {old}) -- exiting to avoid duplicate")
            return 0
        except (ValueError, OSError):
            pass  # stale pid, take over
    pidf.write_text(str(os.getpid()), encoding="utf-8")
    import determinex_pb_autofix as AF
    import pb_eval_unified as U

    DONE = pathlib.Path("C:/tmp/_camp_done")
    DONE.mkdir(parents=True, exist_ok=True)
    log(
        f"=== re-eval campaign START: {len(targets)} targets, running top {max_n} (pid {os.getpid()}) ==="
    )
    locks, improved, done = [], [], []
    hb = pathlib.Path("C:/tmp/campaign.heartbeat")
    for iid in targets[:max_n]:
        hb.write_text(str(time.time()), encoding="utf-8")  # mtime liveness (PID-proof)
        base = iid.split(".")[0].split("__")[-1]
        # RESUMABLE: skip a tool already done this run (watchdog-restart safe)
        marker = DONE / base
        if marker.exists() and (time.time() - marker.stat().st_mtime) < 6 * 3600:
            continue
        d = OV / iid
        if not d.exists():
            cands = [
                x for x in OV.iterdir() if x.is_dir() and x.name.split(".")[0] == iid.split(".")[0]
            ]
            if not cands:
                log(f"SKIP {base}: no override dir")
                continue
            d, iid = cands[0], cands[0].name
        t0 = time.time()
        try:
            data = U.run_local_eval(d.name, AF.pack_submission(d.name)) or {}
        except Exception as e:
            log(f"ERR {base}: {e}")
            marker.write_text(f"ERR {e}"[:80], encoding="utf-8")
            continue
        tr = data.get("test_results") or []
        if not tr:
            log(f"FAIL {base}: no eval.json (build/eval failed) [{time.time() - t0:.0f}s]")
            marker.write_text("FAIL no-eval", encoding="utf-8")
            continue
        (d / "eval_report.json").write_text(
            json.dumps(data, indent=1, ensure_ascii=False), encoding="utf-8"
        )
        c = collections.Counter(r.get("status") for r in tr)
        raw_p, raw_t = c.get("passed", 0), len(tr)
        ej = d / "eval_report.json"
        sc = official_score(d.name, ej)
        scr = f"official~{sc[0]}%" if sc else "official~?"
        status = "LOCK?" if sc and sc[0] >= 100 else "scored"
        log(f"{status} {base}: raw {raw_p}/{raw_t} ({dict(c)}) -> {scr} [{time.time() - t0:.0f}s]")
        marker.write_text(f"{raw_p}/{raw_t} {scr}", encoding="utf-8")  # resumable done-marker
        done.append(base)
        if sc and sc[0] >= 100:
            locks.append(base)
    log(f"=== DONE: scored {len(done)} | LOCK-candidates {locks} ===")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
