#!/usr/bin/env python3
"""Create a Q-VGM H-step transition file from collected pickle episodes."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import torch

from smolvla_qvgm_rlinf.data.chunk_transition import (
    build_chunk_transitions,
    concatenate_chunk_transitions,
)
from smolvla_qvgm_rlinf.data.collected_episode_adapter import load_collected_episode


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--pickle-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--horizon", type=int, default=5)
    parser.add_argument("--gamma", type=float, default=0.99)
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    paths = sorted(args.pickle_dir.glob("*.pkl"))
    episodes = [load_collected_episode(path) for path in paths]
    per_episode = [
        build_chunk_transitions(episode, horizon=args.horizon, gamma=args.gamma)
        for episode in episodes
    ]
    batch = concatenate_chunk_transitions(per_episode)
    output_path = args.output_dir / "chunk_transitions.pt"
    torch.save(batch, output_path)
    metrics = {
        "episodes": len(episodes),
        "transitions": int(batch["proprio"].shape[0]),
        "horizon": args.horizon,
        "gamma": args.gamma,
        "terminal_transitions": int(batch["done"].sum()),
        "bootstrap_transitions": int(batch["bootstrap_mask"].sum()),
        "shapes": {key: list(value.shape) for key, value in batch.items()},
        "output": str(output_path.resolve()),
    }
    (args.output_dir / "metrics.json").write_text(json.dumps(metrics, indent=2) + "\n")
    print(json.dumps(metrics, indent=2))


if __name__ == "__main__":
    main()

