#!/usr/bin/env python3
"""Write the immutable data/action contract beside a PI0.5 training run."""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

from parcel_sorter.mobile_pi05_training_contract import (
    PI05_TRAINING_CONTRACT_FILENAME,
    build_pi05_training_contract,
)
from parcel_sorter.pi05_mode_head_adapter import (
    PI05_MODE_HEAD_POOLING_MASKED_MEAN,
    normalize_pi05_mode_head_pooling,
    pi05_mode_head_protocol,
)
from parcel_sorter.pi05_state_token_adapter import PI05_STATE_TOKEN_PROTOCOL
from parcel_sorter.pi05_action_projection_adapter import (
    PI05_FULL_ACTION_PROJECTION_PROTOCOL,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset-root", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--base-model", required=True)
    parser.add_argument("--base-revision", required=True)
    parser.add_argument("--chunk-size", type=int, required=True)
    parser.add_argument("--n-action-steps", type=int, required=True)
    parser.add_argument(
        "--training-role", choices=("smoke", "tiny_overfit", "candidate"), required=True
    )
    parser.add_argument("--requested-training-steps", type=int, required=True)
    parser.add_argument("--training-batch-size", type=int, required=True)
    parser.add_argument("--scheduler-type", choices=("cosine_decay",), required=True)
    parser.add_argument("--scheduler-warmup-steps", type=int, required=True)
    parser.add_argument("--scheduler-decay-steps", type=int, required=True)
    parser.add_argument("--launch-audit", type=Path, required=True)
    parser.add_argument("--sampling-manifest", type=Path)
    parser.add_argument("--normalization-stats", type=Path)
    parser.add_argument("--train-stats-manifest", type=Path)
    parser.add_argument("--state-token", action="store_true")
    parser.add_argument("--mode-head", action="store_true")
    parser.add_argument("--full-action-projections", action="store_true")
    parser.add_argument(
        "--mode-head-pooling", default=PI05_MODE_HEAD_POOLING_MASKED_MEAN
    )
    parser.add_argument("--mode-head-class-weights")
    parser.add_argument("--stage-loss-weights")
    parser.add_argument("--mode-flow-loss-weights")
    parser.add_argument("--mode-flow-loss-population-normalizer", type=float)
    args = parser.parse_args()
    mode_head_pooling = normalize_pi05_mode_head_pooling(args.mode_head_pooling)
    if not args.mode_head and mode_head_pooling != PI05_MODE_HEAD_POOLING_MASKED_MEAN:
        raise ValueError("non-default mode-head pooling requires --mode-head")
    mode_head_class_weights = (
        [float(value) for value in args.mode_head_class_weights.split(",")]
        if args.mode_head_class_weights
        else None
    )
    if mode_head_class_weights is not None and (
        len(mode_head_class_weights) != 3
        or any(
            not math.isfinite(value) or value <= 0.0
            for value in mode_head_class_weights
        )
    ):
        raise ValueError("mode-head class weights must contain three positive values")
    if mode_head_class_weights is not None and not args.mode_head:
        raise ValueError("mode-head class weights require --mode-head")
    stage_loss_weights = (
        [float(value) for value in args.stage_loss_weights.split(",")]
        if args.stage_loss_weights
        else None
    )
    if stage_loss_weights is not None and (
        len(stage_loss_weights) != 6
        or any(
            not math.isfinite(value) or value <= 0.0
            for value in stage_loss_weights
        )
    ):
        raise ValueError("stage loss weights must contain six positive values")
    mode_flow_loss_weights = (
        [float(value) for value in args.mode_flow_loss_weights.split(",")]
        if args.mode_flow_loss_weights
        else None
    )
    if mode_flow_loss_weights is not None and (
        len(mode_flow_loss_weights) != 3
        or any(
            not math.isfinite(value) or value <= 0.0
            for value in mode_flow_loss_weights
        )
        or args.mode_flow_loss_population_normalizer is None
        or not math.isfinite(args.mode_flow_loss_population_normalizer)
        or args.mode_flow_loss_population_normalizer <= 0.0
    ):
        raise ValueError(
            "mode flow loss weights require three positive values and a positive normalizer"
        )
    if (
        mode_flow_loss_weights is None
        and args.mode_flow_loss_population_normalizer is not None
    ):
        raise ValueError("mode flow loss normalizer requires mode flow loss weights")
    payload = build_pi05_training_contract(
        args.dataset_root,
        base_model=args.base_model,
        base_revision=args.base_revision,
        chunk_size=args.chunk_size,
        n_action_steps=args.n_action_steps,
        state_token_protocol=PI05_STATE_TOKEN_PROTOCOL if args.state_token else None,
        mode_head_protocol=(
            pi05_mode_head_protocol(mode_head_pooling) if args.mode_head else None
        ),
        mode_head_class_weights=mode_head_class_weights,
        stage_loss_weights=stage_loss_weights,
        mode_flow_loss_weights=mode_flow_loss_weights,
        mode_flow_loss_population_normalizer=(
            args.mode_flow_loss_population_normalizer
        ),
        action_projection_protocol=(
            PI05_FULL_ACTION_PROJECTION_PROTOCOL
            if args.full_action_projections
            else None
        ),
        training_role=args.training_role,
        requested_training_steps=args.requested_training_steps,
        training_batch_size=args.training_batch_size,
        scheduler_type=args.scheduler_type,
        scheduler_warmup_steps=args.scheduler_warmup_steps,
        scheduler_decay_steps=args.scheduler_decay_steps,
        training_launch_audit=json.loads(
            args.launch_audit.read_text(encoding="utf-8")
        ),
        sampling_manifest_path=args.sampling_manifest,
        normalization_stats_path=args.normalization_stats,
        train_stats_manifest_path=args.train_stats_manifest,
    )
    args.output_dir.mkdir(parents=True, exist_ok=True)
    path = args.output_dir / PI05_TRAINING_CONTRACT_FILENAME
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"training_contract": str(path), **payload}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
