#!/usr/bin/env python3
"""
determinex_orphan_reaper.py -- kill eval tool binaries that escaped cleanup
========================================================================
WHY: the observe/reimpl runners launch a tool binary (the reference `./executable` or a compiled
candidate) under a parent Python. If that PARENT dies mid-run (stall-detector SIGKILL, crash, a
higher-level timeout), the child binary reparents to init (ppid==1) and keeps running -- a 27h
100%-CPU `json-tui ./executable /tmp/jt_*.json` orphan was the live proof. hardened_runner is
called under threads, so PR_SET_PDEATHSIG (die-with-parent) via preexec_fn is unsafe (fork-in-
thread deadlock); a periodic reaper is the safe net for this parent-death class.

CONSERVATIVE BY DESIGN -- only ever kills a process that is ALL of:
  * ppid == 1            (reparented orphan; an in-progress eval's child still has the eval as parent)
  * etimes > REAP_AGE    (default 1200s/20min -- WAY beyond any per-probe timeout of 10-60s)
  * comm NOT a service / orchestrator / build tool / shell (explicit allowlist-by-exclusion)
  * AND (runs from an eval temp/workspace dir  OR  is pegging CPU > CPU_RUNAWAY)
So the python orchestrators (autodrive/reimpl), redis, docker, ollama, sshd, compilers, and any
live eval are never touched. Run from cron every few minutes; logs each kill to syslog + stdout.

Usage:
  python3 determinex_orphan_reaper.py            # arm: kill matching orphans
  python3 determinex_orphan_reaper.py --dry-run  # list what WOULD be killed, kill nothing
"""

from __future__ import annotations

import subprocess
import sys
import time

REAP_AGE = 1200  # seconds: only orphans older than this (>> any single-probe timeout)
CPU_RUNAWAY = 50.0  # percent: a non-temp orphan must be pegging CPU to qualify

# Never kill these -- orchestrators, services, shells, build tools, runtimes.
SKIP_COMM = {
    "systemd",
    "init",
    "dockerd",
    "containerd",
    "containerd-shim",
    "containerd-shim-runc-v2",
    "sshd",
    "redis-server",
    "redis",
    "cron",
    "crond",
    "ollama",
    "qemu-ga",
    "irqbalance",
    "atd",
    "packagekitd",
    "agetty",
    "rsyslog",
    "rsyslogd",
    "dbus-daemon",
    "systemd-journal",
    "udevd",
    "systemd-udevd",
    "polkitd",
    "multipathd",
    "networkd-dispat",
    "unattended-upgr",
    "accounts-daemon",
    "sleep",
    "bash",
    "sh",
    "dash",
    "zsh",
    "tmux",
    "node",
    "python",
    "python3",
    "python3.11",
    "go",
    "gopls",
    "cargo",
    "rustc",
    "ghc",
    "cc",
    "gcc",
    "g++",
    "clang",
    "clang++",
    "make",
    "ld",
    "npm",
    "pip",
    "pip3",
    "uv",
    "git",
    "ssh",
    "scp",
    "rsync",
    "docker",
    "containerd-shim-runc",
}
# Markers that a binary is an eval tool artifact (vs a system daemon).
EVAL_PATH_MARKERS = (
    "/tmp/",
    "/workspace/",
    "determinex_native_",
    "/executable",
    "./executable",
    ".citrun_",
    "/cand",
    "determinex_obs_",
)
# Long-lived drivers that must NEVER be reaped even if orphaned (ppid==1 after an SSH drop) -- they
# are SUPPOSED to keep running. Checked first so the nested-probe rule below can't catch them.
ORCHESTRATOR_SIG = (
    "determinex_pb_autodrive",
    "determinex_reimpl_drive",
    "determinex_pb_overnight",
    "determinex_pb_reeval",
    "pb_parallel",
    "programbench eval",
    "determinex_hive",
    "determinex_swebench",
    "--watch",
    "--all",
)


def _candidates() -> list[tuple[str, str, int, float, str, str]]:
    """(pid, ppid, etimes, pcpu, comm, args) for ppid==1 orphans older than REAP_AGE."""
    out = subprocess.run(
        ["ps", "-eo", "pid=,ppid=,etimes=,pcpu=,comm=,args="], capture_output=True, text=True
    ).stdout
    rows = []
    for line in out.splitlines():
        parts = line.split(None, 5)
        if len(parts) < 6:
            continue
        pid, ppid, et, cpu, comm, args = parts
        try:
            if int(ppid) != 1 or int(et) < REAP_AGE:
                continue
            rows.append((pid, ppid, int(et), float(cpu), comm, args))
        except ValueError:
            continue
    return rows


def _is_reapable(comm: str, cpu: float, args: str) -> bool:
    if any(s in args for s in ORCHESTRATOR_SIG):
        return False  # never reap a long-lived driver/eval, even if orphaned
    if comm in SKIP_COMM:
        # A skipped runtime (python/sh/...) is STILL reapable if its args reveal a TRANSIENT one-off
        # tool-PROBE running a tmp tool binary -- the exact 23.5h orphan was an orphaned
        # `python3 -c "...subprocess.run(['/tmp/b6f/executable'])..."` (the parent skipped as
        # python3, the tool child not ppid==1). Tightly gated (tmp + executable + already excluded
        # all orchestrators above) so the autodrive/reimpl/hive can never match.
        return "/tmp/" in args and "executable" in args
    looks_eval = any(m in args for m in EVAL_PATH_MARKERS) or args.lstrip().startswith("./")
    return looks_eval or cpu > CPU_RUNAWAY


def main() -> int:
    dry = "--dry-run" in sys.argv
    try:
        import syslog

        syslog.openlog("determinex-reaper")
    except Exception:
        syslog = None
    killed = 0
    for pid, _ppid, et, cpu, comm, args in _candidates():
        if not _is_reapable(comm, cpu, args):
            continue
        tag = f"orphan pid={pid} comm={comm} etimes={et}s cpu={cpu}% :: {args[:90]}"
        if dry:
            print(f"[would-reap] {tag}")
            continue
        try:
            subprocess.run(["kill", "-9", pid], timeout=5)
            killed += 1
            line = f"reaped {tag}"
            print(f"[{time.strftime('%H:%M:%S')}] {line}")
            if syslog:
                syslog.syslog(line)
        except Exception as e:
            print(f"[reap-failed] {pid}: {e}")
    if not dry and killed == 0:
        print(f"[{time.strftime('%H:%M:%S')}] no orphans to reap")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
