"""Submission-grade end-to-end artifact pipeline."""

from __future__ import annotations

import csv
from datetime import datetime, timedelta, timezone
import hashlib
import html
import json
from pathlib import Path
from typing import Any, Mapping

from .analysis import ParameterRange, load_parameter_ranges, run_sensitivity, run_uncertainty
from .contracts import ScenarioInput
from .knowledge import LocalKnowledgeBase
from .memory import LocalMemoryStore
from .receptors import screen_virtual_receptors
from .report_safety import ReportSafetyGate
from .reporting import build_report, generate_demo_artifacts
from .phreeqc_scenario import compile_phreeqc_scenario
from .scenario_validation import ScenarioValidationAgent
from .security import PermissionPolicy
from .workflow import (
    DeterministicWorkflowPlanner,
    EmergencyWorkflow,
    LocalWorkflowPlanner,
    WorkflowPlanner,
)


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _prepare_phreeqc_bridge(
    case: Mapping[str, Any],
    directory: Path,
) -> tuple[dict[str, Any] | None, dict[str, Path]]:
    """Compile an opt-in PHREEQC projection without executing an external solver."""
    if "phreeqc" not in case:
        return None, {}
    compiled = compile_phreeqc_scenario(case)
    canonical = compiled.canonical_payload()
    input_path = directory / "phreeqc-input.pqi"
    metadata_path = directory / "phreeqc-metadata.json"
    input_path.write_text(compiled.input_text, encoding="utf-8")
    _write_json(metadata_path, canonical)
    metadata_sha256 = hashlib.sha256(metadata_path.read_bytes()).hexdigest()
    metadata = compiled.metadata
    exchange = metadata["exchange"]
    mapping = metadata["transport_mapping"]
    bridge = {
        "schema": canonical["schema"],
        "contract": canonical["contract"],
        "status": "compiled-not-run",
        "input_sha256": canonical["input_sha256"],
        "metadata_sha256": metadata_sha256,
        "output_file": compiled.output_file,
        "cells": mapping["cells"],
        "exchange_ions": sorted(exchange["log_k"]),
        "scientific_result_qualified": False,
        "execution_policy": (
            "Ordinary local/CI demo compiles only; external execution requires "
            "the trusted manual PHREEQC workflow on refs/heads/main."
        ),
    }
    return bridge, {
        "phreeqc_input": input_path,
        "phreeqc_metadata": metadata_path,
    }


def _deterministic_clock(seed: int):
    """Return a monotonic clock used only for reproducible demo artifacts."""
    current = datetime(2000, 1, 1, tzinfo=timezone.utc) + timedelta(seconds=seed)

    def tick() -> datetime:
        nonlocal current
        value = current
        current += timedelta(seconds=1)
        return value

    return tick


def _write_sensitivity_csv(path: Path, sensitivity: Mapping[str, Any]) -> None:
    fields = [
        "parameter",
        "case",
        "value",
        "classification",
        "source",
        "effective_kd_m3_kg",
        "retardation_factor",
        "travel_time_s",
        "sampled_max_concentration_bq_m3",
        "final_concentration_bq_m3",
    ]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for parameter, data in sensitivity["parameters"].items():
            range_data = data["range"]
            baseline_value = data["baseline_value"]
            values = {
                "low": range_data["low"],
                "baseline": baseline_value,
                "high": range_data["high"],
            }
            for case_name in ("low", "baseline", "high"):
                summary = data[case_name]
                writer.writerow(
                    {
                        "parameter": parameter,
                        "case": case_name,
                        "value": values[case_name],
                        "classification": range_data["classification"],
                        "source": range_data["source"],
                        **summary,
                    }
                )


def _write_uncertainty_csv(path: Path, uncertainty: Mapping[str, Any]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=["metric", "min", "p05", "p50", "p95", "max"],
        )
        writer.writeheader()
        for metric, values in uncertainty["metrics"].items():
            writer.writerow({"metric": metric, **values})


