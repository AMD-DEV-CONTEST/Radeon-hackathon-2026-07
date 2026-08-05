#!/usr/bin/env python3
"""Benchmark synchronized SmolVLA policy-only latency for SDPA and FA-CK."""

from __future__ import annotations

import argparse
import json
import os
import statistics
import time
from pathlib import Path

import numpy as np
import torch
from omegaconf import OmegaConf

from rlinf.envs.libero.libero_env import LiberoEnv
from rlinf.models import get_model
from smolvla_qvgm_rlinf.extension import register


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model-path", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--task-id", type=int, default=7)
    parser.add_argument("--task-reset-state-id", type=int, default=1)
    parser.add_argument("--seed", type=int, default=2001)
    parser.add_argument("--action-steps", type=int, default=5)
    parser.add_argument("--warmup", type=int, default=3)
    parser.add_argument("--repeats", type=int, default=20)
    parser.add_argument("--compare-inference-optimization", action="store_true")
    parser.add_argument("--candidate-backend", choices=("fa_ck", "sdpa_auto"), default="fa_ck")
    parser.add_argument(
        "--optimized-backend",
        choices=("sdpa", "sdpa_auto", "fa_ck"),
        default="sdpa",
        help="Attention backend for the optimized side of an optimization comparison.",
    )
    parser.add_argument(
        "--optimization",
        choices=("loop", "residual", "language", "layers", "lightweight", "inference_mode", "layout", "safe_bundle", "deployment_bundle", "final_bundle", "layout_incremental", "both"),
        default="both",
        help="Optimization toggles used by --compare-inference-optimization.",
    )
    return parser.parse_args()


def percentile(values: list[float], q: float) -> float:
    ordered = sorted(values)
    position = (len(ordered) - 1) * q
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    fraction = position - lower
    return ordered[lower] * (1 - fraction) + ordered[upper] * fraction


