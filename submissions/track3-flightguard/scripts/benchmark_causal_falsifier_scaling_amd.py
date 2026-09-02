#!/usr/bin/env python3
"""Benchmark always-continue learned-only causal-falsifier scaling on Radeon."""

from __future__ import annotations

import argparse
import json
import math
import os
import statistics
import subprocess
import sys
import time
from dataclasses import asdict, dataclass, replace
from pathlib import Path
from typing import Any

import torch

from flightguard.falsifier import require_registered_output_path
from flightguard.imu import perturb_imu
from scripts.evaluate_causal_falsifier_batch_amd import (
    context_gate_offsets,
    context_noise,
    indexed_gate,
    load_model,
    sha256_file,
    sha256_source_tree,
    verify_implementation_contract,
)

FROZEN_STATUS = "PRE_REGISTERED_AFTER_V3_FAILURE_BEFORE_FIRST_CAUSAL_FALSIFIER_GPU_RUN"
SCHEMA_VERSION = "flightguard-causal-falsifier-scaling-v1"
WORKER_SCHEMA_VERSION = "flightguard-causal-falsifier-scaling-worker-v1"
EXPECTED_BATCH_SIZES = (32, 128, 256, 512)


@dataclass(frozen=True)
class ScalingConfig:
    batch_sizes: tuple[int, int, int, int]
    warmup_runs: int
    measured_runs: int
    checkpoint_seed: int
    genesis_seed: int
    maximum_throughput_cv: float
    minimum_speedup_512_over_32: float


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--protocol", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--worker-batch-size", type=int, help=argparse.SUPPRESS)
    parser.add_argument("--worker-batch-index", type=int, help=argparse.SUPPRESS)
    return parser.parse_args()


def reject_nonfinite(value: str) -> None:
    raise ValueError(f"non-finite JSON constant is forbidden: {value}")


def reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    payload: dict[str, Any] = {}
    for key, value in pairs:
        if key in payload:
            raise ValueError(f"duplicate JSON key is forbidden: {key}")
        payload[key] = value
    return payload


def load_strict_json(path: Path) -> dict[str, Any]:
    payload = json.loads(
        path.read_text(encoding="utf-8"),
        parse_constant=reject_nonfinite,
        object_pairs_hook=reject_duplicate_keys,
    )
    if not isinstance(payload, dict):
        raise TypeError(f"JSON root must be an object: {path}")
    return payload


def write_json(path: Path, payload: dict[str, Any]) -> None:
    if path.exists():
        raise FileExistsError(f"refusing to overwrite: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, allow_nan=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _exact_positive_int(value: Any, *, expected: int, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value != expected:
        raise ValueError(f"{name} must be exactly {expected}")
    return value


def _finite_positive_float(value: Any, *, name: str) -> float:
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(float(value))
        or float(value) <= 0.0
    ):
        raise ValueError(f"{name} must be finite and positive")
    return float(value)


