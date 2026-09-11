#!/usr/bin/env python3
"""Run a resumable paired frozen holdout for the mobile VLA arm residual."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT / "src"))

from parcel_sorter.mobile_self_improvement_cycle import (
    build_randomized_mobile_campaign_config,
    sha256_file,
    write_json,
)


STEP_ORDER = (
    "preflight",
    "evaluate_baseline",
    "summarize_baseline",
    "evaluate_candidate",
    "summarize_candidate",
    "holdout_gate",
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--checkpoint", type=Path, required=True)
    parser.add_argument("--development-gate", type=Path, required=True)
    parser.add_argument("--trials", type=int, default=100)
    parser.add_argument("--seed", type=int, default=20260730)
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--policy-hz", type=int, default=3)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    if args.trials < 100 or args.trials % 4 != 0:
        parser.error("trials must be a multiple of four and at least 100")
    if args.workers < 1 or args.policy_hz < 1:
        parser.error("workers and policy-hz must be positive")
    if not args.checkpoint.is_dir():
        parser.error(f"checkpoint does not exist: {args.checkpoint}")
    checkpoint_config = args.checkpoint / "config.json"
    if not checkpoint_config.is_file():
        parser.error(f"checkpoint config does not exist: {checkpoint_config}")

    development_gate = _read_json(args.development_gate)
    if not (
        development_gate.get("status") == "holdout_authorized"
        and development_gate.get("closed_loop_holdout_authorized") is True
    ):
        parser.error("development gate has not authorized a frozen holdout")

    output = args.output.resolve()
    state_path = output / "holdout-state.json"
    if output.exists() and any(output.iterdir()) and not args.resume:
        parser.error(f"output must be new or --resume must be used: {output}")
    output.mkdir(parents=True, exist_ok=True)
    holdout = build_randomized_mobile_campaign_config(
        campaign_id="mobile-arm-residual-holdout-v1",
        episode_prefix="arm-holdout-v1",
        split="frozen_before_evaluation_do_not_train",
        trials=args.trials,
        seed=args.seed,
    )
    holdout_path = output / "frozen-holdout.json"
    _freeze_json(holdout_path, holdout, resume=args.resume)

    baseline_rollouts = output / "baseline"
    candidate_rollouts = output / "candidate"
    baseline_audit = output / "baseline-audit.json"
    candidate_audit = output / "candidate-audit.json"
    gate_path = output / "holdout-gate.json"
    commands = {
        "preflight": ["bash", str(PROJECT_ROOT / "scripts/preflight_radeon.sh")],
        "evaluate_baseline": _campaign_command(
            holdout_path,
            baseline_rollouts,
            args.checkpoint.resolve(),
            "base_residual",
            args.policy_hz,
            args.workers,
        ),
        "summarize_baseline": _summary_command(baseline_rollouts, baseline_audit),
        "evaluate_candidate": _campaign_command(
            holdout_path,
            candidate_rollouts,
            args.checkpoint.resolve(),
            "base_arm_residual",
            args.policy_hz,
            args.workers,
        ),
        "summarize_candidate": _summary_command(candidate_rollouts, candidate_audit),
        "holdout_gate": [
            sys.executable,
            str(PROJECT_ROOT / "scripts/gate_mobile_arm_residual_campaign.py"),
            "--phase",
            "holdout",
            "--baseline",
            str(baseline_audit),
            "--candidate",
            str(candidate_audit),
            "--output",
            str(gate_path),
        ],
    }
    state = _load_state(
        state_path,
        args=args,
        holdout_path=holdout_path,
        development_gate_path=args.development_gate.resolve(),
        commands=commands,
    )
    if args.dry_run:
        state["status"] = "dry_run"
        write_json(state_path, state)
        print(json.dumps(state, indent=2))
        return 0

    env = os.environ.copy()
    env["HIP_VISIBLE_DEVICES"] = env.get("HIP_VISIBLE_DEVICES", "0")
    env["PARCEL_SORTER_VENV"] = sys.prefix
    env["PATH"] = f"{Path(sys.prefix) / 'bin'}{os.pathsep}{env.get('PATH', '')}"
    env["PYTHONPATH"] = (
        f"{PROJECT_ROOT / 'src'}{os.pathsep}{env['PYTHONPATH']}"
        if env.get("PYTHONPATH")
        else str(PROJECT_ROOT / "src")
    )
    for step in STEP_ORDER:
        if state["steps"].get(step, {}).get("status") == "passed":
            continue
        _run_step(step, commands[step], output, state, state_path, env)
    gate = _read_json(gate_path)
    state["status"] = str(gate["status"])
    state["promoted"] = bool(gate["promoted"])
    state["holdout_gate_sha256"] = sha256_file(gate_path)
    write_json(state_path, state)
    return 0


def _campaign_command(
    config: Path,
    output: Path,
    checkpoint: Path,
    policy_mode: str,
    policy_hz: int,
    workers: int,
) -> list[str]:
    return [
        sys.executable,
        str(PROJECT_ROOT / "scripts/collect_mobile_suction_dataset_rocm.py"),
        "--config",
        str(config),
        "--output",
        str(output),
        "--backend",
        "rocm",
        "--resume",
        "--audit-only",
        "--smolvla-checkpoint",
        str(checkpoint),
        "--policy-mode",
        policy_mode,
        "--policy-hz",
        str(policy_hz),
        "--workers",
        str(workers),
    ]


def _summary_command(rollouts: Path, output: Path) -> list[str]:
    return [
        sys.executable,
        str(PROJECT_ROOT / "scripts/summarize_mobile_vla_campaign.py"),
        "--collection-summary",
        str(rollouts / "collection-summary.json"),
        "--output",
        str(output),
    ]


def _load_state(
    path: Path,
    *,
    args: argparse.Namespace,
    holdout_path: Path,
    development_gate_path: Path,
    commands: dict[str, list[str]],
) -> dict[str, Any]:
    if args.resume and path.is_file():
        state = _read_json(path)
        expected_settings = {
            "trials": args.trials,
            "seed": args.seed,
            "workers": args.workers,
            "policy_hz": args.policy_hz,
        }
        if state.get("settings") != expected_settings:
            raise RuntimeError("resume rejected: evaluation settings changed")
        if state.get("inputs", {}).get("checkpoint") != str(args.checkpoint.resolve()):
            raise RuntimeError("resume rejected: checkpoint path changed")
        if state.get("inputs", {}).get("holdout_sha256") != sha256_file(holdout_path):
            raise RuntimeError("resume rejected: frozen holdout hash changed")
        if state.get("inputs", {}).get("development_gate_sha256") != sha256_file(
            development_gate_path
        ):
            raise RuntimeError("resume rejected: development gate hash changed")
        checkpoint_config = args.checkpoint.resolve() / "config.json"
        expected_checkpoint_hash = sha256_file(checkpoint_config)
        recorded_checkpoint_hash = state.get("inputs", {}).get(
            "checkpoint_config_sha256"
        )
        if recorded_checkpoint_hash not in (None, expected_checkpoint_hash):
            raise RuntimeError("resume rejected: checkpoint config hash changed")
        state["inputs"]["checkpoint_config_sha256"] = expected_checkpoint_hash
        state["commands"] = commands
        return state
    return {
        "schema_version": 1,
        "protocol": "mobile-smolvla-anchored-arm-residual-holdout-runner-v1",
        "status": "prepared",
        "inputs": {
            "checkpoint": str(args.checkpoint.resolve()),
            "checkpoint_config_sha256": sha256_file(
                args.checkpoint.resolve() / "config.json"
            ),
            "development_gate": str(development_gate_path),
            "development_gate_sha256": sha256_file(development_gate_path),
            "holdout_sha256": sha256_file(holdout_path),
        },
        "settings": {
            "trials": args.trials,
            "seed": args.seed,
            "workers": args.workers,
            "policy_hz": args.policy_hz,
        },
        "commands": commands,
        "steps": {},
        "claim_boundary": (
            "paired frozen holdout of base-only versus anchored transport left-arm residual"
        ),
    }


def _run_step(
    name: str,
    command: list[str],
    output: Path,
    state: dict[str, Any],
    state_path: Path,
    env: dict[str, str],
) -> None:
    log_path = output / "logs" / f"{name}.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    state["status"] = "running"
    state["steps"][name] = {
        "status": "running",
        "command": command,
        "log": str(log_path),
    }
    write_json(state_path, state)
    with log_path.open("w", encoding="utf-8") as log:
        completed = subprocess.run(command, stdout=log, stderr=subprocess.STDOUT, env=env)
    state["steps"][name]["return_code"] = completed.returncode
    state["steps"][name]["status"] = (
        "passed" if completed.returncode == 0 else "failed"
    )
    write_json(state_path, state)
    if completed.returncode != 0:
        raise RuntimeError(f"holdout step failed: {name}; inspect {log_path}")


def _freeze_json(path: Path, payload: dict[str, Any], *, resume: bool) -> None:
    if resume and path.is_file():
        if _read_json(path) != payload:
            raise RuntimeError(f"resume rejected: frozen artifact changed: {path}")
        return
    write_json(path, payload)


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


if __name__ == "__main__":
    raise SystemExit(main())
