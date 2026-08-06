"""Atomic event frame and optional short-clip writer."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any, cast

import cv2
import numpy as np
from numpy.typing import NDArray

from buildguard.realtime.schemas import VideoFrame


class ClipWriter:
    def __init__(
        self,
        image_dir: Path,
        clip_dir: Path,
        *,
        codec: str,
        fps: float,
    ) -> None:
        if len(codec) != 4:
            raise ValueError("Video codec must contain exactly four characters")
        if fps <= 0:
            raise ValueError("Clip FPS must be positive")
        self.image_dir = image_dir.resolve()
        self.clip_dir = clip_dir.resolve()
        self.codec = codec
        self.fps = fps
        self.image_dir.mkdir(parents=True, exist_ok=True)
        self.clip_dir.mkdir(parents=True, exist_ok=True)

    def write_frame(self, event_id: str, kind: str, frame: VideoFrame) -> Path:
        target = self.image_dir / f"{event_id}-{kind}.jpg"
        temporary = target.with_suffix(".tmp.jpg")
        ok, encoded = cv2.imencode(".jpg", frame.image)
        if not ok:
            raise ValueError(f"Could not encode {kind} frame for event {event_id}")
        temporary.write_bytes(encoded.tobytes())
        temporary.replace(target)
        return target

    def write_clip(self, event_id: str, frames: list[VideoFrame]) -> Path | None:
        if not frames:
            return None
        height, width = frames[0].image.shape[:2]
        suffix = ".webm" if self.codec in {"VP80", "VP90"} else ".mp4"
        target = self.clip_dir / f"{event_id}{suffix}"
        temporary = self.clip_dir / f"{event_id}.tmp{suffix}"
        fourcc_factory = cast(
            Callable[[str, str, str, str], Any],
            cv2.VideoWriter_fourcc,  # type: ignore[attr-defined]
        )
        writer = cv2.VideoWriter(
            str(temporary),
            fourcc_factory(*self.codec),
            self.fps,
            (int(width), int(height)),
        )
        if not writer.isOpened():
            writer.release()
            raise ValueError(f"Could not open clip writer for event {event_id}")
        try:
            for frame in frames:
                image = frame.image
                if image.shape[:2] != (height, width):
                    image = cast(
                        NDArray[np.uint8],
                        cv2.resize(image, (int(width), int(height))),
                    )
                writer.write(image)
        finally:
            writer.release()
        if not temporary.is_file() or temporary.stat().st_size == 0:
            raise ValueError(f"Clip writer produced no data for event {event_id}")
        temporary.replace(target)
        return target


def ensure_browser_compatible_clip(source: Path) -> Path:
    """Return a cached WebM version for browser-incompatible legacy MP4 clips."""
    source = source.resolve()
    if source.suffix.casefold() == ".webm":
        return source
    target = source.with_name(f"{source.stem}.browser.webm")
    if (
        target.is_file()
        and target.stat().st_size > 0
        and target.stat().st_mtime_ns >= source.stat().st_mtime_ns
    ):
        return target

    capture = cv2.VideoCapture(str(source))
    if not capture.isOpened():
        capture.release()
        raise ValueError(f"Could not decode event clip: {source.name}")
    temporary = target.with_name(f"{target.stem}.tmp.webm")
    writer: cv2.VideoWriter | None = None
    try:
        fps = float(capture.get(cv2.CAP_PROP_FPS)) or 10.0
        ok, frame = capture.read()
        if not ok or frame is None:
            raise ValueError(f"Event clip contains no decodable frames: {source.name}")
        height, width = frame.shape[:2]
        fourcc_factory = cast(
            Callable[[str, str, str, str], Any],
            cv2.VideoWriter_fourcc,  # type: ignore[attr-defined]
        )
        writer = cv2.VideoWriter(
            str(temporary),
            fourcc_factory(*"VP80"),
            fps,
            (int(width), int(height)),
        )
        if not writer.isOpened():
            raise ValueError("This OpenCV build cannot encode browser-compatible VP8/WebM")
        while ok and frame is not None:
            writer.write(frame)
            ok, frame = capture.read()
    finally:
        capture.release()
        if writer is not None:
            writer.release()
    if not temporary.is_file() or temporary.stat().st_size == 0:
        raise ValueError(f"Browser-compatible conversion produced no data: {source.name}")
    temporary.replace(target)
    return target
