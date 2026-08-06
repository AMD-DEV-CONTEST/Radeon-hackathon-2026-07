#!/usr/bin/env python3
"""Sample AMD-SMI JSON into a stable CSV or normalize a captured sample."""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import json
import pathlib
import re
import subprocess
import sys
import time


def normalized_key(key: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", key.casefold()).strip("_")


def leaves(value, prefix=""):
    if isinstance(value, dict):
        for key, child in value.items():
            path = f"{prefix}.{normalized_key(str(key))}" if prefix else normalized_key(str(key))
            yield from leaves(child, path)
    elif isinstance(value, list):
        for index, child in enumerate(value):
            yield from leaves(child, f"{prefix}.{index}")
    else:
        yield prefix, value


def number(value):
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        match = re.search(r"-?[0-9]+(?:\.[0-9]+)?", value.replace(",", ""))
        return float(match.group()) if match else None
    return None


def parse_metrics(document: dict) -> tuple[float, float]:
    vram = None
    util = None
    for path, raw in leaves(document):
        value = number(raw)
        if value is None:
            continue
        if vram is None and (
            ("vram" in path and any(token in path for token in ("used", "usage", "memory_usage")))
            or path.endswith("mem_usage")
        ):
            vram = value
            if any(token in path for token in ("byte", "_b")) or value > 1_000_000:
                vram /= 1024 * 1024
        if util is None and (
            "gfx_activity" in path
            or "gpu_util" in path
            or ("gpu" in path and "usage" in path and "memory" not in path)
        ):
            util = value
    if vram is None or util is None:
        raise ValueError("AMD-SMI JSON did not contain recognizable used-VRAM and GPU-utilization fields")
    return round(vram, 3), round(util, 3)


def read_live() -> dict:
    completed = subprocess.run(
        ["amd-smi", "metric", "--usage", "--mem-usage", "--json"],
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(completed.stdout)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--duration", type=int, default=60)
    parser.add_argument("--interval", type=float, default=1.0)
    parser.add_argument("--output", type=pathlib.Path)
    parser.add_argument("--input-json", type=pathlib.Path, help="normalize one captured AMD-SMI response")
    args = parser.parse_args()
    if args.duration <= 0 or args.interval <= 0:
        parser.error("duration and interval must be positive")
    output = args.output or pathlib.Path(f"vram-{dt.datetime.now(dt.timezone.utc):%Y%m%dT%H%M%SZ}.csv")
    output.parent.mkdir(parents=True, exist_ok=True)

    try:
        with output.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.writer(handle)
            writer.writerow(("ts_utc", "vram_used_mib", "gpu_util_pct"))
            if args.input_json:
                document = json.loads(args.input_json.read_text(encoding="utf-8"))
                vram, util = parse_metrics(document)
                writer.writerow((dt.datetime.now(dt.timezone.utc).isoformat(), vram, util))
            else:
                deadline = time.monotonic() + args.duration
                while time.monotonic() < deadline:
                    vram, util = parse_metrics(read_live())
                    writer.writerow((dt.datetime.now(dt.timezone.utc).isoformat(), vram, util))
                    handle.flush()
                    time.sleep(args.interval)
    except (OSError, ValueError, json.JSONDecodeError, subprocess.SubprocessError) as exc:
        output.unlink(missing_ok=True)
        print(f"FAIL AC-11/20: {exc}", file=sys.stderr)
        return 1
    print(f"PASS AC-11/20: VRAM samples written to {output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
