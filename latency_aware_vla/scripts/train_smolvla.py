#!/usr/bin/env python3
"""B0: fine-tune SmolVLA on Env-A fruit pick-and-place.

Wraps the workshop training loop with hackathon defaults:
  - dataset: local/franka-kitchen-fruit-place-120ep
  - local SmolVLM backbone (offline-friendly)
  - fixed seed
  - auto-export conference-style loss curves at the end

Usage:
  export HF_LEROBOT_HOME=/workspace/cache/huggingface/lerobot
  python scripts/train_smolvla.py --n-steps 4000 --batch-size 4
"""

from __future__ import annotations

import argparse
import json
import os
import random
import subprocess
import sys
import time
from pathlib import Path

import numpy as np
import torch

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_VLM = "/workspace/models/SmolVLM2-500M-Video-Instruct"
DEFAULT_SMOLVLA = "/workspace/models/smolvla_base"


def make_delta_timestamps(delta_indices, fps: int):
    if delta_indices is None:
        return [0.0]
    return [i / fps for i in delta_indices]


def plot_after_train(save_dir: Path, run_name: str) -> None:
    metrics = save_dir / "train_metrics.json"
    summary = save_dir / "train_summary.json"
    if not metrics.exists():
        print("[train] skip plots: missing train_metrics.json")
        return
    out_prefix = ROOT / "artifacts" / "figures" / run_name
    cmd = [
        sys.executable,
        str(ROOT / "scripts" / "plot_train_curves.py"),
        "--metrics",
        str(metrics),
        "--summary",
        str(summary),
        "--out",
        str(out_prefix),
        "--title",
        f"SmolVLA · {run_name}",
    ]
    print("[train] plotting curves:", " ".join(cmd))
    subprocess.run(cmd, check=False)


