#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
import random
import sys
import time
from typing import Any, Mapping


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from parcel_sorter.grasp_scoring import (
    GRASP_FEATURE_NAMES,
    evaluate_ranked_grasp_predictions,
    grouped_grasp_row_indices,
    groupwise_grasp_preference_pairs,
    sha256_file,
    validate_feature_names,
)
from parcel_sorter.grasp_scorer_model import build_grasp_scorer_network


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Train the safety-first structured grasp scorer on one AMD Radeon GPU."
    )
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--train-split", default="train")
    parser.add_argument("--eval-split")
    parser.add_argument("--steps", type=int, default=2000)
    parser.add_argument("--hidden-width", type=int, default=64)
    parser.add_argument("--learning-rate", type=float, default=1e-3)
    parser.add_argument("--weight-decay", type=float, default=1e-4)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--device", default="cuda")
    parser.add_argument("--log-every", type=int, default=100)
    parser.add_argument(
        "--objective",
        choices=("pointwise", "groupwise-safety-first"),
        default="pointwise",
    )
    parser.add_argument("--safety-pair-weight", type=float, default=2.0)
    parser.add_argument("--success-pair-weight", type=float, default=1.0)
    return parser.parse_args()


def _rows(payload: Mapping[str, Any], split: str) -> list[Mapping[str, Any]]:
    return [row for row in payload["rows"] if str(row["split"]) == split]


def _group_mean(torch: Any, values: Any, groups: tuple[tuple[int, ...], ...]) -> Any:
    return torch.stack(
        [values[torch.tensor(group, device=values.device)].mean() for group in groups]
    ).mean()


def _pairwise_logistic_loss(
    torch: Any,
    scores: Any,
    pair_groups: tuple[tuple[tuple[int, int], ...], ...],
    *,
    lower_is_better: bool,
) -> Any:
    if not pair_groups:
        return scores.sum() * 0.0
    group_losses = []
    for pairs in pair_groups:
        preferred = torch.tensor(
            [pair[0] for pair in pairs], dtype=torch.long, device=scores.device
        )
        disfavored = torch.tensor(
            [pair[1] for pair in pairs], dtype=torch.long, device=scores.device
        )
        difference = scores[preferred] - scores[disfavored]
        if not lower_is_better:
            difference = -difference
        group_losses.append(torch.nn.functional.softplus(difference).mean())
    return torch.stack(group_losses).mean()


