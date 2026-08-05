#!/usr/bin/env python3
"""Phase 11B: fit the Q-VGM ensemble to offline Monte-Carlo returns."""

from __future__ import annotations

import argparse
import json
import random
from pathlib import Path

import numpy as np
import torch
import torch.nn.functional as F

from smolvla_qvgm_rlinf.data.feature_cache import (
    sha256_file,
    state_stratified_split,
    within_state_episode_split,
)
from smolvla_qvgm_rlinf.models.qvgm_critic import QVGMCriticConfig, QVGMCriticEnsemble


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cache", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--steps", type=int, default=2000)
    parser.add_argument("--batch-size", type=int, default=256)
    parser.add_argument("--learning-rate", type=float, default=3e-4)
    parser.add_argument("--weight-decay", type=float, default=1e-4)
    parser.add_argument("--hidden-dim", type=int, default=512)
    parser.add_argument("--first-hidden-dim", type=int, default=1024)
    parser.add_argument("--proprio-feature-dim", type=int, default=256)
    parser.add_argument("--ensemble-size", type=int, default=5)
    parser.add_argument("--validation-episodes", type=int, default=2)
    parser.add_argument(
        "--validation-states",
        help="Comma-separated reset state IDs; overrides --validation-episodes",
    )
    parser.add_argument(
        "--within-state-validation-fraction",
        type=float,
        help="Hold out this fraction of complete episodes inside every reset state",
    )
    parser.add_argument("--seed", type=int, default=1000)
    parser.add_argument("--device", default="cuda")
    parser.add_argument(
        "--task-balanced-sampling",
        action="store_true",
        help="Sample benchmark tasks uniformly using cache task_id values.",
    )
    return parser.parse_args()


def episode_split(manifest: dict, validation_episodes: int) -> tuple[torch.Tensor, torch.Tensor, torch.Tensor]:
    episodes = manifest["episodes"]
    if not 0 < validation_episodes < len(episodes):
        raise ValueError("validation_episodes must leave non-empty train and validation sets")
    train, validation, success = [], [], []
    offset = 0
    split_at = len(episodes) - validation_episodes
    for episode_id, episode in enumerate(episodes):
        count = int(episode["transitions"])
        indices = torch.arange(offset, offset + count)
        (train if episode_id < split_at else validation).append(indices)
        success.append(torch.full((count,), bool(episode["success"]), dtype=torch.bool))
        offset += count
    return torch.cat(train), torch.cat(validation), torch.cat(success)


def parse_state_ids(value: str) -> set[int]:
    states = {int(item.strip()) for item in value.split(",") if item.strip()}
    if not states:
        raise ValueError("validation-states must contain at least one state ID")
    return states


def model_values(model: QVGMCriticEnsemble, data: dict, indices: torch.Tensor, action_key: str, mask_key: str):
    return model(
        data["z_state"][indices],
        data["proprio"][indices],
        data[action_key][indices],
        data[mask_key][indices],
    )


@torch.inference_mode()
def evaluate(model, data, indices, success_labels) -> dict[str, float]:
    ensemble = model_values(model, data, indices, "action_chunk_executed", "action_mask")
    target = data["mc_return"][indices].expand_as(ensemble)
    aggregate = ensemble.mean(dim=-1)
    labels = success_labels[indices]
    metrics = {
        "mse": F.mse_loss(ensemble, target).item(),
        "q_mean": ensemble.mean().item(),
        "ensemble_disagreement": ensemble.std(dim=-1, unbiased=False).mean().item(),
        "q_success": aggregate[labels].mean().item() if labels.any() else float("nan"),
        "q_failure": aggregate[~labels].mean().item() if (~labels).any() else float("nan"),
    }
    ref = model_values(model, data, indices, "ref_chunk", "ref_chunk_mask")
    random_actions = torch.empty_like(data["action_chunk_executed"][indices]).uniform_(-1, 1)
    random_q = model(
        data["z_state"][indices], data["proprio"][indices], random_actions, data["action_mask"][indices]
    )
    metrics.update(
        q_dataset=aggregate.mean().item(),
        q_ref=ref.mean(dim=-1).mean().item(),
        q_random=random_q.mean(dim=-1).mean().item(),
    )
    return metrics


def action_gradient_metrics(model, data, indices) -> dict[str, float]:
    sample = indices[: min(64, len(indices))]
    actions = data["ref_chunk"][sample].detach().clone().requires_grad_(True)
    q = model.mean_value(
        data["z_state"][sample], data["proprio"][sample], actions, data["ref_chunk_mask"][sample]
    ).mean()
    gradient = torch.autograd.grad(q, actions)[0]
    return {
        "action_gradient_norm": gradient.norm(dim=(-2, -1)).mean().item(),
        "action_gradient_finite": float(torch.isfinite(gradient).all()),
    }


