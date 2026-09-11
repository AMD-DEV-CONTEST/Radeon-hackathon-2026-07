#!/usr/bin/env python3
"""Derive the exact 18-row PI0.5 tiny-overfit contract dataset."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import shutil
from typing import Any, Mapping

from parcel_sorter.mobile_pi05_contract import PI05_GRASP_MODES
from parcel_sorter.mobile_pi05_research_protocol import (
    PI05_TASK_STAGES,
    PI05_TINY_OVERFIT_ROLE,
    build_stage_panel,
    file_sha256,
    validate_stage_panel,
)


GENERATED_FEATURES = {
    "timestamp",
    "frame_index",
    "episode_index",
    "index",
    "task_index",
}
EXPECTED_ROWS = len(PI05_GRASP_MODES) * len(PI05_TASK_STAGES)
QUANTILES = {
    "q01": 0.01,
    "q10": 0.10,
    "q50": 0.50,
    "q90": 0.90,
    "q99": 0.99,
}


def validate_source_panel(panel: Mapping[str, Any], source_root: Path) -> list[dict[str, Any]]:
    """Require one and only one source row for every mode-stage cell."""

    audit = validate_stage_panel(panel, expected_role=PI05_TINY_OVERFIT_ROLE)
    if Path(str(panel.get("dataset_root"))).resolve() != source_root.resolve():
        raise ValueError("tiny-overfit source panel points at a different dataset")
    observations = [dict(item) for item in panel.get("observations") or ()]
    if audit["observations"] != EXPECTED_ROWS or len(observations) != EXPECTED_ROWS:
        raise ValueError(f"tiny-overfit source panel must contain exactly {EXPECTED_ROWS} rows")
    cells = [(str(item["grasp_mode"]), str(item["stage"])) for item in observations]
    expected = {
        (mode, stage) for mode in PI05_GRASP_MODES for stage in PI05_TASK_STAGES
    }
    if set(cells) != expected or len(cells) != len(set(cells)):
        raise ValueError("tiny-overfit source panel must contain each mode-stage cell once")
    indices = [int(item["dataset_index"]) for item in observations]
    if len(indices) != len(set(indices)):
        raise ValueError("tiny-overfit source panel contains repeated dataset rows")
    return observations


def remap_tiny_observations(
    observations: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Bind source identities to deterministic one-frame output episodes."""

    result = []
    for output_index, item in enumerate(observations):
        result.append(
            {
                **item,
                "source_dataset_index": int(item["dataset_index"]),
                "source_episode_index": int(item["episode_index"]),
                "dataset_index": output_index,
                "episode_index": output_index,
                "observation_id": f"tiny-overfit-{output_index:02d}",
            }
        )
    return result


def _manifest_path(root: Path) -> Path:
    matches = [
        path
        for path in (
            root / "PI05_ABSOLUTE_DATASET_MANIFEST.json",
            root / "PI05_RESIDUAL_DATASET_MANIFEST.json",
            root / "PI05_INCREMENTAL_DATASET_MANIFEST.json",
        )
        if path.is_file()
    ]
    if len(matches) != 1:
        raise ValueError("source dataset must contain exactly one PI0.5 manifest")
    return matches[0]


def _array(value: Any) -> Any:
    import numpy as np

    if hasattr(value, "detach"):
        value = value.detach().cpu().numpy()
    return np.asarray(value)


def _task_text(value: Any) -> str:
    if isinstance(value, (list, tuple)) and len(value) == 1:
        value = value[0]
    result = str(value)
    if not result.strip():
        raise ValueError("selected source frame has empty task text")
    return result


def _writer_value(value: Any, feature: Mapping[str, Any]) -> Any:
    import numpy as np

    array = _array(value)
    if feature.get("dtype") == "image":
        if array.ndim == 3 and array.shape[0] in {1, 3, 4}:
            array = np.moveaxis(array, 0, -1)
        is_depth = bool((feature.get("info") or {}).get("is_depth_map"))
        if is_depth:
            return array.astype(np.float32, copy=False)
        if np.issubdtype(array.dtype, np.floating):
            array = np.rint(np.clip(array, 0.0, 1.0) * 255.0)
        return array.astype(np.uint8, copy=False)
    dtype = str(feature.get("dtype") or "")
    if dtype.startswith("float"):
        array = array.astype(np.float32, copy=False)
    if dtype.startswith("int"):
        array = array.astype(np.int64, copy=False)
    expected_shape = tuple(int(value) for value in feature.get("shape") or ())
    if expected_shape and array.shape != expected_shape:
        if array.size != int(np.prod(expected_shape)):
            raise ValueError(
                f"feature shape mismatch: observed={array.shape}, expected={expected_shape}"
            )
        array = array.reshape(expected_shape)
    return array


