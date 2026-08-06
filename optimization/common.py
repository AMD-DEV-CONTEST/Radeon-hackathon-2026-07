from __future__ import annotations

import argparse
import json
import math
import platform
import statistics
import time
from contextlib import nullcontext
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

import numpy as np
import torch
from lerobot.datasets.lerobot_dataset import LeRobotDatasetMetadata
from lerobot.policies import prepare_observation_for_inference

from franka_fruit_pick.eval_policy import STATE_KEY, load_policy

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_POLICY = ROOT / "artifacts/models/smolvla_fruit_pick_dr_600ep"
DEFAULT_DATASET = ROOT / "artifacts/datasets/fruit_pick_dr_600ep"
DEFAULT_RESULTS = Path(__file__).resolve().parent / "results"


def add_common_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--policy-path", default=str(DEFAULT_POLICY))
    parser.add_argument("--repo-id", default="demo/fruit_pick_dr_600ep")
    parser.add_argument("--dataset-root", default=str(DEFAULT_DATASET))
    parser.add_argument("--device", default="cuda")
    parser.add_argument("--task", default="pick the banana and place it in the bowl")
    parser.add_argument("--seed", type=int, default=1234)
    parser.add_argument("--batch-size", type=int, default=1, help="Synthetic inference batch size (default: 1)")
    parser.add_argument("--warmup", type=int, default=3)
    parser.add_argument("--iterations", type=int, default=20)
    parser.add_argument("--output", default=None, help="JSON path; defaults to optimization/results/<experiment>.json")
    parser.add_argument("--save-output", default=None, help="Optional .npy path for correctness comparison")


def sync(device: torch.device) -> None:
    if device.type == "cuda":
        torch.cuda.synchronize(device)


def load_benchmark(args: argparse.Namespace):
    if args.batch_size < 1:
        raise ValueError("--batch-size must be >= 1")
    torch.manual_seed(args.seed)
    np.random.seed(args.seed)
    pb = load_policy(args.policy_path, args.repo_id, args.dataset_root, args.device)
    cfg = pb.policy.config
    # Raw observations must match the dataset, before the checkpoint's processor
    # renames cameras or pads state/action dimensions for the pretrained policy.
    metadata = LeRobotDatasetMetadata(args.repo_id, root=args.dataset_root)
    state_shape = tuple(metadata.features[STATE_KEY]["shape"])
    rng = np.random.default_rng(args.seed)
    obs: dict[str, np.ndarray] = {STATE_KEY: np.zeros(state_shape, dtype=np.float32)}
    h, w = pb.image_hw
    for key in pb.image_keys:
        obs[key] = rng.integers(0, 256, size=(h, w, 3), dtype=np.uint8)
    batch = prepare_observation_for_inference(obs, pb.device, args.task, "franka")
    batch = pb.preprocessor(batch)
    if args.batch_size > 1:
        # Preprocess one deterministic observation first, then duplicate every
        # batched tensor. This keeps all configurations on exactly the same input
        # while exercising the model with a real batch dimension.
        for key, item in batch.items():
            if isinstance(item, torch.Tensor) and item.ndim > 0 and item.shape[0] == 1:
                repeats = (args.batch_size,) + (1,) * (item.ndim - 1)
                batch[key] = item.repeat(repeats)
    model = pb.policy.model
    noise_shape = (args.batch_size, cfg.chunk_size, cfg.max_action_dim)
    noise = torch.randn(noise_shape, device=pb.device, dtype=torch.float32)

    def model_call() -> torch.Tensor:
        return model.sample_actions(
            *model_inputs(pb.policy, batch), noise=noise
        )

    return pb, batch, noise, model_call


def model_inputs(policy, batch):
    images, image_masks = policy.prepare_images(batch)
    state = policy.prepare_state(batch)
    return (
        images,
        image_masks,
        batch["observation.language.tokens"],
        batch["observation.language.attention_mask"],
        state,
    )


def autocast_context(device: torch.device, dtype: str):
    if dtype == "none":
        return nullcontext()
    types = {"bf16": torch.bfloat16, "fp16": torch.float16}
    if dtype not in types:
        raise ValueError(f"unknown AMP dtype: {dtype}")
    return torch.autocast(device_type=device.type, dtype=types[dtype])


