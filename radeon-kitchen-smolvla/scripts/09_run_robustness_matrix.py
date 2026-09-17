"""Run a paired Sim-to-Real robustness matrix for the custom kitchen scene.

Every condition reuses one placement manifest.  This makes the comparison
paired: a lower score is attributable to the simulated transfer stressor
rather than a different random set of cube positions.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path


CONDITIONS = {
    "nominal": [],
    "brightness_085_115": ["--brightness-range", "0.85", "1.15"],
    "rgb_noise_std4": ["--image-noise-std", "4"],
    "camera_dropout_50": ["--camera-dropout-prob", "0.5"],
    "occlusion_fraction25": [
        "--occlusion-prob", "1.0", "--occlusion-fraction", "0.25"
    ],
    "action_delay_2": ["--action-delay-steps", "2"],
    "friction_low_1p2": ["--cube-friction", "1.2"],
    "friction_high_1p8": ["--cube-friction", "1.8"],
}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--checkpoint", required=True)
    parser.add_argument("--dataset-id", required=True)
    parser.add_argument("--episode-manifest", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, default=Path("output"))
    parser.add_argument("--n-episodes", type=int, default=50)
    parser.add_argument("--max-steps", type=int, default=150)
    parser.add_argument("--seed", type=int, default=99)
    parser.add_argument("--task", default="Pick up the cube.")
    parser.add_argument("--policy-type", default="smolvla")
    parser.add_argument("--camera-layout", default="up_wrist")
    parser.add_argument("--render-cpu", action="store_true")
    parser.add_argument("--skip-existing", action="store_true")
    parser.add_argument("--condition", action="append", choices=sorted(CONDITIONS),
                        help="Run only selected conditions; repeat the flag.")
    args = parser.parse_args()
    if not args.episode_manifest.exists():
        parser.error(f"manifest does not exist: {args.episode_manifest}")

    root = args.output_dir / "eval" / "robustness_matrix"
    root.mkdir(parents=True, exist_ok=True)
    selected = args.condition or list(CONDITIONS)
    records = []
    for name in selected:
        run_name = f"robustness_{name}"
        run_dir = args.output_dir / "eval" / run_name
        summary_path = run_dir / "eval_summary.json"
        if args.skip_existing and summary_path.exists():
            summary = json.loads(summary_path.read_text(encoding="utf-8"))
            print(f"[matrix] reuse {name}: {summary.get('success_rate')}")
        else:
            cmd = [
                sys.executable, str(Path(__file__).with_name("04_eval_custom_scene.py")),
                "--policy-type", args.policy_type,
                "--checkpoint", args.checkpoint,
                "--dataset-id", args.dataset_id,
                "--task", args.task,
                "--camera-layout", args.camera_layout,
                "--episode-manifest", str(args.episode_manifest),
                "--n-episodes", str(args.n_episodes),
                "--max-steps", str(args.max_steps),
                "--seed", str(args.seed),
                "--run-name", run_name,
            ]
            if args.render_cpu:
                cmd.append("--render-cpu")
            cmd.extend(CONDITIONS[name])
            print("[matrix] running:", " ".join(cmd))
            subprocess.run(cmd, check=True)
            summary = json.loads(summary_path.read_text(encoding="utf-8"))

        records.append({
            "condition": name,
            "run_name": run_name,
            "summary": str(summary_path),
            "episodes": int(summary["n_episodes"]),
            "success": int(summary["n_success"]),
            "success_rate": float(summary["success_rate"]),
            "args": CONDITIONS[name],
        })

    payload = {
        "checkpoint": args.checkpoint,
        "dataset_id": args.dataset_id,
        "episode_manifest": str(args.episode_manifest),
        "seed": args.seed,
        "n_episodes": args.n_episodes,
        "paired_manifest": True,
        "conditions": records,
    }
    out = root / "robustness_runs.json"
    out.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(f"[matrix] wrote {out}")
    print("[matrix] summarize with: python scripts/10_summarize_robustness.py --input " + str(out))


if __name__ == "__main__":
    main()
