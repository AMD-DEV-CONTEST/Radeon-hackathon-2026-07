#!/usr/bin/env python3
"""Run a ProgramBench eval with per-tool declarative env provisioning.

Operator-granted (2026-06-03) universal, least-privilege env layer. Reads
corpus/programbench/eval_requirements.json for the tool, provisions EXACTLY what it
declares — per-tool linux capabilities (--cap-add) + ephemeral service sidecars on a
private docker network with connection env injected — runs the official eval, then
tears everything down. Tools not in the manifest get only the harmless NET_RAW default.

This same mechanism is the IDE's real-project env-provisioning layer.

Usage: python scripts/run_pb_eval.py <tool> <pilot_dir> [--filter <author>]
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
MANIFEST = _ROOT / "corpus/programbench/eval_requirements.json"
PB = "T:/Dev/ProgramBench"
BASE_CAPS = ["NET_RAW"]  # harmless default for any ICMP tool


def _docker(*args: str, timeout: int = 60, check: bool = False) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["docker", *args], capture_output=True, text=True, timeout=timeout, check=check
    )


def _load_entry(tool: str) -> dict:
    m = json.loads(MANIFEST.read_text(encoding="utf-8"))
    return m.get("tools", {}).get(tool, {})


def provision(tool: str, entry: dict) -> tuple[list[str], list[str], str | None]:
    """Returns (run_args, started_container_ids, network_name)."""
    caps = list(dict.fromkeys(BASE_CAPS + entry.get("caps", [])))
    run_args = [f"--cap-add={c}" for c in caps]
    if entry.get("privileged"):
        run_args = ["--privileged"]
    services = entry.get("services", [])
    started: list[str] = []
    net = None
    if services:
        net = f"determinex-eval-{tool}"
        _docker("network", "rm", net)  # best-effort clean
        _docker("network", "create", net)
        run_args += ["--network", net]
        for svc in services:
            name, image = svc["name"], svc["image"]
            env_args = []
            for k, v in (svc.get("env") or {}).items():
                env_args += ["-e", f"{k}={v}"]
            _docker("rm", "-f", name)
            r = _docker(
                "run",
                "-d",
                "--name",
                name,
                "--network",
                net,
                "--network-alias",
                name,
                *env_args,
                image,
            )
            if r.returncode != 0:
                raise RuntimeError(f"sidecar {name} failed: {r.stderr.strip()}")
            started.append(name)
            # inject connection env (resolve 'alias' -> the sidecar's network alias)
            for k, v in (svc.get("expose_env") or {}).items():
                run_args += ["-e", f"{k}={name if v == 'alias' else v}"]
            # wait for readiness
            ready = svc.get("ready_cmd")
            if ready:
                ok = False
                for _ in range(60):
                    rc = _docker("exec", name, "sh", "-c", ready, timeout=20)
                    if rc.returncode == 0:
                        ok = True
                        break
                    time.sleep(3)
                print(f"  sidecar {name} ready={ok}")
    return run_args, started, net


def teardown(started: list[str], net: str | None) -> None:
    for c in started:
        _docker("rm", "-f", c)
    if net:
        _docker("network", "rm", net)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("tool")
    p.add_argument("pilot_dir")
    p.add_argument("--filter", default=None)
    args = p.parse_args(argv)
    entry = _load_entry(args.tool)
    flt = args.filter or args.tool
    print(f"== provisioning {args.tool}: {entry or '(default: NET_RAW only)'} ==")
    run_args, started, net = provision(args.tool, entry)
    env = {**os.environ, "PROGRAMBENCH_DOCKER_RUN_ARGS": " ".join(run_args), "PYTHONUTF8": "1"}
    print(f"  PROGRAMBENCH_DOCKER_RUN_ARGS={env['PROGRAMBENCH_DOCKER_RUN_ARGS']}")
    # Build the eval command through the EXISTING resource guard (do not open-code
    # `uv run programbench eval` — the guard caps workers/docker_cpus=1 to stop the
    # eval fan-out that thrashes the box). "Check before invent": this module is the law.
    try:
        sys.path.insert(0, str(_ROOT / "scripts"))
        from programbench_resource_guard import build_eval_cmd  # type: ignore

        cmd, _policy = build_eval_cmd(scaffold_root=args.pilot_dir, filter_re=flt, force=True)
    except Exception:
        cmd = [
            "uv",
            "run",
            "programbench",
            "eval",
            args.pilot_dir,
            "--filter",
            flt,
            "--workers",
            "1",
            "--branch-workers",
            "1",
            "--docker-cpus",
            "1",
            "--force",
        ]
    try:
        rc = subprocess.run(cmd, cwd=PB, env=env)
        return rc.returncode
    finally:
        teardown(started, net)
        print("== sidecars torn down ==")


if __name__ == "__main__":
    raise SystemExit(main())
