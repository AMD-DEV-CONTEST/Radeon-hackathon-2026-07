"""Build a primitive-steerable LeRobot dataset with a progress action channel."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import shutil
from typing import Any

from parcel_sorter.mobile_primitive_learning import (
    MOBILE_PRIMITIVE_ACTION_NAMES,
    primitive_labels,
    primitive_progress,
    primitive_task_text,
    segment_mobile_actions,
    stage_agreement,
)


STAT_KEYS = ("min", "max", "mean", "std", "q01", "q10", "q50", "q90", "q99")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--base-motion-threshold", type=float, default=0.005)
    parser.add_argument("--min-motion-frames", type=int, default=5)
    args = parser.parse_args()
    if not (args.source / "meta" / "info.json").is_file():
        parser.error("source is not a LeRobot dataset")
    if args.output.exists():
        parser.error("output must not already exist")

    import numpy as np
    import pyarrow as pa
    import pyarrow.parquet as pq

    source = args.source.resolve()
    output = args.output.resolve()
    source_files = sorted(source.glob("data/**/*.parquet"))
    if not source_files:
        parser.error("source dataset contains no parquet episodes")
    source_hashes = {
        str(path.relative_to(source)): _sha256(path) for path in source_files
    }
    shutil.copytree(source, output)

    task_rows = pq.read_table(source / "meta" / "tasks.parquet").to_pylist()
    base_tasks = {int(row["task_index"]): str(row["task"]) for row in task_rows}
    primitive_tasks: dict[str, int] = {}
    episode_progress: dict[int, list[float]] = {}
    episode_task_texts: dict[int, list[str]] = {}
    episode_source_task: dict[int, int] = {}
    episode_manifests: list[dict[str, Any]] = []
    all_progress: list[float] = []

    for source_path in source_files:
        table = pq.read_table(source_path)
        rows = table.select(
            [
                "episode_index",
                "frame_index",
                "task_index",
                "action",
                "observation.stage_id",
            ]
        ).to_pylist()
        episode_ids = sorted({int(row["episode_index"]) for row in rows})
        new_actions = [None] * len(rows)
        new_task_indices = [None] * len(rows)
        for episode_index in episode_ids:
            offsets = [
                index
                for index, row in enumerate(rows)
                if int(row["episode_index"]) == episode_index
            ]
            episode_rows = [rows[index] for index in offsets]
            original_task_indices = {int(row["task_index"]) for row in episode_rows}
            if len(original_task_indices) != 1:
                raise ValueError(f"episode {episode_index} has multiple parent tasks")
            original_task_index = original_task_indices.pop()
            base_task = base_tasks[original_task_index]
            segments = segment_mobile_actions(
                [row["action"] for row in episode_rows],
                frame_indices=[int(row["frame_index"]) for row in episode_rows],
                base_motion_threshold=args.base_motion_threshold,
                min_motion_frames=args.min_motion_frames,
            )
            progress = primitive_progress(segments, frame_count=len(episode_rows))
            labels = primitive_labels(segments, frame_count=len(episode_rows))
            agreement = stage_agreement(
                labels,
                [
                    _scalar_stage_id(row["observation.stage_id"])
                    for row in episode_rows
                ],
            )
            task_texts = [primitive_task_text(base_task, label) for label in labels]
            for text in task_texts:
                if text not in primitive_tasks:
                    primitive_tasks[text] = len(primitive_tasks)
            for output_offset, source_offset in enumerate(offsets):
                new_actions[source_offset] = [
                    *map(float, episode_rows[output_offset]["action"]),
                    float(progress[output_offset]),
                ]
                new_task_indices[source_offset] = primitive_tasks[task_texts[output_offset]]
            episode_progress[episode_index] = list(progress)
            episode_task_texts[episode_index] = list(dict.fromkeys(task_texts))
            episode_source_task[episode_index] = original_task_index
            all_progress.extend(progress)
            episode_manifests.append(
                {
                    "episode_index": episode_index,
                    "source_task_index": original_task_index,
                    "source_task": base_task,
                    "frames": len(episode_rows),
                    "segments": [segment.to_dict() for segment in segments],
                    "stage_label_agreement_audit": agreement,
                }
            )

        action_index = table.schema.get_field_index("action")
        task_index = table.schema.get_field_index("task_index")
        table = table.set_column(
            action_index,
            "action",
            pa.array(new_actions, type=pa.list_(pa.float32(), len(MOBILE_PRIMITIVE_ACTION_NAMES))),
        )
        table = table.set_column(
            task_index,
            "task_index",
            pa.array(new_task_indices, type=table.schema.field(task_index).type),
        )
        destination = output / source_path.relative_to(source)
        pq.write_table(table, destination)

    progress_stats = _stats(all_progress, np)
    _rewrite_info(output, total_tasks=len(primitive_tasks))
    _rewrite_global_stats(output, progress_stats)
    _rewrite_tasks(output, primitive_tasks)
    _rewrite_episode_meta(
        output,
        episode_progress=episode_progress,
        episode_task_texts=episode_task_texts,
        np=np,
        pa=pa,
        pq=pq,
    )
    output_hashes = {
        str(path.relative_to(output)): _sha256(path)
        for path in sorted(output.glob("data/**/*.parquet"))
    }
    total_matches = sum(
        item["stage_label_agreement_audit"]["matches"] for item in episode_manifests
    )
    manifest = {
        "schema_version": 1,
        "protocol": "pash-event-primitive-dataset-v1",
        "source_dataset": str(source),
        "output_dataset": str(output),
        "episodes": len(episode_manifests),
        "frames": len(all_progress),
        "primitive_tasks": len(primitive_tasks),
        "action_dimension": len(MOBILE_PRIMITIVE_ACTION_NAMES),
        "action_names": list(MOBILE_PRIMITIVE_ACTION_NAMES),
        "segmentation_inputs": ["base_velocity", "left_tri_suction_command"],
        "segmentation_excludes": ["observation.stage_id", "privileged_parcel_pose"],
        "stage_label_agreement_audit": {
            "frames": len(all_progress),
            "matches": total_matches,
            "accuracy": total_matches / len(all_progress),
        },
        "source_data_sha256": source_hashes,
        "output_data_sha256": output_hashes,
        "episode_manifests": episode_manifests,
        "claim_boundary": (
            "event segmentation is validated on instrumented simulation demonstrations; "
            "it is not a claim of open-world VLM segmentation or unseen-task generalization"
        ),
    }
    manifest_path = output / "PRIMITIVE_DATASET_MANIFEST.json"
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(json.dumps({**manifest, "episode_manifests": "see manifest"}, indent=2))
    return 0


def _rewrite_info(root: Path, *, total_tasks: int) -> None:
    path = root / "meta" / "info.json"
    info = json.loads(path.read_text(encoding="utf-8"))
    info["total_tasks"] = total_tasks
    info["features"]["action"]["shape"] = [len(MOBILE_PRIMITIVE_ACTION_NAMES)]
    info["features"]["action"]["names"] = list(MOBILE_PRIMITIVE_ACTION_NAMES)
    info["features"]["action"]["info"] = {
        "progress_channel": len(MOBILE_PRIMITIVE_ACTION_NAMES) - 1,
        "progress_range": [0.0, 1.0],
    }
    path.write_text(json.dumps(info, indent=2), encoding="utf-8")


def _rewrite_global_stats(root: Path, progress_stats: dict[str, Any]) -> None:
    path = root / "meta" / "stats.json"
    stats = json.loads(path.read_text(encoding="utf-8"))
    for key in STAT_KEYS:
        stats["action"][key].append(progress_stats[key])
    path.write_text(json.dumps(stats, indent=2), encoding="utf-8")


def _rewrite_tasks(root: Path, primitive_tasks: dict[str, int]) -> None:
    import pandas as pd

    path = root / "meta" / "tasks.parquet"
    ordered = sorted(primitive_tasks.items(), key=lambda item: item[1])
    tasks = pd.DataFrame(
        {"task_index": [index for _, index in ordered]},
        index=pd.Index([task for task, _ in ordered], name="task"),
    )
    tasks.to_parquet(path)


def _rewrite_episode_meta(
    root: Path,
    *,
    episode_progress: dict[int, list[float]],
    episode_task_texts: dict[int, list[str]],
    np: Any,
    pa: Any,
    pq: Any,
) -> None:
    for path in sorted((root / "meta" / "episodes").glob("**/*.parquet")):
        table = pq.read_table(path)
        rows = table.to_pylist()
        for key in STAT_KEYS:
            column = f"stats/action/{key}"
            values = []
            for row in rows:
                episode_index = int(row["episode_index"])
                item = list(row[column])
                item.append(_stats(episode_progress[episode_index], np)[key])
                values.append(item)
            index = table.schema.get_field_index(column)
            table = table.set_column(
                index,
                column,
                pa.array(values, type=table.schema.field(index).type),
            )
        tasks_index = table.schema.get_field_index("tasks")
        table = table.set_column(
            tasks_index,
            "tasks",
            pa.array(
                [episode_task_texts[int(row["episode_index"])] for row in rows],
                type=table.schema.field(tasks_index).type,
            ),
        )
        pq.write_table(table, path)


def _stats(values: list[float], np: Any) -> dict[str, float]:
    array = np.asarray(values, dtype=np.float64)
    return {
        "min": float(array.min()),
        "max": float(array.max()),
        "mean": float(array.mean()),
        "std": float(array.std()),
        "q01": float(np.quantile(array, 0.01)),
        "q10": float(np.quantile(array, 0.10)),
        "q50": float(np.quantile(array, 0.50)),
        "q90": float(np.quantile(array, 0.90)),
        "q99": float(np.quantile(array, 0.99)),
    }


def _scalar_stage_id(value: Any) -> int:
    if isinstance(value, (list, tuple)):
        return int(value[0])
    return int(value)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


if __name__ == "__main__":
    raise SystemExit(main())
