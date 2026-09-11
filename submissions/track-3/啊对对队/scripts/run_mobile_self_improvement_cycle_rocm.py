#!/usr/bin/env python3
"""Run one resumable, fail-closed mobile SmolVLA improvement cycle on Radeon."""

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
    build_curriculum_config,
    build_frozen_holdout_config,
    build_replay_from_campaign_audit,
    promotion_gate,
    sha256_file,
    validate_paired_campaigns,
    validate_split_isolation,
    write_json,
)
from parcel_sorter.checkpoint_registry import activate_promoted_checkpoint
from parcel_sorter.harness_agent import (
    HarnessAgentConfig,
    authorize_agent_checkpoint_promotion,
    quarantine_correction,
    sha256_json,
    training_admission_gate,
    verify_replayed_correction,
)


BASE_STEP_ORDER = (
    "preflight",
    "collect_curriculum",
    "audit_curriculum",
    "train_candidate",
    "offline_ablation",
    "evaluate_baseline",
    "summarize_baseline",
    "evaluate_candidate",
    "summarize_candidate",
    "promotion_gate",
)
PRIMITIVE_STEP_ORDER = (
    "preflight",
    "collect_curriculum",
    "audit_curriculum",
    "build_primitive_dataset",
    "audit_primitive_dataset",
    "train_candidate",
    "offline_ablation",
    "evaluate_baseline",
    "summarize_baseline",
    "evaluate_candidate",
    "summarize_candidate",
    "promotion_gate",
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cycle-id", default="v3")
    parser.add_argument("--cycle-dir", type=Path, required=True)
    parser.add_argument("--source-campaign-audit", type=Path, required=True)
    parser.add_argument("--base-training-config", type=Path, required=True)
    parser.add_argument("--baseline-checkpoint", type=Path, required=True)
    parser.add_argument("--holdout-trials", type=int, default=100)
    parser.add_argument("--holdout-seed", type=int, default=20260728)
    parser.add_argument("--training-steps", type=int, default=2800)
    parser.add_argument("--batch-size", type=int, default=8)
    parser.add_argument("--num-workers", type=int, default=4)
    parser.add_argument("--policy-hz", type=int, default=3)
    parser.add_argument("--evaluation-workers", type=int, default=4)
    parser.add_argument(
        "--active-checkpoint-registry",
        type=Path,
        default=PROJECT_ROOT / "configs" / "active_mobile_smolvla.json",
        help="atomically updated only after the frozen promotion gate passes",
    )
    parser.add_argument(
        "--primitive-learning",
        action="store_true",
        help="relabel demonstrations as primitives and train a progress-channel SmolVLA",
    )
    parser.add_argument(
        "--harness-agent-cycle",
        type=Path,
        help=(
            "optional verified Harness Agent cycle; when supplied, independently "
            "admitted corrections become an additional mandatory promotion gate"
        ),
    )
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--stop-after", choices=tuple(dict.fromkeys((*BASE_STEP_ORDER, *PRIMITIVE_STEP_ORDER))))
    args = parser.parse_args()
    if args.training_steps < 1 or min(
        args.batch_size, args.policy_hz, args.evaluation_workers
    ) < 1:
        parser.error(
            "training steps, batch size, policy Hz, and evaluation workers must be positive"
        )
    if args.num_workers < 0:
        parser.error("num-workers cannot be negative")

    root = PROJECT_ROOT
    cycle_dir = args.cycle_dir.resolve()
    state_path = cycle_dir / "cycle-state.json"
    if cycle_dir.exists() and any(cycle_dir.iterdir()) and not args.resume:
        parser.error(f"cycle directory must be new or --resume must be used: {cycle_dir}")
    cycle_dir.mkdir(parents=True, exist_ok=True)

    source_audit = _read_json(args.source_campaign_audit)
    base_training = _read_json(args.base_training_config)
    harness_agent_cycle = (
        _load_harness_agent_cycle(
            args.harness_agent_cycle,
            source_audit_sha256=sha256_file(args.source_campaign_audit),
        )
        if args.harness_agent_cycle is not None
        else None
    )
    replay = build_replay_from_campaign_audit(source_audit)
    curriculum = build_curriculum_config(base_training, replay, cycle_id=args.cycle_id)
    holdout = build_frozen_holdout_config(
        cycle_id=args.cycle_id, trials=args.holdout_trials, seed=args.holdout_seed
    )
    isolation = validate_split_isolation(curriculum, holdout)
    replay_path = cycle_dir / "failure-replay.json"
    curriculum_path = cycle_dir / "curriculum-config.json"
    holdout_path = cycle_dir / "frozen-holdout.json"
    isolation_path = cycle_dir / "split-isolation-audit.json"
    for path, payload in (
        (replay_path, replay),
        (curriculum_path, curriculum),
        (holdout_path, holdout),
        (isolation_path, isolation),
    ):
        _freeze_prepared_artifact(path, payload, resume=args.resume)

    training_dir = cycle_dir / "curriculum-collection"
    primitive_dataset = cycle_dir / "primitive-training-dataset"
    candidate_dataset = primitive_dataset if args.primitive_learning else training_dir / "lerobot_dataset"
    candidate_dir = cycle_dir / "candidate-training"
    candidate_checkpoint = (
        candidate_dir / "checkpoints" / f"{args.training_steps:06d}" / "pretrained_model"
    )
    baseline_rollouts = cycle_dir / "baseline-holdout"
    candidate_rollouts = cycle_dir / "candidate-holdout"
    commands = {
        "preflight": ["bash", str(root / "scripts/preflight_radeon.sh")],
        "collect_curriculum": [
            sys.executable,
            str(root / "scripts/collect_mobile_suction_dataset_rocm.py"),
            "--config", str(curriculum_path), "--output", str(training_dir),
            "--backend", "rocm", "--resume",
        ],
        "audit_curriculum": [
            sys.executable,
            str(root / "scripts/audit_mobile_dataset.py"),
            "--dataset-root", str(training_dir / "lerobot_dataset"),
            "--output", str(cycle_dir / "curriculum-dataset-audit.json"),
            "--min-episodes", str(len(curriculum["episodes"])),
        ],
        "build_primitive_dataset": [
            sys.executable,
            str(root / "scripts/build_mobile_primitive_dataset.py"),
            "--source", str(training_dir / "lerobot_dataset"),
            "--output", str(primitive_dataset),
        ],
        "audit_primitive_dataset": [
            sys.executable,
            str(root / "scripts/audit_mobile_dataset.py"),
            "--dataset-root", str(primitive_dataset),
            "--output", str(cycle_dir / "primitive-dataset-audit.json"),
            "--min-episodes", str(len(curriculum["episodes"])),
        ],
        "train_candidate": [
            "bash", str(root / "scripts/train_mobile_smolvla_rocm.sh"),
            str(candidate_dataset), str(candidate_dir),
        ],
        "offline_ablation": [
            sys.executable,
            str(root / "scripts/smoke_mobile_smolvla_inference_rocm.py"),
            "--checkpoint", str(candidate_checkpoint),
            "--dataset-root", str(candidate_dataset),
            "--output", str(cycle_dir / "candidate-offline-ablation.json"),
        ],
        "evaluate_baseline": _campaign_command(
            root,
            holdout_path,
            baseline_rollouts,
            args.baseline_checkpoint.resolve(),
            args.policy_hz,
            args.evaluation_workers,
        ),
        "summarize_baseline": _summary_command(
            root, baseline_rollouts, cycle_dir / "baseline-holdout-audit.json"
        ),
        "evaluate_candidate": _campaign_command(
            root,
            holdout_path,
            candidate_rollouts,
            candidate_checkpoint,
            args.policy_hz,
            args.evaluation_workers,
        ),
        "summarize_candidate": _summary_command(
            root, candidate_rollouts, cycle_dir / "candidate-holdout-audit.json"
        ),
    }
    step_order = PRIMITIVE_STEP_ORDER if args.primitive_learning else BASE_STEP_ORDER
    commands = {step: commands[step] for step in step_order if step != "promotion_gate"}
    state = _load_state(
        state_path,
        args,
        replay_path,
        curriculum_path,
        holdout_path,
        commands,
    )
    if args.dry_run:
        state["status"] = "dry_run"
        write_json(state_path, state)
        print(json.dumps(state, indent=2))
        return 0

    env = os.environ.copy()
    env.update(
        {
            "HIP_VISIBLE_DEVICES": env.get("HIP_VISIBLE_DEVICES", "0"),
            "MOBILE_SMOLVLA_STEPS": str(args.training_steps),
            "MOBILE_SMOLVLA_BATCH_SIZE": str(args.batch_size),
            "MOBILE_SMOLVLA_NUM_WORKERS": str(args.num_workers),
            "PARCEL_SORTER_VENV": sys.prefix,
        }
    )
    env["MOBILE_SMOLVLA_PROGRESS_CHANNEL"] = "1" if args.primitive_learning else "0"
    env["PATH"] = f"{Path(sys.prefix) / 'bin'}{os.pathsep}{env.get('PATH', '')}"
    env["PYTHONPATH"] = (
        f"{root / 'src'}{os.pathsep}{env['PYTHONPATH']}"
        if env.get("PYTHONPATH")
        else str(root / "src")
    )
    for step in step_order:
        if step == "promotion_gate":
            _run_promotion_gate(
                root,
                cycle_dir,
                args.baseline_checkpoint.resolve(),
                candidate_checkpoint,
                args.active_checkpoint_registry.resolve(),
                harness_agent_cycle,
                state,
                state_path,
            )
        elif state["steps"].get(step, {}).get("status") == "passed":
            continue
        else:
            _run_command(step, commands[step], cycle_dir, state, state_path, env)
        if args.stop_after == step:
            state["status"] = "stopped_after_requested_step"
            write_json(state_path, state)
            return 0
    state["status"] = (
        "completed_promoted"
        if state["steps"]["promotion_gate"]["status"] == "passed"
        else "completed_not_promoted"
    )
    write_json(state_path, state)
    return 0


def _campaign_command(
    root: Path,
    holdout: Path,
    output: Path,
    checkpoint: Path,
    policy_hz: int,
    workers: int,
) -> list[str]:
    return [
        sys.executable,
        str(root / "scripts/collect_mobile_suction_dataset_rocm.py"),
        "--config", str(holdout), "--output", str(output), "--backend", "rocm",
        "--resume", "--audit-only", "--smolvla-checkpoint", str(checkpoint),
        "--policy-mode", "base_residual", "--policy-hz", str(policy_hz),
        "--workers", str(workers),
    ]


def _summary_command(root: Path, rollouts: Path, output: Path) -> list[str]:
    return [
        sys.executable,
        str(root / "scripts/summarize_mobile_vla_campaign.py"),
        "--collection-summary", str(rollouts / "collection-summary.json"),
        "--output", str(output),
    ]


def _load_state(
    path: Path,
    args: argparse.Namespace,
    replay: Path,
    curriculum: Path,
    holdout: Path,
    commands: dict[str, list[str]],
) -> dict[str, Any]:
    if args.resume and path.is_file():
        state = _read_json(path)
        if state.get("inputs", {}).get("holdout_sha256") != sha256_file(holdout):
            raise RuntimeError("resume rejected: frozen holdout hash changed")
        if bool(state.get("settings", {}).get("primitive_learning")) != bool(
            args.primitive_learning
        ):
            raise RuntimeError("resume rejected: primitive-learning mode changed")
        registered_registry = state.get("inputs", {}).get("active_checkpoint_registry")
        requested_registry = str(args.active_checkpoint_registry.resolve())
        if registered_registry not in (None, requested_registry):
            raise RuntimeError("resume rejected: active-checkpoint registry changed")
        state.setdefault("inputs", {})["active_checkpoint_registry"] = requested_registry
        registered_agent_sha = state.get("inputs", {}).get("harness_agent_cycle_sha256")
        requested_agent_sha = (
            sha256_file(args.harness_agent_cycle)
            if args.harness_agent_cycle is not None
            else None
        )
        if registered_agent_sha != requested_agent_sha:
            raise RuntimeError("resume rejected: Harness Agent cycle changed")
        state["commands"] = commands
        state.setdefault("settings", {})["evaluation_workers"] = args.evaluation_workers
        return state
    return {
        "schema_version": 1,
        "protocol": (
            "mobile-smolvla-primitive-self-improvement-cycle-v2"
            if args.primitive_learning
            else "mobile-smolvla-self-improvement-cycle-v1"
        ),
        "cycle_id": args.cycle_id,
        "status": "prepared",
        "inputs": {
            "source_campaign_audit": str(args.source_campaign_audit.resolve()),
            "source_campaign_audit_sha256": sha256_file(args.source_campaign_audit),
            "base_training_config": str(args.base_training_config.resolve()),
            "base_training_config_sha256": sha256_file(args.base_training_config),
            "baseline_checkpoint": str(args.baseline_checkpoint.resolve()),
            "active_checkpoint_registry": str(args.active_checkpoint_registry.resolve()),
            "harness_agent_cycle": (
                str(args.harness_agent_cycle.resolve())
                if args.harness_agent_cycle is not None
                else None
            ),
            "harness_agent_cycle_sha256": (
                sha256_file(args.harness_agent_cycle)
                if args.harness_agent_cycle is not None
                else None
            ),
            "replay_sha256": sha256_file(replay),
            "curriculum_sha256": sha256_file(curriculum),
            "holdout_sha256": sha256_file(holdout),
        },
        "settings": {
            "holdout_trials": args.holdout_trials,
            "holdout_seed": args.holdout_seed,
            "training_steps": args.training_steps,
            "batch_size": args.batch_size,
            "num_workers": args.num_workers,
            "policy_hz": args.policy_hz,
            "evaluation_workers": args.evaluation_workers,
            "primitive_learning": bool(args.primitive_learning),
        },
        "commands": commands,
        "steps": {},
        "claim_boundary": (
            "nearline primitive improvement between episodes; no active rollout mutates "
            "model weights and promotion may reject a regressing candidate"
        ),
    }


def _run_command(
    name: str,
    command: list[str],
    cycle_dir: Path,
    state: dict[str, Any],
    state_path: Path,
    env: dict[str, str],
) -> None:
    log_path = cycle_dir / "logs" / f"{name}.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    state["status"] = "running"
    state["steps"][name] = {"status": "running", "log": str(log_path), "command": command}
    write_json(state_path, state)
    with log_path.open("w", encoding="utf-8") as log:
        completed = subprocess.run(command, stdout=log, stderr=subprocess.STDOUT, env=env)
    state["steps"][name]["return_code"] = completed.returncode
    state["steps"][name]["status"] = "passed" if completed.returncode == 0 else "failed"
    write_json(state_path, state)
    if completed.returncode != 0:
        raise RuntimeError(f"cycle step failed: {name}; inspect {log_path}")


def _run_promotion_gate(
    root: Path,
    cycle_dir: Path,
    baseline_checkpoint: Path,
    checkpoint: Path,
    active_registry: Path,
    harness_agent_cycle: dict[str, Any] | None,
    state: dict[str, Any],
    state_path: Path,
) -> None:
    baseline_audit = cycle_dir / "baseline-holdout-audit.json"
    candidate_audit = cycle_dir / "candidate-holdout-audit.json"
    baseline = _read_json(baseline_audit)
    candidate = _read_json(candidate_audit)
    result = promotion_gate(baseline, candidate)
    pairing = validate_paired_campaigns(baseline, candidate)
    candidate_artifact = checkpoint / "model.safetensors"
    baseline_artifact = baseline_checkpoint / "model.safetensors"
    if not candidate_artifact.is_file():
        raise FileNotFoundError(f"candidate model artifact is missing: {candidate_artifact}")
    pairing.update(
        {
            "baseline_audit": str(baseline_audit),
            "baseline_audit_sha256": sha256_file(baseline_audit),
            "candidate_audit": str(candidate_audit),
            "candidate_audit_sha256": sha256_file(candidate_audit),
            "baseline_checkpoint_sha256": (
                sha256_file(baseline_artifact) if baseline_artifact.is_file() else None
            ),
            "candidate_checkpoint_sha256": sha256_file(candidate_artifact),
        }
    )
    result["pairing"] = pairing
    result["candidate_checkpoint"] = str(checkpoint)
    if harness_agent_cycle is not None:
        admissions = [
            record.get("admission")
            for record in harness_agent_cycle.get("records", ())
            if isinstance(record, dict) and isinstance(record.get("admission"), dict)
        ]
        authorization = authorize_agent_checkpoint_promotion(
            result,
            admissions,
            candidate_checkpoint_sha256=pairing["candidate_checkpoint_sha256"],
        )
        result["harness_agent_authorization"] = authorization
        result["promoted"] = bool(result["promoted"] and authorization["authorized"])
    result_path = cycle_dir / "promotion-gate.json"
    write_json(result_path, result)
    if result["promoted"]:
        active = activate_promoted_checkpoint(
            active_registry,
            project_root=root,
            checkpoint=checkpoint,
            promotion_evidence=result_path,
        )
        write_json(
            cycle_dir / "promoted-checkpoint.json",
            {
                "checkpoint": str(checkpoint),
                "promotion_gate": str(result_path),
                "promotion_gate_sha256": sha256_file(result_path),
                "active_checkpoint_registry": str(active_registry),
                "active_checkpoint": active.to_dict(),
            },
        )
    state["steps"]["promotion_gate"] = {
        "status": "passed" if result["promoted"] else "rejected",
        "result": str(result_path),
        "active_checkpoint_registry": (
            str(active_registry) if result["promoted"] else None
        ),
    }
    write_json(state_path, state)


def _freeze_prepared_artifact(
    path: Path, payload: dict[str, Any], *, resume: bool
) -> None:
    if resume and path.is_file():
        if _read_json(path) != payload:
            raise RuntimeError(f"resume rejected: prepared artifact changed: {path}")
        return
    write_json(path, payload)


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _load_harness_agent_cycle(
    path: Path, *, source_audit_sha256: str
) -> dict[str, Any]:
    payload = _read_json(path)
    if payload.get("protocol") != "parcel-harness-agent-cycle-v1":
        raise ValueError("unsupported Harness Agent cycle protocol")
    if payload.get("source_campaign_audit_sha256") != source_audit_sha256:
        raise ValueError("Harness Agent cycle references a different source campaign")
    registered_sha = str(payload.get("cycle_sha256") or "")
    unsigned = dict(payload)
    unsigned.pop("cycle_sha256", None)
    if registered_sha != sha256_json(unsigned):
        raise ValueError("Harness Agent cycle hash mismatch")
    config_path = Path(str(payload.get("config") or ""))
    if not config_path.is_file() or payload.get("config_sha256") != sha256_file(config_path):
        raise ValueError("Harness Agent config is missing or its hash changed")
    config = HarnessAgentConfig.from_dict(_read_json(config_path))
    records = payload.get("records")
    if not isinstance(records, list):
        raise ValueError("Harness Agent cycle records must be a list")
    for record in records:
        if not isinstance(record, dict):
            raise ValueError("Harness Agent cycle records must be objects")
        packet = record.get("failure_packet")
        analysis = record.get("analysis")
        candidate = record.get("candidate")
        if not all(isinstance(value, dict) for value in (packet, analysis, candidate)):
            raise ValueError("Harness Agent record is missing proposal evidence")
        expected_candidate = quarantine_correction(
            packet, analysis, analyst=config.failure_analyst
        )
        if candidate != expected_candidate:
            raise ValueError("Harness Agent correction candidate was modified")
        replay = record.get("replay_audit")
        verification = record.get("verification")
        admission = record.get("admission")
        if replay is None:
            if verification is not None or admission is not None:
                raise ValueError("unreplayed Agent correction has verification evidence")
            continue
        if not isinstance(replay, dict):
            raise ValueError("Harness Agent replay audit must be an object")
        expected_verification = verify_replayed_correction(
            candidate,
            replay,
            verifier=config.independent_verifier,
            config=config,
        )
        if verification != expected_verification:
            raise ValueError("Harness Agent replay verification was modified")
        expected_admission = training_admission_gate(candidate, verification)
        if admission != expected_admission:
            raise ValueError("Harness Agent training admission was modified")
    return payload


if __name__ == "__main__":
    raise SystemExit(main())
