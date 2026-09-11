"""Deterministic mode/cell-balanced frame sampling for parcel PI0.5 training."""

from __future__ import annotations

from collections import Counter, defaultdict
import hashlib
import json
from pathlib import Path
import sys
from typing import Any, Iterable, Iterator

import numpy as np


SAMPLING_PROTOCOL = "parcel-mode-cell-stage-cap-sampler-v1"
STAGE_COUNT = 6
DESIGN_CELL_COUNT = 24


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _stable_key(seed: int, *parts: object) -> str:
    value = ":".join(str(part) for part in (seed, *parts)).encode("utf-8")
    return hashlib.sha256(value).hexdigest()


def _scalar_int(value: Any, *, field: str) -> int:
    """Accept scalar Arrow values and legacy one-element vector fields."""

    if isinstance(value, np.ndarray):
        value = value.tolist()
    if isinstance(value, (list, tuple)):
        if len(value) != 1:
            raise ValueError(f"{field} must be scalar or length one")
        value = value[0]
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field} is not an integer scalar: {value!r}") from exc


def build_sampling_manifest(
    *,
    frame_rows: Iterable[dict[str, Any]],
    split_manifest: dict[str, Any],
    seed: int = 20260729,
    stage_frame_cap_per_episode: int = 100,
) -> dict[str, Any]:
    """Build capped frame pools for exact design-cell-balanced sampling."""

    if stage_frame_cap_per_episode < 1:
        raise ValueError("stage frame cap must be positive")
    assignments = split_manifest.get("assignments")
    if not isinstance(assignments, list):
        raise ValueError("split manifest lacks assignments")
    train_assignments = {
        int(item["dataset_episode_index"]): item
        for item in assignments
        if item.get("split") == "train"
    }
    if len(train_assignments) != 1200:
        raise ValueError("sampling manifest requires exactly 1,200 train episodes")

    by_episode_stage: dict[tuple[int, int], list[int]] = defaultdict(list)
    seen_indices: set[int] = set()
    for row in frame_rows:
        index = _scalar_int(row["index"], field="index")
        episode_index = _scalar_int(row["episode_index"], field="episode_index")
        stage_id = _scalar_int(row["stage_id"], field="stage_id")
        if index in seen_indices:
            raise ValueError(f"duplicate dataset frame index: {index}")
        seen_indices.add(index)
        if episode_index not in train_assignments:
            continue
        if not 0 <= stage_id < STAGE_COUNT:
            raise ValueError(f"invalid stage id: {stage_id}")
        by_episode_stage[(episode_index, stage_id)].append(index)

    missing = [
        (episode_index, stage_id)
        for episode_index in train_assignments
        for stage_id in range(STAGE_COUNT)
        if not by_episode_stage[(episode_index, stage_id)]
    ]
    if missing:
        raise ValueError(f"train episodes lack task stages: {missing[:5]}")

    indices_by_design_cell: dict[str, list[int]] = defaultdict(list)
    stage_counts: Counter[str] = Counter()
    episode_stage_counts: dict[str, dict[str, int]] = {}
    for episode_index, assignment in sorted(train_assignments.items()):
        cell = str(assignment["design_cell"])
        episode_counts: dict[str, int] = {}
        for stage_id in range(STAGE_COUNT):
            values = sorted(
                by_episode_stage[(episode_index, stage_id)],
                key=lambda index: _stable_key(
                    seed, episode_index, stage_id, index
                ),
            )[:stage_frame_cap_per_episode]
            indices_by_design_cell[cell].extend(values)
            stage_counts[str(stage_id)] += len(values)
            episode_counts[str(stage_id)] = len(values)
        episode_stage_counts[str(episode_index)] = episode_counts

    if len(indices_by_design_cell) != DESIGN_CELL_COUNT:
        raise ValueError("training split does not cover all 24 design cells")
    cell_modes = Counter(cell.rsplit("-cell-", 1)[0] for cell in indices_by_design_cell)
    if set(cell_modes.values()) != {8} or len(cell_modes) != 3:
        raise ValueError("training design cells do not form three balanced modes")
    for cell in indices_by_design_cell:
        indices_by_design_cell[cell].sort()

    cell_counts = {
        cell: len(indices) for cell, indices in sorted(indices_by_design_cell.items())
    }
    samples_per_cell = min(cell_counts.values())
    if samples_per_cell < 1:
        raise ValueError("at least one design cell has no training frames")
    return {
        "schema_version": 1,
        "protocol": SAMPLING_PROTOCOL,
        "seed": seed,
        "stage_frame_cap_per_episode": stage_frame_cap_per_episode,
        "train_episode_count": len(train_assignments),
        "design_cell_count": len(indices_by_design_cell),
        "samples_per_design_cell_per_epoch": samples_per_cell,
        "samples_per_epoch": samples_per_cell * DESIGN_CELL_COUNT,
        "cell_unique_frame_counts": cell_counts,
        "stage_unique_frame_counts": dict(sorted(stage_counts.items())),
        "episode_stage_unique_frame_counts": episode_stage_counts,
        "indices_by_design_cell": dict(sorted(indices_by_design_cell.items())),
        "sampling_probabilities": {
            "grasp_mode": {mode: 1 / 3 for mode in sorted(cell_modes)},
            "design_cell_within_mode": 1 / 8,
        },
    }


