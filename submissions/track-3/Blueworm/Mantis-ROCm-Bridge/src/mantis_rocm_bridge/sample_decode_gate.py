"""Bounded sample-decode integrity gate for local Mantis LeRobot datasets.

This gate proves only that a bounded set of decoded samples - the first,
midpoint, and last frame of every episode - decode to finite 16-dimensional
``observation.state`` and ``action`` vectors and finite channel-first (CHW)
images of the declared shapes (``env_cam`` 3x240x320; both wrist cameras
3x240x424) with pixel values in [0,1].  It reads the dataset strictly read-only,
never downloads anything, never mutates the dataset, and never invokes LeRobot's
network layer.

Two decode paths are available, selected by the CLI ``--loader`` flag and
recorded verbatim in the receipt so the two are never confused:

* ``lerobot`` (default) - the *real* LeRobot runtime.  A
  :class:`LeRobotRuntimeFrameSource` instantiates
  ``lerobot.datasets.lerobot_dataset.LeRobotDataset`` with
  ``download_videos=False`` and ``force_cache_sync=False`` and decodes
  ``dataset[index]``.  Network is fenced off three ways: the required local
  meta/data files are prevalidated, the Hugging Face offline environment flags
  are asserted set *before* LeRobot is imported, and any local-load failure is
  raised as an error rather than triggering a download.
* ``parquet`` - the *cross-check*.  :class:`LeRobotSampleFrameSource` reads the
  data parquet cell directly and applies ``torchvision.ToTensor``.  This path is
  deliberately independent of the LeRobot runtime so it stays version-stable
  across LeRobot 0.4.2 and 0.4.4 image datasets.

The decode work (torch / pyarrow / PIL / LeRobot) lives entirely behind the
:class:`FrameSource` abstraction, so :func:`audit_sample_decode` is pure Python
and runs under the CPU-only unit tests against a tiny in-memory double.  The
receipt records explicit counts, the inspected global indices, declared and
decoded feature shapes, observed value ranges, the index / frame / timestamp
boundaries, ``len(dataset)``, the LeRobot class path, the loader mode, the CPU
device semantics, the LeRobot and dataset codebase versions, the info/stats/gate
hashes, and a strict claim boundary.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

from .contracts import ContractError


#: The qualname the default (runtime) loader is required to instantiate.
EXPECTED_LEROBOT_DATASET_QUALNAME = "lerobot.datasets.lerobot_dataset.LeRobotDataset"

#: Environment variables asserted set *before* LeRobot is imported so a missing
#: local file can never fall through to a network download.
OFFLINE_ENV_FLAGS: dict[str, str] = {
    "HF_HUB_OFFLINE": "1",
    "HF_DATASETS_OFFLINE": "1",
    "TRANSFORMERS_OFFLINE": "1",
}


@dataclass(frozen=True)
class DecodedImage:
    """Summary of one decoded image tensor sufficient for the audit.

    ``shape`` is channel-first (CHW) to match the LeRobot ``hf_transform_to_torch``
    decoding (``torchvision.ToTensor`` -> float32 CHW in [0,1]).
    """

    shape: tuple[int, int, int]
    finite: bool
    min_value: float
    max_value: float


@dataclass(frozen=True)
class DecodedFrame:
    """One decoded sample row handed to the audit by a :class:`FrameSource`.

    ``frame_index`` (intra-episode), ``timestamp`` (seconds) and
    ``episode_index`` are populated by the runtime loader; the cross-check and
    test doubles may leave them ``None``, in which case the audit skips their
    boundary checks.
    """

    global_index: int
    observation_state: list[float]
    action: list[float]
    images: dict[str, DecodedImage]
    frame_index: int | None = None
    timestamp: float | None = None
    episode_index: int | None = None


@runtime_checkable
class FrameSource(Protocol):
    """Minimal, decode-only view of a local LeRobot dataset.

    Implementations hold the torch/pyarrow/PIL/LeRobot dependencies; the audit
    logic only consumes the values below, so a test double can satisfy it
    without any of those packages installed.

    ``loader_mode`` / ``decode_path`` / ``lerobot_class_path`` / ``len_dataset``
    / ``cpu_device_semantics`` let the receipt distinguish a genuine LeRobot
    runtime decode from the direct-parquet cross-check and record the device
    semantics under which the decode ran.
    """

    total_episodes: int
    total_frames: int
    info: dict[str, Any]
    stats: dict[str, Any]
    info_sha256: str
    stats_sha256: str
    codebase_version: str | None
    lerobot_version: str | None
    lerobot_version_source: str

    loader_mode: str
    decode_path: str
    lerobot_class_path: str | None
    len_dataset: int | None
    cpu_device_semantics: dict[str, Any]

    def episode_bounds(self) -> dict[int, tuple[int, int]]:
        """Return ``episode_index -> (first_global_index, frame_length)``."""

    def decode(self, global_index: int) -> DecodedFrame:
        """Decode a single sample by its global dataset ``index``."""


def sample_offsets(length: int) -> list[int]:
    """Return the deduplicated first / midpoint / last intra-episode offsets.

    ``midpoint = length // 2`` is the lower median index; for length 1 it
    collapses to ``[0]`` and for length 2 to ``[0, 1]``.  Ordering and
    deduplication are preserved so a length-1 episode decodes exactly once.
    """

    if length <= 0:
        return []
    offsets: list[int] = []
    for value in (0, length // 2, length - 1):
        if value not in offsets:
            offsets.append(value)
    return offsets


def _finite_vector(value: Any, dimension: int) -> list[float] | None:
    if hasattr(value, "tolist"):
        value = value.tolist()
    if not isinstance(value, (list, tuple)) or len(value) != dimension:
        return None
    try:
        result = [float(component) for component in value]
    except (TypeError, ValueError):
        return None
    return result if all(math.isfinite(component) for component in result) else None


def _vector_components(value: Any, dimension: int) -> list[float] | None:
    """Best-effort finite-tolerant extraction for observed-range folding."""

    if hasattr(value, "tolist"):
        value = value.tolist()
    if not isinstance(value, (list, tuple)) or len(value) != dimension:
        return None
    try:
        return [float(component) for component in value]
    except (TypeError, ValueError):
        return None


def _validate_gate(gate: dict[str, Any]) -> None:
    if gate.get("schema_version") != 1:
        raise ContractError("sample decode gate schema_version must be 1")
    if not isinstance(gate.get("state_dimension"), int) or gate["state_dimension"] <= 0:
        raise ContractError("sample decode gate state_dimension must be a positive integer")
    if not isinstance(gate.get("action_dimension"), int) or gate["action_dimension"] <= 0:
        raise ContractError("sample decode gate action_dimension must be a positive integer")
    vector_features = gate.get("vector_features")
    if (
        not isinstance(vector_features, list)
        or not vector_features
        or len(vector_features) != len(set(vector_features))
    ):
        raise ContractError("sample decode gate vector_features must be unique and non-empty")
    image_features = gate.get("image_features")
    if not isinstance(image_features, dict) or not image_features:
        raise ContractError("sample decode gate image_features must be a non-empty object")
    for name, shape in image_features.items():
        if (
            not isinstance(shape, list)
            or len(shape) != 3
            or not all(isinstance(part, int) and part > 0 for part in shape)
            or shape[0] != 3
        ):
            raise ContractError(
                f"sample decode gate image feature {name} must be a 3-channel CHW shape"
            )
    value_range = gate.get("expected_image_value_range")
    if (
        not isinstance(value_range, list)
        or len(value_range) != 2
        or not all(isinstance(bound, (int, float)) for bound in value_range)
        or float(value_range[0]) > float(value_range[1])
    ):
        raise ContractError("sample decode gate expected_image_value_range must be [low, high]")
    if gate.get("sample_phase") != "first_mid_last":
        raise ContractError("sample decode gate sample_phase must be first_mid_last")


def _fold(extremes: dict[str, float], value: float) -> None:
    if value < extremes["min"]:
        extremes["min"] = value
    if value > extremes["max"]:
        extremes["max"] = value


def _is_nonneg_int(value: Any) -> bool:
    try:
        return int(value) >= 0
    except (TypeError, ValueError):
        return False


def _extremes_record(extremes: dict[str, float]) -> dict[str, float | None]:
    return {"min": _clean(extremes["min"]), "max": _clean(extremes["max"])}


def audit_sample_decode(
    frame_source: FrameSource,
    *,
    gate: dict[str, Any],
    gate_sha256: str | None = None,
) -> dict[str, Any]:
    """Audit decoded samples and return an immutable-ready receipt.

    The receipt's ``sample_decode_gate_pass`` is true only when every required
    sample decoded without issue.  The receipt never claims anything beyond
    bounded sample-decode integrity (see ``claim_boundary``).
    """

    _validate_gate(gate)
    state_dimension = int(gate["state_dimension"])
    action_dimension = int(gate["action_dimension"])
    vector_features: list[str] = list(gate["vector_features"])
    image_features: dict[str, tuple[int, int, int]] = {
        str(name): tuple(int(part) for part in shape)
        for name, shape in gate["image_features"].items()
    }
    low, high = float(gate["expected_image_value_range"][0]), float(
        gate["expected_image_value_range"][1]
    )

    info = frame_source.info
    declared_total_episodes = info.get("total_episodes")
    declared_total_frames = info.get("total_frames")
    supported_codebase_versions = set(gate.get("supported_codebase_versions", []))

    loader_mode = frame_source.loader_mode
    lerobot_class_path = frame_source.lerobot_class_path
    len_dataset = frame_source.len_dataset
    cpu_device_semantics = frame_source.cpu_device_semantics

    bounds = frame_source.episode_bounds()
    observed_episodes = sorted(bounds)

    issues: list[str] = []
    if not observed_episodes:
        issues.append("no_episodes_observed")

    # Episode indices must form a contiguous 0-based range matching info.json.
    contiguous_from_zero = observed_episodes == list(
        range(0, len(observed_episodes))
    )
    if observed_episodes and not contiguous_from_zero:
        issues.append("episode_index_not_contiguous_from_zero")
    if (
        isinstance(declared_total_episodes, int)
        and declared_total_episodes >= 0
        and len(observed_episodes) != declared_total_episodes
    ):
        issues.append("episode_count_mismatch")

    # Device semantics: the audit is CPU-only; an available CUDA runtime is a
    # violation regardless of loader mode.
    if cpu_device_semantics.get("torch_cuda_is_available") is True:
        issues.append("cuda_available_expected_cpu")

    # The runtime loader must instantiate exactly the expected LeRobot class.
    if loader_mode == "lerobot_runtime" and lerobot_class_path != EXPECTED_LEROBOT_DATASET_QUALNAME:
        issues.append(f"lerobot_class_path_unexpected:{lerobot_class_path}")

    # len(dataset) must agree with the declared frame count when both are known.
    if (
        isinstance(len_dataset, int)
        and isinstance(declared_total_frames, int)
        and declared_total_frames >= 0
        and len_dataset != declared_total_frames
    ):
        issues.append(f"len_dataset_mismatch:{len_dataset}:{declared_total_frames}")

    inspected_global_indices: list[int] = []
    decoded_samples = 0
    episodes_with_zero_length: list[int] = []
    samples_per_episode: dict[str, list[int]] = {}
    decoded_image_shapes: dict[str, list[int]] = {}

    vector_range: dict[str, dict[str, list[float]]] = {
        feature: {"min": [math.inf] * dim, "max": [-math.inf] * dim}
        for feature, dim in (
            ("observation.state", state_dimension),
            ("action", action_dimension),
        )
    }
    image_range: dict[str, dict[str, float]] = {
        feature: {"min": math.inf, "max": -math.inf} for feature in image_features
    }
    index_extremes: dict[str, float] = {"min": math.inf, "max": -math.inf}
    frame_index_extremes: dict[str, float] = {"min": math.inf, "max": -math.inf}
    timestamp_extremes: dict[str, float] = {"min": math.inf, "max": -math.inf}

    for episode in observed_episodes:
        first_global, length = bounds[episode]
        offsets = sample_offsets(length)
        if length <= 0:
            episodes_with_zero_length.append(episode)
            samples_per_episode[str(episode)] = []
            continue
        if (
            isinstance(declared_total_frames, int)
            and declared_total_frames >= 0
            and first_global + length > declared_total_frames
        ):
            issues.append(f"episode_exceeds_dataset_frame_span:{episode}")
        decoded_offsets: list[int] = []
        for offset in offsets:
            global_index = first_global + offset
            if global_index < 0 or (
                isinstance(declared_total_frames, int)
                and declared_total_frames >= 0
                and global_index >= declared_total_frames
            ):
                issues.append(f"sample_global_index_out_of_range:{episode}:{offset}")
                continue
            try:
                frame = frame_source.decode(global_index)
            except Exception as exc:  # noqa: BLE001 - auditable decode failure
                issues.append(
                    f"decode_error:{episode}:{offset}:{type(exc).__name__}"
                )
                continue
            if frame.global_index != global_index:
                issues.append(
                    f"decoded_global_index_mismatch:{episode}:{offset}"
                )
            decoded_samples += 1
            decoded_offsets.append(offset)
            if global_index not in inspected_global_indices:
                inspected_global_indices.append(global_index)

            _fold(index_extremes, float(frame.global_index))
            if frame.frame_index is not None:
                if not _is_nonneg_int(frame.frame_index):
                    issues.append(f"frame_index_invalid:{episode}:{offset}")
                else:
                    _fold(frame_index_extremes, float(int(frame.frame_index)))
            if frame.timestamp is not None:
                try:
                    timestamp = float(frame.timestamp)
                except (TypeError, ValueError):
                    timestamp = math.nan
                if not math.isfinite(timestamp) or timestamp < 0:
                    issues.append(f"timestamp_invalid:{episode}:{offset}")
                else:
                    _fold(timestamp_extremes, timestamp)

            _audit_vectors(
                frame,
                vector_features,
                state_dimension,
                action_dimension,
                episode,
                offset,
                issues,
                vector_range,
            )
            _audit_images(
                frame,
                image_features,
                low,
                high,
                episode,
                offset,
                issues,
                image_range,
                decoded_image_shapes,
            )
        samples_per_episode[str(episode)] = decoded_offsets

    issues.extend(f"episode_zero_length:{episode}" for episode in episodes_with_zero_length)

    declared_feature_shapes = _declared_shapes(info, vector_features, image_features)

    observed_ranges: dict[str, Any] = {}
    for feature, limits in vector_range.items():
        observed_ranges[feature] = {
            "min": [_clean(extreme) for extreme in limits["min"]],
            "max": [_clean(extreme) for extreme in limits["max"]],
        }
    for feature, limits in image_range.items():
        observed_ranges[feature] = {
            "min": _clean(limits["min"]),
            "max": _clean(limits["max"]),
        }

    episodes_dataset_index_bounds = {
        str(episode): {
            "dataset_from_index": int(first_global),
            "dataset_to_index": int(first_global + length),
            "length": int(length),
        }
        for episode, (first_global, length) in sorted(bounds.items())
    }

    codebase_version = frame_source.codebase_version
    unique_issues = sorted(set(issues))
    receipt: dict[str, Any] = {
        "schema_version": 1,
        "gate_id": gate["gate_id"],
        "task_id": gate["task_id"],
        "protocol": gate["protocol"],
        "sample_decode_gate_pass": not unique_issues,
        "issues": unique_issues,
        "sample_phase": gate["sample_phase"],
        "loader_mode": loader_mode,
        "decode_path": frame_source.decode_path,
        "lerobot_class_path": lerobot_class_path,
        "len_dataset": len_dataset,
        "cpu_device_semantics": cpu_device_semantics,
        "total_episodes": declared_total_episodes,
        "total_frames": declared_total_frames,
        "inspected_episodes": len(observed_episodes),
        "decoded_samples": decoded_samples,
        "inspected_global_indices": sorted(inspected_global_indices),
        "samples_per_episode": samples_per_episode,
        "episodes_dataset_index_bounds": episodes_dataset_index_bounds,
        "index_boundaries": _extremes_record(index_extremes),
        "frame_index_boundaries": _extremes_record(frame_index_extremes),
        "timestamp_boundaries": _extremes_record(timestamp_extremes),
        "declared_feature_shapes": declared_feature_shapes,
        "decoded_image_shapes": decoded_image_shapes,
        "observed_ranges": observed_ranges,
        "expected_image_value_range": [low, high],
        "codebase_version": codebase_version,
        "codebase_version_recognized": (
            codebase_version in supported_codebase_versions
            if codebase_version is not None
            else False
        ),
        "supported_codebase_versions": sorted(supported_codebase_versions),
        "lerobot_version": frame_source.lerobot_version,
        "lerobot_version_source": frame_source.lerobot_version_source,
        "info_sha256": frame_source.info_sha256,
        "stats_sha256": frame_source.stats_sha256,
        "gate_sha256": gate_sha256,
        "claim_boundary": gate["claim_boundary"],
    }
    return receipt


def _audit_vectors(
    frame: DecodedFrame,
    vector_features: list[str],
    state_dimension: int,
    action_dimension: int,
    episode: int,
    offset: int,
    issues: list[str],
    vector_range: dict[str, dict[str, list[float]]],
) -> None:
    values_by_feature = {
        "observation.state": frame.observation_state,
        "action": frame.action,
    }
    dimensions = {
        "observation.state": state_dimension,
        "action": action_dimension,
    }
    for feature in vector_features:
        raw = values_by_feature[feature]
        dimension = dimensions[feature]
        finite = _finite_vector(raw, dimension)
        if finite is None:
            issues.append(f"invalid_vector:{feature}:{episode}:{offset}")
            continue
        components = _vector_components(raw, dimension) or finite
        limits = vector_range[feature]
        for index, value in enumerate(components):
            if math.isfinite(value):
                if value < limits["min"][index]:
                    limits["min"][index] = value
                if value > limits["max"][index]:
                    limits["max"][index] = value


def _audit_images(
    frame: DecodedFrame,
    image_features: dict[str, tuple[int, int, int]],
    low: float,
    high: float,
    episode: int,
    offset: int,
    issues: list[str],
    image_range: dict[str, dict[str, float]],
    decoded_image_shapes: dict[str, list[int]],
) -> None:
    for feature, expected_shape in image_features.items():
        image = frame.images.get(feature)
        if image is None:
            issues.append(f"image_missing:{feature}:{episode}:{offset}")
            continue
        actual_shape = tuple(int(part) for part in image.shape)
        if actual_shape != expected_shape:
            issues.append(
                f"image_shape_mismatch:{feature}:{episode}:{offset}"
            )
        else:
            decoded_image_shapes.setdefault(feature, list(expected_shape))
        if not image.finite:
            issues.append(f"image_not_finite:{feature}:{episode}:{offset}")
            continue
        if image.min_value < low or image.max_value > high:
            issues.append(f"image_value_out_of_range:{feature}:{episode}:{offset}")
        limits = image_range[feature]
        if math.isfinite(image.min_value) and image.min_value < limits["min"]:
            limits["min"] = image.min_value
        if math.isfinite(image.max_value) and image.max_value > limits["max"]:
            limits["max"] = image.max_value


def _declared_shapes(
    info: dict[str, Any],
    vector_features: list[str],
    image_features: dict[str, tuple[int, int, int]],
) -> dict[str, Any]:
    features = info.get("features", {})
    shapes: dict[str, Any] = {}
    for feature in vector_features:
        entry = features.get(feature, {})
        shapes[feature] = {
            "declared_shape": entry.get("shape"),
            "decoded_shape": [
                int(dim)
                for dim in (
                    entry.get("shape")
                    if isinstance(entry.get("shape"), list)
                    else []
                )
            ]
            or None,
        }
    for feature, expected_shape in image_features.items():
        entry = features.get(feature, {})
        shapes[feature] = {
            "declared_shape": entry.get("shape"),
            "decoded_shape_chw": list(expected_shape),
            "dtype": entry.get("dtype"),
        }
    return shapes


def _clean(extreme: float) -> float | None:
    """Render an observed extreme, mapping the no-observation sentinel to null."""

    if math.isinf(extreme):
        return None
    return extreme


def _sha256(path: Any) -> str:
    import hashlib

    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:  # type: ignore[arg-type]
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _load_json(path: Any) -> dict[str, Any]:
    import json

    text = Path(path).read_text(encoding="utf-8")  # type: ignore[arg-type]
    value = json.loads(text)
    if not isinstance(value, dict):
        raise ContractError(f"metadata root must be an object: {path}")
    return value


def detect_lerobot_version() -> tuple[str | None, str]:
    """Best-effort LeRobot runtime version provenance.

    LeRobot imported from source reports ``__version__ == "unknown"``, so this
    falls back to the sibling ``pyproject.toml`` before giving up.  The cross
    check decode path is independent of LeRobot, so a missing runtime does not
    block the audit - it is recorded as provenance only.
    """

    try:
        import lerobot  # type: ignore
    except Exception:  # noqa: BLE001 - optional provenance
        return None, "not_importable"
    version = getattr(lerobot, "__version__", None)
    if version and version != "unknown":
        return str(version), "runtime_import"
    try:
        from importlib.metadata import PackageNotFoundError, version as dist_version

        resolved = dist_version("lerobot")
        if resolved:
            return str(resolved), "importlib_metadata"
    except Exception:  # noqa: BLE001 - optional provenance
        pass
    try:
        source_path = Path(lerobot.__file__).resolve()  # type: ignore[attr-defined]
    except Exception:  # noqa: BLE001 - optional provenance
        return version or "unknown", "unknown_marker"
    for parent in (source_path.parent, *source_path.parents):
        candidate = parent / "pyproject.toml"
        if candidate.exists():
            try:
                import re

                match = re.search(
                    r'(?m)^version\s*=\s*["\']([^"\']+)["\']',
                    candidate.read_text(encoding="utf-8"),
                )
                if match:
                    return str(match.group(1)), "source_pyproject"
            except Exception:  # noqa: BLE001 - optional provenance
                break
    return version or "unknown", "unknown_marker"


def _capture_cpu_device_semantics(offline_env: dict[str, str]) -> dict[str, Any]:
    """Record the torch device semantics so a receipt proves a CPU-only decode."""

    import os

    import torch

    return {
        "torch_version": str(torch.__version__),
        "torch_cuda_is_available": bool(torch.cuda.is_available()),
        "torch_get_default_dtype": str(torch.get_default_dtype()),
        "cuda_visible_devices_env": os.environ.get("CUDA_VISIBLE_DEVICES", "<unset>"),
        "offline_env": dict(offline_env),
    }


def _enforce_offline_env() -> dict[str, str]:
    """Assert the Hugging Face offline flags *before* importing LeRobot.

    With these set, ``huggingface_hub.snapshot_download`` raises rather than
    reaching the network, so a missing local file can never silently trigger a
    download.  Returns the flags that were asserted for the receipt.
    """

    import os

    asserted: dict[str, str] = {}
    for key, value in OFFLINE_ENV_FLAGS.items():
        os.environ[key] = value
        asserted[key] = os.environ.get(key, value)
    return asserted


def _required_local_files(root: Path) -> dict[str, Any]:
    """Map human-readable labels to the on-disk files a local load needs."""

    return {
        "meta/info.json": root / "meta" / "info.json",
        "meta/stats.json": root / "meta" / "stats.json",
        "meta/tasks.parquet": root / "meta" / "tasks.parquet",
        "meta/episodes/*.parquet": sorted((root / "meta" / "episodes").rglob("*.parquet")),
        "data/*.parquet": sorted((root / "data").rglob("*.parquet")),
    }


def _prevalidate_local_files(root: Path) -> dict[str, Any]:
    """Fail closed if any required local meta/data file is missing.

    Runs *before* LeRobot is imported so the runtime never reaches its
    ``FileNotFoundError`` -> ``download`` fallback.
    """

    files = _required_local_files(root)
    missing: list[str] = []
    for label, paths in files.items():
        items = paths if isinstance(paths, list) else [paths]
        items = [item for item in items if item is not None]
        if not items or not all(Path(item).exists() for item in items):
            missing.append(label)
    if missing:
        raise ContractError(
            f"local LeRobot dataset under {root} is incomplete; missing {missing} "
            "- refusing to attempt any network load"
        )
    return files


class LeRobotRuntimeFrameSource:
    """Read-only frame source that decodes through the real LeRobot runtime.

    Instantiates ``lerobot.datasets.lerobot_dataset.LeRobotDataset`` with
    ``download_videos=False`` and ``force_cache_sync=False`` so it loads purely
    from local disk.  Episode bounds come from ``dataset.meta.episodes`` using
    the ``dataset_from_index`` / ``dataset_to_index`` columns.  Decoding calls
    ``dataset[index]`` so the receipt reflects the genuine LeRobot decode path
    (``hf_transform_to_torch`` -> ``torchvision.ToTensor`` -> float32 CHW [0,1]).

    Network is fenced off three ways: the required local meta/data files are
    prevalidated, the offline environment flags are asserted *before* LeRobot is
    imported, and any local-load failure is raised as a :class:`ContractError`
    rather than triggering a download.
    """

    LOADER_MODE = "lerobot_runtime"
    DECODE_PATH = (
        "LeRobotDataset.__getitem__ runtime decode "
        "(hf_transform_to_torch -> torchvision.ToTensor -> CHW float32 [0,1]); "
        "loaded locally with download_videos=False, force_cache_sync=False"
    )

    def __init__(self, repo_id: Any, dataset_root: Any) -> None:
        self._root = Path(dataset_root).resolve()
        self._repo_id = str(repo_id)
        self.loader_mode = self.LOADER_MODE
        self.decode_path = self.DECODE_PATH
        # Offline flags FIRST, before any LeRobot import, then prevalidate.
        self._offline_env = _enforce_offline_env()
        self._prevalidated_files = _prevalidate_local_files(self._root)
        self._info_path = self._root / "meta" / "info.json"
        self._stats_path = self._root / "meta" / "stats.json"
        self.info = _load_json(self._info_path)
        self.stats = _load_json(self._stats_path)
        self.info_sha256 = _sha256(self._info_path)
        self.stats_sha256 = _sha256(self._stats_path)
        self.codebase_version = self.info.get("codebase_version")
        self.total_episodes = int(self.info.get("total_episodes", 0))
        self.total_frames = int(self.info.get("total_frames", 0))
        self.lerobot_version, self.lerobot_version_source = detect_lerobot_version()
        self._dataset = self._load_runtime_dataset()
        self.lerobot_class_path = self._dataset_qualname()
        self.len_dataset = int(len(self._dataset))
        self._bounds = self._load_episode_bounds_from_meta()
        self.cpu_device_semantics = _capture_cpu_device_semantics(self._offline_env)

    def episode_bounds(self) -> dict[int, tuple[int, int]]:
        return dict(self._bounds)

    def _load_runtime_dataset(self) -> Any:
        try:
            from lerobot.datasets.lerobot_dataset import LeRobotDataset
        except Exception as exc:  # noqa: BLE001 - missing runtime dependency
            raise ContractError(
                "lerobot runtime decode requires the lerobot package "
                f"(import failed: {exc!r})"
            ) from exc
        try:
            return LeRobotDataset(
                self._repo_id,
                root=self._root,
                download_videos=False,
                force_cache_sync=False,
            )
        except Exception as exc:  # noqa: BLE001 - any local-load failure fails closed
            raise ContractError(
                "local LeRobotDataset load failed and no download was attempted "
                f"(offline_env={self._offline_env}, root={self._root}): {exc!r}"
            ) from exc

    def _dataset_qualname(self) -> str:
        cls = type(self._dataset)
        return f"{cls.__module__}.{cls.__qualname__}"

    def _load_episode_bounds_from_meta(self) -> dict[int, tuple[int, int]]:
        """Return ``episode_index -> (dataset_from_index, length)``.

        ``length`` is derived from ``dataset_to_index - dataset_from_index`` as
        recorded in ``dataset.meta.episodes``.
        """

        episodes = self._dataset.meta.episodes
        episode_index = list(episodes["episode_index"])
        from_index = list(episodes["dataset_from_index"])
        to_index = list(episodes["dataset_to_index"])
        bounds: dict[int, tuple[int, int]] = {}
        for episode, start, end in zip(episode_index, from_index, to_index):
            bounds[int(episode)] = (int(start), int(end) - int(start))
        if not bounds:
            raise ContractError(
                f"dataset.meta.episodes carried no episode bounds for {self._root}"
            )
        return bounds

    def decode(self, global_index: int) -> DecodedFrame:
        try:
            item = self._dataset[int(global_index)]
        except Exception as exc:  # noqa: BLE001 - auditable decode failure
            raise ContractError(
                f"LeRobot runtime decode failed for index {global_index}: {exc!r}"
            ) from exc
        images = {
            feature: self._tensor_summary(item[feature])
            for feature in (
                "observation.images.env_cam",
                "observation.images.left_wrist_cam",
                "observation.images.right_wrist_cam",
            )
        }
        return DecodedFrame(
            global_index=int(item["index"].item()),
            observation_state=_vector_from_item(item["observation.state"]),
            action=_vector_from_item(item["action"]),
            images=images,
            frame_index=_int_or_none(item.get("frame_index")),
            timestamp=_float_or_none(item.get("timestamp")),
            episode_index=_int_or_none(item.get("episode_index")),
        )

    @staticmethod
    def _tensor_summary(tensor: Any) -> DecodedImage:
        import torch

        shape = tuple(int(dim) for dim in tensor.shape)
        finite = bool(torch.isfinite(tensor).all())
        return DecodedImage(
            shape=shape,
            finite=finite,
            min_value=float(tensor.min()),
            max_value=float(tensor.max()),
        )


def _vector_from_item(tensor: Any) -> list[float]:
    values = tensor.tolist() if hasattr(tensor, "tolist") else list(tensor)
    return [float(component) for component in values]


def _int_or_none(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value.item() if hasattr(value, "item") else value)
    except (TypeError, ValueError):
        return None


def _float_or_none(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value.item() if hasattr(value, "item") else value)
    except (TypeError, ValueError):
        return None


class LeRobotSampleFrameSource:
    """Read-only, no-network cross-check frame source over a local LeRobot dataset.

    The *cross-check* decode path: the inline parquet image ``bytes`` (or
    on-disk ``path`` fallback) -> PIL RGB ->
    ``torchvision.transforms.functional.to_tensor`` -> float32 CHW in [0,1].
    This decode is deliberately independent of the LeRobot runtime so it stays
    version-stable across LeRobot 0.4.2 and 0.4.4 image datasets and never
    downloads or mutates anything.
    """

    LOADER_MODE = "parquet_crosscheck"
    DECODE_PATH = (
        "direct parquet cell read + torchvision.ToTensor -> CHW float32 [0,1] "
        "(version-stable cross-check; does NOT use the LeRobot runtime)"
    )

    def __init__(self, dataset_root: Any) -> None:
        self._root = Path(dataset_root).resolve()
        self.loader_mode = self.LOADER_MODE
        self.decode_path = self.DECODE_PATH
        self.lerobot_class_path = None
        self.len_dataset = None
        self._info_path = self._root / "meta" / "info.json"
        self._stats_path = self._root / "meta" / "stats.json"
        if not self._info_path.exists():
            raise ContractError(f"missing LeRobot info.json: {self._info_path}")
        if not self._stats_path.exists():
            raise ContractError(f"missing LeRobot stats.json: {self._stats_path}")
        self.info = _load_json(self._info_path)
        self.stats = _load_json(self._stats_path)
        self.info_sha256 = _sha256(self._info_path)
        self.stats_sha256 = _sha256(self._stats_path)
        self.codebase_version = self.info.get("codebase_version")
        self.total_episodes = int(self.info.get("total_episodes", 0))
        self.total_frames = int(self.info.get("total_frames", 0))
        self.lerobot_version, self.lerobot_version_source = detect_lerobot_version()
        self._bounds = self._load_episode_bounds()
        self._index_location, self._row_group_cache = self._build_index_map(), {}
        self.cpu_device_semantics = self._capture_cpu_device_semantics()

    def _capture_cpu_device_semantics(self) -> dict[str, Any]:
        try:
            return _capture_cpu_device_semantics({})
        except Exception:  # noqa: BLE001 - torch optional for the cross check provenance
            return {"torch_cuda_is_available": None}

    def episode_bounds(self) -> dict[int, tuple[int, int]]:
        return dict(self._bounds)

    def _load_episode_bounds(self) -> dict[int, tuple[int, int]]:
        """Return ``episode_index -> (first_global_index, length)``."""

        try:
            import pyarrow.parquet as pq
        except ImportError as exc:
            raise ContractError("sample decode requires pyarrow") from exc
        episodes_dir = self._root / "meta" / "episodes"
        bounds: dict[int, tuple[int, int]] = {}
        if episodes_dir.exists():
            for parquet_path in sorted(episodes_dir.rglob("*.parquet")):
                table = pq.read_table(parquet_path)
                for row in table.to_pylist():
                    episode_index = row.get("episode_index")
                    length = row.get("length")
                    from_index = row.get("dataset_from_index")
                    if (
                        not isinstance(episode_index, int)
                        or not isinstance(length, int)
                        or length < 0
                    ):
                        continue
                    if isinstance(from_index, int):
                        first_global = from_index
                    elif isinstance(row.get("data/file_index"), int):
                        first_global = int(row["data/file_index"])
                    else:
                        first_global = None
                    if first_global is None:
                        continue
                    bounds[int(episode_index)] = (int(first_global), int(length))
        if bounds:
            return bounds
        # Fallback: derive contiguous bounds from the data parquet index column.
        index_to_episode = self._scan_index_column(pq, with_episode=True)
        if not index_to_episode:
            raise ContractError(
                f"could not determine episode bounds for {self._root}"
            )
        episodes: dict[int, list[int]] = {}
        for global_index, episode in index_to_episode.items():
            episodes.setdefault(episode, []).append(global_index)
        for episode, indices in episodes.items():
            ordered = sorted(indices)
            bounds[episode] = (ordered[0], len(ordered))
        return bounds

    def _data_parquets(self) -> list[Any]:
        files = sorted((self._root / "data").rglob("*.parquet"))
        if not files:
            raise ContractError(
                f"no LeRobot parquet files found below {self._root / 'data'}"
            )
        return files

    def _scan_index_column(self, pq: Any, *, with_episode: bool) -> dict[int, int]:
        columns = ["index"] + (["episode_index"] if with_episode else [])
        mapping: dict[int, int] = {}
        for parquet_path in self._data_parquets():
            table = pq.read_table(parquet_path, columns=columns)
            indices = table.column("index").to_pylist()
            episodes = (
                table.column("episode_index").to_pylist() if with_episode else [0] * len(indices)
            )
            for global_index, episode in zip(indices, episodes):
                mapping[int(global_index)] = int(episode)
        return mapping

    def _build_index_map(self) -> dict[int, tuple[Any, int]]:
        import pyarrow.parquet as pq

        locations: dict[int, tuple[Any, int]] = {}
        for parquet_path in self._data_parquets():
            table = pq.read_table(parquet_path, columns=["index"])
            for offset, global_index in enumerate(table.column("index").to_pylist()):
                locations[int(global_index)] = (parquet_path, int(offset))
        return locations

    def _row_group_table(self, parquet_path: Any, columns: list[str]) -> Any:
        import pyarrow.parquet as pq

        parquet_file = pq.ParquetFile(parquet_path)
        if parquet_file.num_row_groups != 1:
            raise ContractError(
                f"{parquet_path.name} must contain exactly one row group for bounded decode"
            )
        return parquet_file.read_row_group(0, columns=columns)

    def decode(self, global_index: int) -> DecodedFrame:
        if global_index not in self._index_location:
            raise ContractError(f"global index {global_index} is not present in the dataset")
        parquet_path, offset = self._index_location[global_index]
        needed_columns = [
            "index",
            "frame_index",
            "timestamp",
            "episode_index",
            "observation.state",
            "action",
            "observation.images.env_cam",
            "observation.images.left_wrist_cam",
            "observation.images.right_wrist_cam",
        ]
        cache_key = str(parquet_path)
        table = self._row_group_cache.get(cache_key)
        if table is None:
            table = self._row_group_table(parquet_path, needed_columns)
            self._row_group_cache[cache_key] = table
        try:
            row = {column: table.column(column)[offset].as_py() for column in needed_columns}
        except IndexError as exc:
            raise ContractError(
                f"global index {global_index} maps to out-of-range row {offset}"
            ) from exc
        images = {
            feature: self._decode_image(feature, row[feature])
            for feature in (
                "observation.images.env_cam",
                "observation.images.left_wrist_cam",
                "observation.images.right_wrist_cam",
            )
        }
        state = [float(component) for component in row["observation.state"]]
        action = [float(component) for component in row["action"]]
        return DecodedFrame(
            global_index=int(row["index"]),
            observation_state=state,
            action=action,
            images=images,
            frame_index=_int_or_none(row.get("frame_index")),
            timestamp=_float_or_none(row.get("timestamp")),
            episode_index=_int_or_none(row.get("episode_index")),
        )

    def _decode_image(self, feature: str, cell: Any) -> DecodedImage:
        import io

        from PIL import Image

        raw: bytes | None = None
        if isinstance(cell, dict):
            raw = cell.get("bytes")
            if raw is None and cell.get("path"):
                raw = self._read_image_path(feature, cell["path"])
        if raw is None:
            raise ContractError(f"{feature} image cell has no decodable bytes or path")
        image = Image.open(io.BytesIO(raw)).convert("RGB")
        shape, finite, min_value, max_value = self._tensor_summary(image)
        return DecodedImage(shape=shape, finite=finite, min_value=min_value, max_value=max_value)

    def _read_image_path(self, feature: str, path_value: Any) -> bytes | None:
        candidate = Path(str(path_value))
        if not candidate.is_absolute():
            candidate = self._root / candidate
        if candidate.exists():
            return candidate.read_bytes()
        legacy = self._root / "images" / feature / Path(str(path_value)).name
        if legacy.exists():
            return legacy.read_bytes()
        return None

    @staticmethod
    def _tensor_summary(image: Any) -> tuple[tuple[int, int, int], bool, float, float]:
        try:
            import torch
            from torchvision.transforms.functional import to_tensor
        except ImportError as exc:
            raise ContractError(
                "image decode requires torch and torchvision (CPU build is sufficient)"
            ) from exc
        tensor = to_tensor(image)
        shape = tuple(int(dim) for dim in tensor.shape)
        finite = bool(torch.isfinite(tensor).all())
        return shape, finite, float(tensor.min()), float(tensor.max())
