#!/usr/bin/env python3
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
import math
from pathlib import Path
from typing import Any, Mapping, Sequence


PROJECT_ROOT = Path(__file__).resolve().parents[1]
VECTOR_FIELDS = (
    "robot_qpos",
    "robot_dof_velocity",
    "robot_dof_actual_force_n",
    "robot_dof_control_force_n",
    "parcel_qpos",
    "parcel_dof_velocity",
)
CONTROL_TARGET_FIELDS = (
    "robot_dof_position_target",
    "robot_dof_velocity_target",
    "robot_dof_force_target_n",
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Summarize the preregistered Genesis control-input replay."
    )
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--stock", type=Path, required=True)
    parser.add_argument("--mass-aware", type=Path, required=True)
    parser.add_argument("--comparison", type=Path, required=True)
    parser.add_argument("--preregistered-commit", required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args()


def _load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _artifact(path: Path) -> dict[str, Any]:
    path = path.resolve()
    return {
        "path": str(path),
        "bytes": path.stat().st_size,
        "sha256": _sha256(path),
    }


def _event_key(event: Mapping[str, Any]) -> tuple[int, int]:
    return int(event["control_step"]), int(event["physics_substep"])


def _max_abs(left: Sequence[Any], right: Sequence[Any]) -> float:
    return max(
        abs(float(a) - float(b))
        for a, b in zip(left, right, strict=True)
    )


def _maximum_penetration(event: Mapping[str, Any]) -> float:
    return max(
        (float(row["penetration_m"]) for row in event.get("contacts", ())),
        default=0.0,
    )


def _source_replay_differences(
    source_events: Sequence[Mapping[str, Any]],
    replay_events: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    source_by_key = {_event_key(event): event for event in source_events}
    replay_by_key = {_event_key(event): event for event in replay_events}
    keys = sorted(set(source_by_key) & set(replay_by_key))
    if not keys:
        raise ValueError("source and replay have no aligned events")
    vector_differences = {
        field: max(
            _max_abs(source_by_key[key][field], replay_by_key[key][field])
            for key in keys
        )
        for field in VECTOR_FIELDS
    }
    scalar_differences = {
        "peak_parcel_contact_force_n": max(
            abs(
                float(source_by_key[key]["peak_parcel_contact_force_n"])
                - float(replay_by_key[key]["peak_parcel_contact_force_n"])
            )
            for key in keys
        ),
        "maximum_contact_penetration_m": max(
            abs(
                _maximum_penetration(source_by_key[key])
                - _maximum_penetration(replay_by_key[key])
            )
            for key in keys
        ),
    }
    return {
        "aligned_event_count": len(keys),
        "first_event": list(keys[0]),
        "last_event": list(keys[-1]),
        "maximum_absolute_difference": {
            **vector_differences,
            **scalar_differences,
        },
    }


def _control_input_summary(
    events: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    signatures = Counter(
        tuple(int(value) for value in event["robot_dof_control_mode"])
        for event in events
    )
    changes = []
    for previous, current in zip(events, events[1:], strict=False):
        changed_fields = []
        if previous["robot_dof_control_mode"] != current["robot_dof_control_mode"]:
            changed_fields.append("robot_dof_control_mode")
        for field in CONTROL_TARGET_FIELDS:
            if _max_abs(previous[field], current[field]) > 0.0:
                changed_fields.append(field)
        if changed_fields:
            changes.append(
                {
                    "event": list(_event_key(current)),
                    "changed_fields": changed_fields,
                }
            )
    return {
        "mode_encoding": {"0": "position", "1": "velocity", "2": "force"},
        "mode_signatures": [
            {"modes": list(signature), "event_count": count}
            for signature, count in sorted(signatures.items())
        ],
        "control_input_change_events": changes,
    }


def _first_failure(summary: Mapping[str, Any]) -> dict[str, Any] | None:
    force = summary.get("first_force_abort")
    penetration = summary.get("first_penetration_limit")
    if force is None and penetration is None:
        return None
    candidates = []
    if force is not None:
        candidates.append(
            {
                "event": [int(force["control_step"]), int(force["physics_substep"])],
                "reason": "force",
                "force_n": float(force["force_n"]),
            }
        )
    if penetration is not None:
        candidates.append(
            {
                "event": [
                    int(penetration["control_step"]),
                    int(penetration["physics_substep"]),
                ],
                "reason": "penetration",
                "penetration_m": float(penetration["penetration_m"]),
            }
        )
    return min(candidates, key=lambda item: tuple(item["event"]))


def main() -> int:
    args = parse_args()
    paths = {
        "source_capture": args.source.resolve(),
        "stock_replay": args.stock.resolve(),
        "mass_aware_replay": args.mass_aware.resolve(),
        "comparison": args.comparison.resolve(),
    }
    source = _load(paths["source_capture"])
    stock = _load(paths["stock_replay"])
    mass_aware = _load(paths["mass_aware_replay"])
    comparison = _load(paths["comparison"])
    source_rollout = source["rollouts"][0]
    source_events = source_rollout["report"]["safety_summary"][
        "contact_branch_events"
    ]
    source_summary = source_rollout["report"]["safety_summary"][
        "contact_branch_summary"
    ]
    mass_differences = _source_replay_differences(
        source_events,
        mass_aware["events"],
    )
    maximum_mass_difference = max(
        float(value)
        for value in mass_differences["maximum_absolute_difference"].values()
    )
    if not math.isfinite(maximum_mass_difference):
        raise ValueError("source/replay difference is non-finite")

    code_paths = {
        "genesis_env": PROJECT_ROOT / "src/parcel_sorter/genesis_env.py",
        "replay_runner": (
            PROJECT_ROOT / "scripts/replay_genesis_finger_constraint_dynamic_state.py"
        ),
        "capture_runner": (
            PROJECT_ROOT / "scripts/diagnose_counterfactual_grasp_candidates.py"
        ),
        "comparison_runner": (
            PROJECT_ROOT / "scripts/compare_genesis_finger_constraint_repro.py"
        ),
        "replay_support_module": (
            PROJECT_ROOT / "src/parcel_sorter/finger_constraint_repro.py"
        ),
        "result_summarizer": Path(__file__).resolve(),
    }
    payload = {
        "schema_version": "1.0",
        "status": "complete_invalid_cross_model_reference",
        "recorded_date": "2026-07-26",
        "study_type": "genesis_panda_finger_constraint_control_input_replay",
        "runtime": {
            "accelerator": "single AMD Radeon gfx1100",
            "accelerator_memory_gib": 47.98,
            "rocm_version": "7.2",
            "simulator": "Genesis 1.2.3",
            "physics_hz": 240,
        },
        "preregistered_commit": args.preregistered_commit,
        "source_capture": {
            "same_candidate_selected": (
                source["tested_candidate_ids"]
                == ["canonical-long-+0.000-up-0.045"]
            ),
            "force_abort_frame": int(source_rollout["force_abort_frame"]),
            "peak_force_n": float(source_summary["peak_force_contact"]["force_magnitude_n"]),
            "maximum_penetration_m": float(
                source_summary["maximum_contact_penetration_m"]
            ),
            "event_count": len(source_events),
            "control_inputs": _control_input_summary(source_events),
        },
        "replays": {
            "stock": {
                "status": stock["status"],
                "first_failure": _first_failure(stock["summary"]),
                "peak_force_n": float(
                    stock["summary"]["peak_force_contact"]["force_magnitude_n"]
                ),
                "maximum_penetration_m": float(
                    stock["summary"]["maximum_contact_penetration_m"]
                ),
            },
            "mass_aware": {
                "status": mass_aware["status"],
                "first_failure": _first_failure(mass_aware["summary"]),
                "peak_force_n": float(
                    mass_aware["summary"]["peak_force_contact"]["force_magnitude_n"]
                ),
                "maximum_penetration_m": float(
                    mass_aware["summary"]["maximum_contact_penetration_m"]
                ),
                "source_alignment": mass_differences,
            },
        },
        "comparison": {
            "conclusion": comparison["conclusion"],
            "reference_numerical_safety_failure": comparison[
                "reference_numerical_safety_failure"
            ],
            "candidate_numerical_safety_failure": comparison[
                "candidate_numerical_safety_failure"
            ],
            "aligned_sample_count": comparison["comparison"][
                "aligned_sample_count"
            ],
            "first_divergence": comparison["comparison"]["first_divergence"],
        },
        "interpretation": {
            "raw_control_inputs_reproduced_failure_event_and_safety_metrics": (
                mass_aware["summary"]["first_force_abort"]
                == source_summary["first_force_abort"]
                and math.isclose(
                    float(
                        mass_aware["summary"]["peak_force_contact"][
                            "force_magnitude_n"
                        ]
                    ),
                    float(source_summary["peak_force_contact"]["force_magnitude_n"]),
                    rel_tol=0.0,
                    abs_tol=0.0001,
                )
                and math.isclose(
                    float(mass_aware["summary"]["maximum_contact_penetration_m"]),
                    float(source_summary["maximum_contact_penetration_m"]),
                    rel_tol=0.0,
                    abs_tol=0.000001,
                )
            ),
            "all_aligned_fields_within_initial_state_tolerance": (
                maximum_mass_difference <= 0.000001
            ),
            "maximum_aligned_field_difference": maximum_mass_difference,
            "cross_model_inertia_attribution_valid": False,
            "reason": (
                "the stock-inertia scene crossed both registered safety boundaries "
                "when initialized from the mass-aware source state"
            ),
            "solver_warm_start_required_for_mass_aware_reproduction": False,
            "adapter_promoted": False,
            "new_episode_opened": False,
            "holdout_opened": False,
            "safety_threshold_changed": False,
            "next_allowed_work": (
                "return to the stock-hand geometry-planning baseline or separately "
                "preregister a full-trajectory physical adapter design; do not tune "
                "the rejected adapter on episode 4120001"
            ),
        },
        "artifacts": {name: _artifact(path) for name, path in paths.items()},
        "execution_code": {
            name: _artifact(path) for name, path in code_paths.items()
        },
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "output": str(args.output),
                "status": payload["status"],
                "source_replay_max_abs_difference": maximum_mass_difference,
                "comparison": payload["comparison"],
            },
            allow_nan=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
