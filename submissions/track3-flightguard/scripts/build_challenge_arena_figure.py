#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import html
import json
import os
from pathlib import Path
from typing import Any

BG = "#0f1115"
PANEL = "#171b22"
PANEL2 = "#1f2530"
TEXT = "#f5f7fa"
MUTED = "#9da7b4"
RED = "#ff6b5e"
GREEN = "#55e06f"
BLUE = "#55a7ff"
LINE = "#303846"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def text(x: float, y: float, value: str, *, size: int = 18, weight: int = 500,
         fill: str = TEXT, anchor: str = "start") -> str:
    return (
        f'<text x="{x}" y="{y}" font-family="Inter,Arial,sans-serif" '
        f'font-size="{size}" font-weight="{weight}" fill="{fill}" '
        f'text-anchor="{anchor}">{html.escape(value)}</text>'
    )


def rect(x: float, y: float, width: float, height: float, *, fill: str,
         stroke: str = "none", radius: int = 12) -> str:
    return (
        f'<rect x="{x}" y="{y}" width="{width}" height="{height}" rx="{radius}" '
        f'fill="{fill}" stroke="{stroke}"/>'
    )


def write_new(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_CLOEXEC, 0o444)
    try:
        os.write(fd, payload)
        os.fsync(fd)
    finally:
        os.close(fd)
    os.chmod(path, 0o444)


def validate(summary: dict[str, Any]) -> None:
    if summary.get("schema_version") != "flightguard.challenge_arena.summary.v1":
        raise ValueError("unexpected summary schema")
    if summary.get("status") != "PASS" or summary.get("simulation_only") is not True:
        raise ValueError("summary is not a passing simulation-only result")
    gates = summary.get("gates")
    if not isinstance(gates, dict) or len(gates) != 14 or not all(gates.values()):
        raise ValueError("expected all 14 frozen gates to pass")
    primary = summary["primary"]
    retention = summary["retention"]
    expected = {
        "primary": (384, 194, 371, 177, 0),
        "retention": (192, 121, 192, 71, 0),
    }
    for name, row in (("primary", primary), ("retention", retention)):
        actual = (
            row["pair_count"], row["nominal_success_count"],
            row["robust_success_count"], row["success_delta_count"],
            row["nominal_only_success"],
        )
        if actual != expected[name]:
            raise ValueError(f"{name} aggregate drift: {actual!r}")


