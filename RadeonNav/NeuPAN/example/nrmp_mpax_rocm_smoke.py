"""Validate the experimental NRMP MPAX backend on an AMD ROCm GPU.

This is intentionally a fixed-input NRMP test rather than a navigation demo. It
compares the same obstacle-aware QP against the established ECOS CPU result,
checks constraint residuals, and reports cold/warm solve latency.
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
import types
from pathlib import Path

try:
    import tkinter  # noqa: F401
except ModuleNotFoundError:
    tkinter = types.ModuleType("tkinter")
    tkinter.Scale = object
    sys.modules["tkinter"] = tkinter

import jax
import torch

from neupan import configuration
from neupan.blocks import DUNE
from neupan.blocks.nrmp import NRMP
from neupan.robot import robot


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--receding", type=int, default=10)
    parser.add_argument("--iterations", type=int, default=3)
    parser.add_argument("--cpu-iterations", type=int, default=20)
    parser.add_argument("--json-output", type=Path)
    return parser.parse_args()


def make_robot(receding: int) -> robot:
    return robot(
        receding=receding,
        step_time=0.1,
        kinematics="diff",
        length=0.70,
        width=0.40,
        max_speed=[1.0, 1.0],
        max_acce=[2.0, 2.0],
    )


def make_inputs(receding: int, obstacle_count: int = 4):
    nominal_state = torch.zeros(3, receding + 1)
    nominal_velocity = torch.zeros(2, receding)
    reference_state = torch.zeros(3, receding + 1)
    reference_state[0] = torch.linspace(0.0, 1.0, receding + 1)
    reference_velocity = torch.full((receding,), 0.8)

    base_points = torch.tensor(
        [[0.65, 0.75, 0.85, 0.95], [-0.40, -0.15, 0.15, 0.40]],
        dtype=torch.float32,
    )[:, :obstacle_count]
    base_lam = torch.nn.functional.normalize(base_points, dim=0)
    base_mu = torch.zeros(4, obstacle_count)

    point_list = [base_points.clone() for _ in range(receding + 1)]
    lam_list = [base_lam.clone() for _ in range(receding + 1)]
    mu_list = [base_mu.clone() for _ in range(receding + 1)]
    return (
        nominal_state,
        nominal_velocity,
        reference_state,
        reference_velocity,
        mu_list,
        lam_list,
        point_list,
    )


def benchmark(call, iterations: int) -> list[float]:
    samples = []
    for _ in range(iterations):
        started = time.perf_counter()
        call()
        samples.append((time.perf_counter() - started) * 1_000.0)
    return samples


def dynamics_residual(
    model: robot,
    nominal_state: torch.Tensor,
    nominal_velocity: torch.Tensor,
    state: torch.Tensor,
    velocity: torch.Tensor,
) -> float:
    predicted = []
    for index in range(model.T):
        A, B, C = model.linear_diff_model(
            nominal_state[:, index : index + 1],
            nominal_velocity[:, index : index + 1],
            model.dt,
        )
        predicted.append(
            A @ state[:, index : index + 1]
            + B @ velocity[:, index : index + 1]
            + C
        )
    return torch.max(torch.abs(state[:, 1:] - torch.hstack(predicted))).item()


def dune_inputs(receding: int, point_count: int = 16):
    generator = torch.Generator(device="cpu").manual_seed(23)
    points = torch.randn(2, point_count, generator=generator)
    points[0] = 1.2 + 0.15 * points[0]
    points[1] = 0.45 + 0.20 * points[1]
    point_flow = [points.clone() for _ in range(receding + 1)]
    rotations = [torch.eye(2) for _ in range(receding + 1)]
    obstacle_points = [points.clone() for _ in range(receding + 1)]
    return point_flow, rotations, obstacle_points


def main() -> int:
    args = parse_args()
    if args.iterations < 1 or args.cpu_iterations < 1:
        raise ValueError("iteration counts must be positive")
    if not torch.cuda.is_available() or torch.version.hip is None:
        raise RuntimeError("a ROCm-enabled PyTorch GPU is required")

    configuration.device = torch.device("cpu")
    configuration.time_print = False
    obstacle_count = 4
    common = {
        "nrmp_max_num": obstacle_count,
        "solver": "ECOS",
        "eta": 10.0,
        "d_max": 1.0,
        "d_min": 0.1,
        "ro_obs": 50.0,
        "bk": 0.1,
    }
    cpu_robot = make_robot(args.receding)
    gpu_robot = make_robot(args.receding)
    cpu_nrmp = NRMP(args.receding, 0.1, cpu_robot, **common)
    gpu_nrmp = NRMP(
        args.receding,
        0.1,
        gpu_robot,
        **common,
        nrmp_backend="mpax_rocm",
        nrmp_fallback=False,
    )
    if gpu_nrmp.nrmp_backend != "mpax_rocm":
        raise RuntimeError(
            f"MPAX did not activate: {gpu_nrmp.nrmp_backend_reason}"
        )

    inputs = make_inputs(args.receding, obstacle_count)

    def cpu_call():
        with torch.no_grad():
            return cpu_nrmp(*inputs)

    def gpu_call():
        output = gpu_nrmp(*inputs)
        torch.cuda.synchronize()
        return output

    cpu_reference = cpu_call()
    cold_started = time.perf_counter()
    gpu_output = gpu_call()
    cold_ms = (time.perf_counter() - cold_started) * 1_000.0
    cpu_samples = benchmark(cpu_call, args.cpu_iterations)

    gpu_samples = []
    for _ in range(args.iterations):
        started = time.perf_counter()
        gpu_output = gpu_call()
        gpu_samples.append((time.perf_counter() - started) * 1_000.0)

    output_errors = {
        name: torch.max(torch.abs(candidate - reference)).item()
        for name, candidate, reference in zip(
            ("state", "velocity", "distance"), gpu_output, cpu_reference
        )
    }
    residual = dynamics_residual(
        gpu_robot, inputs[0], inputs[1], gpu_output[0], gpu_output[1]
    )
    finite = all(bool(torch.isfinite(value).all()) for value in gpu_output)

    checkpoint = (
        Path(__file__).resolve().parent
        / "model/go2_diff_070_040/model_2000.pth"
    )
    dune = DUNE(
        receding=args.receding,
        checkpoint=str(checkpoint),
        robot=gpu_robot,
        dune_max_num=16,
        inference_device="cuda",
        inference_dtype="float32",
        train_kwargs={},
    )
    mu_list, lam_list, sorted_points = dune(*dune_inputs(args.receding))
    integrated_inputs = (*inputs[:4], mu_list, lam_list, sorted_points)
    with torch.no_grad():
        integrated_cpu = cpu_nrmp(*integrated_inputs)
    integrated_started = time.perf_counter()
    integrated_gpu = gpu_nrmp(*integrated_inputs)
    torch.cuda.synchronize()
    integrated_ms = (time.perf_counter() - integrated_started) * 1_000.0
    integrated_errors = {
        name: torch.max(torch.abs(candidate - reference)).item()
        for name, candidate, reference in zip(
            ("state", "velocity", "distance"), integrated_gpu, integrated_cpu
        )
    }
    integrated_finite = all(
        bool(torch.isfinite(value).all()) for value in integrated_gpu
    )
    result = {
        "status": "PASSED",
        "backend_requested": gpu_nrmp.nrmp_backend_requested,
        "backend_active": gpu_nrmp.nrmp_backend,
        "backend_reason": gpu_nrmp.nrmp_backend_reason,
        "torch_version": torch.__version__,
        "rocm_version": torch.version.hip,
        "gpu": torch.cuda.get_device_name(0),
        "jax_version": jax.__version__,
        "jax_backend": jax.default_backend(),
        "jax_devices": [str(device) for device in jax.devices()],
        "receding": args.receding,
        "obstacle_count": obstacle_count,
        "output_max_abs_error": output_errors,
        "dynamics_max_abs_residual": residual,
        "all_outputs_finite": finite,
        "dune_device": str(dune.model_device),
        "dune_nrmp_outputs_finite": integrated_finite,
        "dune_nrmp_output_max_abs_error": integrated_errors,
        "dune_nrmp_solve_ms": integrated_ms,
        "cold_compile_and_solve_ms": cold_ms,
        "cpu_ecos_mean_ms": statistics.mean(cpu_samples),
        "cpu_ecos_samples_ms": cpu_samples,
        "mpax_rocm_mean_ms": statistics.mean(gpu_samples),
        "mpax_rocm_samples_ms": gpu_samples,
        "mpax_solver_options": gpu_nrmp.nrmp_solver_options,
    }

    if not finite:
        result["status"] = "FAILED"
    if max(output_errors.values()) > 1e-3:
        result["status"] = "FAILED"
    if residual > 1e-3:
        result["status"] = "FAILED"
    if not integrated_finite or max(integrated_errors.values()) > 1e-3:
        result["status"] = "FAILED"

    rendered = json.dumps(result, indent=2)
    print(rendered)
    if args.json_output is not None:
        args.json_output.parent.mkdir(parents=True, exist_ok=True)
        args.json_output.write_text(rendered + "\n")
    return 0 if result["status"] == "PASSED" else 1


if __name__ == "__main__":
    raise SystemExit(main())