def validate_scaling_protocol(protocol: dict[str, Any]) -> ScalingConfig:
    if protocol.get("status") != FROZEN_STATUS:
        raise ValueError("causal falsifier protocol is not frozen")
    scaling = protocol.get("scaling")
    checkpoints = protocol.get("checkpoints")
    runtime = protocol.get("runtime")
    if not isinstance(scaling, dict):
        raise TypeError("protocol scaling object is missing")
    if not isinstance(checkpoints, dict) or not isinstance(runtime, dict):
        raise TypeError("protocol checkpoints/runtime objects are missing")
    batch_sizes = scaling.get("batch_sizes")
    if batch_sizes != list(EXPECTED_BATCH_SIZES):
        raise ValueError("scaling batch sizes must be exactly [32, 128, 256, 512]")
    warmup_runs = _exact_positive_int(
        scaling.get("warmup_runs"),
        expected=1,
        name="scaling.warmup_runs",
    )
    measured_runs = _exact_positive_int(
        scaling.get("measured_runs"),
        expected=3,
        name="scaling.measured_runs",
    )
    checkpoint_seed = _exact_positive_int(
        scaling.get("checkpoint_seed"),
        expected=30,
        name="scaling.checkpoint_seed",
    )
    if not isinstance(checkpoints.get(str(checkpoint_seed)), dict):
        raise TypeError("scaling checkpoint is not registered")
    genesis_seed = scaling.get("genesis_seed")
    if isinstance(genesis_seed, bool) or not isinstance(genesis_seed, int) or genesis_seed < 0:
        raise ValueError("scaling.genesis_seed must be a non-negative integer")
    maximum_cv = _finite_positive_float(
        scaling.get("maximum_throughput_cv"),
        name="scaling.maximum_throughput_cv",
    )
    minimum_speedup = _finite_positive_float(
        scaling.get("minimum_speedup_512_over_32"),
        name="scaling.minimum_speedup_512_over_32",
    )
    steps = runtime.get("steps")
    dropout_start = runtime.get("dropout_start_step")
    dropout_steps = runtime.get("dropout_steps")
    if (
        isinstance(steps, bool)
        or not isinstance(steps, int)
        or steps <= 0
        or isinstance(dropout_start, bool)
        or not isinstance(dropout_start, int)
        or dropout_start <= 0
        or isinstance(dropout_steps, bool)
        or not isinstance(dropout_steps, int)
        or dropout_steps <= 0
        or dropout_start + dropout_steps != steps
    ):
        raise ValueError("scaling requires the complete frozen fit+blackout runtime")
    if scaling.get("timed_steps") != steps:
        raise ValueError("scaling.timed_steps must equal runtime.steps")
    return ScalingConfig(
        batch_sizes=EXPECTED_BATCH_SIZES,
        warmup_runs=warmup_runs,
        measured_runs=measured_runs,
        checkpoint_seed=checkpoint_seed,
        genesis_seed=genesis_seed,
        maximum_throughput_cv=maximum_cv,
        minimum_speedup_512_over_32=minimum_speedup,
    )


def coefficient_of_variation(values: list[float]) -> float:
    if len(values) < 2:
        raise ValueError("coefficient of variation requires at least two values")
    if not all(math.isfinite(value) and value > 0.0 for value in values):
        raise ValueError("throughput values must be finite and positive")
    mean = statistics.fmean(values)
    return statistics.stdev(values) / mean


def summarize_scaling(
    worker_records: list[dict[str, Any]],
    *,
    config: ScalingConfig,
) -> dict[str, Any]:
    if [record.get("batch_size") for record in worker_records] != list(config.batch_sizes):
        raise ValueError("worker batch order differs from frozen scaling order")
    summaries: list[dict[str, Any]] = []
    for record in worker_records:
        repetitions = record.get("repetitions")
        if not isinstance(repetitions, list):
            raise TypeError("scaling worker repetitions are missing")
        warmups = [item for item in repetitions if item.get("kind") == "warmup"]
        measured = [item for item in repetitions if item.get("kind") == "measured"]
        if len(warmups) != config.warmup_runs or len(measured) != config.measured_runs:
            raise ValueError("scaling worker repetition count mismatch")
        throughputs = [float(item["transitions_per_s"]) for item in measured]
        cv = coefficient_of_variation(throughputs)
        summaries.append(
            {
                "batch_size": record["batch_size"],
                "measured_transitions_per_s": throughputs,
                "mean_transitions_per_s": statistics.fmean(throughputs),
                "coefficient_of_variation": cv,
                "maximum_peak_allocated_gib": max(
                    float(item["gpu_peak_allocated_gib"]) for item in measured
                ),
                "maximum_peak_reserved_gib": max(
                    float(item["gpu_peak_reserved_gib"]) for item in measured
                ),
            }
        )
    speedup = summaries[-1]["mean_transitions_per_s"] / summaries[0]["mean_transitions_per_s"]
    checks = {
        "batch_sizes_exact": [record["batch_size"] for record in summaries]
        == list(EXPECTED_BATCH_SIZES),
        "one_warmup_three_measured": True,
        "all_workers_integrity_pass": all(
            record.get("status") == "PASS" for record in worker_records
        ),
        "all_measured_cv_within_limit": all(
            record["coefficient_of_variation"] <= config.maximum_throughput_cv
            for record in summaries
        ),
        "throughput_speedup_512_over_32_meets_minimum": (
            speedup >= config.minimum_speedup_512_over_32
        ),
    }
    return {
        "status": "PASS" if all(checks.values()) else "FAIL",
        "checks": checks,
        "batch_summaries": summaries,
        "throughput_speedup_512_over_32": speedup,
        "acceptance": {
            "maximum_throughput_cv": config.maximum_throughput_cv,
            "minimum_speedup_512_over_32": config.minimum_speedup_512_over_32,
            "coefficient_of_variation_definition": "sample_standard_deviation / arithmetic_mean",
        },
    }