def render(summary: dict[str, Any], summary_sha: str) -> str:
    primary = summary["primary"]
    retention = summary["retention"]
    width, height = 1400, 900
    out = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
        f'<rect width="{width}" height="{height}" fill="{BG}"/>',
        text(52, 58, "FLIGHTGUARD · CHALLENGE ARENA", size=29, weight=800),
        text(52, 90, "Same Genesis mission. Same paired contexts. One controller change.", size=17, fill=MUTED),
    ]

    cards = [
        (52, "PRIMARY ADVERSARIAL", primary),
        (708, "RETENTION HELDOUT", retention),
    ]
    for x, label, row in cards:
        out.append(rect(x, 120, 640, 178, fill=PANEL, stroke=LINE))
        out.append(text(x + 24, 151, label, size=14, weight=800, fill=MUTED))
        baseline = 100.0 * row["nominal_success_rate"]
        robust = 100.0 * row["robust_success_rate"]
        out.append(text(x + 24, 208, f"{baseline:.1f}%", size=42, weight=800, fill=RED))
        out.append(text(x + 165, 207, "→", size=38, weight=700, fill=MUTED))
        out.append(text(x + 222, 208, f"{robust:.1f}%", size=42, weight=800, fill=GREEN))
        out.append(text(x + 24, 247, f"{row['nominal_success_count']}/{row['pair_count']} baseline", size=15, fill=MUTED))
        out.append(text(x + 222, 247, f"{row['robust_success_count']}/{row['pair_count']} robust_z", size=15, fill=MUTED))
        out.append(text(x + 24, 278, f"+{row['success_delta_count']} successes · +{row['success_delta_percentage_points']:.1f} pp", size=17, weight=700, fill=BLUE))
        out.append(text(x + 440, 278, "0 regressions", size=17, weight=800, fill=GREEN))

    out.append(text(52, 352, "PRIMARY ADVERSARIAL · SUCCESS BY FROZEN STRATUM", size=18, weight=800))
    out.append(text(52, 378, "Baseline", size=14, weight=700, fill=RED))
    out.append(text(145, 378, "Robust Z", size=14, weight=700, fill=GREEN))
    out.append(text(1280, 378, "successes / pairs", size=13, fill=MUTED, anchor="end"))

    label_map = {
        "mass_thrust_coupled": "mass + thrust",
        "horizontal_wind_delay_coupled": "horizontal wind + delay",
        "vertical_wind_delay_coupled": "vertical wind + delay",
        "mass_horizontal_wind_coupled": "mass + horizontal wind",
        "thrust_horizontal_wind_delay_coupled": "thrust + horizontal wind + delay",
        "joint_adversarial_distribution": "joint adversarial",
    }
    plot_x, plot_w = 410, 830
    for index, row in enumerate(primary["per_stratum"]):
        y = 408 + index * 62
        out.append(rect(52, y, 1296, 48, fill=PANEL if index % 2 == 0 else PANEL2, radius=8))
        out.append(text(72, y + 30, label_map[row["name"]], size=15, weight=600))
        pair_count = row["pair_count"]
        baseline_w = plot_w * row["nominal_success_count"] / pair_count
        robust_w = plot_w * row["robust_success_count"] / pair_count
        out.append(rect(plot_x, y + 9, plot_w, 12, fill=LINE, radius=6))
        out.append(rect(plot_x, y + 27, plot_w, 12, fill=LINE, radius=6))
        if baseline_w:
            out.append(rect(plot_x, y + 9, baseline_w, 12, fill=RED, radius=6))
        if robust_w:
            out.append(rect(plot_x, y + 27, robust_w, 12, fill=GREEN, radius=6))
        out.append(text(1325, y + 18, f"{row['nominal_success_count']}/{pair_count}", size=13, weight=700, fill=RED, anchor="end"))
        out.append(text(1325, y + 38, f"{row['robust_success_count']}/{pair_count}", size=13, weight=700, fill=GREEN, anchor="end"))

    gate_y = 800
    out.append(rect(52, gate_y, 1296, 58, fill=PANEL, stroke=LINE, radius=10))
    gate_items = [
        "no-op bit-exact",
        "kill magnitude 10.506 m",
        "3/3 seeds positive",
        "0 nominal-only wins",
        "max saturation 0",
        "14/14 gates PASS",
    ]
    for index, item in enumerate(gate_items):
        x = 72 + index * 207
        out.append(text(x, gate_y + 35, "✓ " + item, size=14, weight=700, fill=GREEN))

    out.extend([
        text(52, 884, "SIMULATION ONLY · sampled contexts · no sim-to-real, safety, certification, SOTA, or real-flight claim", size=13, fill=MUTED),
        text(1348, 884, "summary SHA " + summary_sha[:16], size=12, fill=MUTED, anchor="end"),
        "</svg>",
    ])
    return "\n".join(out) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description="Render the frozen Challenge Arena summary as SVG.")
    parser.add_argument("--summary", required=True, type=Path)
    parser.add_argument("--expected-summary-sha256", required=True)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    actual_sha = sha256(args.summary)
    if actual_sha != args.expected_summary_sha256:
        raise ValueError(f"summary SHA mismatch: {actual_sha}")
    summary = json.loads(args.summary.read_text(encoding="utf-8"))
    if not isinstance(summary, dict):
        raise ValueError("summary root must be an object")
    validate(summary)
    payload = render(summary, actual_sha).encode("utf-8")
    write_new(args.output, payload)
    print(json.dumps({
        "output": str(args.output),
        "output_sha256": sha256(args.output),
        "output_size_bytes": args.output.stat().st_size,
        "summary_sha256": actual_sha,
        "status": "PASS",
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