def build_sampling_manifest_from_dataset(
    *,
    dataset_root: str | Path,
    split_manifest_path: str | Path,
    output: str | Path,
    seed: int = 20260729,
    stage_frame_cap_per_episode: int = 100,
) -> dict[str, Any]:
    """Read LeRobot metadata and write a fingerprinted sampling manifest."""

    import pyarrow as pa
    import pyarrow.parquet as pq

    root = Path(dataset_root).resolve()
    split_path = Path(split_manifest_path).resolve()
    output_path = Path(output)
    info_path = root / "meta" / "info.json"
    data_files = sorted((root / "data").rglob("*.parquet"))
    if not info_path.is_file() or not data_files:
        raise ValueError("dataset is missing info metadata or parquet data")
    split_manifest = json.loads(split_path.read_text(encoding="utf-8"))
    table = pa.concat_tables(
        [
            pq.read_table(
                path,
                columns=["index", "episode_index", "observation.stage_id"],
            )
            for path in data_files
        ]
    ).combine_chunks()
    frame_rows = (
        {
            "index": _scalar_int(index, field="index"),
            "episode_index": _scalar_int(episode_index, field="episode_index"),
            "stage_id": _scalar_int(stage_id, field="stage_id"),
        }
        for index, episode_index, stage_id in zip(
            table["index"].to_pylist(),
            table["episode_index"].to_pylist(),
            table["observation.stage_id"].to_pylist(),
        )
    )
    payload = build_sampling_manifest(
        frame_rows=frame_rows,
        split_manifest=split_manifest,
        seed=seed,
        stage_frame_cap_per_episode=stage_frame_cap_per_episode,
    )
    payload["source"] = {
        "dataset_root": str(root),
        "dataset_info_sha256": _sha256(info_path),
        "split_manifest": str(split_path),
        "split_manifest_sha256": _sha256(split_path),
        "data_files": [
            {"path": str(path), "sha256": _sha256(path)} for path in data_files
        ],
    }
    unsigned = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode(
        "utf-8"
    )
    payload["manifest_sha256"] = hashlib.sha256(unsigned).hexdigest()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return payload


