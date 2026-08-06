from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

RESULTS = Path(__file__).resolve().parent / "results"


def read(path: Path) -> dict | None:
    try:
        return json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return None


def main():
    parser = argparse.ArgumentParser(description="Summarize full sample_actions runtime backends")
    parser.add_argument("--results-dir", type=Path, default=RESULTS)
    args = parser.parse_args()
    eager = read(args.results_dir / "full_eager.json")
    if eager is None:
        raise FileNotFoundError(f"missing {args.results_dir / 'full_eager.json'}")
    eager_ms = eager["metrics"]["mean_ms"]
    eager_mem = eager["metrics"]["peak_allocated_mib"]
    rows = []
    for backend in ("eager", "compile", "hip-graph"):
        performance = read(args.results_dir / f"full_{backend}.json")
        validation = read(args.results_dir / f"validation_{backend}.json") if backend != "eager" else None
        if performance is None:
            continue
        metrics = performance["metrics"]
        mean_ms = metrics["mean_ms"]
        fixed = validation.get("fixed_input_comparison", {}) if validation else {}
        changed = validation.get("changed_input_comparison", {}) if validation else {}
        rows.append(
            {
                "backend": backend,
                "mean_ms": mean_ms,
                "p50_ms": metrics["p50_ms"],
                "p95_ms": metrics["p95_ms"],
                "samples_per_second": metrics["samples_per_second"],
                "speedup": eager_ms / mean_ms,
                "latency_reduction_pct": (1 - mean_ms / eager_ms) * 100,
                "first_call_ms": metrics["first_call_ms"],
                "peak_allocated_mib": metrics["peak_allocated_mib"],
                "memory_delta_mib": metrics["peak_allocated_mib"] - eager_mem,
                "validation_status": validation.get("status") if validation else "reference",
                "validation_passed": validation.get("validation_passed") if validation else None,
                "fixed_max_abs_error": fixed.get("max_abs_error"),
                "fixed_rmse": fixed.get("rmse"),
                "changed_max_abs_error": changed.get("max_abs_error"),
                "changed_rmse": changed.get("rmse"),
            }
        )

    def fmt(value, digits=2, suffix=""):
        return "—" if value is None else f"{value:.{digits}f}{suffix}"

    lines = [
        "# Full SmolVLA `sample_actions()` runtime backends",
        "",
        "| Backend | Mean ms | P50 ms | P95 ms | Samples/s | Speedup | Latency reduction | First call ms | Peak MiB | Memory Δ MiB | Validation | Fixed max error | Fixed RMSE | Changed max error |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|---:|---:|---:|",
    ]
    for row in rows:
        validation_label = row["validation_status"]
        if row["validation_passed"] is not None:
            validation_label += f" (passed={row['validation_passed']})"
        lines.append(
            f"| {row['backend']} | {fmt(row['mean_ms'])} | {fmt(row['p50_ms'])} | {fmt(row['p95_ms'])} | "
            f"{fmt(row['samples_per_second'])} | {fmt(row['speedup'], 3, '×')} | "
            f"{fmt(row['latency_reduction_pct'], 2, '%')} | {fmt(row['first_call_ms'])} | "
            f"{fmt(row['peak_allocated_mib'])} | {fmt(row['memory_delta_mib'])} | {validation_label} | "
            f"{fmt(row['fixed_max_abs_error'], 6)} | {fmt(row['fixed_rmse'], 6)} | "
            f"{fmt(row['changed_max_abs_error'], 6)} |"
        )
    report = "\n".join(lines) + "\n"
    markdown_path = args.results_dir / "summary.md"
    csv_path = args.results_dir / "summary.csv"
    markdown_path.write_text(report)
    with csv_path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    print(report)
    print(f"Wrote {markdown_path} and {csv_path}")


if __name__ == "__main__":
    main()
