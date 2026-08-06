"""Episode-aware HDF5 storage for robot interactions and compatible loaders.

The layout deliberately follows the common ``data/demo_*`` convention used by
robot-learning datasets while retaining Genesis-specific task metadata in a
sidecar JSON manifest.  HDF5 handles are opened lazily per DataLoader worker,
which prevents unsafe handle sharing with multiprocessing.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np
import torch
from torch.utils.data import DataLoader, Dataset


SCHEMA_VERSION = 1


def _h5py() -> Any:
    try:
        import h5py
    except ImportError as error:
        raise ImportError("Install h5py to read or write robot interaction datasets.") from error
    return h5py


def _jsonable(value: Any) -> Any:
    if isinstance(value, np.ndarray):
        return value.tolist()
    if isinstance(value, np.generic):
        return value.item()
    if isinstance(value, Mapping):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    return value


@dataclass
class EpisodeTrajectory:
    """In-memory buffer for one transition trajectory."""

    states: list[np.ndarray] = field(default_factory=list)
    actions: list[np.ndarray] = field(default_factory=list)
    rewards: list[float] = field(default_factory=list)
    terminated: list[bool] = field(default_factory=list)
    truncated: list[bool] = field(default_factory=list)
    next_states: list[np.ndarray] = field(default_factory=list)
    proprio: list[np.ndarray] = field(default_factory=list)
    next_proprio: list[np.ndarray] = field(default_factory=list)
    rgb: list[np.ndarray] = field(default_factory=list)
    next_rgb: list[np.ndarray] = field(default_factory=list)

    def append(
        self,
        *,
        state: np.ndarray,
        action: np.ndarray,
        reward: float,
        terminated: bool,
        truncated: bool,
        next_state: np.ndarray,
        proprio: np.ndarray | None = None,
        next_proprio: np.ndarray | None = None,
        observation: Mapping[str, np.ndarray] | None = None,
        next_observation: Mapping[str, np.ndarray] | None = None,
    ) -> None:
        self.states.append(np.asarray(state, dtype=np.float32))
        self.actions.append(np.asarray(action, dtype=np.float32))
        self.rewards.append(float(reward))
        self.terminated.append(bool(terminated))
        self.truncated.append(bool(truncated))
        self.next_states.append(np.asarray(next_state, dtype=np.float32))
        if proprio is not None:
            self.proprio.append(np.asarray(proprio, dtype=np.float32))
        if next_proprio is not None:
            self.next_proprio.append(np.asarray(next_proprio, dtype=np.float32))
        if observation is not None and "camera" in observation:
            self.rgb.append(np.asarray(observation["camera"], dtype=np.uint8))
        if next_observation is not None and "camera" in next_observation:
            self.next_rgb.append(np.asarray(next_observation["camera"], dtype=np.uint8))

    @property
    def length(self) -> int:
        return len(self.actions)


class TrajectoryHDF5Writer:
    """Write trajectories into ``dataset.hdf5`` plus an auditable manifest."""

    def __init__(self, output_dir: str | Path, *, env_metadata: Mapping[str, Any]) -> None:
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.path = self.output_dir / "dataset.hdf5"
        self.manifest_path = self.output_dir / "manifest.json"
        self.env_metadata = _jsonable(dict(env_metadata))
        self.episodes: list[dict[str, Any]] = []
        self._file: Any | None = None

    def __enter__(self) -> "TrajectoryHDF5Writer":
        h5py = _h5py()
        self._file = h5py.File(self.path, "w")
        self._file.attrs["schema_version"] = SCHEMA_VERSION
        self._file.attrs["env_metadata"] = json.dumps(self.env_metadata, sort_keys=True)
        self._file.create_group("data")
        return self

    def add_episode(
        self, trajectory: EpisodeTrajectory, *, episode: int, metadata: Mapping[str, Any]
    ) -> None:
        if self._file is None:
            raise RuntimeError("use TrajectoryHDF5Writer as a context manager")
        if trajectory.length == 0:
            raise ValueError("cannot store an empty trajectory")
        if trajectory.rgb and len(trajectory.rgb) != trajectory.length:
            raise ValueError("camera observations must be present for every transition or none")
        if trajectory.next_rgb and len(trajectory.next_rgb) != trajectory.length:
            raise ValueError("next camera observations must match trajectory length")
        if bool(trajectory.proprio) != bool(trajectory.next_proprio):
            raise ValueError("proprio and next proprio must be provided together")
        if trajectory.proprio and len(trajectory.proprio) != trajectory.length:
            raise ValueError("proprio observations must be present for every transition or none")

        name = f"demo_{episode:06d}"
        group = self._file["data"].create_group(name)
        group.attrs["num_samples"] = trajectory.length
        group.attrs["metadata"] = json.dumps(_jsonable(dict(metadata)), sort_keys=True)
        obs_group, next_obs_group = group.create_group("obs"), group.create_group("next_obs")
        obs_group.create_dataset("state", data=np.stack(trajectory.states), compression="gzip")
        next_obs_group.create_dataset("state", data=np.stack(trajectory.next_states), compression="gzip")
        if trajectory.proprio:
            obs_group.create_dataset("proprio", data=np.stack(trajectory.proprio), compression="gzip")
            next_obs_group.create_dataset("proprio", data=np.stack(trajectory.next_proprio), compression="gzip")
        if trajectory.rgb:
            obs_group.create_dataset("rgb", data=np.stack(trajectory.rgb), compression="gzip")
            next_obs_group.create_dataset("rgb", data=np.stack(trajectory.next_rgb), compression="gzip")
        group.create_dataset("actions", data=np.stack(trajectory.actions), compression="gzip")
        group.create_dataset("rewards", data=np.asarray(trajectory.rewards, dtype=np.float32))
        group.create_dataset("terminated", data=np.asarray(trajectory.terminated, dtype=np.bool_))
        group.create_dataset("truncated", data=np.asarray(trajectory.truncated, dtype=np.bool_))
        self.episodes.append({
            "id": name,
            "length": trajectory.length,
            "success": bool(metadata.get("success", False)),
            "modalities": ["state", *( ["proprio"] if trajectory.proprio else [] ), *( ["rgb"] if trajectory.rgb else [] )],
            "metadata": _jsonable(dict(metadata)),
        })

    def close(self) -> Path:
        if self._file is None:
            raise RuntimeError("writer is not open")
        total = sum(item["length"] for item in self.episodes)
        self._file["data"].attrs["total"] = total
        self._file.close()
        self._file = None
        manifest = {
            "schema_version": SCHEMA_VERSION,
            "format": "robot_interaction_hdf5",
            "dataset_path": self.path.name,
            "total_transitions": total,
            "env_metadata": self.env_metadata,
            "episodes": self.episodes,
        }
        self.manifest_path.write_text(json.dumps(manifest, indent=2) + "\n")
        return self.manifest_path

    def __exit__(self, exc_type: Any, exc: Any, traceback: Any) -> None:
        if self._file is not None:
            if exc_type is None:
                self.close()
            else:
                self._file.close()
                self._file = None


class RobotInteractionDataset(Dataset[dict[str, torch.Tensor]]):
    """Transition dataset for HDF5 trajectories or legacy ``.npy`` pairs.

    ``source`` may be a dataset directory, ``manifest.json``, ``dataset.hdf5``,
    or a legacy directory containing ``state.npy`` and ``action.npy``.
    """

    def __init__(self, source: str | Path, *, modalities: Sequence[str] = ("state",)) -> None:
        self.source = Path(source)
        self.modalities = tuple(modalities)
        self._handle: Any | None = None
        self._legacy_states: np.ndarray | None = None
        self._legacy_actions: np.ndarray | None = None
        self._index: list[tuple[str, int]] = []
        self._hdf5_path, self._manifest = self._resolve_source()
        if self._hdf5_path is None:
            self._load_legacy()
        else:
            self._build_hdf5_index()

    def _resolve_source(self) -> tuple[Path | None, dict[str, Any] | None]:
        directory = self.source if self.source.is_dir() else self.source.parent
        manifest_path = self.source if self.source.name == "manifest.json" else directory / "manifest.json"
        if manifest_path.exists():
            manifest = json.loads(manifest_path.read_text())
            return directory / manifest["dataset_path"], manifest
        hdf5_path = self.source if self.source.suffix in {".h5", ".hdf5"} else directory / "dataset.hdf5"
        if hdf5_path.exists():
            return hdf5_path, None
        return None, None

    def _load_legacy(self) -> None:
        directory = self.source if self.source.is_dir() else self.source.parent
        state_path, action_path = directory / "state.npy", directory / "action.npy"
        if not state_path.exists() or not action_path.exists():
            raise FileNotFoundError(f"no HDF5 or legacy state/action pair found under {directory}")
        self._legacy_states = np.load(state_path, mmap_mode="r")
        self._legacy_actions = np.load(action_path, mmap_mode="r")
        if len(self._legacy_states) != len(self._legacy_actions):
            raise ValueError("legacy state.npy and action.npy have different lengths")

    def _build_hdf5_index(self) -> None:
        if self._manifest is not None:
            for episode in self._manifest["episodes"]:
                self._index.extend((episode["id"], step) for step in range(int(episode["length"])))
            return
        with _h5py().File(self._hdf5_path, "r") as file:
            for name, group in file["data"].items():
                self._index.extend((name, step) for step in range(int(group.attrs["num_samples"])))

    def _file(self) -> Any:
        if self._handle is None:
            self._handle = _h5py().File(self._hdf5_path, "r")
        return self._handle

    def __len__(self) -> int:
        return len(self._index) if self._hdf5_path is not None else len(self._legacy_actions)

    def __getitem__(self, index: int) -> dict[str, torch.Tensor]:
        if self._hdf5_path is None:
            assert self._legacy_states is not None and self._legacy_actions is not None
            next_index = min(index + 1, len(self._legacy_states) - 1)
            return {
                "state": torch.from_numpy(np.array(self._legacy_states[index], dtype=np.float32)),
                "action": torch.from_numpy(np.array(self._legacy_actions[index], dtype=np.float32)),
                "next_state": torch.from_numpy(np.array(self._legacy_states[next_index], dtype=np.float32)),
                "reward": torch.tensor(0.0),
                "terminated": torch.tensor(index == len(self._legacy_states) - 1),
                "truncated": torch.tensor(False),
            }
        episode, step = self._index[index]
        group = self._file()["data"][episode]
        sample: dict[str, torch.Tensor] = {
            "state": torch.from_numpy(np.asarray(group["obs"]["state"][step], dtype=np.float32)),
            "action": torch.from_numpy(np.asarray(group["actions"][step], dtype=np.float32)),
            "next_state": torch.from_numpy(np.asarray(group["next_obs"]["state"][step], dtype=np.float32)),
            "reward": torch.tensor(group["rewards"][step], dtype=torch.float32),
            "terminated": torch.tensor(group["terminated"][step], dtype=torch.bool),
            "truncated": torch.tensor(group["truncated"][step], dtype=torch.bool),
        }
        if "rgb" in self.modalities and "rgb" in group["obs"]:
            sample["rgb"] = torch.from_numpy(np.asarray(group["obs"]["rgb"][step], dtype=np.uint8))
            sample["next_rgb"] = torch.from_numpy(np.asarray(group["next_obs"]["rgb"][step], dtype=np.uint8))
        if "proprio" in self.modalities and "proprio" in group["obs"]:
            sample["proprio"] = torch.from_numpy(np.asarray(group["obs"]["proprio"][step], dtype=np.float32))
            sample["next_proprio"] = torch.from_numpy(np.asarray(group["next_obs"]["proprio"][step], dtype=np.float32))
        return sample

    def close(self) -> None:
        handle, self._handle = self._handle, None
        if handle is not None:
            handle.close()

    def __getstate__(self) -> dict[str, Any]:
        state = self.__dict__.copy()
        state["_handle"] = None
        return state

    def __del__(self) -> None:
        # Interpreter teardown can invalidate h5py's module globals before
        # Dataset destructors run.  Never surface teardown-only errors to users.
        try:
            if hasattr(self, "_handle"):
                self.close()
        except Exception:
            pass


def build_dataloader(
    source: str | Path,
    *,
    batch_size: int,
    shuffle: bool = True,
    num_workers: int = 0,
    modalities: Sequence[str] = ("state",),
) -> DataLoader[dict[str, torch.Tensor]]:
    """Construct a worker-safe DataLoader over HDF5 or legacy demonstrations."""
    return DataLoader(
        RobotInteractionDataset(source, modalities=modalities),
        batch_size=batch_size,
        shuffle=shuffle,
        num_workers=num_workers,
        persistent_workers=num_workers > 0,
    )