def _content_sha256(frame: Mapping[str, Any], feature_names: list[str]) -> str:
    digest = hashlib.sha256()
    for name in sorted(feature_names):
        array = _array(frame[name])
        digest.update(name.encode("utf-8"))
        digest.update(str(array.dtype).encode("ascii"))
        digest.update(json.dumps(list(array.shape)).encode("ascii"))
        digest.update(array.tobytes(order="C"))
    digest.update(_task_text(frame["task"]).encode("utf-8"))
    return digest.hexdigest()


def vector_stats(rows: list[Any]) -> dict[str, list[float | int]]:
    """Compute true global vector statistics instead of aggregating one-row quantiles."""

    import numpy as np

    values = np.stack([_array(row).reshape(-1) for row in rows]).astype(np.float64)
    result: dict[str, list[float | int]] = {
        "min": values.min(axis=0).tolist(),
        "max": values.max(axis=0).tolist(),
        "mean": values.mean(axis=0).tolist(),
        "std": values.std(axis=0).tolist(),
        "count": [int(values.shape[0])],
    }
    result.update(
        {
            name: np.quantile(values, quantile, axis=0).tolist()
            for name, quantile in QUANTILES.items()
        }
    )
    return result


def build_dataset(source_root: Path, panel_path: Path, output_root: Path) -> dict[str, Any]:
    try:
        from lerobot.datasets.lerobot_dataset import LeRobotDataset
    except ImportError as exc:
        raise RuntimeError("LeRobot is required to derive the tiny-overfit dataset") from exc

    source_root = source_root.resolve()
    output_root = output_root.resolve()
    if output_root.exists():
        raise FileExistsError(f"output dataset already exists: {output_root}")
    panel = json.loads(panel_path.read_text(encoding="utf-8"))
    observations = validate_source_panel(panel, source_root)
    source_manifest_path = _manifest_path(source_root)
    if file_sha256(source_manifest_path) != panel["dataset_manifest_sha256"]:
        raise ValueError("source panel fingerprint does not match the source manifest")
    source_manifest = json.loads(source_manifest_path.read_text(encoding="utf-8"))
    if source_manifest.get("action_contract") != "absolute_v1":
        raise ValueError("tiny-overfit contract dataset requires absolute_v1 actions")
    source_info = json.loads((source_root / "meta/info.json").read_text(encoding="utf-8"))
    source_features = dict(source_info.get("features") or {})
    features = {
        name: {
            **definition,
            "shape": tuple(definition.get("shape") or ()),
        }
        for name, definition in source_features.items()
        if name not in GENERATED_FEATURES
    }
    required = {"observation.state", "action"}
    if not required <= set(features):
        raise ValueError("source dataset lacks state or action features")

    source = LeRobotDataset(
        "local/mobile-bimanual-parcel-expert",
        root=source_root,
    )
    output = LeRobotDataset.create(
        repo_id="local/mobile-pi05-tiny-overfit-contract",
        root=output_root,
        fps=int(source_info["fps"]),
        features=features,
        robot_type=str(source_info.get("robot_type") or "mobile_bi_franka_sim"),
        use_videos=False,
        image_writer_threads=4,
    )
    remapped = remap_tiny_observations(observations)
    row_records = []
    normalization_rows: dict[str, list[Any]] = {
        "observation.state": [],
        "action": [],
    }
    for item in remapped:
        source_index = int(item["source_dataset_index"])
        if not 0 <= source_index < len(source):
            raise ValueError(f"source dataset index is out of range: {source_index}")
        frame = source[source_index]
        frame_episode = frame["episode_index"]
        if hasattr(frame_episode, "item"):
            frame_episode = frame_episode.item()
        if int(frame_episode) != int(item["source_episode_index"]):
            raise ValueError("source panel episode does not match the selected frame")
        payload = {
            name: _writer_value(frame[name], definition)
            for name, definition in features.items()
        }
        payload["task"] = _task_text(frame["task"])
        for feature_name in normalization_rows:
            normalization_rows[feature_name].append(payload[feature_name])
        content_sha256 = _content_sha256(
            frame,
            [
                "observation.state",
                "action",
                *list(source_manifest.get("policy_visual_keys") or ()),
            ],
        )
        output.add_frame(payload)
        output.save_episode()
        row_records.append(
            {
                "output_index": int(item["dataset_index"]),
                "source_dataset_index": source_index,
                "source_episode_index": int(item["source_episode_index"]),
                "source_identity": item["source_identity"],
                "grasp_mode": item["grasp_mode"],
                "stage": item["stage"],
                "content_sha256": content_sha256,
            }
        )

    stats_path = output_root / "meta/stats.json"
    stats = json.loads(stats_path.read_text(encoding="utf-8"))
    for feature_name, rows in normalization_rows.items():
        stats[feature_name] = vector_stats(rows)
    stats_path.write_text(
        json.dumps(stats, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )

    output_info = json.loads((output_root / "meta/info.json").read_text(encoding="utf-8"))
    if int(output_info.get("total_frames", -1)) != EXPECTED_ROWS:
        raise RuntimeError("derived dataset did not produce exactly 18 frames")
    if int(output_info.get("total_episodes", -1)) != EXPECTED_ROWS:
        raise RuntimeError("derived dataset did not produce 18 one-frame episodes")

    nonzero_base_frames = 0
    for item in remapped:
        action = _array(source[int(item["source_dataset_index"])]["action"]).reshape(-1)
        nonzero_base_frames += int(any(abs(float(value)) > 1e-8 for value in action[:3]))
    episode_manifests = [
        {
            "episode_index": int(item["dataset_index"]),
            "source_dataset": str(source_root),
            "source_dataset_index": int(item["source_dataset_index"]),
            "source_episode_index": int(item["source_episode_index"]),
            "source_identity": str(item["source_identity"]),
            "grasp_modes": [str(item["grasp_mode"])],
            "stages": [str(item["stage"])],
            "seed_role": "tiny_overfit_contract_sample",
        }
        for item in remapped
    ]
    manifest = {
        **source_manifest,
        "schema_version": 1,
        "protocol": "pi05-absolute-tiny-overfit-dataset-v1",
        "dataset_role": "tiny_overfit_contract_only",
        "action_contract": "absolute_v1",
        "source_dataset": str(source_root),
        "source_dataset_manifest": str(source_manifest_path),
        "source_dataset_manifest_sha256": file_sha256(source_manifest_path),
        "source_stage_panel": str(panel_path.resolve()),
        "source_stage_panel_sha256": file_sha256(panel_path),
        "total_frames": EXPECTED_ROWS,
        "total_episodes": EXPECTED_ROWS,
        "mode_stage_cells": EXPECTED_ROWS,
        "one_frame_per_episode": True,
        "episode_manifests": episode_manifests,
        "selected_rows": row_records,
        "nonzero_base_command_frames": nonzero_base_frames,
        "performance_data": False,
        "claim_boundary": (
            "Action-pipeline memorization contract only; this dataset and its scores "
            "must never be reported as held-out or closed-loop performance."
        ),
    }
    manifest_path = output_root / "PI05_ABSOLUTE_DATASET_MANIFEST.json"
    manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    output_panel = build_stage_panel(
        remapped,
        role=PI05_TINY_OVERFIT_ROLE,
        dataset_root=output_root,
        dataset_manifest_sha256=file_sha256(manifest_path),
        minimum_observations_per_mode_stage=1,
        minimum_independent_sources_per_mode=1,
    )
    output_panel_path = output_root / "PI05_TINY_OVERFIT_PANEL.json"
    output_panel_path.write_text(
        json.dumps(output_panel, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    summary = {
        "status": "passed",
        "protocol": "pi05-tiny-overfit-dataset-build-audit-v1",
        "dataset_root": str(output_root),
        "frames": EXPECTED_ROWS,
        "episodes": EXPECTED_ROWS,
        "mode_stage_cells": EXPECTED_ROWS,
        "manifest": str(manifest_path),
        "manifest_sha256": file_sha256(manifest_path),
        "panel": str(output_panel_path),
        "panel_sha256": output_panel["panel_sha256"],
        "stats_sha256": file_sha256(stats_path),
        "performance_data": False,
    }
    (output_root / "TINY_OVERFIT_BUILD_AUDIT.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-dataset", type=Path, required=True)
    parser.add_argument("--source-panel", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    output_existed = args.output.exists()
    try:
        summary = build_dataset(args.source_dataset, args.source_panel, args.output)
    except (FileExistsError, OSError, RuntimeError, ValueError, json.JSONDecodeError) as exc:
        if not output_existed and args.output.exists():
            shutil.rmtree(args.output)
        parser.error(str(exc))
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
