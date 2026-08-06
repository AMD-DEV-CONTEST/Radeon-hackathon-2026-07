"""M5 helper: thin, policy-agnostic wrapper around ``lerobot-train``.

This does not reimplement training -- it just assembles the right CLI for
lerobot's own trainer, wired to this project's conventions:

  * datasets live under ``datasets/<name>``
  * runs are written to ``outputs/train/<job-name>``
  * the resulting ``checkpoints/last/pretrained_model`` dir is exactly what
    ``eval_policy.py --policy-path`` expects.

Two presets are built in (``act`` and ``smolvla``), but any lerobot policy can
be trained via ``--policy-type`` / ``--policy-path``. Everything after ``--`` is
forwarded verbatim to ``lerobot-train`` for advanced overrides.

Usage:
    # ACT on the 50-episode banana dataset
    uv run python franka_fruit_pick/train_policy.py act \
        --repo-id genesis/banana_pick \
        --dataset-root datasets/banana_pick_50ep

    # SmolVLA (fine-tuned from the pretrained base), fewer steps
    uv run python franka_fruit_pick/train_policy.py smolvla \
        --repo-id genesis/banana_pick \
        --dataset-root datasets/banana_pick_50ep \
        --steps 20000

    # Just print the command without running it
    uv run python franka_fruit_pick/train_policy.py act --repo-id genesis/x --dry-run

    # Forward extra lerobot flags (after --)
    uv run python franka_fruit_pick/train_policy.py act --repo-id genesis/x -- \
        --policy.optimizer_lr=1e-4 --policy.chunk_size=50
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
#
# `rename_map` (optional): maps this project's dataset image keys to the keys the
# pretrained policy expects. SmolVLA's base (`lerobot/smolvla_base`) is trained
# with canonical camera keys `observation.images.camera{1,2,3}`, but our datasets
# use `world` / `wrist`. lerobot bakes this rename into the *saved* preprocessor
# (a `rename_observations_processor`), so eval_policy.py needs no change -- it can
# keep feeding `world`/`wrist` and the checkpoint renames them internally. ACT has
# no such constraint (it adapts its input features to the dataset), so no rename.
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
    output_dir = args.output_dir or f"outputs/train/{job_name}"

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
    # Default to the pyav decoder: torchcodec needs system FFmpeg shared libs
    # (libavutil.so.*) and is ABI-tied to the torch build, which is unreliable on
    # this ROCm setup. `pyav` (bundled with `av`) works out of the box. A user
    # override in `passthrough` takes precedence (appended after, last wins).
    if args.video_backend:
        cmd.append(f"--dataset.video_backend={args.video_backend}")

    # Camera-key rename (see PRESETS docstring). Explicit --rename-map wins; else
    # fall back to the preset default unless the user already passed one through.
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
    parser.add_argument("--repo-id", required=True, help="Dataset repo id (e.g. genesis/banana_pick).")
    parser.add_argument(
        "--dataset-root",
        default=None,
        help="Local dataset dir (default: datasets/<repo-name>).",
    )
    parser.add_argument("--name", default=None, help="Job/output name (default: <policy>_<dataset-dir>).")
    parser.add_argument("--output-dir", default=None, help="Run output dir (default: outputs/train/<name>).")
    parser.add_argument("--steps", type=int, default=20000, help="Training steps.")
    parser.add_argument("--batch-size", type=int, default=None, help="Override the preset batch size.")
    parser.add_argument("--save-freq", type=int, default=10000, help="Checkpoint every N steps (and at the end).")
    parser.add_argument("--log-freq", type=int, default=200)
    parser.add_argument("--num-workers", type=int, default=4)
    parser.add_argument("--seed", type=int, default=1000)
    parser.add_argument("--device", default="cuda", help="Training device (cuda | cpu | mps).")
    parser.add_argument(
        "--video-backend",
        default="pyav",
        help="Dataset video decoder (default: pyav; torchcodec needs system FFmpeg libs). "
        "Pass an empty string to leave lerobot's default.",
    )
    parser.add_argument("--wandb", action="store_true", help="Enable Weights & Biases logging.")
    parser.add_argument("--push-to-hub", action="store_true", help="Push the trained policy to the HF Hub.")
    parser.add_argument(
        "--rename-map",
        default=None,
        help="JSON dict mapping dataset image keys to the policy's expected keys "
        "(forwarded as lerobot --rename_map). Overrides the preset default; pass '{}' to disable. "
        "The smolvla preset auto-maps world/wrist -> camera1/camera2.",
    )
    parser.add_argument(
        "--policy-type",
        default=None,
        help="Override: train this lerobot policy type from scratch (e.g. diffusion). Ignores the preset.",
    )
    parser.add_argument(
        "--policy-path",
        default=None,
        help="Override: fine-tune from this pretrained checkpoint/base. Ignores the preset.",
    )
    parser.add_argument("--dry-run", action="store_true", help="Print the command and exit.")
    args, passthrough = parser.parse_known_args()

    # Drop a leading `--` separator (argparse leaves it in the remainder).
    if passthrough and passthrough[0] == "--":
        passthrough = passthrough[1:]

    cmd = build_command(args, passthrough)

    print("[train] " + " ".join(cmd))
    if args.dry_run:
        return

    raise SystemExit(subprocess.call(cmd))


if __name__ == "__main__":
    main()
