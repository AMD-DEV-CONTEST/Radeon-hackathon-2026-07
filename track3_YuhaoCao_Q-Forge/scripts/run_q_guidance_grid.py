#!/usr/bin/env python3
"""Evaluate the complete paper-aligned test-time Q-guidance grid offline."""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

import torch

from smolvla_qvgm_rlinf.data.feature_cache import (
    state_stratified_split,
    within_state_episode_split,
)
from smolvla_qvgm_rlinf.models.q_guidance import QGuidanceConfig, guide_action_chunk
from smolvla_qvgm_rlinf.models.qvgm_critic import QVGMCriticConfig, QVGMCriticEnsemble


def comma_separated(value: str, cast):
    items = [cast(item.strip()) for item in value.split(",") if item.strip()]
    if not items:
        raise argparse.ArgumentTypeError("list must not be empty")
    return items


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cache", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--checkpoint-glob", required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--steps", default="5,10")
    parser.add_argument("--step-sizes", default="0.01,0.02")
    parser.add_argument("--max-deltas", default="0.02,0.05")
    parser.add_argument("--max-gradient-norm", type=float, default=1.0)
    parser.add_argument("--optimize-prefix-steps", type=int, default=5)
    parser.add_argument("--optimize-action-dims", type=int, default=7)
    parser.add_argument("--validation-fraction", type=float, default=1 / 3)
    parser.add_argument(
        "--validation-states",
        help="comma-separated reset-state IDs; mutually exclusive with validation-fraction",
    )
    parser.add_argument("--batch-size", type=int, default=512)
    parser.add_argument("--maximum-saturation-increase", type=float, default=0.005)
    parser.add_argument("--device", default="cuda")
    return parser.parse_args()


def critic_gate(metrics: dict) -> tuple[bool, list[str]]:
    final = metrics["final"]
    td = final["td_validation"]
    mc = final["mc_validation"]
    values = [
        td["td_loss"],
        td["q_min"],
        td["q_max"],
        mc["q_success"],
        mc["q_failure"],
        mc["q_dataset"],
        mc["q_random"],
        final["action_gradient_norm"],
    ]
    failures = []
    if not all(math.isfinite(value) for value in values):
        failures.append("non_finite_metric")
    if td["td_loss"] > 0.01:
        failures.append("validation_td_loss_above_0.01")
    if td["q_min"] < -2.0 or td["q_max"] > 2.0:
        failures.append("q_outside_-2_2")
    if mc["q_success"] <= mc["q_failure"]:
        failures.append("q_success_not_above_failure")
    if mc["q_dataset"] <= mc["q_random"]:
        failures.append("q_dataset_not_above_random")
    if final["action_gradient_norm"] <= 0 or not final["action_gradient_finite"]:
        failures.append("invalid_action_gradient")
    return not failures, failures


def evaluate_config(
    critic: QVGMCriticEnsemble,
    data: dict[str, torch.Tensor],
    indices: torch.Tensor,
    *,
    batch_size: int,
    config: QGuidanceConfig,
) -> dict[str, float | bool | int]:
    totals = {
        "transitions": 0,
        "valid_actions": 0,
        "q_base": 0.0,
        "q_guided": 0.0,
        "q_improvement": 0.0,
        "improved": 0,
        "delta": 0.0,
        "saturation_before": 0,
        "saturation_after": 0,
        "disagreement_before": 0.0,
        "disagreement_after": 0.0,
        "gradient_norm": 0.0,
        "gradient_values": 0,
    }
    improvement_min = float("inf")
    delta_max = gradient_max = 0.0
    all_finite = True
    for start in range(0, len(indices), batch_size):
        selected = indices[start : start + batch_size]
        reference = data["ref_chunk"][selected].clamp(-1.0, 1.0)
        mask = data["ref_chunk_mask"][selected]
        guided, info = guide_action_chunk(
            critic,
            data["z_state"][selected],
            data["proprio"][selected],
            reference,
            mask,
            config,
        )
        with torch.no_grad():
            before_disagreement = critic.disagreement(
                data["z_state"][selected], data["proprio"][selected], reference, mask
            )
            after_disagreement = critic.disagreement(
                data["z_state"][selected], data["proprio"][selected], guided, mask
            )
        valid = mask.unsqueeze(-1).expand_as(reference)
        delta = torch.abs(guided - reference)[valid]
        improvement = info["best_q"] - info["base_q"]
        count = len(selected)
        totals["transitions"] += count
        totals["valid_actions"] += int(valid.sum())
        totals["q_base"] += float(info["base_q"].sum())
        totals["q_guided"] += float(info["best_q"].sum())
        totals["q_improvement"] += float(improvement.sum())
        totals["improved"] += int((improvement > 0).sum())
        totals["delta"] += float(delta.sum())
        totals["saturation_before"] += int((torch.abs(reference[valid]) >= 0.99).sum())
        totals["saturation_after"] += int((torch.abs(guided[valid]) >= 0.99).sum())
        totals["disagreement_before"] += float(before_disagreement.sum())
        totals["disagreement_after"] += float(after_disagreement.sum())
        totals["gradient_norm"] += float(info["gradient_norm"].sum())
        totals["gradient_values"] += info["gradient_norm"].numel()
        improvement_min = min(improvement_min, float(improvement.min()))
        delta_max = max(delta_max, float(delta.max()))
        gradient_max = max(gradient_max, float(info["gradient_norm"].max()))
        all_finite = all_finite and bool(
            torch.isfinite(guided).all()
            and torch.isfinite(info["best_q"]).all()
            and torch.isfinite(info["gradient_norm"]).all()
        )

    transitions = totals["transitions"]
    valid_actions = totals["valid_actions"]
    saturation_before = totals["saturation_before"] / valid_actions
    saturation_after = totals["saturation_after"] / valid_actions
    return {
        "transitions": transitions,
        "q_base_mean": totals["q_base"] / transitions,
        "q_guided_mean": totals["q_guided"] / transitions,
        "q_improvement_mean": totals["q_improvement"] / transitions,
        "q_improvement_min": improvement_min,
        "improved_fraction": totals["improved"] / transitions,
        "delta_abs_mean": totals["delta"] / valid_actions,
        "delta_abs_max": delta_max,
        "saturation_before": saturation_before,
        "saturation_after": saturation_after,
        "saturation_increase": saturation_after - saturation_before,
        "disagreement_before": totals["disagreement_before"] / transitions,
        "disagreement_after": totals["disagreement_after"] / transitions,
        "gradient_norm_mean": totals["gradient_norm"] / totals["gradient_values"],
        "gradient_norm_max": gradient_max,
        "all_finite": all_finite,
    }


