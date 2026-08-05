#!/usr/bin/env python3
"""Train the paper-aligned learned 2048-dim RLT prefix autoencoder."""

from __future__ import annotations

import argparse
import json
import math
import random
from collections import defaultdict
from pathlib import Path

import torch
import torch.nn.functional as F

from smolvla_qvgm_rlinf.models.prefix_features import RLTFeatureConfig, make_rlt_module


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--token-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument(
        "--resume",
        type=Path,
        help="Model-only checkpoint to resume from; --steps remains the total target step.",
    )
    parser.add_argument("--steps", type=int, default=5000)
    parser.add_argument("--batch-size", type=int, default=4)
    parser.add_argument("--learning-rate", type=float, default=2.5e-5)
    parser.add_argument("--weight-decay", type=float, default=1e-10)
    parser.add_argument("--embed-dim", type=int, default=2048)
    parser.add_argument("--num-layers", type=int, default=2)
    parser.add_argument("--num-heads", type=int, default=8)
    parser.add_argument("--mlp-ratio", type=float, default=4.0)
    parser.add_argument("--validation-fraction", type=float, default=1 / 3)
    parser.add_argument(
        "--validation-states",
        help=(
            "Comma-separated reset states held out for every task. Use this for "
            "suite data with one rollout per task/state pair."
        ),
    )
    parser.add_argument("--log-interval", type=int, default=100)
    parser.add_argument("--checkpoint-interval", type=int, default=500)
    parser.add_argument("--validation-samples", type=int, default=256)
    parser.add_argument("--seed", type=int, default=1000)
    parser.add_argument("--device", default="cuda")
    return parser.parse_args()


def masked_cosine(reconstructed: torch.Tensor, target: torch.Tensor, mask: torch.Tensor):
    cosine = F.cosine_similarity(reconstructed.float(), target.float(), dim=-1)
    weights = mask.float()
    return (cosine * weights).sum() / weights.sum().clamp_min(1)


@torch.inference_mode()
def evaluate(model, hidden, mask, indices, *, batch_size: int, device: str):
    model.eval()
    mse_total = cosine_total = count = 0.0
    for start in range(0, len(indices), batch_size):
        selected = indices[start : start + batch_size]
        target = hidden[selected].to(device=device, non_blocking=True)
        valid = mask[selected].to(device=device, non_blocking=True)
        with torch.autocast("cuda", dtype=torch.bfloat16, enabled=device.startswith("cuda")):
            reconstructed, _ = model.reconstruct(target, valid)
            error = torch.square(reconstructed.float() - target.float())
            weights = valid[..., None].float()
            mse = (error * weights).sum() / (weights.sum() * target.shape[-1]).clamp_min(1)
            cosine = masked_cosine(reconstructed, target, valid)
        batch_count = len(selected)
        mse_total += float(mse) * batch_count
        cosine_total += float(cosine) * batch_count
        count += batch_count
    return {"mse": mse_total / count, "cosine": cosine_total / count}