def _make_context(
    *,
    batch_size: int,
    device: torch.device,
    runtime: dict[str, Any],
) -> Any:
    from flightguard.online_context import FrozenAffineDelayConfig, FrozenAffineDelayContext

    return FrozenAffineDelayContext(
        batch_size,
        device=device,
        dtype=torch.float32,
        config=FrozenAffineDelayConfig(
            max_delay_steps=int(runtime["context_max_delay_steps"]),
            ridge=float(runtime["context_ridge"]),
            gamma_min=-float(runtime["context_gamma_limit"]),
            gamma_max=float(runtime["context_gamma_limit"]),
            bias_abs_max_mps2=float(runtime["context_bias_limit_mps2"]),
            min_fit_samples=int(runtime["context_min_fit_samples"]),
            min_score_samples=int(runtime["context_min_score_samples"]),
            min_excitation=float(runtime["context_min_excitation"]),
            delay_score_tolerance=float(runtime["context_delay_score_tolerance"]),
            min_score_improvement_absolute=float(runtime["context_min_score_improvement_absolute"]),
            min_score_improvement_relative=float(runtime["context_min_score_improvement_relative"]),
            score_residual_quantile=float(runtime["context_score_residual_quantile"]),
            max_score_samples=(
                int(runtime["dropout_start_step"]) - int(runtime["context_fit_steps"])
            ),
        ),
    )


def _make_controller(runtime: dict[str, Any]) -> Any:
    from flightguard.controller import BatchedWaypointController, controller_config_for_profile

    config = controller_config_for_profile(runtime["controller_profile"])
    config = replace(
        config,
        max_upward_vertical_acceleration=float(runtime["max_upward_vertical_acceleration_mps2"]),
        max_downward_vertical_acceleration=float(
            runtime["max_downward_vertical_acceleration_mps2"]
        ),
    )
    return BatchedWaypointController(config)


