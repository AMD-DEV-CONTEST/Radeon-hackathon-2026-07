#!/usr/bin/env python3
"""Fine-tune SmolVLA on one or more raw LIBERO HDF5 tasks."""

from __future__ import annotations

import argparse
import json
import math
import os
import random
import time
from pathlib import Path

# DataLoader workers are forked after the policy loads Hugging Face tokenizers.
# Keep tokenizer internals single-threaded in this process and its children so
# tokenizers neither emits fork warnings nor risks a fork/parallelism deadlock.
os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")

import numpy as np
import torch
from omegaconf import OmegaConf
from torch.utils.data import DataLoader, WeightedRandomSampler

from smolvla_qvgm_rlinf.data import (
    LiberoHDF5MultiTaskDataset,
    LiberoHDF5TaskDataset,
    LiberoLeRobotTaskDataset,
    compute_libero_hdf5_stats,
)
from smolvla_qvgm_rlinf.models.checkpoint import load_smolvla_checkpoint


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default="configs/experiments/task0_sft_smoke.yaml")
    parser.add_argument("--steps", type=int)
    parser.add_argument("--output-dir", type=Path)
    args = parser.parse_args()
    cfg = OmegaConf.load(args.config)
    steps = args.steps or int(cfg.steps)
    output = args.output_dir or Path(cfg.output_dir)
    output.mkdir(parents=True, exist_ok=True)
    random.seed(cfg.seed)
    np.random.seed(cfg.seed)
    torch.manual_seed(cfg.seed)

    sampler = None
    if "lerobot_root" in cfg:
        dataset_paths = [str(cfg.lerobot_root)]
        task_texts = [str(cfg.task)]
        dataset = LiberoLeRobotTaskDataset(
            cfg.lerobot_root,
            str(cfg.task),
            num_episodes=cfg.get("num_episodes"),
            episodes=OmegaConf.to_object(cfg.episodes) if "episodes" in cfg else None,
            chunk_size=50,
        )
        stats = dataset.dataset_stats()
        print(json.dumps(dataset.summary(), indent=2), flush=True)
    elif "datasets" in cfg:
        dataset_paths = [str(item.path) for item in cfg.datasets]
        task_texts = [str(item.task) for item in cfg.datasets]
        stats = compute_libero_hdf5_stats(dataset_paths)
        dataset = LiberoHDF5MultiTaskDataset(dataset_paths, task_texts, chunk_size=50)
        if bool(cfg.get("task_balanced_sampling", True)):
            generator = torch.Generator().manual_seed(int(cfg.seed))
            sampler = WeightedRandomSampler(
                dataset.task_balanced_sample_weights(),
                num_samples=len(dataset),
                replacement=True,
                generator=generator,
            )
    else:
        dataset_paths = [str(cfg.dataset_path)]
        task_texts = [str(cfg.task)]
        stats = compute_libero_hdf5_stats(cfg.dataset_path)
        dataset = LiberoHDF5TaskDataset(cfg.dataset_path, cfg.task, chunk_size=50)
    loader = DataLoader(
        dataset,
        batch_size=cfg.batch_size,
        shuffle=sampler is None,
        sampler=sampler,
        num_workers=int(cfg.get("num_workers", 0)),
        pin_memory=True,
    )
    policy = load_smolvla_checkpoint(
        cfg.base_checkpoint, device="cuda", dtype=torch.bfloat16, dataset_stats=stats
    )
    policy.train()
    parameters = [parameter for parameter in policy.parameters() if parameter.requires_grad]
    optimizer = torch.optim.AdamW(parameters, lr=cfg.learning_rate, betas=(0.9, 0.95), weight_decay=1e-10)
    warmup_steps = int(cfg.warmup_steps)
    decay_steps = int(cfg.get("decay_steps", steps))
    decay_lr = float(cfg.get("decay_lr", cfg.learning_rate))
    min_ratio = decay_lr / float(cfg.learning_rate)

    def lr_multiplier(step: int) -> float:
        if step < warmup_steps:
            return (step + 1) / max(1, warmup_steps)
        progress = min(1.0, (step - warmup_steps) / max(1, decay_steps - warmup_steps))
        return min_ratio + 0.5 * (1.0 - min_ratio) * (1.0 + math.cos(math.pi * progress))

    scheduler = torch.optim.lr_scheduler.LambdaLR(optimizer, lr_multiplier)
    iterator = iter(loader)
    records = []
    started = time.perf_counter()
    for step in range(1, steps + 1):
        try:
            batch = next(iterator)
        except StopIteration:
            iterator = iter(loader)
            batch = next(iterator)
        batch = {key: value.cuda(non_blocking=True) if torch.is_tensor(value) else value for key, value in batch.items()}
        optimizer.zero_grad(set_to_none=True)
        with torch.autocast("cuda", dtype=torch.bfloat16):
            loss, _ = policy(batch)
        loss.backward()
        grad_norm = torch.nn.utils.clip_grad_norm_(parameters, 10.0)
        optimizer.step()
        scheduler.step()
        record = {
            "step": step,
            "loss": loss.detach().item(),
            "grad_norm": grad_norm.detach().item(),
            "lr": scheduler.get_last_lr()[0],
        }
        records.append(record)
        if step % int(cfg.log_freq) == 0 or step == 1:
            print(json.dumps(record), flush=True)
        if step < steps and step % int(cfg.save_freq) == 0:
            intermediate = output / f"checkpoint-{step:06d}" / "pretrained_model"
            intermediate.mkdir(parents=True, exist_ok=True)
            policy.save_pretrained(intermediate)

    checkpoint = output / "checkpoint-final" / "pretrained_model"
    checkpoint.mkdir(parents=True, exist_ok=True)
    policy.save_pretrained(checkpoint)
    if isinstance(dataset, LiberoHDF5MultiTaskDataset):
        dataset_demos = sum(dataset.task_demo_counts)
        task_frame_counts = list(dataset.task_frame_counts)
    elif isinstance(dataset, LiberoLeRobotTaskDataset):
        dataset_demos = len(dataset.episodes)
        task_frame_counts = [len(dataset)]
    else:
        dataset_demos = len({name for name, _, _ in dataset.samples})
        task_frame_counts = [len(dataset)]
    metrics = {
        "steps": steps,
        "dataset_frames": len(dataset),
        "dataset_demos": dataset_demos,
        "dataset_tasks": len(task_texts),
        "dataset_paths": dataset_paths,
        "task_texts": task_texts,
        "task_frame_counts": task_frame_counts,
        "dataset_episodes": (
            dataset.episode_indices
            if isinstance(dataset, LiberoLeRobotTaskDataset)
            else None
        ),
        "task_balanced_sampling": sampler is not None,
        "initial_loss": records[0]["loss"],
        "final_loss": records[-1]["loss"],
        "min_loss": min(record["loss"] for record in records),
        "elapsed_seconds": time.perf_counter() - started,
        "peak_vram_mib": torch.cuda.max_memory_allocated() / 1024**2,
        "checkpoint": str(checkpoint.resolve()),
    }
    (output / "metrics.json").write_text(json.dumps(metrics, indent=2) + "\n")
    with (output / "train.jsonl").open("w") as handle:
        for record in records:
            handle.write(json.dumps(record) + "\n")
    print(json.dumps(metrics, indent=2))


if __name__ == "__main__":
    main()
