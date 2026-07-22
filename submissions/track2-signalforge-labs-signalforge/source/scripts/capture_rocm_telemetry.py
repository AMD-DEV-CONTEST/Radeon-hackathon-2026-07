#!/usr/bin/env python3
"""Capture secret-safe Radeon and cgroup telemetry while a benchmark runs."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path


def nested_value(payload: dict, *keys: str) -> float | str | None:
    current: object = payload
    for key in keys:
        if not isinstance(current, dict) or key not in current:
            return None
        current = current[key]
    if isinstance(current, dict) and "value" in current:
        current = current["value"]
    if isinstance(current, (int, float, str)):
        return current
    return None


def read_number(path: Path) -> int | None:
    try:
        value = path.read_text(encoding="utf-8").strip()
        return None if value == "max" else int(value)
    except (OSError, ValueError):
        return None


def process_exists(pid: int | None) -> bool:
    if pid is None:
        return True
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def parse_process_status(text: str) -> tuple[int | None, int | None]:
    parent_pid: int | None = None
    rss_bytes: int | None = None
    for line in text.splitlines():
        if line.startswith("PPid:"):
            parent_pid = int(line.split()[1])
        elif line.startswith("VmRSS:"):
            rss_bytes = int(line.split()[1]) * 1024
    return parent_pid, rss_bytes


def process_tree_rss(root_pid: int | None) -> tuple[int | None, int]:
    if root_pid is None:
        return None, 0
    processes: dict[int, tuple[int | None, int | None]] = {}
    for entry in Path("/proc").iterdir():
        if not entry.name.isdigit():
            continue
        try:
            processes[int(entry.name)] = parse_process_status(
                (entry / "status").read_text(encoding="utf-8")
            )
        except (OSError, ValueError):
            continue
    selected = {root_pid}
    changed = True
    while changed:
        changed = False
        for pid, (parent_pid, _) in processes.items():
            if parent_pid in selected and pid not in selected:
                selected.add(pid)
                changed = True
    rss = sum(processes[pid][1] or 0 for pid in selected if pid in processes)
    return rss, len(selected & processes.keys())


def capture(amd_smi: str, process_root_pid: int | None = None) -> dict:
    result = subprocess.run(
        [amd_smi, "metric", "--json"],
        check=False,
        capture_output=True,
        text=True,
        timeout=10,
    )
    sample: dict[str, object] = {
        "observed_at": datetime.now(timezone.utc).isoformat(),
        "monotonic_seconds": time.monotonic(),
        "cgroup_memory_current_bytes": read_number(Path("/sys/fs/cgroup/memory.current")),
        "cgroup_memory_limit_bytes": read_number(Path("/sys/fs/cgroup/memory.max")),
        "load_average_1m": os.getloadavg()[0],
    }
    process_rss, process_count = process_tree_rss(process_root_pid)
    sample["process_tree_rss_bytes"] = process_rss
    sample["process_tree_count"] = process_count
    if result.returncode != 0:
        sample["amd_smi_error"] = result.stderr.strip() or f"exit {result.returncode}"
        return sample
    try:
        gpu = json.loads(result.stdout)["gpu_data"][0]
    except (json.JSONDecodeError, KeyError, IndexError, TypeError) as error:
        sample["amd_smi_error"] = f"invalid JSON: {error}"
        return sample
    sample.update(
        {
            "gpu_index": gpu.get("gpu", 0),
            "gfx_activity_percent": nested_value(gpu, "usage", "gfx_activity"),
            "memory_activity_percent": nested_value(gpu, "usage", "umc_activity"),
            "socket_power_watts": nested_value(gpu, "power", "socket_power"),
            "throttle_status": nested_value(gpu, "power", "throttle_status"),
            "temperature_edge_celsius": nested_value(gpu, "temperature", "edge"),
            "temperature_hotspot_celsius": nested_value(gpu, "temperature", "hotspot"),
            "temperature_memory_celsius": nested_value(gpu, "temperature", "mem"),
            "vram_total_mb": nested_value(gpu, "mem_usage", "total_vram"),
            "vram_used_mb": nested_value(gpu, "mem_usage", "used_vram"),
            "vram_free_mb": nested_value(gpu, "mem_usage", "free_vram"),
        }
    )
    return sample


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--watch-pid", type=int)
    parser.add_argument("--process-root-pid", type=int)
    parser.add_argument("--duration", type=float, default=1800)
    parser.add_argument("--interval", type=float, default=1.0)
    parser.add_argument("--amd-smi", default="/opt/rocm/bin/amd-smi")
    args = parser.parse_args()
    if args.duration <= 0 or args.interval <= 0:
        raise SystemExit("duration and interval must be positive")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    deadline = time.monotonic() + args.duration
    with args.output.open("w", encoding="utf-8") as stream:
        while time.monotonic() < deadline and process_exists(args.watch_pid):
            stream.write(json.dumps(capture(args.amd_smi, args.process_root_pid), sort_keys=True) + "\n")
            stream.flush()
            time.sleep(args.interval)


if __name__ == "__main__":
    main()
