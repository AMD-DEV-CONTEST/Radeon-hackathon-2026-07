"""Train-only normalization statistics for the balanced parcel dataset."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sys
from typing import Any

import numpy as np

from .mobile_stratified_sampler import load_sampling_manifest


TRAIN_STATS_PROTOCOL = "parcel-balanced-train-normalization-v1"
POLICY_NORMALIZED_FEATURES = ("observation.state", "action")
QUANTILES = (0.01, 0.10, 0.50, 0.90, 0.99)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _payload_sha256(payload: Any) -> str:
    value = json.dumps(
        payload, ensure_ascii=True, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(value).hexdigest()


def _jsonable(value: Any) -> Any:
    if isinstance(value, np.ndarray):
        return value.tolist()
    if isinstance(value, np.generic):
        return value.item()
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    return value


def _fixed_list_numpy(table: Any, name: str, width: int) -> np.ndarray:
    column = table[name].combine_chunks()
    values = getattr(column, "values", None)
    if values is not None:
        array = np.asarray(values.to_numpy(zero_copy_only=False))
        if array.size == len(column) * width:
            return array.reshape(len(column), width)
    array = np.asarray(column.to_pylist())
    if array.shape != (len(column), width):
        raise ValueError(f"{name} does not match its declared width {width}")
    return array


def _balanced_normalization_indices(manifest: dict[str, Any]) -> list[int]:
    seed = int(manifest["seed"])
    samples_per_cell = int(manifest["samples_per_design_cell_per_epoch"])
    selected: list[int] = []
    for cell, values in sorted(manifest["indices_by_design_cell"].items()):
        ordered = sorted(
            (int(value) for value in values),
            key=lambda index: hashlib.sha256(
                f"{seed}:normalization:{cell}:{index}".encode("utf-8")
            ).hexdigest(),
        )
        if len(ordered) < samples_per_cell:
            raise ValueError(f"normalization pool is too small for {cell}")
        selected.extend(ordered[:samples_per_cell])
    if len(selected) != int(manifest["samples_per_epoch"]):
        raise ValueError("balanced normalization index count does not match sampler epoch")
    if len(selected) != len(set(selected)):
        raise ValueError("balanced normalization indices are not unique")
    return sorted(selected)


def build_train_only_normalization_stats(
    *,
    dataset_root: str | Path,
    split_manifest_path: str | Path,
    sampling_manifest_path: str | Path,
    output_stats: str | Path,
    output_manifest: str | Path,
) -> dict[str, Any]:
    """Compute policy stats from the balanced train frames, never held-out frames."""

    import pyarrow.parquet as pq
    from lerobot.datasets.compute_stats import get_feature_stats
    from lerobot.datasets.io_utils import cast_stats_to_numpy

    root = Path(dataset_root).resolve()
    split_path = Path(split_manifest_path).resolve()
    sampling_path = Path(sampling_manifest_path).resolve()
    output_stats_path = Path(output_stats)
    output_manifest_path = Path(output_manifest)
    info_path = root / "meta" / "info.json"
    global_stats_path = root / "meta" / "stats.json"
    data_files = sorted((root / "data").rglob("*.parquet"))
    if not info_path.is_file() or not global_stats_path.is_file() or not data_files:
        raise ValueError("dataset is missing info, global stats, or parquet data")
    split = json.loads(split_path.read_text(encoding="utf-8"))
    if split.get("counts") != {
        "total": 1500,
        "train": 1200,
        "development": 150,
        "confirmation": 150,
    }:
        raise ValueError("train-only stats require the frozen 1,200/150/150 split")
    if split.get("source", {}).get("dataset_info_sha256") != _sha256(info_path):
        raise ValueError("split manifest does not match dataset metadata")
    sampling = load_sampling_manifest(sampling_path)
    source = sampling.get("source") or {}
    if source.get("dataset_info_sha256") != _sha256(info_path):
        raise ValueError("sampling manifest does not match dataset metadata")
    if source.get("split_manifest_sha256") != _sha256(split_path):
        raise ValueError("sampling manifest does not match the frozen split")

    info = json.loads(info_path.read_text(encoding="utf-8"))
    features = info.get("features") or {}
    widths = {
        name: int(features[name]["shape"][0]) for name in POLICY_NORMALIZED_FEATURES
    }
    selected = _balanced_normalization_indices(sampling)
    selected_array = np.asarray(selected, dtype=np.int64)
    arrays: dict[str, list[np.ndarray]] = {name: [] for name in widths}
    observed_indices: list[np.ndarray] = []
    for path in data_files:
        table = pq.read_table(path, columns=["index", *widths])
        frame_indices = np.asarray(
            table["index"].combine_chunks().to_numpy(), dtype=np.int64
        )
        mask = np.isin(frame_indices, selected_array, assume_unique=False)
        if not np.any(mask):
            continue
        observed_indices.append(frame_indices[mask])
        for name, width in widths.items():
            arrays[name].append(_fixed_list_numpy(table, name, width)[mask])
    if not observed_indices:
        raise ValueError("none of the balanced train frames were found in parquet data")
    observed = np.concatenate(observed_indices)
    if len(observed) != len(selected) or set(observed.tolist()) != set(selected):
        raise ValueError("balanced train frames are missing or duplicated in parquet data")

    global_stats = cast_stats_to_numpy(
        json.loads(global_stats_path.read_text(encoding="utf-8"))
    )
    for name, parts in arrays.items():
        values = np.concatenate(parts, axis=0)
        global_stats[name] = get_feature_stats(
            values,
            axis=0,
            keepdims=False,
            quantile_list=list(QUANTILES),
        )
    serialized = _jsonable(global_stats)
    output_stats_path.parent.mkdir(parents=True, exist_ok=True)
    output_stats_path.write_text(
        json.dumps(serialized, indent=2) + "\n", encoding="utf-8"
    )
    payload: dict[str, Any] = {
        "schema_version": 1,
        "protocol": TRAIN_STATS_PROTOCOL,
        "dataset_root": str(root),
        "dataset_info_sha256": _sha256(info_path),
        "dataset_global_stats_sha256": _sha256(global_stats_path),
        "split_manifest": str(split_path),
        "split_manifest_sha256": _sha256(split_path),
        "sampling_manifest": str(sampling_path),
        "sampling_manifest_file_sha256": _sha256(sampling_path),
        "sampling_manifest_sha256": sampling["manifest_sha256"],
        "normalization_stats": str(output_stats_path.resolve()),
        "normalization_stats_sha256": _sha256(output_stats_path),
        "normalization_frame_count": len(selected),
        "normalization_frames_per_design_cell": int(
            sampling["samples_per_design_cell_per_epoch"]
        ),
        "normalization_frame_indices_sha256": _payload_sha256(selected),
        "policy_normalized_features": list(POLICY_NORMALIZED_FEATURES),
        "copied_global_stats_features": sorted(
            set(serialized) - set(POLICY_NORMALIZED_FEATURES)
        ),
        "held_out_frame_count": 0,
        "normalization_policy": (
            "equal grasp mode and design cell probability; at most 100 unique "
            "frames per episode stage; train split only"
        ),
    }
    payload["manifest_sha256"] = _payload_sha256(payload)
    output_manifest_path.parent.mkdir(parents=True, exist_ok=True)
    output_manifest_path.write_text(
        json.dumps(payload, indent=2) + "\n", encoding="utf-8"
    )
    return payload


def load_train_only_normalization_stats(
    *,
    stats_path: str | Path,
    manifest_path: str | Path,
    sampling_manifest_path: str | Path,
) -> dict[str, dict[str, np.ndarray]]:
    from lerobot.datasets.io_utils import cast_stats_to_numpy

    stats_path = Path(stats_path).resolve()
    manifest_path = Path(manifest_path).resolve()
    sampling_path = Path(sampling_manifest_path).resolve()
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    unsigned = dict(manifest)
    claimed = str(unsigned.pop("manifest_sha256", ""))
    if claimed != _payload_sha256(unsigned):
        raise ValueError("train-only normalization manifest fingerprint mismatch")
    if manifest.get("protocol") != TRAIN_STATS_PROTOCOL:
        raise ValueError("train-only normalization protocol mismatch")
    sampling = load_sampling_manifest(sampling_path)
    if manifest.get("normalization_stats_sha256") != _sha256(stats_path):
        raise ValueError("train-only normalization stats hash mismatch")
    if manifest.get("sampling_manifest_file_sha256") != _sha256(sampling_path):
        raise ValueError("train-only stats sampling file hash mismatch")
    if manifest.get("sampling_manifest_sha256") != sampling["manifest_sha256"]:
        raise ValueError("train-only stats sampling content hash mismatch")
    if int(manifest.get("held_out_frame_count", -1)) != 0:
        raise ValueError("train-only normalization includes held-out frames")
    stats = cast_stats_to_numpy(json.loads(stats_path.read_text(encoding="utf-8")))
    if any(name not in stats for name in POLICY_NORMALIZED_FEATURES):
        raise ValueError("train-only normalization lacks policy features")
    return stats


def install_train_stats_override(
    *,
    stats_path: str | Path,
    manifest_path: str | Path,
    sampling_manifest_path: str | Path,
) -> Any:
    """Install a LeRobot dataset factory wrapper using train-only stats."""

    import lerobot.datasets as datasets_module
    from lerobot.datasets import factory as factory_module

    stats = load_train_only_normalization_stats(
        stats_path=stats_path,
        manifest_path=manifest_path,
        sampling_manifest_path=sampling_manifest_path,
    )
    original = factory_module.make_train_eval_datasets

    def make_train_eval_datasets_with_train_stats(cfg: Any) -> tuple[Any, Any]:
        train_dataset, eval_dataset = original(cfg)
        train_dataset.meta.stats = stats
        if eval_dataset is not None:
            eval_dataset.meta.stats = stats
        return train_dataset, eval_dataset

    make_train_eval_datasets_with_train_stats.__name__ = (
        "make_train_eval_datasets_with_parcel_train_stats"
    )
    factory_module.make_train_eval_datasets = make_train_eval_datasets_with_train_stats
    datasets_module.make_train_eval_datasets = make_train_eval_datasets_with_train_stats
    train_module = sys.modules.get("lerobot.scripts.lerobot_train")
    if train_module is not None:
        train_module.make_train_eval_datasets = make_train_eval_datasets_with_train_stats
    return make_train_eval_datasets_with_train_stats
