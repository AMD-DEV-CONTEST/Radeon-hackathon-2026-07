#!/usr/bin/env python3
"""Replay a frozen Phase-B collection recipe on an AMD/ROCm device."""

from __future__ import annotations

import argparse
import concurrent.futures
import json
import os
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
COLLECTOR = ROOT / "experiments/neupan_agility/ft_collect.py"


@dataclass(frozen=True)
class Recipe:
    family: str
    scene: str
    seed: int

    @property
    def tag(self) -> str:
        return f"{self.family}_{self.scene}_seed{self.seed}"


def load_recipes(recipe_dir: Path) -> list[Recipe]:
    recipes: list[Recipe] = []
    for metadata_path in sorted(recipe_dir.glob("*.json")):
        if not metadata_path.with_suffix(".npz").is_file():
            continue
        metadata = json.loads(metadata_path.read_text())
        recipes.append(
            Recipe(
                family=str(metadata["family"]),
                scene=str(metadata["scene"]),
                seed=int(metadata["seed"]),
            )
        )
    tags = [recipe.tag for recipe in recipes]
    if len(tags) != len(set(tags)):
        raise ValueError(f"duplicate recipe tags under {recipe_dir}")
    return recipes


def collect_one(
    recipe: Recipe,
    output_dir: Path,
    checkpoint: Path | None,
    device: str,
) -> tuple[str, str, float]:
    npz_path = output_dir / f"{recipe.tag}.npz"
    json_path = output_dir / f"{recipe.tag}.json"
    if npz_path.is_file() and json_path.is_file():
        return recipe.tag, "SKIPPED", 0.0

    command = [
        sys.executable,
        str(COLLECTOR),
        "--family",
        recipe.family,
        "--scene",
        recipe.scene,
        "--seed",
        str(recipe.seed),
        "--device",
        device,
        "--output-dir",
        str(output_dir),
    ]
    if checkpoint is not None:
        command.extend(("--depth-encoder-checkpoint", str(checkpoint)))
    env = os.environ.copy()
    env.setdefault("MUJOCO_GL", "egl")
    started = time.monotonic()
    completed = subprocess.run(
        command,
        cwd=ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )
    elapsed = time.monotonic() - started
    if completed.returncode != 0:
        details = "\n".join(
            part for part in (completed.stdout.strip(), completed.stderr.strip()) if part
        )
        raise RuntimeError(
            f"{recipe.tag} exited {completed.returncode} after {elapsed:.1f}s\n{details}"
        )
    return recipe.tag, "COLLECTED", elapsed


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--recipe-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--depth-encoder-checkpoint", type=Path)
    parser.add_argument("--expected-count", type=int, required=True)
    parser.add_argument("--jobs", type=int, default=4)
    parser.add_argument("--device", default="cuda")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    if args.jobs < 1:
        parser.error("--jobs must be positive")
    if not args.recipe_dir.is_dir():
        parser.error(f"missing recipe directory: {args.recipe_dir}")
    if args.depth_encoder_checkpoint is not None:
        args.depth_encoder_checkpoint = args.depth_encoder_checkpoint.resolve()
        if not args.depth_encoder_checkpoint.is_file():
            parser.error(
                f"missing checkpoint: {args.depth_encoder_checkpoint}"
            )
    return args


def main() -> int:
    args = parse_args()
    recipes = load_recipes(args.recipe_dir)
    if len(recipes) != args.expected_count:
        raise ValueError(
            f"expected {args.expected_count} recipes, found {len(recipes)}"
        )
    print(
        f"RECIPE count={len(recipes)} jobs={args.jobs} "
        f"checkpoint={args.depth_encoder_checkpoint or 'released'}",
        flush=True,
    )
    if args.dry_run:
        for recipe in recipes:
            print(recipe.tag)
        return 0

    args.output_dir.mkdir(parents=True, exist_ok=True)
    failures: list[str] = []
    collected = 0
    skipped = 0
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.jobs) as executor:
        futures = {
            executor.submit(
                collect_one,
                recipe,
                args.output_dir,
                args.depth_encoder_checkpoint,
                args.device,
            ): recipe
            for recipe in recipes
        }
        for future in concurrent.futures.as_completed(futures):
            recipe = futures[future]
            try:
                tag, status, elapsed = future.result()
            except Exception as exc:  # keep the other frozen episodes running
                failures.append(recipe.tag)
                print(f"FAILED {exc}", flush=True)
                continue
            collected += status == "COLLECTED"
            skipped += status == "SKIPPED"
            print(
                f"{status} {tag} elapsed={elapsed:.1f}s "
                f"progress={collected + skipped}/{len(recipes)}",
                flush=True,
            )
    print(
        f"SUMMARY collected={collected} skipped={skipped} failed={len(failures)}",
        flush=True,
    )
    if failures:
        print("FAILED_TAGS " + " ".join(sorted(failures)), flush=True)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
