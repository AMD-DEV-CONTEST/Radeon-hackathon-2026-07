"""Thin, policy-agnostic wrapper around ``lerobot-train``.

Based on franka_fruit_pick_demo's train_policy.py. Key changes:
- Presets point to color_sort dataset conventions
- Default dataset root = datasets/<repo-name>

Usage:
    # ACT (Phase A baseline)
    python train_policy.py act --repo-id color_sort/train --steps 20000

    # SmolVLA (Phase B fine-tune)
    python train_policy.py smolvla --repo-id color_sort/train --steps 4000

    # Print the command without running
    python train_policy.py act --repo-id color_sort/train --dry-run
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from paths import DATASETS_DIR

# Per-preset defaults. `type` -> `--policy.type=<t>` (train from scratch);
# `path` -> `--policy.path=<p>` (fine-tune from a pretrained checkpoint/base).
PRESETS: dict[str, dict] = {
    "act": {"policy_arg": ("type", "act"), "batch_size": 8},
    "smolvla": {
        "policy_arg": ("path", "lerobot/smolvla_base"),
        "batch_size": 4,
        "rename_map": {
            "observation.images.world": "observation.images.camera1",
            "observation.images.wrist": "observation.images.camera2",
        },
    },
}


def build_command(args: argparse.Namespace, passthrough: list[str]) -> list[str]:
    if args.policy_path:
        policy_flag = f"--policy.path={args.policy_path}"
    elif args.policy_type:
        policy_flag = f"--policy.type={args.policy_type}"
    else:
        kind, value = PRESETS[args.policy]["policy_arg"]
        policy_flag = f"--policy.{kind}={value}"

    dataset_root = args.dataset_root or str(DATASETS_DIR / args.repo_id.split("/")[-1])
    batch_size = args.batch_size if args.batch_size is not None else PRESETS[args.policy]["batch_size"]
    job_name = args.name or f"{args.policy}_{Path(dataset_root).name}"
    output_dir = args.output_dir or f"../outputs/train/{job_name}"

    cmd = [
        sys.executable, "-m", "lerobot.scripts.lerobot_train",
        policy_flag,
        f"--dataset.repo_id={args.repo_id}",
        f"--dataset.root={dataset_root}",
        f"--output_dir={output_dir}",
        f"--job_name={job_name}",
        f"--batch_size={batch_size}",
        f"--steps={args.steps}",
        f"--save_freq={args.save_freq}",
        f"--log_freq={args.log_freq}",
        f"--num_workers={args.num_workers}",
        f"--seed={args.seed}",
        f"--policy.device={args.device}",
        f"--policy.push_to_hub={'true' if args.push_to_hub else 'false'}",
        f"--wandb.enable={'true' if args.wandb else 'false'}",
    ]
    # Default to pyav decoder (torchcodec needs system FFmpeg shared libs
    # which are unreliable on this ROCm setup).
    if args.video_backend:
        cmd.append(f"--dataset.video_backend={args.video_backend}")

    # Camera-key rename for SmolVLA
    passthrough_has_rename = any(p.startswith("--rename_map") for p in passthrough)
    if args.rename_map is not None:
        cmd.append(f"--rename_map={args.rename_map}")
    elif not passthrough_has_rename:
        preset_rename = PRESETS[args.policy].get("rename_map")
        if preset_rename:
            cmd.append(f"--rename_map={json.dumps(preset_rename)}")

    cmd += passthrough
    return cmd


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Thin wrapper around lerobot-train (ACT / SmolVLA presets).",
        epilog="Anything after `--` is forwarded verbatim to lerobot-train.",
    )
    parser.add_argument("policy", choices=sorted(PRESETS), help="Built-in preset to train.")
    parser.add_argument("--repo-id", required=True, help="Dataset repo id (e.g. color_sort/train).")
    parser.add_argument("--dataset-root", default=None, help="Local dataset dir (default: datasets/<repo-name>).")
    parser.add_argument("--name", default=None, help="Job/output name (default: <policy>_<dataset-dir>).")
    parser.add_argument("--output-dir", default=None, help="Run output dir (default: outputs/train/<name>).")
    parser.add_argument("--steps", type=int, default=20000, help="Training steps.")
    parser.add_argument("--batch-size", type=int, default=None, help="Override the preset batch size.")
    parser.add_argument("--save-freq", type=int, default=10000, help="Checkpoint every N steps (and at the end).")
    parser.add_argument("--log-freq", type=int, default=200)
    parser.add_argument("--num-workers", type=int, default=4)
    parser.add_argument("--seed", type=int, default=1000)
    parser.add_argument("--device", default="cuda", help="Training device (cuda | cpu | mps).")
    parser.add_argument("--video-backend", default="pyav", help="Dataset video decoder (default: pyav).")
    parser.add_argument("--wandb", action="store_true", help="Enable Weights & Biases logging.")
    parser.add_argument("--push-to-hub", action="store_true", help="Push the trained policy to the HF Hub.")
    parser.add_argument("--rename-map", default=None, help="JSON dict mapping dataset image keys to policy keys.")
    parser.add_argument("--policy-type", default=None, help="Override: train this lerobot policy type from scratch.")
    parser.add_argument("--policy-path", default=None, help="Override: fine-tune from this pretrained checkpoint.")
    parser.add_argument("--dry-run", action="store_true", help="Print the command and exit.")
    args, passthrough = parser.parse_known_args()

    if passthrough and passthrough[0] == "--":
        passthrough = passthrough[1:]

    cmd = build_command(args, passthrough)
    print("[train] " + " ".join(cmd))
    if args.dry_run:
        return
    raise SystemExit(subprocess.call(cmd))


if __name__ == "__main__":
    main()