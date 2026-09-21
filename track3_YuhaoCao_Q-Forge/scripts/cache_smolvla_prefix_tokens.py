#!/usr/bin/env python3
"""Resumably cache frozen SmolVLA prefix tokens for RLT autoencoder training."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import torch

from cache_qvgm_features import observation_batch
from smolvla_qvgm_rlinf.data.collected_episode_adapter import load_collected_episode
from smolvla_qvgm_rlinf.models.checkpoint import load_smolvla_checkpoint
from smolvla_qvgm_rlinf.models.prefix_features import extract_prefix_hidden


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--pickle-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument(
        "--model-path",
        type=Path,
        default=Path(
            "checkpoints/smolvla_libero_task0/public_recipe_20k/"
            "checkpoint-final/pretrained_model"
        ),
    )
    parser.add_argument("--batch-size", type=int, default=8)
    parser.add_argument("--worker-id", type=int, default=0)
    parser.add_argument("--num-workers", type=int, default=1)
    parser.add_argument("--device", default="cuda")
    return parser.parse_args()


@torch.inference_mode()
def extract_tokens(policy, observations: list[dict], *, batch_size: int, device: str):
    hidden_batches, mask_batches = [], []
    dtype = next(policy.parameters()).dtype
    for start in range(0, len(observations), batch_size):
        batch = observation_batch(observations[start : start + batch_size], device)
        with torch.autocast(
            device_type="cuda", dtype=dtype, enabled=device.startswith("cuda")
        ):
            hidden, mask = extract_prefix_hidden(policy, batch)
        hidden_batches.append(hidden.to(device="cpu", dtype=torch.bfloat16))
        mask_batches.append(mask.to(device="cpu", dtype=torch.bool))
    return torch.cat(hidden_batches), torch.cat(mask_batches)


def main() -> None:
    args = parse_args()
    if args.batch_size <= 0:
        raise ValueError("batch-size must be positive")
    if not 0 <= args.worker_id < args.num_workers:
        raise ValueError("worker-id must be in [0,num-workers)")
    args.output_dir.mkdir(parents=True, exist_ok=True)
    paths = sorted(args.pickle_dir.glob("*.pkl"))
    paths = [path for index, path in enumerate(paths) if index % args.num_workers == args.worker_id]
    if not paths:
        raise FileNotFoundError("worker shard contains no pickle episodes")

    policy = load_smolvla_checkpoint(
        args.model_path.resolve(), device=args.device, dtype=torch.bfloat16
    )
    records = []
    for path in paths:
        output = args.output_dir / f"{path.stem}.pt"
        if output.exists():
            payload = torch.load(output, map_location="cpu", weights_only=True)
            records.append(
                {"source": str(path.resolve()), "output": str(output.resolve()),
                 "observations": int(payload["hidden"].shape[0]), "resumed": True}
            )
            continue
        episode = load_collected_episode(path)
        hidden, mask = extract_tokens(
            policy, episode["observations"], batch_size=args.batch_size, device=args.device
        )
        metadata = episode.get("qvgm_metadata", {})
        payload = {
            "hidden": hidden,
            "mask": mask,
            "source": str(path.resolve()),
            "task_reset_state_id": metadata.get("task_reset_state_id", metadata.get("state_id")),
            "task_id": metadata.get("task_id"),
            "repeat_id": metadata.get("repeat_id"),
            "success": bool(episode["success"]),
        }
        temporary = output.with_suffix(".pt.tmp")
        torch.save(payload, temporary)
        temporary.replace(output)
        record = {
            "source": str(path.resolve()),
            "output": str(output.resolve()),
            "observations": int(hidden.shape[0]),
            "sequence_length": int(hidden.shape[1]),
            "hidden_dim": int(hidden.shape[2]),
            "resumed": False,
        }
        records.append(record)
        print(json.dumps(record), flush=True)

    summary = {
        "worker_id": args.worker_id,
        "num_workers": args.num_workers,
        "files": len(records),
        "observations": sum(record["observations"] for record in records),
        "model_path": str(args.model_path.resolve()),
    }
    (args.output_dir / f"worker_{args.worker_id}_summary.json").write_text(
        json.dumps(summary, indent=2) + "\n"
    )
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
