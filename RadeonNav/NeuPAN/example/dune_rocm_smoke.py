#!/usr/bin/env python3
"""Validate DUNE-only ROCm inference while keeping NRMP on the CPU."""

import argparse
import json
from pathlib import Path
import sys
import time
import types

try:
    import tkinter  # noqa: F401
except ModuleNotFoundError:
    tkinter = types.ModuleType("tkinter")
    tkinter.Scale = object
    sys.modules["tkinter"] = tkinter

import numpy as np
import torch

from neupan import configuration, neupan
from neupan.blocks import DUNE
from neupan.robot import robot


NEUPAN_ROOT = Path(__file__).resolve().parents[1]
CHECKPOINT = NEUPAN_ROOT / "example/model/go2_diff_070_040/model_2000.pth"


def make_robot(receding: int):
    return robot(
        receding=receding,
        step_time=0.1,
        kinematics="diff",
        max_speed=[2.0, 3.0],
        max_acce=[2.0, 3.0],
        length=0.70,
        width=0.40,
    )


def make_dune(device: str, receding: int, point_count: int) -> DUNE:
    configuration.device = torch.device("cpu")
    return DUNE(
        receding=receding,
        checkpoint=str(CHECKPOINT),
        robot=make_robot(receding),
        dune_max_num=point_count,
        inference_device=device,
        inference_dtype="float32",
    )


def make_inputs(receding: int, point_count: int):
    generator = torch.Generator(device="cpu").manual_seed(17)
    point_flow = [
        torch.randn(2, point_count, generator=generator)
        for _ in range(receding + 1)
    ]
    rotations = [torch.eye(2) for _ in range(receding + 1)]
    obstacle_points = [
        torch.randn(2, point_count, generator=generator)
        for _ in range(receding + 1)
    ]
    return point_flow, rotations, obstacle_points


def max_output_error(reference, candidate) -> float:
    return max(
        torch.max(torch.abs(reference_tensor - candidate_tensor)).item()
        for reference_group, candidate_group in zip(reference, candidate)
        for reference_tensor, candidate_tensor in zip(reference_group, candidate_group)
    )


def benchmark(dune: DUNE, inputs, warmup: int, iterations: int) -> float:
    for _ in range(warmup):
        dune(*inputs)
    if dune.model_device.type == "cuda":
        torch.cuda.synchronize(dune.model_device)

    start = time.perf_counter()
    for _ in range(iterations):
        dune(*inputs)
    if dune.model_device.type == "cuda":
        torch.cuda.synchronize(dune.model_device)
    return (time.perf_counter() - start) * 1000.0 / iterations


def make_planner(dune_device: str):
    planner = neupan(
        receding=3,
        step_time=0.1,
        ref_speed=0.8,
        device="cpu",
        robot_kwargs={
            "kinematics": "diff",
            "max_speed": [2.0, 3.0],
            "max_acce": [2.0, 3.0],
            "length": 0.70,
            "width": 0.40,
        },
        ipath_kwargs={
            "waypoints": [[0.0, 0.0, 0.0], [5.0, 0.0, 0.0]],
            "curve_style": "line",
            "loop": False,
            "arrive_threshold": 0.2,
            "close_threshold": 0.1,
            "ind_range": 10,
            "arrive_index_threshold": 1,
        },
        pan_kwargs={
            "iter_num": 1,
            "dune_max_num": 16,
            "nrmp_max_num": 4,
            "dune_checkpoint": str(CHECKPOINT),
            "dune_device": dune_device,
            "dune_dtype": "float32",
        },
        adjust_kwargs={
            "q_s": 0.5,
            "p_u": 1.0,
            "eta": 15.0,
            "d_max": 1.0,
            "d_min": 0.1,
            "bk": 1.0,
            "solver": "ECOS",
        },
        train_kwargs={},
    )
    planner.update_initial_path_from_waypoints(planner.waypoints)
    return planner


def planner_probe():
    state = np.array([[0.1], [0.0], [0.0]], dtype=np.float32)
    points = np.array(
        [[1.2, 1.4, 1.6, 1.8], [0.45, 0.55, 0.65, 0.75]], dtype=np.float32
    )
    cpu_planner = make_planner("cpu")
    gpu_planner = make_planner("cuda")
    cpu_action, _ = cpu_planner(state, points)
    gpu_action, gpu_info = gpu_planner(state, points)
    return {
        "cpu_action": cpu_action.ravel().tolist(),
        "gpu_action": gpu_action.ravel().tolist(),
        "action_max_abs_error": float(np.max(np.abs(cpu_action - gpu_action))),
        "dune_device": str(gpu_planner.pan.dune_layer.model_device),
        "nrmp_device": str(gpu_planner.pan.nrmp_layer.G.device),
        "nrmp_output_device": str(gpu_info["state_tensor"].device),
        "finite": bool(np.isfinite(gpu_action).all()),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--iterations", type=int, default=100)
    parser.add_argument("--warmup", type=int, default=20)
    parser.add_argument("--receding", type=int, default=10)
    parser.add_argument("--point-count", type=int, default=100)
    args = parser.parse_args()

    if not torch.cuda.is_available():
        raise RuntimeError("PyTorch cannot access a CUDA/ROCm GPU")
    if args.iterations < 1 or args.warmup < 0:
        raise ValueError("iterations must be positive and warmup must be non-negative")

    inputs = make_inputs(args.receding, args.point_count)
    cpu_dune = make_dune("cpu", args.receding, args.point_count)
    gpu_dune = make_dune("cuda", args.receding, args.point_count)
    reference = cpu_dune(*inputs)
    candidate = gpu_dune(*inputs)

    result = {
        "torch_version": torch.__version__,
        "rocm_version": torch.version.hip,
        "gpu": torch.cuda.get_device_name(0),
        "dtype": "float32",
        "input_points": (args.receding + 1) * args.point_count,
        "dune_max_abs_error": max_output_error(reference, candidate),
        "cpu_dune_ms": benchmark(cpu_dune, inputs, args.warmup, args.iterations),
        "rocm_dune_ms": benchmark(gpu_dune, inputs, args.warmup, args.iterations),
        "planner_probe": planner_probe(),
    }
    result["dune_speedup"] = result["cpu_dune_ms"] / result["rocm_dune_ms"]
    print(json.dumps(result, indent=2))

    if result["dune_max_abs_error"] > 1e-4:
        raise RuntimeError("DUNE ROCm output exceeded the FP32 error tolerance")
    if result["planner_probe"]["action_max_abs_error"] > 1e-3:
        raise RuntimeError("Hybrid planner action exceeded the error tolerance")
    if not result["planner_probe"]["finite"]:
        raise RuntimeError("Hybrid planner produced a non-finite action")
    if result["planner_probe"]["nrmp_device"] != "cpu":
        raise RuntimeError("NRMP left the required CPU device")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
