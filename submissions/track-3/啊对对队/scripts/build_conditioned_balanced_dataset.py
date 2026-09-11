from __future__ import annotations

import argparse
from collections import Counter
import json
import os
from pathlib import Path
import shutil
from typing import Any

import numpy as np

from parcel_sorter.task_conditioning import (
    build_conditioned_task,
    select_balanced_train_episodes,
)


QUANTILES = {
    "q01": 0.01,
    "q10": 0.10,
    "q50": 0.50,
    "q90": 0.90,
    "q99": 0.99,
}


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def _replace_column(table: Any, name: str, values: list[Any], pa: Any) -> Any:
    index = table.schema.get_field_index(name)
    if index < 0:
        raise ValueError(f"missing parquet column: {name}")
    field = table.schema.field(index)
    return table.set_column(index, name, pa.array(values, type=field.type))


def _constant_stat_updates(prefix: str, value: float, count: int) -> dict[str, list[float]]:
    updates = {
        f"{prefix}/min": [value],
        f"{prefix}/max": [value],
        f"{prefix}/mean": [value],
        f"{prefix}/std": [0.0],
        f"{prefix}/count": [count],
    }
    updates.update({f"{prefix}/{name}": [value] for name in QUANTILES})
    return updates


def _range_stat_updates(prefix: str, start: int, count: int) -> dict[str, list[float]]:
    values = np.arange(start, start + count, dtype=np.float64)
    updates = {
        f"{prefix}/min": [float(values.min())],
        f"{prefix}/max": [float(values.max())],
        f"{prefix}/mean": [float(values.mean())],
        f"{prefix}/std": [float(values.std())],
        f"{prefix}/count": [count],
    }
    updates.update(
        {
            f"{prefix}/{name}": [float(np.quantile(values, quantile))]
            for name, quantile in QUANTILES.items()
        }
    )
    return updates


def _episode_stats(row: dict[str, Any], feature_names: list[str]) -> dict[str, dict[str, Any]]:
    stats: dict[str, dict[str, Any]] = {}
    for feature_name in feature_names:
        feature_stats: dict[str, Any] = {}
        prefix = f"stats/{feature_name}/"
        for key, value in row.items():
            if key.startswith(prefix):
                feature_stats[key[len(prefix) :]] = np.asarray(value)
        if feature_stats:
            stats[feature_name] = feature_stats
    return stats