def main() -> None:
    args = parse_args()
    os.environ.setdefault("MUJOCO_GL", "egl")
    os.environ.setdefault("PYOPENGL_PLATFORM", "egl")
    torch.manual_seed(args.seed)
    np.random.seed(args.seed)

    register()
    model_cfg = OmegaConf.load("configs/rlinf/libero_smolvla_eval.yaml")
    model_cfg.model_path = str(args.model_path.resolve())
    model_cfg.num_action_chunks = args.action_steps
    model = get_model(model_cfg)

    env_cfg = OmegaConf.load("configs/rlinf/libero_smolvla_closed_loop.yaml")
    env_cfg.max_episode_steps = 50
    env_cfg.task_id_filter = [args.task_id]
    env_cfg.specific_reset_id = None
    env = LiberoEnv(env_cfg, num_envs=1, seed_offset=0, total_num_processes=1, worker_info=None)
    try:
        global_id = int(sum(env.trial_id_bins[: args.task_id])) + args.task_reset_state_id
        observation, _ = env.reset(reset_state_ids=np.array([global_id]))
        if (int(env.task_ids[0]), int(env.trial_ids[0])) != (
            args.task_id,
            args.task_reset_state_id,
        ):
            observation, _ = env.reset(reset_state_ids=np.array([global_id]))

        dtype = next(model.parameters()).dtype
        noise_generator = torch.Generator(device="cuda").manual_seed(args.seed + 17)
        fixed_noise = torch.randn(
            1,
            model.config.chunk_size,
            model.config.max_action_dim,
            device="cuda",
            dtype=dtype,
            generator=noise_generator,
        )

        variants = ("baseline", "optimized") if args.compare_inference_optimization else ("sdpa", args.candidate_backend)

        def select_variant(variant: str) -> None:
            if args.compare_inference_optimization:
                os.environ["SMOLVLA_ATTENTION_BACKEND"] = (
                    args.optimized_backend if variant == "optimized" else "sdpa"
                )
                enabled = variant == "optimized"
                os.environ["SMOLVLA_OPTIMIZE_LOOP"] = "1" if enabled and args.optimization in ("loop", "both") else "0"
                os.environ["SMOLVLA_OPTIMIZE_RESIDUAL"] = "1" if enabled and args.optimization in ("residual", "both") else "0"
                os.environ["SMOLVLA_CACHE_LANGUAGE"] = "1" if enabled and args.optimization in ("language", "safe_bundle", "both") else "0"
                os.environ["SMOLVLA_CACHE_MODEL_LAYERS"] = "1" if enabled and args.optimization in ("layers", "safe_bundle", "both") else "0"
                os.environ["SMOLVLA_LIGHTWEIGHT_OUTPUT"] = "1" if enabled and args.optimization in ("lightweight", "safe_bundle", "both") else "0"
                os.environ["SMOLVLA_USE_INFERENCE_MODE"] = "1" if enabled and args.optimization in ("inference_mode", "safe_bundle", "deployment_bundle", "both") else "0"
                os.environ["SMOLVLA_CACHE_DENOISE_LAYOUT"] = "1" if enabled and args.optimization in ("layout", "final_bundle", "both") else "0"
                if enabled and args.optimization == "deployment_bundle":
                    os.environ["SMOLVLA_OPTIMIZE_LOOP"] = "1"
                    os.environ["SMOLVLA_CACHE_LANGUAGE"] = "1"
                    os.environ["SMOLVLA_CACHE_MODEL_LAYERS"] = "1"
                    os.environ["SMOLVLA_LIGHTWEIGHT_OUTPUT"] = "1"
                if enabled and args.optimization == "final_bundle":
                    os.environ["SMOLVLA_OPTIMIZE_LOOP"] = "1"
                    os.environ["SMOLVLA_CACHE_LANGUAGE"] = "1"
                    os.environ["SMOLVLA_CACHE_MODEL_LAYERS"] = "1"
                    os.environ["SMOLVLA_LIGHTWEIGHT_OUTPUT"] = "1"
                    os.environ["SMOLVLA_USE_INFERENCE_MODE"] = "1"
                if args.optimization == "layout_incremental":
                    os.environ["SMOLVLA_ATTENTION_BACKEND"] = args.optimized_backend
                    os.environ["SMOLVLA_OPTIMIZE_LOOP"] = "1"
                    os.environ["SMOLVLA_CACHE_LANGUAGE"] = "1"
                    os.environ["SMOLVLA_CACHE_MODEL_LAYERS"] = "1"
                    os.environ["SMOLVLA_LIGHTWEIGHT_OUTPUT"] = "1"
                    os.environ["SMOLVLA_USE_INFERENCE_MODE"] = "1"
                    os.environ["SMOLVLA_CACHE_DENOISE_LAYOUT"] = "1" if enabled else "0"
            else:
                os.environ["SMOLVLA_ATTENTION_BACKEND"] = variant
                os.environ["SMOLVLA_OPTIMIZE_LOOP"] = "0"
                os.environ["SMOLVLA_OPTIMIZE_RESIDUAL"] = "0"
                os.environ["SMOLVLA_CACHE_LANGUAGE"] = "0"
                os.environ["SMOLVLA_CACHE_MODEL_LAYERS"] = "0"
                os.environ["SMOLVLA_LIGHTWEIGHT_OUTPUT"] = "0"
                os.environ["SMOLVLA_USE_INFERENCE_MODE"] = "0"
                os.environ["SMOLVLA_CACHE_DENOISE_LAYOUT"] = "0"

        outputs: dict[str, torch.Tensor] = {}
        for backend in variants:
            select_variant(backend)
            for _ in range(args.warmup):
                output, _ = model.predict_action_batch(observation, noise=fixed_noise.clone())
            torch.cuda.synchronize()
            outputs[backend] = output.clone()

        timings = {backend: [] for backend in variants}
        # Alternate the first backend every iteration to reduce order and
        # temperature bias while keeping observation and flow noise identical.
        for repeat in range(args.repeats):
            order = variants if repeat % 2 == 0 else tuple(reversed(variants))
            for backend in order:
                select_variant(backend)
                torch.cuda.synchronize()
                started = time.perf_counter()
                output, _ = model.predict_action_batch(observation, noise=fixed_noise.clone())
                torch.cuda.synchronize()
                timings[backend].append((time.perf_counter() - started) * 1000.0)
                outputs[backend] = output.clone()

        summaries = {
            backend: {
                "median_ms_per_replan": statistics.median(values),
                "mean_ms_per_replan": statistics.fmean(values),
                "p10_ms_per_replan": percentile(values, 0.10),
                "p90_ms_per_replan": percentile(values, 0.90),
                "median_ms_per_executed_action": statistics.median(values) / args.action_steps,
            }
            for backend, values in timings.items()
        }
        reference, candidate = variants
        speedup = summaries[reference]["median_ms_per_replan"] / summaries[candidate]["median_ms_per_replan"]
        result = {
            "experiment": (
                "SmolVLA low-drift inference optimization"
                if args.compare_inference_optimization
                else "SmolVLA policy-only synchronized latency"
            ),
            "protocol": {
                "task_id": args.task_id,
                "reset_state_id": args.task_reset_state_id,
                "seed": args.seed,
                "fixed_observation": True,
                "fixed_explicit_flow_noise": True,
                "actions_returned_per_replan": args.action_steps,
                "warmup_per_backend": args.warmup,
                "timed_repeats_per_backend": args.repeats,
                "gpu_synchronized_before_and_after": True,
                "timed_scope": "model.predict_action_batch only",
                "environment_reset_and_step_timed": False,
            },
            "timings_ms": timings,
            "summary": summaries,
            "candidate_speedup": speedup,
            "candidate_latency_reduction_percent": (1.0 - 1.0 / speedup) * 100.0,
            "action_output_difference": {
                "max_abs": float((outputs[reference] - outputs[candidate]).abs().max()),
                "mean_abs": float((outputs[reference] - outputs[candidate]).abs().mean()),
                "bitwise_equal": bool(torch.equal(outputs[reference], outputs[candidate])),
            },
        }
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(result, indent=2))
    finally:
        env.env.close()


if __name__ == "__main__":
    main()
