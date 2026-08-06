#!/usr/bin/env python3
"""scripts/optimize_summary.py - optimization comparison summary report generator

Scans all opt_*.json files in the benchmarks directory, compares them with the FP16 baseline,
and generates a structured summary report (JSON + terminal table).

Usage::

    # Basic usage
    python scripts/optimize_summary.py \
        --bench-dir docs/benchmarks \
        --output docs/benchmarks/opt_summary.json

    # Specify a baseline file
    python scripts/optimize_summary.py \
        --baseline docs/benchmarks/benchmarks/vllm_profile.json \
        --bench-dir docs/benchmarks \
        --output docs/benchmarks/opt_summary.json
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any


def load_json(path: str | Path) -> dict[str, Any] | None:
    """Safely load a JSON file."""
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError) as e:
        print(f"  [WARN] cannot load {path}: {e}", file=sys.stderr)
        return None


def extract_conc4(data: dict[str, Any]) -> dict[str, Any] | None:
    """Extract the concurrency=4 data from vllm_profile results."""
    results = data.get("benchmark_results", [])
    for r in results:
        if r.get("concurrency") == 4:
            return r
    return None


def extract_all_conc(data: dict[str, Any]) -> list[dict[str, Any]]:
    """Extract the data for all concurrency levels."""
    return data.get("benchmark_results", [])


def compute_speedup(baseline_tps: float, optimized_tps: float) -> float:
    """Compute the speedup ratio."""
    if baseline_tps <= 0:
        return 0.0
    return optimized_tps / baseline_tps


def format_speedup(speedup: float) -> str:
    """Format the speedup ratio."""
    if speedup >= 1.0:
        return f"{speedup:.2f}x up"
    elif speedup > 0:
        return f"{speedup:.2f}x down"
    return "N/A"


def scan_optimization_files(bench_dir: str | Path) -> list[dict[str, Any]]:
    """Scan all opt_*.json files and extract key metrics."""
    bench_path = Path(bench_dir)
    opt_files = sorted(bench_path.glob("opt_*.json"))

    entries = []
    for f in opt_files:
        if f.name == "opt_summary.json":
            continue

        data = load_json(f)
        if data is None:
            continue

        # Determine the file type
        name = f.stem  # e.g. opt_osl_256, opt_int4_512

        config = data.get("config", {})
        results = data.get("benchmark_results", [])
        analysis = data.get("bottleneck_analysis", {})

        entry = {
            "file": str(f),
            "name": name,
            "model": config.get("model", "unknown"),
            "isl": config.get("isl", 0),
            "osl": config.get("osl", 0),
            "concurrency_levels": config.get("concurrency_levels", []),
            "results": results,
            "bottleneck": analysis.get("bottleneck", "unknown"),
        }

        # Extract key metrics for conc=4
        conc4 = extract_conc4(data)
        if conc4:
            entry["conc4_output_tps"] = conc4.get("output_tps", 0)
            entry["conc4_total_tps"] = conc4.get("total_tps", 0)
            entry["conc4_p50"] = conc4.get("lat_p50_s", 0)
            entry["conc4_p90"] = conc4.get("lat_p90_s", 0)
            entry["conc4_success"] = conc4.get("success", 0)
            entry["conc4_failures"] = conc4.get("failures", 0)

        # Extract metrics for conc=1
        for r in results:
            if r.get("concurrency") == 1:
                entry["conc1_output_tps"] = r.get("output_tps", 0)
                entry["conc1_p50"] = r.get("lat_p50_s", 0)
                break

        entries.append(entry)

    return entries


def generate_comparison_table(
    baseline: dict[str, Any] | None,
    optimizations: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Generate the comparison table data."""
    table = []

    # Baseline row
    if baseline:
        conc4 = extract_conc4(baseline)
        conc1_data = None
        for r in baseline.get("benchmark_results", []):
            if r.get("concurrency") == 1:
                conc1_data = r
                break

        base_entry = {
            "name": "FP16 baseline (C0)",
            "config": "FP16, OSL=512, max_seqs=4",
            "conc1_tps": conc1_data.get("output_tps", 0) if conc1_data else 0,
            "conc1_p50": conc1_data.get("lat_p50_s", 0) if conc1_data else 0,
            "conc4_tps": conc4.get("output_tps", 0) if conc4 else 0,
            "conc4_p50": conc4.get("lat_p50_s", 0) if conc4 else 0,
            "speedup_vs_baseline": 1.0,
            "speedup_str": "1.00x (baseline)",
        }
        table.append(base_entry)

    # Optimization rows
    for opt in optimizations:
        base_tps = table[0]["conc4_tps"] if table else 0
        opt_tps = opt.get("conc4_output_tps", 0)
        speedup = compute_speedup(base_tps, opt_tps)

        # Generate the config description
        name = opt["name"]
        if "osl" in name:
            config_desc = f"FP16, OSL={opt.get('osl', '?')}"
        elif "int4" in name and "batch" in name:
            config_desc = f"INT4, OSL={opt.get('osl', '?')}, batch=16"
        elif "int4" in name:
            config_desc = f"INT4, OSL={opt.get('osl', '?')}"
        elif "e2e" in name:
            config_desc = "E2E load test"
        else:
            config_desc = f"OSL={opt.get('osl', '?')}"

        entry = {
            "name": name,
            "config": config_desc,
            "conc1_tps": opt.get("conc1_output_tps", 0),
            "conc1_p50": opt.get("conc1_p50", 0),
            "conc4_tps": opt_tps,
            "conc4_p50": opt.get("conc4_p50", 0),
            "speedup_vs_baseline": round(speedup, 3),
            "speedup_str": format_speedup(speedup),
        }
        table.append(entry)

    return table


