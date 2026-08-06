"""Fine-tune SmolVLA on the SO-101 synthetic dataset (thin lerobot-train wrapper).

This does not reimplement training -- it assembles the right ``lerobot-train`` CLI
wired to this project's conventions:

  * dataset lives under ``datasets/<name>``
  * runs are written to ``outputs/train/<job-name>``
  * ``checkpoints/last/pretrained_model`` is what ``vla/inference.py --checkpoint``
    and ``scripts/run_demo.py`` expect.

SmolVLA is fine-tuned from the pretrained base ``lerobot/smolvla_base`` with the
camera rename world/wrist -> camera1/camera2 (see vla/agent.py). ACT is also
available (trained from scratch, no rename).

Usage (on the Radeon machine):
    python training/finetune.py smolvla --repo-id so101/cube_pick \\
        --dataset-root datasets/cube_pick --steps 20000

    python training/finetune.py smolvla --repo-id so101/cube_pick --dry-run

Everything after ``--`` is forwarded verbatim to lerobot-train.

NOTE: On ROCm, ``--device cuda`` selects the AMD GPU (ROCm torch maps CUDA->HIP).
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from paths import DATASETS_DIR, TRAIN_DIR

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
    output_dir = args.output_dir or str(TRAIN_DIR / job_name)

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
    # pyav decoder by default (torchcodec needs system FFmpeg libs; unreliable on ROCm).
    if args.video_backend:
        cmd.append(f"--dataset.video_backend={args.video_backend}")

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
        description="Thin wrapper around lerobot-train (SmolVLA / ACT presets) for SO-101.",
        epilog="Anything after `--` is forwarded verbatim to lerobot-train.",
    )
    parser.add_argument("policy", choices=sorted(PRESETS), help="Built-in preset to train.")
    parser.add_argument("--repo-id", required=True)
    parser.add_argument("--dataset-root", default=None, help="Default: datasets/<repo-name>.")
    parser.add_argument("--name", default=None)
    parser.add_argument("--output-dir", default=None)
    parser.add_argument("--steps", type=int, default=20000)
    parser.add_argument("--batch-size", type=int, default=None)
    parser.add_argument("--save-freq", type=int, default=10000)
    parser.add_argument("--log-freq", type=int, default=200)
    parser.add_argument("--num-workers", type=int, default=4)
    parser.add_argument("--seed", type=int, default=1000)
    parser.add_argument("--device", default="cuda", help="cuda (=AMD GPU on ROCm) | cpu | mps.")
    parser.add_argument("--video-backend", default="pyav")
    parser.add_argument("--wandb", action="store_true")
    parser.add_argument("--push-to-hub", action="store_true")
    parser.add_argument("--rename-map", default=None, help="JSON override of the camera rename map.")
    parser.add_argument("--policy-type", default=None, help="Train this lerobot policy type from scratch.")
    parser.add_argument("--policy-path", default=None, help="Fine-tune from this checkpoint/base.")
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
