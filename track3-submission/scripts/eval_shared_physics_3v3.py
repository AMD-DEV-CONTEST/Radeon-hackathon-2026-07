#!/usr/bin/env python3
"""Headless, single-Genesis-scene multi-robot acceptance evaluation.

Unlike the historical socket demo, this runner creates *one* Genesis scene,
loads six robot entities and one shared ball, computes six commands every high
level tick, and advances one shared physics clock.  It is intentionally
importable on a CPU-only machine: Genesis is imported only inside ``run`` so
the schema/identity helpers can be tested in CI.

The output is an auditable JSON document.  A failed import, missing artifact,
solver error, or malformed state is reported as ``status=blocked``/``failed``
and never as a successful demo.

Canonical remote command (AMD GPU):

    cd /workspace/radeon-repo
    python scripts/eval_shared_physics_3v3.py --backend gpu --steps 100 \
      --model models/chase_v8_policy.onnx \
      --walk-model models/pretrained/t1_walk.pt \
      --output match_logs/shared_physics_3v3.json
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import math
import os
import sys
import time
from pathlib import Path
from typing import Any, Iterable

import numpy as np


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
ROBOT_IDS = (
    "A_attacker", "A_defender", "A_keeper",
    "B_attacker", "B_defender", "B_keeper",
)
ROBOT_ROLES = ("attacker", "defender", "keeper") * 2
POLICY_SOURCE = ROOT / "src/match_3v3/policy.py"
ENV_SOURCE = ROOT / "scripts/soccer_env_3v3.py"
EVALUATOR_SOURCE = Path(__file__).resolve()
SCHEMA_VERSION = "track3.shared_physics_3v3.v1"


def sha256_file(path: Path) -> str:
    """Hash the exact artifact bytes used by the evaluator."""
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _numpy(value: Any) -> np.ndarray:
    """Convert tensor-like data to a detached numpy array."""
    if hasattr(value, "detach"):
        value = value.detach().cpu().numpy()
    return np.asarray(value)


def _scalar(value: Any, default: Any = None) -> Any:
    if value is None:
        return default
    array = _numpy(value)
    if array.size == 0:
        return default
    return array.reshape(-1)[0].item()


def _bool(value: Any, default: bool = False) -> bool:
    value = _scalar(value, default)
    return bool(value)


def _finite_vector(value: Any, size: int, name: str) -> list[float]:
    array = np.asarray(_numpy(value), dtype=np.float64).reshape(-1)
    if array.size != size:
        raise ValueError(f"{name} expected {size} values, got shape {array.shape}")
    if not np.isfinite(array).all():
        raise ValueError(f"{name} contains non-finite values")
    return [float(item) for item in array]


def _finite_matrix(value: Any, rows: int, cols: int, name: str) -> np.ndarray:
    array = np.asarray(_numpy(value), dtype=np.float64)
    array = np.squeeze(array)
    if array.shape != (rows, cols):
        raise ValueError(f"{name} expected shape {(rows, cols)}, got {array.shape}")
    if not np.isfinite(array).all():
        raise ValueError(f"{name} contains non-finite values")
    return array


def identity_records(model_path: Path, walk_model_path: Path) -> dict[str, dict[str, Any]]:
    """Return the fixed six-way identity map used in every output row.

    The identity tuple is deliberately independent of connection/order.  A
    single ball authority is declared (A_attacker), matching the coordinator
    contract, even though all six entities physically read the shared ball.
    """
    model_sha = sha256_file(model_path)
    walk_sha = sha256_file(walk_model_path)
    rule_sha = sha256_file(POLICY_SOURCE)
    records: dict[str, dict[str, Any]] = {}
    for index, (robot_id, role) in enumerate(zip(ROBOT_IDS, ROBOT_ROLES)):
        team = robot_id[0]
        controller = "ONNX" if team == "A" else "Rule"
        records[robot_id] = {
            "robot_id": robot_id,
            "robot_index": index,
            "team": team,
            "role": role,
            "controller": controller,
            "model_sha": model_sha if controller == "ONNX" else rule_sha,
            "model_path": str(model_path.resolve()) if controller == "ONNX" else str(POLICY_SOURCE.resolve()),
            "walk_model_sha256": walk_sha,
            "ball_authority": robot_id == "A_attacker",
        }
    return records


def validate_identities(identities: dict[str, dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Validate the strict identity contract and return normalized records."""
    # Import lazily because match_protocol has no external dependencies but is
    # kept out of the module import path for tiny schema-only tools.
    from match_protocol import validate_identity

    if set(identities) != set(ROBOT_IDS):
        raise ValueError(f"identity set must be exactly {ROBOT_IDS}, got {sorted(identities)}")
    normalized: dict[str, dict[str, Any]] = {}
    combinations = set()
    authority = []
    for robot_id in ROBOT_IDS:
        item = dict(identities[robot_id])
        validated = validate_identity(item, strict=True)
        if item.get("robot_id") != robot_id or int(item.get("robot_index", -1)) != ROBOT_IDS.index(robot_id):
            raise ValueError(f"identity index/id mismatch for {robot_id}")
        combinations.add((validated["team"], validated["role"]))
        if validated["ball_authority"]:
            authority.append(robot_id)
        item.update(validated)
        normalized[robot_id] = item
    if combinations != {(team, role) for team in ("A", "B") for role in ("attacker", "defender", "keeper")}:
        raise ValueError("identities must contain one attacker/defender/keeper per team")
    if authority != ["A_attacker"]:
        raise ValueError(f"ball authority must be exactly A_attacker, got {authority}")
    if any(item["controller"] != ("ONNX" if item["team"] == "A" else "Rule")
           for item in normalized.values()):
        raise ValueError("team/controller mapping must be A=ONNX and B=Rule")
    return normalized


