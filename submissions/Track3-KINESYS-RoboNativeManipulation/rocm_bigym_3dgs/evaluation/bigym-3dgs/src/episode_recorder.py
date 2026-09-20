#!/usr/bin/env python3
"""Crash-aware, per-episode recording for BiGym policy evaluation.

The recorder intentionally keeps diagnostics separate from the evaluator's
compact ``results.json``.  Each episode owns an append-only JSONL step log, one
video per policy camera, and an atomically replaced manifest.  A graceful
interruption can be resumed in a new video segment; an unclean interruption is
reported as ``restart_required`` when its video segment cannot be trusted.

Only the Python standard library, NumPy, and OpenCV are used.  OpenCV is loaded
lazily so JSON/manifest contract tests can run on machines without the BiGym
rendering dependencies installed.
"""

from __future__ import annotations

import base64
from collections.abc import Mapping, Sequence
from datetime import date, datetime, timezone
from enum import Enum
import hashlib
import json
import math
import os
from pathlib import Path
import shutil
import time
from typing import Any
import uuid

import numpy as np


SCHEMA_VERSION = 1
DEFAULT_CAMERA_NAMES = ("head", "left_wrist", "right_wrist")
TERMINAL_STATUSES = frozenset({"complete", "failed"})
RESUMABLE_STATUSES = frozenset({"recording", "interrupted"})
_NP_INTEGER_TYPES = (
    (getattr(np, "integer"),) if hasattr(np, "integer") else ()
)
_NP_FLOAT_TYPES = (
    (getattr(np, "floating"),) if hasattr(np, "floating") else ()
)
_NP_ARRAY_TYPES = (
    (getattr(np, "ndarray"),) if hasattr(np, "ndarray") else ()
)
_NP_GENERIC_TYPES = (
    (getattr(np, "generic"),) if hasattr(np, "generic") else ()
)


class EpisodeRecorderError(RuntimeError):
    """Base error raised by the episode recorder."""


class EpisodeAlreadyComplete(EpisodeRecorderError):
    """Raised when resume is requested for a terminal episode."""


class EpisodeRestartRequired(EpisodeRecorderError):
    """Raised when an interrupted episode cannot be resumed safely."""


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _nonfinite_float(value: float) -> str:
    if math.isnan(value):
        return "NaN"
    return "Infinity" if value > 0 else "-Infinity"


def json_safe(value: Any) -> Any:
    """Convert simulator/policy metadata into strict, loss-aware JSON values.

    NumPy values, arrays, paths, datetimes, enums, bytes, sets, and nested
    mappings are supported.  JSON has no representation for NaN or infinity,
    so those values become tagged strings rather than emitting non-standard
    JSON tokens.  Unknown objects are represented by their type and ``repr``.
    Cycles are represented explicitly instead of recursing forever.
    """

    def convert(item: Any, seen: set[int]) -> Any:
        if item is None or isinstance(item, (bool, str)):
            return item
        if isinstance(item, _NP_GENERIC_TYPES):
            return convert(item.item(), seen)
        if isinstance(item, (int, *_NP_INTEGER_TYPES)) and not isinstance(item, bool):
            return int(item)
        if isinstance(item, (float, *_NP_FLOAT_TYPES)):
            number = float(item)
            return number if math.isfinite(number) else _nonfinite_float(number)
        if isinstance(item, Path):
            return str(item)
        if isinstance(item, (datetime, date)):
            return item.isoformat()
        if isinstance(item, Enum):
            return convert(item.value, seen)
        if isinstance(item, (bytes, bytearray, memoryview)):
            return {
                "__type__": "bytes",
                "base64": base64.b64encode(bytes(item)).decode("ascii"),
            }

        identity = id(item)
        if identity in seen:
            return {"__type__": "cycle", "python_type": type(item).__name__}

        if isinstance(item, _NP_ARRAY_TYPES):
            seen.add(identity)
            try:
                return convert(item.tolist(), seen)
            finally:
                seen.remove(identity)
        if isinstance(item, Mapping):
            seen.add(identity)
            try:
                return {
                    str(convert(key, seen)): convert(child, seen)
                    for key, child in item.items()
                }
            finally:
                seen.remove(identity)
        if isinstance(item, (list, tuple)):
            seen.add(identity)
            try:
                return [convert(child, seen) for child in item]
            finally:
                seen.remove(identity)
        if isinstance(item, (set, frozenset)):
            seen.add(identity)
            try:
                ordered = sorted(item, key=lambda child: repr(child))
                return [convert(child, seen) for child in ordered]
            finally:
                seen.remove(identity)
        if isinstance(item, Sequence):
            seen.add(identity)
            try:
                return [convert(child, seen) for child in item]
            finally:
                seen.remove(identity)

        try:
            representation = repr(item)
        except Exception as error:  # pragma: no cover - exceptionally defensive.
            representation = f"<repr failed: {type(error).__name__}: {error}>"
        return {
            "__type__": "python_object",
            "python_type": f"{type(item).__module__}.{type(item).__qualname__}",
            "repr": representation,
        }

    return convert(value, set())


