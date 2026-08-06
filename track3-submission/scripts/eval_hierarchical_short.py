#!/usr/bin/env python3
"""Deterministic, short, single-robot Genesis evaluation.

The script is intentionally importable without Genesis.  Genesis and the soccer
environment are imported only by :func:`run`, so report aggregation can be unit
tested on ordinary CI machines.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
import time
from pathlib import Path
from typing import Any, Iterable

import numpy as np


ROOT = Path(__file__).resolve().parents[1]
REWARD_COMPONENT_NAMES = (
    "approach_ball", "ball_control", "ball_contact", "ball_progress",
    "goal_scored", "fall_penalty",
)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _scalar(value: Any) -> Any:
    """Convert a one-env tensor/array/scalar to a Python scalar."""
    if hasattr(value, "detach"):
        value = value.detach().cpu().numpy()
    array = np.asarray(value)
    if array.size != 1:
        raise ValueError(f"expected one value, got shape {array.shape}")
    return array.reshape(-1)[0].item()


def extra_signal(extras: Any, key: str) -> tuple[bool, bool]:
    """Find an explicit environment signal, including in nested extras mappings."""
    if not isinstance(extras, dict):
        return False, False
    if key in extras:
        return True, bool(_scalar(extras[key]))
    for value in extras.values():
        if isinstance(value, dict):
            found, signal = extra_signal(value, key)
            if found:
                return found, signal
    return False, False


def reward_components(extras: Any) -> dict[str, dict[str, float]] | None:
    """Read the explicit per-step reward component contract without inference."""
    if not isinstance(extras, dict) or not isinstance(extras.get("reward_components"), dict):
        return None
    result: dict[str, dict[str, float]] = {}
    for name, component in extras["reward_components"].items():
        if (name in REWARD_COMPONENT_NAMES and isinstance(component, dict)
                and "raw" in component and "weighted" in component):
            result[name] = {
                "raw": float(_scalar(component["raw"])),
                "weighted": float(_scalar(component["weighted"])),
            }
    return result


def onnx_action(session: Any, policy_obs: Any) -> np.ndarray:
    """Run the exported policy on the environment's exact 19-element observation."""
    obs = np.asarray(policy_obs, dtype=np.float32).reshape(-1)
    if obs.shape != (19,):
        raise ValueError(f"ONNX controller requires env policy obs shape (19,), got {obs.shape}")
    input_name = session.get_inputs()[0].name
    action = np.asarray(session.run(None, {input_name: obs.reshape(1, 19)})[0], dtype=np.float32)
    action = action.reshape(-1)
    if action.shape != (3,):
        raise ValueError(f"ONNX controller returned shape {action.shape}, expected (3,)")
    return action


def terminal_positions(extras: Any) -> tuple[np.ndarray, np.ndarray] | None:
    """Read the pre-reset one-env base/ball positions from the extras contract."""
    if not isinstance(extras, dict) or not isinstance(extras.get("terminal_state"), dict):
        return None
    state = extras["terminal_state"]
    base = state.get("base_pos", state.get("base"))
    ball = state.get("ball_pos", state.get("ball"))
    if base is None or ball is None:
        return None
    base_array, ball_array = np.asarray(_to_numpy(base)).squeeze(), np.asarray(_to_numpy(ball)).squeeze()
    if base_array.shape != (3,) or ball_array.shape != (3,):
        return None
    return base_array.astype(float), ball_array.astype(float)


def termination_reason(extras: Any) -> str:
    """Return an explicit reason where available, otherwise an honest fallback."""
    if isinstance(extras, dict) and extras.get("termination_reason") is not None:
        value = extras["termination_reason"]
        if isinstance(value, (list, tuple)) and len(value) == 1:
            value = value[0]
        return str(value)
    scored_found, scored = extra_signal(extras, "scored")
    if scored_found and scored:
        return "scored"
    timeout_found, timeout = extra_signal(extras, "time_outs")
    if timeout_found and timeout:
        return "time_out"
    fallen_found, fallen = extra_signal(extras, "fallen")
    if fallen_found and fallen:
        return "fallen_or_orientation_limit"
    return "unknown"


def count_rising_edges(values: Iterable[bool]) -> int:
    count, previous = 0, False
    for value in values:
        current = bool(value)
        count += int(current and not previous)
        previous = current
    return count


def percentile95(values: list[float]) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    return float(ordered[math.ceil(0.95 * len(ordered)) - 1])


