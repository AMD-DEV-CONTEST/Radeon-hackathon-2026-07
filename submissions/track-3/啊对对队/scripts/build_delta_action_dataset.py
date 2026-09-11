#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
from typing import Any


EE_POSITION_SLICE = slice(9, 12)
ACTION_WIDTH = 8


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _stats(values: Any) -> dict[str, list[float] | list[int]]:
    import numpy as np

    return {
        "min": values.min(axis=0).astype(float).tolist(),
        "max": values.max(axis=0).astype(float).tolist(),
        "mean": values.mean(axis=0, dtype=np.float64).tolist(),
        "std": values.std(axis=0, dtype=np.float64).tolist(),
        "count": [int(values.shape[0])],
        "q01": np.quantile(values, 0.01, axis=0).astype(float).tolist(),
        "q10": np.quantile(values, 0.10, axis=0).astype(float).tolist(),
        "q50": np.quantile(values, 0.50, axis=0).astype(float).tolist(),
        "q90": np.quantile(values, 0.90, axis=0).astype(float).tolist(),
        "q99": np.quantile(values, 0.99, axis=0).astype(float).tolist(),
    }


def build(source: Path, destination: Path) -> dict[str, Any]:
    import numpy as np
    import pyarrow as pa
    import pyarrow.parquet as pq

    source = source.resolve()
    destination = destination.resolve()
    if destination.exists():
        raise FileExistsError(f"destination already exists: {destination}")
    info_path = source / "meta" / "info.json"
    stats_path = source / "meta" / "stats.json"
    if not info_path.is_file() or not stats_path.is_file():
        raise FileNotFoundError("source is not a LeRobot dataset")

    source_info_sha256 = _sha256(info_path)
    source_stats_sha256 = _sha256(stats_path)
    try:
        shutil.copytree(source, destination, copy_function=os.link)
        copy_mode = "hardlink_then_replace_numeric_parquet"
        for relative in (Path("meta/info.json"), Path("meta/stats.json")):
            derived_metadata = destination / relative
            derived_metadata.unlink()
            shutil.copy2(source / relative, derived_metadata)
    except OSError:
        if destination.exists():
            shutil.rmtree(destination)
        shutil.copytree(source, destination, copy_function=shutil.copy2)
        copy_mode = "full_copy"

    action_batches = []
    parquet_hashes: dict[str, str] = {}
    for path in sorted((destination / "data").rglob("*.parquet")):
        table = pq.read_table(path)
        actions = np.asarray(table["action"].to_pylist(), dtype=np.float32)
        states = np.asarray(table["observation.state"].to_pylist(), dtype=np.float32)
        if actions.ndim != 2 or actions.shape[1] != ACTION_WIDTH:
            raise ValueError(f"unexpected action shape in {path}: {actions.shape}")
        if states.ndim != 2 or states.shape[1] < EE_POSITION_SLICE.stop:
            raise ValueError(f"unexpected state shape in {path}: {states.shape}")
        actions[:, :3] -= states[:, EE_POSITION_SLICE]
        action_batches.append(actions.copy())
        flat = pa.array(actions.reshape(-1), type=pa.float32())
        column = pa.FixedSizeListArray.from_arrays(flat, ACTION_WIDTH)
        action_index = table.schema.get_field_index("action")
        transformed = table.set_column(action_index, table.schema.field(action_index), column)
        temporary = path.with_suffix(".parquet.tmp")
        pq.write_table(transformed, temporary)
        temporary.replace(path)
        parquet_hashes[str(path.relative_to(destination)).replace("\\", "/")] = _sha256(path)

    all_actions = np.concatenate(action_batches, axis=0)
    info = json.loads((destination / "meta" / "info.json").read_text(encoding="utf-8"))
    info["features"]["action"]["names"] = [
        "delta_x",
        "delta_y",
        "delta_z",
        "qw",
        "qx",
        "qy",
        "qz",
        "gripper",
    ]
    (destination / "meta" / "info.json").write_text(
        json.dumps(info, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    stats = json.loads((destination / "meta" / "stats.json").read_text(encoding="utf-8"))
    stats["action"] = _stats(all_actions)
    (destination / "meta" / "stats.json").write_text(
        json.dumps(stats, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    manifest = {
        "schema_version": "1.0",
        "transformation": "delta_xyz_absolute_quaternion_gripper",
        "source": str(source),
        "destination": str(destination),
        "source_info_sha256": source_info_sha256,
        "source_stats_sha256": source_stats_sha256,
        "copy_mode": copy_mode,
        "frame_count": int(all_actions.shape[0]),
        "state_ee_position_indices": [9, 10, 11],
        "action_delta_indices": [0, 1, 2],
        "unchanged_action_indices": [3, 4, 5, 6, 7],
        "parquet_sha256": parquet_hashes,
    }
    (destination / "DELTA_ACTION_MANIFEST.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    if _sha256(info_path) != source_info_sha256 or _sha256(stats_path) != source_stats_sha256:
        raise RuntimeError("source metadata changed while building the derived dataset")
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Create a derived LeRobot dataset with delta XYZ actions."
    )
    parser.add_argument("source", type=Path)
    parser.add_argument("destination", type=Path)
    args = parser.parse_args()
    result = build(args.source, args.destination)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