def benchmark(
    fn: Callable[[], torch.Tensor],
    *,
    device: torch.device,
    warmup: int,
    iterations: int,
    experiment: str,
    config: dict,
) -> tuple[dict, torch.Tensor]:
    if iterations < 1 or warmup < 0:
        raise ValueError("--iterations must be >= 1 and --warmup must be >= 0")
    if device.type == "cuda":
        torch.cuda.empty_cache()
        torch.cuda.reset_peak_memory_stats(device)
    sync(device)
    t0 = time.perf_counter()
    with torch.inference_mode():
        first = fn()
    sync(device)
    first_ms = (time.perf_counter() - t0) * 1000
    with torch.inference_mode():
        for _ in range(warmup):
            fn()
    sync(device)
    samples: list[float] = []
    out = first
    with torch.inference_mode():
        for _ in range(iterations):
            sync(device)
            start = time.perf_counter()
            out = fn()
            sync(device)
            samples.append((time.perf_counter() - start) * 1000)
    ordered = sorted(samples)

    def percentile(q: float) -> float:
        pos = (len(ordered) - 1) * q
        lo, hi = math.floor(pos), math.ceil(pos)
        return ordered[lo] if lo == hi else ordered[lo] * (hi - pos) + ordered[hi] * (pos - lo)

    result = {
        "status": "ok",
        "experiment": experiment,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "config": config,
        "metrics": {
            "first_call_ms": first_ms,
            "mean_ms": statistics.fmean(samples),
            "p50_ms": percentile(0.50),
            "p95_ms": percentile(0.95),
            "p99_ms": percentile(0.99),
            "min_ms": min(samples),
            "max_ms": max(samples),
            "chunks_per_second": 1000.0 / statistics.fmean(samples),
            "samples_per_second": config.get("batch_size", 1) * 1000.0 / statistics.fmean(samples),
            "per_sample_latency_ms": statistics.fmean(samples) / config.get("batch_size", 1),
            "warmup": warmup,
            "iterations": iterations,
        },
        "output": tensor_summary(out),
        "system": system_info(device),
    }
    if device.type == "cuda":
        result["metrics"]["peak_allocated_mib"] = torch.cuda.max_memory_allocated(device) / 2**20
        result["metrics"]["peak_reserved_mib"] = torch.cuda.max_memory_reserved(device) / 2**20
    return result, out.detach().float().cpu()


def tensor_summary(value: torch.Tensor) -> dict:
    x = value.detach().float()
    return {
        "shape": list(x.shape),
        "dtype": str(value.dtype),
        "finite": bool(torch.isfinite(x).all()),
        "mean": float(x.mean()),
        "std": float(x.std()),
        "min": float(x.min()),
        "max": float(x.max()),
    }


def system_info(device: torch.device) -> dict:
    info = {
        "python": platform.python_version(),
        "torch": torch.__version__,
        "hip": torch.version.hip,
        "device": str(device),
    }
    if device.type == "cuda":
        info["gpu"] = torch.cuda.get_device_name(device)
        info["bf16_supported"] = torch.cuda.is_bf16_supported()
    return info


def write_result(args: argparse.Namespace, experiment: str, result: dict, output: torch.Tensor | None = None) -> Path:
    batch_suffix = f"_bs{args.batch_size}" if getattr(args, "batch_size", 1) != 1 else ""
    path = Path(args.output) if args.output else DEFAULT_RESULTS / f"{experiment}{batch_suffix}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    if args.save_output and output is not None:
        output_path = Path(args.save_output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        np.save(output_path, output.numpy())
    print(json.dumps(result, indent=2, sort_keys=True))
    print(f"[benchmark] wrote {path}")
    return path


def run_standard(args: argparse.Namespace, experiment: str, fn, device, config: dict) -> None:
    config = {**config, "batch_size": args.batch_size}
    result, out = benchmark(
        fn, device=device, warmup=args.warmup, iterations=args.iterations, experiment=experiment, config=config
    )
    write_result(args, experiment, result, out)