def main() -> None:
    args = parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    random.seed(args.seed)
    np.random.seed(args.seed)
    torch.manual_seed(args.seed)
    if args.device.startswith("cuda"):
        torch.cuda.manual_seed_all(args.seed)

    manifest = json.loads(args.manifest.read_text())
    data = torch.load(args.cache, map_location=args.device, weights_only=True)
    if args.validation_states and args.within_state_validation_fraction is not None:
        raise ValueError("choose either validation-states or within-state-validation-fraction")
    validation_states = parse_state_ids(args.validation_states) if args.validation_states else None
    if args.within_state_validation_fraction is not None:
        train_indices, validation_indices, success_labels = within_state_episode_split(
            manifest, args.within_state_validation_fraction
        )
    elif validation_states is None:
        train_indices, validation_indices, success_labels = episode_split(
            manifest, args.validation_episodes
        )
    else:
        train_indices, validation_indices, success_labels = state_stratified_split(
            manifest, validation_states
        )
    train_indices = train_indices.to(args.device)
    validation_indices = validation_indices.to(args.device)
    success_labels = success_labels.to(args.device)
    horizon, action_dim = data["action_chunk_executed"].shape[-2:]
    config = QVGMCriticConfig(
        z_dim=data["z_state"].shape[-1],
        proprio_dim=data["proprio"].shape[-1],
        action_dim=action_dim,
        horizon=horizon,
        proprio_feature_dim=args.proprio_feature_dim,
        hidden_dim=args.hidden_dim,
        first_hidden_dim=args.first_hidden_dim,
        ensemble_size=args.ensemble_size,
        joint_state_norm=True,
    )
    model = QVGMCriticEnsemble(config).to(args.device)
    optimizer = torch.optim.AdamW(
        model.parameters(), lr=args.learning_rate, weight_decay=args.weight_decay
    )
    generator = torch.Generator(device=args.device).manual_seed(args.seed)
    train_sampling_weights = None
    if args.task_balanced_sampling:
        if "task_id" not in data:
            raise ValueError("task-balanced sampling requires cache task_id")
        train_tasks = data["task_id"][train_indices].long()
        _, inverse, counts = torch.unique(
            train_tasks, sorted=True, return_inverse=True, return_counts=True
        )
        train_sampling_weights = counts[inverse].float().reciprocal()
    history = []
    for step in range(1, args.steps + 1):
        if train_sampling_weights is None:
            positions = torch.randint(
                len(train_indices),
                (args.batch_size,),
                generator=generator,
                device=args.device,
            )
        else:
            positions = torch.multinomial(
                train_sampling_weights,
                args.batch_size,
                replacement=True,
                generator=generator,
            )
        sampled = train_indices[positions]
        prediction = model_values(
            model, data, sampled, "action_chunk_executed", "action_mask"
        )
        target = data["mc_return"][sampled].expand_as(prediction).float()
        loss = F.mse_loss(prediction, target)
        optimizer.zero_grad(set_to_none=True)
        loss.backward()
        gradient_norm = torch.nn.utils.clip_grad_norm_(model.parameters(), 10.0)
        optimizer.step()
        if step == 1 or step % 100 == 0 or step == args.steps:
            model.eval()
            validation = evaluate(model, data, validation_indices, success_labels)
            model.train()
            record = {
                "step": step,
                "train_loss": loss.item(),
                "parameter_gradient_norm": float(gradient_norm),
                "validation": validation,
            }
            history.append(record)
            print(json.dumps(record), flush=True)

    model.eval()
    all_indices = torch.arange(data["z_state"].shape[0], device=args.device)
    final_metrics = {
        "train": evaluate(model, data, train_indices, success_labels),
        "validation": evaluate(model, data, validation_indices, success_labels),
        "all": evaluate(model, data, all_indices, success_labels),
        **action_gradient_metrics(model, data, validation_indices),
    }
    checkpoint = {
        "model": model.state_dict(),
        "optimizer": optimizer.state_dict(),
        "config": model.config_dict,
        "step": args.steps,
        "cache_sha256": sha256_file(args.cache),
        "cache_manifest_sha256": sha256_file(args.manifest),
        "split": {
            "train_indices": train_indices.cpu(),
            "validation_indices": validation_indices.cpu(),
            "validation_states": sorted(validation_states) if validation_states else None,
            "within_state_validation_fraction": args.within_state_validation_fraction,
        },
    }
    torch.save(checkpoint, args.output_dir / "checkpoint-final.pt")
    output = {
        "config": vars(args) | {"cache": str(args.cache), "manifest": str(args.manifest), "output_dir": str(args.output_dir)},
        "model_config": model.config_dict,
        "train_transitions": len(train_indices),
        "validation_transitions": len(validation_indices),
        "history": history,
        "final": final_metrics,
    }
    (args.output_dir / "metrics.json").write_text(json.dumps(output, indent=2, default=str) + "\n")
    print(json.dumps(final_metrics, indent=2))


if __name__ == "__main__":
    main()
