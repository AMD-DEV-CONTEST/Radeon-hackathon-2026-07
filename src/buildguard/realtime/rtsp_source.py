"""Allowlisted RTSP source with bounded exponential reconnect."""

from __future__ import annotations

import ipaddress
from typing import Any, cast
from urllib.parse import urlparse

import numpy as np
from numpy.typing import NDArray

from buildguard.exceptions import EndpointSecurityError
from buildguard.realtime.reconnect import ExponentialReconnect
from buildguard.realtime.schemas import CameraState, VideoFrame
from buildguard.realtime.source import (
    CaptureFactory,
    StatusSink,
    VideoSource,
    default_capture_factory,
)
from buildguard.utils.time import utc_now


def validate_rtsp_endpoint(url: str, allowed_lan_cidrs: list[str]) -> None:
    parsed = urlparse(url)
    if parsed.scheme not in {"rtsp", "rtsps"} or not parsed.hostname:
        raise EndpointSecurityError("RTSP source must be a valid rtsp:// or rtsps:// URL")
    host = parsed.hostname.lower()
    if host == "localhost":
        return
    try:
        address = ipaddress.ip_address(host)
    except ValueError as exc:
        raise EndpointSecurityError("Non-local RTSP hostnames are blocked") from exc
    if address.is_loopback:
        return
    networks = [ipaddress.ip_network(value, strict=False) for value in allowed_lan_cidrs]
    if any(address in network for network in networks):
        return
    raise EndpointSecurityError("Public and unapproved RTSP addresses are blocked")


class RtspVideoSource(VideoSource):
    def __init__(
        self,
        camera_id: str,
        url: str,
        *,
        allowed_lan_cidrs: list[str],
        failure_threshold: int,
        reconnect: ExponentialReconnect,
        status_sink: StatusSink | None = None,
        capture_factory: CaptureFactory = default_capture_factory,
    ) -> None:
        super().__init__(camera_id, "rtsp", status_sink)
        validate_rtsp_endpoint(url, allowed_lan_cidrs)
        if failure_threshold < 1:
            raise ValueError("RTSP failure threshold must be positive")
        self.url = url
        self.failure_threshold = failure_threshold
        self.reconnect_policy = reconnect
        self.capture_factory = capture_factory
        self.capture: Any | None = None
        self.sequence = 0

    def _release(self) -> None:
        capture, self.capture = self.capture, None
        if capture is not None:
            try:
                capture.release()
            except Exception:
                self._set_state(CameraState.DEGRADED, error="RTSP release failed")

    def open(self) -> bool:
        self._set_state(CameraState.OPENING)
        try:
            capture = self.capture_factory(self.url)
            if not bool(capture.isOpened()):
                capture.release()
                self._status = self._status.model_copy(
                    update={"consecutive_failures": self._status.consecutive_failures + 1}
                )
                self._set_state(CameraState.DEGRADED, error="Could not open RTSP source")
                return False
            self.capture = capture
            self.reconnect_policy.reset()
            self._set_state(CameraState.RUNNING, reset_failures=True)
            return True
        except Exception as exc:
            self.capture = None
            self._status = self._status.model_copy(
                update={"consecutive_failures": self._status.consecutive_failures + 1}
            )
            self._set_state(CameraState.DEGRADED, error=str(exc))
            return False

    def read(self) -> VideoFrame | None:
        if self.capture is None:
            self._set_state(CameraState.RECONNECTING, error="RTSP source is not open")
            return None
        try:
            ok, raw = self.capture.read()
            if not ok or raw is None:
                failures = self._status.consecutive_failures + 1
                self._status = self._status.model_copy(update={"consecutive_failures": failures})
                state = (
                    CameraState.RECONNECTING
                    if failures >= self.failure_threshold
                    else CameraState.DEGRADED
                )
                self._set_state(state, error="RTSP frame read failed")
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
            self._status = self._status.model_copy(
                update={"consecutive_failures": self._status.consecutive_failures + 1}
            )
            self._set_state(CameraState.RECONNECTING, error=str(exc))
            return None

    def reconnect(self) -> bool:
        self._release()
        decision = self.reconnect_policy.wait()
        self._status = self._status.model_copy(update={"reconnect_attempts": decision.attempt})
        self._set_state(CameraState.RECONNECTING)
        return self.open()

    def close(self) -> None:
        self._release()
        self._set_state(CameraState.STOPPED)
