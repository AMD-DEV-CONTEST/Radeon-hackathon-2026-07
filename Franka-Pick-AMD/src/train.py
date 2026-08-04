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
    ap.add_argument("--lr", type=float, default=None, help="Peak learning rate (defaults to cfg.optimizer_lr)")
    ap.add_argument(
        "--lr-warmup-steps",
        type=int,
        default=200,
        help="Linear warmup steps. 0 disables.",
    )
    ap.add_argument(
        "--lr-decay-steps",
        type=int,
        default=2000,
        help="Cosine decay steps (peak_lr → decay_lr).",
    )
    ap.add_argument(
        "--lr-decay-end",
        type=float,
        default=1e-5,
        help="Minimum LR after cosine decay.",
    )
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
        "--vlm-backbone",
        default="HuggingFaceTB/SmolVLM2-500M-Video-Instruct",
        help="Path or HF model id for the VLM backbone (e.g. SmolVLM2-500M-Video-Instruct).",
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

    from lerobot.configs.types import FeatureType
    from lerobot.datasets.lerobot_dataset import (
        LeRobotDataset,
        LeRobotDatasetMetadata,
    )
    from lerobot.utils.feature_utils import dataset_to_policy_features
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
        chunk_size=30,
        n_action_steps=30,
        freeze_vision_encoder=True,
        train_expert_only=True,
        train_state_proj=True,
        vlm_model_name=args.vlm_backbone,
        optimizer_lr=args.lr if args.lr is not None else 1e-4,
        scheduler_warmup_steps=args.lr_warmup_steps,
        scheduler_decay_steps=args.lr_decay_steps,
        scheduler_decay_lr=args.lr_decay_end,
    )

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

    # ---- optimizer & scheduler (LeRobot official presets) ----
    opt_cfg = cfg.get_optimizer_preset()
    optimizer = opt_cfg.build(policy.get_optim_params())
    peak_lr = opt_cfg.lr
    print(f"[train] optimizer: {type(optimizer).__name__} lr={peak_lr} "
          f"betas={cfg.optimizer_betas} weight_decay={cfg.optimizer_weight_decay}")

    sch_cfg = cfg.get_scheduler_preset()
    scheduler = sch_cfg.build(optimizer, args.n_steps)
    print(f"[train] scheduler: warmup={sch_cfg.num_warmup_steps} "
          f"decay={sch_cfg.num_decay_steps} "
          f"peak_lr={sch_cfg.peak_lr}→{sch_cfg.decay_lr}")

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

            optimizer.zero_grad()

            with torch.autocast(
                device_type="cuda", dtype=amp_dtype, enabled=amp_enabled
            ):
                loss, info = policy.forward(batch)

            loss.backward()

            grad_norm = torch.nn.utils.clip_grad_norm_(
                optimizer.param_groups[0]["params"], cfg.optimizer_grad_clip_norm
            )
            current_lr = optimizer.param_groups[0]["lr"]
            optimizer.step()
            if scheduler is not None:
                scheduler.step()
            step_time = time.time() - t0         
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
                    f"lr {current_lr:.2e} | "
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
        "lr": float(peak_lr),
        "lr_decay_steps": args.lr_decay_steps,
        "lr_decay_end": args.lr_decay_end,
        "lr_warmup_steps": args.lr_warmup_steps,
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
        "vlm_backbone": args.vlm_backbone,
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
