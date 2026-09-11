#!/usr/bin/env python3
"""Summarize mode supervision and observable context in a PI0.5 dataset."""

from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path

import pyarrow.parquet as pq

from parcel_sorter.mobile_pi05_contract import MOBILE_STAGE_NAMES, PI05_GRASP_MODES


def _mode(action: list[float], mode_start: int = 9) -> str:
    logits = action[mode_start : mode_start + 3]
    return PI05_GRASP_MODES[max(range(3), key=logits.__getitem__)]


def _quantile_normalized_mode(
    action: list[float], action_stats: dict[str, list[float]], mode_start: int = 9
) -> str:
    """Decode the label after the same per-channel quantile map used by PI0.5."""

    q01 = action_stats["q01"]
    q99 = action_stats["q99"]
    normalized = []
    for index in range(mode_start, mode_start + 3):
        scale = max(float(q99[index]) - float(q01[index]), 1e-8)
        normalized.append(
            2.0 * (float(action[index]) - float(q01[index])) / scale - 1.0
        )
    return PI05_GRASP_MODES[max(range(3), key=normalized.__getitem__)]


def _stage(state: list[float]) -> str:
    values = state[56:62]
    return MOBILE_STAGE_NAMES[max(range(len(values)), key=values.__getitem__)]


def _task_lookup(dataset: Path) -> dict[int, str]:
    rows = pq.read_table(dataset / "meta" / "tasks.parquet").to_pylist()
    return {int(row["task_index"]): str(row["task"]) for row in rows}


def summarize(dataset: Path) -> dict[str, object]:
    tasks = _task_lookup(dataset)
    stats = json.loads((dataset / "meta" / "stats.json").read_text(encoding="utf-8"))
    action_stats = stats["action"]
    info = json.loads((dataset / "meta" / "info.json").read_text(encoding="utf-8"))
    action_shape = info.get("features", {}).get("action", {}).get("shape")
    if action_shape == [23]:
        action_contract = "absolute_v1"
        mode_start = 19
    elif action_shape == [14]:
        action_contract = "residual_v1"
        mode_start = 9
    else:
        raise ValueError(f"unsupported PI0.5 action shape: {action_shape}")
    frame_counts: Counter[str] = Counter()
    stage_counts: dict[str, Counter[str]] = defaultdict(Counter)
    episodes: dict[str, set[int]] = defaultdict(set)
    task_counts: dict[str, Counter[str]] = defaultdict(Counter)
    contexts: dict[str, set[tuple[object, ...]]] = defaultdict(set)
    hidden_mode_violations = 0
    normalized_mode_label_mismatches = 0

    columns = ["episode_index", "task_index", "observation.state", "action"]
    files = sorted((dataset / "data").rglob("*.parquet"))
    for path in files:
        for row in pq.read_table(path, columns=columns).to_pylist():
            action = [float(value) for value in row["action"]]
            state = [float(value) for value in row["observation.state"]]
            mode = _mode(action, mode_start)
            normalized_mode_label_mismatches += int(
                _quantile_normalized_mode(action, action_stats, mode_start) != mode
            )
            episode = int(row["episode_index"])
            task = tasks[int(row["task_index"])]
            shape = "box" if state[46] >= state[47] else "cylinder"
            context = (
                shape,
                round(state[48], 6),
                round(state[49], 6),
                round(state[50], 6),
                round(state[51], 6),
            )
            frame_counts[mode] += 1
            stage_counts[mode][_stage(state)] += 1
            episodes[mode].add(episode)
            task_counts[mode][task] += 1
            contexts[mode].add(context)
            hidden_mode_violations += int(any(abs(value) > 1e-8 for value in state[52:55]))

    modes = {}
    for mode in PI05_GRASP_MODES:
        modes[mode] = {
            "frames": frame_counts[mode],
            "frame_fraction": frame_counts[mode] / max(1, sum(frame_counts.values())),
            "episodes": sorted(episodes[mode]),
            "episode_count": len(episodes[mode]),
            "stage_frames": dict(stage_counts[mode]),
            "tasks": dict(task_counts[mode]),
            "observable_object_contexts": [
                {
                    "shape": item[0],
                    "size_m": list(item[1:4]),
                    "mass_kg": item[4],
                }
                for item in sorted(contexts[mode])
            ],
        }
    status = (
        "passed"
        if not hidden_mode_violations
        and not normalized_mode_label_mismatches
        and all(frame_counts.values())
        else "failed"
    )
    total_frames = sum(frame_counts.values())
    balanced_weights = {
        mode: total_frames / (len(PI05_GRASP_MODES) * frame_counts[mode])
        for mode in PI05_GRASP_MODES
        if frame_counts[mode]
    }
    return {
        "schema_version": 1,
        "protocol": "pi05-hidden-mode-dataset-diagnostic-v1",
        "status": status,
        "dataset": str(dataset.resolve()),
        "action_contract": action_contract,
        "parquet_files": len(files),
        "frames": sum(frame_counts.values()),
        "hidden_mode_state_violations": hidden_mode_violations,
        "normalized_mode_label_mismatches": normalized_mode_label_mismatches,
        "mode_action_quantiles": {
            key: [
                float(value)
                for value in action_stats[key][mode_start : mode_start + 3]
            ]
            for key in ("min", "max", "q01", "q99")
        },
        "balanced_cross_entropy_weights": balanced_weights,
        "modes": modes,
        "claim_boundary": "Dataset supervision audit only; it does not measure policy accuracy.",
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("dataset", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    payload = summarize(args.dataset)
    rendered = json.dumps(payload, indent=2, sort_keys=True)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)
    return 0 if payload["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
