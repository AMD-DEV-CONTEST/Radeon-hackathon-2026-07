#!/usr/bin/env python3
"""Encode observable PI0.5 state as mode-blind per-frame task language."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
from typing import Any

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq

from parcel_sorter.mobile_pi05_contract import (
    build_pi05_observable_context_task,
    decode_pi05_context,
)


QUANTILES = {"q01": 0.01, "q10": 0.10, "q50": 0.50, "q90": 0.90, "q99": 0.99}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _replace_column(table: Any, name: str, values: list[Any]) -> Any:
    index = table.schema.get_field_index(name)
    if index < 0:
        raise ValueError(f"missing parquet column: {name}")
    return table.set_column(
        index,
        name,
        pa.array(values, type=table.schema.field(index).type),
    )


def _write_parquet_replacing(table: Any, path: Path) -> None:
    """Replace a hard-linked destination without modifying the source inode."""

    temporary = path.with_name(f".{path.name}.tmp")
    pq.write_table(table, temporary, compression="zstd")
    temporary.replace(path)


def _write_text_replacing(path: Path, text: str) -> None:
    """Atomically replace writable metadata copied via hard links."""

    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(text, encoding="utf-8")
    temporary.replace(path)


def _dataset_manifest(source: Path) -> Path:
    paths = [
        path
        for path in (
            source / "PI05_RESIDUAL_DATASET_MANIFEST.json",
            source / "PI05_ABSOLUTE_DATASET_MANIFEST.json",
        )
        if path.is_file()
    ]
    if len(paths) != 1:
        raise ValueError(f"expected one PI0.5 dataset manifest in {source}")
    return paths[0]


def _mutable_source_hashes(source: Path) -> dict[str, str]:
    paths = [
        _dataset_manifest(source),
        source / "meta/info.json",
        source / "meta/stats.json",
        source / "meta/tasks.parquet",
        *sorted((source / "meta/episodes").rglob("*.parquet")),
        *sorted((source / "data").rglob("*.parquet")),
    ]
    return {
        str(path.relative_to(source)).replace("\\", "/"): _sha256(path)
        for path in paths
    }


def _scalar_stats(values: list[int]) -> dict[str, list[float]]:
    array = np.asarray(values, dtype=np.float64)
    result = {
        "count": [len(values)],
        "min": [float(array.min())],
        "max": [float(array.max())],
        "mean": [float(array.mean())],
        "std": [float(array.std())],
    }
    result.update(
        {name: [float(np.quantile(array, quantile))] for name, quantile in QUANTILES.items()}
    )
    return result


def build(source: Path, destination: Path) -> dict[str, Any]:
    source = source.resolve()
    destination = destination.resolve()
    if destination.exists():
        raise FileExistsError(f"destination already exists: {destination}")
    manifest_path = _dataset_manifest(source)
    source_hashes = _mutable_source_hashes(source)
    try:
        shutil.copytree(source, destination, copy_function=os.link)
    except OSError:
        if destination.exists():
            shutil.rmtree(destination)
        shutil.copytree(source, destination, copy_function=shutil.copy2)

    try:
        source_tasks = pq.read_table(source / "meta/tasks.parquet")
        task_by_index = {
            int(row["task_index"]): str(row["task"])
            for row in source_tasks.to_pylist()
        }
        data_paths = sorted((source / "data").rglob("*.parquet"))
        tables: list[tuple[Path, Any, list[str]]] = []
        task_texts: set[str] = set()
        for path in data_paths:
            table = pq.read_table(path)
            texts = []
            for row in table.select(["task_index", "observation.state"]).to_pylist():
                context = decode_pi05_context(row["observation.state"])
                text = build_pi05_observable_context_task(
                    task_by_index[int(row["task_index"])], context
                )
                texts.append(text)
                task_texts.add(text)
            tables.append((path, table, texts))

        ordered_tasks = sorted(task_texts)
        task_index_by_text = {text: index for index, text in enumerate(ordered_tasks)}
        episode_task_indices: dict[int, list[int]] = {}
        all_task_indices: list[int] = []
        for source_path, table, texts in tables:
            indices = [task_index_by_text[text] for text in texts]
            rewritten = _replace_column(table, "task_index", indices)
            output_path = destination / source_path.relative_to(source)
            _write_parquet_replacing(rewritten, output_path)
            all_task_indices.extend(indices)
            for episode, task_index in zip(
                table["episode_index"].to_pylist(), indices, strict=True
            ):
                values = episode_task_indices.setdefault(int(episode), [])
                if task_index not in values:
                    values.append(task_index)

        task_table = pa.Table.from_arrays(
            [
                pa.array(range(len(ordered_tasks)), type=source_tasks.schema.field("task_index").type),
                pa.array(ordered_tasks, type=source_tasks.schema.field("task").type),
            ],
            schema=source_tasks.schema,
        )
        _write_parquet_replacing(task_table, destination / "meta/tasks.parquet")

        for source_path in sorted((source / "meta/episodes").rglob("*.parquet")):
            table = pq.read_table(source_path)
            rows = table.to_pylist()
            task_lists = []
            stat_values: dict[str, list[Any]] = {}
            for row in rows:
                indices = episode_task_indices[int(row["episode_index"])]
                task_lists.append([ordered_tasks[index] for index in indices])
                stats = _scalar_stats(indices)
                for name, value in stats.items():
                    stat_values.setdefault(f"stats/task_index/{name}", []).append(value)
            table = _replace_column(table, "tasks", task_lists)
            for name, values in stat_values.items():
                if table.schema.get_field_index(name) >= 0:
                    table = _replace_column(table, name, values)
            output_path = destination / source_path.relative_to(source)
            _write_parquet_replacing(table, output_path)

        info_path = destination / "meta/info.json"
        info = json.loads(info_path.read_text(encoding="utf-8"))
        info["total_tasks"] = len(ordered_tasks)
        _write_text_replacing(info_path, json.dumps(info, indent=2) + "\n")
        stats_path = destination / "meta/stats.json"
        stats = json.loads(stats_path.read_text(encoding="utf-8"))
        stats["task_index"] = _scalar_stats(all_task_indices)
        _write_text_replacing(stats_path, json.dumps(stats, indent=2) + "\n")

        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if _mutable_source_hashes(source) != source_hashes:
            raise RuntimeError("source dataset changed while contextualizing task language")
        manifest.update(
            {
                "protocol": "pash-pi05-observable-language-v1",
                "source_dataset": str(source),
                "output_dataset": str(destination),
                "task_language_policy": "observable_context_mode_blind_v1",
                "observable_language_fields": [
                    "parcel_shape",
                    "parcel_size_m",
                    "parcel_mass_kg",
                    "stage",
                    "retry_index",
                ],
                "tasks": len(ordered_tasks),
                "task_metadata_sha256": _sha256(destination / "meta/tasks.parquet"),
                "source_integrity": {
                    "status": "passed",
                    "mutable_file_sha256": source_hashes,
                },
                "output_data_sha256": {
                    str(path.relative_to(destination)).replace("\\", "/"): _sha256(path)
                    for path in sorted(destination.glob("data/**/*.parquet"))
                },
                "claim_boundary": (
                    "Observable state is rendered as mode-blind language for LeRobot PI0.5; "
                    "no grasp-mode label is present in policy inputs."
                ),
            }
        )
        _write_text_replacing(
            destination / manifest_path.name,
            json.dumps(manifest, indent=2) + "\n",
        )
        return {
            "dataset": str(destination),
            "frames": len(all_task_indices),
            "tasks": len(ordered_tasks),
            "episodes": len(episode_task_indices),
            "task_language_policy": manifest["task_language_policy"],
        }
    except Exception:
        if destination.exists():
            shutil.rmtree(destination)
        raise


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("destination", type=Path)
    args = parser.parse_args()
    print(json.dumps(build(args.source, args.destination), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