def main() -> None:
    args = parse_args()
    if args.steps <= 0 or args.batch_size <= 0:
        raise ValueError("steps and batch-size must be positive")
    if not 0 < args.validation_fraction < 1:
        raise ValueError("validation-fraction must be in (0,1)")
    random.seed(args.seed)
    torch.manual_seed(args.seed)
    torch.cuda.manual_seed_all(args.seed)
    args.output_dir.mkdir(parents=True, exist_ok=True)

    files = sorted(args.token_dir.glob("*.pt"))
    if not files:
        raise FileNotFoundError(f"no token files in {args.token_dir}")
    payloads = [torch.load(path, map_location="cpu", weights_only=True) for path in files]
    validation_files: set[int] = set()
    if args.validation_states:
        validation_states = {
            int(value.strip()) for value in args.validation_states.split(",") if value.strip()
        }
        if not validation_states:
            raise ValueError("validation-states must be non-empty")
        for file_index, payload in enumerate(payloads):
            state_id = payload.get("task_reset_state_id")
            if state_id is None:
                raise ValueError("token payload is missing reset-state metadata")
            if int(state_id) in validation_states:
                validation_files.add(file_index)
        task_ids = {int(payload.get("task_id", -1)) for payload in payloads}
        for task_id in task_ids:
            task_files = [
                index
                for index, payload in enumerate(payloads)
                if int(payload.get("task_id", -1)) == task_id
            ]
            if not any(index in validation_files for index in task_files):
                raise ValueError(f"task {task_id} has no RLT validation episode")
            if not any(index not in validation_files for index in task_files):
                raise ValueError(f"task {task_id} has no RLT training episode")
    else:
        files_by_state: dict[tuple[int, int], list[tuple[int, int]]] = defaultdict(list)
        for file_index, payload in enumerate(payloads):
            state_id = payload.get("task_reset_state_id")
            repeat_id = payload.get("repeat_id")
            if state_id is None or repeat_id is None:
                raise ValueError("token payload is missing state/repeat metadata")
            key = (int(payload.get("task_id", -1)), int(state_id))
            files_by_state[key].append((int(repeat_id), file_index))
        for key, repeats in files_by_state.items():
            count = max(1, math.ceil(len(repeats) * args.validation_fraction))
            if count >= len(repeats):
                raise ValueError(f"task/state {key} has no RLT training episode after split")
            validation_files.update(index for _, index in sorted(repeats)[-count:])
    train_payloads = [payload for index, payload in enumerate(payloads) if index not in validation_files]
    validation_payloads = [payload for index, payload in enumerate(payloads) if index in validation_files]
    hidden = torch.cat([payload["hidden"] for payload in train_payloads]).contiguous()
    mask = torch.cat([payload["mask"] for payload in train_payloads]).contiguous()
    validation_hidden = torch.cat(
        [payload["hidden"] for payload in validation_payloads]
    ).contiguous()
    validation_mask = torch.cat([payload["mask"] for payload in validation_payloads]).contiguous()
    observation_count, sequence_length, input_dim = hidden.shape
    train_indices = torch.arange(observation_count)
    validation_indices = torch.arange(len(validation_hidden))

    config = RLTFeatureConfig(
        input_dim=input_dim,
        embed_dim=args.embed_dim,
        num_rl_tokens=1,
        prefix_seq_len=sequence_length,
        num_layers=args.num_layers,
        num_heads=args.num_heads,
        mlp_ratio=args.mlp_ratio,
    )
    model = make_rlt_module(config).to(device=args.device, dtype=torch.bfloat16)
    start_step = 0
    if args.resume is not None:
        resume_payload = torch.load(args.resume, map_location="cpu", weights_only=True)
        if resume_payload["config"] != vars(config):
            raise ValueError("resume checkpoint RLT config does not match current data/config")
        model.load_state_dict(resume_payload["model"])
        start_step = int(resume_payload["step"])
        if start_step >= args.steps:
            raise ValueError(
                f"resume step {start_step} must be smaller than target steps {args.steps}"
            )
    optimizer = torch.optim.AdamW(
        model.parameters(), lr=args.learning_rate, weight_decay=args.weight_decay
    )
    sample_generator = torch.Generator().manual_seed(args.seed + 1)
    if start_step:
        # Preserve the original deterministic minibatch stream even though the
        # optimizer is intentionally restarted from the model-only checkpoint.
        torch.randint(
            len(train_indices),
            (start_step * args.batch_size,),
            generator=sample_generator,
        )
    history = []
    for step in range(start_step + 1, args.steps + 1):
        sampled = train_indices[
            torch.randint(len(train_indices), (args.batch_size,), generator=sample_generator)
        ]
        target = hidden[sampled].to(device=args.device, non_blocking=True)
        valid = mask[sampled].to(device=args.device, non_blocking=True)
        model.train()
        with torch.autocast(
            "cuda", dtype=torch.bfloat16, enabled=args.device.startswith("cuda")
        ):
            loss, _ = model(target, valid)
        optimizer.zero_grad(set_to_none=True)
        loss.backward()
        gradient_norm = torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
        optimizer.step()
        if step == 1 or step % args.log_interval == 0 or step == args.steps:
            eval_count = min(args.validation_samples, len(validation_indices))
            metrics = evaluate(
                model,
                validation_hidden,
                validation_mask,
                validation_indices[:eval_count],
                batch_size=args.batch_size,
                device=args.device,
            )
            record = {
                "step": step,
                "train_loss": float(loss.detach()),
                "gradient_norm": float(gradient_norm.detach()),
                "validation": metrics,
            }
            history.append(record)
            print(json.dumps(record), flush=True)
            if step % args.checkpoint_interval == 0 or step == args.steps:
                checkpoint = {
                    "model": model.state_dict(),
                    "config": vars(config),
                    "step": step,
                }
                torch.save(checkpoint, args.output_dir / "checkpoint-latest.pt")

    final = evaluate(
        model,
        validation_hidden,
        validation_mask,
        validation_indices,
        batch_size=args.batch_size,
        device=args.device,
    )
    checkpoint = {"model": model.state_dict(), "config": vars(config), "step": args.steps}
    torch.save(checkpoint, args.output_dir / "checkpoint-final.pt")
    metrics = {
        "config": {key: str(value) if isinstance(value, Path) else value for key, value in vars(args).items()},
        "model_config": vars(config),
        "files": len(files),
        "observations": observation_count + len(validation_hidden),
        "train_observations": len(train_indices),
        "validation_observations": len(validation_indices),
        "start_step": start_step,
        "history": history,
        "final_validation": final,
    }
    (args.output_dir / "metrics.json").write_text(json.dumps(metrics, indent=2) + "\n")
    print(json.dumps(metrics | {"history": f"{len(history)} records"}, indent=2))


if __name__ == "__main__":
    main()