def load_sampling_manifest(path: str | Path) -> dict[str, Any]:
    path = Path(path)
    payload = json.loads(path.read_text(encoding="utf-8"))
    claimed = str(payload.get("manifest_sha256") or "")
    unsigned = dict(payload)
    unsigned.pop("manifest_sha256", None)
    actual = hashlib.sha256(
        json.dumps(unsigned, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    if claimed != actual or payload.get("protocol") != SAMPLING_PROTOCOL:
        raise ValueError("sampling manifest fingerprint or protocol mismatch")
    pools = payload.get("indices_by_design_cell")
    if not isinstance(pools, dict) or len(pools) != DESIGN_CELL_COUNT:
        raise ValueError("sampling manifest lacks 24 design-cell pools")
    if int(payload.get("train_episode_count", 0)) != 1200:
        raise ValueError("sampling manifest does not contain 1,200 train episodes")
    if int(payload.get("samples_per_epoch", 0)) < DESIGN_CELL_COUNT:
        raise ValueError("sampling manifest has an invalid epoch size")
    if any(not isinstance(values, list) or not values for values in pools.values()):
        raise ValueError("sampling manifest contains an empty design-cell pool")
    return payload


def make_stratified_sampler_class(manifest_path: str | Path) -> type:
    """Create an EpisodeAwareSampler-compatible balanced sampler class."""

    manifest = load_sampling_manifest(manifest_path)
    manifest_pools = {
        cell: np.asarray(indices, dtype=np.int64)
        for cell, indices in manifest["indices_by_design_cell"].items()
    }

    class ParcelStratifiedSampler:
        def __init__(
            self,
            dataset_from_indices: list[int],
            dataset_to_indices: list[int],
            episode_indices_to_use: list | None = None,
            drop_n_first_frames: int = 0,
            drop_n_last_frames: int = 0,
            shuffle: bool = False,
            seed: int = 0,
            absolute_to_relative_idx: dict[int, int] | None = None,
        ) -> None:
            if drop_n_first_frames < 0 or drop_n_last_frames < 0:
                raise ValueError("dropped frame counts cannot be negative")
            starts = np.asarray(dataset_from_indices, dtype=np.int64)
            ends = np.asarray(dataset_to_indices, dtype=np.int64)
            if starts.shape != ends.shape:
                raise ValueError("episode boundary arrays differ")
            used = np.ones(len(starts), dtype=bool)
            if episode_indices_to_use is not None:
                used[:] = False
                used[np.asarray(episode_indices_to_use, dtype=np.int64)] = True
            valid_starts = starts + drop_n_first_frames
            valid_ends = ends - drop_n_last_frames
            pools: dict[str, np.ndarray] = {}
            for cell, indices in manifest_pools.items():
                episodes = np.searchsorted(ends, indices, side="right")
                inside = episodes < len(ends)
                clipped = np.minimum(episodes, len(ends) - 1)
                inside &= used[clipped]
                inside &= indices >= valid_starts[clipped]
                inside &= indices < valid_ends[clipped]
                filtered = indices[inside]
                if absolute_to_relative_idx is not None:
                    filtered = np.asarray(
                        [absolute_to_relative_idx[int(index)] for index in filtered],
                        dtype=np.int64,
                    )
                if len(filtered) < 1:
                    raise ValueError(f"no sampler frames remain for {cell}")
                pools[cell] = filtered
            self._pools = pools
            self._samples_per_cell = min(len(values) for values in pools.values())
            self._num_frames = self._samples_per_cell * len(pools)
            self.shuffle = shuffle
            self.seed = seed
            self._epoch = 0
            self._start_index = 0

        @property
        def indices(self) -> list[int]:
            return self._epoch_indices(0).tolist()

        def set_epoch(self, epoch: int) -> None:
            self._epoch = epoch

        def state_dict(self) -> dict[str, int]:
            return {"epoch": self._epoch, "start_index": self._start_index}

        def load_state_dict(self, state: dict[str, int]) -> None:
            self._epoch = int(state["epoch"])
            self._start_index = int(state["start_index"])

        def _generator(self, epoch: int):
            import torch

            epoch_seed = int(
                np.random.SeedSequence([self.seed, epoch]).generate_state(
                    1, dtype=np.uint64
                )[0]
            )
            return torch.Generator().manual_seed(epoch_seed)

        def _epoch_indices(self, epoch: int) -> np.ndarray:
            import torch

            generator = self._generator(epoch)
            selected = []
            for cell in sorted(self._pools):
                pool = self._pools[cell]
                order = torch.randperm(len(pool), generator=generator).numpy()
                selected.append(pool[order[: self._samples_per_cell]])
            values = np.concatenate(selected)
            if self.shuffle:
                order = torch.randperm(len(values), generator=generator).numpy()
                values = values[order]
            return values

        def __iter__(self) -> Iterator[int]:
            epoch, start = self._epoch, self._start_index
            self._epoch += 1
            self._start_index = 0
            values = self._epoch_indices(epoch)
            return iter(int(value) for value in values[start:])

        def __len__(self) -> int:
            return self._num_frames

    ParcelStratifiedSampler.__name__ = "ParcelStratifiedSampler"
    return ParcelStratifiedSampler


def install_stratified_sampler(manifest_path: str | Path) -> type:
    """Patch LeRobot before its train module imports EpisodeAwareSampler."""

    import lerobot.datasets as datasets_module
    from lerobot.datasets import sampler as sampler_module

    sampler_class = make_stratified_sampler_class(manifest_path)
    sampler_module.EpisodeAwareSampler = sampler_class
    # lerobot_train imports the package-level re-export, not the submodule
    # attribute. Both bindings must point at the balanced implementation.
    datasets_module.EpisodeAwareSampler = sampler_class
    train_module = sys.modules.get("lerobot.scripts.lerobot_train")
    if train_module is not None:
        train_module.EpisodeAwareSampler = sampler_class
    return sampler_class