def _run_always_continue_repetition(
    *,
    env: Any,
    model: torch.nn.Module,
    context: Any,
    controller: Any,
    runtime: dict[str, Any],
    noise_seed_base: int,
    kind: str,
    repetition_index: int,
) -> dict[str, Any]:
    from flightguard.gate_math import gate_crossing, gate_lookthrough_target

    if kind not in {"warmup", "measured"}:
        raise ValueError("repetition kind is invalid")
    batch_size = env.num_envs
    device = env.device
    steps = int(runtime["steps"])
    dropout_start = int(runtime["dropout_start_step"])
    fit_steps = int(runtime["context_fit_steps"])
    all_envs = torch.arange(batch_size, device=device)
    env.reset(all_envs)
    context.reset()

    context_seeds = [
        noise_seed_base + 10_000 * repetition_index + index for index in range(batch_size)
    ]
    attitude_noise, angular_velocity_noise = context_noise(
        context_seeds,
        steps=steps,
        attitude_std_rad=math.radians(float(runtime["attitude_noise_std_deg"])),
        angular_velocity_std_rad_s=float(runtime["angular_velocity_noise_std_rad_s"]),
    )
    attitude_bias = torch.tensor(
        runtime["attitude_bias_deg"],
        device=device,
        dtype=torch.float32,
    ) * (math.pi / 180.0)
    angular_velocity_bias = torch.tensor(
        runtime["angular_velocity_bias_rad_s"],
        device=device,
        dtype=torch.float32,
    )

    estimated_position = env.drone.get_pos().clone()
    estimated_velocity = env.drone.get_vel().clone()
    control_gate_index = torch.zeros(batch_size, dtype=torch.long, device=device)
    finite = torch.ones((), dtype=torch.bool, device=device)
    reset_count = 0
    learned_prediction_steps = 0

    torch.cuda.reset_peak_memory_stats()
    torch.cuda.synchronize()
    started = time.perf_counter()
    with torch.inference_mode():
        for step in range(steps):
            if step == fit_steps:
                context.begin_scoring()
            if step == dropout_start:
                context.freeze()

            position = env.drone.get_pos()
            quaternion = env.drone.get_quat()
            velocity = env.drone.get_vel()
            angular_velocity = env.drone.get_ang()
            if step < dropout_start:
                estimated_position = position
                estimated_velocity = velocity

            measured_quaternion, measured_angular_velocity = perturb_imu(
                quaternion,
                angular_velocity,
                attitude_noise[step].to(device=device) + attitude_bias,
                angular_velocity_noise[step].to(device=device) + angular_velocity_bias,
            )
            gate_center, target_yaw = indexed_gate(
                env.gates,
                env.gate_yaws,
                control_gate_index,
            )
            controller_target = gate_lookthrough_target(
                gate_center,
                target_yaw,
                float(runtime["gate_lookthrough_m"]),
            )
            action = controller(
                estimated_position,
                measured_quaternion,
                estimated_velocity,
                measured_angular_velocity,
                controller_target,
            )
            context.push_issued(action)

            if step >= dropout_start:
                learned_acceleration = context.predict_acceleration(
                    model,
                    estimated_velocity,
                    measured_quaternion,
                    measured_angular_velocity,
                )
                proposed_position = (
                    estimated_position
                    + estimated_velocity * env.dt
                    + 0.5 * learned_acceleration * env.dt * env.dt
                )
                proposed_velocity = estimated_velocity + learned_acceleration * env.dt
                learned_prediction_steps += batch_size
            else:
                proposed_position = position
                proposed_velocity = velocity

            result = env.step(action)
            next_position = env.drone.get_pos()
            next_velocity = env.drone.get_vel()
            if step < dropout_start:
                context.observe_transition(
                    model,
                    velocity,
                    measured_quaternion,
                    measured_angular_velocity,
                    next_velocity,
                    dt=env.dt,
                    phase=("fit" if step < fit_steps else "score"),
                    mask=torch.ones(batch_size, dtype=torch.bool, device=device),
                )
                proposed_position = next_position
                proposed_velocity = next_velocity

            crossing = gate_crossing(
                estimated_position,
                proposed_position,
                gate_center,
                target_yaw,
                half_width=0.6,
                half_height=0.5,
                proxy_radius=0.08,
            )
            control_gate_index += crossing.passed.long()
            estimated_position = proposed_position
            estimated_velocity = proposed_velocity
            finite &= torch.stack(
                [
                    torch.isfinite(values).all()
                    for values in (
                        next_position,
                        next_velocity,
                        measured_quaternion,
                        measured_angular_velocity,
                        estimated_position,
                        estimated_velocity,
                        action,
                        env.last_applied_action,
                    )
                ]
            ).all()

            done_idx = torch.nonzero(result.done, as_tuple=False).reshape(-1)
            if done_idx.numel():
                reset_count += int(done_idx.numel())
                env.reset(done_idx)
                control_gate_index[done_idx] = 0
                estimated_position[done_idx] = env.drone.get_pos()[done_idx]
                estimated_velocity[done_idx] = env.drone.get_vel()[done_idx]
                if step < dropout_start:
                    context.reset(done_idx)

    torch.cuda.synchronize()
    elapsed_s = time.perf_counter() - started
    transitions = batch_size * steps
    return {
        "kind": kind,
        "repetition_index": repetition_index,
        "steps": steps,
        "transitions": transitions,
        "elapsed_s": elapsed_s,
        "transitions_per_s": transitions / elapsed_s,
        "gpu_peak_allocated_gib": torch.cuda.max_memory_allocated() / 2**30,
        "gpu_peak_reserved_gib": torch.cuda.max_memory_reserved() / 2**30,
        "all_tracked_tensors_finite": bool(finite.item()),
        "always_continue_reset_count": reset_count,
        "learned_prediction_steps": learned_prediction_steps,
        "expected_learned_prediction_steps": batch_size * (steps - dropout_start),
        "context_frozen": bool(context.frozen.item()),
        "context_post_freeze_update_attempts": int(context.post_freeze_update_attempts.item()),
    }


