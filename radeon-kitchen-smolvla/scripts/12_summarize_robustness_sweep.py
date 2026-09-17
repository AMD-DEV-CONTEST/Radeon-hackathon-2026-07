"""Summarize multi-strength robustness sweeps as CSV, Markdown and SVG."""
from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
from xml.sax.saxutils import escape


COLORS = {
    "brightness": "#2563eb",
    "rgb_noise": "#7c3aed",
    "occlusion": "#dc2626",
    "action_delay": "#d97706",
    "friction_low": "#059669",
    "friction_high": "#0891b2",
}
LABELS = {
    "brightness": "Brightness +/-",
    "rgb_noise": "RGB noise",
    "occlusion": "Occlusion",
    "action_delay": "Action delay",
    "friction_low": "Friction low",
    "friction_high": "Friction high",
}


def wilson(success: int, total: int) -> tuple[float, float]:
    if total <= 0:
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
    nominal = next(row for row in payload["points"] if row["family"] == "nominal")
    rows = []
    for point in payload["points"]:
        low, high = wilson(int(point["success"]), int(point["episodes"]))
        family_key = point["family"]
        if family_key == "friction":
            family_key = f"friction_{point['direction']}"
        rows.append({
            "label": point["label"],
            "family": family_key,
            "direction": point["direction"],
            "severity": float(point["severity"]),
            "episodes": int(point["episodes"]),
            "success": int(point["success"]),
            "success_rate": float(point["success_rate"]),
            "wilson_95_low": low,
            "wilson_95_high": high,
            "retention_vs_nominal": float(point["success_rate"]) / float(nominal["success_rate"]),
            "parameter": point["parameter"],
        })

    csv_fields = ["label", "family", "direction", "severity", "episodes", "success", "success_rate", "wilson_95_low", "wilson_95_high", "retention_vs_nominal", "parameter"]
    with (out_dir / "robustness_sweep_summary.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=csv_fields)
        writer.writeheader()
        for row in rows:
            output = dict(row)
            output["parameter"] = " ".join(row["parameter"])
            writer.writerow(output)

    lines = [
        "# Sim-to-Real Robustness Intensity Sweep",
        "",
        "Every point reuses one placement manifest. Severity is normalized within each stress family: 0 is nominal and 1 is the maximum listed perturbation.",
        "",
        "| Family | Severity | Parameter | Episodes | Success | Rate | Retention |",
        "|---|---:|---|---:|---:|---:|---:|",
    ]
    for row in rows:
        parameter = " ".join(row["parameter"]) if row["parameter"] else "nominal"
        lines.append(
            f"| {LABELS.get(row['family'], row['family'])} | {row['severity']:.2f} | `{parameter}` | "
            f"{row['episodes']} | {row['success']} | {row['success_rate']:.1%} | {row['retention_vs_nominal']:.1%} |"
        )
    lines.extend([
        "",
        "## Reading the Curve",
        "",
        "The expected transfer pattern is lower success at higher stress, but each point is an episode-level binomial estimate. A non-monotonic local step is reported as sampling variance rather than smoothed away.",
        "",
        "The friction family is shown as separate low- and high-friction directions because the same absolute deviation can affect contact in different ways.",
        "",
        "These are Genesis stress tests, not real-robot success guarantees.",
    ])
    (out_dir / "robustness_sweep_summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")

    by_family: dict[str, list[dict]] = {}
    for row in rows:
        if row["family"] == "nominal":
            continue
        by_family.setdefault(row["family"], []).append(row)
    nominal_rate = float(nominal["success_rate"])
    width, height = 1180, 700
    left, top, chart_w, chart_h = 110, 90, 770, 470
    svg = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
        '<rect width="100%" height="100%" fill="#ffffff"/>',
        '<style>text{font-family:Arial,sans-serif;fill:#111827}.title{font-size:24px;font-weight:bold}.sub{font-size:13px}.axis{font-size:12px}.rate{font-size:12px;font-weight:bold}</style>',
        '<text class="title" x="34" y="38">Sim-to-Real robustness intensity sweep</text>',
        '<text class="sub" x="34" y="61">Same placement manifest; stress severity increases from 0 to 1</text>',
        f'<rect x="{left}" y="{top}" width="{chart_w}" height="{chart_h}" fill="#f9fafb" stroke="#d1d5db"/>',
    ]
    for tick in [0.0, 0.25, 0.5, 0.75, 1.0]:
        y = top + (1 - tick) * chart_h
        svg.append(f'<line x1="{left}" y1="{y:.1f}" x2="{left + chart_w}" y2="{y:.1f}" stroke="#e5e7eb"/>')
        svg.append(f'<text class="axis" x="{left - 42}" y="{y + 4:.1f}">{tick:.0%}</text>')
    for tick in [0.0, 0.25, 0.5, 0.75, 1.0]:
        x = left + tick * chart_w
        svg.append(f'<line x1="{x:.1f}" y1="{top}" x2="{x:.1f}" y2="{top + chart_h}" stroke="#eef2f7"/>')
        svg.append(f'<text class="axis" x="{x - 8:.1f}" y="{top + chart_h + 24}">{tick:.2f}</text>')

    nominal_x = left
    nominal_y = top + (1 - nominal_rate) * chart_h
    svg.append(f'<circle cx="{nominal_x}" cy="{nominal_y:.1f}" r="7" fill="#111827"/>')
    svg.append(f'<text class="rate" x="{nominal_x + 10}" y="{nominal_y - 12:.1f}">{nominal_rate:.0%} nominal</text>')
    for family, family_rows in by_family.items():
        color = COLORS.get(family, "#374151")
        points = [(nominal_x, nominal_y)]
        ordered_rows = sorted(family_rows, key=lambda item: item["severity"])
        for row in ordered_rows:
            x = left + row["severity"] * chart_w
            y = top + (1 - row["success_rate"]) * chart_h
            points.append((x, y))
        polyline = " ".join(f"{x:.1f},{y:.1f}" for x, y in points)
        svg.append(f'<polyline points="{polyline}" fill="none" stroke="{color}" stroke-width="3"/>')
        for row, (x, y) in zip(ordered_rows, points[1:]):
            low_y = top + (1 - row["wilson_95_high"]) * chart_h
            high_y = top + (1 - row["wilson_95_low"]) * chart_h
            svg.append(f'<line x1="{x:.1f}" y1="{low_y:.1f}" x2="{x:.1f}" y2="{high_y:.1f}" stroke="{color}" stroke-width="1.5" opacity="0.65"/>')
            svg.append(f'<line x1="{x - 5:.1f}" y1="{low_y:.1f}" x2="{x + 5:.1f}" y2="{low_y:.1f}" stroke="{color}" stroke-width="1.5" opacity="0.65"/>')
            svg.append(f'<line x1="{x - 5:.1f}" y1="{high_y:.1f}" x2="{x + 5:.1f}" y2="{high_y:.1f}" stroke="{color}" stroke-width="1.5" opacity="0.65"/>')
            svg.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="5" fill="{color}"/>')
    svg.append(f'<text class="axis" x="{left + 290}" y="{height - 28}">normalized perturbation intensity  →</text>')
    svg.append(f'<text class="axis" transform="translate(22,{top + 280}) rotate(-90)">closed-loop success rate</text>')
    legend_x, legend_y = 930, 125
    for index, family in enumerate(by_family):
        y = legend_y + index * 42
        color = COLORS.get(family, "#374151")
        svg.append(f'<line x1="{legend_x}" y1="{y}" x2="{legend_x + 28}" y2="{y}" stroke="{color}" stroke-width="4"/>')
        svg.append(f'<text class="axis" x="{legend_x + 40}" y="{y + 4}">{escape(LABELS.get(family, family))}</text>')
    svg.extend([
        f'<text class="sub" x="930" y="480">Nominal: {nominal_rate:.0%}</text>',
        '<text class="sub" x="930" y="510">Friction is split by direction.</text>',
        '<text class="sub" x="930" y="540">Thin bars: 95% Wilson interval.</text>',
        '<text class="sub" x="930" y="570">No curve is artificially smoothed.</text>',
        "</svg>",
    ])
    (out_dir / "robustness_intensity_envelope.svg").write_text("\n".join(svg) + "\n", encoding="utf-8")
    print(f"wrote {len(rows)} sweep rows to {out_dir}")


if __name__ == "__main__":
    main()
