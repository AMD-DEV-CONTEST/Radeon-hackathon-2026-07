#!/usr/bin/env python3
"""Phase 11C: H-step TD training with a Polyak target ensemble."""

from __future__ import annotations

import argparse
import copy
import json
from pathlib import Path

import torch

from smolvla_qvgm_rlinf.data.feature_cache import (
    sha256_file,
    state_stratified_split,
    within_state_episode_split,
)
from smolvla_qvgm_rlinf.models.critic_training import (
    cql_conservative_loss,
    polyak_update,
    td_ensemble_loss,
)
from smolvla_qvgm_rlinf.models.qvgm_critic import QVGMCriticConfig, QVGMCriticEnsemble
from train_qvgm_critic_mc import action_gradient_metrics, episode_split, evaluate, parse_state_ids


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("--cache", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--init-checkpoint", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--next-action-source", choices=("reference", "dataset"), required=True)
    parser.add_argument("--steps", type=int, default=2000)
    parser.add_argument("--batch-size", type=int, default=256)
    parser.add_argument("--learning-rate", type=float, default=1e-4)
    parser.add_argument("--tau", type=float, default=0.005)
    parser.add_argument("--cql-alpha", type=float, default=0.0)
    parser.add_argument("--cql-random-actions", type=int, default=10)
    parser.add_argument("--cql-reference-noise-std", type=float, default=0.1)
    parser.add_argument("--calql", action="store_true")
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


def indexed_batch(data, indices):
    return {key: value[indices] for key, value in data.items()}


@torch.inference_mode()
def td_metrics(model, target_model, data, indices, source):
    loss, details = td_ensemble_loss(
        model, target_model, indexed_batch(data, indices), next_action_source=source
    )
    prediction = details["prediction"]
    target = details["target"]
    metrics = {
        "td_loss": loss.item(),
        "q_mean": prediction.mean().item(),
        "q_min": prediction.min().item(),
        "q_max": prediction.max().item(),
        "target_mean": target.mean().item(),
        "target_min": target.min().item(),
        "target_max": target.max().item(),
        "ensemble_disagreement": prediction.std(-1, unbiased=False).mean().item(),
    }
    return metrics


def main():
    args = parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    torch.manual_seed(args.seed)
    data = torch.load(args.cache, map_location=args.device, weights_only=True)
    manifest = json.loads(args.manifest.read_text())
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

    initial = torch.load(args.init_checkpoint, map_location=args.device, weights_only=True)
    config = QVGMCriticConfig(**initial["config"])
    model = QVGMCriticEnsemble(config).to(args.device)
    model.load_state_dict(initial["model"])
    target_model = copy.deepcopy(model).eval()
    target_model.requires_grad_(False)
    optimizer = torch.optim.AdamW(model.parameters(), lr=args.learning_rate, weight_decay=1e-4)
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
        td_loss, _ = td_ensemble_loss(
            model,
            target_model,
            indexed_batch(data, sampled),
            next_action_source=args.next_action_source,
        )
        cql_loss, cql_details = cql_conservative_loss(
            model,
            indexed_batch(data, sampled),
            random_action_count=args.cql_random_actions,
            reference_noise_std=args.cql_reference_noise_std,
            calibration_floor=(
                indexed_batch(data, sampled)["mc_return"] if args.calql else None
            ),
        )
        loss = td_loss + args.cql_alpha * cql_loss
        optimizer.zero_grad(set_to_none=True)
        loss.backward()
        gradient_norm = torch.nn.utils.clip_grad_norm_(model.parameters(), 10.0)
        optimizer.step()
        polyak_update(model, target_model, tau=args.tau)
        if step == 1 or step % 100 == 0 or step == args.steps:
            model.eval()
            validation = td_metrics(
                model, target_model, data, validation_indices, args.next_action_source
            )
            model.train()
            record = {
                "step": step,
                "train_td_loss": loss.item(),
                "raw_td_loss": td_loss.item(),
                "cql_loss": cql_loss.item(),
                "q_data_minus_ood": (
                    cql_details["data_q"].mean() - cql_details["candidate_q"].mean()
                ).item(),
                "parameter_gradient_norm": float(gradient_norm),
                "validation": validation,
            }
            history.append(record)
            print(json.dumps(record), flush=True)

    model.eval()
    all_indices = torch.arange(len(data["z_state"]), device=args.device)
    final = {
        "td_train": td_metrics(model, target_model, data, train_indices, args.next_action_source),
        "td_validation": td_metrics(model, target_model, data, validation_indices, args.next_action_source),
        "mc_validation": evaluate(model, data, validation_indices, success_labels),
        "mc_all": evaluate(model, data, all_indices, success_labels),
        **action_gradient_metrics(model, data, validation_indices),
    }
    checkpoint = {
        "model": model.state_dict(),
        "target_model": target_model.state_dict(),
        "optimizer": optimizer.state_dict(),
        "config": model.config_dict,
        "step": args.steps,
        "next_action_source": args.next_action_source,
        "tau": args.tau,
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
        "config": {key: str(value) if isinstance(value, Path) else value for key, value in vars(args).items()},
        "history": history,
        "final": final,
    }
    (args.output_dir / "metrics.json").write_text(json.dumps(output, indent=2) + "\n")
    print(json.dumps(final, indent=2))


if __name__ == "__main__":
    main()
