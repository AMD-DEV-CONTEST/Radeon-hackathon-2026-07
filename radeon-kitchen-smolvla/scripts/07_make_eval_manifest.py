"""Create a fixed evaluation placement manifest."""
from __future__ import annotations

import argparse
import json
import random
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--n-episodes", type=int, default=50)
    parser.add_argument("--seed", type=int, default=99)
    parser.add_argument("--cube-x-range", type=float, nargs=2, default=(0.40, 0.70))
    parser.add_argument("--cube-y-range", type=float, nargs=2, default=(-0.20, 0.20))
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    if args.n_episodes < 1:
        parser.error("--n-episodes must be >= 1")
    if args.cube_x_range[0] >= args.cube_x_range[1]:
        parser.error("cube x range must have min < max")
    if args.cube_y_range[0] >= args.cube_y_range[1]:
        parser.error("cube y range must have min < max")

    rng = random.Random(args.seed)
    coordinates = [
        {
            "episode": index,
            "cube_local_dxdy": [
                rng.uniform(*args.cube_x_range),
                rng.uniform(*args.cube_y_range),
            ],
        }
        for index in range(args.n_episodes)
    ]
    payload = {
        "version": 1,
        "seed": args.seed,
        "n_episodes": args.n_episodes,
        "cube_x_range": list(args.cube_x_range),
        "cube_y_range": list(args.cube_y_range),
        "coordinates": coordinates,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {args.n_episodes} fixed placements to {args.out}")


if __name__ == "__main__":
    main()
