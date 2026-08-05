#!/usr/bin/env python3
"""Compare completed Q-VGM paired gate summaries without silently preferring latest."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--gate",
        action="append",
        required=True,
        metavar="LABEL=SUMMARY_JSON",
        help="Repeat once per completed checkpoint gate.",
    )
    parser.add_argument(
        "--expected-count",
        type=int,
        default=4,
        help="Require all planned gates before ranking (default: 4).",
    )
    parser.add_argument("--output-json", type=Path, required=True)
    parser.add_argument("--output-md", type=Path, required=True)
    args = parser.parse_args()
    if len(args.gate) != args.expected_count:
        raise ValueError(
            f"expected {args.expected_count} completed gates, received {len(args.gate)}"
        )

    gates: list[dict[str, object]] = []
    reference_protocol = None
    reference_base = None
    for spec in args.gate:
        if "=" not in spec:
            raise ValueError(f"invalid --gate {spec!r}; expected LABEL=SUMMARY_JSON")
        label, raw_path = spec.split("=", 1)
        path = Path(raw_path)
        payload = json.loads(path.read_text())
        protocol = payload["protocol"]
        comparable_protocol = {
            key: protocol[key]
            for key in (
                "tasks",
                "states_per_task",
                "seed",
                "episodes_per_method",
                "action_steps_per_replan",
                "paired",
                "method",
            )
        }
        base = {
            key: payload["base"][key]
            for key in ("model_paths", "successes", "success_rate")
        }
        if reference_protocol is None:
            reference_protocol = comparable_protocol
            reference_base = base
        elif comparable_protocol != reference_protocol or base != reference_base:
            raise ValueError(
                f"gate {label!r} is not comparable to the first gate: "
                f"protocol_equal={comparable_protocol == reference_protocol}, "
                f"base_equal={base == reference_base}"
            )
        candidate = payload["qvgm"]
        paired = payload["paired"]
        gates.append(
            {
                "label": label,
                "source": str(path.resolve()),
                "model_paths": candidate["model_paths"],
                "successes": int(candidate["successes"]),
                "success_rate": float(candidate["success_rate"]),
                "wilson_95_ci": candidate["success_rate_95_wilson_ci"],
                "paired_difference": float(paired["success_rate_difference"]),
                "paired_bootstrap_95_ci": paired[
                    "success_rate_difference_95_percentile_ci"
                ],
                "failure_to_success": len(paired["fail_to_success"]),
                "success_to_failure": len(paired["success_to_fail"]),
                "mcnemar_p": float(paired["exact_mcnemar_two_sided_p"]),
                "all_actions_finite": bool(payload["all_actions_finite"]),
            }
        )

    labels = [str(gate["label"]) for gate in gates]
    if len(set(labels)) != len(labels):
        raise ValueError(f"duplicate gate labels: {labels}")
    if not all(bool(gate["all_actions_finite"]) for gate in gates):
        raise ValueError("at least one gate contains non-finite actions")
    best_count = max(int(gate["successes"]) for gate in gates)
    best_labels = [
        str(gate["label"]) for gate in gates if int(gate["successes"]) == best_count
    ]
    comparison = {
        "protocol": reference_protocol,
        "base": reference_base,
        "selection_rule": {
            "primary": "highest closed-loop successes on the common paired gate",
            "latest_checkpoint_tiebreak": False,
            "tie_policy": "retain all tied checkpoints for additional evidence",
        },
        "highest_point_estimate_successes": best_count,
        "highest_point_estimate_labels": best_labels,
        "unique_recommendation_for_10x50": best_labels[0]
        if len(best_labels) == 1
        else None,
        "gates": gates,
    }
    args.output_json.parent.mkdir(parents=True, exist_ok=True)
    args.output_md.parent.mkdir(parents=True, exist_ok=True)
    args.output_json.write_text(json.dumps(comparison, indent=2) + "\n")

    lines = [
        "# Q-VGM checkpoint paired gate comparison",
        "",
        "All rows use the same tasks, reset states, seed, SFT baseline, and 5 actions/replan.",
        "The primary ranking is observed closed-loop successes; latest is not a tiebreaker.",
        "",
        "| Checkpoint | Success | Paired diff | F→S | S→F | Bootstrap 95% CI | McNemar p |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    total = int(reference_protocol["episodes_per_method"])
    for gate in gates:
        ci = gate["paired_bootstrap_95_ci"]
        lines.append(
            f"| {gate['label']} | {gate['successes']}/{total} "
            f"({gate['success_rate']:.1%}) | {gate['paired_difference']:+.1%} | "
            f"{gate['failure_to_success']} | {gate['success_to_failure']} | "
            f"[{ci[0]:+.1%}, {ci[1]:+.1%}] | {gate['mcnemar_p']:.4g} |"
        )
    lines.extend(
        [
            "",
            f"Highest point estimate: {best_count}/{total}, checkpoint(s): "
            + ", ".join(best_labels)
            + ".",
            "Unique recommendation for 10×50: "
            + (best_labels[0] if len(best_labels) == 1 else "none (tie; gather more evidence)")
            + ".",
        ]
    )
    args.output_md.write_text("\n".join(lines) + "\n")
    print(json.dumps(comparison, indent=2))


if __name__ == "__main__":
    main()