def sha256_file(path: str | Path) -> str:
    """Return the SHA-256 digest of one file."""

    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _fsync_directory(path: Path) -> None:
    try:
        descriptor = os.open(path, os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(descriptor)
    except OSError:
        pass
    finally:
        os.close(descriptor)


def _fsync_file(path: Path) -> None:
    try:
        descriptor = os.open(path, os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(descriptor)
    except OSError:
        pass
    finally:
        os.close(descriptor)


def _atomic_write_json(path: Path, payload: Mapping[str, Any], fsync: bool) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.{uuid.uuid4().hex}.tmp")
    encoded = (
        json.dumps(json_safe(payload), indent=2, sort_keys=True, allow_nan=False)
        + "\n"
    ).encode("utf-8")
    try:
        with temporary.open("xb") as stream:
            stream.write(encoded)
            stream.flush()
            if fsync:
                os.fsync(stream.fileno())
        os.replace(temporary, path)
        if fsync:
            _fsync_directory(path.parent)
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass


def _append_json_line(path: Path, payload: Mapping[str, Any], fsync: bool) -> int:
    """Append exactly one strict-JSON record and return the new file size."""

    encoded = (
        json.dumps(json_safe(payload), separators=(",", ":"), allow_nan=False)
        + "\n"
    ).encode("utf-8")
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o644)
    try:
        view = memoryview(encoded)
        while view:
            written = os.write(descriptor, view)
            if written <= 0:
                raise OSError("append-only JSONL write made no progress")
            view = view[written:]
        if fsync:
            os.fsync(descriptor)
    finally:
        os.close(descriptor)
    return path.stat().st_size


def _scan_jsonl(path: Path, episode_index: int, seed: int | None) -> dict[str, Any]:
    if not path.exists():
        return {
            "path": str(path),
            "count": 0,
            "last_step_index": None,
            "valid_bytes": 0,
            "bytes": 0,
            "partial_tail_bytes": 0,
            "error": None,
        }

    count = 0
    valid_bytes = 0
    last_step_index: int | None = None
    error: str | None = None
    with path.open("rb") as stream:
        while True:
            start = stream.tell()
            line = stream.readline()
            if not line:
                break
            end = stream.tell()
            if not line.endswith(b"\n"):
                error = f"partial JSONL tail at byte {start}"
                break
            try:
                record = json.loads(line)
            except (UnicodeDecodeError, json.JSONDecodeError) as parse_error:
                error = f"invalid JSONL record {count} at byte {start}: {parse_error}"
                break
            if not isinstance(record, dict):
                error = f"JSONL record {count} is not an object"
                break
            expected_step = count
            if record.get("step_index") != expected_step:
                error = (
                    f"JSONL step_index is not contiguous at record {count}: "
                    f"{record.get('step_index')!r} != {expected_step}"
                )
                break
            if record.get("episode_index") != episode_index:
                error = f"JSONL episode_index mismatch at record {count}"
                break
            if seed is not None and record.get("seed") != seed:
                error = f"JSONL seed mismatch at record {count}"
                break
            count += 1
            last_step_index = expected_step
            valid_bytes = end

    total_bytes = path.stat().st_size
    return {
        "path": str(path),
        "count": count,
        "last_step_index": last_step_index,
        "valid_bytes": valid_bytes,
        "bytes": total_bytes,
        "partial_tail_bytes": total_bytes - valid_bytes,
        "error": error,
    }


def _load_cv2() -> Any:
    try:
        import cv2  # type: ignore
    except ModuleNotFoundError as error:
        raise EpisodeRecorderError(
            "OpenCV is required when recording or inspecting camera videos"
        ) from error
    return cv2


def _fourcc_label(value: float | int) -> str | None:
    integer = int(value)
    if integer <= 0:
        return None
    label = "".join(chr((integer >> (8 * offset)) & 0xFF) for offset in range(4))
    return label.strip("\x00") or None


def probe_video(path: str | Path, *, decode: bool = True) -> dict[str, Any]:
    """Return stable video metadata, optional full decode count, and SHA-256."""

    source = Path(path)
    report: dict[str, Any] = {
        "path": str(source),
        "exists": source.is_file(),
        "bytes": source.stat().st_size if source.is_file() else 0,
        "sha256": sha256_file(source) if source.is_file() else None,
        "opened": False,
        "codec_fourcc": None,
        "width": None,
        "height": None,
        "fps": None,
        "declared_frames": None,
        "decoded_frames": None,
        "passed": False,
        "error": None,
    }
    if not source.is_file():
        report["error"] = "video file is missing"
        return report

    cv2 = _load_cv2()
    capture = cv2.VideoCapture(str(source))
    try:
        if not capture.isOpened():
            report["error"] = "OpenCV could not open video"
            return report
        report["opened"] = True
        report["codec_fourcc"] = _fourcc_label(capture.get(cv2.CAP_PROP_FOURCC))
        report["width"] = int(round(capture.get(cv2.CAP_PROP_FRAME_WIDTH)))
        report["height"] = int(round(capture.get(cv2.CAP_PROP_FRAME_HEIGHT)))
        report["fps"] = float(capture.get(cv2.CAP_PROP_FPS))
        report["declared_frames"] = int(
            round(capture.get(cv2.CAP_PROP_FRAME_COUNT))
        )
        if decode:
            decoded = 0
            while True:
                ok, _frame = capture.read()
                if not ok:
                    break
                decoded += 1
            report["decoded_frames"] = decoded
        else:
            report["decoded_frames"] = report["declared_frames"]
        dimensions_ok = report["width"] > 0 and report["height"] > 0
        fps_ok = report["fps"] is not None and report["fps"] > 0
        frame_count_ok = (
            report["decoded_frames"] is not None
            and report["decoded_frames"] == report["declared_frames"]
            and report["decoded_frames"] > 0
        )
        report["passed"] = bool(dimensions_ok and fps_ok and frame_count_ok)
        if not report["passed"]:
            report["error"] = "video metadata or full decode validation failed"
        return report
    finally:
        capture.release()


def _episode_dir(root: str | Path, episode_index: int) -> Path:
    if episode_index < 0:
        raise ValueError("episode_index must be non-negative")
    return Path(root).expanduser().resolve() / "episodes" / f"episode-{episode_index:06d}"


def _read_manifest(path: Path) -> tuple[dict[str, Any] | None, str | None]:
    if not path.is_file():
        return None, "manifest.json is missing"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        return None, f"manifest.json is invalid: {type(error).__name__}: {error}"
    if not isinstance(payload, dict):
        return None, "manifest.json is not an object"
    return payload, None


def _video_entries_are_resumable(
    episode_dir: Path,
    manifest: Mapping[str, Any],
) -> tuple[bool, list[str]]:
    errors: list[str] = []
    videos = manifest.get("videos", {})
    if not isinstance(videos, Mapping):
        return False, ["manifest videos is not an object"]
    expected_camera_frames = int(
        manifest.get("steps", {}).get("camera_frame_steps", 0)
        if isinstance(manifest.get("steps"), Mapping)
        else 0
    )
    for camera in manifest.get("camera_names", []):
        camera_record = videos.get(camera, {})
        if not isinstance(camera_record, Mapping):
            errors.append(f"invalid video record for {camera}")
            continue
        camera_total = 0
        for segment in camera_record.get("segments", []):
            if not isinstance(segment, Mapping) or not segment.get("path"):
                errors.append(f"invalid video segment for {camera}")
                continue
            segment_path = episode_dir / str(segment["path"])
            if not segment_path.exists():
                if int(segment.get("frame_count", 0)) > 0:
                    errors.append(f"missing video segment for {camera}: {segment_path}")
                continue
            report = probe_video(segment_path)
            if not report["passed"]:
                errors.append(f"unreadable video segment for {camera}: {segment_path}")
                continue
            expected = int(segment.get("frame_count", report["decoded_frames"]))
            camera_total += expected
            if report["decoded_frames"] != expected:
                errors.append(
                    f"video frame mismatch for {camera}: "
                    f"{report['decoded_frames']} != {expected}"
                )
        if camera_total != expected_camera_frames:
            errors.append(
                f"camera/step frame mismatch for {camera}: "
                f"{camera_total} != {expected_camera_frames}"
            )
    return not errors, errors


def inspect_episode(
    root: str | Path,
    episode_index: int,
    *,
    seed: int | None = None,
) -> dict[str, Any]:
    """Classify an episode as new, terminal, resumable, or restart-required."""

    directory = _episode_dir(root, episode_index)
    if not directory.exists():
        return {
            "state": "new",
            "episode_dir": str(directory),
            "episode_index": episode_index,
            "seed": seed,
        }
    manifest, manifest_error = _read_manifest(directory / "manifest.json")
    if manifest_error or manifest is None:
        return {
            "state": "restart_required",
            "episode_dir": str(directory),
            "episode_index": episode_index,
            "seed": seed,
            "errors": [manifest_error],
        }

    errors: list[str] = []
    if manifest.get("schema_version") != SCHEMA_VERSION:
        errors.append("unsupported manifest schema_version")
    if manifest.get("episode_index") != episode_index:
        errors.append("manifest episode_index mismatch")
    recorded_seed = manifest.get("seed")
    if seed is not None and recorded_seed != seed:
        errors.append(f"manifest seed mismatch: {recorded_seed!r} != {seed!r}")
    steps = _scan_jsonl(directory / "steps.jsonl", episode_index, recorded_seed)
    manifest_steps = manifest.get("steps", {})
    if isinstance(manifest_steps, Mapping):
        recorded_count = int(manifest_steps.get("count", 0))
        if recorded_count != steps["count"] and not steps["partial_tail_bytes"]:
            errors.append(
                f"manifest/JSONL step count mismatch: {recorded_count} != {steps['count']}"
            )
    else:
        errors.append("manifest steps is not an object")

    status = str(manifest.get("status", "unknown"))
    if status in TERMINAL_STATUSES:
        recorded_sha256 = (
            manifest_steps.get("sha256")
            if isinstance(manifest_steps, Mapping)
            else None
        )
        if recorded_sha256 is not None:
            if not (directory / "steps.jsonl").is_file():
                errors.append("terminal steps.jsonl is missing")
            elif recorded_sha256 != sha256_file(directory / "steps.jsonl"):
                errors.append("terminal steps.jsonl SHA-256 mismatch")
        videos = manifest.get("videos", {})
        camera_frame_steps = (
            int(manifest_steps.get("camera_frame_steps", 0))
            if isinstance(manifest_steps, Mapping)
            else 0
        )
        for camera in manifest.get("camera_names", []):
            final = videos.get(camera, {}).get("final") if isinstance(videos, Mapping) else None
            if final is None:
                if camera_frame_steps:
                    errors.append(f"terminal video metadata is missing for {camera}")
                continue
            video_path = directory / str(final.get("path", ""))
            if not video_path.is_file():
                errors.append(f"terminal video is missing for {camera}")
                continue
            actual_video = probe_video(video_path)
            if not actual_video.get("passed"):
                errors.append(f"terminal video decode failed for {camera}")
                continue
            for field in (
                "sha256",
                "codec_fourcc",
                "width",
                "height",
                "declared_frames",
                "decoded_frames",
            ):
                if final.get(field) != actual_video.get(field):
                    errors.append(
                        f"terminal video {field} mismatch for {camera}: "
                        f"{final.get(field)!r} != {actual_video.get(field)!r}"
                    )
            if not math.isclose(
                float(final.get("fps", 0)), float(actual_video.get("fps", 0)), rel_tol=1e-6
            ):
                errors.append(f"terminal video FPS mismatch for {camera}")
        state = "restart_required" if errors or steps["error"] else status
    elif status in RESUMABLE_STATUSES:
        videos_ok, video_errors = _video_entries_are_resumable(directory, manifest)
        errors.extend(video_errors)
        if steps["error"] and not steps["partial_tail_bytes"]:
            errors.append(str(steps["error"]))
        state = "resumable" if videos_ok and not errors else "restart_required"
    else:
        errors.append(f"unsupported manifest status: {status}")
        state = "restart_required"

    return {
        "state": state,
        "episode_dir": str(directory),
        "episode_index": episode_index,
        "seed": recorded_seed,
        "manifest_status": status,
        "steps": steps,
        "errors": errors,
        "manifest": manifest,
    }


def _as_hwc_rgb(frame: np.ndarray, camera: str) -> np.ndarray:
    image = np.asarray(frame)
    if image.ndim != 3:
        raise ValueError(f"{camera} frame must have three dimensions, got {image.shape}")
    if image.shape[-1] == 3:
        hwc = image
    elif image.shape[0] == 3:
        hwc = np.moveaxis(image, 0, -1)
    else:
        raise ValueError(f"{camera} frame must be HWC or CHW RGB, got {image.shape}")
    if hwc.dtype != np.uint8:
        raise ValueError(f"{camera} frame must use uint8, got {hwc.dtype}")
    if hwc.shape[0] < 1 or hwc.shape[1] < 1:
        raise ValueError(f"{camera} frame is empty")
    return np.ascontiguousarray(hwc)


class _VideoSegmentWriter:
    def __init__(self, path: Path, fps: float, codec: str) -> None:
        self.path = path
        self.fps = fps
        self.codec = codec
        self.frame_count = 0
        self.height: int | None = None
        self.width: int | None = None
        self._writer: Any = None

    def write(self, frame: np.ndarray, camera: str) -> None:
        rgb = _as_hwc_rgb(frame, camera)
        height, width = rgb.shape[:2]
        if self._writer is None:
            cv2 = _load_cv2()
            self.path.parent.mkdir(parents=True, exist_ok=True)
            fourcc = cv2.VideoWriter_fourcc(*self.codec)
            self._writer = cv2.VideoWriter(
                str(self.path), fourcc, self.fps, (width, height)
            )
            if not self._writer.isOpened():
                self._writer.release()
                self._writer = None
                raise EpisodeRecorderError(f"failed to open video writer: {self.path}")
            self.height = height
            self.width = width
        elif (height, width) != (self.height, self.width):
            raise ValueError(
                f"{camera} frame resolution changed from "
                f"{(self.height, self.width)} to {(height, width)}"
            )
        self._writer.write(np.ascontiguousarray(rgb[:, :, ::-1]))
        self.frame_count += 1

    def close(self) -> None:
        if self._writer is not None:
            self._writer.release()
            self._writer = None


class EpisodeRecorder:
    """Record one evaluation episode with append-only steps and three videos."""

    def __init__(
        self,
        root: str | Path,
        episode_index: int,
        seed: int,
        fps: float,
        *,
        camera_names: Sequence[str] = DEFAULT_CAMERA_NAMES,
        resume: bool = False,
        fsync: bool = True,
        video_codec: str = "mp4v",
    ) -> None:
        if fps <= 0 or not math.isfinite(float(fps)):
            raise ValueError("fps must be a finite positive value")
        names = tuple(str(name) for name in camera_names)
        if not names or len(set(names)) != len(names):
            raise ValueError("camera_names must be non-empty and unique")
        if any(not name or "/" in name or "\\" in name for name in names):
            raise ValueError("camera names must be non-empty path-safe labels")
        if len(video_codec) != 4:
            raise ValueError("video_codec must be a four-character code")

        self.root = Path(root).expanduser().resolve()
        self.episode_index = int(episode_index)
        self.seed = int(seed)
        self.fps = float(fps)
        self.camera_names = names
        self.fsync = bool(fsync)
        self.video_codec = video_codec
        self._episode_dir = _episode_dir(self.root, self.episode_index)
        self._manifest_path = self._episode_dir / "manifest.json"
        self._steps_path = self._episode_dir / "steps.jsonl"
        self._terminal = False
        self._closed = False
        self._session_started = time.perf_counter()
        self._writers: dict[str, _VideoSegmentWriter] = {}

        report = inspect_episode(
            self.root, self.episode_index, seed=self.seed
        )
        if report["state"] == "new":
            if resume:
                raise FileNotFoundError(
                    f"cannot resume missing episode: {self._episode_dir}"
                )
            self._episode_dir.mkdir(parents=True, exist_ok=False)
            (self._episode_dir / "videos").mkdir()
            self._step_count = 0
            self._camera_frame_steps = 0
            self._session_index = 0
            created_at = _utc_now()
            self._manifest: dict[str, Any] = {
                "schema_version": SCHEMA_VERSION,
                "episode_index": self.episode_index,
                "seed": self.seed,
                "status": "recording",
                "created_at": created_at,
                "updated_at": created_at,
                "finished_at": None,
                "fps": self.fps,
                "camera_names": list(self.camera_names),
                "session_count": 1,
                "current_session": self._session_index,
                "steps": {
                    "path": "steps.jsonl",
                    "count": 0,
                    "last_step_index": None,
                    "bytes": 0,
                    "sha256": None,
                    "camera_frame_steps": 0,
                },
                "videos": {
                    camera: {"segments": [], "final": None}
                    for camera in self.camera_names
                },
                "result": None,
                "failure_reason": None,
                "failure_detail": None,
                "last_error": None,
                "recovery": [],
            }
        else:
            if not resume:
                raise FileExistsError(f"episode already exists: {self._episode_dir}")
            if report["state"] in TERMINAL_STATUSES:
                raise EpisodeAlreadyComplete(
                    f"episode is already terminal ({report['state']}): {self._episode_dir}"
                )
            if report["state"] != "resumable":
                raise EpisodeRestartRequired(
                    f"episode cannot be resumed safely: {report.get('errors', [])}"
                )
            self._manifest = dict(report["manifest"])
            if tuple(self._manifest.get("camera_names", ())) != self.camera_names:
                raise EpisodeRestartRequired("camera_names changed across resume")
            if not math.isclose(float(self._manifest.get("fps", 0)), self.fps):
                raise EpisodeRestartRequired("fps changed across resume")
            steps = report["steps"]
            if steps["partial_tail_bytes"]:
                with self._steps_path.open("r+b") as stream:
                    stream.truncate(steps["valid_bytes"])
                    stream.flush()
                    if self.fsync:
                        os.fsync(stream.fileno())
                self._manifest.setdefault("recovery", []).append(
                    {
                        "at": _utc_now(),
                        "action": "truncate_partial_jsonl_tail",
                        "trimmed_bytes": steps["partial_tail_bytes"],
                    }
                )
            self._step_count = int(steps["count"])
            self._camera_frame_steps = int(
                self._manifest.get("steps", {}).get("camera_frame_steps", 0)
            )
            self._session_index = int(self._manifest.get("session_count", 0))
            self._manifest["session_count"] = self._session_index + 1
            self._manifest["current_session"] = self._session_index
            self._manifest["status"] = "recording"
            self._manifest["last_error"] = None
            self._manifest["finished_at"] = None

        self._start_video_segments()
        self._checkpoint_manifest()

    @property
    def episode_dir(self) -> Path:
        return self._episode_dir

    @property
    def step_count(self) -> int:
        return self._step_count

    @property
    def next_step_index(self) -> int:
        return self._step_count

    @property
    def manifest(self) -> dict[str, Any]:
        return json.loads(json.dumps(self._manifest))

    def _start_video_segments(self) -> None:
        for camera in self.camera_names:
            relative = f"videos/{camera}.segment-{self._session_index:04d}.mp4"
            descriptor = {
                "session": self._session_index,
                "path": relative,
                "frame_count": 0,
                "closed": False,
                "metadata": None,
            }
            self._manifest["videos"][camera]["segments"].append(descriptor)
            self._writers[camera] = _VideoSegmentWriter(
                self._episode_dir / relative,
                self.fps,
                self.video_codec,
            )

    def _checkpoint_manifest(self) -> None:
        steps = self._manifest["steps"]
        steps["count"] = self._step_count
        steps["last_step_index"] = (
            self._step_count - 1 if self._step_count else None
        )
        steps["bytes"] = self._steps_path.stat().st_size if self._steps_path.exists() else 0
        steps["camera_frame_steps"] = self._camera_frame_steps
        for camera, writer in self._writers.items():
            segments = self._manifest["videos"][camera]["segments"]
            segments[-1]["frame_count"] = writer.frame_count
        self._manifest["updated_at"] = _utc_now()
        _atomic_write_json(self._manifest_path, self._manifest, self.fsync)

    def _require_open(self) -> None:
        if self._closed or self._terminal:
            raise EpisodeRecorderError("episode recorder is closed")

    def append_step(
        self,
        record: Mapping[str, Any],
        camera_frames: Mapping[str, np.ndarray] | None = None,
    ) -> dict[str, Any]:
        """Append one step record and its synchronized policy-camera frames."""

        self._require_open()
        if not isinstance(record, Mapping):
            raise TypeError("record must be a mapping")
        step_index = record.get("step_index", self._step_count)
        if step_index != self._step_count:
            raise ValueError(
                f"step_index must be contiguous: {step_index!r} != {self._step_count}"
            )
        if "episode_index" in record and record["episode_index"] != self.episode_index:
            raise ValueError("record episode_index does not match recorder")
        if "seed" in record and record["seed"] != self.seed:
            raise ValueError("record seed does not match recorder")

        prepared_frames: dict[str, np.ndarray] | None = None
        if camera_frames is not None:
            if set(camera_frames) != set(self.camera_names):
                raise ValueError(
                    "camera_frames must contain exactly "
                    f"{sorted(self.camera_names)}, got {sorted(camera_frames)}"
                )
            prepared_frames = {
                camera: _as_hwc_rgb(camera_frames[camera], camera)
                for camera in self.camera_names
            }

        payload = dict(record)
        payload["schema_version"] = SCHEMA_VERSION
        payload["episode_index"] = self.episode_index
        payload["seed"] = self.seed
        payload["step_index"] = self._step_count
        payload.setdefault("timestamp_utc", _utc_now())
        payload.setdefault(
            "monotonic_s", time.perf_counter() - self._session_started
        )
        payload["camera_frames_recorded"] = prepared_frames is not None
        safe_payload = json_safe(payload)

        try:
            if prepared_frames is not None:
                for camera in self.camera_names:
                    self._writers[camera].write(prepared_frames[camera], camera)
            _append_json_line(self._steps_path, safe_payload, self.fsync)
        except Exception as error:
            self._manifest["last_error"] = f"{type(error).__name__}: {error}"
            self._checkpoint_manifest()
            raise

        self._step_count += 1
        if prepared_frames is not None:
            self._camera_frame_steps += 1
        self._checkpoint_manifest()
        return safe_payload

    def _close_video_segments(self) -> None:
        for camera, writer in self._writers.items():
            writer.close()
            descriptor = self._manifest["videos"][camera]["segments"][-1]
            descriptor["frame_count"] = writer.frame_count
            descriptor["closed"] = True
            if writer.frame_count:
                metadata = probe_video(writer.path)
                metadata["path"] = str(writer.path.relative_to(self._episode_dir))
                descriptor["metadata"] = metadata
            else:
                descriptor["metadata"] = None

    def _merge_camera_segments(self, camera: str) -> dict[str, Any] | None:
        descriptors = self._manifest["videos"][camera]["segments"]
        segment_paths = [
            self._episode_dir / descriptor["path"]
            for descriptor in descriptors
            if int(descriptor.get("frame_count", 0)) > 0
        ]
        if not segment_paths:
            return None
        cv2 = _load_cv2()
        expected_frames = sum(
            int(descriptor.get("frame_count", 0)) for descriptor in descriptors
        )
        final_path = self._episode_dir / "videos" / f"{camera}.mp4"
        temporary = final_path.with_name(f".{final_path.name}.{uuid.uuid4().hex}.tmp.mp4")
        try:
            if len(segment_paths) == 1:
                shutil.copyfile(segment_paths[0], temporary)
            else:
                writer = None
                expected_resolution: tuple[int, int] | None = None
                try:
                    for segment_path in segment_paths:
                        capture = cv2.VideoCapture(str(segment_path))
                        try:
                            if not capture.isOpened():
                                raise EpisodeRecorderError(
                                    f"cannot merge unreadable video: {segment_path}"
                                )
                            width = int(round(capture.get(cv2.CAP_PROP_FRAME_WIDTH)))
                            height = int(round(capture.get(cv2.CAP_PROP_FRAME_HEIGHT)))
                            if writer is None:
                                expected_resolution = (width, height)
                                writer = cv2.VideoWriter(
                                    str(temporary),
                                    cv2.VideoWriter_fourcc(*self.video_codec),
                                    self.fps,
                                    (width, height),
                                )
                                if not writer.isOpened():
                                    raise EpisodeRecorderError(
                                        f"cannot open merged video: {temporary}"
                                    )
                            elif (width, height) != expected_resolution:
                                raise EpisodeRecorderError(
                                    f"video resolution changed across {camera} segments: "
                                    f"{(width, height)} != {expected_resolution}"
                                )
                            while True:
                                ok, frame = capture.read()
                                if not ok:
                                    break
                                writer.write(frame)
                        finally:
                            capture.release()
                finally:
                    if writer is not None:
                        writer.release()
            os.replace(temporary, final_path)
            if self.fsync:
                _fsync_file(final_path)
                _fsync_directory(final_path.parent)
        finally:
            try:
                temporary.unlink()
            except FileNotFoundError:
                pass
        metadata = probe_video(final_path)
        if not metadata["passed"]:
            raise EpisodeRecorderError(
                f"final video validation failed for {camera}: {metadata['error']}"
            )
        if metadata["decoded_frames"] != expected_frames:
            raise EpisodeRecorderError(
                f"final video frame mismatch for {camera}: "
                f"{metadata['decoded_frames']} != {expected_frames}"
            )
        metadata["path"] = str(final_path.relative_to(self._episode_dir))
        return metadata

    def _cleanup_video_segments(self) -> None:
        """Remove finalized temporary segments while retaining their metadata."""

        for camera in self.camera_names:
            for descriptor in self._manifest["videos"][camera]["segments"]:
                segment_path = self._episode_dir / descriptor["path"]
                try:
                    segment_path.unlink()
                    descriptor["retained"] = False
                except FileNotFoundError:
                    descriptor["retained"] = False
                except OSError as error:
                    descriptor["retained"] = True
                    descriptor["cleanup_error"] = (
                        f"{type(error).__name__}: {error}"
                    )

    def finalize(
        self,
        *,
        success: bool,
        result: Mapping[str, Any] | None = None,
        failure_reason: str | None = None,
        failure_detail: str | None = None,
    ) -> dict[str, Any]:
        """Close and validate all artifacts, then write a terminal manifest."""

        self._require_open()
        if success and (failure_reason is not None or failure_detail is not None):
            raise ValueError("successful episodes cannot have failure details")
        if not success and not failure_reason:
            raise ValueError("failed episodes require failure_reason")
        try:
            self._close_video_segments()
            final_videos: dict[str, dict[str, Any] | None] = {}
            for camera in self.camera_names:
                final_videos[camera] = self._merge_camera_segments(camera)
                self._manifest["videos"][camera]["final"] = final_videos[camera]
            for camera, metadata in final_videos.items():
                decoded_frames = 0 if metadata is None else int(metadata["decoded_frames"])
                if decoded_frames != self._camera_frame_steps:
                    raise EpisodeRecorderError(
                        f"camera/step frame mismatch for {camera}: "
                        f"{decoded_frames} != {self._camera_frame_steps}"
                    )
            self._manifest["steps"]["sha256"] = (
                sha256_file(self._steps_path) if self._steps_path.exists() else None
            )
            self._manifest["status"] = "complete" if success else "failed"
            self._manifest["result"] = json_safe(result) if result is not None else None
            self._manifest["failure_reason"] = None if success else failure_reason
            self._manifest["failure_detail"] = None if success else failure_detail
            self._manifest["last_error"] = None
            self._manifest["finished_at"] = _utc_now()
            self._checkpoint_manifest()
            self._terminal = True
            self._closed = True
            try:
                self._cleanup_video_segments()
                self._checkpoint_manifest()
            except Exception as cleanup_error:  # Final videos remain authoritative.
                self._manifest["segment_cleanup_error"] = (
                    f"{type(cleanup_error).__name__}: {cleanup_error}"
                )
            return self.manifest
        except Exception as error:
            self._manifest["status"] = "interrupted"
            self._manifest["last_error"] = f"{type(error).__name__}: {error}"
            self._manifest["finished_at"] = _utc_now()
            self._checkpoint_manifest()
            self._closed = True
            raise

    def interrupt(self, error: BaseException | str | None = None) -> dict[str, Any]:
        """Gracefully close segments and mark this episode as resumable."""

        if self._terminal:
            return self.manifest
        if self._closed:
            return self.manifest
        try:
            self._close_video_segments()
        finally:
            self._manifest["status"] = "interrupted"
            if isinstance(error, BaseException):
                detail = f"{type(error).__name__}: {error}"
            elif error is None:
                detail = "recorder closed before finalize"
            else:
                detail = str(error)
            self._manifest["last_error"] = detail
            self._manifest["finished_at"] = _utc_now()
            self._checkpoint_manifest()
            self._closed = True
        return self.manifest

    def close(self) -> None:
        if not self._closed and not self._terminal:
            self.interrupt()

    def __enter__(self) -> "EpisodeRecorder":
        return self

    def __exit__(self, error_type: Any, error: BaseException | None, traceback: Any) -> bool:
        if not self._closed and not self._terminal:
            self.interrupt(error)
        return False


__all__ = [
    "DEFAULT_CAMERA_NAMES",
    "EpisodeAlreadyComplete",
    "EpisodeRecorder",
    "EpisodeRecorderError",
    "EpisodeRestartRequired",
    "inspect_episode",
    "json_safe",
    "probe_video",
    "sha256_file",
]
