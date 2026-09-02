"""Create a submission-ready comparison from matched ablation summaries."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


CONDITIONS = (
    ("A_gripper_only", "Gripper-only suspended carry", "lifted", True),
    ("B_support_tray_slip_on", "Support tray + slip monitoring", "body_centered", True),
    ("C_support_tray_slip_off", "Support tray, slip monitoring disabled", "body_centered", False),
)


def create_comparison(root: Path) -> dict:
    rows = []
    for directory, label, carry_mode, slip_enabled in CONDITIONS:
        summary_path = root / directory / "batch_summary.json"
        if not summary_path.is_file():
            raise FileNotFoundError(f"Missing ablation result: {summary_path}")
        result = json.loads(summary_path.read_text(encoding="utf-8"))
        rows.append(
            {
                "condition": directory,
                "label": label,
                "carry_mode": carry_mode,
                "slip_monitoring_enabled": slip_enabled,
                "attempted_trials": result["attempted_trials"],
                "successful_trials": result["successful_trials"],
                "transport_success_rate": result["transport_success_rate"],
                "transport_success_wilson_95": result[
                    "transport_success_wilson_95"
                ],
                "grasp_success_rate": result["grasp_success_rate"],
                "payload_retention_rate": result["payload_retention_rate"],
                "place_success_rate": result["place_success_rate"],
                "outcome_counts": result["outcome_counts"],
                "mean_place_horizontal_error_m": result.get(
                    "mean_place_horizontal_error_m"
                ),
                "mean_trial_runtime_s": result.get("mean_trial_runtime_s"),
                "source": f"{directory}/batch_summary.json",
            }
        )
    return {
        "schema_version": 1,
        "experiment": "matched_seed_carry_and_slip_ablation",
        "object_profile": "package_heavy",
        "seeds": [20260730, 20260731],
        "record_video": False,
        "conditions": rows,
        "disclosure": (
            "All conditions use the same object profile, seeds, navigation steps, "
            "transport steps, simulator, and Radeon Cloud environment."
        ),
    }


def markdown(comparison: dict) -> str:
    lines = [
        "# Matched Carry/Slip Ablation (2026-08-02)",
        "",
        comparison["disclosure"],
        "",
        "| Condition | End-to-end | Grasp | Retain | Place | Mean placement error | Mean runtime | Outcomes |",
        "|---|---:|---:|---:|---:|---:|---:|---|",
    ]
    for row in comparison["conditions"]:
        error = row["mean_place_horizontal_error_m"]
        runtime = row["mean_trial_runtime_s"]
        error_text = "n/a" if error is None else f"{error * 1000:.2f} mm"
        runtime_text = "n/a" if runtime is None else f"{runtime:.2f} s"
        outcomes = ", ".join(
            f"{name}: {count}" for name, count in row["outcome_counts"].items()
        )
        lines.append(
            f"| {row['label']} | {row['successful_trials']}/{row['attempted_trials']} "
            f"({row['transport_success_rate']:.1%}) | {row['grasp_success_rate']:.1%} "
            f"| {row['payload_retention_rate']:.1%} | {row['place_success_rate']:.1%} "
            f"| {error_text} | "
            f"{runtime_text} | {outcomes} |"
        )
    lines.extend(
        [
            "",
            "## Interpretation boundary",
            "",
            "Two seeds per condition provide a controlled engineering comparison, not a "
            "high-confidence population estimate. Raw per-trial JSON and failures are retained.",
        ]
    )
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description="Summarize matched ablation results")
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--output-json", type=Path, required=True)
    parser.add_argument("--output-markdown", type=Path, required=True)
    args = parser.parse_args()
    comparison = create_comparison(args.root)
    args.output_json.write_text(
        json.dumps(comparison, indent=2), encoding="utf-8"
    )
    args.output_markdown.write_text(markdown(comparison), encoding="utf-8")
    print(json.dumps(comparison, indent=2))


if __name__ == "__main__":
    main()