def _terminal_state(extras: Any) -> dict[str, Any] | None:
    if not isinstance(extras, dict):
        return None
    state = extras.get("terminal_state")
    return state if isinstance(state, dict) else None


def _state_arrays(env: Any, extras: Any, done: bool) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """Read the canonical pre-reset state (or current state) from the env."""
    terminal = _terminal_state(extras) if done else None
    if terminal is not None:
        base = terminal.get("all_base_pos")
        quat = terminal.get("all_base_quat")
        euler = terminal.get("all_base_euler")
        vel = terminal.get("all_filtered_lin_vel")
        ball = terminal.get("ball_pos")
        ball_vel = terminal.get("ball_vel")
    else:
        base = getattr(env, "all_base_pos", None)
        quat = getattr(env, "all_base_quat", None)
        euler = getattr(env, "all_base_euler", None)
        vel = getattr(env, "all_filtered_lin_vel", None)
        ball = getattr(env, "ball_pos", None)
        ball_vel = getattr(env, "ball_vel", None)
    base_a = _finite_matrix(base, 6, 3, "robot positions")
    quat_a = _finite_matrix(quat, 6, 4, "robot quaternions")
    euler_a = _finite_matrix(euler, 6, 3, "robot euler angles")
    vel_a = _finite_matrix(vel, 6, 3, "robot velocities")
    ball_a = np.asarray(_numpy(ball), dtype=np.float64).squeeze()
    ball_vel_a = np.asarray(_numpy(ball_vel), dtype=np.float64).squeeze()
    if ball_a.shape != (3,) or ball_vel_a.shape != (3,):
        raise ValueError(f"ball state must be 3D, got {ball_a.shape}/{ball_vel_a.shape}")
    if not np.isfinite(ball_a).all() or not np.isfinite(ball_vel_a).all():
        raise ValueError("ball state contains non-finite values")
    return base_a, quat_a, euler_a, vel_a, ball_a, ball_vel_a


def _robot_rows(identities: dict[str, dict[str, Any]], base: np.ndarray,
                quat: np.ndarray, euler: np.ndarray, vel: np.ndarray,
                fall_height: float, term_pitch: float, term_roll: float) -> dict[str, dict[str, Any]]:
    base = np.asarray(base, dtype=np.float64)
    quat = np.asarray(quat, dtype=np.float64)
    euler = np.asarray(euler, dtype=np.float64)
    vel = np.asarray(vel, dtype=np.float64)
    rows: dict[str, dict[str, Any]] = {}
    for index, robot_id in enumerate(ROBOT_IDS):
        fallen = bool(base[index, 2] < fall_height or
                      abs(euler[index, 1]) > term_pitch or abs(euler[index, 0]) > term_roll)
        rows[robot_id] = {
            "robot_index": index,
            "team": identities[robot_id]["team"],
            "role": identities[robot_id]["role"],
            "controller": identities[robot_id]["controller"],
            "model_sha": identities[robot_id]["model_sha"],
            "position": [float(item) for item in base[index]],
            "quaternion": [float(item) for item in quat[index]],
            "euler": [float(item) for item in euler[index]],
            "velocity": [float(item) for item in vel[index]],
            "fallen": fallen,
        }
    return rows


