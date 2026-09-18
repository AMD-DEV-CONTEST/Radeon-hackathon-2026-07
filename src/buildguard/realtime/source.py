"""Video source contract and status handling."""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from collections.abc import Callable
from typing import Any

import cv2

from buildguard.realtime.schemas import (
    CameraState,
    CameraStatus,
    SamplingMode,
    VideoFrame,
)
from buildguard.utils.time import utc_now

LOGGER = logging.getLogger(__name__)
StatusSink = Callable[[CameraStatus], None]
CaptureFactory = Callable[[str | int], Any]


def default_capture_factory(source: str | int) -> Any:
    return cv2.VideoCapture(source)


class VideoSource(ABC):
    """Failure-containing interface shared by file, USB, and RTSP sources."""

    def __init__(
        self,
        camera_id: str,
        source_type: str,
        status_sink: StatusSink | None = None,
    ) -> None:
        self.camera_id = camera_id
        self.source_type = source_type
        self._status_sink = status_sink
        self._status = CameraStatus(
            camera_id=camera_id,
            source_type=source_type,
            state=CameraState.STOPPED,
        )

    def _set_state(
        self,
        state: CameraState,
        *,
        error: str | None = None,
        reset_failures: bool = False,
    ) -> None:
        updates: dict[str, object] = {
            "state": state,
            "last_error": error,
            "updated_at": utc_now(),
        }
        if reset_failures:
            updates["consecutive_failures"] = 0
        self._status = self._status.model_copy(update=updates)
        if self._status_sink is not None:
            try:
                self._status_sink(self._status.model_copy(deep=True))
            except Exception as exc:
                LOGGER.warning("Camera status persistence failed: %s", exc)

    def _record_frame(self, frame: VideoFrame) -> None:
        self._status = self._status.model_copy(
            update={
                "state": CameraState.RUNNING,
                "consecutive_failures": 0,
                "frames_read": self._status.frames_read + 1,
                "last_frame_at": frame.captured_at,
                "last_error": None,
                "updated_at": utc_now(),
            }
        )
        if self._status_sink is not None:
            try:
                self._status_sink(self._status.model_copy(deep=True))
            except Exception as exc:
                LOGGER.warning("Camera status persistence failed: %s", exc)

    def mark_sampled(self) -> None:
        self._status = self._status.model_copy(
            update={
                "frames_sampled": self._status.frames_sampled + 1,
                "updated_at": utc_now(),
            }
        )

    def update_runtime_metrics(
        self,
        *,
        sampling_mode: SamplingMode,
        target_fps: float,
        current_fps: float,
        motion_score: float,
        inference_queue_length: int,
        event_queue_length: int,
        dropped_normal_frames: int,
    ) -> None:
        self._status = self._status.model_copy(
            update={
                "sampling_mode": sampling_mode,
                "target_fps": target_fps,
                "current_fps": current_fps,
                "motion_score": motion_score,
                "inference_queue_length": inference_queue_length,
                "event_queue_length": event_queue_length,
                "dropped_normal_frames": dropped_normal_frames,
                "updated_at": utc_now(),
            }
        )
        if self._status_sink is not None:
            try:
                self._status_sink(self._status.model_copy(deep=True))
            except Exception as exc:
                LOGGER.warning("Camera runtime metric persistence failed: %s", exc)

    @abstractmethod
    def open(self) -> bool:
        """Open without allowing expected device errors to escape."""

    @abstractmethod
    def read(self) -> VideoFrame | None:
        """Return one frame or a structured unavailable state."""

    @abstractmethod
    def reconnect(self) -> bool:
        """Attempt to reopen the configured source."""

    @abstractmethod
    def close(self) -> None:
        """Release source resources idempotently."""

    def status(self) -> CameraStatus:
        return self._status.model_copy(deep=True)
