#!/usr/bin/env python3
"""Build the final audited LIBERO-Long method comparison from completed reports."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def read_json(path: Path) -> dict:
    if not path.is_file():
        raise FileNotFoundError(f"required completed report is missing: {path}")
    return json.loads(path.read_text())


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--report-dir", type=Path, default=Path("reports/libero_long_exp")
    )
    parser.add_argument("--output-json", type=Path)
    parser.add_argument("--output-md", type=Path)
    args = parser.parse_args()
    root = args.report_dir
    output_json = args.output_json or root / "method_comparison_final.json"
    output_md = args.output_md or root / "method_comparison_final.md"

    selection = read_json(root / "q_selection_n4_suite.json")
    guidance = read_json(root / "q_guidance_suite.json")
    selection_paired = read_json(root / "q_selection_paired_states0_4.json")
    guidance_paired = read_json(root / "q_guidance_paired_states0_4.json")
    checkpoint_choice = read_json(root / "qvgm_tiebreak_states0_9_comparison.json")
    selected = checkpoint_choice.get("unique_recommendation_for_10x50")
    selected_labels = (
        [selected]
        if selected
        else list(checkpoint_choice["highest_point_estimate_labels"])
    )
    if not selected_labels:
        raise ValueError("Q-VGM checkpoint comparison has no retained checkpoint")
    qvgm_reports = {
        label: read_json(root / f"qvgm_{label}_suite.json")
        for label in selected_labels
    }
    qvgm_paired_reports = {
        label: read_json(root / f"qvgm_{label}_gate_states0_9.json")
        for label in selected_labels
    }

    suites = {
        "Q-selection N=4": selection,
        "Q-guidance": guidance,
    }
    suites.update(
        {f"Q-VGM ({label})": report for label, report in qvgm_reports.items()}
    )
    reference_protocol = None
    for label, report in suites.items():
        protocol = report["protocol"]
        comparable = {
            key: protocol[key]
            for key in (
                "tasks",
                "states_per_task",
                "seed",
                "episodes",
                "action_steps_per_replan",
            )
        }
        if reference_protocol is None:
            reference_protocol = comparable
        elif comparable != reference_protocol:
            raise ValueError(f"suite protocol mismatch for {label}: {comparable}")
        if not report["all_actions_finite"]:
            raise ValueError(f"non-finite action recorded for {label}")

    paired_reports = {
        "Q-selection N=4": (selection_paired, "selection"),
        "Q-guidance": (guidance_paired, "guidance"),
    }
    paired_reports.update(
        {
            f"Q-VGM ({label})": (report, "qvgm")
            for label, report in qvgm_paired_reports.items()
        }
    )
    suite_rows = []
    paired_rows = []
    for label, report in suites.items():
        suite_rows.append(
            {
                "method": label,
                "successes": report["successes"],
                "episodes": report["protocol"]["episodes"],
                "success_rate": report["success_rate"],
                "wilson_95_ci": report["success_rate_95_wilson_ci"],
                "per_task": report["per_task"],
            }
        )
    for label, (report, key) in paired_reports.items():
        paired = report["paired"]
        paired_rows.append(
            {
                "method": label,
                "states_per_task": report["protocol"]["states_per_task"],
                "episodes": report["protocol"]["episodes_per_method"],
                "sft_successes": report["base"]["successes"],
                "method_successes": report[key]["successes"],
                "difference": paired["success_rate_difference"],
                "bootstrap_95_ci": paired[
                    "success_rate_difference_95_percentile_ci"
                ],
                "failure_to_success": len(paired["fail_to_success"]),
                "success_to_failure": len(paired["success_to_fail"]),
                "mcnemar_p": paired["exact_mcnemar_two_sided_p"],
            }
        )

    payload = {
        "protocol": reference_protocol,
        "qvgm_checkpoint_selection": {
            "unique": selected,
            "retained_for_full_evaluation": selected_labels,
            "selection_status": "unique" if selected else "tie retained",
        },
        "suite_results": suite_rows,
        "paired_sft_subsets": paired_rows,
        "interpretation_constraint": (
            "Suite rows share the same 10x50 reset-state protocol, but there is no "
            "500-episode SFT sweep. SFT effect claims use only the explicitly paired subsets."
        ),
    }
    output_json.parent.mkdir(parents=True, exist_ok=True)
    output_md.parent.mkdir(parents=True, exist_ok=True)
    output_json.write_text(json.dumps(payload, indent=2) + "\n")

    lines = [
        "# LIBERO-Long final method comparison",
        "",
        "All suite rows use 10 tasks × 50 reset states, seed 2001, 5 actions/replan, "
        "and finite executed actions.",
        "",
        "| Method | Success | Wilson 95% CI |",
        "|---|---:|---:|",
    ]
    for row in suite_rows:
        ci = row["wilson_95_ci"]
        lines.append(
            f"| {row['method']} | {row['successes']}/{row['episodes']} "
            f"({row['success_rate']:.1%}) | [{ci[0]:.1%}, {ci[1]:.1%}] |"
        )
    lines.extend(
        [
            "",
            "## Strict paired SFT subsets",
            "",
            "There is no 500-episode SFT sweep. The following effect estimates use only "
            "the reset states explicitly shared with the SFT baseline.",
            "",
            "| Method | States/task | SFT | Method | Diff | Bootstrap 95% CI | F→S / S→F | McNemar p |",
            "|---|---:|---:|---:|---:|---:|---:|---:|",
        ]
    )
    for row in paired_rows:
        states = row["states_per_task"]
        ci = row["bootstrap_95_ci"]
        lines.append(
            f"| {row['method']} | {states[0]}–{states[-1]} | "
            f"{row['sft_successes']}/{row['episodes']} | "
            f"{row['method_successes']}/{row['episodes']} | {row['difference']:+.1%} | "
            f"[{ci[0]:+.1%}, {ci[1]:+.1%}] | "
            f"{row['failure_to_success']} / {row['success_to_failure']} | "
            f"{row['mcnemar_p']:.4g} |"
        )
    output_md.write_text("\n".join(lines) + "\n")
    print(json.dumps(payload, indent=2))


if __name__ == "__main__":
    main()
