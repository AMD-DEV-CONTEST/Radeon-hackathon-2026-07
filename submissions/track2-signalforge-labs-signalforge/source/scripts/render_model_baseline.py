#!/usr/bin/env python3
"""Render the public Radeon model-baseline comparison from frozen evidence."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, default=Path("evidence/radeon-baseline.json"))
    parser.add_argument("--output", type=Path, default=Path("evidence/model-baseline-comparison.svg"))
    args = parser.parse_args()

    payload = json.loads(args.input.read_text(encoding="utf-8"))
    candidates = payload["candidates"]
    labels = [candidate["profile_id"].split("-")[0] for candidate in candidates]
    series = (
        ("Contract checks", [100 * item["contract_checks_passed"] / item["contract_checks_total"] for item in candidates], 100, "%"),
        ("Decode throughput", [item["decode_tokens_per_second_p50"] for item in candidates], 100, " tok/s"),
        ("Duration p50", [item["duration_ms_p50"] / 1000 for item in candidates], 5, " s"),
    )
    colors = ("#d95f02", "#1b9e77", "#355c9a")
    width, height = 1320, 500
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
        '<rect width="100%" height="100%" fill="#f7f4ed"/>',
        '<style>text{font-family:Verdana,sans-serif;fill:#17202a}.title{font-size:23px;font-weight:700}.sub{font-size:13px;fill:#566573}.panel{font-size:17px;font-weight:700}.label{font-size:12px}.value{font-size:12px;font-weight:700}</style>',
        '<text x="660" y="38" text-anchor="middle" class="title">SignalForge Radeon baseline · gfx1100 · ROCm 7.2.1</text>',
        '<text x="660" y="61" text-anchor="middle" class="sub">8 workloads × 5 repetitions · deterministic contract quality only</text>',
    ]
    for panel_index, (title, values, scale, suffix) in enumerate(series):
        panel_x = 35 + panel_index * 430
        baseline = 400
        parts.append(f'<rect x="{panel_x}" y="82" width="390" height="348" rx="12" fill="#ffffff" stroke="#d5d8dc"/>')
        parts.append(f'<text x="{panel_x + 195}" y="112" text-anchor="middle" class="panel">{title}</text>')
        for index, (label, value, color) in enumerate(zip(labels, values, colors)):
            x = panel_x + 42 + index * 116
            bar_height = max(2, 245 * value / scale)
            y = baseline - bar_height
            parts.append(f'<rect x="{x}" y="{y:.1f}" width="72" height="{bar_height:.1f}" rx="4" fill="{color}"/>')
            parts.append(f'<text x="{x + 36}" y="{y - 8:.1f}" text-anchor="middle" class="value">{value:.1f}{suffix}</text>')
            parts.append(f'<text x="{x + 36}" y="420" text-anchor="middle" class="label">{label}</text>')
    parts.append('<text x="660" y="470" text-anchor="middle" class="sub">Source: evidence/radeon-baseline.json · Gemma selected; Qwen retained as long-context alternate</text>')
    parts.append('</svg>')
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text("\n".join(parts) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
