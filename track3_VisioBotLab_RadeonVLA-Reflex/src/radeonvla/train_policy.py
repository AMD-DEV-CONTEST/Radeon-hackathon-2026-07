"""Thin wrapper around ``lerobot-train`` with SmolVLA defaults for this project."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

from radeonvla.paths import DATASETS_DIR, PROJECT_ROOT, TRAIN_DIR
from radeonvla.protocol import SMOLVLA_INPUT_FEATURES, SMOLVLA_RENAME_MAP

SMOLVLA_BASE_REVISION = "c83c3163b8ca9b7e67c509fffd9121e66cb96205"

PRESETS: dict[str, dict] = {
    "smolvla": {
        "policy_arg": ("path", "lerobot/smolvla_base"),
        "pretrained_revision": SMOLVLA_BASE_REVISION,
        "batch_size": 4,
        "rename_map": SMOLVLA_RENAME_MAP,
        "input_features": SMOLVLA_INPUT_FEATURES,
    },
    "act": {
        "policy_arg": ("type", "act"),
        "batch_size": 8,
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
        sys.executable,
        "-m",
        "lerobot.scripts.lerobot_train",
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
    hub_model_id = getattr(args, "hub_model_id", None)
    if args.push_to_hub:
        if not hub_model_id:
            raise ValueError("--push-to-hub requires --hub-model-id so weights are never sent to an implicit repo")
        cmd.append(f"--policy.repo_id={hub_model_id}")
    if args.video_backend:
        cmd.append(f"--dataset.video_backend={args.video_backend}")

    passthrough_has_revision = any(p.startswith("--policy.pretrained_revision") for p in passthrough)
    if not passthrough_has_revision:
        preset_revision = PRESETS[args.policy].get("pretrained_revision")
        if preset_revision:
            cmd.append(f"--policy.pretrained_revision={preset_revision}")

    passthrough_has_rename = any(p.startswith("--rename_map") for p in passthrough)
    if args.rename_map is not None:
        cmd.append(f"--rename_map={args.rename_map}")
    elif not passthrough_has_rename:
        preset_rename = PRESETS[args.policy].get("rename_map")
        if preset_rename:
            cmd.append(f"--rename_map={json.dumps(preset_rename)}")

    passthrough_has_inputs = any(p.startswith("--policy.input_features") for p in passthrough)
    if not passthrough_has_inputs:
        preset_inputs = PRESETS[args.policy].get("input_features")
        if preset_inputs:
            # A pretrained config otherwise keeps the base checkpoint's 6-D
            # state declaration even though this dataset contains 9-D states.
            cmd.append("--policy.input_features=" + json.dumps(preset_inputs, separators=(",", ":")))

    cmd += passthrough
    return cmd


def parse_args(argv: list[str] | None = None) -> tuple[argparse.Namespace, list[str]]:
    parser = argparse.ArgumentParser(
        description=__doc__,
        epilog="Anything after `--` is forwarded to lerobot-train.",
    )
    parser.add_argument("policy", nargs="?", default="smolvla", choices=sorted(PRESETS))
    parser.add_argument("--config", type=Path, default=PROJECT_ROOT / "configs" / "train.yaml")
    parser.add_argument("--repo-id", default="visiobot/radeonvla_reflex")
    parser.add_argument("--dataset-root", default=None)
    parser.add_argument("--name", default=None)
    parser.add_argument("--output-dir", default=None)
    parser.add_argument("--steps", type=int, default=10000)
    parser.add_argument("--batch-size", type=int, default=None)
    parser.add_argument("--save-freq", type=int, default=2000)
    parser.add_argument("--log-freq", type=int, default=200)
    parser.add_argument("--num-workers", type=int, default=4)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--device", default="cuda")
    parser.add_argument("--video-backend", default="pyav")
    parser.add_argument("--wandb", action="store_true")
    parser.add_argument("--push-to-hub", action="store_true")
    parser.add_argument("--hub-model-id", default=None, help="Required Hub model repo when --push-to-hub is set.")
    parser.add_argument("--rename-map", default=None)
    parser.add_argument("--policy-type", default=None)
    parser.add_argument("--policy-path", default=None)
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_known_args(argv)


def main(argv: list[str] | None = None) -> int:
    args, passthrough = parse_args(argv)
    if passthrough and passthrough[0] == "--":
        passthrough = passthrough[1:]
    cmd = build_command(args, passthrough)
    print("[train] " + " ".join(cmd))
    if args.dry_run:
        return 0
    return subprocess.call(cmd)


if __name__ == "__main__":
    raise SystemExit(main())