def _make_player(player_cls: Any, team_cls: Any, role_cls: Any, index: int,
                 robot: dict[str, Any]) -> Any:
    team = team_cls.LEFT if robot["team"] == "A" else team_cls.RIGHT
    role = {"attacker": role_cls.ATTACKER, "defender": role_cls.DEFENDER,
            "keeper": role_cls.GOALKEEPER}[robot["role"]]
    return player_cls(team=team, robot_idx=index, role=role)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", type=Path, default=ROOT / "models/chase_v8_policy.onnx",
                        help="ONNX high-level controller for team A")
    parser.add_argument("--walk-model", type=Path, default=ROOT / "models/pretrained/t1_walk.pt",
                        help="frozen 720->21 locomotion TorchScript model")
    parser.add_argument("--config", type=Path, default=ROOT / "configs/hierarchical_agent.yaml")
    parser.add_argument("--steps", type=int, default=100)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--backend", choices=("gpu", "cpu"), default="gpu")
    parser.add_argument("--output", type=Path,
                        default=ROOT / "match_logs/shared_physics_3v3.json")
    parser.add_argument("--viewer", action="store_true",
                        help="debug only; acceptance runs leave the viewer disabled")
    parser.add_argument("--zero-actions", action="store_true",
                        help="diagnostic mode: advance physics with zero high-level commands")
    parser.add_argument("--hold-stand", action="store_true",
                        help="diagnostic mode: hold default joint pose; skip walk-model outputs")
    return parser


def _failure_report(args: argparse.Namespace, reason: str, started: float) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "status": "blocked",
        "validation_status": "failed",
        "failure": str(reason),
        "configuration": {
            "seed": int(args.seed), "steps_requested": int(args.steps),
            "backend": args.backend, "single_scene": True, "num_envs": 1,
            "headless": not bool(args.viewer),
            "model_path": str(args.model), "walk_model_path": str(args.walk_model),
        },
        "steps": [],
        "events": {"fall_event_count": None, "score_event_count": None,
                   "kick_event_count": None},
        "duration_s": time.perf_counter() - started,
    }