def _uncertainty_svg(uncertainty: Mapping[str, Any]) -> str:
    metrics = list(uncertainty["metrics"].items())
    width = 1000
    row_height = 76
    height = 100 + row_height * len(metrics)
    left, right = 330, 60
    plot_width = width - left - right
    metadata = {
        "effective_kd_m3_kg": ("Effective Kd (m³/kg)", 1.0),
        "retardation_factor": ("Retardation factor (–)", 1.0),
        "travel_time_s": ("Travel time (years)", 1.0 / (365.25 * 86400)),
        "sampled_max_concentration_bq_m3": (
            "Sampled maximum concentration (Bq/m³)",
            1.0,
        ),
        "final_concentration_bq_m3": ("Final concentration (Bq/m³)", 1.0),
    }
    elements = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
        '<rect width="100%" height="100%" fill="#0b1020"/>',
        '<text x="40" y="42" fill="#f8fafc" font-family="Liberation Sans, sans-serif" font-size="24" font-weight="700">Uncertainty intervals (P05–P95)</text>',
        f'<text x="40" y="67" fill="#94a3b8" font-family="Liberation Sans, sans-serif" font-size="13">{uncertainty["samples"]} seeded Monte Carlo samples · median shown in amber · screening inputs only</text>',
    ]
    for index, (metric, values) in enumerate(metrics):
        label, scale = metadata.get(metric, (metric.replace("_", " "), 1.0))
        p05 = values["p05"] * scale
        p50 = values["p50"] * scale
        p95 = values["p95"] * scale
        span = max(p95 - p05, 1e-30)
        y = 105 + index * row_height

        def xpos(value: float) -> float:
            return left + (value - p05) / span * plot_width

        median_x = xpos(p50)
        median_label_x = min(max(median_x, left + 70), left + plot_width - 70)
        elements.extend(
            [
                f'<text x="40" y="{y + 5}" fill="#e2e8f0" font-family="Liberation Sans, sans-serif" font-size="13">{html.escape(label)}</text>',
                f'<line x1="{left}" y1="{y}" x2="{left + plot_width}" y2="{y}" stroke="#334155" stroke-width="6" stroke-linecap="round"/>',
                f'<line x1="{left}" y1="{y}" x2="{left + plot_width}" y2="{y}" stroke="#38bdf8" stroke-width="10" stroke-linecap="round"/>',
                f'<circle cx="{median_x:.2f}" cy="{y}" r="7" fill="#fbbf24"/>',
                f'<text x="{left}" y="{y + 25}" fill="#94a3b8" font-family="Liberation Mono, monospace" font-size="11">P05 {p05:.4g}</text>',
                f'<text x="{median_label_x:.2f}" y="{y - 14}" text-anchor="middle" fill="#fbbf24" font-family="Liberation Mono, monospace" font-size="11">P50 {p50:.4g}</text>',
                f'<text x="{left + plot_width}" y="{y + 25}" text-anchor="end" fill="#94a3b8" font-family="Liberation Mono, monospace" font-size="11">P95 {p95:.4g}</text>',
            ]
        )
    elements.append("</svg>")
    return "\n".join(elements)