def run_worker(
    *,
    protocol_path: Path,
    batch_size: int,
    batch_index: int,
) -> dict[str, Any]:
    protocol = load_strict_json(protocol_path)
    protocol_sha256 = sha256_file(protocol_path)
    config = validate_scaling_protocol(protocol)
    project_root = Path(__file__).resolve().parent.parent
    implementation_files_sha256 = verify_implementation_contract(
        protocol,
        project_root=project_root,
    )
    if (
        batch_index < 0
        or batch_index >= len(config.batch_sizes)
        or config.batch_sizes[batch_index] != batch_size
    ):
        raise ValueError("worker batch index/size binding mismatch")

    checkpoints = protocol["checkpoints"]
    checkpoint_record = checkpoints[str(config.checkpoint_seed)]
    checkpoint_path = Path(checkpoint_record["path"]).resolve()
    if not checkpoint_path.is_file():
        raise FileNotFoundError(checkpoint_path)
    checkpoint_sha256 = sha256_file(checkpoint_path)
    if checkpoint_sha256 != checkpoint_record.get("sha256"):
        raise ValueError("scaling checkpoint SHA256 mismatch")

    import genesis as gs

    genesis_source = Path(gs.__file__).resolve().parents[1]
    genesis_source_tree = sha256_source_tree(genesis_source)
    expected_genesis_sha256 = protocol["execution_environment"]["genesis_source_tree_sha256"]
    if genesis_source_tree["sha256"] != expected_genesis_sha256:
        raise ValueError("Genesis source-tree SHA256 mismatch")
    worker_genesis_seed = config.genesis_seed + batch_index
    gs.init(
        backend=gs.amdgpu,
        precision="32",
        seed=worker_genesis_seed,
        performance_mode=False,
        logging_level="warning",
    )
    visible_gpu_count = torch.cuda.device_count()
    if (
        gs.backend != gs.amdgpu
        or not torch.cuda.is_available()
        or visible_gpu_count != 1
        or not torch.version.hip
    ):
        raise RuntimeError("exactly one Radeon/ROCm GPU is required")

    from flightguard.domain_randomization import DomainParameters
    from flightguard.genesis_env import FlightGuardGenesisEnv

    runtime = protocol["runtime"]
    domain_parameters = DomainParameters(
        mass_scale=torch.ones(batch_size),
        thrust_scale=torch.ones(batch_size),
        wind_acceleration_mps2=torch.zeros((batch_size, 3)),
        action_delay_steps=torch.zeros(batch_size, dtype=torch.long),
        stratum=torch.full((batch_size,), -1, dtype=torch.long),
        profile="off",
        seed=worker_genesis_seed,
    )
    env = FlightGuardGenesisEnv(
        batch_size,
        domain_parameters=domain_parameters,
    )
    if env.dt != float(runtime["dt_s"]):
        raise ValueError("Genesis environment dt differs from protocol")
    runtime_asset_sha256 = sha256_file(env.drone_urdf)
    model = load_model(checkpoint_path, gs.device)
    context = _make_context(
        batch_size=batch_size,
        device=gs.device,
        runtime=runtime,
    )
    controller = _make_controller(runtime)
    gate_seed_base = config.genesis_seed + 100_000 + batch_index * 1_000
    gate_seeds = [gate_seed_base + index for index in range(batch_size)]
    env.gates += context_gate_offsets(
        gate_seeds,
        y_jitter_m=float(runtime["gate_y_jitter_m"]),
        z_jitter_m=float(runtime["gate_z_jitter_m"]),
    ).to(device=gs.device)[:, None, :]

    repetitions: list[dict[str, Any]] = []
    total_runs = config.warmup_runs + config.measured_runs
    for repetition_index in range(total_runs):
        repetitions.append(
            _run_always_continue_repetition(
                env=env,
                model=model,
                context=context,
                controller=controller,
                runtime=runtime,
                noise_seed_base=(config.genesis_seed + 1_000_000 + batch_index * 100_000),
                kind=("warmup" if repetition_index < config.warmup_runs else "measured"),
                repetition_index=repetition_index,
            )
        )
    checks = {
        "backend_is_amdgpu": gs.backend == gs.amdgpu,
        "visible_gpu_count_is_one": visible_gpu_count == 1,
        "torch_hip_nonempty": bool(torch.version.hip),
        "all_repetitions_finite": all(
            record["all_tracked_tensors_finite"] for record in repetitions
        ),
        "all_repetitions_used_learned_only_for_full_blackout": all(
            record["learned_prediction_steps"] == record["expected_learned_prediction_steps"]
            for record in repetitions
        ),
        "all_repetitions_froze_context": all(record["context_frozen"] for record in repetitions),
        "post_freeze_context_updates_zero": all(
            record["context_post_freeze_update_attempts"] == 0 for record in repetitions
        ),
        "always_continue_kernel": True,
        "forbidden_policy_arms_absent": True,
    }
    return {
        "schema_version": WORKER_SCHEMA_VERSION,
        "status": "PASS" if all(checks.values()) else "FAIL",
        "protocol_sha256": protocol_sha256,
        "scaling_leaf_sha256": sha256_file(Path(__file__).resolve()),
        "batch_size": batch_size,
        "batch_index": batch_index,
        "worker_genesis_seed": worker_genesis_seed,
        "checkpoint": {
            "seed": config.checkpoint_seed,
            "path": str(checkpoint_path),
            "sha256": checkpoint_sha256,
        },
        "execution": {
            "backend": str(gs.backend),
            "device": str(gs.device),
            "gpu_name": torch.cuda.get_device_name(0),
            "visible_gpu_count": visible_gpu_count,
            "torch_version": torch.__version__,
            "torch_hip": torch.version.hip,
            "genesis_version": str(gs.__version__),
            "genesis_source_tree": genesis_source_tree,
            "runtime_race_asset": str(env.drone_urdf),
            "runtime_race_asset_sha256": runtime_asset_sha256,
            "implementation_files_sha256": implementation_files_sha256,
        },
        "kernel_contract": {
            "name": "causal_falsifier_learned_only_always_continue_v1",
            "evaluator_helper_source": {
                "path": str(Path(load_model.__code__.co_filename).resolve()),
                "sha256": sha256_file(Path(load_model.__code__.co_filename).resolve()),
            },
            "shared_primitives": [
                "FlightGuardGenesisEnv",
                "BatchedWaypointController",
                "FrozenAffineDelayContext",
                "FlightDynamicsModel",
                "perturb_imu",
                "gate_crossing",
                "gate_lookthrough_target",
            ],
            "terminal_handling": "reset_and_continue",
            "safety_or_fallback_policy_arms": [],
            "timing_boundary": "torch.cuda.synchronize before and after full step loop",
        },
        "controller": asdict(controller.config),
        "checks": checks,
        "repetitions": repetitions,
    }


