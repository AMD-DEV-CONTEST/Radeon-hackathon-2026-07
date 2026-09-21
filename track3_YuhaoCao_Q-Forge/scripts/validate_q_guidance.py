#!/usr/bin/env python3
"""Offline boundary and keep-best validation for test-time Q ascent."""

import argparse
import json
from pathlib import Path

import torch

from smolvla_qvgm_rlinf.models.q_guidance import QGuidanceConfig, guide_action_chunk
from smolvla_qvgm_rlinf.models.qvgm_critic import QVGMCriticConfig, QVGMCriticEnsemble
from smolvla_qvgm_rlinf.data.feature_cache import state_stratified_split, within_state_episode_split
from train_qvgm_critic_mc import episode_split, parse_state_ids


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--cache", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--checkpoint", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--steps", type=int, default=20)
    parser.add_argument("--step-size", type=float, default=0.05)
    parser.add_argument("--max-delta", type=float, default=0.2)
    parser.add_argument("--max-gradient-norm", type=float, default=1.0)
    parser.add_argument("--optimize-prefix-steps", type=int)
    parser.add_argument("--optimize-action-dims", type=int)
    parser.add_argument("--validation-states", help="Comma-separated reset state IDs")
    parser.add_argument("--within-state-validation-fraction", type=float)
    parser.add_argument("--device", default="cuda")
    args = parser.parse_args()
    data = torch.load(args.cache, map_location=args.device, weights_only=True)
    manifest = json.loads(args.manifest.read_text())
    if args.validation_states and args.within_state_validation_fraction is not None:
        raise ValueError("choose either validation-states or within-state-validation-fraction")
    if args.within_state_validation_fraction is not None:
        _, indices, _ = within_state_episode_split(
            manifest, args.within_state_validation_fraction
        )
    elif args.validation_states:
        _, indices, _ = state_stratified_split(manifest, parse_state_ids(args.validation_states))
    else:
        _, indices, _ = episode_split(manifest, 2)
    indices = indices.to(args.device)
    checkpoint = torch.load(args.checkpoint, map_location=args.device, weights_only=True)
    critic = QVGMCriticEnsemble(QVGMCriticConfig(**checkpoint["config"])).to(args.device).eval()
    critic.load_state_dict(checkpoint["model"])
    reference = data["ref_chunk"][indices].clamp(-1.0, 1.0)
    mask = data["ref_chunk_mask"][indices]
    guided, info = guide_action_chunk(
        critic,
        data["z_state"][indices],
        data["proprio"][indices],
        reference,
        mask,
        QGuidanceConfig(
            steps=args.steps,
            step_size=args.step_size,
            max_delta=args.max_delta,
            max_gradient_norm=args.max_gradient_norm,
            optimize_prefix_steps=args.optimize_prefix_steps,
            optimize_action_dims=args.optimize_action_dims,
        ),
    )
    with torch.no_grad():
        before_disagreement = critic.disagreement(data["z_state"][indices], data["proprio"][indices], reference, mask)
        after_disagreement = critic.disagreement(data["z_state"][indices], data["proprio"][indices], guided, mask)
    valid = mask.unsqueeze(-1).expand_as(reference)
    delta = torch.abs(guided - reference)[valid]
    before_saturation = (torch.abs(reference[valid]) >= 0.99).float().mean()
    after_saturation = (torch.abs(guided[valid]) >= 0.99).float().mean()
    improvement = info["best_q"] - info["base_q"]
    metrics = {
        "transitions": len(indices),
        "config": vars(args) | {"cache": str(args.cache), "manifest": str(args.manifest), "checkpoint": str(args.checkpoint), "output": str(args.output)},
        "q_base_mean": info["base_q"].mean().item(),
        "q_guided_mean": info["best_q"].mean().item(),
        "q_improvement_mean": improvement.mean().item(),
        "q_improvement_min": improvement.min().item(),
        "improved_fraction": (improvement > 0).float().mean().item(),
        "delta_abs_mean": delta.mean().item(),
        "delta_abs_max": delta.max().item(),
        "saturation_before": before_saturation.item(),
        "saturation_after": after_saturation.item(),
        "disagreement_before": before_disagreement.mean().item(),
        "disagreement_after": after_disagreement.mean().item(),
        "gradient_norm_mean": info["gradient_norm"].mean().item(),
        "gradient_norm_max": info["gradient_norm"].max().item(),
        "all_finite": bool(torch.isfinite(guided).all() and torch.isfinite(info["best_q"]).all()),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(metrics, indent=2, default=str) + "\n")
    print(json.dumps(metrics, indent=2, default=str))


if __name__ == "__main__":
    main()
