#!/usr/bin/env python3
"""Run a bounded same-device ACT-shape precision microbenchmark."""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import json
import math
import sys
import time
from pathlib import Path
from typing import Any, Callable

from mantis_rocm_bridge.contracts import ContractError
from mantis_rocm_bridge.rocm_tuning import (
    evaluate_benchmark_receipt,
    latency_summary,
    load_json_object,
    validate_tuning_plan,
    write_json_exclusive,
)


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("plan", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--warmup-iterations", type=int)
    parser.add_argument("--measured-iterations", type=int)
    parser.add_argument(
        "--allow-cpu-test-only",
        action="store_true",
        help="permit a non-ROCm functional test that makes no AMD claim",
    )
    return parser


def _autocast(torch: Any, execution_mode: str, precision: str) -> Any:
    if precision == "float32":
        return contextlib.nullcontext()
    dtype = {
        "bfloat16": torch.bfloat16,
        "float16": torch.float16,
    }[precision]
    device_type = "cuda" if execution_mode == "rocm" else "cpu"
    return torch.autocast(device_type=device_type, dtype=dtype)


def _timed_call(
    torch: Any,
    execution_mode: str,
    function: Callable[[], None],
) -> float:
    if execution_mode == "rocm":
        start = torch.cuda.Event(enable_timing=True)
        end = torch.cuda.Event(enable_timing=True)
        start.record()
        function()
        end.record()
        torch.cuda.synchronize()
        elapsed = float(start.elapsed_time(end))
    else:
        started = time.perf_counter()
        function()
        elapsed = (time.perf_counter() - started) * 1000.0
    if not math.isfinite(elapsed) or elapsed <= 0.0:
        raise RuntimeError("timer returned a non-positive or non-finite duration")
    return elapsed


def _cosine_and_error(torch: Any, baseline: Any, candidate: Any) -> tuple[bool, float, float]:
    baseline_flat = baseline.detach().float().reshape(-1)
    candidate_flat = candidate.detach().float().reshape(-1)
    finite = bool(torch.isfinite(candidate_flat).all().item())
    if not finite:
        return False, float("inf"), float("-inf")
    maximum_error = float(
        torch.max(torch.abs(baseline_flat - candidate_flat)).item()
    )
    denominator = (
        torch.linalg.vector_norm(baseline_flat)
        * torch.linalg.vector_norm(candidate_flat)
    )
    if float(denominator.item()) == 0.0:
        cosine = 1.0 if maximum_error == 0.0 else 0.0
    else:
        cosine = float(
            torch.dot(baseline_flat, candidate_flat).div(denominator).item()
        )
    return finite, maximum_error, cosine


def _profile(
    torch: Any,
    model: Any,
    inputs: Any,
    execution_mode: str,
    profile: dict[str, Any],
    warmup: int,
    measured: int,
    baseline_output: Any | None,
) -> tuple[dict[str, Any], Any]:
    precision = profile["precision"]
    model.eval()
    with torch.no_grad():
        with _autocast(torch, execution_mode, precision):
            output = model(inputs)
    reference_output = output.detach().float().cpu()
    if baseline_output is None:
        finite = bool(torch.isfinite(reference_output).all().item())
        maximum_error = 0.0
        cosine = 1.0
    else:
        finite, maximum_error, cosine = _cosine_and_error(
            torch, baseline_output, reference_output
        )

    def inference_step() -> None:
        model.eval()
        with torch.no_grad():
            with _autocast(torch, execution_mode, precision):
                model(inputs)

    def training_step() -> None:
        model.train()
        model.zero_grad(set_to_none=True)
        with _autocast(torch, execution_mode, precision):
            predicted = model(inputs)
            loss = predicted.float().square().mean()
        loss.backward()

    for _ in range(warmup):
        inference_step()
        training_step()
    if execution_mode == "rocm":
        torch.cuda.synchronize()
        torch.cuda.reset_peak_memory_stats()
    inference_samples = [
        _timed_call(torch, execution_mode, inference_step) for _ in range(measured)
    ]
    inference_peak = (
        int(torch.cuda.max_memory_allocated()) if execution_mode == "rocm" else 0
    )
    if execution_mode == "rocm":
        torch.cuda.reset_peak_memory_stats()
    training_samples = [
        _timed_call(torch, execution_mode, training_step) for _ in range(measured)
    ]
    training_peak = (
        int(torch.cuda.max_memory_allocated()) if execution_mode == "rocm" else 0
    )
    batch_size = int(inputs.shape[0])
    inference_summary = latency_summary(inference_samples)
    training_summary = latency_summary(training_samples)
    return (
        {
            "profile_id": profile["profile_id"],
            "precision": precision,
            "status": "measured",
            "output_finite": finite,
            "max_abs_error": maximum_error,
            "cosine_similarity": cosine,
            "inference": {
                "latency_ms_samples": inference_samples,
                "latency_summary": inference_summary,
                "throughput_samples_per_second": (
                    batch_size * 1000.0 / inference_summary["p50_ms"]
                ),
                "peak_memory_bytes": inference_peak,
            },
            "training": {
                "operation": "forward_mean_square_backward_without_optimizer_step",
                "latency_ms_samples": training_samples,
                "latency_summary": training_summary,
                "throughput_samples_per_second": (
                    batch_size * 1000.0 / training_summary["p50_ms"]
                ),
                "peak_memory_bytes": training_peak,
            },
        },
        reference_output,
    )


def _device_receipt(torch: Any, execution_mode: str) -> dict[str, Any]:
    if execution_mode == "cpu_test_only":
        return {
            "strict_rocm": False,
            "torch_device": "cpu",
            "torch_version": str(torch.__version__),
            "hip_version": (
                str(torch.version.hip) if getattr(torch.version, "hip", None) else None
            ),
            "device_count": 0,
            "device_name": "CPU",
            "total_memory_bytes": 0,
        }
    properties = torch.cuda.get_device_properties(0)
    return {
        "strict_rocm": True,
        "torch_device": "cuda:0",
        "torch_version": str(torch.__version__),
        "hip_version": str(torch.version.hip),
        "device_count": int(torch.cuda.device_count()),
        "device_name": str(torch.cuda.get_device_name(0)),
        "total_memory_bytes": int(properties.total_memory),
    }


def _execution_mode(torch: Any, allow_cpu_test_only: bool) -> str:
    hip = getattr(torch.version, "hip", None)
    if torch.cuda.is_available() and hip and torch.cuda.device_count() == 1:
        name = str(torch.cuda.get_device_name(0)).lower()
        if "amd" in name or "radeon" in name:
            return "rocm"
    if allow_cpu_test_only:
        return "cpu_test_only"
    raise ContractError(
        "strict single-GPU AMD ROCm runtime is unavailable; "
        "use --allow-cpu-test-only only for a non-AMD functional test"
    )


def _run(args: argparse.Namespace) -> dict[str, Any]:
    if args.output.exists():
        raise ContractError(f"refusing to overwrite output: {args.output}")
    plan = validate_tuning_plan(load_json_object(args.plan))
    protocol = plan["protocol"]
    warmup = (
        args.warmup_iterations
        if args.warmup_iterations is not None
        else protocol["warmup_iterations"]
    )
    measured = (
        args.measured_iterations
        if args.measured_iterations is not None
        else protocol["measured_iterations"]
    )
    if not 1 <= warmup <= 100 or not 1 <= measured <= 500:
        raise ContractError("iteration overrides are outside bounded limits")

    import torch

    execution_mode = _execution_mode(torch, args.allow_cpu_test_only)
    device = torch.device("cuda:0" if execution_mode == "rocm" else "cpu")
    torch.manual_seed(int(protocol["seed"]))
    if execution_mode == "rocm":
        torch.cuda.manual_seed_all(int(protocol["seed"]))

    model_plan = plan["benchmark_model"]
    morphology = plan["morphology"]

    class ActShapeModel(torch.nn.Module):
        def __init__(self) -> None:
            super().__init__()
            self.state_projection = torch.nn.Linear(
                morphology["policy_state_dimension"], model_plan["d_model"]
            )
            layer = torch.nn.TransformerEncoderLayer(
                d_model=model_plan["d_model"],
                nhead=model_plan["nhead"],
                dim_feedforward=model_plan["d_model"] * 4,
                dropout=0.0,
                activation="gelu",
                batch_first=True,
                norm_first=True,
            )
            self.encoder = torch.nn.TransformerEncoder(
                layer, num_layers=model_plan["encoder_layers"]
            )
            self.action_head = torch.nn.Linear(
                model_plan["d_model"], morphology["policy_action_dimension"]
            )

        def forward(self, state_tokens: Any) -> Any:
            return self.action_head(self.encoder(self.state_projection(state_tokens)))

    model = ActShapeModel().to(device=device, dtype=torch.float32)
    inputs = torch.randn(
        model_plan["batch_size"],
        model_plan["sequence_length"],
        morphology["policy_state_dimension"],
        device=device,
        dtype=torch.float32,
    )
    model_weight_sha256 = hashlib.sha256(
        b"".join(
            parameter.detach().cpu().contiguous().numpy().tobytes()
            for parameter in model.parameters()
        )
    ).hexdigest()
    input_sha256 = hashlib.sha256(
        inputs.detach().cpu().contiguous().numpy().tobytes()
    ).hexdigest()

    profiles: list[dict[str, Any]] = []
    baseline_output = None
    for profile in plan["profiles"]:
        try:
            measured_profile, output = _profile(
                torch,
                model,
                inputs,
                execution_mode,
                profile,
                warmup,
                measured,
                baseline_output,
            )
            profiles.append(measured_profile)
            if profile["role"] == "baseline":
                baseline_output = output
        except (RuntimeError, TypeError, ValueError) as exc:
            if profile["role"] == "baseline":
                raise
            profiles.append(
                {
                    "profile_id": profile["profile_id"],
                    "precision": profile["precision"],
                    "status": "unsupported",
                    "reason": f"{type(exc).__name__}: {exc}",
                }
            )
    if baseline_output is None:
        raise RuntimeError("baseline profile did not produce an output")

    receipt: dict[str, Any] = {
        "schema_version": 1,
        "kind": "rocm_act_shape_benchmark_receipt",
        "execution_mode": execution_mode,
        "plan_sha256": _sha256_file(args.plan),
        "device": _device_receipt(torch, execution_mode),
        "protocol": {
            "seed": int(protocol["seed"]),
            "warmup_iterations": warmup,
            "measured_iterations": measured,
            "same_model_weights_inputs_shapes_and_device": True,
            "model_weight_sha256": model_weight_sha256,
            "input_sha256": input_sha256,
        },
        "profiles": profiles,
        "claim_boundary": (
            "Synthetic ACT-shape forward/backward microbenchmark only; no dataset, "
            "training optimization step, checkpoint, task inference, or robot "
            "success was evaluated."
        ),
    }
    receipt["decision"] = evaluate_benchmark_receipt(plan, receipt)
    write_json_exclusive(args.output, receipt)
    return receipt


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        result = _run(args)
    except (ContractError, OSError, RuntimeError, TypeError, ValueError) as exc:
        print(
            json.dumps(
                {
                    "status": "error",
                    "error_type": type(exc).__name__,
                    "error": str(exc),
                },
                indent=2,
                sort_keys=True,
            ),
            file=sys.stderr,
        )
        return 2
    print(json.dumps(result["decision"], indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
