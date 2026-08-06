"""List Demo1 experiment runs under outputs/runs/."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from common import list_run_dirs


def parse_args():
    parser = argparse.ArgumentParser(
        description="List HighwayEnv DQN experiment runs."
    )
    parser.add_argument(
        "--outputs",
        type=Path,
        default=Path("outputs"),
        help="Outputs root containing runs/.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Print machine-readable JSON.",
    )
    return parser.parse_args()


def summarize_run(run_dir: Path) -> dict:
    meta_path = run_dir / "run_meta.json"
    meta = {}
    if meta_path.exists():
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            meta = {"error": "invalid run_meta.json"}

    models_dir = run_dir / "models"
    metrics_dir = run_dir / "metrics"
    videos_dir = run_dir / "videos"

    def exists(path: Path) -> bool:
        return path.exists()

    return {
        "run_name": run_dir.name,
        "root": str(run_dir),
        "created_at": meta.get("created_at"),
        "updated_at": meta.get("updated_at"),
        "last_stage": meta.get("last_stage"),
        "params": {
            k: meta.get("params", {}).get(k)
            for k in (
                "timesteps",
                "n_envs",
                "device",
                "gamma",
                "seed",
            )
            if k in meta.get("params", {})
        },
        "has_final_model": exists(models_dir / "dqn_highway.zip"),
        "has_best_model": exists(models_dir / "best" / "best_model.zip"),
        "has_train_summary": exists(metrics_dir / "train_summary.json"),
        "has_eval": exists(metrics_dir / "eval.json"),
        "has_learning_curve": exists(metrics_dir / "learning_curve.png"),
        "has_videos": any(videos_dir.glob("*.mp4")) if videos_dir.exists() else False,
    }


def main():
    args = parse_args()
    runs = [summarize_run(p) for p in list_run_dirs(args.outputs)]

    if args.json:
        print(json.dumps(runs, indent=2, ensure_ascii=False))
        return

    if not runs:
        print(f"No runs found under {args.outputs / 'runs'}")
        print("Train one with: python scripts/02_train_dqn.py --run-name demo")
        return

    print(f"{'RUN':<40} {'STAGE':<12} {'T':>6} {'N':>3} {'DEV':<5} {'EVAL':>4} {'VID':>3}")
    print("-" * 80)
    for item in runs:
        params = item.get("params") or {}
        print(
            f"{item['run_name']:<40} "
            f"{str(item.get('last_stage') or '-'):<12} "
            f"{str(params.get('timesteps') or '-'):>6} "
            f"{str(params.get('n_envs') or '-'):>3} "
            f"{str(params.get('device') or '-'):<5} "
            f"{'Y' if item['has_eval'] else 'N':>4} "
            f"{'Y' if item['has_videos'] else 'N':>3}"
        )

    print(
        "\nInspect one run:\n"
        "  python -m json.tool outputs/runs/<run>/run_meta.json\n"
        "  python scripts/03_evaluate.py --run-name <run>\n"
        "  python scripts/04_plot_monitor.py --run-name <run>"
    )


if __name__ == "__main__":
    main()
