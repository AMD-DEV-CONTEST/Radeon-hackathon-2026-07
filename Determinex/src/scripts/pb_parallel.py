#!/usr/bin/env python3
"""pb_parallel — run N PB evals concurrently on one box (the throughput unlock).

The box is 8-core but a serial eval uses ~3 -> ~60% idle. The prior parallel attempt
collided because broad `docker kill`/`image prune` during one eval clobbered another's
containers. This runner is collision-safe:
  * each slot evals a DIFFERENT factory dir (PB names its own task containers per-slug)
  * NO global docker prune/kill DURING evals -- prune only once, when ALL slots are idle
  * CPU split: PROGRAMBENCH_DOCKER_CPUS per slot (default 2) * slots <= cores

Reads a queue file (slug:factory_dir:author per line), runs --slots at a time, writes
each tool's score to /tmp/grind/_grind.log as `[parallel] <slug>: P/T = X% [verdict]`.

Usage (on the box):  python3 pb_parallel.py <queue_file> --slots 3 --cpus 2
"""

from __future__ import annotations

import argparse
import glob
import json
import os
import subprocess
import sys
import time
from pathlib import Path

PB = "/root/ProgramBench/.venv/bin/programbench"
ROOT = "/root/citadel-programbench"
LOG = "/tmp/grind/_grind.log"


def log(msg: str) -> None:
    with open(LOG, "a") as f:
        f.write(msg + "\n")
    print(msg, flush=True)


def score(slug: str, fdir: str) -> str:
    cands = glob.glob(f"{ROOT}/{fdir}/**/*.eval.json", recursive=True)
    if not cands:
        return f"[parallel] {slug}: NO eval.json"
    try:
        d = json.load(open(cands[0]))
        tr = d.get("test_results") or d.get("results", {}).get("test_results") or []
        p = sum(1 for x in tr if x.get("status") == "passed")
        t = len(tr)
        rc = sum(1 for x in tr if "127" in str((x.get("extra") or {}).get("text", ""))[:150])
        pct = 100 * p / t if t else 0
        v = "LOCK" if (t and p == t) else ("TARGET" if pct >= 90 else "more")
        return f"[parallel] {slug}: {p}/{t} = {pct:.1f}% [{v}] rc127={rc}"
    except Exception as e:
        return f"[parallel] {slug}: SCORE-ERR {e}"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("queue")
    ap.add_argument("--slots", type=int, default=3)
    ap.add_argument("--cpus", type=int, default=2)
    args = ap.parse_args()
    jobs = []
    for ln in Path(args.queue).read_text().splitlines():
        ln = ln.strip()
        if not ln or ln.startswith("#"):
            continue
        parts = ln.split(":")
        if len(parts) >= 3:
            jobs.append((parts[0], parts[1], parts[2]))
    # de-dup preserving order
    seen = set()
    jobs = [j for j in jobs if not (j[0] in seen or seen.add(j[0]))]
    log(
        f"[parallel] start: {len(jobs)} tools, {args.slots} slots x {args.cpus} cpus  {time.strftime('%H:%M:%S')}"
    )
    running = {}  # proc -> (slug, fdir, start)
    qi = 0
    launched = set(j[0] for j in jobs)
    qpath = Path(args.queue)

    def _reread():
        # CONTINUOUS feeder: re-read the queue file for NEW entries appended since start,
        # so the box stays full as I top up the queue. Skips already-launched slugs.
        nonlocal jobs
        try:
            for ln in qpath.read_text().splitlines():
                ln = ln.strip()
                if not ln or ln.startswith("#"):
                    continue
                p = ln.split(":")
                if len(p) >= 3 and p[0] not in launched:
                    jobs.append((p[0], p[1], p[2]))
                    launched.add(p[0])
        except Exception:
            pass

    while qi < len(jobs) or running:
        _reread()
        # fill slots
        while len(running) < args.slots and qi < len(jobs):
            slug, fdir, author = jobs[qi]
            qi += 1
            env = dict(os.environ, PYTHONUTF8="1", PROGRAMBENCH_DOCKER_CPUS=str(args.cpus))
            lf = open(f"/tmp/grind/{slug}.par.log", "w")
            p = subprocess.Popen(
                [PB, "eval", f"{ROOT}/{fdir}", "--filter", author, "--force"],
                stdout=lf,
                stderr=subprocess.STDOUT,
                env=env,
            )
            running[p] = (slug, fdir, time.time())
            log(
                f"[parallel] launched {slug} (slot {len(running)}/{args.slots})  {time.strftime('%H:%M:%S')}"
            )
        # reap finished
        done = [p for p in running if p.poll() is not None]
        for p in done:
            slug, fdir, st = running.pop(p)
            log(score(slug, fdir) + f"  ({int(time.time() - st)}s)")
        if not done:
            time.sleep(20)
    # safe: prune only now that ALL slots are idle
    subprocess.run(["docker", "image", "prune", "-f"], capture_output=True)
    log(f"[parallel] ALL DONE {time.strftime('%H:%M:%S')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
