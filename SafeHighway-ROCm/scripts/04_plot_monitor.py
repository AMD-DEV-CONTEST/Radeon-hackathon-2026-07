"""Plot training reward curve from a Stable-Baselines3 monitor CSV."""

from __future__ import annotations

import argparse
from pathlib import Path

import matplotlib.pyplot as plt
import pandas as pd

from common import monitor_csv_path, resolve_run_paths


def parse_args():
    parser = argparse.ArgumentParser(
        description="Plot HighwayEnv DQN learning curve from monitor CSV."
    )
    parser.add_argument(
        "--run-name",
        type=str,
        default=None,
        help="Read/write under outputs/runs/<run-name>/metrics/.",
    )
    parser.add_argument(
        "--monitor",
        type=Path,
        default=None,
        help="Override monitor CSV path.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Override output PNG path.",
    )
    parser.add_argument(
        "--window",
        type=int,
        default=20,
        help="Rolling mean window over episodes.",
    )
    return parser.parse_args()


def load_monitor(path: Path) -> pd.DataFrame:
    return pd.read_csv(path, comment="#")


def main():
    args = parse_args()

    if args.run_name:
        run = resolve_run_paths(args.run_name)
        monitor = monitor_csv_path(
            args.monitor or (run.metrics / "train.monitor.csv")
        )
        output = args.output or (run.metrics / "learning_curve.png")
    else:
        monitor = monitor_csv_path(
            args.monitor or Path("outputs/metrics/train.monitor.csv")
        )
        output = args.output or Path("outputs/metrics/learning_curve.png")

    if not monitor.exists():
        raise FileNotFoundError(f"Monitor CSV not found: {monitor}")

    df = load_monitor(monitor)
    if "r" not in df.columns:
        raise ValueError(f"No reward column 'r' in {monitor}")

    df = df.copy()
    df["episode"] = range(1, len(df) + 1)
    df["reward_smooth"] = (
        df["r"].rolling(window=args.window, min_periods=1).mean()
    )

    output.parent.mkdir(parents=True, exist_ok=True)

    title = "HighwayEnv DQN learning curve"
    if args.run_name:
        title = f"{title} ({args.run_name})"

    fig, ax = plt.subplots(figsize=(10, 5))
    ax.plot(df["episode"], df["r"], alpha=0.35, label="episode reward")
    ax.plot(
        df["episode"],
        df["reward_smooth"],
        label=f"rolling mean (window={args.window})",
    )
    ax.set_xlabel("Episode")
    ax.set_ylabel("Episode reward")
    ax.set_title(title)
    ax.grid(True, alpha=0.3)
    ax.legend()
    fig.tight_layout()
    fig.savefig(output, dpi=150)
    plt.close(fig)

    print(f"Episodes: {len(df)}")
    print(f"Mean reward: {df['r'].mean():.2f}")
    print(
        f"Last-{min(args.window, len(df))} mean: "
        f"{df['r'].tail(args.window).mean():.2f}"
    )
    print(f"Saved: {output}")


if __name__ == "__main__":
    main()