def _parse_worker_payload(stdout: str) -> dict[str, Any]:
    lines = [line for line in stdout.splitlines() if line.strip()]
    for line in reversed(lines):
        try:
            payload = json.loads(
                line,
                parse_constant=reject_nonfinite,
                object_pairs_hook=reject_duplicate_keys,
            )
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict) and payload.get("schema_version") == WORKER_SCHEMA_VERSION:
            return payload
    raise ValueError("scaling worker did not emit its final JSON payload")


def _failure_payload(
    *,
    protocol_path: Path,
    protocol_sha256: str,
    batch_size: int,
    returncode: int,
    stdout: str,
    stderr: str,
) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "status": "FAIL",
        "protocol": {
            "path": str(protocol_path),
            "sha256": protocol_sha256,
        },
        "failure": {
            "batch_size": batch_size,
            "returncode": returncode,
            "stdout": stdout,
            "stderr": stderr,
            "automatic_retry": False,
        },
    }


def run_parent(
    *,
    protocol_path: Path,
    output_path: Path,
) -> int:
    if not protocol_path.is_file():
        raise FileNotFoundError(protocol_path)
    if output_path == protocol_path:
        raise ValueError("--output must not overwrite --protocol")
    if output_path.exists():
        raise FileExistsError(f"refusing to overwrite output: {output_path}")
    protocol = load_strict_json(protocol_path)
    require_registered_output_path(protocol, output_path, "scaling.json")
    protocol_sha256 = sha256_file(protocol_path)
    config = validate_scaling_protocol(protocol)
    expected_implementation_files = protocol.get("implementation_contract", {}).get("files")
    if not isinstance(expected_implementation_files, dict) or not expected_implementation_files:
        raise ValueError("protocol implementation file hashes are not frozen")

    worker_records: list[dict[str, Any]] = []
    script_path = Path(__file__).resolve()
    script_sha256 = sha256_file(script_path)
    project_root = script_path.parent.parent
    for batch_index, batch_size in enumerate(config.batch_sizes):
        if sha256_file(protocol_path) != protocol_sha256:
            raise RuntimeError("protocol changed after scaling preflight")
        if sha256_file(script_path) != script_sha256:
            raise RuntimeError("scaling leaf changed after scaling preflight")
        command = [
            sys.executable,
            str(script_path),
            "--protocol",
            str(protocol_path),
            "--worker-batch-size",
            str(batch_size),
            "--worker-batch-index",
            str(batch_index),
        ]
        environment = os.environ.copy()
        environment["HIP_VISIBLE_DEVICES"] = "0"
        pythonpath = [str(project_root / "src"), str(project_root)]
        if environment.get("PYTHONPATH"):
            pythonpath.append(environment["PYTHONPATH"])
        environment["PYTHONPATH"] = os.pathsep.join(pythonpath)
        run = subprocess.run(
            command,
            text=True,
            capture_output=True,
            env=environment,
            check=False,
        )
        if run.returncode:
            write_json(
                output_path,
                _failure_payload(
                    protocol_path=protocol_path,
                    protocol_sha256=protocol_sha256,
                    batch_size=batch_size,
                    returncode=run.returncode,
                    stdout=run.stdout,
                    stderr=run.stderr,
                ),
            )
            return run.returncode
        try:
            record = _parse_worker_payload(run.stdout)
        except (TypeError, ValueError) as error:
            write_json(
                output_path,
                _failure_payload(
                    protocol_path=protocol_path,
                    protocol_sha256=protocol_sha256,
                    batch_size=batch_size,
                    returncode=0,
                    stdout=run.stdout,
                    stderr=f"{run.stderr}\nworker payload error: {error}",
                ),
            )
            return 2
        if (
            record.get("protocol_sha256") != protocol_sha256
            or record.get("scaling_leaf_sha256") != script_sha256
            or record.get("batch_size") != batch_size
            or record.get("batch_index") != batch_index
            or record.get("execution", {}).get("implementation_files_sha256")
            != expected_implementation_files
        ):
            write_json(
                output_path,
                _failure_payload(
                    protocol_path=protocol_path,
                    protocol_sha256=protocol_sha256,
                    batch_size=batch_size,
                    returncode=0,
                    stdout=run.stdout,
                    stderr=f"{run.stderr}\nworker binding mismatch",
                ),
            )
            return 2
        if (
            sha256_file(protocol_path) != protocol_sha256
            or sha256_file(script_path) != script_sha256
        ):
            raise RuntimeError("protocol or scaling leaf changed during worker")
        worker_records.append(record)
        print(
            json.dumps(
                {
                    "event": "causal_falsifier_scaling_batch_complete",
                    "batch_size": batch_size,
                },
                sort_keys=True,
            ),
            flush=True,
        )

    scaling_summary = summarize_scaling(worker_records, config=config)
    payload = {
        "schema_version": SCHEMA_VERSION,
        "status": scaling_summary["status"],
        "simulation_only": True,
        "protocol": {
            "path": str(protocol_path),
            "sha256": protocol_sha256,
            "version": protocol["protocol_version"],
        },
        "execution_contract": {
            "one_radeon_gpu": True,
            "batch_order": list(config.batch_sizes),
            "warmup_runs_per_batch": config.warmup_runs,
            "measured_runs_per_batch": config.measured_runs,
            "automatic_retry": False,
            "output_overwrite": False,
            "scaling_leaf_sha256": script_sha256,
        },
        "workers": worker_records,
        "scaling": scaling_summary,
    }
    write_json(output_path, payload)
    print(
        json.dumps(
            {
                "event": "causal_falsifier_scaling_final",
                "status": payload["status"],
                "output": str(output_path),
            },
            sort_keys=True,
        ),
        flush=True,
    )
    return 0 if payload["status"] == "PASS" else 2


def main() -> None:
    args = parse_args()
    protocol_path = args.protocol.expanduser().resolve()
    worker_mode = args.worker_batch_size is not None or args.worker_batch_index is not None
    if worker_mode:
        if (
            args.worker_batch_size is None
            or args.worker_batch_index is None
            or args.output is not None
        ):
            raise ValueError("worker mode requires both worker fields and forbids --output")
        payload = run_worker(
            protocol_path=protocol_path,
            batch_size=args.worker_batch_size,
            batch_index=args.worker_batch_index,
        )
        print(json.dumps(payload, allow_nan=False, sort_keys=True), flush=True)
        if payload["status"] != "PASS":
            raise SystemExit(2)
        return
    if args.output is None:
        raise ValueError("parent mode requires --output")
    raise SystemExit(
        run_parent(
            protocol_path=protocol_path,
            output_path=args.output.expanduser().resolve(),
        )
    )


if __name__ == "__main__":
    main()
