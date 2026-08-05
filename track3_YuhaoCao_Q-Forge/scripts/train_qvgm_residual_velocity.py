#!/usr/bin/env python3
"""Offline Q-VGM residual velocity matching for a SmolVLA action expert."""

from __future__ import annotations

import argparse
import copy
import json
import math
import random
import time
from pathlib import Path

import numpy as np
import torch
from omegaconf import OmegaConf
from torch.utils.data._utils.collate import default_collate

from smolvla_qvgm_rlinf.data.policy_observation_cache import (
    QVGMPolicyObservationDataset,
    prepare_cached_policy_batch,
)
from smolvla_qvgm_rlinf.models.checkpoint import load_smolvla_checkpoint
from smolvla_qvgm_rlinf.models.qvgm_critic import QVGMCriticConfig, QVGMCriticEnsemble
from smolvla_qvgm_rlinf.models.qvgm_residual import (
    QVGMResidualConfig,
    configure_qvgm_trainable_parameters,
    residual_velocity_matching_loss,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--steps", type=int)
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--batch-size", type=int)
    parser.add_argument("--gradient-accumulation-steps", type=int)
    parser.add_argument(
        "--resume-from",
        type=Path,
        help="Checkpoint directory containing pretrained_model/ and trainer_state.pt",
    )
    return parser.parse_args()


def learning_rate_multiplier(step: int, *, warmup: int, total: int, minimum_ratio: float) -> float:
    if step < warmup:
        return (step + 1) / max(1, warmup)
    progress = min(1.0, (step - warmup) / max(1, total - warmup))
    return minimum_ratio + 0.5 * (1 - minimum_ratio) * (1 + math.cos(math.pi * progress))


def save_checkpoint(
    directory: Path,
    policy,
    optimizer,
    scheduler,
    generator: torch.Generator,
    *,
    step: int,
    config: dict,
    trainable_names: list[str],
) -> None:
    model_dir = directory / "pretrained_model"
    model_dir.mkdir(parents=True, exist_ok=True)
    policy.save_pretrained(model_dir)
    state = {
        "step": step,
        "optimizer": optimizer.state_dict(),
        "scheduler": scheduler.state_dict(),
        "sampling_generator_state": generator.get_state(),
        "torch_rng_state": torch.get_rng_state(),
        "cuda_rng_state": torch.cuda.get_rng_state_all(),
        "numpy_rng_state": np.random.get_state(),
        "python_rng_state": random.getstate(),
        "config": config,
        "trainable_parameter_names": trainable_names,
    }
    torch.save(state, directory / "trainer_state.pt")


def main() -> None:
    args = parse_args()
    cfg = OmegaConf.load(args.config)
    total_steps = int(args.steps or cfg.training.steps)
    scheduler_decay_steps = int(cfg.training.get("scheduler_decay_steps", total_steps))
    if scheduler_decay_steps < total_steps:
        raise ValueError("scheduler_decay_steps must be at least the requested training steps")
    output = args.output_dir or Path(cfg.output_dir)
    output.mkdir(parents=True, exist_ok=True)
    seed = int(cfg.seed)
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)
    torch.cuda.manual_seed_all(seed)
    device = str(cfg.device)

    dataset = QVGMPolicyObservationDataset(
        cfg.data.observation_cache,
        cfg.data.observation_manifest,
        cfg.data.feature_cache,
    )
    model_source = (
        args.resume_from / "pretrained_model" if args.resume_from else Path(cfg.base_checkpoint)
    )
    policy = load_smolvla_checkpoint(
        model_source,
        device=device,
        dtype=torch.bfloat16,
        num_steps=int(cfg.residual.denoising_steps),
    )
    base_policy = load_smolvla_checkpoint(
        cfg.base_checkpoint,
        device=device,
        dtype=torch.bfloat16,
        num_steps=int(cfg.residual.denoising_steps),
    )
    base_policy.eval().requires_grad_(False)
    parameters, trainable_names = configure_qvgm_trainable_parameters(policy)
    policy.train()
    # Prefix parameters stay frozen and deterministic; the action expert remains in train mode.
    policy.model.vlm_with_expert.get_vlm_model().eval()
    policy.model.state_proj.eval()

    critic_device = str(cfg.get("critic_device", device))
    critic_payload = torch.load(
        cfg.critic_checkpoint, map_location=critic_device, weights_only=True
    )
    critic = QVGMCriticEnsemble(
        QVGMCriticConfig(**critic_payload["config"])
    ).to(critic_device)
    critic.load_state_dict(critic_payload["model"])
    critic.eval().requires_grad_(False)
    residual_config = QVGMResidualConfig(**OmegaConf.to_container(cfg.residual, resolve=True))
    if critic.config.horizon != residual_config.horizon or critic.config.action_dim != residual_config.action_dim:
        raise ValueError("critic and residual action horizon/dimension do not match")

    optimizer = torch.optim.AdamW(
        parameters,
        lr=float(cfg.training.learning_rate),
        betas=tuple(cfg.training.betas),
        weight_decay=float(cfg.training.weight_decay),
    )
    minimum_ratio = float(cfg.training.minimum_learning_rate) / float(cfg.training.learning_rate)
    scheduler = torch.optim.lr_scheduler.LambdaLR(
        optimizer,
        lambda step: learning_rate_multiplier(
            step,
            warmup=int(cfg.training.warmup_steps),
            total=scheduler_decay_steps,
            minimum_ratio=minimum_ratio,
        ),
    )
    generator = torch.Generator(device="cpu").manual_seed(seed)
    sampling_weights = None
    if bool(cfg.data.get("task_balanced_sampling", False)):
        task_indices = dataset.observations["task_index"].long()
        _, inverse, counts = torch.unique(
            task_indices, sorted=True, return_inverse=True, return_counts=True
        )
        sampling_weights = counts[inverse].double().reciprocal()
    start_step = 0
    if args.resume_from:
        trainer_state = torch.load(
            args.resume_from / "trainer_state.pt", map_location="cpu", weights_only=False
        )
        optimizer.load_state_dict(trainer_state["optimizer"])
        scheduler.load_state_dict(trainer_state["scheduler"])
        generator.set_state(trainer_state["sampling_generator_state"])
        torch.set_rng_state(trainer_state["torch_rng_state"])
        torch.cuda.set_rng_state_all(trainer_state["cuda_rng_state"])
        np.random.set_state(trainer_state["numpy_rng_state"])
        random.setstate(trainer_state["python_rng_state"])
        start_step = int(trainer_state["step"])
        if trainer_state["trainable_parameter_names"] != trainable_names:
            raise ValueError("trainable parameter set changed since resume checkpoint")
    if start_step >= total_steps:
        raise ValueError(f"resume step {start_step} is not below target {total_steps}")

    config_record = OmegaConf.to_container(cfg, resolve=True)
    parameter_record = {
        "trainable_count": sum(parameter.numel() for parameter in parameters),
        "total_count": sum(parameter.numel() for parameter in policy.parameters()),
        "names": trainable_names,
    }
    (output / "trainable_parameters.json").write_text(json.dumps(parameter_record, indent=2) + "\n")
    print(json.dumps({key: value for key, value in parameter_record.items() if key != "names"}), flush=True)

    batch_size = int(args.batch_size or cfg.training.batch_size)
    accumulation = int(
        args.gradient_accumulation_steps or cfg.training.gradient_accumulation_steps
    )
    if batch_size <= 0 or accumulation <= 0:
        raise ValueError("batch size and gradient accumulation must be positive")
    records = []
    started = time.perf_counter()
    for step in range(start_step + 1, total_steps + 1):
        optimizer.zero_grad(set_to_none=True)
        totals = {
            "loss": 0.0,
            "q_improvement": 0.0,
            "action_delta_abs": 0.0,
            "target_residual_norm": 0.0,
            "target_confidence": 0.0,
            "critic_disagreement": 0.0,
            "base_anchor_loss": 0.0,
        }
        for _ in range(accumulation):
            if sampling_weights is None:
                indices = torch.randint(
                    len(dataset), (batch_size,), generator=generator
                ).tolist()
            else:
                indices = torch.multinomial(
                    sampling_weights,
                    batch_size,
                    replacement=True,
                    generator=generator,
                ).tolist()
            raw_batch = default_collate([dataset[index] for index in indices])
            batch = prepare_cached_policy_batch(raw_batch, device)
            with torch.autocast("cuda", dtype=torch.bfloat16, enabled=device.startswith("cuda")):
                loss, details = residual_velocity_matching_loss(
                    policy, base_policy, critic, batch, residual_config
                )
                scaled_loss = loss / accumulation
            scaled_loss.backward()
            for key in totals:
                totals[key] += float(details[key]) / accumulation
        gradient_norm = torch.nn.utils.clip_grad_norm_(
            parameters, float(cfg.training.max_gradient_norm)
        )
        if not torch.isfinite(gradient_norm):
            raise FloatingPointError("non-finite action expert gradient norm")
        optimizer.step()
        scheduler.step()
        record = {
            "step": step,
            **totals,
            "gradient_norm": float(gradient_norm),
            "learning_rate": scheduler.get_last_lr()[0],
            "peak_vram_mib": torch.cuda.max_memory_allocated() / 1024**2,
        }
        records.append(record)
        if step == 1 or step % int(cfg.training.log_interval) == 0:
            print(json.dumps(record), flush=True)
        save_interval = int(cfg.training.save_interval)
        if step < total_steps and save_interval > 0 and step % save_interval == 0:
            save_checkpoint(
                output / f"checkpoint-{step:06d}",
                policy,
                optimizer,
                scheduler,
                generator,
                step=step,
                config=config_record,
                trainable_names=trainable_names,
            )

    final_dir = output / "checkpoint-final"
    save_checkpoint(
        final_dir,
        policy,
        optimizer,
        scheduler,
        generator,
        step=total_steps,
        config=config_record,
        trainable_names=trainable_names,
    )
    metrics = {
        "steps": total_steps,
        "scheduler_decay_steps": scheduler_decay_steps,
        "start_step": start_step,
        "transitions": len(dataset),
        "elapsed_seconds": time.perf_counter() - started,
        "peak_vram_mib": torch.cuda.max_memory_allocated() / 1024**2,
        "final": records[-1],
        "checkpoint": str((final_dir / "pretrained_model").resolve()),
        "critic_required_for_inference": False,
    }
    (output / "metrics.json").write_text(json.dumps(metrics, indent=2) + "\n")
    with (output / "train.jsonl").open("a") as handle:
        for record in records:
            handle.write(json.dumps(record) + "\n")
    print(json.dumps(metrics, indent=2), flush=True)


if __name__ == "__main__":
    main()
