"""Summarize paired robustness runs as CSV, Markdown and SVG."""
from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
from xml.sax.saxutils import escape


def wilson(success: int, total: int) -> tuple[float, float]:
    if total == 0:
        return 0.0, 0.0
    z = 1.96
    p = success / total
    d = 1 + z * z / total
    c = (p + z * z / (2 * total)) / d
    m = z * ((p * (1 - p) / total + z * z / (4 * total * total)) ** 0.5) / d
    return max(0.0, c - m), min(1.0, c + m)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--out-dir", type=Path, default=None)
    args = parser.parse_args()
    payload = json.loads(args.input.read_text(encoding="utf-8"))
    out_dir = args.out_dir or args.input.parent
    out_dir.mkdir(parents=True, exist_ok=True)
    rows = []
    nominal = None
    for item in payload["conditions"]:
        low, high = wilson(int(item["success"]), int(item["episodes"]))
        row = {
            "condition": item["condition"],
            "episodes": int(item["episodes"]),
            "success": int(item["success"]),
            "success_rate": float(item["success_rate"]),
            "wilson_95_low": low,
            "wilson_95_high": high,
        }
        rows.append(row)
        if item["condition"] == "nominal":
            nominal = row
    nominal_rate = nominal["success_rate"] if nominal else 0.0
    for row in rows:
        row["robustness_retention"] = (
            row["success_rate"] / nominal_rate if nominal_rate > 0 else None
        )

    with (out_dir / "robustness_summary.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)

    lines = [
        "# Sim-to-Real Robustness Envelope",
        "",
        "All conditions reuse the same placement manifest. `robustness retention` is stressed success divided by nominal success.",
        "",
        "| Condition | Episodes | Success | Rate | 95% Wilson CI | Retention |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for row in rows:
        ci = f"{row['wilson_95_low']:.1%}-{row['wilson_95_high']:.1%}"
        retention = "n/a" if row["robustness_retention"] is None else f"{row['robustness_retention']:.1%}"
        lines.append(
            f"| {row['condition']} | {row['episodes']} | {row['success']} | "
            f"{row['success_rate']:.1%} | {ci} | {retention} |"
        )
    lines += [
        "",
        "## Interpretation",
        "",
        "- Nominal is the paired control; it should remain the first row in the video and report.",
        "- A falling curve is expected under stronger visual, timing, and contact perturbations; the engineering goal is to measure the envelope rather than hide failures.",
        "- Camera dropout and occlusion test observation loss. Action delay and friction test control and contact gaps.",
        "- These are simulation stress tests, not evidence of real-robot success. Real transfer still requires camera calibration and guarded hardware trials.",
    ]
    (out_dir / "robustness_summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")

    width = 900
    height = 420
    left, top, chart_w, chart_h = 90, 55, 760, 285
    max_rate = max((row["success_rate"] for row in rows), default=1.0)
    max_rate = max(1.0, max_rate)
    points = []
    for index, row in enumerate(rows):
        x = left + (index / max(len(rows) - 1, 1)) * chart_w
        y = top + (1 - row["success_rate"] / max_rate) * chart_h
        points.append((x, y))
    polyline = " ".join(f"{x:.1f},{y:.1f}" for x, y in points)
    svg = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
        '<rect width="100%" height="100%" fill="#ffffff"/>',
        '<style>text{font-family:Arial,sans-serif;fill:#111827}.title{font-size:20px;font-weight:bold}.small{font-size:11px}.rate{font-size:12px;font-weight:bold}</style>',
        '<text class="title" x="24" y="30">Sim-to-Real robustness envelope</text>',
        '<text class="small" x="24" y="47">Paired placement manifest; lower scores under stress reveal the transfer boundary.</text>',
        f'<rect x="{left}" y="{top}" width="{chart_w}" height="{chart_h}" fill="#f9fafb" stroke="#d1d5db"/>',
    ]
    for tick in [0.0, 0.25, 0.5, 0.75, 1.0]:
        y = top + (1 - tick) * chart_h
        svg.append(f'<line x1="{left}" y1="{y:.1f}" x2="{left + chart_w}" y2="{y:.1f}" stroke="#e5e7eb"/>')
        svg.append(f'<text class="small" x="{left - 32}" y="{y + 4:.1f}">{tick:.0%}</text>')
    if points:
        svg.append(f'<polyline points="{polyline}" fill="none" stroke="#0f766e" stroke-width="3"/>')
    for (x, y), row in zip(points, rows):
        svg.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="5" fill="#0f766e"/>')
        svg.append(f'<text class="rate" x="{x - 14:.1f}" y="{y - 10:.1f}">{row["success_rate"]:.0%}</text>')
        svg.append(f'<text class="small" transform="translate({x + 4:.1f},{top + chart_h + 18}) rotate(35)">{escape(row["condition"])}</text>')
    svg += [
        f'<text class="small" x="{left + 315}" y="{height - 18}">evaluation condition (paired order)</text>',
        f'<text class="small" transform="translate(18,{top + 180}) rotate(-90)">closed-loop success rate</text>',
        "</svg>",
    ]
    (out_dir / "robustness_envelope.svg").write_text("\n".join(svg) + "\n", encoding="utf-8")
    print(f"wrote {len(rows)} robustness rows to {out_dir}")


if __name__ == "__main__":
    main()
