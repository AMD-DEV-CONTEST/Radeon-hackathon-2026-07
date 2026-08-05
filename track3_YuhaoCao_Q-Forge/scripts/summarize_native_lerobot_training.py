#!/usr/bin/env python3
"""Extract an exact-step metric curve from LeRobot's humanized training log."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path


METRIC_RE = re.compile(
    r"step:(?P<display_step>\S+)\s+"
    r"smpl:(?P<samples>\S+)\s+"
    r"ep:(?P<episodes>\S+)\s+"
    r"epch:(?P<epochs>\S+)\s+"
    r"loss:(?P<loss>\S+)\s+"
    r"grdn:(?P<grad_norm>\S+)\s+"
    r"lr:(?P<lr>\S+)\s+"
    r"updt_s:(?P<update_seconds>\S+)\s+"
    r"data_s:(?P<data_seconds>\S+)"
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("log", type=Path)
    parser.add_argument("--log-freq", type=int, default=200)
    parser.add_argument("--expected-steps", type=int)
    parser.add_argument("--output", type=Path)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    rows = []
    for line in args.log.read_text(errors="replace").splitlines():
        match = METRIC_RE.search(line)
        if match is None:
            continue
        values = match.groupdict()
        rows.append(
            {
                "step": len(rows) * args.log_freq + args.log_freq,
                "display_step": values["display_step"],
                "display_samples": values["samples"],
                "display_episodes": values["episodes"],
                "epochs": float(values["epochs"]),
                "loss": float(values["loss"]),
                "grad_norm": float(values["grad_norm"]),
                "learning_rate": float(values["lr"]),
                "update_seconds": float(values["update_seconds"]),
                "data_seconds": float(values["data_seconds"]),
            }
        )

    if not rows:
        raise ValueError(f"no LeRobot training metric rows found in {args.log}")
    if args.expected_steps is not None and rows[-1]["step"] != args.expected_steps:
        raise ValueError(
            f"last metric step is {rows[-1]['step']}, expected {args.expected_steps}"
        )

    summary = {
        "log": str(args.log.resolve()),
        "log_frequency": args.log_freq,
        "last_step": rows[-1]["step"],
        "minimum_loss": min(row["loss"] for row in rows),
        "final_loss": rows[-1]["loss"],
        "mean_update_seconds": sum(row["update_seconds"] for row in rows) / len(rows),
        "rows": rows,
    }
    encoded = json.dumps(summary, indent=2) + "\n"
    if args.output is None:
        print(encoded, end="")
    else:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(encoded)


if __name__ == "__main__":
    main()
