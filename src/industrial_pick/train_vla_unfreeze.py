"""
Phase 1 SmolVLA post-training on Genesis synthetic pick data.

Loads a local LeRobot dataset (from 01_gen_data.py) and fine-tunes
lerobot/smolvla_base for N steps. Logs per-step metrics to JSON for analysis.

Default training recipe (workshop preset):
  - BF16 mixed-precision via torch.autocast (AMP) on CUDA
  - PyTorch SDPA auto-dispatch (flash/efficient/math, AOTriton on AMD)
  - Constant LR from SmolVLAConfig
  - Vision encoder frozen, expert + state projection trainable

Usage:
  python scripts/02_train_vla.py --dataset-id local/so101-genesis-pick --n-steps 2000
  python scripts/02_train_vla.py --dataset-id local/so101-genesis-pick --n-steps 100 --batch-size 2
"""

from __future__ import annotations

import argparse
import json
import random
import time
from pathlib import Path

import numpy as np
import torch


def make_delta_timestamps(delta_indices, fps: int):
    if delta_indices is None:
        return [0.0]
    return [i / fps for i in delta_indices]


def main():
    ap = argparse.ArgumentParser(description="SmolVLA post-train on Genesis pick data")
    ap.add_argument("--dataset-id", default="local/so101-genesis-pick")
    ap.add_argument("--pretrained", default="lerobot/smolvla_base")
    ap.add_argument("--n-steps", type=int, default=2000)
    ap.add_argument("--batch-size", type=int, default=8)
    ap.add_argument("--lr", type=float, default=None, help="Override learning rate")
    ap.add_argument("--output-dir", default="./output")
    ap.add_argument(
        "--run-name",
        default="smolvla_pick",
        help="Subfolder under output-dir/train/ for this run",
    )
    ap.add_argument("--log-every", type=int, default=50)
    ap.add_argument("--save-every", type=int, default=500)
    ap.add_argument(
        "--num-workers",
        type=int,
        default=2,
        help="Dataloader workers. Use 0 to avoid occasional video decoder worker crashes.",
    )
    ap.add_argument(
        "--seed",
        type=int,
        default=None,
        help="Seed for torch / numpy / random (affects weight init, shuffling, dropout). "
        "Omit for non-deterministic run (prior default behaviour).",
    )
    ap.add_argument(
        "--finger-loss-weight",
        type=float,
        default=1.0,
        help="Extra loss weight for finger action dims (7,8). >1.0 forces the model "
        "to learn finger open/close timing more aggressively.",
    )
    ap.add_argument(
        "--unfreeze-vision-last",
        type=int,
        default=0,
        help="Unfreeze the last K vision-encoder blocks (+ post_layernorm) after loading. "
        "0 keeps the workshop default (whole vision tower frozen). The unfrozen blocks "
        "train at --vision-lr-scale x the base LR.",
    )
    ap.add_argument(
        "--vision-lr-scale",
        type=float,
        default=0.1,
        help="LR multiplier for the blocks unfrozen via --unfreeze-vision-last.",
    )
    args = ap.parse_args()

    if args.seed is not None:
        random.seed(args.seed)
        np.random.seed(args.seed)
        torch.manual_seed(args.seed)
        if torch.cuda.is_available():
            torch.cuda.manual_seed_all(args.seed)
        print(f"[train] seed: {args.seed}")

    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    print(f"[train] device: {device}")
    if torch.cuda.is_available():
        for i in range(torch.cuda.device_count()):
            props = torch.cuda.get_device_properties(i)
            print(
                f"  GPU[{i}]: {props.name}  VRAM: {props.total_memory / 1024**3:.1f} GB"
            )

    try:
        from lerobot.configs.types import FeatureType
        from lerobot.common.datasets.lerobot_dataset import (
            LeRobotDataset,
            LeRobotDatasetMetadata,
        )
        from lerobot.common.datasets.utils import dataset_to_policy_features
        from lerobot.policies.smolvla.configuration_smolvla import SmolVLAConfig
        from lerobot.policies.smolvla.modeling_smolvla import SmolVLAPolicy
        from lerobot.policies.factory import make_pre_post_processors
    except ImportError:
        from lerobot.configs.types import FeatureType
        from lerobot.datasets.lerobot_dataset import (
            LeRobotDataset,
            LeRobotDatasetMetadata,
        )
        from lerobot.datasets.utils import dataset_to_policy_features
        from lerobot.policies.smolvla.configuration_smolvla import SmolVLAConfig
        from lerobot.policies.smolvla.modeling_smolvla import SmolVLAPolicy
        from lerobot.policies.factory import make_pre_post_processors

    # ---- dataset ----
    print(f"\n[train] loading dataset: {args.dataset_id}")
    dataset_metadata = LeRobotDatasetMetadata(args.dataset_id)
    print(f"  total_frames: {dataset_metadata.total_frames}")
    print(f"  episodes: {dataset_metadata.total_episodes}")
    print(f"  fps: {dataset_metadata.fps}")

    features = dataset_to_policy_features(dataset_metadata.features)
    output_features = {
        k: ft for k, ft in features.items() if ft.type is FeatureType.ACTION
    }
    input_features = {k: ft for k, ft in features.items() if k not in output_features}
    print(f"  input_features: {list(input_features.keys())}")
    print(f"  output_features: {list(output_features.keys())}")

    # ---- policy ----
    print(f"\n[train] loading SmolVLA from {args.pretrained}")
    cfg = SmolVLAConfig(
        input_features=input_features,
        output_features=output_features,
        chunk_size=50,
        n_action_steps=50,
        freeze_vision_encoder=True,
        train_expert_only=True,
        train_state_proj=True,
        finger_loss_weight=args.finger_loss_weight,
    )
    cfg.vlm_model_name = '/persistent/track3-robot/models/SmolVLM2-500M-Video-Instruct'

    try:
        policy = SmolVLAPolicy.from_pretrained(
            args.pretrained, config=cfg, strict=False
        )
    except Exception as e:
        print(f"[train] loading safetensors from local dir")
        from safetensors.torch import load_file

        policy = SmolVLAPolicy(config=cfg)
        st = load_file(str(Path(args.pretrained) / "model.safetensors"))
        policy.load_state_dict(st, strict=False)
    policy.train()
    policy.to(device)

    # Optionally unfreeze the last K vision-encoder blocks for fine-grained spatial
    # regression (e.g. thin-part grasp alignment). Construction still used
    # freeze_vision_encoder=True, so only the blocks named here ever get grads.
    vision_param_names: list[str] = []
    if args.unfreeze_vision_last > 0:
        import re as _re

        n_layers = max(
            int(m.group(1))
            for n, _ in policy.named_parameters()
            if (m := _re.search(r"vision_model\.encoder\.layers\.(\d+)\.", n))
        ) + 1
        keep_from = n_layers - args.unfreeze_vision_last
        for name, p in policy.named_parameters():
            layer_m = _re.search(r"vision_model\.encoder\.layers\.(\d+)\.", name)
            in_tail_block = layer_m is not None and int(layer_m.group(1)) >= keep_from
            if in_tail_block or "vision_model.post_layernorm" in name:
                p.requires_grad = True
                vision_param_names.append(name)
        print(
            f"[train] unfroze vision layers {keep_from}..{n_layers - 1} + post_layernorm: "
            f"{len(vision_param_names)} tensors"
        )

    total_params = sum(p.numel() for p in policy.parameters())
    trainable_params = sum(p.numel() for p in policy.parameters() if p.requires_grad)
    print(f"  total params: {total_params:,} (~{total_params/1e6:.0f}M)")
    print(f"  trainable: {trainable_params:,} (~{trainable_params/1e6:.1f}M)")
    print(f"  frozen: {total_params - trainable_params:,}")

    # AMP BF16 is always on when CUDA is available (workshop preset).
    amp_enabled = device.type == "cuda"
    amp_dtype = torch.bfloat16 if amp_enabled else None
    if amp_enabled:
        print(f"[train] AMP enabled: dtype={amp_dtype}")

    preprocessor, postprocessor = make_pre_post_processors(
        cfg,
        dataset_stats=dataset_metadata.stats,
    )

    # ---- dataloader ----
    fps = dataset_metadata.fps
    delta_timestamps = {
        "action": make_delta_timestamps(cfg.action_delta_indices, fps),
    }
    for img_key in cfg.image_features:
        delta_timestamps[img_key] = make_delta_timestamps(
            cfg.observation_delta_indices, fps
        )
    delta_timestamps["observation.state"] = make_delta_timestamps(
        cfg.observation_delta_indices, fps
    )

    dataset = LeRobotDataset(
        args.dataset_id,
        delta_timestamps=delta_timestamps,
    )
    dataloader = torch.utils.data.DataLoader(
        dataset,
        batch_size=args.batch_size,
        shuffle=True,
        num_workers=args.num_workers,
        pin_memory=torch.cuda.is_available(),
        drop_last=True,
    )
    print(
        f"\n[train] dataloader: {len(dataset)} samples, "
        f"batch_size={args.batch_size}, num_workers={args.num_workers}"
    )

    # ---- optimizer ----
    lr = args.lr if args.lr is not None else cfg.optimizer_lr
    if vision_param_names:
        vision_set = set(vision_param_names)
        groups = [
            {
                "params": [p for n, p in policy.named_parameters() if p.requires_grad and n not in vision_set],
                "lr": lr,
            },
            {
                "params": [p for n, p in policy.named_parameters() if p.requires_grad and n in vision_set],
                "lr": lr * args.vision_lr_scale,
            },
        ]
        trainable = [p for g in groups for p in g["params"]]
    else:
        trainable = [p for p in policy.parameters() if p.requires_grad]
        groups = [{"params": trainable, "lr": lr}]
    optimizer = torch.optim.AdamW(
        groups,
        lr=lr,
        betas=cfg.optimizer_betas,
        eps=cfg.optimizer_eps,
        weight_decay=cfg.optimizer_weight_decay,
    )
    print(f"[train] optimizer: AdamW lr={lr}"
          + (f" (vision blocks @ {lr * args.vision_lr_scale:g})" if vision_param_names else ""))

    # ---- training loop ----
    save_dir = Path(args.output_dir) / "train" / args.run_name
    save_dir.mkdir(parents=True, exist_ok=True)

    metrics_log = []
    step = 0
    epoch = 0
    t_start = time.time()

    print(f"\n[train] starting {args.n_steps} steps...")
    while step < args.n_steps:
        epoch += 1
        for batch in dataloader:
            if step >= args.n_steps:
                break

            t0 = time.time()
            batch = preprocessor(batch)

            with torch.autocast(
                device_type="cuda", dtype=amp_dtype, enabled=amp_enabled
            ):
                loss, info = policy.forward(batch)

            loss.backward()

            grad_norm = torch.nn.utils.clip_grad_norm_(
                trainable, cfg.optimizer_grad_clip_norm
            )
            optimizer.step()
            optimizer.zero_grad()
            step_time = time.time() - t0

            current_lr = optimizer.param_groups[0]["lr"]
            record = {
                "step": step,
                "epoch": epoch,
                "loss": float(loss.item()),
                "grad_norm": (
                    float(grad_norm.item())
                    if hasattr(grad_norm, "item")
                    else float(grad_norm)
                ),
                "lr": float(current_lr),
                "step_time_s": float(step_time),
            }
            metrics_log.append(record)

            if step % args.log_every == 0 or step == args.n_steps - 1:
                elapsed = time.time() - t_start
                print(
                    f"  step {step:5d}/{args.n_steps} | loss {record['loss']:.4f} | "
                    f"grad_norm {record['grad_norm']:.4f} | "
                    f"{step_time:.2f}s/step | elapsed {elapsed:.0f}s"
                )

            if args.save_every > 0 and step > 0 and step % args.save_every == 0:
                ckpt_dir = save_dir / f"checkpoint_{step:06d}"
                policy.save_pretrained(ckpt_dir)
                print(f"  [ckpt] saved to {ckpt_dir}")

            step += 1

    # ---- save final ----
    elapsed = time.time() - t_start
    print(f"\n[train] done: {step} steps, {epoch} epochs, {elapsed:.0f}s")

    peak_mb = None
    if torch.cuda.is_available():
        peak_mb = torch.cuda.max_memory_allocated() / 1024**2
        print(f"  peak VRAM: {peak_mb:.0f} MB ({peak_mb/1024:.2f} GB)")

    final_dir = save_dir / "final"
    policy.save_pretrained(final_dir)
    preprocessor.save_pretrained(final_dir)
    postprocessor.save_pretrained(final_dir)
    print(f"  model saved: {final_dir}")

    # ---- save metrics ----
    metrics_summary = {
        "dataset_id": args.dataset_id,
        "pretrained": args.pretrained,
        "n_steps": step,
        "n_epochs": epoch,
        "batch_size": args.batch_size,
        "num_workers": int(args.num_workers),
        "lr": float(lr),
        "amp": amp_enabled,
        "total_time_s": float(elapsed),
        "final_loss": float(metrics_log[-1]["loss"]) if metrics_log else None,
        "loss_start": float(metrics_log[0]["loss"]) if metrics_log else None,
        "loss_end": float(metrics_log[-1]["loss"]) if metrics_log else None,
        "peak_vram_mb": float(peak_mb) if peak_mb is not None else None,
        "trainable_params": trainable_params,
        "total_params": total_params,
        "device": str(device),
        "seed": args.seed,
        "finger_loss_weight": args.finger_loss_weight,
        "unfreeze_vision_last": args.unfreeze_vision_last,
        "vision_lr_scale": args.vision_lr_scale,
    }
    (save_dir / "train_summary.json").write_text(
        json.dumps(metrics_summary, indent=2), encoding="utf-8"
    )
    (save_dir / "train_metrics.json").write_text(
        json.dumps(metrics_log, indent=2), encoding="utf-8"
    )
    print(f"  metrics saved: {save_dir / 'train_summary.json'}")
    print(
        f"  per-step log: {save_dir / 'train_metrics.json'} ({len(metrics_log)} records)"
    )


if __name__ == "__main__":
    main()
