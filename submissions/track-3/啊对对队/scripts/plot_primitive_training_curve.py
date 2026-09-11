from __future__ import annotations

import argparse
import re
from pathlib import Path


UPDATE_RE = re.compile(
    r"loss:(?P<loss>[0-9.]+)\s+grdn:(?P<grad>[0-9.]+)\s+"
    r"lr:(?P<lr>[0-9.e+-]+).*?mem_gb:(?P<memory>[0-9.]+)"
)


def parse_updates(text: str) -> list[dict[str, float]]:
    return [
        {
            "loss": float(match.group("loss")),
            "gradient_norm": float(match.group("grad")),
            "learning_rate": float(match.group("lr")),
            "memory_gb": float(match.group("memory")),
        }
        for match in UPDATE_RE.finditer(text)
    ]


def rolling_mean(values: list[float], window: int) -> list[float]:
    if window < 1:
        raise ValueError("window must be positive")
    result: list[float] = []
    running_sum = 0.0
    for index, value in enumerate(values):
        running_sum += value
        if index >= window:
            running_sum -= values[index - window]
        result.append(running_sum / min(index + 1, window))
    return result


def read_training_log(path: Path) -> str:
    raw = path.read_bytes()
    if raw.startswith((b"\xff\xfe", b"\xfe\xff")):
        return raw.decode("utf-16")
    if b"\x00" in raw[:1024]:
        return raw.decode("utf-16-le")
    return raw.decode("utf-8", errors="replace")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--log", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--expected-updates", type=int, default=2800)
    parser.add_argument("--window", type=int, default=100)
    args = parser.parse_args()

    updates = parse_updates(read_training_log(args.log))
    if len(updates) != args.expected_updates:
        raise RuntimeError(
            f"expected {args.expected_updates} updates, parsed {len(updates)}"
        )

    import matplotlib.pyplot as plt

    steps = list(range(1, len(updates) + 1))
    losses = [row["loss"] for row in updates]
    trend = rolling_mean(losses, args.window)

    plt.rcParams.update(
        {
            "font.family": "sans-serif",
            "font.sans-serif": ["DejaVu Sans", "Arial", "Helvetica"],
            "font.size": 8,
            "axes.labelsize": 9,
            "axes.titlesize": 9,
            "xtick.labelsize": 7,
            "ytick.labelsize": 7,
            "legend.fontsize": 7,
            "pdf.fonttype": 42,
        }
    )
    fig, axis = plt.subplots(figsize=(7.2, 3.0), constrained_layout=True)
    axis.plot(steps, losses, color="#999999", linewidth=0.45, alpha=0.35, label="Per update")
    axis.plot(
        steps,
        trend,
        color="#0072B2",
        linewidth=1.6,
        label=f"Rolling mean ({args.window} updates)",
    )
    axis.set_xlabel("Training update")
    axis.set_ylabel("Imitation loss")
    axis.set_xlim(1, len(updates))
    axis.set_ylim(bottom=0)
    axis.spines["top"].set_visible(False)
    axis.spines["right"].set_visible(False)
    axis.grid(axis="y", color="#D9D9D9", linewidth=0.5, alpha=0.7)
    axis.legend(frameon=False, loc="upper right")
    first_mean = sum(losses[:100]) / 100
    last_mean = sum(losses[-100:]) / 100
    axis.text(
        0.99,
        0.72,
        f"Single Radeon run (n=1)\nFirst 100 mean: {first_mean:.3f}\n"
        f"Last 100 mean: {last_mean:.3f}",
        transform=axis.transAxes,
        ha="right",
        va="top",
        color="#333333",
    )

    args.output.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(args.output.with_suffix(".png"), dpi=300, facecolor="white")
    fig.savefig(args.output.with_suffix(".pdf"), facecolor="white")
    plt.close(fig)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