def generate_summary_report(
    baseline: dict[str, Any] | None,
    optimizations: list[dict[str, Any]],
    comparison_table: list[dict[str, Any]],
) -> dict[str, Any]:
    """Generate the complete summary report."""
    # Find the best config
    best = max(comparison_table, key=lambda x: x.get("conc4_tps", 0)) if comparison_table else None

    # Find the maximum speedup
    best_speedup = max(comparison_table, key=lambda x: x.get("speedup_vs_baseline", 0)) if comparison_table else None

    # Count the number of experiments
    osl_experiments = [o for o in optimizations if "osl" in o["name"]]
    int4_experiments = [o for o in optimizations if "int4" in o["name"]]
    batch_experiments = [o for o in optimizations if "batch" in o["name"]]
    e2e_experiments = [o for o in optimizations if "e2e" in o["name"]]

    report = {
        "generated_at": __import__("datetime").datetime.now().isoformat(),
        "baseline": {
            "file": "benchmarks/vllm_profile.json",
            "model": baseline.get("config", {}).get("model", "Qwen3-8B") if baseline else "unknown",
            "config": "FP16, OSL=512, ISL=512, max_num_seqs=4",
            "conc4_tps": comparison_table[0]["conc4_tps"] if comparison_table else 0,
            "conc4_p50": comparison_table[0]["conc4_p50"] if comparison_table else 0,
            "bottleneck": baseline.get("bottleneck_analysis", {}).get("bottleneck", "unknown") if baseline else "unknown",
        },
        "experiments": {
            "total": len(optimizations),
            "osl_optimization": len(osl_experiments),
            "int4_quantization": len(int4_experiments),
            "batch_optimization": len(batch_experiments),
            "e2e_validation": len(e2e_experiments),
        },
        "comparison_table": comparison_table,
        "best_config": {
            "name": best["name"] if best else "N/A",
            "config": best["config"] if best else "N/A",
            "conc4_tps": best["conc4_tps"] if best else 0,
            "conc4_p50": best["conc4_p50"] if best else 0,
            "speedup": best_speedup["speedup_str"] if best_speedup else "N/A",
            "speedup_value": best_speedup["speedup_vs_baseline"] if best_speedup else 0,
        },
        "competition_compliance": {
            "required_comparison_groups": 2,
            "available_comparison_groups": len(comparison_table) - 1,  # minus the baseline
            "meets_requirement": len(comparison_table) - 1 >= 2,
            "comparison_groups": [
                {
                    "group": entry["name"],
                    "variable": entry["config"],
                    "speedup": entry["speedup_str"],
                }
                for entry in comparison_table[1:]  # skip the baseline
            ],
        },
    }

    return report


