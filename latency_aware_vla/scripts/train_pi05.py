#!/usr/bin/env python3
"""B1: fine-tune π0.5 (pi05) on Env-A fruit pick-and-place.

Uses local weights (e.g. /workspace/models/pi05_base downloaded via hf-mirror).
Records loss CSV/JSON, peak VRAM, wall time, and conference-style plots.
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
DEFAULT_PRETRAINED = "/workspace/models/pi05_base"


def make_delta_timestamps(delta_indices, fps: int):
    if delta_indices is None:
        return [0.0]
    return [i / fps for i in delta_indices]


def plot_after_train(save_dir: Path, run_name: str) -> None:
    metrics = save_dir / "train_metrics.json"
    summary = save_dir / "train_summary.json"
    if not metrics.exists():
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
        f"π0.5 · {run_name}",
    ]
    subprocess.run(cmd, check=False)


def main():
    ap = argparse.ArgumentParser(description="π0.5 B1 train on Env-A fruit place")
    ap.add_argument("--dataset-id", default="local/franka-kitchen-fruit-place-120ep")
    ap.add_argument("--pretrained", default=DEFAULT_PRETRAINED)
    ap.add_argument("--n-steps", type=int, default=3000)
    ap.add_argument("--batch-size", type=int, default=2)
    ap.add_argument("--lr", type=float, default=None)
    ap.add_argument("--output-dir", default=str(ROOT / "output"))
    ap.add_argument("--run-name", default="pi05_fruit_place_b1")
    ap.add_argument("--log-every", type=int, default=20)
    ap.add_argument("--save-every", type=int, default=1000)
    ap.add_argument("--num-workers", type=int, default=2)
    ap.add_argument("--seed", type=int, default=2026)
    ap.add_argument("--no-plot", action="store_true")
    ap.add_argument("--gradient-checkpointing", action="store_true", default=True)
    ap.add_argument("--no-gradient-checkpointing", action="store_true")
    ap.add_argument("--freeze-vision", action="store_true", default=True)
    ap.add_argument("--unfreeze-vision", action="store_true",
                    help="Also train SigLIP vision encoder (higher VRAM)")
    ap.add_argument("--train-expert-only", action="store_true", default=True)
    ap.add_argument("--train-full", action="store_true",
                    help="Train beyond expert-only (language+expert)")
    args = ap.parse_args()
    if args.no_gradient_checkpointing:
        args.gradient_checkpointing = False
    if args.unfreeze_vision:
        args.freeze_vision = False
    if args.train_full:
        args.train_expert_only = False

    os.environ.setdefault("HF_LEROBOT_HOME", "/workspace/cache/huggingface/lerobot")
    os.environ.setdefault("HF_HOME", "/workspace/cache/huggingface")
    os.environ.setdefault("HF_HUB_OFFLINE", "1")
    os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")

    if not (Path(args.pretrained) / "model.safetensors").exists() and not Path(
        args.pretrained
    ).is_file():
        raise FileNotFoundError(
            f"π0.5 weights not found at {args.pretrained}. "
            "Run: bash scripts/download_pi05_hf_mirror.sh"
        )

    random.seed(args.seed)
    np.random.seed(args.seed)
    torch.manual_seed(args.seed)
    if torch.cuda.is_available():
        torch.cuda.manual_seed_all(args.seed)
        torch.cuda.reset_peak_memory_stats()

    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    print(f"[train] seed={args.seed} device={device}")

    from lerobot.configs.types import FeatureType
    from lerobot.datasets.lerobot_dataset import LeRobotDataset, LeRobotDatasetMetadata
    from lerobot.datasets.utils import dataset_to_policy_features
    from lerobot.policies.factory import make_pre_post_processors
    from lerobot.policies.pi05.configuration_pi05 import PI05Config
    from lerobot.policies.pi05.modeling_pi05 import PI05Policy

    print(f"[train] dataset={args.dataset_id}")
    dataset_metadata = LeRobotDatasetMetadata(args.dataset_id)
    features = dataset_to_policy_features(dataset_metadata.features)
    output_features = {k: ft for k, ft in features.items() if ft.type is FeatureType.ACTION}
    input_features = {k: ft for k, ft in features.items() if k not in output_features}
    print(f"  frames={dataset_metadata.total_frames} eps={dataset_metadata.total_episodes}")
    print(f"  inputs={list(input_features)} outputs={list(output_features)}")

    cfg_kwargs = dict(
        input_features=input_features,
        output_features=output_features,
        chunk_size=50,
        n_action_steps=50,
        dtype="bfloat16",
        freeze_vision_encoder=args.freeze_vision,
        train_expert_only=args.train_expert_only,
    )
    print(
        f"[train] freeze_vision={args.freeze_vision} "
        f"train_expert_only={args.train_expert_only}"
    )
    # optional knobs depending on installed lerobot version
    try:
        cfg = PI05Config(**cfg_kwargs, gradient_checkpointing=args.gradient_checkpointing)
    except TypeError:
        cfg = PI05Config(**cfg_kwargs)

    print(f"[train] loading π0.5 from {args.pretrained}")
    try:
        policy = PI05Policy.from_pretrained(args.pretrained, config=cfg, strict=False)
    except Exception as e:
        print(f"[train] from_pretrained failed ({e}); safetensors fallback")
        from safetensors.torch import load_file

        policy = PI05Policy(cfg)
        weight_path = Path(args.pretrained)
        st_path = weight_path if weight_path.is_file() else weight_path / "model.safetensors"
        policy.load_state_dict(load_file(str(st_path)), strict=False)

    policy.train()
    policy.to(device)
    total_params = sum(p.numel() for p in policy.parameters())
    trainable_params = sum(p.numel() for p in policy.parameters() if p.requires_grad)
    print(f"  total={total_params:,} trainable={trainable_params:,}")

    amp_enabled = device.type == "cuda"
    amp_dtype = torch.bfloat16 if amp_enabled else None
    preprocessor, postprocessor = make_pre_post_processors(
        cfg, dataset_stats=dataset_metadata.stats
    )

    fps = dataset_metadata.fps
    delta_timestamps = {"action": make_delta_timestamps(cfg.action_delta_indices, fps)}
    for img_key in cfg.image_features:
        delta_timestamps[img_key] = make_delta_timestamps(cfg.observation_delta_indices, fps)
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

    trainable = [p for p in policy.parameters() if p.requires_grad]
    lr = args.lr if args.lr is not None else getattr(cfg, "optimizer_lr", 2.5e-5)
    optimizer = torch.optim.AdamW(
        trainable,
        lr=lr,
        betas=getattr(cfg, "optimizer_betas", (0.9, 0.95)),
        eps=getattr(cfg, "optimizer_eps", 1e-8),
        weight_decay=getattr(cfg, "optimizer_weight_decay", 1e-10),
    )
    grad_clip = getattr(cfg, "optimizer_grad_clip_norm", 1.0)
    print(f"[train] AdamW lr={lr} batch={args.batch_size} steps={args.n_steps}")

    save_dir = Path(args.output_dir) / "train" / args.run_name
    save_dir.mkdir(parents=True, exist_ok=True)
    (save_dir / "run_config.json").write_text(json.dumps(vars(args), indent=2) + "\n")

    metrics_log = []
    csv_path = save_dir / "train_metrics.csv"
    with csv_path.open("w", encoding="utf-8") as f:
        f.write("step,epoch,loss,grad_norm,lr,step_time_s\n")

    step = 0
    epoch = 0
    t_start = time.time()
    print(f"[train] starting → {save_dir}")
    while step < args.n_steps:
        epoch += 1
        for batch in dataloader:
            if step >= args.n_steps:
                break
            t0 = time.time()
            batch = preprocessor(batch)
            with torch.autocast(device_type="cuda", dtype=amp_dtype, enabled=amp_enabled):
                loss, info = policy.forward(batch)
            loss.backward()
            grad_norm = torch.nn.utils.clip_grad_norm_(trainable, grad_clip)
            optimizer.step()
            optimizer.zero_grad()
            step_time = time.time() - t0
            record = {
                "step": step,
                "epoch": epoch,
                "loss": float(loss.item()),
                "grad_norm": float(grad_norm.item()) if hasattr(grad_norm, "item") else float(grad_norm),
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
                    f"grad {record['grad_norm']:.4f} | {step_time:.2f}s/step | {elapsed:.0f}s",
                    flush=True,
                )
                (save_dir / "train_metrics.json").write_text(
                    json.dumps(metrics_log, indent=2), encoding="utf-8"
                )
            if args.save_every > 0 and step > 0 and step % args.save_every == 0:
                ckpt = save_dir / f"checkpoint_{step:06d}"
                policy.save_pretrained(ckpt)
                print(f"  [ckpt] {ckpt}", flush=True)
            step += 1

    elapsed = time.time() - t_start
    peak_mb = torch.cuda.max_memory_allocated() / 1024**2 if torch.cuda.is_available() else None
    final_dir = save_dir / "final"
    policy.save_pretrained(final_dir)
    preprocessor.save_pretrained(final_dir)
    postprocessor.save_pretrained(final_dir)

    summary = {
        "run_name": args.run_name,
        "dataset_id": args.dataset_id,
        "pretrained": args.pretrained,
        "task": "Pick up the fruit and place it in the basket.",
        "n_steps": step,
        "n_epochs": epoch,
        "batch_size": args.batch_size,
        "lr": float(lr),
        "amp": amp_enabled,
        "total_time_s": float(elapsed),
        "total_time_min": float(elapsed) / 60.0,
        "final_loss": float(metrics_log[-1]["loss"]) if metrics_log else None,
        "loss_start": float(metrics_log[0]["loss"]) if metrics_log else None,
        "loss_end": float(metrics_log[-1]["loss"]) if metrics_log else None,
        "peak_vram_mb": float(peak_mb) if peak_mb is not None else None,
        "peak_vram_gb": float(peak_mb / 1024) if peak_mb is not None else None,
        "mean_step_time_s": float(np.mean([m["step_time_s"] for m in metrics_log])) if metrics_log else None,
        "trainable_params": trainable_params,
        "total_params": total_params,
        "device": str(device),
        "seed": args.seed,
        "chunk_size": 50,
        "freeze_vision_encoder": True,
        "train_expert_only": True,
        "gradient_checkpointing": bool(args.gradient_checkpointing),
    }
    (save_dir / "train_summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    (save_dir / "train_metrics.json").write_text(json.dumps(metrics_log, indent=2))
    art = ROOT / "artifacts" / "formal" / args.run_name
    art.mkdir(parents=True, exist_ok=True)
    (art / "train_summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    (art / "train_report.json").write_text(
        json.dumps(
            {
                "run_name": args.run_name,
                "role": "B1 π0.5 Sync baseline (train)",
                "status": "completed",
                "hardware": {
                    "gpu": torch.cuda.get_device_name(0) if torch.cuda.is_available() else None,
                    "peak_vram_gb": summary["peak_vram_gb"],
                },
                "timing": {
                    "total_time_s": summary["total_time_s"],
                    "total_time_min": summary["total_time_min"],
                    "mean_step_time_s": summary["mean_step_time_s"],
                    "n_steps": summary["n_steps"],
                },
                "train": summary,
            },
            indent=2,
        )
        + "\n"
    )
    print(f"[train] done {step} steps in {elapsed:.0f}s peak_vram={summary['peak_vram_gb']:.2f}GB")
    if not args.no_plot:
        plot_after_train(save_dir, args.run_name)


if __name__ == "__main__":
    main()
