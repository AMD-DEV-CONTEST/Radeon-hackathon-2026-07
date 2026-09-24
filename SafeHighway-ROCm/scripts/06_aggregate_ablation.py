"""Aggregate reward-profile ablation runs into a comparison table and plot.

Reads every ``outputs/runs/<name>/metrics/eval.json`` produced by
``run_ablation.sh``, groups the runs by the reward profile they were trained
with, and reports mean +/- std across seeds. All runs are scored on the same
canonical baseline reward, so the numbers are directly comparable.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
import numpy as np


ACTION_ORDER = ["LANE_LEFT", "IDLE", "LANE_RIGHT", "FASTER", "SLOWER"]
PROFILE_ORDER = ["baseline", "penalty", "ttc"]
PROFILE_COLORS = {
    "baseline": "#d62728",
    "penalty": "#ff7f0e",
    "ttc": "#2ca02c",
}


def parse_args():
    parser = argparse.ArgumentParser(
        description="Aggregate reward-profile ablation runs."
    )
    parser.add_argument(
        "--outputs-root",
        type=Path,
        default=Path("outputs"),
    )
    parser.add_argument(
        "--pattern",
        type=str,
        default="abl_*",
        help="Glob over run directory names.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("outputs/ablation"),
        help="Where the table, JSON and plot are written.",
    )
    return parser.parse_args()


def collect_runs(outputs_root: Path, pattern: str) -> list[dict]:
    runs = []
    for run_dir in sorted((outputs_root / "runs").glob(pattern)):
        eval_path = run_dir / "metrics" / "eval.json"
        train_path = run_dir / "metrics" / "train_summary.json"
        if not eval_path.exists() or not train_path.exists():
            continue

        evaluation = json.loads(eval_path.read_text(encoding="utf-8"))
        training = json.loads(train_path.read_text(encoding="utf-8"))

        runs.append(
            {
                "run_name": run_dir.name,
                "profile": training.get("reward_profile", "unknown"),
                "seed": training.get("seed"),
                "timesteps": training.get("timesteps"),
                "gamma": training.get("gamma"),
                "train": training,
                "dqn": evaluation["dqn"],
                "random": evaluation["random"],
            }
        )
    return runs


def action_shares(policy_summary: dict) -> dict[str, float]:
    totals = {name: 0 for name in ACTION_ORDER}
    for episode in policy_summary["episode_results"]:
        for name, count in episode["action_counts"].items():
            totals[name] = totals.get(name, 0) + count
    grand_total = sum(totals.values())
    if grand_total == 0:
        return {name: 0.0 for name in ACTION_ORDER}
    return {name: totals[name] / grand_total for name in ACTION_ORDER}


def _mean_std(values: list[float | None]) -> tuple[float | None, float | None]:
    clean = [v for v in values if v is not None]
    if not clean:
        return None, None
    return float(np.mean(clean)), float(np.std(clean))


def aggregate(runs: list[dict], key: str) -> dict:
    """Aggregate one policy key ('dqn' or 'random') across seeds."""
    metrics = [
        "collision_rate",
        "survival_rate",
        "mean_speed",
        "mean_step_reward",
        "mean_total_reward",
        "mean_episode_steps",
        "mean_min_ttc",
        "ttc_violation_rate",
    ]

    summary: dict = {"n_seeds": len(runs)}
    for metric in metrics:
        mean, std = _mean_std([run[key].get(metric) for run in runs])
        summary[metric] = mean
        summary[f"{metric}_std"] = std

    shares = [action_shares(run[key]) for run in runs]
    summary["action_shares"] = {
        name: float(np.mean([s[name] for s in shares])) for name in ACTION_ORDER
    }
    return summary


def _fmt(value: float | None, spec: str = ".3f", scale: float = 1.0) -> str:
    if value is None:
        return "n/a"
    return format(value * scale, spec)


def _fmt_pm(
    mean: float | None,
    std: float | None,
    spec: str = ".3f",
    scale: float = 1.0,
) -> str:
    if mean is None:
        return "n/a"
    if std is None:
        return _fmt(mean, spec, scale)
    return f"{_fmt(mean, spec, scale)} ± {_fmt(std, spec, scale)}"


def render_markdown(groups: dict[str, dict], random_summary: dict) -> str:
    lines = [
        "# Reward-profile ablation",
        "",
        "All policies are scored on the canonical baseline reward "
        "(`normalize_reward=True`, `collision_reward=-1`) so that runs "
        "trained under different shaping schemes remain comparable. "
        "Values are mean ± std across seeds.",
        "",
        "## Main results",
        "",
        "| Profile | Seeds | Collision rate | Survival rate | Mean speed |"
        " Step reward | Mean min TTC (s) | TTC violation |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]

    rows = [("random", random_summary)] + [
        (name, groups[name]) for name in PROFILE_ORDER if name in groups
    ]
    for name, summary in rows:
        lines.append(
            "| {profile} | {n} | {collision} | {survival} | {speed} |"
            " {reward} | {ttc} | {violation} |".format(
                profile=f"`{name}`",
                n=summary["n_seeds"],
                collision=_fmt_pm(
                    summary["collision_rate"],
                    summary["collision_rate_std"],
                    ".1f",
                    100,
                )
                + "%",
                survival=_fmt_pm(
                    summary["survival_rate"],
                    summary["survival_rate_std"],
                    ".1f",
                    100,
                )
                + "%",
                speed=_fmt_pm(
                    summary["mean_speed"], summary["mean_speed_std"], ".2f"
                ),
                reward=_fmt_pm(
                    summary["mean_step_reward"],
                    summary["mean_step_reward_std"],
                    ".3f",
                ),
                ttc=_fmt_pm(
                    summary["mean_min_ttc"], summary["mean_min_ttc_std"], ".2f"
                ),
                violation=_fmt_pm(
                    summary["ttc_violation_rate"],
                    summary["ttc_violation_rate_std"],
                    ".1f",
                    100,
                )
                + "%",
            )
        )

    lines += [
        "",
        "## Action distribution",
        "",
        "The baseline policy degenerates into a speed maximiser: it almost "
        "never brakes. Shaping is expected to restore the `SLOWER` action.",
        "",
        "| Profile | " + " | ".join(ACTION_ORDER) + " |",
        "| --- | " + " | ".join(["---:"] * len(ACTION_ORDER)) + " |",
    ]
    for name, summary in rows:
        shares = summary["action_shares"]
        cells = " | ".join(
            f"{shares[action] * 100:.1f}%" for action in ACTION_ORDER
        )
        lines.append(f"| `{name}` | {cells} |")

    return "\n".join(lines) + "\n"


def plot_pareto(runs: list[dict], random_summary: dict, output_path: Path):
    figure, axes = plt.subplots(figsize=(7.5, 5.5))

    seen = set()
    for run in runs:
        profile = run["profile"]
        axes.scatter(
            run["dqn"]["mean_speed"],
            run["dqn"]["collision_rate"] * 100,
            s=110,
            alpha=0.85,
            color=PROFILE_COLORS.get(profile, "#7f7f7f"),
            edgecolors="black",
            linewidths=0.6,
            label=profile if profile not in seen else None,
        )
        seen.add(profile)

    axes.scatter(
        random_summary["mean_speed"],
        random_summary["collision_rate"] * 100,
        marker="X",
        s=190,
        color="#1f77b4",
        edgecolors="black",
        linewidths=0.6,
        label="random",
    )

    axes.set_xlabel("Mean speed (m/s)  →  faster")
    axes.set_ylabel("Collision rate (%)  →  less safe")
    axes.set_title(
        "Safety vs efficiency by reward profile\n"
        "(HighwayEnv, DQN on AMD ROCm; lower-right is better)"
    )
    axes.grid(alpha=0.3, linestyle="--")
    axes.legend(title="Reward profile")
    figure.tight_layout()

    output_path.parent.mkdir(parents=True, exist_ok=True)
    figure.savefig(output_path, dpi=150)
    plt.close(figure)


def main():
    args = parse_args()

    runs = collect_runs(args.outputs_root, args.pattern)
    if not runs:
        raise SystemExit(
            f"No completed runs matched {args.pattern!r} under "
            f"{args.outputs_root / 'runs'}. Run scripts/run_ablation.sh first."
        )

    groups: dict[str, dict] = {}
    for profile in sorted({run["profile"] for run in runs}):
        profile_runs = [run for run in runs if run["profile"] == profile]
        groups[profile] = aggregate(profile_runs, "dqn")

    random_summary = aggregate(runs, "random")

    args.output_dir.mkdir(parents=True, exist_ok=True)
    table_path = args.output_dir / "ablation.md"
    json_path = args.output_dir / "ablation.json"
    plot_path = args.output_dir / "safety_efficiency_pareto.png"

    table = render_markdown(groups, random_summary)
    table_path.write_text(table, encoding="utf-8")

    json_path.write_text(
        json.dumps(
            {
                "runs": [
                    {
                        "run_name": run["run_name"],
                        "profile": run["profile"],
                        "seed": run["seed"],
                        "timesteps": run["timesteps"],
                        "gamma": run["gamma"],
                        "collision_rate": run["dqn"]["collision_rate"],
                        "survival_rate": run["dqn"]["survival_rate"],
                        "mean_speed": run["dqn"]["mean_speed"],
                        "mean_step_reward": run["dqn"]["mean_step_reward"],
                        "mean_min_ttc": run["dqn"]["mean_min_ttc"],
                        "ttc_violation_rate": run["dqn"]["ttc_violation_rate"],
                        "action_shares": action_shares(run["dqn"]),
                    }
                    for run in runs
                ],
                "by_profile": groups,
                "random": random_summary,
            },
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    plot_pareto(runs, random_summary, plot_path)

    print(table)
    print(f"Table: {table_path}")
    print(f"JSON:  {json_path}")
    print(f"Plot:  {plot_path}")


if __name__ == "__main__":
    main()
