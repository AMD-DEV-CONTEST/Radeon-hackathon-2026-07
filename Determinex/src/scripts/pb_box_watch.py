#!/usr/bin/env python3
"""Box watchdog: memory / disk / cloud spend / model activity digest.

Runs on the Hetzner eval box every 15 min (systemd timer determinex-pb-watch).
Appends one block per run to /root/pb_watch.log; WARN lines are grep-able.
The 15Gi box starves evals into all-not_run garbage below ~1.5G available
(see memory: box-memory-constraint), and HF cloud spend was previously
untracked — this is the single place both become observable.
"""

from __future__ import annotations

import datetime as dt
import json
import os
import shutil
import subprocess

LOG = "/root/pb_watch.log"
LEDGER = "/root/Citadel/logs/api_ledger/providers.jsonl"
EVENTS = "/root/Citadel/logs/pb_churn_events.jsonl"
REIMPL = "/root/Citadel/logs/reimpl"
MEM_WARN_MB = 1500
SPEND_WARN_USD_DAY = 5.0


def main() -> None:
    now = dt.datetime.now(dt.UTC)
    today = now.date().isoformat()
    lines = [f"=== pb_watch {now.isoformat(timespec='seconds')} ==="]

    mem = {}
    for line in open("/proc/meminfo"):
        k, v = line.split(":", 1)
        mem[k] = int(v.strip().split()[0]) // 1024
    avail = mem.get("MemAvailable", 0)
    lines.append(f"mem: avail={avail}MB total={mem.get('MemTotal', 0)}MB")
    if avail < MEM_WARN_MB:
        top = subprocess.run(
            ["ps", "-eo", "rss,comm", "--sort=-rss"], capture_output=True, text=True
        ).stdout.splitlines()[1:4]
        joined = "; ".join(t.strip() for t in top)
        lines.append(f"WARN low-memory avail={avail}MB top={joined}")

    du = shutil.disk_usage("/")
    pct = du.used * 100 // du.total
    lines.append(f"disk: {pct}% used ({du.free // 2**30}G free)")
    if pct > 85:
        lines.append(f"WARN disk {pct}% used")

    spent_today = spent_total = 0.0
    calls_today = 0
    if os.path.exists(LEDGER):
        for line in open(LEDGER):
            try:
                r = json.loads(line)
            except ValueError:
                continue
            spent_total += r.get("est_usd", 0)
            if str(r.get("ts", "")).startswith(today):
                spent_today += r.get("est_usd", 0)
                calls_today += 1
    lines.append(f"spend: today=${spent_today:.2f} ({calls_today} calls) total=${spent_total:.2f}")
    if spent_today > SPEND_WARN_USD_DAY:
        lines.append(f"WARN spend today ${spent_today:.2f} > ${SPEND_WARN_USD_DAY}")

    acts: dict[str, int] = {}
    last = ""
    if os.path.exists(EVENTS):
        for line in open(EVENTS):
            try:
                e = json.loads(line)
            except ValueError:
                continue
            if str(e.get("ts", "")).startswith(today):
                name = (e.get("action") or {}).get("name", "?")
                acts[name] = acts.get(name, 0) + 1
            last = f"{e.get('slug')} {(e.get('action') or {}).get('name')}"
    lines.append(f"churn today: {acts or 'none'} | last: {last}")

    fresh = []
    if os.path.isdir(REIMPL):
        for f in os.listdir(REIMPL):
            p = os.path.join(REIMPL, f)
            m = dt.datetime.fromtimestamp(os.path.getmtime(p), dt.UTC)
            if m.date().isoformat() == today:
                fresh.append(f"{f}({os.path.getsize(p)}B)")
    lines.append(f"candidates today: {', '.join(fresh) or 'none'}")

    with open(LOG, "a") as f:
        f.write("\n".join(lines) + "\n")


if __name__ == "__main__":
    main()
