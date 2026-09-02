#!/usr/bin/env python3
"""Render the controlled Radeon optimization decision as a dependency-free SVG."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, default=ROOT / "evidence" / "radeon-optimization.json")
    parser.add_argument("--output", type=Path, default=ROOT / "evidence" / "radeon-optimization.svg")
    args = parser.parse_args()
    report = json.loads(args.input.read_text(encoding="utf-8"))
    journeys = report["golden_journeys"]
    labels = ["4 / auto", "4 / flash on", "3 / auto", "2 / auto"]
    maximum = max(item["metrics"]["end_to_end_duration_ms"] for item in journeys)
    colors = ["#34d399", "#f59e0b", "#f59e0b", "#ef4444"]
    rows = []
    for index, (label, item, color) in enumerate(zip(labels, journeys, colors)):
        y = 150 + index * 86
        duration = item["metrics"]["end_to_end_duration_ms"] / 1000
        width = 650 * item["metrics"]["end_to_end_duration_ms"] / maximum
        checks = f'{item["semantic_checks_passed"]}/{item["semantic_checks_total"]}'
        rows.append(
            f'<text x="48" y="{y + 22}" class="label">{label}</text>'
            f'<rect x="190" y="{y}" width="{width:.1f}" height="34" rx="8" fill="{color}"/>'
            f'<text x="{205 + width:.1f}" y="{y + 23}" class="value">{duration:.1f}s | {checks}</text>'
        )
    svg = f'''<svg xmlns="http://www.w3.org/2000/svg" width="1100" height="560" viewBox="0 0 1100 560">
<rect width="1100" height="560" fill="#08111f"/>
<style>.title{{font:700 30px sans-serif;fill:#f8fafc}}.sub{{font:16px sans-serif;fill:#94a3b8}}.label{{font:600 17px monospace;fill:#e2e8f0}}.value{{font:600 15px monospace;fill:#f8fafc}}.foot{{font:14px sans-serif;fill:#94a3b8}}</style>
<text x="48" y="56" class="title">Radeon workload optimization</text>
<text x="48" y="88" class="sub">End-to-end golden journey; lower is better. Label shows semantic checks passed.</text>
{''.join(rows)}
<text x="48" y="515" class="foot">Selected: 4 context workers, flash auto, unified F16 KV, Gemma 4 26B A4B QAT Q4_0 on ROCm 7.2.1.</text>
</svg>'''
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(svg, encoding="utf-8")


if __name__ == "__main__":
    main()
