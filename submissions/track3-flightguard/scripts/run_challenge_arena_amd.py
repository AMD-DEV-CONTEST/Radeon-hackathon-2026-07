#!/usr/bin/env python3
"""Run the frozen FlightGuard Challenge Arena on one Radeon GPU.

The experiment compares the repository-default ``nominal`` geometric-PD
controller with ``robust_z`` under matched Genesis scenes.  It is strictly a
simulation-only capability demonstration, not a safety or real-flight claim.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import subprocess
import sys
import time
from dataclasses import asdict
from pathlib import Path
from typing import Any

import torch

ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = ROOT.parents[1]
CONFIG_PATH = ROOT / "configs" / "challenge_arena_v1.json"
STRATUM_NAMES = {
    0: "mass_scale_edge",
    1: "thrust_scale_edge",
    2: "horizontal_wind_edge",
    3: "vertical_wind_edge",
    4: "actuator_delay_edge",
    6: "mass_thrust_coupled",
    7: "horizontal_wind_delay_coupled",
    8: "vertical_wind_delay_coupled",
    9: "mass_horizontal_wind_coupled",
    10: "thrust_horizontal_wind_delay_coupled",
    11: "joint_adversarial_distribution",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--mode", choices=("compare", "noop", "kill"), required=True)
    parser.add_argument("--domain-profile", choices=("adversarial", "heldout"), required=True)
    parser.add_argument("--seed", type=int, required=True)
    parser.add_argument("--pairs", type=int, required=True)
    parser.add_argument("--steps", type=int, required=True)
    parser.add_argument("--log-every", type=int, default=250)
    return parser.parse_args()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def git_head() -> str:
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        check=True,
    )
    return result.stdout.strip()


def validate_args(args: argparse.Namespace, config: dict[str, Any]) -> None:
    if args.output.exists():
        raise FileExistsError(f"refusing to overwrite output: {args.output}")
    if args.pairs <= 0 or args.steps <= 0 or args.log_every <= 0:
        raise ValueError("pairs, steps, and log-every must be positive")
    if args.seed < 0:
        raise ValueError("seed must be non-negative")
    expected: dict[str, Any]
    if args.mode == "noop":
        expected = config["diagnostics"]["no_op"]
    elif args.mode == "kill":
        expected = config["diagnostics"]["kill_magnitude"]
    elif args.domain_profile == config["primary"]["domain_profile"]:
        expected = config["primary"]
    elif args.domain_profile == config["retention"]["domain_profile"]:
        expected = config["retention"]
    else:
        raise ValueError("run is outside the frozen protocol")
    if args.mode in {"noop", "kill"}:
        required = {
            "seed": expected["seed"],
            "pairs": expected["pairs"],
            "steps": expected["steps"],
            "domain_profile": expected["domain_profile"],
        }
        actual = {
            "seed": args.seed,
            "pairs": args.pairs,
            "steps": args.steps,
            "domain_profile": args.domain_profile,
        }
        if actual != required:
            raise ValueError(f"diagnostic invocation does not match frozen protocol: {actual}")
    else:
        if args.seed not in expected["seeds"]:
            raise ValueError("compare seed is outside the frozen protocol")
        expected_pairs = expected["pairs_per_seed"]
        if args.pairs != expected_pairs or args.steps != expected["steps"]:
            raise ValueError("compare shape or horizon does not match frozen protocol")


def paired_gate_offsets(
    pairs: int,
    *,
    seed: int,
    y_jitter_m: float,
    z_jitter_m: float,
) -> torch.Tensor:
    generator = torch.Generator(device="cpu")
    generator.manual_seed(seed)
    unit = torch.rand(
        (pairs, 2), generator=generator, dtype=torch.float32, device="cpu"
    ) * 2.0 - 1.0
    offsets = torch.zeros((pairs, 3), dtype=torch.float32)
    offsets[:, 1] = unit[:, 0] * y_jitter_m
    offsets[:, 2] = unit[:, 1] * z_jitter_m
    return offsets


def indexed_gate(
    gates: torch.Tensor,
    gate_yaws: torch.Tensor,
    gate_index: torch.Tensor,
) -> tuple[torch.Tensor, torch.Tensor]:
    env_index = torch.arange(gates.shape[0], device=gates.device)
    clamped = gate_index.clamp(min=0, max=gates.shape[1] - 1)
    return gates[env_index, clamped], gate_yaws[env_index, clamped]


def paired_equal(value: torch.Tensor, pairs: int) -> bool:
    return bool(torch.equal(value[:pairs], value[pairs:]))


def exact_pair_state(
    *,
    pairs: int,
    tensors: dict[str, torch.Tensor],
) -> tuple[bool, str | None]:
    for name, value in tensors.items():
        if not paired_equal(value, pairs):
            return False, name
    return True, None


def arm_summary(
    *,
    arm_slice: slice,
    terminal: torch.Tensor,
    success: torch.Tensor,
    struck: torch.Tensor,
    gates_passed: torch.Tensor,
    terminal_step: torch.Tensor,
    active_steps: torch.Tensor,
    saturated_steps: torch.Tensor,
    maximum_abs_applied_action: torch.Tensor,
) -> dict[str, Any]:
    terminal_arm = terminal[arm_slice]
    success_arm = success[arm_slice]
    saturation = saturated_steps[arm_slice].float() / active_steps[arm_slice].clamp_min(1).float()
    completed_steps = terminal_step[arm_slice][terminal_step[arm_slice] >= 0]
    return {
        "evaluated_envs": int(success_arm.numel()),
        "mission_success_count": int(success_arm.sum().item()),
        "mission_success_rate": float(success_arm.float().mean().item()),
        "mission_failure_count": int((~success_arm).sum().item()),
        "terminal_count": int(terminal_arm.sum().item()),
        "terminal_failure_count": int((terminal_arm & ~success_arm).sum().item()),
        "strike_count": int(struck[arm_slice].sum().item()),
        "unfinished_count": int((~terminal_arm).sum().item()),
        "gate_passes_total": int(gates_passed[arm_slice].sum().item()),
        "mean_gates_passed": float(gates_passed[arm_slice].float().mean().item()),
        "mean_terminal_step": (
            float(completed_steps.float().mean().item()) if completed_steps.numel() else None
        ),
        "applied_action_saturation": {
            "threshold_absolute": 1.0 - 1.0e-6,
            "maximum_per_episode_fraction": float(saturation.max().item()),
            "mean_per_episode_fraction": float(saturation.mean().item()),
            "all_episodes_at_most_5_percent": bool((saturation <= 0.05).all()),
            "per_episode_fraction": [float(value) for value in saturation.cpu().tolist()],
            "maximum_absolute_action": float(maximum_abs_applied_action[arm_slice].max().item()),
        },
    }


def pair_records(
    *,
    pairs: int,
    paired_domain: Any,
    gate_offsets: torch.Tensor,
    arm_names: tuple[str, str],
    success: torch.Tensor,
    terminal: torch.Tensor,
    struck: torch.Tensor,
    gates_passed: torch.Tensor,
    terminal_step: torch.Tensor,
    active_steps: torch.Tensor,
    saturated_steps: torch.Tensor,
    last_position: torch.Tensor,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    saturation = saturated_steps.float() / active_steps.clamp_min(1).float()
    wind = paired_domain.wind_acceleration_mps2
    for index in range(pairs):
        arms: dict[str, Any] = {}
        for group, name in enumerate(arm_names):
            offset = group * pairs + index
            arms[name] = {
                "mission_success": bool(success[offset].item()),
                "terminal": bool(terminal[offset].item()),
                "strike": bool(struck[offset].item()),
                "gates_passed": int(gates_passed[offset].item()),
                "terminal_step": int(terminal_step[offset].item()),
                "active_steps": int(active_steps[offset].item()),
                "applied_action_saturation_fraction": float(saturation[offset].item()),
                "last_position_m": [float(value) for value in last_position[offset].cpu().tolist()],
            }
        stratum = int(paired_domain.stratum[index].item())
        rows.append(
            {
                "pair_index": index,
                "stratum": stratum,
                "stratum_name": STRATUM_NAMES.get(stratum, "unknown"),
                "mass_scale": float(paired_domain.mass_scale[index].item()),
                "thrust_scale": float(paired_domain.thrust_scale[index].item()),
                "wind_acceleration_mps2": [float(value) for value in wind[index].tolist()],
                "action_delay_steps": int(paired_domain.action_delay_steps[index].item()),
                "gate_offset_m": [float(value) for value in gate_offsets[index].tolist()],
                "arms": arms,
            }
        )
    return rows


def main() -> int:
    args = parse_args()
    config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    validate_args(args, config)
    if git_head() != config["source_commit"]:
        raise RuntimeError("live commit differs from the frozen Challenge Arena commit")

    sys.path.insert(0, str(ROOT / "src"))
    import genesis as gs

    gs.init(
        backend=gs.amdgpu,
        precision="32",
        seed=args.seed,
        performance_mode=False,
        logging_level="warning",
    )
    visible_gpu_count = torch.cuda.device_count()
    if gs.backend != gs.amdgpu:
        raise RuntimeError(f"expected gs.amdgpu, got {gs.backend}")
    if not torch.cuda.is_available() or visible_gpu_count != 1:
        raise RuntimeError("Challenge Arena requires exactly one visible Radeon GPU")

    from flightguard.controller import BatchedWaypointController, controller_config_for_profile
    from flightguard.domain_randomization import sample_domain_parameters
    from flightguard.gate_math import gate_lookthrough_target
    from flightguard.genesis_env import FlightGuardGenesisEnv

    torch.manual_seed(args.seed)
    pairs = args.pairs
    total_envs = pairs * 2
    baseline_slice = slice(0, pairs)
    candidate_slice = slice(pairs, total_envs)
    domain_seed = args.seed + int(config["paired_design"]["domain_seed_offset"])
    paired_domain = sample_domain_parameters(
        pairs,
        profile=args.domain_profile,
        seed=domain_seed,
    )
    if paired_domain is None:
        raise RuntimeError("Challenge Arena requires a non-off domain profile")
    domain = paired_domain.repeat(2)
    env = FlightGuardGenesisEnv(total_envs, domain_parameters=domain)

    gate_offsets = paired_gate_offsets(
        pairs,
        seed=args.seed,
        y_jitter_m=float(config["paired_design"]["gate_jitter_y_m"]),
        z_jitter_m=float(config["paired_design"]["gate_jitter_z_m"]),
    )
    repeated_offsets = torch.cat([gate_offsets, gate_offsets], dim=0).to(device=gs.device)
    env.gates += repeated_offsets[:, None, :]
    all_envs = torch.arange(total_envs, device=gs.device)
    env.reset(all_envs)

    baseline_controller = BatchedWaypointController(controller_config_for_profile("nominal"))
    candidate_profile = "nominal" if args.mode == "noop" else "robust_z"
    candidate_controller = BatchedWaypointController(
        controller_config_for_profile(candidate_profile)
    )
    candidate_name = (
        "nominal_duplicate" if args.mode == "noop" else "zero_action" if args.mode == "kill" else "robust_z"
    )
    arm_names = ("nominal", candidate_name)

    active = torch.ones(total_envs, dtype=torch.bool, device=gs.device)
    terminal = torch.zeros_like(active)
    success = torch.zeros_like(active)
    struck = torch.zeros_like(active)
    gates_passed = torch.zeros(total_envs, dtype=torch.long, device=gs.device)
    terminal_step = torch.full((total_envs,), -1, dtype=torch.long, device=gs.device)
    active_steps = torch.zeros(total_envs, dtype=torch.long, device=gs.device)
    saturated_steps = torch.zeros(total_envs, dtype=torch.long, device=gs.device)
    maximum_abs_applied_action = torch.zeros(total_envs, dtype=torch.float32, device=gs.device)
    last_position = env.drone.get_pos().clone()
    all_finite = True
    no_op_bit_exact = True
    no_op_first_mismatch: dict[str, Any] | None = None
    action_divergent_observations = 0
    paired_active_observations = 0
    maximum_position_divergence_m = 0.0
    executed_steps = 0

    pairing_checks = {
        "mass_scale": paired_equal(domain.mass_scale, pairs),
        "thrust_scale": paired_equal(domain.thrust_scale, pairs),
        "wind_acceleration_mps2": paired_equal(domain.wind_acceleration_mps2, pairs),
        "action_delay_steps": paired_equal(domain.action_delay_steps, pairs),
        "stratum": paired_equal(domain.stratum, pairs),
        "gate_offsets": paired_equal(repeated_offsets, pairs),
    }
    if not all(pairing_checks.values()):
        raise RuntimeError(f"paired context construction failed: {pairing_checks}")

    started = time.perf_counter()
    print(json.dumps({"event": "challenge_arena_start", "mode": args.mode, "seed": args.seed, "pairs": pairs, "steps": args.steps}, sort_keys=True), flush=True)
    with torch.inference_mode():
        for step in range(args.steps):
            executed_steps = step + 1
            active_before = active.clone()
            position = env.drone.get_pos()
            quaternion = env.drone.get_quat()
            velocity = env.drone.get_vel()
            angular_velocity = env.drone.get_ang()
            gate_center, gate_yaw = indexed_gate(env.gates, env.gate_yaws, env.gate_index)
            target = gate_lookthrough_target(
                gate_center,
                gate_yaw,
                float(config["paired_design"]["gate_lookthrough_m"]),
            )

            baseline_action = baseline_controller(
                position[baseline_slice],
                quaternion[baseline_slice],
                velocity[baseline_slice],
                angular_velocity[baseline_slice],
                target[baseline_slice],
            )
            if args.mode == "kill":
                candidate_action = torch.zeros_like(baseline_action)
            else:
                candidate_action = candidate_controller(
                    position[candidate_slice],
                    quaternion[candidate_slice],
                    velocity[candidate_slice],
                    angular_velocity[candidate_slice],
                    target[candidate_slice],
                )
            action = torch.cat([baseline_action, candidate_action], dim=0)
            action = torch.where(active_before[:, None], action, torch.zeros_like(action))

            if args.mode == "noop" and no_op_bit_exact:
                exact, field = exact_pair_state(
                    pairs=pairs,
                    tensors={
                        "pre_position": position,
                        "pre_quaternion": quaternion,
                        "pre_velocity": velocity,
                        "pre_angular_velocity": angular_velocity,
                        "pre_gate_index": env.gate_index,
                        "pre_active": active_before,
                        "issued_action": action,
                    },
                )
                if not exact:
                    no_op_bit_exact = False
                    no_op_first_mismatch = {"step": step, "field": field, "phase": "pre_step"}

            if args.mode == "kill":
                paired_active_before = (
                    active_before[baseline_slice] & active_before[candidate_slice]
                )
                issued_action_diverges = (
                    (action[baseline_slice] - action[candidate_slice]).abs() > 1.0e-6
                ).any(dim=1)
                action_divergent_observations += int(
                    (issued_action_diverges & paired_active_before).sum().item()
                )
                paired_active_observations += int(paired_active_before.sum().item())

            result = env.step(action)
            applied_action = env.last_applied_action
            next_position = env.drone.get_pos()
            next_quaternion = env.drone.get_quat()
            next_velocity = env.drone.get_vel()
            next_angular_velocity = env.drone.get_ang()

            finite_now = all(
                bool(torch.isfinite(value).all())
                for value in (
                    position,
                    quaternion,
                    velocity,
                    angular_velocity,
                    action,
                    applied_action,
                    next_position,
                    next_quaternion,
                    next_velocity,
                    next_angular_velocity,
                )
            )
            all_finite = all_finite and finite_now
            active_steps += active_before.long()
            saturated_steps += (
                active_before
                & (applied_action.abs() >= 1.0 - 1.0e-6).any(dim=1)
            ).long()
            maximum_abs_applied_action = torch.maximum(
                maximum_abs_applied_action,
                torch.where(
                    active_before,
                    applied_action.abs().amax(dim=1),
                    torch.zeros_like(maximum_abs_applied_action),
                ),
            )
            last_position = torch.where(active_before[:, None], next_position, last_position)

            if args.mode == "noop" and no_op_bit_exact:
                exact, field = exact_pair_state(
                    pairs=pairs,
                    tensors={
                        "applied_action": applied_action,
                        "post_position": next_position,
                        "post_quaternion": next_quaternion,
                        "post_velocity": next_velocity,
                        "post_angular_velocity": next_angular_velocity,
                        "post_gate_index": env.gate_index,
                        "passed": result.passed,
                        "struck": result.struck,
                        "done": result.done,
                    },
                )
                if not exact:
                    no_op_bit_exact = False
                    no_op_first_mismatch = {"step": step, "field": field, "phase": "post_step"}

            if args.mode == "kill" and bool(paired_active_before.any()):
                divergence = torch.linalg.vector_norm(
                    next_position[baseline_slice] - next_position[candidate_slice], dim=1
                )
                maximum_position_divergence_m = max(
                    maximum_position_divergence_m,
                    float(divergence[paired_active_before].max().item()),
                )

            gates_passed += (result.passed & active_before).long()
            completed = result.done & (env.gate_index >= env.gates.shape[1])
            newly_done = active_before & result.done
            success |= newly_done & completed
            struck |= newly_done & result.struck
            terminal |= newly_done
            terminal_step[newly_done] = step + 1
            active = active_before & ~newly_done

            done_idx = torch.nonzero(newly_done, as_tuple=False).reshape(-1)
            if done_idx.numel():
                env.reset(done_idx)

            if executed_steps % args.log_every == 0 or executed_steps == args.steps:
                print(json.dumps({"event": "challenge_arena_progress", "step": executed_steps, "active": int(active.sum().item()), "successes": int(success.sum().item())}, sort_keys=True), flush=True)
            if not bool(active.any()):
                break

    torch.cuda.synchronize()
    elapsed = time.perf_counter() - started
    baseline = arm_summary(
        arm_slice=baseline_slice,
        terminal=terminal,
        success=success,
        struck=struck,
        gates_passed=gates_passed,
        terminal_step=terminal_step,
        active_steps=active_steps,
        saturated_steps=saturated_steps,
        maximum_abs_applied_action=maximum_abs_applied_action,
    )
    candidate = arm_summary(
        arm_slice=candidate_slice,
        terminal=terminal,
        success=success,
        struck=struck,
        gates_passed=gates_passed,
        terminal_step=terminal_step,
        active_steps=active_steps,
        saturated_steps=saturated_steps,
        maximum_abs_applied_action=maximum_abs_applied_action,
    )

    baseline_success = success[baseline_slice]
    candidate_success = success[candidate_slice]
    outcomes = {
        "both_success": int((baseline_success & candidate_success).sum().item()),
        "robust_only_success": int((~baseline_success & candidate_success).sum().item()),
        "nominal_only_success": int((baseline_success & ~candidate_success).sum().item()),
        "both_fail": int((~baseline_success & ~candidate_success).sum().item()),
        "candidate_minus_nominal_success_count": int(candidate_success.sum().item() - baseline_success.sum().item()),
    }

    per_stratum: dict[str, Any] = {}
    for value in torch.unique(paired_domain.stratum):
        stratum = int(value.item())
        mask = paired_domain.stratum == stratum
        base_mask = baseline_success[mask.to(device=gs.device)]
        cand_mask = candidate_success[mask.to(device=gs.device)]
        per_stratum[str(stratum)] = {
            "name": STRATUM_NAMES.get(stratum, "unknown"),
            "pair_count": int(mask.sum().item()),
            "nominal_success_count": int(base_mask.sum().item()),
            "candidate_success_count": int(cand_mask.sum().item()),
            "robust_only_success": int((~base_mask & cand_mask).sum().item()),
            "nominal_only_success": int((base_mask & ~cand_mask).sum().item()),
        }

    diagnostic: dict[str, Any] | None = None
    scientific_status = "MEASURED"
    exit_code = 0
    if args.mode == "noop":
        diagnostic = {
            "bit_exact": no_op_bit_exact,
            "first_mismatch": no_op_first_mismatch,
            "required_fields": ["issued_action", "applied_action", "state", "gate", "terminal"],
        }
        scientific_status = "PASS" if no_op_bit_exact else "FAIL"
        exit_code = 0 if no_op_bit_exact else 2
    elif args.mode == "kill":
        threshold = float(config["diagnostics"]["kill_magnitude"]["required"]["minimum_maximum_position_divergence_m"])
        checks = {
            "zero_action_mission_success_count_is_zero": candidate["mission_success_count"] == 0,
            "zero_action_gate_passes_total_is_zero": candidate["gate_passes_total"] == 0,
            "paired_active_observations_exist": paired_active_observations > 0,
            "issued_action_diverges": action_divergent_observations > 0,
            "position_divergence_reaches_threshold": maximum_position_divergence_m >= threshold,
        }
        diagnostic = {
            "checks": checks,
            "action_divergent_pair_steps": action_divergent_observations,
            "paired_active_pair_steps": paired_active_observations,
            "maximum_position_divergence_m": maximum_position_divergence_m,
            "minimum_required_position_divergence_m": threshold,
        }
        scientific_status = "PASS" if all(checks.values()) else "FAIL"
        exit_code = 0 if all(checks.values()) else 2

    integrity = {
        "all_fields_finite": all_finite,
        "single_visible_radeon": visible_gpu_count == 1,
        "paired_contexts_exact": all(pairing_checks.values()),
        "per_episode_applied_action_saturation_at_most_5_percent": (
            baseline["applied_action_saturation"]["all_episodes_at_most_5_percent"]
            and candidate["applied_action_saturation"]["all_episodes_at_most_5_percent"]
        ),
    }
    if not all(integrity.values()):
        scientific_status = "FAIL"
        exit_code = 2

    records = pair_records(
        pairs=pairs,
        paired_domain=paired_domain,
        gate_offsets=gate_offsets,
        arm_names=arm_names,
        success=success,
        terminal=terminal,
        struck=struck,
        gates_passed=gates_passed,
        terminal_step=terminal_step,
        active_steps=active_steps,
        saturated_steps=saturated_steps,
        last_position=last_position,
    )
    payload = {
        "schema_version": "flightguard.challenge_arena.run.v1",
        "status": scientific_status,
        "mode": args.mode,
        "simulation_only": True,
        "claim_boundary": config["claim_boundary"],
        "frozen_config": {"path": str(CONFIG_PATH), "sha256": sha256_file(CONFIG_PATH)},
        "source": {
            "commit": git_head(),
            "runner_path": str(Path(__file__).resolve()),
            "runner_sha256": sha256_file(Path(__file__).resolve()),
            "controller_sha256": sha256_file(ROOT / "src" / "flightguard" / "controller.py"),
            "domain_randomization_sha256": sha256_file(ROOT / "src" / "flightguard" / "domain_randomization.py"),
        },
        "runtime": {
            "backend": str(gs.backend),
            "device": str(gs.device),
            "gpu_name": torch.cuda.get_device_name(0),
            "visible_gpu_count": visible_gpu_count,
            "torch_version": torch.__version__,
            "torch_hip": torch.version.hip,
            "genesis_version": str(gs.__version__),
            "hip_visible_devices": os.environ.get("HIP_VISIBLE_DEVICES"),
            "elapsed_s": elapsed,
            "executed_steps": executed_steps,
            "simulated_transitions": total_envs * executed_steps,
            "transitions_per_s": total_envs * executed_steps / elapsed,
        },
        "experiment": {
            "seed": args.seed,
            "domain_seed": domain_seed,
            "domain_profile": args.domain_profile,
            "pairs": pairs,
            "total_envs": total_envs,
            "requested_steps": args.steps,
            "arm_names": list(arm_names),
            "controller_state_source": "FlightGuardGenesisEnv simulator truth",
            "same_initial_state": True,
            "same_domain_parameters": True,
            "only_controller_profile_changes": args.mode in {"compare", "noop"},
            "gate_lookthrough_m": float(config["paired_design"]["gate_lookthrough_m"]),
            "domain_summary": paired_domain.summary(),
            "pairing_checks": pairing_checks,
            "controller_configs": {
                "nominal": asdict(baseline_controller.config),
                candidate_name: None if args.mode == "kill" else asdict(candidate_controller.config),
            },
        },
        "integrity": integrity,
        "arms": {"nominal": baseline, candidate_name: candidate},
        "paired_outcomes": outcomes,
        "per_stratum": per_stratum,
        "diagnostic": diagnostic,
        "pair_records": records,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    raw = (json.dumps(payload, indent=2, sort_keys=True, allow_nan=False) + "\n").encode("utf-8")
    fd = os.open(args.output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o444)
    try:
        os.write(fd, raw)
        os.fsync(fd)
    finally:
        os.close(fd)
    print(json.dumps({"event": "challenge_arena_final", "status": scientific_status, "output": str(args.output), "output_sha256": hashlib.sha256(raw).hexdigest(), "paired_outcomes": outcomes}, sort_keys=True), flush=True)
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
