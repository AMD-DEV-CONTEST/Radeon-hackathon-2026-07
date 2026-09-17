"""Analyze Genesis closed-loop evaluation summaries.

The script writes three reproducible artifacts:

* eval_episode_records.csv - one row per episode
* eval_comparison.md - compact experiment comparison and interpretation
* failure_coordinate_scatter.svg - success/failure cube placement plot

It intentionally uses only the Python standard library so the analysis can run
on a fresh cloud instance without plotting dependencies.
"""
from __future__ import annotations

import argparse
import csv
import json
import math
from collections import OrderedDict
from pathlib import Path
from xml.sax.saxutils import escape


X_MIN, X_MAX = 0.38, 0.72
Y_MIN, Y_MAX = -0.22, 0.22


def _cube_xy(result: dict) -> tuple[float, float]:
    if "cube_local_dxdy" in result:
        x, y = result["cube_local_dxdy"]
    elif "cube_xy" in result:
        x, y = result["cube_xy"]
    elif "cube_world_xy" in result:
        x, y = result["cube_world_xy"]
    else:
        raise KeyError(f"missing cube coordinate in result keys: {sorted(result)}")
    return float(x), float(y)


def load_records(paths: list[Path], labels: list[str]) -> list[dict]:
    records: list[dict] = []
    for path, label in zip(paths, labels):
        data = json.loads(path.read_text(encoding="utf-8"))
        results = data.get("results") or data.get("episodes") or data.get("episode_results")
        if not isinstance(results, list):
            raise RuntimeError(f"{path} does not contain an episode result list")

        for result in results:
            x, y = _cube_xy(result)
            records.append(
                {
                    "run": label,
                    "episode": int(result["episode"]),
                    "cube_x": x,
                    "cube_y": y,
                    "success": bool(result["success"]),
                    "max_lift_m": float(result.get("max_lift_m", 0.0)),
                    "end_lift_m": float(result.get("end_lift_m", 0.0)),
                    "sustain_frames": int(result.get("sustain_frames", 0)),
                    "source_file": str(path),
                }
            )
    return records


def grouped(records: list[dict]) -> OrderedDict[str, list[dict]]:
    out: OrderedDict[str, list[dict]] = OrderedDict()
    for row in records:
        out.setdefault(row["run"], []).append(row)
    return out


def wilson_interval(successes: int, total: int, z: float = 1.96) -> tuple[float, float]:
    if total <= 0:
        return 0.0, 0.0
    p = successes / total
    denominator = 1.0 + z * z / total
    center = (p + z * z / (2.0 * total)) / denominator
    margin = (
        z
        * math.sqrt(
            p * (1.0 - p) / total
            + z * z / (4.0 * total * total)
        )
        / denominator
    )
    return max(0.0, center - margin), min(1.0, center + margin)


