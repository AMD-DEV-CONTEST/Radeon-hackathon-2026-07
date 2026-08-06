"""Local video file source."""

from __future__ import annotations

from pathlib import Path
from typing import Any, cast

import cv2
import numpy as np
from numpy.typing import NDArray

from buildguard.realtime.schemas import CameraState, VideoFrame
from buildguard.realtime.source import (
    CaptureFactory,
    StatusSink,
    VideoSource,
    default_capture_factory,
)
from buildguard.utils.time import utc_now


class LocalVideoSource(VideoSource):
    def __init__(
        self,
        camera_id: str,
        path: Path,
        *,
        status_sink: StatusSink | None = None,
        capture_factory: CaptureFactory = default_capture_factory,
    ) -> None:
        super().__init__(camera_id, "local", status_sink)
        self.path = path.resolve()
        self.capture_factory = capture_factory
        self.capture: Any | None = None
        self.sequence = 0
        self.fps = 0.0

    def open(self) -> bool:
        self._set_state(CameraState.OPENING)
        if not self.path.is_file():
            self._set_state(
                CameraState.FAILED,
                error=f"Local video file does not exist: {self.path}",
            )
            return False
        try:
            capture = self.capture_factory(str(self.path))
            if not bool(capture.isOpened()):
                capture.release()
                self._set_state(CameraState.FAILED, error="Could not open local video")
                return False
            self.capture = capture
            self.sequence = 0
            self.fps = max(0.0, float(capture.get(cv2.CAP_PROP_FPS)))
            self._set_state(CameraState.RUNNING, reset_failures=True)
            return True
        except Exception as exc:
            self.capture = None
            self._set_state(CameraState.FAILED, error=str(exc))
            return False

    def read(self) -> VideoFrame | None:
        if self.capture is None:
            self._set_state(CameraState.FAILED, error="Local video is not open")
            return None
        try:
            ok, raw = self.capture.read()
            if not ok or raw is None:
                self._set_state(CameraState.STOPPED, error="End of local video")
                return None
            position_ms = max(0.0, float(self.capture.get(cv2.CAP_PROP_POS_MSEC)))
            source_seconds = (
                position_ms / 1000
                if position_ms > 0
                else self.sequence / self.fps
                if self.fps > 0
                else float(self.sequence)
            )
            frame = VideoFrame(
                camera_id=self.camera_id,
                sequence=self.sequence,
                captured_at=utc_now(),
                source_time_seconds=source_seconds,
                image=cast(NDArray[np.uint8], raw),
            )
            self.sequence += 1
            self._record_frame(frame)
            return frame
        except Exception as exc:
            self._set_state(CameraState.DEGRADED, error=str(exc))
            return None

    def reconnect(self) -> bool:
        self.close()
        return self.open()

    def close(self) -> None:
        capture, self.capture = self.capture, None
        if capture is not None:
            try:
                capture.release()
            except Exception:
                self._set_state(CameraState.DEGRADED, error="Video release failed")
                return
        self._set_state(CameraState.STOPPED)
