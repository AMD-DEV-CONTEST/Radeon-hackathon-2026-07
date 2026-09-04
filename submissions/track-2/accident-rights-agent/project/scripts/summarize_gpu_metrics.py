#!/usr/bin/env python3
"""Summarize an amd-smi metric log into compact JSON."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from statistics import mean

PATTERNS = {
    "gfx_activity_pct": re.compile(r"^\s*GFX_ACTIVITY:\s+(\d+)\s+%"),
    "socket_power_w": re.compile(r"^\s*SOCKET_POWER:\s+(\d+)\s+W"),
    "used_vram_mb": re.compile(r"^\s*USED_VRAM:\s+(\d+)\s+MB"),
    "edge_temperature_c": re.compile(r"^\s*EDGE:\s+(\d+)\s+°C"),
    "hotspot_temperature_c": re.compile(r"^\s*HOTSPOT:\s+(\d+)\s+°C"),
}


def parse_metrics(text: str) -> dict[str, list[int]]:
    values = {name: [] for name in PATTERNS}
    for line in text.splitlines():
        for name, pattern in PATTERNS.items():
            match = pattern.match(line)
            if match:
                values[name].append(int(match.group(1)))
    return values


def summarize(values: dict[str, list[int]]) -> dict[str, object]:
    if not values["gfx_activity_pct"]:
        raise ValueError("No GFX_ACTIVITY samples found")
    return {
        "samples": len(values["gfx_activity_pct"]),
        "metrics": {
            name: {
                "count": len(series),
                "mean": mean(series) if series else None,
                "max": max(series) if series else None,
            }
            for name, series in values.items()
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("log_path", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    report = {
        "source": str(args.log_path),
        **summarize(parse_metrics(args.log_path.read_text(encoding="utf-8"))),
    }
    rendered = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    print(rendered, end="")
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
        print(f"Saved GPU summary: {args.output.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
