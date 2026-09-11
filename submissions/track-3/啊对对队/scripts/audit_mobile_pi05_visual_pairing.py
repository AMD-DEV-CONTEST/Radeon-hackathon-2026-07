#!/usr/bin/env python3
"""Audit that a wrist RGB-D dataset changes vision but not control supervision."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from parcel_sorter.mobile_dataset import infer_mobile_policy_modality


CONTROL_COLUMNS = (
    "episode_index",
    "frame_index",
    "task_index",
    "observation.stage_id",
    "observation.state",
    "action",
)


def _flatten_numeric(value: Any, np: Any) -> Any:
    return np.asarray(value, dtype=np.float64).reshape(-1)


def _compare_aligned_rows(
    baseline_rows: list[dict[str, Any]],
    wrist_rows: list[dict[str, Any]],
    np: Any,
    *,
    state_atol: float,
    action_atol: float,
) -> dict[str, Any]:
    if len(baseline_rows) != len(wrist_rows):
        return {
            "passed": False,
            "baseline_frames": len(baseline_rows),
            "wrist_frames": len(wrist_rows),
            "alignment_mismatches": abs(len(baseline_rows) - len(wrist_rows)),
            "state_max_abs_error": None,
            "action_max_abs_error": None,
            "state_violation_frames": None,
            "action_violation_frames": None,
        }

    alignment_mismatches = 0
    state_violation_frames = 0
    action_violation_frames = 0
    state_shape_mismatches = 0
    action_shape_mismatches = 0
    state_max_abs_error = 0.0
    action_max_abs_error = 0.0
    for baseline, wrist in zip(baseline_rows, wrist_rows, strict=True):
        if any(
            baseline[key] != wrist[key]
            for key in (
                "episode_index",
                "frame_index",
                "task_index",
                "observation.stage_id",
            )
        ):
            alignment_mismatches += 1
        baseline_state = _flatten_numeric(baseline["observation.state"], np)
        wrist_state = _flatten_numeric(wrist["observation.state"], np)
        baseline_action = _flatten_numeric(baseline["action"], np)
        wrist_action = _flatten_numeric(wrist["action"], np)
        if baseline_state.shape != wrist_state.shape:
            state_violation_frames += 1
            state_shape_mismatches += 1
        else:
            state_error = float(np.max(np.abs(baseline_state - wrist_state)))
            state_max_abs_error = max(state_max_abs_error, state_error)
            state_violation_frames += int(state_error > state_atol)
        if baseline_action.shape != wrist_action.shape:
            action_violation_frames += 1
            action_shape_mismatches += 1
        else:
            action_error = float(np.max(np.abs(baseline_action - wrist_action)))
            action_max_abs_error = max(action_max_abs_error, action_error)
            action_violation_frames += int(action_error > action_atol)

    return {
        "passed": not any(
            (alignment_mismatches, state_violation_frames, action_violation_frames)
        ),
        "baseline_frames": len(baseline_rows),
        "wrist_frames": len(wrist_rows),
        "alignment_mismatches": alignment_mismatches,
        "state_max_abs_error": state_max_abs_error,
        "action_max_abs_error": action_max_abs_error,
        "state_violation_frames": state_violation_frames,
        "action_violation_frames": action_violation_frames,
        "state_shape_mismatches": state_shape_mismatches,
        "action_shape_mismatches": action_shape_mismatches,
        "state_atol": state_atol,
        "action_atol": action_atol,
    }


def _load_control_rows(root: Path, pq: Any) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    paths = sorted(root.glob("data/**/*.parquet"))
    if not paths:
        raise ValueError(f"dataset contains no data parquet: {root}")
    for path in paths:
        schema_names = set(pq.read_schema(path).names)
        missing = set(CONTROL_COLUMNS) - schema_names
        if missing:
            raise ValueError(f"dataset parquet is missing control columns: {sorted(missing)}")
        rows.extend(pq.read_table(path, columns=list(CONTROL_COLUMNS)).to_pylist())
    return sorted(rows, key=lambda row: (int(row["episode_index"]), int(row["frame_index"])))


def _load_tasks(root: Path, pq: Any) -> list[dict[str, Any]]:
    path = root / "meta/tasks.parquet"
    if not path.is_file():
        raise ValueError(f"dataset tasks metadata is missing: {path}")
    return sorted(
        pq.read_table(path, columns=["task_index", "task"]).to_pylist(),
        key=lambda row: int(row["task_index"]),
    )


def _successful_collection_signature(path: Path | None) -> list[dict[str, Any]] | None:
    if path is None:
        return None
    payload = json.loads(path.read_text(encoding="utf-8"))
    results = [item for item in payload.get("results", ()) if item.get("success")]
    declared = list(map(str, payload.get("successful_episode_order", ())))
    observed = [str(item.get("episode_id")) for item in results]
    if declared and declared != observed:
        raise ValueError(f"collection order is internally inconsistent: {path}")
    return [
        {
            "episode_id": str(item.get("episode_id")),
            "parameters": item.get("parameters"),
        }
        for item in results
    ]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("baseline", type=Path)
    parser.add_argument("wrist", type=Path)
    parser.add_argument("--baseline-collection-summary", type=Path)
    parser.add_argument("--wrist-collection-summary", type=Path)
    parser.add_argument("--state-atol", type=float, default=1e-6)
    parser.add_argument("--action-atol", type=float, default=1e-6)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.state_atol < 0.0 or args.action_atol < 0.0:
        parser.error("pairing tolerances must be non-negative")

    import numpy as np
    import pyarrow.parquet as pq

    baseline = args.baseline.resolve()
    wrist = args.wrist.resolve()
    baseline_info = json.loads((baseline / "meta/info.json").read_text(encoding="utf-8"))
    wrist_info = json.loads((wrist / "meta/info.json").read_text(encoding="utf-8"))
    baseline_modality = infer_mobile_policy_modality(baseline_info.get("features", {}))
    wrist_modality = infer_mobile_policy_modality(wrist_info.get("features", {}))
    modality_passed = baseline_modality == "rgbd" and wrist_modality == "rgbd_wrist"

    paired = _compare_aligned_rows(
        _load_control_rows(baseline, pq),
        _load_control_rows(wrist, pq),
        np,
        state_atol=args.state_atol,
        action_atol=args.action_atol,
    )
    tasks_match = _load_tasks(baseline, pq) == _load_tasks(wrist, pq)
    baseline_signature = _successful_collection_signature(
        args.baseline_collection_summary
    )
    wrist_signature = _successful_collection_signature(args.wrist_collection_summary)
    collection_pairing_required = (
        args.baseline_collection_summary is not None
        or args.wrist_collection_summary is not None
    )
    collection_match = (
        baseline_signature == wrist_signature
        if baseline_signature is not None and wrist_signature is not None
        else not collection_pairing_required
    )
    errors = []
    if not modality_passed:
        errors.append("visual_modality_pair_mismatch")
    if not paired["passed"]:
        errors.append("control_supervision_mismatch")
    if not tasks_match:
        errors.append("task_metadata_mismatch")
    if not collection_match:
        errors.append("collection_episode_or_parameter_mismatch")
    payload = {
        "schema_version": 1,
        "protocol": "pi05-wrist-single-factor-pairing-audit-v1",
        "status": "passed" if not errors else "failed",
        "errors": errors,
        "baseline_dataset": str(baseline),
        "wrist_dataset": str(wrist),
        "baseline_modality": baseline_modality,
        "wrist_modality": wrist_modality,
        "control_pairing": paired,
        "tasks_match": tasks_match,
        "collection_signatures_match": collection_match,
        "claim_boundary": (
            "This audit isolates the visual treatment by checking paired supervision; "
            "it does not measure routing or closed-loop VLA capability."
        ),
    }
    rendered = json.dumps(payload, indent=2, sort_keys=True) + "\n"
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        temporary = args.output.with_name(f".{args.output.name}.tmp")
        temporary.write_text(rendered, encoding="utf-8")
        temporary.replace(args.output)
    print(rendered, end="")
    return 0 if payload["status"] == "passed" else 2


if __name__ == "__main__":
    raise SystemExit(main())
