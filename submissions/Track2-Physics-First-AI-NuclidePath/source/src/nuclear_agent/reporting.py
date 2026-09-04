"""Offline demo execution and provenance-preserving report generation."""

from __future__ import annotations

import html
import json
from pathlib import Path
from typing import Any, Mapping, Sequence

from .agents import DeterministicPlanner, Orchestrator
from .contracts import ScenarioInput


REPORT_VERSION = "report-0.2"


def _number(value: float) -> str:
    return f"{value:.6g}"


def _run_for_potassium(payload: Mapping[str, Any], potassium_mg_l: float) -> dict[str, Any]:
    scenario = dict(payload)
    scenario["potassium_mg_l"] = float(potassium_mg_l)
    execution = Orchestrator(DeterministicPlanner()).run(scenario).to_dict()
    tool_result = execution["tool_result"]
    points = tool_result["points"]
    peak = max(points, key=lambda point: point["concentration_bq_m3"])
    first = points[0]
    return {
        "label": f"K+ = {_number(float(potassium_mg_l))} mg/L",
        "potassium_mg_l": float(potassium_mg_l),
        "effective_kd_m3_kg": first["effective_kd_m3_kg"],
        "retardation_factor": first["retardation_factor"],
        "travel_time_s": first["travel_time_s"],
        "sampled_max_concentration_bq_m3": peak["concentration_bq_m3"],
        "sampled_max_time_s": peak["time_s"],
        "points": points,
        "deterministic_tool_plan": execution["plan"],
        "deterministic_agents_called": execution["agents_called"],
        "assumptions": tool_result["assumptions"],
        "warnings": execution["warnings"],
        "tool": tool_result["tool"],
        "model_version": tool_result["model_version"],
        "inputs": tool_result["inputs"],
    }