def main() -> None:
    args = parse_args()
    steps = comma_separated(args.steps, int)
    step_sizes = comma_separated(args.step_sizes, float)
    max_deltas = comma_separated(args.max_deltas, float)
    if args.batch_size <= 0:
        raise ValueError("batch-size must be positive")
    checkpoints = sorted(Path().glob(args.checkpoint_glob))
    if not checkpoints:
        raise FileNotFoundError(f"no checkpoints match {args.checkpoint_glob}")
    args.output_dir.mkdir(parents=True, exist_ok=True)
    manifest = json.loads(args.manifest.read_text())
    if args.validation_states:
        validation_states = set(comma_separated(args.validation_states, int))
        _, indices, _ = state_stratified_split(manifest, validation_states)
        validation_split = {
            "mode": "state_stratified",
            "validation_states": sorted(validation_states),
        }
    else:
        _, indices, _ = within_state_episode_split(manifest, args.validation_fraction)
        validation_split = {
            "mode": "within_state_episode",
            "validation_fraction": args.validation_fraction,
        }
    indices = indices.to(args.device)
    data = torch.load(args.cache, map_location=args.device, weights_only=True)
    records = []
    for checkpoint_path in checkpoints:
        checkpoint = torch.load(checkpoint_path, map_location=args.device, weights_only=True)
        critic = QVGMCriticEnsemble(QVGMCriticConfig(**checkpoint["config"])).to(args.device)
        critic.load_state_dict(checkpoint["model"])
        critic.eval()
        training_metrics_path = checkpoint_path.parent / "metrics.json"
        training_metrics = json.loads(training_metrics_path.read_text())
        critic_pass, critic_failures = critic_gate(training_metrics)
        training_config = training_metrics["config"]
        for ascent_steps in steps:
            for step_size in step_sizes:
                for max_delta in max_deltas:
                    guidance = QGuidanceConfig(
                        steps=ascent_steps,
                        step_size=step_size,
                        max_delta=max_delta,
                        max_gradient_norm=args.max_gradient_norm,
                        optimize_prefix_steps=args.optimize_prefix_steps,
                        optimize_action_dims=args.optimize_action_dims,
                    )
                    metrics = evaluate_config(
                        critic,
                        data,
                        indices,
                        batch_size=args.batch_size,
                        config=guidance,
                    )
                    guidance_failures = []
                    if not metrics["all_finite"]:
                        guidance_failures.append("non_finite_guidance")
                    if metrics["delta_abs_max"] > max_delta + 1e-6:
                        guidance_failures.append("max_delta_violation")
                    if metrics["q_improvement_min"] < -1e-7:
                        guidance_failures.append("keep_best_regression")
                    if metrics["saturation_increase"] > args.maximum_saturation_increase:
                        guidance_failures.append("excess_action_saturation")
                    tag = (
                        f"{checkpoint_path.parent.name}_s{ascent_steps}_"
                        f"lr{step_size:g}_d{max_delta:g}"
                    )
                    record = {
                        "tag": tag,
                        "checkpoint": str(checkpoint_path),
                        "critic": {
                            "calql_alpha": training_config["cql_alpha"],
                            "local_noise_std": training_config["cql_reference_noise_std"],
                            "passes_gate": critic_pass,
                            "gate_failures": critic_failures,
                        },
                        "guidance": {
                            "steps": ascent_steps,
                            "step_size": step_size,
                            "max_delta": max_delta,
                            "max_gradient_norm": args.max_gradient_norm,
                            "optimize_prefix_steps": args.optimize_prefix_steps,
                            "optimize_action_dims": args.optimize_action_dims,
                            "passes_gate": not guidance_failures,
                            "gate_failures": guidance_failures,
                        },
                        "metrics": metrics,
                    }
                    (args.output_dir / f"{tag}.json").write_text(
                        json.dumps(record, indent=2) + "\n"
                    )
                    records.append(record)
                    print(json.dumps(record), flush=True)
        del critic

    eligible = [
        record
        for record in records
        if record["critic"]["passes_gate"] and record["guidance"]["passes_gate"]
    ]
    eligible.sort(
        key=lambda record: (
            -record["metrics"]["q_improvement_mean"],
            record["metrics"]["saturation_increase"],
            record["metrics"]["disagreement_after"],
        )
    )
    summary = {
        "config": {
            key: str(value) if isinstance(value, Path) else value
            for key, value in vars(args).items()
        },
        "validation_split": validation_split,
        "validation_transitions": len(indices),
        "checkpoints": len(checkpoints),
        "configurations": len(records),
        "eligible_configurations": len(eligible),
        "ranked_eligible_tags": [record["tag"] for record in eligible],
    }
    (args.output_dir / "grid_summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
