#!/usr/bin/env python3
"""Run the NeuPAN -> TSC -> BBC interface sanity and save JSON evidence."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import time
import types
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np

from bridge import ManeuverPhase, ManeuverWaypointGate, path_to_tsc_waypoints

ROOT = Path(__file__).resolve().parents[2]
NEUPAN_ROOT = ROOT / "NeuPAN"
AGILITY_ROOT = ROOT / "quadrupedal-agility"
DEFAULT_PLANNER = NEUPAN_ROOT / "example/dyna_non_obs/diff/planner.yaml"
DEFAULT_HIGH_POLICY = AGILITY_ROOT / "go2_deploy/models/high_policy/cruft/model.pt"
DEFAULT_LOW_POLICY = AGILITY_ROOT / "go2_deploy/models/ll_policy/3_model/model.pt"
DEFAULT_RESULT = ROOT / "experiment-results/neupan-agility/NAG-S001/result.json"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    os.replace(temporary, path)


def _headless_tkinter_shim() -> bool:
    """Work around gctl==1.2 importing an unused Tk Scale on headless hosts."""
    try:
        import tkinter  # noqa: F401
    except ModuleNotFoundError:
        tkinter = types.ModuleType("tkinter")
        tkinter.Scale = object
        sys.modules["tkinter"] = tkinter
        return True
    return False


def _git_revision(path: Path) -> str | None:
    completed = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=path,
        text=True,
        capture_output=True,
        check=False,
    )
    return completed.stdout.strip() if completed.returncode == 0 else None


def _new_neupan_planner(args: argparse.Namespace) -> tuple[Any, bool]:
    shim_used = _headless_tkinter_shim()
    from neupan import neupan

    previous_cwd = Path.cwd()
    try:
        os.chdir(NEUPAN_ROOT)
        planner = neupan.init_from_yaml(
            str(args.planner_config.resolve()), time_print=False
        )
    finally:
        os.chdir(previous_cwd)
    planner.update_initial_path_from_waypoints(planner.waypoints)
    return planner, shim_used


def _run_neupan(
    args: argparse.Namespace,
) -> tuple[dict[str, Any], np.ndarray, np.ndarray]:
    planner, shim_used = _new_neupan_planner(args)
    no_obstacle_planner, _ = _new_neupan_planner(args)

    state = np.array([[-1.0], [25.0], [0.0]])
    obstacle_y = np.linspace(
        args.obstacle_y - args.obstacle_half_span,
        args.obstacle_y + args.obstacle_half_span,
        args.obstacle_points,
    )
    points = np.vstack([np.full_like(obstacle_y, args.obstacle_x), obstacle_y])
    velocities = np.vstack(
        [np.zeros_like(obstacle_y), np.full_like(obstacle_y, args.obstacle_speed)]
    )
    started = time.perf_counter()
    action, info = planner(state, points, velocities)
    latency_ms = (time.perf_counter() - started) * 1000
    trajectory = np.hstack(planner.opt_trajectory).T
    reference_trajectory = np.hstack(planner.ref_trajectory).T

    counterfactual_started = time.perf_counter()
    no_obstacle_action, no_obstacle_info = no_obstacle_planner(state, None, None)
    counterfactual_latency_ms = (
        time.perf_counter() - counterfactual_started
    ) * 1000
    no_obstacle_trajectory = np.hstack(no_obstacle_planner.opt_trajectory).T
    obstacle_vs_reference = np.linalg.norm(
        trajectory[:, :2] - reference_trajectory[:, :2], axis=1
    )
    obstacle_vs_no_obstacle = np.linalg.norm(
        trajectory[:, :2] - no_obstacle_trajectory[:, :2], axis=1
    )
    robot_extent = np.ptp(planner.robot.vertices, axis=1).reshape(-1).tolist()
    dune_checkpoint = Path(planner.pan.dune_layer.abs_checkpoint_path)
    if not dune_checkpoint.is_absolute():
        dune_checkpoint = (NEUPAN_ROOT / dune_checkpoint).resolve()
    if not dune_checkpoint.is_file():
        raise FileNotFoundError(dune_checkpoint)
    return (
        {
            "finite": bool(
                np.isfinite(action).all()
                and np.isfinite(trajectory).all()
                and np.isfinite(reference_trajectory).all()
                and np.isfinite(no_obstacle_action).all()
                and np.isfinite(no_obstacle_trajectory).all()
            ),
            "action": action.reshape(-1).tolist(),
            "latency_ms": latency_ms,
            "stop": bool(info["stop"]),
            "arrive": bool(info["arrive"]),
            "min_distance_m": float(planner.min_distance),
            "trajectory_points": int(len(trajectory)),
            "obstacle_vs_reference_path_max_xy_m": float(
                obstacle_vs_reference.max()
            ),
            "obstacle_vs_no_obstacle_path_max_xy_m": float(
                obstacle_vs_no_obstacle.max()
            ),
            "no_obstacle": {
                "action": no_obstacle_action.reshape(-1).tolist(),
                "latency_ms": counterfactual_latency_ms,
                "stop": bool(no_obstacle_info["stop"]),
                "arrive": bool(no_obstacle_info["arrive"]),
            },
            "dune_geometry_extent_m": robot_extent,
            "dune_geometry_final_go2_compatible": False,
            "dune_checkpoint": str(dune_checkpoint),
            "dune_checkpoint_sha256": _sha256(dune_checkpoint),
            "headless_tkinter_shim": shim_used,
        },
        trajectory,
        no_obstacle_trajectory,
    )


def _make_high_actor(cfg: Any, policy_cfg: Any, device: str) -> Any:
    from go2_deploy.module.net_high import Actor, get_activation

    return Actor(
        num_prop=cfg.env.n_proprio,
        num_auxiliary=cfg.env.n_auxiliary,
        num_scan=cfg.env.n_scan,
        num_priv_latent=cfg.env.n_priv_latent,
        num_priv_explicit=cfg.env.n_priv,
        num_hist=cfg.env.history_len,
        num_actions_d=cfg.env.num_actions_d,
        num_actions_c=cfg.env.num_actions_c,
        scan_encoder_dims=policy_cfg.policy.scan_encoder_dims,
        actor_hidden_dims=policy_cfg.policy.actor_hidden_dims,
        priv_encoder_dims=policy_cfg.policy.priv_encoder_dims,
        init_with_orthogonal=policy_cfg.policy.init_with_orthogonal,
        tanh_encoder_output=policy_cfg.policy.tanh_encoder_output,
        activation=get_activation(policy_cfg.policy.activation),
    ).to(device)


def _run_tsc_bbc(
    args: argparse.Namespace, nominal_command: Any, planner_command: Any
) -> dict[str, Any]:
    sys.path.insert(0, str(AGILITY_ROOT))
    sys.path.insert(0, str(AGILITY_ROOT / "tsc"))

    import torch
    from go2_deploy.config.go2_parkour_config import (
        Go2ParkourCfg,
        Go2ParkourCfgPPO,
    )
    from go2_deploy.scripts.common import (
        build_low_level_model,
        validate_low_level_checkpoint,
    )
    from go2_deploy.utils.command_builder import CommandBuilder

    if not torch.cuda.is_available() and str(args.device).startswith("cuda"):
        raise RuntimeError("CUDA requested but unavailable")
    torch.manual_seed(args.seed)
    device = torch.device(args.device)
    if device.type == "cuda":
        torch.cuda.reset_peak_memory_stats(device)

    cfg = Go2ParkourCfg()
    policy_cfg = Go2ParkourCfgPPO()
    high_actor = _make_high_actor(cfg, policy_cfg, str(device))
    high_checkpoint = torch.load(
        args.high_policy, map_location=device, weights_only=False
    )
    high_actor.load_state_dict(high_checkpoint["depth_actor_state_dict"])

    low_actor, low_estimator = build_low_level_model(3, str(device), False)
    low_checkpoint = torch.load(
        args.low_policy, map_location=device, weights_only=False
    )
    validate_low_level_checkpoint(low_checkpoint, 3)
    low_actor.load_state_dict(low_checkpoint["actor_critic"])
    low_estimator.load_state_dict(low_checkpoint["estimator"])
    high_actor.eval()
    low_actor.eval()
    low_estimator.eval()

    commands = [nominal_command, planner_command]
    high_obs = torch.zeros(
        (len(commands), cfg.env.num_observations), device=device
    )
    high_obs[:, 57:59] = torch.tensor(
        [[command.delta_yaw, command.delta_next_yaw] for command in commands],
        device=device,
    )
    high_obs[:, 59] = 1.0  # privileged source obstacle class 0 for contract only

    started = time.perf_counter()
    with torch.no_grad():
        embedding = high_actor(high_obs, hist_encoding=True)
        logits = high_actor.actor_d(embedding)
        continuous = high_actor.actor_c(embedding)
        skills = torch.argmax(logits, dim=-1)

        low_commands = []
        for index, skill in enumerate(skills):
            builder = CommandBuilder(3, cfg, device=str(device), use_half=False)
            high_action = torch.cat(
                [skill.float().reshape(1, 1), continuous[index].reshape(1, -1)],
                dim=-1,
            )
            low_commands.append(builder.set_commands(high_action))
        low_commands_tensor = torch.cat(low_commands, dim=0)

        proprio = torch.zeros((len(commands), 57), device=device)
        explicit = low_estimator(proprio)
        low_obs = torch.cat(
            [
                proprio,
                explicit,
                torch.zeros((len(commands), 29), device=device),
                torch.zeros((len(commands), 570), device=device),
                low_commands_tensor,
            ],
            dim=-1,
        )
        joint_actions = low_actor.act_inference(low_obs, hist_encoding=True)
    if device.type == "cuda":
        torch.cuda.synchronize(device)
    latency_ms = (time.perf_counter() - started) * 1000

    finite = bool(
        torch.isfinite(embedding).all()
        and torch.isfinite(logits).all()
        and torch.isfinite(continuous).all()
        and torch.isfinite(explicit).all()
        and torch.isfinite(low_commands_tensor).all()
        and torch.isfinite(joint_actions).all()
    )
    return {
        "finite": finite,
        "synthetic_zero_observation": True,
        "high_observation_dim": int(high_obs.shape[1]),
        "low_observation_dim": int(low_obs.shape[1]),
        "joint_action_dim": int(joint_actions.shape[1]),
        "skill_names": [
            cfg.env.mocap_category[int(index)] for index in skills.detach().cpu()
        ],
        "planner_changes_high_continuous_max_abs": float(
            torch.max(torch.abs(continuous[0] - continuous[1])).item()
        ),
        "planner_changes_joint_action_max_abs": float(
            torch.max(torch.abs(joint_actions[0] - joint_actions[1])).item()
        ),
        "inference_latency_ms": latency_ms,
        "peak_cuda_memory_bytes": (
            int(torch.cuda.max_memory_allocated(device))
            if device.type == "cuda"
            else 0
        ),
        "torch_version": torch.__version__,
        "cuda_device_name": (
            torch.cuda.get_device_name(device) if device.type == "cuda" else None
        ),
        "low_commands": low_commands_tensor.detach().cpu().tolist(),
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--device", default="cuda")
    parser.add_argument("--planner-config", type=Path, default=DEFAULT_PLANNER)
    parser.add_argument("--high-policy", type=Path, default=DEFAULT_HIGH_POLICY)
    parser.add_argument("--low-policy", type=Path, default=DEFAULT_LOW_POLICY)
    parser.add_argument("--current-lookahead", type=float, default=0.35)
    parser.add_argument("--next-lookahead", type=float, default=0.70)
    parser.add_argument("--max-abs-yaw", type=float, default=0.60)
    parser.add_argument("--obstacle-x", type=float, default=2.0)
    parser.add_argument("--obstacle-y", type=float, default=25.0)
    parser.add_argument("--obstacle-half-span", type=float, default=0.5)
    parser.add_argument("--obstacle-speed", type=float, default=0.2)
    parser.add_argument("--obstacle-points", type=int, default=20)
    parser.add_argument("--result", type=Path, default=DEFAULT_RESULT)
    return parser.parse_args()


def _run(args: argparse.Namespace) -> int:
    np.random.seed(args.seed)
    if args.obstacle_points < 1 or args.obstacle_half_span <= 0:
        raise ValueError("obstacle_points and obstacle_half_span must be positive")
    for path in (args.planner_config, args.high_policy, args.low_policy):
        if not path.is_file():
            raise FileNotFoundError(path)

    neupan_result, trajectory, no_obstacle_trajectory = _run_neupan(args)
    pose = np.array([-1.0, 25.0, 0.0])
    planner_command = path_to_tsc_waypoints(
        trajectory,
        pose,
        args.current_lookahead,
        args.next_lookahead,
        args.max_abs_yaw,
    )
    nominal_command = path_to_tsc_waypoints(
        no_obstacle_trajectory,
        pose,
        args.current_lookahead,
        args.next_lookahead,
        args.max_abs_yaw,
    )

    gate = ManeuverWaypointGate()
    accepted = gate.apply(nominal_command, ManeuverPhase.NORMAL)
    frozen = gate.apply(planner_command, ManeuverPhase.COMMITTED)
    phase_gate_passed = frozen == accepted
    tsc_result = _run_tsc_bbc(args, nominal_command, planner_command)

    checks = {
        "neupan_finite": neupan_result["finite"],
        "obstacle_changes_neupan_path": (
            neupan_result["obstacle_vs_no_obstacle_path_max_xy_m"] > 1e-5
            and neupan_result["obstacle_vs_reference_path_max_xy_m"] > 1e-5
        ),
        "waypoint_yaws_within_contract": all(
            abs(value) <= args.max_abs_yaw
            for value in (
                planner_command.delta_yaw,
                planner_command.delta_next_yaw,
            )
        ),
        "committed_waypoint_frozen": phase_gate_passed,
        "tsc_bbc_finite": tsc_result["finite"],
        "bbc_action_dim_is_12": tsc_result["joint_action_dim"] == 12,
        "planner_signal_reaches_bbc": (
            tsc_result["planner_changes_joint_action_max_abs"] > 1e-7
        ),
    }
    payload = {
        "run_id": "NAG-S001",
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "status": "PASSED" if all(checks.values()) else "FAILED",
        "claim_scope": "interface-only; no physics or navigation-success claim",
        "seed": args.seed,
        "device": args.device,
        "inputs": {
            "planner_config": str(args.planner_config),
            "planner_config_sha256": _sha256(args.planner_config),
            "high_policy_sha256": _sha256(args.high_policy),
            "low_policy_sha256": _sha256(args.low_policy),
            "neupan_revision": _git_revision(NEUPAN_ROOT),
            "quadrupedal_agility_revision": _git_revision(AGILITY_ROOT),
            "lookahead_m": [args.current_lookahead, args.next_lookahead],
            "max_abs_yaw_rad": args.max_abs_yaw,
            "obstacle": {
                "x": args.obstacle_x,
                "y": args.obstacle_y,
                "half_span": args.obstacle_half_span,
                "speed": args.obstacle_speed,
                "points": args.obstacle_points,
            },
        },
        "checks": checks,
        "neupan": neupan_result,
        "adapter": {
            "nominal": nominal_command.to_dict(),
            "planned": planner_command.to_dict(),
        },
        "phase_gate": {
            "oracle_phase": True,
            "committed_waypoint_frozen": phase_gate_passed,
        },
        "tsc_bbc": tsc_result,
    }
    _write_json(args.result, payload)
    print(json.dumps(payload, indent=2, ensure_ascii=False))
    return 0 if payload["status"] == "PASSED" else 1


def main() -> int:
    args = parse_args()
    try:
        return _run(args)
    except Exception as error:
        _write_json(
            args.result,
            {
                "run_id": "NAG-S001",
                "timestamp_utc": datetime.now(timezone.utc).isoformat(),
                "status": "FAILED",
                "error": {
                    "type": type(error).__name__,
                    "message": str(error),
                },
            },
        )
        raise


if __name__ == "__main__":
    raise SystemExit(main())