def build_report(
    payload: Mapping[str, Any],
    potassium_levels: Sequence[float] = (0.0, 20.0),
    execution: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Execute the deterministic demo for each potassium comparison level."""
    if not potassium_levels:
        raise ValueError("potassium comparison must contain at least one level")
    levels = tuple(float(level) for level in potassium_levels)
    if any(level < 0 for level in levels):
        raise ValueError("potassium comparison levels must be >= 0")

    runs = [_run_for_potassium(payload, level) for level in levels]
    source_scenario = ScenarioInput.from_dict(payload).to_dict()
    execution_metadata = dict(
        execution
        or {
            "mode": "offline",
            "planner": "deterministic",
            "physics_source": "simulate_transport",
            "llm_required": False,
        }
    )
    return {
        "report_version": REPORT_VERSION,
        "execution": execution_metadata,
        "scenario": source_scenario,
        "comparison": {
            "potassium_levels_mg_l": list(levels),
            "interpretation": (
                "Within this empirical prototype, increasing K+ reduces effective Kd "
                "and therefore reduces the retardation factor."
            ),
        },
        "runs": runs,
        "assumptions": runs[0]["assumptions"],
        "warnings": sorted({warning for run in runs for warning in run["warnings"]}),
    }


def _markdown_report(report: Mapping[str, Any]) -> str:
    scenario = report["scenario"]
    runs = report["runs"]
    lines = [
        f"# Nuclear Emergency Transport Report - {scenario['scenario_id']}",
        "",
        "> Private local-agent report. Deterministic tools remain authoritative; the model is not validated for operational radiological assessment.",
        "",
        "## Execution provenance",
        "",
        f"- Mode: `{report['execution']['mode']}`",
        f"- Planner: `{report['execution']['planner']}`",
        f"- Physics tool: `{report['execution']['physics_source']}`",
        f"- Model version: `{runs[0]['model_version']}`",
        f"- LLM required: `{'yes' if report['execution']['llm_required'] else 'no'}`",
        "",
        "## Scenario inputs",
        "",
        "| Parameter | Value |",
        "|---|---:|",
    ]
    for key, value in scenario.items():
        lines.append(f"| `{key}` | `{value}` |")

    lines.extend(
        [
            "",
            "## Potassium comparison",
            "",
            "| Case | K+ (mg/L) | Kd_eff (m³/kg) | R (-) | Travel time (years) | Sampled maximum (Bq/m³) |",
            "|---|---:|---:|---:|---:|---:|",
        ]
    )
    for run in runs:
        lines.append(
            f"| {run['label']} | {_number(run['potassium_mg_l'])} | "
            f"{_number(run['effective_kd_m3_kg'])} | {_number(run['retardation_factor'])} | "
            f"{_number(run['travel_time_s'] / (365.25 * 86400))} | {_number(run['sampled_max_concentration_bq_m3'])} |"
        )

    lines.extend(["", "## Time-series points", ""])
    for run in runs:
        lines.extend(
            [
                f"### {run['label']}",
                "",
                "| Time (s) | Concentration (Bq/m³) | Kd_eff (m³/kg) | R (-) |",
                "|---:|---:|---:|---:|",
            ]
        )
        for point in run["points"]:
            lines.append(
                f"| {_number(point['time_s'])} | {_number(point['concentration_bq_m3'])} | "
                f"{_number(point['effective_kd_m3_kg'])} | {_number(point['retardation_factor'])} |"
            )
        lines.append("")

    lines.extend(
        [
            "## Assumptions and warnings",
            "",
            *[f"- {item}" for item in report["assumptions"]],
            *[f"- WARNING: {item}" for item in report["warnings"]],
            "",
            "This output is a screening demonstration. It must not be used for operational radiological decisions.",
            "",
        ]
    )
    return "\n".join(lines)


def _svg_graph(report: Mapping[str, Any]) -> str:
    width, height = 900, 540
    left, right, top, bottom = 90, 30, 60, 80
    plot_width, plot_height = width - left - right, height - top - bottom
    all_points = [point for run in report["runs"] for point in run["points"]]
    min_time = min(point["time_s"] for point in all_points)
    max_time = max(point["time_s"] for point in all_points)
    max_concentration = max(point["concentration_bq_m3"] for point in all_points)
    time_span = max(max_time - min_time, 1.0)
    concentration_scale = max(max_concentration, 1.0)
    palette = ("#b42318", "#175cd3", "#027a48", "#7f56d9", "#b54708")

    def x(time_s: float) -> float:
        return left + (time_s - min_time) / time_span * plot_width

    def y(concentration: float) -> float:
        return top + plot_height - concentration / concentration_scale * plot_height

    elements = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
        '<rect width="100%" height="100%" fill="white"/>',
        f'<text x="{width / 2}" y="28" text-anchor="middle" font-family="sans-serif" font-size="20" font-weight="bold">Cs-137 concentration vs time</text>',
        f'<line x1="{left}" y1="{top}" x2="{left}" y2="{top + plot_height}" stroke="#344054"/>',
        f'<line x1="{left}" y1="{top + plot_height}" x2="{left + plot_width}" y2="{top + plot_height}" stroke="#344054"/>',
        f'<text x="{width / 2}" y="{height - 22}" text-anchor="middle" font-family="sans-serif" font-size="14">Time (years)</text>',
        f'<text x="18" y="{height / 2}" transform="rotate(-90 18 {height / 2})" text-anchor="middle" font-family="sans-serif" font-size="14">Concentration (Bq/m³)</text>',
        f'<text x="{left - 10}" y="{top + plot_height + 5}" text-anchor="end" font-family="sans-serif" font-size="11">0</text>',
        f'<text x="{left - 10}" y="{top + 5}" text-anchor="end" font-family="sans-serif" font-size="11">{html.escape(_number(concentration_scale))}</text>',
        f'<text x="{left}" y="{top + plot_height + 22}" text-anchor="middle" font-family="sans-serif" font-size="11">{html.escape(_number(min_time / (365.25 * 86400)))}</text>',
        f'<text x="{left + plot_width}" y="{top + plot_height + 22}" text-anchor="middle" font-family="sans-serif" font-size="11">{html.escape(_number(max_time / (365.25 * 86400)))}</text>',
    ]

    for index, run in enumerate(report["runs"]):
        color = palette[index % len(palette)]
        points = " ".join(f"{x(point['time_s']):.2f},{y(point['concentration_bq_m3']):.2f}" for point in run["points"])
        legend_x = left + index * 180
        elements.extend(
            [
                f'<polyline points="{points}" fill="none" stroke="{color}" stroke-width="3"/>',
                f'<line x1="{legend_x}" y1="45" x2="{legend_x + 22}" y2="45" stroke="{color}" stroke-width="3"/>',
                f'<text x="{legend_x + 28}" y="49" font-family="sans-serif" font-size="12">{html.escape(run["label"])}</text>',
            ]
        )
        for point in run["points"]:
            elements.append(f'<circle cx="{x(point["time_s"]):.2f}" cy="{y(point["concentration_bq_m3"]):.2f}" r="4" fill="{color}"/>')

    elements.append("</svg>")
    return "\n".join(elements)


def generate_demo_artifacts(
    payload: Mapping[str, Any],
    output_dir: str | Path,
    potassium_levels: Sequence[float] = (0.0, 20.0),
    execution: Mapping[str, Any] | None = None,
) -> dict[str, Path]:
    """Generate JSON, Markdown and SVG artifacts for an offline scenario."""
    report = build_report(payload, potassium_levels, execution=execution)
    directory = Path(output_dir)
    directory.mkdir(parents=True, exist_ok=True)
    paths = {
        "json": directory / "report.json",
        "markdown": directory / "report.md",
        "svg": directory / "concentration_vs_time.svg",
    }
    paths["json"].write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    paths["markdown"].write_text(_markdown_report(report), encoding="utf-8")
    paths["svg"].write_text(_svg_graph(report), encoding="utf-8")
    return paths
