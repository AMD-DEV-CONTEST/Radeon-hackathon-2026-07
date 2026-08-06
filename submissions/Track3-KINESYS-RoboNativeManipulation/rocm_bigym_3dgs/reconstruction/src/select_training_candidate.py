#!/usr/bin/env python3
"""Select a completed gsplat candidate with explicit quality gates."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--training-root", type=Path, required=True)
    parser.add_argument("--steps", type=int, default=30_000)
    parser.add_argument("--candidate", action="append", default=["default", "mcmc"])
    parser.add_argument("--psnr-min", type=float, default=30.0)
    parser.add_argument("--ssim-min", type=float, default=0.92)
    parser.add_argument("--lpips-max", type=float, default=0.15)
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.steps <= 0:
        raise SystemExit("--steps must be positive")
    thresholds = {
        "psnr_min": args.psnr_min,
        "ssim_min": args.ssim_min,
        "lpips_max": args.lpips_max,
    }
    candidates: list[dict[str, object]] = []
    for name in dict.fromkeys(args.candidate):
        directory = args.training_root / f"{name}-{args.steps}"
        metrics_files = sorted((directory / "stats").glob("val_step*.json"))
        checkpoints = sorted((directory / "ckpts").glob("ckpt_*_rank0.pt"))
        if not metrics_files or not checkpoints:
            raise RuntimeError(f"candidate is incomplete: {directory}")
        metrics_path = metrics_files[-1]
        metrics = json.loads(metrics_path.read_text(encoding="utf-8"))
        finite = all(
            isinstance(metrics.get(key), (int, float))
            for key in ("psnr", "ssim", "lpips")
        )
        passed = bool(
            finite
            and float(metrics["psnr"]) >= args.psnr_min
            and float(metrics["ssim"]) >= args.ssim_min
            and float(metrics["lpips"]) <= args.lpips_max
        )
        candidates.append(
            {
                "name": name,
                "steps": args.steps,
                "directory": str(directory.resolve()),
                "metrics_path": str(metrics_path.resolve()),
                "checkpoint": str(checkpoints[-1].resolve()),
                "metrics": metrics,
                "thresholds_passed": passed,
            }
        )

    passing = [candidate for candidate in candidates if candidate["thresholds_passed"]]
    selected = min(
        passing or candidates,
        key=lambda item: float(item["metrics"]["lpips"]),
    )
    payload = {
        "schema_version": 1,
        "status": "passed" if passing else "quality_target_not_met",
        "thresholds": thresholds,
        "candidates": candidates,
        "selected": selected,
        "formal_export_allowed": bool(passing),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(payload))
    if not passing:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