def run(args: argparse.Namespace) -> dict[str, Any]:
    """Run the physical evaluation and return its JSON-compatible report."""
    if args.steps <= 0:
        raise ValueError("--steps must be positive")
    args.model = Path(args.model).expanduser()
    args.walk_model = Path(args.walk_model).expanduser()
    args.config = Path(args.config).expanduser()
    for path in (args.model, args.walk_model, args.config):
        if not path.is_file():
            raise FileNotFoundError(path)

    identities = validate_identities(identity_records(args.model, args.walk_model))
    import torch
    import yaml
    import genesis as gs

    sys.path.insert(0, str(ROOT))
    sys.path.insert(0, str(ROOT / "src"))
    # The evaluator imports the canonical six-entity environment only after
    # Genesis is initialized, keeping ``--help`` and unit tests CPU-safe.
    from scripts.soccer_env_3v3 import SoccerEnv3v3
    from match_3v3.policy import RulePolicy, SharedRLPolicy
    from match_3v3.scene import BallState, PlayerState, Role, Team

    with args.config.open(encoding="utf-8") as stream:
        cfg = yaml.safe_load(stream)
    np.random.seed(args.seed)
    torch.manual_seed(args.seed)
    backend = gs.gpu if args.backend == "gpu" else gs.cpu
    gs.init(backend=backend, precision="32", logging_level="warning", seed=args.seed)

    env_cfg = dict(cfg["env"])
    env_cfg["task"] = "chase_hl"
    env_cfg["episode_length_s"] = max(float(env_cfg.get("episode_length_s", 24.0)), args.steps * 0.1)
    high_level = cfg.get("high_level", {})
    env = SoccerEnv3v3(
        num_envs=1,
        env_cfg=env_cfg,
        obs_cfg=cfg["obs"],
        reward_cfg=cfg["reward"],
        command_cfg=cfg["command"],
        walk_model_path=str(args.walk_model),
        high_level_decimation=int(high_level.get("decimation", 5)),
        show_viewer=bool(args.viewer),
    )
    env.hold_stand = bool(args.hold_stand)

    # One ONNX session is shared by three independent policy objects.  Their
    # last-action history is separate, so no robot's action leaks into another.
    onnx_policy = SharedRLPolicy(onnx_path=str(args.model))
    if not onnx_policy.onnx_loaded:
        raise RuntimeError("ONNX controller did not load a real inference session")
    onnx_policies = [copy.copy(onnx_policy) for _ in range(3)]
    rule_policies = [RulePolicy() for _ in range(3)]

    # Explicitly check the physical cardinality before stepping.  This avoids
    # reporting a one-robot fallback as a multi-robot pass.
    if getattr(env, "num_robots", None) != 6 or len(getattr(env, "robots", [])) != 6:
        raise RuntimeError("shared scene did not create exactly six robots")
    if not hasattr(env, "ball"):
        raise RuntimeError("shared scene did not create one ball")

    samples: list[dict[str, Any]] = []
    score = {"A": 0, "B": 0}
    fall_edges = {robot_id: 0 for robot_id in ROBOT_IDS}
    previous_fallen = {robot_id: False for robot_id in ROBOT_IDS}
    score_event_count = 0
    kick_event_count = 0
    started = time.perf_counter()
    initial = env.reset()
    del initial
    term_pitch = float(getattr(env, "term_pitch", math.radians(30.0)))
    term_roll = float(getattr(env, "term_roll", math.radians(30.0)))
    fall_height = float(getattr(env, "fall_height", 0.4))
    try:
        for step_index in range(1, args.steps + 1):
            base, quat, euler, vel, ball, ball_vel = _state_arrays(env, {}, False)
            # Build one observation and one command per robot.  The model and
            # rule controller therefore receive six independent state views.
            commands = []
            for index, robot_id in enumerate(ROBOT_IDS):
                robot_identity = identities[robot_id]
                player = _make_player(PlayerState, Team, Role, index, robot_identity)
                player.pos = base[index].copy()
                player.quat = quat[index].copy()
                player.vel = vel[index].copy()
                ball_state = BallState(pos=ball.copy(), vel=ball_vel.copy())
                if args.zero_actions:
                    command = np.zeros(3, dtype=np.float32)
                else:
                    controller = onnx_policies[index] if index < 3 else rule_policies[index - 3]
                    action = controller.compute(player, ball_state)
                    command = np.asarray(action.velocity_cmd, dtype=np.float32).reshape(-1)
                if command.shape != (3,) or not np.isfinite(command).all():
                    raise ValueError(f"{robot_id} controller returned invalid command {command}")
                commands.append(command)

            action_tensor = torch.as_tensor(np.asarray(commands), dtype=env.hl_actions.dtype,
                                             device=env.device).reshape(1, 6, 3)
            _, reward, done, extras = env.step_multi(action_tensor)
            done_bool = _bool(done)
            base, quat, euler, vel, ball, ball_vel = _state_arrays(env, extras, done_bool)
            robot_rows = _robot_rows(identities, base, quat, euler, vel,
                                     fall_height, term_pitch, term_roll)
            fallen_now = {robot_id: bool(row["fallen"]) for robot_id, row in robot_rows.items()}
            fallen_events = []
            for robot_id, is_fallen in fallen_now.items():
                if is_fallen and not previous_fallen[robot_id]:
                    fall_edges[robot_id] += 1
                    fallen_events.append(robot_id)
                previous_fallen[robot_id] = is_fallen

            kick_events = []
            kick_array = extras.get("kick_events") if isinstance(extras, dict) else None
            if kick_array is not None:
                kick_array = np.asarray(_numpy(kick_array)).reshape(-1)
                kick_events = [ROBOT_IDS[i] for i, value in enumerate(kick_array[:6]) if bool(value)]
            kick_event_count += len(kick_events)

            scored_a = _bool(extras.get("terminal_state", {}).get("scored_left"), False) if isinstance(extras, dict) else False
            scored_b = _bool(extras.get("terminal_state", {}).get("scored_right"), False) if isinstance(extras, dict) else False
            scored_by = "A" if scored_a else "B" if scored_b else None
            if scored_by is not None:
                score[scored_by] += 1
                score_event_count += 1

            ball_out = bool(abs(ball[0]) > 7.5 or abs(ball[1]) > 5.0)
            samples.append({
                "step": step_index,
                "sim_time_s": float(step_index * env.high_level_dt),
                "robots": robot_rows,
                "ball": {"position": [float(item) for item in ball],
                         "velocity": [float(item) for item in ball_vel]},
                "events": {
                    "fallen": fallen_events,
                    "scored": scored_by is not None,
                    "scored_by": scored_by,
                    "kicks": kick_events,
                    "ball_out_of_bounds": ball_out,
                    "done": done_bool,
                },
                "score": dict(score),
                "reward": float(_scalar(reward, 0.0)),
            })
            if done_bool:
                # A match lifecycle may end early because of a goal/fall.  A
                # deterministic reset followed by continued stepping is useful
                # evidence, so keep the requested fixed horizon unless a solver
                # error was signalled by Genesis.
                env.reset()
                previous_fallen = {robot_id: False for robot_id in ROBOT_IDS}
    finally:
        onnx_policy.close()
        close = getattr(env, "close", None)
        if callable(close):
            close()

    if len(samples) != args.steps:
        raise RuntimeError(f"only observed {len(samples)} of {args.steps} requested steps")
    duration = time.perf_counter() - started
    all_fallen_frames = sum(
        all(robot["fallen"] for robot in sample["robots"].values())
        for sample in samples
    )
    health_issues = []
    if all_fallen_frames:
        health_issues.append(f"all_six_fallen_in_{all_fallen_frames}_frames")
    if not any(np.linalg.norm(np.asarray(sample["ball"]["velocity"][:2])) > 1e-4 for sample in samples):
        health_issues.append("no_material_ball_motion")
    validation_status = "passed" if not health_issues else "failed"
    report = {
        "schema_version": SCHEMA_VERSION,
        "status": "passed" if not health_issues else "observed",
        "validation_status": validation_status,
        "health_issues": health_issues,
        "configuration": {
            "seed": int(args.seed), "steps_requested": int(args.steps),
            "steps_observed": len(samples), "backend": args.backend,
            "headless": not bool(args.viewer), "single_scene": True,
            "num_scenes": 1, "num_envs": 1, "num_robots": 6,
            "num_balls": 1, "high_level_dt_s": float(env.high_level_dt),
            "config_path": str(args.config.resolve()),
            "model_path": str(args.model.resolve()),
            "walk_model_path": str(args.walk_model.resolve()),
        },
        "identities": identities,
        "model_hashes": {
            "onnx_sha256": sha256_file(args.model),
            "walk_model_sha256": sha256_file(args.walk_model),
            "rule_controller_source_sha256": sha256_file(POLICY_SOURCE),
            "config_sha256": sha256_file(args.config),
            "environment_source_sha256": sha256_file(ENV_SOURCE),
            "evaluator_source_sha256": sha256_file(EVALUATOR_SOURCE),
        },
        "events": {
            "fall_event_count": int(sum(fall_edges.values())),
            "falls_by_robot": fall_edges,
            "score_event_count": int(score_event_count),
            "score": score,
            "kick_event_count": int(kick_event_count),
        },
        "summary": {
            "mean_reward": float(np.mean([row["reward"] for row in samples])),
            "total_reward": float(sum(row["reward"] for row in samples)),
            "final_ball_position": samples[-1]["ball"]["position"],
            "final_score": score,
            "all_six_fallen_frames": int(all_fallen_frames),
        },
        "event_semantics": {
            "kick": "proximity-triggered simulator assistance impulse; not a controller decision or measured foot contact",
            "score": "goal-volume entry followed by immediate scene reset; one event per entry",
            "fall": "false-to-true edge from base height or roll/pitch thresholds",
        },
        "steps": samples,
        "duration_s": float(duration),
        "command": [sys.executable, *sys.argv],
    }
    return report


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    started = time.perf_counter()
    try:
        report = run(args)
        exit_code = 0 if report.get("validation_status") == "passed" else 1
    except Exception as exc:  # noqa: BLE001 - acceptance must emit a report
        report = _failure_report(args, f"{type(exc).__name__}: {exc}", started)
        exit_code = 2
    encoded = json.dumps(report, indent=2, sort_keys=True, allow_nan=False)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(encoded + "\n", encoding="utf-8")
    print(encoded)
    print(f"[shared_3v3] report={args.output} status={report['status']}", file=sys.stderr)
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