def run(args: argparse.Namespace) -> dict[str, Any]:
    if min(args.steps, args.hidden_width, args.log_every) < 1:
        raise ValueError("steps, hidden width, and log interval must be positive")
    if args.learning_rate <= 0 or args.weight_decay < 0:
        raise ValueError("learning rate must be positive and weight decay non-negative")
    if min(args.safety_pair_weight, args.success_pair_weight) < 0:
        raise ValueError("pairwise loss weights must be non-negative")
    try:
        import torch
    except ImportError as exc:
        raise RuntimeError("PyTorch is required for grasp scorer training") from exc
    if args.device == "cuda" and not torch.cuda.is_available():
        raise RuntimeError("AMD ROCm device is unavailable through torch.cuda")

    payload = json.loads(args.dataset.read_text(encoding="utf-8"))
    validate_feature_names(payload["feature_names"])
    train_rows = _rows(payload, args.train_split)
    if not train_rows:
        raise ValueError(f"dataset contains no rows for train split {args.train_split}")
    eval_split = args.eval_split or args.train_split
    eval_rows = _rows(payload, eval_split)
    if not eval_rows:
        raise ValueError(f"dataset contains no rows for eval split {eval_split}")

    random.seed(args.seed)
    torch.manual_seed(args.seed)
    if torch.cuda.is_available():
        torch.cuda.manual_seed_all(args.seed)
    device = torch.device(args.device)
    x_train = torch.tensor(
        [row["features"] for row in train_rows], dtype=torch.float32, device=device
    )
    mean = x_train.mean(dim=0)
    scale = x_train.std(dim=0, unbiased=False).clamp_min(1e-6)
    x_train = (x_train - mean) / scale
    unsafe_target = torch.tensor(
        [float(row["labels"]["safety_aborted"]) for row in train_rows],
        dtype=torch.float32,
        device=device,
    )
    success_target = torch.tensor(
        [float(row["labels"]["success"]) for row in train_rows],
        dtype=torch.float32,
        device=device,
    )
    force_target = torch.log1p(
        torch.tensor(
            [float(row["labels"]["max_contact_force_n"]) for row in train_rows],
            dtype=torch.float32,
            device=device,
        )
    )
    duration_target = torch.log1p(
        torch.tensor(
            [float(row["labels"]["duration_seconds"]) for row in train_rows],
            dtype=torch.float32,
            device=device,
        )
    )

    model = build_grasp_scorer_network(torch, args.hidden_width).to(device)
    optimizer = torch.optim.AdamW(
        model.parameters(), lr=args.learning_rate, weight_decay=args.weight_decay
    )
    bce = torch.nn.BCEWithLogitsLoss(reduction="none")
    smooth_l1 = torch.nn.SmoothL1Loss(reduction="none")
    train_groups = grouped_grasp_row_indices(train_rows)
    preference_pairs = groupwise_grasp_preference_pairs(train_rows)
    started = time.perf_counter_ns()
    history: list[dict[str, float | int]] = []
    model.train()
    for step in range(1, args.steps + 1):
        prediction = model(x_train)
        unsafe_rows = bce(prediction[:, 0], unsafe_target)
        success_rows = bce(prediction[:, 1], success_target)
        force_rows = smooth_l1(prediction[:, 2], force_target)
        duration_rows = smooth_l1(prediction[:, 3], duration_target)
        if args.objective == "groupwise-safety-first":
            unsafe_loss = _group_mean(torch, unsafe_rows, train_groups)
            success_loss = _group_mean(torch, success_rows, train_groups)
            force_loss = _group_mean(torch, force_rows, train_groups)
            duration_loss = _group_mean(torch, duration_rows, train_groups)
            safety_pair_loss = _pairwise_logistic_loss(
                torch,
                prediction[:, 0],
                preference_pairs["safety"],
                lower_is_better=True,
            )
            success_pair_loss = _pairwise_logistic_loss(
                torch,
                prediction[:, 1],
                preference_pairs["success"],
                lower_is_better=False,
            )
        else:
            unsafe_loss = unsafe_rows.mean()
            success_loss = success_rows.mean()
            force_loss = force_rows.mean()
            duration_loss = duration_rows.mean()
            safety_pair_loss = prediction.sum() * 0.0
            success_pair_loss = prediction.sum() * 0.0
        loss = unsafe_loss + success_loss + 0.5 * force_loss + 0.25 * duration_loss
        loss = (
            loss
            + args.safety_pair_weight * safety_pair_loss
            + args.success_pair_weight * success_pair_loss
        )
        optimizer.zero_grad(set_to_none=True)
        loss.backward()
        optimizer.step()
        if step == 1 or step == args.steps or step % args.log_every == 0:
            history.append(
                {
                    "step": step,
                    "loss": float(loss.detach().cpu()),
                    "unsafe_loss": float(unsafe_loss.detach().cpu()),
                    "success_loss": float(success_loss.detach().cpu()),
                    "force_loss": float(force_loss.detach().cpu()),
                    "duration_loss": float(duration_loss.detach().cpu()),
                    "safety_pair_loss": float(safety_pair_loss.detach().cpu()),
                    "success_pair_loss": float(success_pair_loss.detach().cpu()),
                }
            )

    def predict(rows: list[Mapping[str, Any]]) -> list[dict[str, Any]]:
        features = torch.tensor(
            [row["features"] for row in rows], dtype=torch.float32, device=device
        )
        model.eval()
        with torch.inference_mode():
            raw = model((features - mean) / scale)
            unsafe = torch.sigmoid(raw[:, 0])
            success = torch.sigmoid(raw[:, 1])
            force = torch.expm1(raw[:, 2]).clamp_min(0)
            duration = torch.expm1(raw[:, 3]).clamp_min(0)
            if device.type == "cuda":
                torch.cuda.synchronize()
        return [
            {
                "candidate_id": row["candidate_id"],
                "static_rank": int(row["static_rank"]),
                "unsafe_probability": float(unsafe[index].cpu()),
                "success_probability": float(success[index].cpu()),
                "predicted_force_n": float(force[index].cpu()),
                "predicted_duration_seconds": float(duration[index].cpu()),
            }
            for index, row in enumerate(rows)
        ]

    eval_predictions = predict(eval_rows)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    checkpoint_path = args.output_dir / "grasp_scorer.pt"
    torch.save(
        {
            "schema_version": 1,
            "feature_names": list(GRASP_FEATURE_NAMES),
            "feature_mean": mean.detach().cpu(),
            "feature_scale": scale.detach().cpu(),
            "hidden_width": args.hidden_width,
            "training_objective": args.objective,
            "model_state_dict": {
                name: tensor.detach().cpu()
                for name, tensor in model.state_dict().items()
            },
        },
        checkpoint_path,
    )
    elapsed_ms = (time.perf_counter_ns() - started) / 1_000_000
    result = {
        "schema_version": 1,
        "claim_boundary": (
            "Training-pipeline smoke only; no generalization claim."
            if eval_split == args.train_split
            else "Evaluation uses the named frozen split."
        ),
        "dataset": str(args.dataset.resolve()),
        "dataset_file_sha256": sha256_file(args.dataset),
        "dataset_payload_sha256": payload["dataset_sha256"],
        "train_split": args.train_split,
        "eval_split": eval_split,
        "train_rows": len(train_rows),
        "eval_rows": len(eval_rows),
        "feature_count": len(GRASP_FEATURE_NAMES),
        "steps": args.steps,
        "seed": args.seed,
        "hidden_width": args.hidden_width,
        "parameter_count": sum(parameter.numel() for parameter in model.parameters()),
        "learning_rate": args.learning_rate,
        "weight_decay": args.weight_decay,
        "objective": args.objective,
        "safety_pair_weight": args.safety_pair_weight,
        "success_pair_weight": args.success_pair_weight,
        "train_group_count": len(train_groups),
        "informative_safety_group_count": len(preference_pairs["safety"]),
        "informative_success_group_count": len(preference_pairs["success"]),
        "device": str(device),
        "torch_version": torch.__version__,
        "hip_version": torch.version.hip,
        "device_name": torch.cuda.get_device_name(0) if device.type == "cuda" else None,
        "elapsed_ms": elapsed_ms,
        "history": history,
        "evaluation": evaluate_ranked_grasp_predictions(eval_rows, eval_predictions),
        "checkpoint": str(checkpoint_path.resolve()),
        "checkpoint_sha256": sha256_file(checkpoint_path),
    }
    summary_path = args.output_dir / "summary.json"
    summary_path.write_text(
        json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    return result


def main() -> int:
    args = parse_args()
    result = run(args)
    print(
        json.dumps(
            {
                "summary": str(args.output_dir / "summary.json"),
                "device": result["device_name"],
                "hip_version": result["hip_version"],
                "train_rows": result["train_rows"],
                "eval_rows": result["eval_rows"],
                "elapsed_ms": result["elapsed_ms"],
                "evaluation": result["evaluation"],
            },
            allow_nan=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