def _append_agent_sections(
    markdown: str,
    workflow: Mapping[str, Any],
    uncertainty: Mapping[str, Any],
) -> str:
    lines = [
        markdown.rstrip(),
        "",
        "## Private agent workflow",
        "",
        "| Capability | Verified in this run |",
        "|---|---|",
    ]
    for capability, enabled in workflow["capabilities"].items():
        lines.append(f"| `{capability}` | {'yes' if enabled else 'no'} |")
    lines.extend(
        [
            "",
            "### Execution plan",
            "",
            " → ".join(f"`{step}`" for step in workflow["plan"]),
            "",
            "### Local knowledge citations",
            "",
        ]
    )
    for hit in workflow["knowledge_hits"]:
        urls = ", ".join(hit["source_urls"]) or "bundled document"
        lines.append(
            f"- **{hit['title']}** — {hit['excerpt']} ([source]({urls}) if URL is available)"
        )
    lines.extend(
        [
            "",
            "## Uncertainty summary",
            "",
            f"Method: `{uncertainty['method']}`, samples: `{uncertainty['samples']}`, seed: `{uncertainty['seed']}`.",
            "",
            "| Metric | P05 | P50 | P95 |",
            "|---|---:|---:|---:|",
        ]
    )
    for metric, values in uncertainty["metrics"].items():
        lines.append(
            f"| `{metric}` | {values['p05']:.6g} | {values['p50']:.6g} | {values['p95']:.6g} |"
        )
    lines.extend(
        [
            "",
            "Uncertainty intervals propagate declared input ranges only; they do not represent total predictive uncertainty.",
            "",
        ]
    )
    return "\n".join(lines)


def _append_phreeqc_section(
    markdown: str,
    bridge: Mapping[str, Any],
) -> str:
    lines = [
        markdown.rstrip(),
        "",
        "## PHREEQC chemistry bridge",
        "",
        "This opt-in projection was compiled from the declared scenario. It is "
        "evidence preparation, not a scientific-result qualification.",
        "",
        "| Field | Value |",
        "|---|---|",
        f"| Status | `{bridge['status']}` |",
        f"| Input SHA-256 | `{bridge['input_sha256']}` |",
        f"| Exchange ions | `{', '.join(bridge['exchange_ions'])}` |",
        f"| Cells | `{bridge['cells']}` |",
        f"| Scientific result qualified | `{'yes' if bridge['scientific_result_qualified'] else 'no'}` |",
        "",
        "The generated input and path-free metadata are included in the output "
        "manifest. A trusted operator may run the external solver later on "
        "`refs/heads/main`; the canonical empirical Kd path remains unchanged.",
        "",
    ]
    return "\n".join(lines)


