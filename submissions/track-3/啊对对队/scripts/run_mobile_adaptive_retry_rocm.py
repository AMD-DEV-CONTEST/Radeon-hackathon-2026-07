"""Run up to three audited mobile attempts with persisted PASH strategy memory."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import subprocess
import sys
from typing import Any

from parcel_sorter.checkpoint_registry import load_active_checkpoint
from parcel_sorter.mobile_adaptive_retry import (
    EpisodicStrategyMemory,
    build_primitive_acquisition_manifest,
    choose_recovery_plan,
    classify_mobile_failure,
    strategy_context,
    summarize_adaptive_attempts,
)


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.parent / f".{path.name}.tmp"
    temporary.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    temporary.replace(path)


def _float(value: float) -> str:
    return format(value, ".10f").rstrip("0").rstrip(".") or "0"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--strategy-memory", type=Path)
    parser.add_argument("--smolvla-checkpoint", type=Path, required=True)
    parser.add_argument("--backend", choices=("rocm", "cuda"), default="rocm")
    parser.add_argument("--max-attempts", type=int, default=3)
    parser.add_argument("--policy-hz", type=int, default=3)
    parser.add_argument("--parcel-profile", default="small_carton")
    parser.add_argument("--parcel-size-m", type=float, nargs=3, default=(0.20, 0.12, 0.20))
    parser.add_argument("--parcel-mass-kg", type=float, default=0.40)
    parser.add_argument("--parcel-friction", type=float, default=0.80)
    parser.add_argument("--parcel-offset-m", type=float, nargs=2, default=(0.0, 0.0))
    parser.add_argument("--task-text")
    parser.add_argument("--cooperative-cradle", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    if not 1 <= args.max_attempts <= 3:
        parser.error("max-attempts must be in [1, 3]")
    if args.output.exists() and any(args.output.iterdir()):
        parser.error("output directory must be absent or empty")
    checkpoint_selection: dict[str, Any] = {
        "source": "direct_path",
        "checkpoint": str(args.smolvla_checkpoint),
    }
    if args.smolvla_checkpoint.is_file():
        try:
            selected = load_active_checkpoint(args.smolvla_checkpoint)
        except (FileNotFoundError, ValueError, json.JSONDecodeError) as exc:
            parser.error(f"active checkpoint verification failed: {exc}")
        args.smolvla_checkpoint = selected.checkpoint
        checkpoint_selection = {"source": "promoted_registry", **selected.to_dict()}
    if not args.smolvla_checkpoint.exists() and not args.dry_run:
        parser.error("SmolVLA checkpoint does not exist")

    memory_path = args.strategy_memory or args.output / "strategy-memory.json"
    memory = EpisodicStrategyMemory.load(memory_path)
    evaluator = Path(__file__).resolve().parent / "evaluate_mobile_suction_lift_rocm.py"
    attempted_plan_keys: list[str] = []
    attempt_records: list[dict[str, Any]] = []
    previous_failure: str | None = None

    for attempt_index in range(args.max_attempts):
        context = strategy_context(
            profile=args.parcel_profile,
            mass_kg=args.parcel_mass_kg,
            previous_failure=previous_failure,
        )
        recovery_plan = choose_recovery_plan(
            memory=memory,
            context=context,
            previous_failure=previous_failure,
            attempted_plan_keys=attempted_plan_keys,
            cooperative_cradle=args.cooperative_cradle,
        )
        strategy = recovery_plan.strategy
        recipe = recovery_plan.recipe
        attempted_plan_keys.append(recovery_plan.key)
        attempt_dir = args.output / f"attempt-{attempt_index + 1:02d}-{strategy.name}"
        recovery_dataset = attempt_dir / "recovery-dataset"
        command = [
            sys.executable,
            str(evaluator),
            "--backend",
            args.backend,
            "--output",
            str(attempt_dir),
            "--parcel-profile",
            args.parcel_profile,
            "--parcel-size-m",
            *(_float(value) for value in args.parcel_size_m),
            "--parcel-mass-kg",
            _float(args.parcel_mass_kg),
            "--parcel-friction",
            _float(args.parcel_friction),
            "--parcel-offset-m",
            *(_float(value) for value in args.parcel_offset_m),
            "--smolvla-checkpoint",
            str(args.smolvla_checkpoint),
            "--policy-mode",
            strategy.policy_mode,
            "--policy-hz",
            str(args.policy_hz),
            "--record-dataset",
            str(recovery_dataset),
            "--recovery-contact-offset-m",
            *(_float(value) for value in recipe.contact_offset_m),
            "--recovery-contact-penetration-delta-m",
            _float(recipe.contact_penetration_delta_m),
            "--recovery-approach-speed-scale",
            _float(recipe.approach_speed_scale),
            "--recovery-vertical-speed-scale",
            _float(recipe.vertical_speed_scale),
            "--recovery-lift-height-delta-m",
            _float(recipe.lift_height_delta_m),
            "--recovery-placement-clearance-m",
            _float(recipe.placement_clearance_m),
        ]
        if strategy.force_memory:
            command.append("--force-memory-harness")
        if strategy.depth_sidecar:
            command.append("--depth-risk-sidecar")
        if args.cooperative_cradle:
            command.append("--cooperative-cradle")
        if args.task_text:
            command.extend(("--task-text", args.task_text))

        record: dict[str, Any] = {
            "attempt_index": attempt_index,
            "context": context,
            "strategy": strategy.to_dict(),
            "recovery_plan": recovery_plan.to_dict(),
            "command": command,
            "summary_available": False,
            "success": False,
            "failure_stage": "dry_run" if args.dry_run else "infrastructure_failure",
        }
        if args.dry_run:
            attempt_records.append(record)
            previous_failure = "unclassified"
            continue

        completed = subprocess.run(command, check=False, capture_output=True, text=True)
        attempt_dir.mkdir(parents=True, exist_ok=True)
        (attempt_dir / "runner.stdout.log").write_text(completed.stdout, encoding="utf-8")
        (attempt_dir / "runner.stderr.log").write_text(completed.stderr, encoding="utf-8")
        record["return_code"] = completed.returncode
        summary_path = attempt_dir / "summary.json"
        if summary_path.exists():
            summary = json.loads(summary_path.read_text(encoding="utf-8"))
            previous_failure = classify_mobile_failure(summary)
            record.update(
                {
                    "summary_available": True,
                    "summary": str(summary_path),
                    "success": bool(summary.get("success")),
                    "failure_stage": previous_failure,
                    "placement_error_m": summary.get("placement_error_m"),
                    "policy": {
                        key: (summary.get("policy") or {}).get(key)
                        for key in (
                            "mode",
                            "force_memory_enabled",
                            "force_memory_tighten_count",
                            "force_memory_full_fallback_count",
                            "mean_force_memory_scale_cap",
                            "depth_sidecar_enabled",
                            "depth_sidecar_tighten_count",
                            "depth_sidecar_fail_closed_count",
                            "mean_depth_sidecar_scale_cap",
                            "inference_calls",
                            "applied_physics_steps",
                            "arm_residual",
                        )
                    },
                    "suction": summary.get("suction"),
                    "cradle": summary.get("cradle"),
                    "dataset": summary.get("dataset"),
                    "recovery_parameters": summary.get("recovery_parameters"),
                }
            )
            memory.record_plan(
                context=context,
                plan=recovery_plan,
                success=bool(summary.get("success")),
                force_abort=previous_failure == "force_safety_abort",
            )
            memory.save(memory_path)
        attempt_records.append(record)
        _write_json(args.output / "adaptive-retry-summary.partial.json", summarize_adaptive_attempts(attempt_records))
        if record["success"]:
            break

    result = summarize_adaptive_attempts(attempt_records)
    result.update(
        {
            "runtime_backend": args.backend,
            "maximum_attempts": args.max_attempts,
            "strategy_memory": str(memory_path),
            "checkpoint_selection": checkpoint_selection,
            "physical_parameters": {
                "profile": args.parcel_profile,
                "size_m": list(args.parcel_size_m),
                "mass_kg": args.parcel_mass_kg,
                "friction": args.parcel_friction,
                "offset_m": list(args.parcel_offset_m),
            },
        }
    )
    _write_json(
        args.output / "primitive-acquisition-manifest.json",
        build_primitive_acquisition_manifest(attempt_records),
    )
    _write_json(args.output / "adaptive-retry-summary.json", result)
    print(json.dumps(result, indent=2))
    return 0 if result["eventual_success"] or args.dry_run else 2


if __name__ == "__main__":
    raise SystemExit(main())