def summarize(samples: list[dict[str, Any]], initial_ball_x: float | None = None) -> dict[str, Any]:
    if not samples:
        raise ValueError("at least one sample is required")
    position_rows = [row for row in samples
                     if row["distance_m"] is not None and row["ball_x_m"] is not None]
    distances = [float(row["distance_m"]) for row in position_rows]
    ball_x = [float(row["ball_x_m"]) for row in position_rows]
    latencies = [float(row["inference_s"]) for row in samples]
    rewards = [float(row["reward"]) for row in samples]

    component_summary: dict[str, Any] = {}
    for name in REWARD_COMPONENT_NAMES:
        observed = [row.get("reward_components", {}).get(name)
                    for row in samples if isinstance(row.get("reward_components"), dict)
                    and row["reward_components"].get(name) is not None]
        status = ("observed" if len(observed) == len(samples)
                  else "partial_unknown" if observed else "unknown")
        entry: dict[str, Any] = {"status": status, "observed_steps": len(observed)}
        for field in ("raw", "weighted"):
            values = [float(component[field]) for component in observed]
            entry[field] = ({"mean": float(np.mean(values)), "sum": float(sum(values)),
                             "min": min(values), "max": max(values)} if values else
                            {"mean": None, "sum": None, "min": None, "max": None})
        component_summary[name] = entry

    def events(key: str) -> dict[str, Any]:
        observed = [row[key] for row in samples if row[key] is not None]
        if len(observed) != len(samples):
            return {"status": "unknown", "count": None,
                    "reason": f"extras did not expose '{key}' on every step"}
        return {"status": "observed", "count": count_rising_edges(observed)}

    latency_mean = float(np.mean(latencies))
    ball_initial = (ball_x[0] if ball_x else 0.0) if initial_ball_x is None else float(initial_ball_x)
    position_status = "observed" if len(position_rows) == len(samples) else "partial_unknown"
    final_position_observed = samples[-1]["distance_m"] is not None and samples[-1]["ball_x_m"] is not None
    last_position_step = max((index + 1 for index, row in enumerate(samples)
                              if row["distance_m"] is not None and row["ball_x_m"] is not None),
                             default=None)
    distance_metrics = ({"status": position_status, "observed_steps": len(position_rows),
                         "mean": float(np.mean(distances)), "min": min(distances),
                         "final": distances[-1] if final_position_observed else None,
                         "last_observed": distances[-1], "last_observed_step": last_position_step}
                        if distances else {"status": "unknown", "observed_steps": 0,
                                           "mean": None, "min": None, "final": None,
                                           "last_observed": None, "last_observed_step": None})
    ball_metrics = ({"status": position_status, "observed_steps": len(position_rows),
                     "initial": ball_initial,
                     "final": ball_x[-1] if final_position_observed else None,
                     "net": (ball_x[-1] - ball_initial) if final_position_observed else None,
                     "last_observed": ball_x[-1], "last_observed_step": last_position_step,
                     "last_observed_net": ball_x[-1] - ball_initial,
                     "maximum": max([ball_initial, *ball_x])}
                    if ball_x else {"status": "unknown", "observed_steps": 0,
                                    "initial": ball_initial, "final": None,
                                    "net": None, "last_observed": None,
                                    "last_observed_step": None, "last_observed_net": None,
                                    "maximum": None})
    return {
        "steps_observed": len(samples),
        "events": {"falls": events("fallen"), "goals": events("scored")},
        "base_to_ball_m": distance_metrics,
        "ball_x_progress_m": ball_metrics,
        "inference": {"latency_mean_ms": latency_mean * 1000.0,
                      "latency_p95_ms": percentile95(latencies) * 1000.0,
                      "fps": (1.0 / latency_mean) if latency_mean > 0 else None},
        "reward": {"sum": float(sum(rewards)), "mean": float(np.mean(rewards)),
                   "min": min(rewards), "max": max(rewards), "final": rewards[-1]},
        "reward_components": component_summary,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--controller", choices=("onnx", "rule"), default="onnx")
    parser.add_argument("--onnx", type=Path, default=ROOT / "models/chase_v8_policy.onnx")
    parser.add_argument("--walk-model", type=Path, default=ROOT / "models/pretrained/t1_walk.pt")
    parser.add_argument("--config", type=Path, default=ROOT / "configs/hierarchical_agent.yaml")
    parser.add_argument("--steps", type=int, default=100)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--backend", choices=("gpu", "cpu"), default="gpu")
    parser.add_argument("--output", type=Path)
    return parser


def _to_numpy(value: Any) -> np.ndarray:
    if hasattr(value, "detach"):
        value = value.detach().cpu().numpy()
    return np.asarray(value)


def _numpy(tensor: Any) -> np.ndarray:
    return np.asarray(_to_numpy(tensor), dtype=np.float64)


def run(args: argparse.Namespace) -> dict[str, Any]:
    if args.steps <= 0:
        raise ValueError("--steps must be positive")
    required = [args.config, args.walk_model] + ([args.onnx] if args.controller == "onnx" else [])
    for path in required:
        if not path.is_file():
            raise FileNotFoundError(path)

    import yaml
    import genesis as gs

    sys.path.insert(0, str(ROOT))
    sys.path.insert(0, str(ROOT / "src"))
    from soccer_env_hierarchical import SoccerEnvHierarchical
    from match_3v3.policy import RulePolicy
    from match_3v3.scene import BallState, PlayerState, Role, Team

    with args.config.open() as stream:
        cfg = yaml.safe_load(stream)
    np.random.seed(args.seed)
    backend = gs.gpu if args.backend == "gpu" else gs.cpu
    gs.init(backend=backend, precision="32", logging_level="warning", seed=args.seed)

    env_cfg = dict(cfg["env"])
    env_cfg["task"] = cfg.get("task", "chase_hl")
    env = SoccerEnvHierarchical(1, env_cfg, cfg["obs"], cfg["reward"], cfg["command"],
                                str(args.walk_model), cfg.get("high_level", {}).get("decimation", 5), False)
    if args.controller == "onnx":
        import onnxruntime as ort
        session = ort.InferenceSession(str(args.onnx), providers=["CPUExecutionProvider"])
        providers = list(session.get_providers())
        controller = None
    else:
        controller = RulePolicy()
        session = None
        providers = []

    samples: list[dict[str, Any]] = []
    started = time.perf_counter()
    initial_ball_x = float(_numpy(env.ball_pos[0])[0])
    termination_step = None
    ended_reason = None
    try:
        for _ in range(args.steps):
            robot_pos = _numpy(env.base_pos[0])
            robot_quat = _numpy(env.base_quat[0])
            robot_vel = _numpy(env.filtered_lin_vel[0])
            ball_pos = _numpy(env.ball_pos[0])
            ball_vel = _numpy(env.ball_vel[0])
            infer_start = time.perf_counter()
            if session is not None:
                policy_obs = _numpy(env.get_observations()["policy"][0])
                velocity_cmd = onnx_action(session, policy_obs)
            else:
                player = PlayerState(team=Team.LEFT, robot_idx=0, role=Role.ATTACKER,
                                     pos=robot_pos, quat=robot_quat, vel=robot_vel)
                ball = BallState(pos=ball_pos, vel=ball_vel)
                velocity_cmd = controller.compute(player, ball).velocity_cmd
            inference_s = time.perf_counter() - infer_start
            _, reward, done, extras = env.step(
                __import__("torch").as_tensor(velocity_cmd, dtype=env.hl_actions.dtype,
                                              device=env.device).reshape(1, 3))
            fallen_found, fallen = extra_signal(extras, "fallen")
            scored_found, scored = extra_signal(extras, "scored")
            terminated = bool(_scalar(done))
            terminal = terminal_positions(extras) if terminated else None
            if terminated and terminal is None:
                post_robot_pos = post_ball_pos = None
            elif terminal is not None:
                post_robot_pos, post_ball_pos = terminal
            else:
                post_robot_pos, post_ball_pos = _numpy(env.base_pos[0]), _numpy(env.ball_pos[0])
            samples.append({"distance_m": (float(np.linalg.norm(post_robot_pos[:2] - post_ball_pos[:2]))
                                           if post_robot_pos is not None else None),
                            "ball_x_m": (float(post_ball_pos[0]) if post_ball_pos is not None else None),
                            "inference_s": inference_s,
                            "reward": float(_scalar(reward)),
                            "reward_components": reward_components(extras),
                            "fallen": fallen if fallen_found else None,
                            "scored": scored if scored_found else None})
            if terminated:
                termination_step = len(samples)
                ended_reason = termination_reason(extras)
                break
    finally:
        close = getattr(env, "close", None)
        if callable(close):
            close()

    report = summarize(samples, initial_ball_x=initial_ball_x)
    report.update({
        "schema_version": 1,
        "command": [sys.executable, *sys.argv],
        "configuration": {"controller": args.controller, "steps": args.steps,
                          "seed": args.seed, "backend": args.backend,
                          "config": str(args.config.resolve()),
                          "onnx_execution_providers": providers},
        "hashes": {"config_sha256": sha256_file(args.config),
                   "walk_model_sha256": sha256_file(args.walk_model),
                   "onnx_model_sha256": sha256_file(args.onnx) if args.controller == "onnx" else None},
        "duration_s": time.perf_counter() - started,
        "termination_step": termination_step,
        "termination_reason": ended_reason or "step_limit",
        "termination": {"terminated": termination_step is not None,
                        "termination_step": termination_step,
                        "reason": ended_reason or "step_limit"},
    })
    return report


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    report = run(args)
    encoded = json.dumps(report, indent=2, sort_keys=True)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(encoded + "\n", encoding="utf-8")
    print(encoded)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