def print_terminal_report(report: dict[str, Any]) -> None:
    """Print a formatted report in the terminal."""
    print()
    print("=" * 70)
    print("  Inference optimization comparison summary report")
    print("=" * 70)
    print()

    # Baseline
    baseline = report.get("baseline", {})
    print(f"  Baseline: {baseline.get('config', 'N/A')}")
    print(f"  Bottleneck: {baseline.get('bottleneck', 'N/A')}")
    print(f"  Conc=4 TPS: {baseline.get('conc4_tps', 0):.1f} tok/s")
    print(f"  Conc=4 P50: {baseline.get('conc4_p50', 0):.3f}s")
    print()

    # Comparison table
    table = report.get("comparison_table", [])
    if not table:
        print("  (no optimization experiment data)")
        return

    print("  Comparison table (conc=4):")
    print(f"  {'config':<30} {'TPS':>8} {'P50':>8} {'speedup':>12}")
    print(f"  {'-'*30} {'-'*8} {'-'*8} {'-'*12}")

    for entry in table:
        name = entry["name"][:28]
        tps = entry.get("conc4_tps", 0)
        p50 = entry.get("conc4_p50", 0)
        speedup = entry.get("speedup_str", "N/A")
        print(f"  {name:<30} {tps:>8.1f} {p50:>7.3f}s {speedup:>12}")

    print()

    # Best config
    best = report.get("best_config", {})
    if best.get("name") != "N/A":
        print(f"  Best config: {best.get('name', 'N/A')}")
        print(f"  Parameters: {best.get('config', 'N/A')}")
        print(f"  Peak TPS: {best.get('conc4_tps', 0):.1f} tok/s")
        print(f"  Latency P50: {best.get('conc4_p50', 0):.3f}s")
        print(f"  Speedup: {best.get('speedup', 'N/A')}")
        print()

    # Competition compliance
    compliance = report.get("competition_compliance", {})
    status = "met" if compliance.get("meets_requirement") else "not met"
    print(f"  Competition compliance: {status} (require >=2 comparison groups, currently {compliance.get('available_comparison_groups', 0)} groups)")
    print()

    # Experiment statistics
    exp = report.get("experiments", {})
    print(f"  Experiment statistics:")
    print(f"    OSL optimization: {exp.get('osl_optimization', 0)} groups")
    print(f"    INT4 quantization: {exp.get('int4_quantization', 0)} groups")
    print(f"    Batch optimization: {exp.get('batch_optimization', 0)} groups")
    print(f"    E2E validation: {exp.get('e2e_validation', 0)} groups")
    print(f"    Total: {exp.get('total', 0)} groups")
    print()
    print("=" * 70)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Optimization comparison summary report generator",
    )
    parser.add_argument(
        "--baseline",
        type=str,
        default=None,
        help="baseline JSON file path (default: benchmarks/vllm_profile.json)",
    )
    parser.add_argument(
        "--bench-dir",
        type=str,
        default="docs/benchmarks",
        help="benchmark data directory",
    )
    parser.add_argument(
        "--output",
        type=str,
        default="docs/benchmarks/opt_summary.json",
        help="summary report output path",
    )
    args = parser.parse_args()

    bench_dir = Path(args.bench_dir)

    # Load the baseline
    baseline_path = args.baseline
    if baseline_path is None:
        default_baseline = bench_dir / "benchmarks" / "vllm_profile.json"
        if default_baseline.exists():
            baseline_path = str(default_baseline)
        else:
            # Try directly under bench_dir
            alt = bench_dir / "vllm_profile.json"
            if alt.exists():
                baseline_path = str(alt)

    baseline = None
    if baseline_path:
        print(f"  Loading baseline: {baseline_path}")
        baseline = load_json(baseline_path)
    else:
        print("  [WARN] baseline file not found")

    # Scan the optimization files
    print(f"  Scanning optimization files: {bench_dir}")
    optimizations = scan_optimization_files(bench_dir)
    print(f"  Found {len(optimizations)} optimization experiment files")

    # Generate the comparison table
    comparison_table = generate_comparison_table(baseline, optimizations)

    # Generate the report
    report = generate_summary_report(baseline, optimizations, comparison_table)

    # Save the report
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"\n  Summary report saved: {output_path}")

    # Print the terminal report
    print_terminal_report(report)


if __name__ == "__main__":
    main()