def main():
    ap = argparse.ArgumentParser(description="SmolVLA B0 train on Env-A fruit place")
    ap.add_argument("--dataset-id", default="local/franka-kitchen-fruit-place-120ep")
    ap.add_argument("--pretrained", default=DEFAULT_SMOLVLA)
    ap.add_argument("--vlm-model", default=DEFAULT_VLM)
    ap.add_argument("--n-steps", type=int, default=4000)
    ap.add_argument("--batch-size", type=int, default=4)
    ap.add_argument("--lr", type=float, default=None)
    ap.add_argument("--output-dir", default=str(ROOT / "output"))
    ap.add_argument("--run-name", default="smolvla_fruit_place_b0")
    ap.add_argument("--log-every", type=int, default=20)
    ap.add_argument("--save-every", type=int, default=1000)
    ap.add_argument("--num-workers", type=int, default=2)
    ap.add_argument("--seed", type=int, default=2026)
    ap.add_argument("--no-plot", action="store_true")
    args = ap.parse_args()

    os.environ.setdefault("HF_LEROBOT_HOME", "/workspace/cache/huggingface/lerobot")
    os.environ.setdefault("HF_HOME", "/workspace/cache/huggingface")
    # Prefer local VLM; still allow hub if missing.
    if Path(args.vlm_model).exists():
        os.environ.setdefault("HF_HUB_OFFLINE", "1")
        os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")

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
        from lerobot.datasets.lerobot_dataset import (
            LeRobotDataset,
            LeRobotDatasetMetadata,
        )
        from lerobot.datasets.utils import dataset_to_policy_features
        from lerobot.policies.factory import make_pre_post_processors
        from lerobot.policies.smolvla.configuration_smolvla import SmolVLAConfig
        from lerobot.policies.smolvla.modeling_smolvla import SmolVLAPolicy
    except ImportError:
        from lerobot.configs.types import FeatureType
        from lerobot.common.datasets.lerobot_dataset import (
            LeRobotDataset,
            LeRobotDatasetMetadata,
        )
        from lerobot.common.datasets.utils import dataset_to_policy_features
        from lerobot.policies.factory import make_pre_post_processors
        from lerobot.policies.smolvla.configuration_smolvla import SmolVLAConfig
        from lerobot.policies.smolvla.modeling_smolvla import SmolVLAPolicy

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

    vlm_name = args.vlm_model if Path(args.vlm_model).exists() else args.vlm_model
    print(f"\n[train] loading SmolVLA from {args.pretrained}")
    print(f"[train] VLM backbone: {vlm_name}")
    cfg = SmolVLAConfig(
        input_features=input_features,
        output_features=output_features,
        chunk_size=50,
        n_action_steps=50,
        freeze_vision_encoder=True,
        train_expert_only=True,
        train_state_proj=True,
        vlm_model_name=vlm_name,
    )

    try:
        policy = SmolVLAPolicy.from_pretrained(
            args.pretrained, config=cfg, strict=False
        )
    except Exception as e:
        print(f"[train] from_pretrained failed ({e}); loading safetensors fallback")
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

    amp_enabled = device.type == "cuda"
    amp_dtype = torch.bfloat16 if amp_enabled else None
    if amp_enabled:
        print(f"[train] AMP enabled: dtype={amp_dtype}")

    preprocessor, postprocessor = make_pre_post_processors(
        cfg,
        dataset_stats=dataset_metadata.stats,
    )

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

    dataset = LeRobotDataset(args.dataset_id, delta_timestamps=delta_timestamps)
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

    trainable = [p for p in policy.parameters() if p.requires_grad]
    lr = args.lr if args.lr is not None else cfg.optimizer_lr
    optimizer = torch.optim.AdamW(
        trainable,
        lr=lr,
        betas=cfg.optimizer_betas,
        eps=cfg.optimizer_eps,
        weight_decay=cfg.optimizer_weight_decay,
    )
    print(f"[train] optimizer: AdamW lr={lr}")

    save_dir = Path(args.output_dir) / "train" / args.run_name
    save_dir.mkdir(parents=True, exist_ok=True)
    (save_dir / "run_config.json").write_text(
        json.dumps(vars(args), indent=2) + "\n", encoding="utf-8"
    )

    metrics_log = []
    step = 0
    epoch = 0
    t_start = time.time()
    # live CSV for mid-run plotting
    csv_path = save_dir / "train_metrics.csv"
    with csv_path.open("w", encoding="utf-8") as f:
        f.write("step,epoch,loss,grad_norm,lr,step_time_s\n")

    print(f"\n[train] starting {args.n_steps} steps → {save_dir}")
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

            record = {
                "step": step,
                "epoch": epoch,
                "loss": float(loss.item()),
                "grad_norm": (
                    float(grad_norm.item())
                    if hasattr(grad_norm, "item")
                    else float(grad_norm)
                ),
                "lr": float(optimizer.param_groups[0]["lr"]),
                "step_time_s": float(step_time),
            }
            metrics_log.append(record)
            with csv_path.open("a", encoding="utf-8") as f:
                f.write(
                    f"{record['step']},{record['epoch']},{record['loss']:.8f},"
                    f"{record['grad_norm']:.8f},{record['lr']:.8e},{record['step_time_s']:.6f}\n"
                )

            if step % args.log_every == 0 or step == args.n_steps - 1:
                elapsed = time.time() - t_start
                print(
                    f"  step {step:5d}/{args.n_steps} | loss {record['loss']:.4f} | "
                    f"grad_norm {record['grad_norm']:.4f} | "
                    f"{step_time:.2f}s/step | elapsed {elapsed:.0f}s",
                    flush=True,
                )
                # mid-run JSON snapshot for live plotting
                (save_dir / "train_metrics.json").write_text(
                    json.dumps(metrics_log, indent=2), encoding="utf-8"
                )

            if args.save_every > 0 and step > 0 and step % args.save_every == 0:
                ckpt_dir = save_dir / f"checkpoint_{step:06d}"
                policy.save_pretrained(ckpt_dir)
                print(f"  [ckpt] saved to {ckpt_dir}", flush=True)

            step += 1

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

    metrics_summary = {
        "run_name": args.run_name,
        "dataset_id": args.dataset_id,
        "pretrained": args.pretrained,
        "vlm_model": vlm_name,
        "task": "Pick up the fruit and place it in the basket.",
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
        "chunk_size": 50,
        "freeze_vision_encoder": True,
        "train_expert_only": True,
    }
    (save_dir / "train_summary.json").write_text(
        json.dumps(metrics_summary, indent=2), encoding="utf-8"
    )
    (save_dir / "train_metrics.json").write_text(
        json.dumps(metrics_log, indent=2), encoding="utf-8"
    )
    # also copy into artifacts for submission
    art = ROOT / "artifacts" / "formal" / args.run_name
    art.mkdir(parents=True, exist_ok=True)
    (art / "train_summary.json").write_text(
        json.dumps(metrics_summary, indent=2) + "\n", encoding="utf-8"
    )
    (art / "train_metrics.json").write_text(
        json.dumps(metrics_log, indent=2), encoding="utf-8"
    )
    print(f"  metrics: {save_dir / 'train_summary.json'}")
    print(f"  formal copy: {art}")

    if not args.no_plot:
        plot_after_train(save_dir, args.run_name)


if __name__ == "__main__":
    main()