def write_csv(records: list[dict], out_dir: Path) -> None:
    with (out_dir / "eval_episode_records.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(records[0]))
        writer.writeheader()
        writer.writerows(records)


def write_markdown(records: list[dict], out_dir: Path) -> None:
    groups = grouped(records)
    lines = [
        "# Evaluation Comparison",
        "",
        "Closed-loop success is the primary metric. The 4,000-step aligned-prompt model remains the current best submission checkpoint because it has the highest controlled result on seed 99, while the second seed shows high variance that should be disclosed.",
        "",
        "| Run | Episodes | Success | Failure | Success rate | 95% Wilson CI | Main lesson |",
        "|---|---:|---:|---:|---:|---:|---|",
    ]

    lessons = {
        "baseline_4000_prompt_red_seed99": "Prompt mismatch hurts VLA behavior.",
        "baseline_4000_prompt_cube_seed99": "Best controlled result; keep as submission checkpoint.",
        "baseline_8000_prompt_cube_seed99": "More training steps did not improve closed-loop success.",
        "baseline_4000_prompt_cube_seed123": "Second seed exposes large evaluation variance.",
        "targeted_4000_prompt_cube_seed99": "Hard-case-only fine-tune likely forgot the broad distribution.",
    }

    for run, rows in groups.items():
        success = sum(1 for row in rows if row["success"])
        total = len(rows)
        low, high = wilson_interval(success, total)
        lines.append(
            f"| {run} | {total} | {success} | {total - success} | "
            f"{success / total:.1%} | {low:.1%}-{high:.1%} | "
            f"{lessons.get(run, '')} |"
        )

    lines += [
        "",
        "## Failure Coordinates",
        "",
        "Coordinates are robot-local cube placement values: cube_x is forward reach and cube_y is lateral offset.",
        "",
    ]

    for run, rows in groups.items():
        failures = [row for row in rows if not row["success"]]
        coords = ", ".join(
            f"ep{row['episode']:02d} ({row['cube_x']:.3f}, {row['cube_y']:.3f})" for row in failures
        )
        lines.append(f"- **{run}**: {coords or 'no failures'}")

    lines += [
        "",
        "## Interpretation",
        "",
        "- Use output/train/smolvla_kitchen_wrist/final as the current best checkpoint, not the targeted fine-tune.",
        "- The prompt control shows language conditioning matters: Pick up the cube. beat Pick up the red cube. under the same seed and checkpoint.",
        "- The 8,000-step control shows imitation loss and closed-loop success can diverge.",
        "- The targeted-only run collapsed to 5%, so the next data strategy should mix hard-case data with replay from the original broad distribution instead of replacing it.",
        "- The second seed also scored 5%, so any public claim should present seed-99 success as the best controlled result and disclose that robustness still needs work.",
    ]

    (out_dir / "eval_comparison.md").write_text("\n".join(lines) + "\n", encoding="utf-8")

    summary = []
    for run, rows in groups.items():
        success = sum(1 for row in rows if row["success"])
        low, high = wilson_interval(success, len(rows))
        summary.append({
            "run": run,
            "episodes": len(rows),
            "success": success,
            "failure": len(rows) - success,
            "success_rate": success / len(rows),
            "wilson_95_low": low,
            "wilson_95_high": high,
        })
    (out_dir / "eval_summary.json").write_text(
        json.dumps(summary, indent=2) + "\n", encoding="utf-8"
    )


def _scale_x(x: float, left: float, width: float) -> float:
    return left + (x - X_MIN) / (X_MAX - X_MIN) * width


def _scale_y(y: float, top: float, height: float) -> float:
    return top + (Y_MAX - y) / (Y_MAX - Y_MIN) * height


def write_svg(records: list[dict], out_dir: Path) -> None:
    groups = grouped(records)
    panel_w, panel_h = 260, 250
    margin_l, margin_t = 52, 74
    gap = 28
    chart_w, chart_h = 190, 170
    width = margin_l + len(groups) * panel_w + (len(groups) - 1) * gap + 24
    height = 370

    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
        '<rect width="100%" height="100%" fill="#ffffff"/>',
        '<style>text{font-family:Arial, sans-serif;} .small{font-size:10px;fill:#374151}.label{font-size:12px;fill:#111827}.title{font-size:16px;font-weight:bold;fill:#111827}.run{font-size:12px;font-weight:bold;fill:#111827}</style>',
        '<text class="title" x="24" y="28">Closed-loop cube placement: success vs failure</text>',
        '<text class="small" x="24" y="48">Green circles are successful picks; red crosses are failures. Yellow band highlights far-reach x=0.60-0.70.</text>',
    ]

    for idx, (run, rows) in enumerate(groups.items()):
        left = margin_l + idx * (panel_w + gap)
        top = margin_t
        plot_left = left + 42
        plot_top = top + 48
        success = sum(1 for row in rows if row["success"])
        total = len(rows)
        rate = success / total if total else 0.0

        parts.append(f'<text class="run" x="{left}" y="{top}">{escape(run)}</text>')
        parts.append(f'<text class="small" x="{left}" y="{top + 17}">{success}/{total} = {rate:.0%}</text>')
        parts.append(f'<rect x="{plot_left}" y="{plot_top}" width="{chart_w}" height="{chart_h}" fill="#f9fafb" stroke="#d1d5db"/>')

        band_x1 = _scale_x(0.60, plot_left, chart_w)
        band_x2 = _scale_x(0.70, plot_left, chart_w)
        parts.append(f'<rect x="{band_x1:.1f}" y="{plot_top}" width="{band_x2 - band_x1:.1f}" height="{chart_h}" fill="#fde68a" opacity="0.45"/>')

        for y_tick in [-0.2, -0.1, 0.0, 0.1, 0.2]:
            yy = _scale_y(y_tick, plot_top, chart_h)
            parts.append(f'<line x1="{plot_left}" y1="{yy:.1f}" x2="{plot_left + chart_w}" y2="{yy:.1f}" stroke="#e5e7eb"/>')
            parts.append(f'<text class="small" x="{plot_left - 34}" y="{yy + 3:.1f}">{y_tick:.1f}</text>')
        for x_tick in [0.4, 0.5, 0.6, 0.7]:
            xx = _scale_x(x_tick, plot_left, chart_w)
            parts.append(f'<line x1="{xx:.1f}" y1="{plot_top}" x2="{xx:.1f}" y2="{plot_top + chart_h}" stroke="#e5e7eb"/>')
            parts.append(f'<text class="small" x="{xx - 9:.1f}" y="{plot_top + chart_h + 17}">{x_tick:.1f}</text>')

        for row in rows:
            x = _scale_x(row["cube_x"], plot_left, chart_w)
            y = _scale_y(row["cube_y"], plot_top, chart_h)
            if row["success"]:
                parts.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="5.2" fill="#16a34a" stroke="#14532d" stroke-width="1"/>')
            else:
                parts.append(f'<g stroke="#dc2626" stroke-width="2"><line x1="{x - 5:.1f}" y1="{y - 5:.1f}" x2="{x + 5:.1f}" y2="{y + 5:.1f}"/><line x1="{x - 5:.1f}" y1="{y + 5:.1f}" x2="{x + 5:.1f}" y2="{y - 5:.1f}"/></g>')
            parts.append(f'<text class="small" x="{x + 6:.1f}" y="{y - 5:.1f}">{row["episode"]}</text>')

        parts.append(f'<text class="label" x="{plot_left + 58}" y="{plot_top + chart_h + 38}">cube_x</text>')
        parts.append(f'<text class="label" transform="translate({plot_left - 42},{plot_top + 112}) rotate(-90)">cube_y</text>')

    legend_y = height - 36
    parts.append(f'<circle cx="24" cy="{legend_y}" r="5" fill="#16a34a" stroke="#14532d"/>')
    parts.append(f'<text class="small" x="36" y="{legend_y + 4}">success</text>')
    parts.append(f'<g stroke="#dc2626" stroke-width="2"><line x1="96" y1="{legend_y - 5}" x2="106" y2="{legend_y + 5}"/><line x1="96" y1="{legend_y + 5}" x2="106" y2="{legend_y - 5}"/></g>')
    parts.append(f'<text class="small" x="114" y="{legend_y + 4}">failure</text>')
    parts.append("</svg>")

    (out_dir / "failure_coordinate_scatter.svg").write_text("\n".join(parts) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--eval", nargs="+", type=Path, required=True)
    parser.add_argument("--label", nargs="+", required=True)
    parser.add_argument("--out-dir", type=Path, required=True)
    args = parser.parse_args()

    if len(args.eval) != len(args.label):
        parser.error("--eval and --label must have the same number of values")

    records = load_records(args.eval, args.label)
    if not records:
        raise RuntimeError("no evaluation records found")

    args.out_dir.mkdir(parents=True, exist_ok=True)
    write_csv(records, args.out_dir)
    write_markdown(records, args.out_dir)
    write_svg(records, args.out_dir)
    print(f"wrote {len(records)} episode records to {args.out_dir}")


if __name__ == "__main__":
    main()
