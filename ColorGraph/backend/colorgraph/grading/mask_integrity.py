from __future__ import annotations

import hashlib
import json
import subprocess
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

import cv2
import numpy as np

from colorgraph.config import settings

LEGACY_MASK_ASSET_SCHEMA = "colorgraph.mask-asset/v2"
MASK_ASSET_SCHEMA = "colorgraph.mask-asset/v3"
SUPPORTED_MASK_ASSET_SCHEMAS = frozenset(
    {LEGACY_MASK_ASSET_SCHEMA, MASK_ASSET_SCHEMA}
)


class MissingFramePolicy(StrEnum):
    ERROR = "error"
    HOLD_LAST = "hold_last"


@dataclass(frozen=True, slots=True)
class MaskSequenceInspection:
    frame_count: int
    file_count: int
    width: int
    height: int
    bit_depth: int
    sample_dtype: str
    maximum_quantization_error: float
    sha256: str
    missing_frame_indices: tuple[int, ...]


@dataclass(frozen=True, slots=True)
class MaskVideoInspection:
    frame_count: int
    width: int
    height: int
    fps: float
    pixel_format: str
    bits_per_raw_sample: int | None
    sha256: str


def file_sha256(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _sequence_sha256(paths: list[Path]) -> str:
    digest = hashlib.sha256()
    for path in paths:
        digest.update(path.name.encode("utf-8"))
        digest.update(b"\0")
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
    return digest.hexdigest()


def inspect_mask_sequence(
    root: str | Path,
    *,
    expected_frame_count: int,
    expected_width: int,
    expected_height: int,
    expected_bit_depth: int | None = None,
    expected_sha256: str | None = None,
    missing_frame_policy: MissingFramePolicy = MissingFramePolicy.ERROR,
) -> MaskSequenceInspection:
    directory = Path(root)
    if not directory.is_dir():
        raise FileNotFoundError(f"mask sequence directory is missing: {directory}")
    if expected_frame_count <= 0:
        raise ValueError("mask sequence expected_frame_count must be positive")
    if expected_width <= 0 or expected_height <= 0:
        raise ValueError("mask sequence dimensions must be positive")

    expected_names = {
        f"{frame_index:06d}.png"
        for frame_index in range(expected_frame_count)
    }
    paths = sorted(directory.glob("*.png"))
    actual_names = {path.name for path in paths}
    unexpected = sorted(actual_names - expected_names)
    if unexpected:
        raise ValueError(
            f"mask sequence contains out-of-range frames: {unexpected[:8]}"
        )
    missing = tuple(
        frame_index
        for frame_index in range(expected_frame_count)
        if f"{frame_index:06d}.png" not in actual_names
    )
    if missing and missing_frame_policy == MissingFramePolicy.ERROR:
        raise FileNotFoundError(
            f"mask sequence is missing frames: {list(missing[:8])}"
        )
    if missing and 0 in missing:
        raise FileNotFoundError(
            "mask sequence cannot use hold_last because frame 0 is missing"
        )

    bit_depth: int | None = None
    sample_dtype: str | None = None
    for path in paths:
        frame = cv2.imread(str(path), cv2.IMREAD_UNCHANGED)
        if frame is None:
            raise RuntimeError(f"could not decode mask frame {path}")
        if frame.ndim != 2:
            raise ValueError(
                f"mask frame {path.name} must be single-channel; "
                f"got shape {frame.shape}"
            )
        if frame.shape != (expected_height, expected_width):
            raise ValueError(
                f"mask frame {path.name} has shape {frame.shape}; "
                f"expected {(expected_height, expected_width)}"
            )
        if frame.dtype == np.uint8:
            frame_bit_depth = 8
        elif frame.dtype == np.uint16:
            frame_bit_depth = 16
        elif np.issubdtype(frame.dtype, np.floating):
            frame_bit_depth = 32
        else:
            raise ValueError(
                f"mask frame {path.name} uses unsupported dtype {frame.dtype}"
            )
        if bit_depth is None:
            bit_depth = frame_bit_depth
            sample_dtype = str(frame.dtype)
        elif frame_bit_depth != bit_depth or str(frame.dtype) != sample_dtype:
            raise ValueError("mask sequence mixes sample dtypes or bit depths")
    if bit_depth is None or sample_dtype is None:
        raise RuntimeError("mask sequence did not contain any decodable frames")
    if expected_bit_depth is not None and bit_depth != expected_bit_depth:
        raise ValueError(
            f"mask sequence bit depth {bit_depth} does not match "
            f"expected {expected_bit_depth}"
        )

    checksum = _sequence_sha256(paths)
    if expected_sha256 is not None and not missing and checksum != expected_sha256:
        raise ValueError(
            f"mask sequence checksum mismatch: expected {expected_sha256}, "
            f"got {checksum}"
        )
    return MaskSequenceInspection(
        frame_count=expected_frame_count,
        file_count=len(paths),
        width=expected_width,
        height=expected_height,
        bit_depth=bit_depth,
        sample_dtype=sample_dtype,
        maximum_quantization_error=(
            0.0 if bit_depth == 32 else 0.5 / ((1 << bit_depth) - 1)
        ),
        sha256=checksum,
        missing_frame_indices=missing,
    )


def inspect_mask_video(
    path: str | Path,
    *,
    expected_frame_count: int,
    expected_width: int,
    expected_height: int,
    expected_fps: float,
    expected_pixel_format: str | None = None,
    expected_sha256: str | None = None,
) -> MaskVideoInspection:
    video_path = Path(path)
    if not video_path.is_file():
        raise FileNotFoundError(f"mask video is missing: {video_path}")
    if expected_frame_count <= 0:
        raise ValueError("mask video expected_frame_count must be positive")
    if expected_width <= 0 or expected_height <= 0:
        raise ValueError("mask video dimensions must be positive")
    if expected_fps <= 0:
        raise ValueError("mask video fps must be positive")

    checksum = file_sha256(video_path)
    if expected_sha256 is not None and checksum != expected_sha256:
        raise ValueError(
            f"mask video checksum mismatch: expected {expected_sha256}, "
            f"got {checksum}"
        )
    probe = subprocess.run(
        [
            settings.ffprobe_binary,
            "-v",
            "error",
            "-select_streams",
            "v:0",
            "-show_entries",
            "stream=pix_fmt,bits_per_raw_sample",
            "-of",
            "json",
            str(video_path),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if probe.returncode:
        raise RuntimeError(
            f"could not probe mask video {video_path}: {probe.stderr.strip()}"
        )
    try:
        streams = json.loads(probe.stdout).get("streams", [])
        stream = streams[0]
        pixel_format = str(stream["pix_fmt"])
        raw_bits = stream.get("bits_per_raw_sample")
        bits_per_raw_sample = (
            int(raw_bits)
            if raw_bits not in {None, "", "N/A"}
            else None
        )
    except (IndexError, KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise RuntimeError(
            f"mask video probe returned incomplete stream metadata: {video_path}"
        ) from exc
    if expected_pixel_format is not None and pixel_format != expected_pixel_format:
        raise ValueError(
            f"mask video pixel format {pixel_format!r} does not match "
            f"expected {expected_pixel_format!r}"
        )

    capture = cv2.VideoCapture(str(video_path))
    if not capture.isOpened():
        raise RuntimeError(f"could not open mask video {video_path}")
    reported_fps = float(capture.get(cv2.CAP_PROP_FPS))
    reported_width = round(capture.get(cv2.CAP_PROP_FRAME_WIDTH))
    reported_height = round(capture.get(cv2.CAP_PROP_FRAME_HEIGHT))
    reported_frames = round(capture.get(cv2.CAP_PROP_FRAME_COUNT))
    tolerance = max(0.01, expected_fps * 0.001)
    if reported_fps <= 0 or abs(reported_fps - expected_fps) > tolerance:
        capture.release()
        raise ValueError(
            f"mask video fps {reported_fps} does not match expected {expected_fps}"
        )
    if (reported_width, reported_height) != (expected_width, expected_height):
        capture.release()
        raise ValueError(
            f"mask video size {(reported_width, reported_height)} does not match "
            f"expected {(expected_width, expected_height)}"
        )
    if reported_frames > 0 and reported_frames != expected_frame_count:
        capture.release()
        raise ValueError(
            f"mask video reports {reported_frames} frames; "
            f"expected {expected_frame_count}"
        )

    decoded_frames = 0
    try:
        while True:
            success, frame = capture.read()
            if not success:
                break
            if frame.shape[:2] != (expected_height, expected_width):
                raise ValueError(
                    f"decoded mask video frame {decoded_frames} has shape "
                    f"{frame.shape[:2]}; expected {(expected_height, expected_width)}"
                )
            decoded_frames += 1
    finally:
        capture.release()
    if decoded_frames != expected_frame_count:
        raise RuntimeError(
            f"mask video decoded {decoded_frames} frames; "
            f"expected {expected_frame_count}"
        )
    return MaskVideoInspection(
        frame_count=decoded_frames,
        width=expected_width,
        height=expected_height,
        fps=reported_fps,
        pixel_format=pixel_format,
        bits_per_raw_sample=bits_per_raw_sample,
        sha256=checksum,
    )
