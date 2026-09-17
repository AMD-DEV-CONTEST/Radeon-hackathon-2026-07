"""Run multi-strength paired Sim-to-Real robustness sweeps.

Each stress family reuses one placement manifest and the same nominal control.
The output is intentionally explicit about the physical parameter at each
normalized severity so the plot is an evidence envelope, not an interpolated
claim.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path


SWEEP_POINTS = [
    {"family": "brightness", "direction": "symmetric", "severity": 1 / 3, "label": "brightness_pm05", "args": ["--brightness-range", "0.95", "1.05"]},
    {"family": "brightness", "direction": "symmetric", "severity": 2 / 3, "label": "brightness_pm15", "args": ["--brightness-range", "0.85", "1.15"]},
    {"family": "brightness", "direction": "symmetric", "severity": 1.0, "label": "brightness_pm25", "args": ["--brightness-range", "0.75", "1.25"]},
    {"family": "rgb_noise", "direction": "positive", "severity": 1 / 3, "label": "rgb_noise_std2", "args": ["--image-noise-std", "2"]},
    {"family": "rgb_noise", "direction": "positive", "severity": 2 / 3, "label": "rgb_noise_std4", "args": ["--image-noise-std", "4"]},
    {"family": "rgb_noise", "direction": "positive", "severity": 1.0, "label": "rgb_noise_std8", "args": ["--image-noise-std", "8"]},
    {"family": "occlusion", "direction": "positive", "severity": 1 / 3, "label": "occlusion_fraction10", "args": ["--occlusion-prob", "1.0", "--occlusion-fraction", "0.10"]},
    {"family": "occlusion", "direction": "positive", "severity": 2 / 3, "label": "occlusion_fraction25", "args": ["--occlusion-prob", "1.0", "--occlusion-fraction", "0.25"]},
    {"family": "occlusion", "direction": "positive", "severity": 1.0, "label": "occlusion_fraction40", "args": ["--occlusion-prob", "1.0", "--occlusion-fraction", "0.40"]},
    {"family": "action_delay", "direction": "positive", "severity": 1 / 3, "label": "action_delay_1", "args": ["--action-delay-steps", "1"]},
    {"family": "action_delay", "direction": "positive", "severity": 2 / 3, "label": "action_delay_2", "args": ["--action-delay-steps", "2"]},
    {"family": "action_delay", "direction": "positive", "severity": 1.0, "label": "action_delay_4", "args": ["--action-delay-steps", "4"]},
    {"family": "friction", "direction": "low", "severity": 1 / 3, "label": "friction_low_1p4", "args": ["--cube-friction", "1.4"]},
    {"family": "friction", "direction": "low", "severity": 2 / 3, "label": "friction_low_1p2", "args": ["--cube-friction", "1.2"]},
    {"family": "friction", "direction": "low", "severity": 1.0, "label": "friction_low_1p0", "args": ["--cube-friction", "1.0"]},
    {"family": "friction", "direction": "high", "severity": 1 / 3, "label": "friction_high_1p6", "args": ["--cube-friction", "1.6"]},
    {"family": "friction", "direction": "high", "severity": 2 / 3, "label": "friction_high_1p8", "args": ["--cube-friction", "1.8"]},
    {"family": "friction", "direction": "high", "severity": 1.0, "label": "friction_high_2p0", "args": ["--cube-friction", "2.0"]},
]


def run_point(args, point: dict | None) -> dict:
    label = "nominal" if point is None else point["label"]
    run_name = f"robustness_sweep_{label}"
    run_dir = args.output_dir / "eval" / run_name
    summary_path = run_dir / "eval_summary.json"
    if args.skip_existing and summary_path.exists():
        summary = json.loads(summary_path.read_text(encoding="utf-8"))
        print(f"[sweep] reuse {label}: {summary['success_rate']:.1%}")
    else:
        command = [
            sys.executable,
            str(Path(__file__).with_name("04_eval_custom_scene.py")),
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
            command.append("--render-cpu")
        if args.record_video:
            command.append("--record-video")
        if point is not None:
            command.extend(point["args"])
        print("[sweep] running:", " ".join(command))
        subprocess.run(command, check=True)
        summary = json.loads(summary_path.read_text(encoding="utf-8"))

    return {
        "label": label,
        "family": "nominal" if point is None else point["family"],
        "direction": "control" if point is None else point["direction"],
        "severity": 0.0 if point is None else float(point["severity"]),
        "parameter": [] if point is None else point["args"],
        "episodes": int(summary["n_episodes"]),
        "success": int(summary["n_success"]),
        "success_rate": float(summary["success_rate"]),
        "summary": str(summary_path),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--checkpoint", required=True)
    parser.add_argument("--dataset-id", required=True)
    parser.add_argument("--episode-manifest", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, default=Path("output"))
    parser.add_argument("--n-episodes", type=int, default=20)
    parser.add_argument("--max-steps", type=int, default=150)
    parser.add_argument("--seed", type=int, default=99)
    parser.add_argument("--task", default="Pick up the cube.")
    parser.add_argument("--policy-type", default="smolvla")
    parser.add_argument("--camera-layout", default="up_wrist")
    parser.add_argument("--render-cpu", action="store_true")
    parser.add_argument("--record-video", action="store_true",
                        help="Record every sweep run; use only for a small demo sweep.")
    parser.add_argument("--skip-existing", action="store_true")
    args = parser.parse_args()
    if not args.episode_manifest.exists():
        parser.error(f"manifest does not exist: {args.episode_manifest}")

    rows = [run_point(args, None)]
    rows.extend(run_point(args, point) for point in SWEEP_POINTS)
    payload = {
        "checkpoint": args.checkpoint,
        "dataset_id": args.dataset_id,
        "episode_manifest": str(args.episode_manifest),
        "seed": args.seed,
        "n_episodes": args.n_episodes,
        "paired_manifest": True,
        "nominal_control": "nominal",
        "severity_definition": "0 is nominal; 1 is the maximum listed stress for each family",
        "points": rows,
    }
    out_dir = args.output_dir / "eval" / "robustness_sweep"
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / "robustness_sweep_runs.json"
    out.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(f"[sweep] wrote {out}")


if __name__ == "__main__":
    main()
