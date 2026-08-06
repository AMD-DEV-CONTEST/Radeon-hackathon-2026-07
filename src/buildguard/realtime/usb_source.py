"""USB camera source."""

from __future__ import annotations

from typing import Any, cast

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


class UsbCameraSource(VideoSource):
    def __init__(
        self,
        camera_id: str,
        device_index: int,
        *,
        status_sink: StatusSink | None = None,
        capture_factory: CaptureFactory = default_capture_factory,
    ) -> None:
        super().__init__(camera_id, "usb", status_sink)
        if device_index < 0:
            raise ValueError("USB device index must be non-negative")
        self.device_index = device_index
        self.capture_factory = capture_factory
        self.capture: Any | None = None
        self.sequence = 0

    def open(self) -> bool:
        self._set_state(CameraState.OPENING)
        try:
            capture = self.capture_factory(self.device_index)
            if not bool(capture.isOpened()):
                capture.release()
                self._set_state(CameraState.DEGRADED, error="Could not open USB camera")
                return False
            self.capture = capture
            self._set_state(CameraState.RUNNING, reset_failures=True)
            return True
        except Exception as exc:
            self.capture = None
            self._set_state(CameraState.DEGRADED, error=str(exc))
            return False

    def read(self) -> VideoFrame | None:
        if self.capture is None:
            self._set_state(CameraState.DEGRADED, error="USB camera is not open")
            return None
        try:
            ok, raw = self.capture.read()
            if not ok or raw is None:
                failures = self._status.consecutive_failures + 1
                self._status = self._status.model_copy(update={"consecutive_failures": failures})
                self._set_state(CameraState.DEGRADED, error="USB camera read failed")
                return None
            frame = VideoFrame(
                camera_id=self.camera_id,
                sequence=self.sequence,
                captured_at=utc_now(),
                source_time_seconds=float(self.sequence),
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
                self._set_state(CameraState.DEGRADED, error="USB release failed")
                return
        self._set_state(CameraState.STOPPED)