def run_full_demo(
    case: Mapping[str, Any],
    output_dir: str | Path,
    knowledge_dir: str | Path,
    parameter_ranges: Mapping[str, ParameterRange],
    uncertainty_samples: int = 512,
    seed: int = 42,
    session_id: str = "demo-session",
    planner: WorkflowPlanner | None = None,
) -> dict[str, Path]:
    """Execute every private-agent and deterministic-analysis stage."""
    if not isinstance(case.get("transport"), Mapping):
        raise ValueError("full demo requires a transport object")
    selected_planner = planner if planner is not None else DeterministicWorkflowPlanner()
    if type(selected_planner) is DeterministicWorkflowPlanner:
        execution = {
            "mode": "offline",
            "planner": "deterministic",
            "physics_source": "simulate_transport",
            "llm_required": False,
        }
    elif type(selected_planner) is LocalWorkflowPlanner:
        execution = {
            "mode": "llm-planned-local",
            "planner": "local_llm",
            "physics_source": "simulate_transport",
            "llm_required": True,
        }
    else:
        raise ValueError(
            "full demo requires a classified planner: "
            "DeterministicWorkflowPlanner or LocalWorkflowPlanner"
        )
    directory = Path(output_dir)
    directory.mkdir(parents=True, exist_ok=True)
    phreeqc_bridge, phreeqc_artifacts = _prepare_phreeqc_bridge(case, directory)
    policy = PermissionPolicy(role="analyst", local_only=True)
    memory_path = directory / "memory.jsonl"
    memory = LocalMemoryStore(
        memory_path, policy=policy, clock=_deterministic_clock(seed)
    )
    memory.clear_session(session_id)
    workflow = EmergencyWorkflow(
        planner=selected_planner,
        knowledge_base=LocalKnowledgeBase.from_directory(knowledge_dir),
        memory=memory,
        policy=policy,
    ).run(case, session_id=session_id).to_dict()

    scenario = ScenarioInput.from_dict(case["transport"])
    comparison_levels = tuple(dict.fromkeys((0.0, scenario.potassium_mg_l)))
    base = generate_demo_artifacts(
        case["transport"],
        directory,
        potassium_levels=comparison_levels,
        execution=execution,
    )
    sensitivity = run_sensitivity(case["transport"], parameter_ranges)
    uncertainty = run_uncertainty(
        case["transport"],
        parameter_ranges,
        samples=uncertainty_samples,
        seed=seed,
    )

    workflow_path = directory / "workflow.json"
    sensitivity_json = directory / "sensitivity.json"
    sensitivity_csv = directory / "sensitivity.csv"
    uncertainty_json = directory / "uncertainty.json"
    uncertainty_csv = directory / "uncertainty.csv"
    uncertainty_svg = directory / "uncertainty.svg"
    manifest_path = directory / "manifest.json"

    _write_json(workflow_path, workflow)
    _write_json(sensitivity_json, sensitivity)
    _write_sensitivity_csv(sensitivity_csv, sensitivity)
    _write_json(uncertainty_json, uncertainty)
    _write_uncertainty_csv(uncertainty_csv, uncertainty)
    uncertainty_svg.write_text(_uncertainty_svg(uncertainty), encoding="utf-8")

    report = json.loads(base["json"].read_text(encoding="utf-8"))
    report["agent_workflow"] = workflow
    report["sensitivity"] = sensitivity
    report["uncertainty"] = uncertainty
    if phreeqc_bridge is not None:
        report["phreeqc_bridge"] = phreeqc_bridge
    _write_json(base["json"], report)
    report_markdown = _append_agent_sections(
        base["markdown"].read_text(encoding="utf-8"), workflow, uncertainty
    )
    if phreeqc_bridge is not None:
        report_markdown = _append_phreeqc_section(report_markdown, phreeqc_bridge)
    base["markdown"].write_text(report_markdown, encoding="utf-8")

    artifacts = {
        "report_json": base["json"],
        "report_markdown": base["markdown"],
        "concentration_svg": base["svg"],
        "workflow_json": workflow_path,
        "sensitivity_json": sensitivity_json,
        "sensitivity_csv": sensitivity_csv,
        "uncertainty_json": uncertainty_json,
        "uncertainty_csv": uncertainty_csv,
        "uncertainty_svg": uncertainty_svg,
        "manifest_json": manifest_path,
        "memory_jsonl": memory_path,
    }
    artifacts.update(phreeqc_artifacts)
    checksums = {
        path.relative_to(directory).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for name, path in artifacts.items()
        if name != "manifest_json"
    }
    _write_json(
        manifest_path,
        {
            "manifest_version": "manifest-0.1",
            "scenario_id": case["transport"]["scenario_id"],
            "sha256": checksums,
        },
    )
    return artifacts


