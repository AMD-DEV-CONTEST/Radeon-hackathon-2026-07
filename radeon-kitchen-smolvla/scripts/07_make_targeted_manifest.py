"""Create targeted placements from failed closed-loop evaluation episodes."""
from __future__ import annotations

import argparse
import json
import random
from pathlib import Path


def _result_xy(result: dict) -> tuple[float, float]:
    values = result.get("cube_local_dxdy") or result.get("cube_xy")
    if values is None:
        raise KeyError(f"missing cube coordinates: {sorted(result)}")
    return float(values[0]), float(values[1])


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--eval", nargs="+", type=Path, required=True)
    parser.add_argument("--n-episodes", type=int, default=40)
    parser.add_argument("--jitter-x", type=float, default=0.015)
    parser.add_argument("--jitter-y", type=float, default=0.015)
    parser.add_argument("--seed", type=int, default=2026)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    if args.n_episodes < 1:
        parser.error("--n-episodes must be >= 1")
    if args.jitter_x < 0.0 or args.jitter_y < 0.0:
        parser.error("jitter values must be non-negative")

    failure_points = []
    for path in args.eval:
        data = json.loads(path.read_text(encoding="utf-8"))
        results = data.get("results") or data.get("episodes") or []
        for result in results:
            if not result.get("success", False):
                failure_points.append(_result_xy(result))
    if not failure_points:
        raise RuntimeError("no failed episodes found in the supplied evaluations")

    rng = random.Random(args.seed)
    coordinates = []
    for index in range(args.n_episodes):
        x, y = failure_points[index % len(failure_points)]
        coordinates.append({
            "episode": index,
            "source_failure_index": index % len(failure_points),
            "cube_local_dxdy": [
                x + rng.uniform(-args.jitter_x, args.jitter_x),
                y + rng.uniform(-args.jitter_y, args.jitter_y),
            ],
        })

    payload = {
        "version": 1,
        "source_eval_files": [str(path) for path in args.eval],
        "seed": args.seed,
        "n_episodes": args.n_episodes,
        "jitter": [args.jitter_x, args.jitter_y],
        "coordinates": coordinates,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {args.n_episodes} targeted placements to {args.out}")


if __name__ == "__main__":
    main()
