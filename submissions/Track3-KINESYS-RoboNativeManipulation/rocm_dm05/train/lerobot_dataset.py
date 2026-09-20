"""OpenDM-compatible loader for a local LeRobot Dataset v3 repository.

The loader reuses OpenDM's existing transform chain without modifying dataset
targets. Its output matches the raw dictionary contract of OpenDM's
``JsonlDataset``:

- ``raw_lines`` contains the serialized state/action sequence for one episode;
- ``meta_data`` contains the zero-based frame index and state description;
- ``images_1/2/3`` are current-frame PIL images from head and wrist cameras;
- ``state`` and ``action`` are current-frame float lists;
- ``prompt`` is the LeRobot task text.

Episode lines are materialized once and reused by every sample. LeRobot is
imported lazily so model-only inference does not require the dataset package.
"""

import os

import numpy as np
import orjson
from PIL import Image
from torch.utils.data import Dataset

# OpenDM image keys follow the head, left-wrist, right-wrist order expected by
# ChatTokenization.
CAMERA_MAP_DEFAULT = {
    "images_1": "observation.images.cam_high",
    "images_2": "observation.images.cam_left_wrist",
    "images_3": "observation.images.cam_right_wrist",
}


class LerobotDataset(Dataset):
    """Expose a local LeRobot v3 dataset through OpenDM's raw sample contract.

    Args:
        lerobot_path: Dataset root containing ``data``, ``videos`` and ``meta``.
        image_keys: OpenDM image keys to emit.
        camera_map: Mapping from OpenDM image keys to LeRobot feature names.
        state_desc: Per-dimension robot-state semantics stored in metadata.
        transforms: OpenDM transform pipeline applied to each raw sample.
        dataset_name: Stable name used for logs and normalization statistics.
        dataset_meta: Additional metadata merged into every sample.
        repo_id: LeRobot identifier; local roots do not require network access.
        decode_video: Decode RGB for training; disable for normalization stats.
        video_backend: LeRobot video backend. The validated path uses PyAV.
    """

    def __init__(
        self,
        lerobot_path: str,
        image_keys: list[str] | None = None,
        camera_map: dict[str, str] | None = None,
        state_desc: list | None = None,
        transforms=None,
        dataset_name: str | None = None,
        dataset_meta: dict | None = None,
        repo_id: str | None = None,
        decode_video: bool = True,
        video_backend: str = "pyav",
    ):
        from lerobot.datasets.lerobot_dataset import LeRobotDataset as _LRS

        self.lerobot_path = lerobot_path
        self.image_keys = list(image_keys or ["images_1", "images_2", "images_3"])
        self.camera_map = dict(camera_map) if camera_map else dict(CAMERA_MAP_DEFAULT)
        self.state_desc = list(state_desc or [])
        self.transforms = transforms
        self.dataset_name = dataset_name
        self.dataset_meta = dict(dataset_meta or {})
        self.decode_video = decode_video
        self.repo_id = repo_id or _default_repo_id(lerobot_path)

        self._ds = _LRS(
            repo_id=self.repo_id,
            root=lerobot_path,
            video_backend=video_backend,
        )
        self._build_episode_index()

    def _build_episode_index(self) -> None:
        """Materialize episode state/actions and build the sample index."""
        hf = self._ds.hf_dataset
        self._all_states = list(hf["observation.state"])
        self._all_actions = list(hf["action"])

        episodes = self._ds.meta.episodes
        total = int(self._ds.meta.total_episodes)

        self._episode_lines: dict[int, list[str]] = {}
        self._episode_range: dict[int, tuple[int, int]] = {}
        self._task_of_episode: dict[int, str] = {}
        sample_index: list[tuple[int, int]] = []

        for ep_id in range(total):
            episode = episodes[ep_id]
            frame_from = int(episode["dataset_from_index"])
            frame_to = int(episode["dataset_to_index"])
            self._episode_range[ep_id] = (frame_from, frame_to)

            lines = [
                orjson.dumps(
                    {
                        "state": np.asarray(self._all_states[index]).tolist(),
                        "action": np.asarray(self._all_actions[index]).tolist(),
                    }
                ).decode()
                for index in range(frame_from, frame_to)
            ]
            self._episode_lines[ep_id] = lines

            tasks = episode.get("tasks") or []
            self._task_of_episode[ep_id] = tasks[0] if tasks else ""

            # Match JsonlDataset: the last frame has no next-step training target.
            length = frame_to - frame_from
            for frame_index in range(max(0, length - 1)):
                sample_index.append((ep_id, frame_index))

        self.sample_index = sample_index
        self.total_samples = len(sample_index)

    def __len__(self) -> int:
        return self.total_samples

    def __getitem__(self, idx: int) -> dict:
        episode_id, frame_index = self.sample_index[idx]
        frame_from, _ = self._episode_range[episode_id]
        global_index = frame_from + frame_index

        result: dict = {
            "raw_lines": self._episode_lines[episode_id],
            "meta_data": {
                **self.dataset_meta,
                "frame_index": frame_index,
                "state_desc": self.state_desc,
            },
            "prompt": self._task_of_episode[episode_id],
        }

        if self.decode_video:
            frame = self._ds[global_index]
            for image_key in self.image_keys:
                camera_key = self.camera_map[image_key]
                result[image_key] = _tensor_to_pil(frame[camera_key])
            result["state"] = frame["observation.state"].detach().cpu().numpy().tolist()
            result["action"] = frame["action"].detach().cpu().numpy().tolist()
        else:
            result["state"] = np.asarray(self._all_states[global_index]).tolist()
            result["action"] = np.asarray(self._all_actions[global_index]).tolist()

        if self.transforms is not None:
            result = self.transforms(result)
        return result


def _tensor_to_pil(tensor) -> Image.Image:
    """Convert a float ``(C,H,W)`` LeRobot tensor to an RGB PIL image."""
    array = (
        (tensor.clamp(0.0, 1.0).detach().cpu().permute(1, 2, 0).numpy() * 255.0)
        .astype(np.uint8)
    )
    return Image.fromarray(array, mode="RGB")


def _default_repo_id(path: str) -> str:
    name = os.path.basename(os.path.normpath(path))
    return f"local/{name}"