def run_library_scenario(
    entry: Mapping[str, Any],
    output_dir: str | Path,
    samples: int = 512,
    seed: int = 42,
) -> dict[str, Path]:
    """Validate and publish one versioned scenario with virtual receptors."""
    validation = ScenarioValidationAgent().validate(entry)
    ranges_payload = entry.get("uncertainty_ranges")
    if not isinstance(ranges_payload, Mapping):
        raise ValueError("library scenario requires uncertainty_ranges for receptor screening")
    receptors = entry.get("receptors")
    if not isinstance(receptors, list):
        raise ValueError("library scenario requires a receptors list")
    ranges = load_parameter_ranges(ranges_payload)
    receptor_result = screen_virtual_receptors(
        entry["transport"], receptors, ranges, samples=samples, seed=seed
    )
    report = build_report(entry["transport"])
    report.update(
        {
            "scenario_library_version": entry["library_version"],
            "scenario_schema_version": entry["schema_version"],
            "scenario_classification": entry["scenario_classification"],
            "parameter_sources": entry["parameter_sources"],
            "expected_qualitative_behavior": entry["expected_qualitative_behavior"],
            "scenario_validation": validation,
            "virtual_receptors": receptor_result,
        }
    )
    gate = ReportSafetyGate().assert_safe(report)
    report["report_safety_gate"] = gate
    ReportSafetyGate().assert_safe(report)

    directory = Path(output_dir)
    directory.mkdir(parents=True, exist_ok=True)
    report_json = directory / "report.json"
    report_markdown = directory / "report.md"
    receptors_svg = directory / "virtual_receptors.svg"
    validation_json = directory / "scenario_validation.json"
    manifest_json = directory / "manifest.json"
    _write_json(report_json, report)
    _write_json(validation_json, validation)

    lines = [
        f"# Versioned scenario report — {entry['transport']['scenario_id']}",
        "", f"Library: `{entry['library_version']}` · classification: **{entry['scenario_classification']}**.",
        "", "## Virtual receptor screening", "",
        "| Receptor | Distance (m) | Arrival P05/P50/P95 (s) | Sampled maximum P05/P50/P95 (Bq/m³) |",
        "|---|---:|---:|---:|",
    ]
    for row in receptor_result["receptors"]:
        arrival = row["arrival_time_s"]
        maximum = row["sampled_max_concentration_bq_m3"]
        lines.append(
            f"| {row['receptor_id']} | {row['distance_m']:.6g} | "
            f"{arrival['p05']:.6g} / {arrival['p50']:.6g} / {arrival['p95']:.6g} | "
            f"{maximum['p05']:.6g} / {maximum['p50']:.6g} / {maximum['p95']:.6g} |"
        )
    lines.extend([
        "", "## Limitations", "",
        *[f"- {item}" for item in receptor_result["limitations"]],
        "", "Demonstration screening only; no regulatory interpretation.", "",
    ])
    report_markdown.write_text("\n".join(lines), encoding="utf-8")

    width, height = 760, 120 + 70 * len(receptor_result["receptors"])
    svg = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}">',
        '<rect width="100%" height="100%" fill="#0b1020"/>',
        '<text x="30" y="38" fill="white" font-family="sans-serif" font-size="22">Virtual receptor arrival intervals</text>',
    ]
    max_p95 = max(row["arrival_time_s"]["p95"] for row in receptor_result["receptors"])
    for index, row in enumerate(receptor_result["receptors"]):
        y = 85 + index * 70
        values = row["arrival_time_s"]
        x05 = 220 + 500 * values["p05"] / max(max_p95, 1.0)
        x50 = 220 + 500 * values["p50"] / max(max_p95, 1.0)
        x95 = 220 + 500 * values["p95"] / max(max_p95, 1.0)
        svg.extend([
            f'<text x="30" y="{y + 5}" fill="#e2e8f0" font-family="sans-serif">{html.escape(row["receptor_id"])}</text>',
            f'<line x1="{x05:.2f}" y1="{y}" x2="{x95:.2f}" y2="{y}" stroke="#38bdf8" stroke-width="8"/>',
            f'<circle cx="{x50:.2f}" cy="{y}" r="6" fill="#fbbf24"/>',
        ])
    svg.append("</svg>")
    receptors_svg.write_text("\n".join(svg), encoding="utf-8")

    artifacts = {
        "report_json": report_json,
        "report_markdown": report_markdown,
        "receptors_svg": receptors_svg,
        "validation_json": validation_json,
        "manifest_json": manifest_json,
    }
    checksums = {
        path.relative_to(directory).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for name, path in artifacts.items() if name != "manifest_json"
    }
    _write_json(manifest_json, {
        "manifest_version": "manifest-0.1",
        "scenario_id": entry["transport"]["scenario_id"],
        "scenario_library_version": entry["library_version"],
        "sha256": checksums,
    })
    return artifacts