def build(
    source: Path,
    destination: Path,
    *,
    source_split_manifest: Path,
    audit_manifest: Path,
    output_split_manifest: Path,
    target_per_profile: int,
    max_repeats: int,
    seed: int,
) -> dict[str, Any]:
    try:
        import pyarrow as pa
        import pyarrow.parquet as pq
        from lerobot.datasets.compute_stats import aggregate_stats
        from lerobot.datasets.io_utils import write_stats
    except ImportError as exc:
        raise RuntimeError("pyarrow and LeRobot are required to derive the dataset") from exc

    source = source.resolve()
    destination = destination.resolve()
    if destination.exists():
        raise FileExistsError(f"destination already exists: {destination}")

    split_payload = json.loads(source_split_manifest.read_text(encoding="utf-8"))
    assignments = list(split_payload["assignments"])
    assignment_by_dataset = {
        int(item["dataset_episode_index"]): item for item in assignments
    }
    audit_by_original = {
        int(item["episode_index"]): item for item in _read_jsonl(audit_manifest)
    }
    balanced_train = select_balanced_train_episodes(
        assignments,
        target_per_profile=target_per_profile,
        max_repeats=max_repeats,
        seed=seed,
    )

    ordered_sources: list[tuple[int, str, int]] = [
        (item.source_episode_index, "train", item.repeat_ordinal)
        for item in balanced_train
    ]
    for split_name in ("validation", "heldout"):
        ordered_sources.extend(
            (
                int(item["dataset_episode_index"]),
                split_name,
                0,
            )
            for item in assignments
            if item["split"] == split_name
        )

    try:
        shutil.copytree(source, destination, copy_function=os.link)
    except OSError:
        if destination.exists():
            shutil.rmtree(destination)
        shutil.copytree(source, destination, copy_function=shutil.copy2)

    try:
        source_data_files = sorted((source / "data").rglob("*.parquet"))
        source_data = pa.concat_tables([pq.read_table(path) for path in source_data_files])
        source_indices = np.asarray(source_data["index"].to_numpy())
        if not np.array_equal(source_indices, np.arange(source_data.num_rows)):
            raise ValueError("source data index is not contiguous")

        source_episode_path = next((source / "meta" / "episodes").rglob("*.parquet"))
        source_episodes = pq.read_table(source_episode_path)
        episode_row_by_index = {
            int(source_episodes["episode_index"][row].as_py()): row
            for row in range(source_episodes.num_rows)
        }
        source_info = json.loads((source / "meta" / "info.json").read_text(encoding="utf-8"))
        source_stats = json.loads((source / "meta" / "stats.json").read_text(encoding="utf-8"))

        tasks = sorted(
            {
                build_conditioned_task(
                    str(assignment_by_dataset[source_index]["profile_id"]),
                    str(
                        audit_by_original[
                            int(assignment_by_dataset[source_index]["original_episode_index"])
                        ]["sample"]["destination"]
                    ),
                )
                for source_index, _, _ in ordered_sources
            }
        )
        task_index_by_text = {task: index for index, task in enumerate(tasks)}

        derived_data_file_groups: list[list[Any]] = []
        current_data_tables: list[Any] = []
        current_data_frames = 0
        data_file_index = 0
        derived_episode_rows = []
        derived_assignments = []
        global_index = 0
        split_indices: dict[str, list[int]] = {"train": [], "validation": [], "heldout": []}

        for derived_index, (source_index, split_name, repeat_ordinal) in enumerate(ordered_sources):
            assignment = assignment_by_dataset[source_index]
            original_index = int(assignment["original_episode_index"])
            audit = audit_by_original[original_index]
            profile_id = str(assignment["profile_id"])
            destination_name = str(audit["sample"]["destination"])
            task = build_conditioned_task(profile_id, destination_name)
            task_index = task_index_by_text[task]

            source_episode_row_index = episode_row_by_index[source_index]
            source_episode_dict = source_episodes.slice(source_episode_row_index, 1).to_pylist()[0]
            start = int(source_episode_dict["dataset_from_index"])
            end = int(source_episode_dict["dataset_to_index"])
            length = end - start
            if current_data_tables and current_data_frames + length > 5_000:
                derived_data_file_groups.append(current_data_tables)
                current_data_tables = []
                current_data_frames = 0
                data_file_index += 1
            data_table = source_data.slice(start, length)
            data_table = _replace_column(data_table, "episode_index", [derived_index] * length, pa)
            data_table = _replace_column(
                data_table,
                "index",
                list(range(global_index, global_index + length)),
                pa,
            )
            data_table = _replace_column(data_table, "task_index", [task_index] * length, pa)
            current_data_tables.append(data_table)
            current_data_frames += length

            episode_row = source_episodes.slice(source_episode_row_index, 1)
            updates: dict[str, Any] = {
                "episode_index": derived_index,
                "tasks": [task],
                "data/chunk_index": 0,
                "data/file_index": data_file_index,
                "dataset_from_index": global_index,
                "dataset_to_index": global_index + length,
                "meta/episodes/chunk_index": 0,
                "meta/episodes/file_index": 0,
            }
            updates.update(
                _constant_stat_updates("stats/episode_index", float(derived_index), length)
            )
            updates.update(_constant_stat_updates("stats/task_index", float(task_index), length))
            updates.update(_range_stat_updates("stats/index", global_index, length))
            for name, value in updates.items():
                episode_row = _replace_column(episode_row, name, [value], pa)
            derived_episode_rows.append(episode_row)

            split_indices[split_name].append(derived_index)
            derived_assignments.append(
                {
                    "dataset_episode_index": derived_index,
                    "source_dataset_episode_index": source_index,
                    "original_episode_index": original_index,
                    "profile_id": profile_id,
                    "destination": destination_name,
                    "task": task,
                    "task_index": task_index,
                    "split": split_name,
                    "repeat_ordinal": repeat_ordinal,
                }
            )
            global_index += length

        if current_data_tables:
            derived_data_file_groups.append(current_data_tables)

        output_episodes = pa.concat_tables(derived_episode_rows).combine_chunks()

        shutil.rmtree(destination / "data")
        (destination / "data" / "chunk-000").mkdir(parents=True)
        for file_index, tables in enumerate(derived_data_file_groups):
            # Combining within a bounded shard avoids both Hugging Face's
            # nested-chunk limitation and Arrow's 2 GB binary offset limit.
            pq.write_table(
                pa.concat_tables(tables).combine_chunks(),
                destination
                / "data"
                / "chunk-000"
                / f"file-{file_index:03d}.parquet",
                compression="zstd",
            )
        shutil.rmtree(destination / "meta" / "episodes")
        (destination / "meta" / "episodes" / "chunk-000").mkdir(parents=True)
        pq.write_table(
            output_episodes,
            destination / "meta" / "episodes" / "chunk-000" / "file-000.parquet",
            compression="zstd",
        )

        source_tasks = pq.read_table(source / "meta" / "tasks.parquet")
        task_table = pa.Table.from_arrays(
            [
                pa.array(range(len(tasks)), type=source_tasks.schema.field("task_index").type),
                pa.array(tasks, type=source_tasks.schema.field("task").type),
            ],
            schema=source_tasks.schema,
        )
        pq.write_table(task_table, destination / "meta" / "tasks.parquet", compression="zstd")

        info = dict(source_info)
        info["total_episodes"] = len(derived_assignments)
        info["total_frames"] = global_index
        info["total_tasks"] = len(tasks)
        info["splits"] = {"train": f"0:{len(derived_assignments)}"}
        (destination / "meta" / "info.json").write_text(
            json.dumps(info, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

        episode_stats = [
            _episode_stats(row, list(source_stats)) for row in output_episodes.to_pylist()
        ]
        write_stats(aggregate_stats(episode_stats), destination)

        profile_counts = Counter(
            item["profile_id"] for item in derived_assignments if item["split"] == "train"
        )
        manifest = {
            "schema_version": 1,
            "seed": seed,
            "source": {
                "dataset": str(source),
                "split_manifest": str(source_split_manifest),
                "audit_manifest": str(audit_manifest),
            },
            "balancing": {
                "target_per_profile": target_per_profile,
                "max_repeats": max_repeats,
                "train_profile_counts": dict(sorted(profile_counts.items())),
            },
            "counts": {
                "total": len(derived_assignments),
                "train": len(split_indices["train"]),
                "validation": len(split_indices["validation"]),
                "heldout": len(split_indices["heldout"]),
                "frames": global_index,
                "tasks": len(tasks),
            },
            "lerobot": {
                # LeRobot stratifies eval_split independently per language task.
                # With 23 tasks that would change the frozen 135/24 boundary,
                # so training receives only the derived train indices.
                "episodes": split_indices["train"],
                "eval_split": 0.0,
                "validation_episodes": split_indices["validation"],
                "heldout_episodes": split_indices["heldout"],
            },
            "assignments": derived_assignments,
        }
        output_split_manifest.parent.mkdir(parents=True, exist_ok=True)
        output_split_manifest.write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        (destination / "CONDITIONED_BALANCE_MANIFEST.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        return manifest
    except Exception:
        if destination.exists():
            shutil.rmtree(destination)
        raise


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Create a task-conditioned, profile-balanced LeRobot dataset"
    )
    parser.add_argument("source", type=Path)
    parser.add_argument("destination", type=Path)
    parser.add_argument("--source-split", required=True, type=Path)
    parser.add_argument("--audit-manifest", required=True, type=Path)
    parser.add_argument("--output-split", required=True, type=Path)
    parser.add_argument("--target-per-profile", type=int, default=12)
    parser.add_argument("--max-repeats", type=int, default=3)
    parser.add_argument("--seed", type=int, default=11)
    args = parser.parse_args()
    result = build(
        args.source,
        args.destination,
        source_split_manifest=args.source_split,
        audit_manifest=args.audit_manifest,
        output_split_manifest=args.output_split,
        target_per_profile=args.target_per_profile,
        max_repeats=args.max_repeats,
        seed=args.seed,
    )
    print(json.dumps(result["counts"], ensure_ascii=False, indent=2))
    print(json.dumps(result["balancing"], ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
