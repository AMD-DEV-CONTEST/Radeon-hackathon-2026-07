#!/usr/bin/env python3
"""Run up to three attributed PI0.5 residual recovery attempts."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import subprocess
import sys
from typing import Any

from parcel_sorter.mobile_adaptive_retry import classify_mobile_failure


PROTOCOL = "pi05-autonomous-recovery-v2"
FAILURE_OBSERVATIONS = {
    "scene_stability_failure": "The previous scene did not settle before manipulation.",
    "contact_failure": "The previous attempt did not establish physical parcel contact.",
    "suction_latch_failure": "The previous contact did not form a stable suction seal.",
    "lift_support_failure": "The previous attempt lost support during lift.",
    "transport_failure": "The previous attempt lost stable support during transport.",
    "placement_failure": "The previous attempt did not reach a valid placement pose.",
    "release_failure": "The previous attempt did not complete a verified release.",
    "scene_stability": "The previous scene did not settle before manipulation.",
    "suction_latch": "The previous attempt did not form a stable suction seal.",
    "lift_success": "The previous attempt lost support during lift.",
    "transport_success": "The previous attempt lost stable support during transport.",
    "placement_success": "The previous attempt did not reach a valid placement pose.",
    "release_success": "The previous attempt did not complete a verified release.",
    "force_safety_abort": "The previous attempt was stopped by the contact-force limit.",
    "unclassified": "The previous attempt did not complete the parcel task.",
}


def recovery_task_text(base_task: str, previous_failure: str | None) -> str:
    """Expose the audited outcome without prescribing mode or motion labels."""

    task = base_task.strip()
    if not task:
        raise ValueError("base task must be non-empty")
    if previous_failure is None:
        return task
    observation = FAILURE_OBSERVATIONS.get(
        previous_failure, FAILURE_OBSERVATIONS["unclassified"]
    )
    return (
        f"{task} {observation} Re-observe RGB-D, suction state, and force history; "
        "choose a safer grasp family and contact residual, then complete the same task."
    )


def build_attempt_command(
    *,
    evaluator: Path,
    checkpoint: Path,
    attempt_output: Path,
    replay_root: Path,
    backend: str,
    policy_hz: int,
    chunk_execution_protocol: str,
    chunk_execution_steps: int,
    retry_index: int,
    parcel_profile: str,
    parcel_shape: str,
    parcel_orientation: str,
    parcel_yaw_rad: float,
    expected_grasp_mode: str,
    minimum_sealed_cups: int,
    parcel_size_m: tuple[float, float, float],
    parcel_mass_kg: float,
    parcel_friction: float,
    parcel_offset_m: tuple[float, float],
    task_text: str,
    force_memory_harness: bool,
    depth_risk_sidecar: bool,
) -> list[str]:
    command = [
        sys.executable,
        str(evaluator),
        "--backend",
        backend,
        "--output",
        str(attempt_output),
        "--record-pi05-residual-dataset",
        str(replay_root),
        "--vla-checkpoint",
        str(checkpoint),
        "--policy-mode",
        "pi05_residual",
        "--policy-hz",
        str(policy_hz),
        "--pi05-chunk-execution-protocol",
        chunk_execution_protocol,
        "--pi05-chunk-execution-steps",
        str(chunk_execution_steps),
        "--vla-routes-grasp-mode",
        "--require-vla-goal-verdict",
        "--retry-index",
        str(retry_index),
        "--parcel-profile",
        parcel_profile,
        "--parcel-shape",
        parcel_shape,
        "--parcel-orientation",
        parcel_orientation,
        "--parcel-yaw-rad",
        _float(parcel_yaw_rad),
        "--grasp-mode",
        expected_grasp_mode,
        "--minimum-sealed-cups",
        str(minimum_sealed_cups),
        "--parcel-size-m",
        *(_float(value) for value in parcel_size_m),
        "--parcel-mass-kg",
        _float(parcel_mass_kg),
        "--parcel-friction",
        _float(parcel_friction),
        "--parcel-offset-m",
        *(_float(value) for value in parcel_offset_m),
        "--task-text",
        task_text,
    ]
    if force_memory_harness:
        command.append("--force-memory-harness")
    if depth_risk_sidecar:
        command.append("--depth-risk-sidecar")
    if any(part.startswith("--recovery-") for part in command):
        raise RuntimeError("autonomous PI0.5 recovery cannot inject expert recovery parameters")
    return command


def summarize_attempts(
    attempts: list[dict[str, Any]],
    *,
    checkpoint: Path,
    maximum_attempts: int,
) -> dict[str, Any]:
    if not attempts:
        raise ValueError("autonomous recovery requires at least one attempt")
    valid = [item for item in attempts if item.get("summary_available")]
    qualified = [item for item in valid if item.get("vla_qualified_success")]
    pure_qualified = [
        item for item in qualified if item.get("accepted_as_pure_vla_experience")
    ]
    first_qualified_index = next(
        (
            int(item["attempt_index"])
            for item in valid
            if item.get("vla_qualified_success")
        ),
        None,
    )
    return {
        "schema_version": 1,
        "protocol": PROTOCOL,
        "checkpoint": str(checkpoint.resolve()),
        "maximum_attempts": maximum_attempts,
        "attempts_run": len(attempts),
        "attempts_with_summary": len(valid),
        "first_attempt_success": bool(
            valid and valid[0].get("vla_qualified_success")
        ),
        "eventual_success": bool(qualified),
        "pure_vla_eventual_success": bool(pure_qualified),
        "attempts_to_success": (
            first_qualified_index + 1 if first_qualified_index is not None else None
        ),
        "vla_qualified_run_count": len(qualified),
        "pure_vla_qualified_run_count": len(pure_qualified),
        "policy_authority_counts": {
            authority: sum(item.get("policy_authority") == authority for item in valid)
            for authority in sorted(
                {str(item.get("policy_authority") or "unknown") for item in valid}
            )
        },
        "expert_fallback_count": sum(
            int(item.get("expert_fallback_count") or 0) for item in valid
        ),
        "emergency_stop_count": sum(
            int(item.get("emergency_stop_count") or 0) for item in valid
        ),
        "force_violation_count": sum(
            int(item.get("force_violation_count") or 0) for item in valid
        ),
        "successful_replay_roots": [
            item["replay_root"] for item in qualified
        ],
        "attempts": attempts,
        "external_recovery_action_parameters": False,
        "expert_policy_fallback_allowed": False,
        "claim_boundary": (
            "eventual success is an attributed PI0.5 residual cross-rollout retry result; "
            "hybrid expert-reference execution is not labeled pure VLA. Each attempt "
            "restarts the same physical initial condition and receives only the prior "
            "audited failure class, not an expert mode, contact offset, or action label"
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--checkpoint", type=Path, required=True)
    parser.add_argument("--backend", choices=("rocm", "cuda"), default="rocm")
    parser.add_argument("--max-attempts", type=int, default=3)
    parser.add_argument("--policy-hz", type=int, default=3)
    parser.add_argument(
        "--pi05-chunk-execution-protocol",
        choices=(
            "first-action-hold-v1",
            "pi05-window-aggregate-v1",
            "pi05-open-loop-queue-v1",
        ),
        default="first-action-hold-v1",
    )
    parser.add_argument("--pi05-chunk-execution-steps", type=int, default=1)
    parser.add_argument("--parcel-profile", default="small_carton")
    parser.add_argument("--parcel-shape", choices=("box", "cylinder"), default="box")
    parser.add_argument(
        "--parcel-orientation",
        choices=("yaw", "upright", "horizontal"),
        default="yaw",
    )
    parser.add_argument("--parcel-yaw-rad", type=float, default=0.0)
    parser.add_argument(
        "--expected-grasp-mode",
        choices=("top_suction", "side_suction", "cooperative_cradle"),
        default="top_suction",
        help="hidden evaluation label; it is not exposed as a conditioned policy input",
    )
    parser.add_argument("--minimum-sealed-cups", type=int, default=2)
    parser.add_argument(
        "--parcel-size-m", type=float, nargs=3, default=(0.20, 0.12, 0.20)
    )
    parser.add_argument("--parcel-mass-kg", type=float, default=0.40)
    parser.add_argument("--parcel-friction", type=float, default=0.80)
    parser.add_argument("--parcel-offset-m", type=float, nargs=2, default=(0.0, 0.0))
    parser.add_argument("--task-text")
    parser.add_argument("--force-memory-harness", action="store_true")
    parser.add_argument("--depth-risk-sidecar", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    if not 1 <= args.max_attempts <= 3:
        parser.error("max-attempts must be in [1, 3]")
    if args.output.exists() and any(args.output.iterdir()):
        parser.error("output directory must be absent or empty")
    if not args.dry_run and not args.checkpoint.exists():
        parser.error("PI0.5 checkpoint does not exist")
    if args.policy_hz <= 0 or 30 % args.policy_hz != 0:
        parser.error("policy-hz must be a positive divisor of 30")
    if not 1 <= args.pi05_chunk_execution_steps <= 30:
        parser.error("chunk execution steps must be in [1, 30]")
    if (
        args.pi05_chunk_execution_protocol == "first-action-hold-v1"
        and args.pi05_chunk_execution_steps != 1
    ):
        parser.error("first-action hold requires one execution step")
    if (args.parcel_shape == "box") != (args.parcel_orientation == "yaw"):
        parser.error("parcel shape and orientation are inconsistent")

    base_task = args.task_text or (
        f"Pick up the {args.parcel_profile} parcel and place it at the matching "
        "sorting destination."
    )
    evaluator = Path(__file__).resolve().parent / "evaluate_mobile_suction_lift_rocm.py"
    attempts: list[dict[str, Any]] = []
    previous_failure: str | None = None
    args.output.mkdir(parents=True, exist_ok=True)

    for retry_index in range(args.max_attempts):
        attempt_root = args.output / f"attempt-{retry_index + 1:02d}"
        run_root = attempt_root / "run"
        replay_root = attempt_root / "pi05-replay"
        task_text = recovery_task_text(base_task, previous_failure)
        command = build_attempt_command(
            evaluator=evaluator,
            checkpoint=args.checkpoint,
            attempt_output=run_root,
            replay_root=replay_root,
            backend=args.backend,
            policy_hz=args.policy_hz,
            chunk_execution_protocol=args.pi05_chunk_execution_protocol,
            chunk_execution_steps=args.pi05_chunk_execution_steps,
            retry_index=retry_index,
            parcel_profile=args.parcel_profile,
            parcel_shape=args.parcel_shape,
            parcel_orientation=args.parcel_orientation,
            parcel_yaw_rad=args.parcel_yaw_rad,
            expected_grasp_mode=args.expected_grasp_mode,
            minimum_sealed_cups=args.minimum_sealed_cups,
            parcel_size_m=tuple(args.parcel_size_m),
            parcel_mass_kg=args.parcel_mass_kg,
            parcel_friction=args.parcel_friction,
            parcel_offset_m=tuple(args.parcel_offset_m),
            task_text=task_text,
            force_memory_harness=args.force_memory_harness,
            depth_risk_sidecar=args.depth_risk_sidecar,
        )
        record: dict[str, Any] = {
            "attempt_index": retry_index,
            "retry_index": retry_index,
            "previous_failure_observation": previous_failure,
            "task_text": task_text,
            "command": command,
            "summary_available": False,
            "physical_success": False,
            "vla_qualified_success": False,
            "failure_stage": "dry_run" if args.dry_run else "infrastructure_failure",
            "replay_root": str(replay_root.resolve()),
        }
        if args.dry_run:
            attempts.append(record)
            previous_failure = "unclassified"
            continue

        attempt_root.mkdir(parents=True, exist_ok=True)
        completed = subprocess.run(command, check=False, capture_output=True, text=True)
        (attempt_root / "runner.stdout.log").write_text(
            completed.stdout, encoding="utf-8"
        )
        (attempt_root / "runner.stderr.log").write_text(
            completed.stderr, encoding="utf-8"
        )
        record["return_code"] = completed.returncode
        summary_path = run_root / "summary.json"
        if summary_path.is_file():
            summary = json.loads(summary_path.read_text(encoding="utf-8"))
            policy = summary.get("policy") or {}
            replay = summary.get("pi05_residual_dataset") or {}
            qualification = replay.get("qualification") or {}
            physical_success = bool(summary.get("success"))
            classified_failure = classify_mobile_failure(summary)
            accepted = bool(replay.get("accepted_for_behavior_cloning"))
            vla_qualified = bool(physical_success and accepted)
            previous_failure = (
                None
                if vla_qualified
                else classified_failure or "unclassified"
            )
            record.update(
                {
                    "summary_available": True,
                    "summary": str(summary_path.resolve()),
                    "physical_success": physical_success,
                    "vla_qualified_success": vla_qualified,
                    "failure_stage": None if vla_qualified else previous_failure,
                    "selected_grasp_mode": policy.get("selected_grasp_mode"),
                    "goal_arrival_verified": policy.get("goal_arrival_verified"),
                    "expert_fallback_count": int(
                        qualification.get("expert_fallback_count") or 0
                    ),
                    "emergency_stop_count": int(
                        qualification.get("emergency_stop_count") or 0
                    ),
                    "force_violation_count": int(
                        qualification.get("force_violation_count") or 0
                    ),
                    "policy_authority": qualification.get(
                        "policy_authority", "unknown"
                    ),
                    "expert_reference_used": bool(
                        qualification.get("expert_reference_used")
                    ),
                    "accepted_as_pure_vla_experience": bool(
                        replay.get("accepted_as_pure_vla_experience")
                    ),
                    "replay_accepted": accepted,
                    "replay_rejection_reasons": qualification.get(
                        "rejection_reasons", []
                    ),
                }
            )
        attempts.append(record)
        _write_json(
            args.output / "autonomous-recovery-summary.partial.json",
            summarize_attempts(
                attempts,
                checkpoint=args.checkpoint,
                maximum_attempts=args.max_attempts,
            ),
        )
        if record["vla_qualified_success"]:
            break

    result = summarize_attempts(
        attempts,
        checkpoint=args.checkpoint,
        maximum_attempts=args.max_attempts,
    )
    result["physical_parameters"] = {
        "profile": args.parcel_profile,
        "shape": args.parcel_shape,
        "orientation": args.parcel_orientation,
        "yaw_rad": args.parcel_yaw_rad,
        "size_m": list(args.parcel_size_m),
        "mass_kg": args.parcel_mass_kg,
        "friction": args.parcel_friction,
        "offset_m": list(args.parcel_offset_m),
        "hidden_expected_grasp_mode": args.expected_grasp_mode,
    }
    _write_json(args.output / "autonomous-recovery-summary.json", result)
    print(json.dumps(result, indent=2))
    return 0 if result["eventual_success"] or args.dry_run else 2


def _float(value: float) -> str:
    rendered = f"{float(value):.10f}".rstrip("0").rstrip(".")
    return "0" if rendered in {"", "-0"} else rendered


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.parent / f".{path.name}.tmp"
    temporary.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    temporary.replace(path)


if __name__ == "__main__":
    raise SystemExit(main())
