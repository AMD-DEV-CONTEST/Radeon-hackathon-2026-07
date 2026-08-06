"""Realtime monitoring schemas."""

from __future__ import annotations

from datetime import datetime
from enum import IntEnum, StrEnum
from pathlib import Path
from typing import Any

import numpy as np
from numpy.typing import NDArray
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from buildguard.schemas.common import BoundingBox, Severity, StrictSchema, new_id
from buildguard.schemas.vision import Detection
from buildguard.utils.time import utc_now


class CameraState(StrEnum):
    STOPPED = "stopped"
    OPENING = "opening"
    RUNNING = "running"
    RECONNECTING = "reconnecting"
    DEGRADED = "degraded"
    FAILED = "failed"


class EventState(StrEnum):
    PENDING = "pending"
    ACTIVE = "active"
    ACKNOWLEDGED = "acknowledged"
    RESOLVED = "resolved"
    DISMISSED = "dismissed"


class SamplingMode(StrEnum):
    STATIC = "static"
    LOW_MOTION = "low_motion"
    NORMAL = "normal"
    ACTIVE = "active"
    SUSPECTED = "suspected"
    RECOVERY = "recovery"


class FramePriority(IntEnum):
    """Lower values are more important to the realtime inference loop."""

    CRITICAL = 0
    SUSPECTED = 1
    RECOVERY = 2
    NORMAL = 3
    HEARTBEAT = 4


class VideoFrame(BaseModel):
    """One decoded BGR frame; never serialized into tool or audit output."""

    model_config = ConfigDict(arbitrary_types_allowed=True, extra="forbid")

    camera_id: str = Field(min_length=1, max_length=128)
    sequence: int = Field(ge=0)
    captured_at: datetime = Field(default_factory=utc_now)
    source_time_seconds: float = Field(ge=0)
    image: NDArray[np.uint8]
    key_frame: bool = False

    @field_validator("captured_at")
    @classmethod
    def timestamp_must_be_aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("captured_at must be timezone-aware")
        return value

    @field_validator("image")
    @classmethod
    def image_must_be_bgr(cls, value: NDArray[np.uint8]) -> NDArray[np.uint8]:
        if value.dtype != np.uint8 or value.ndim != 3 or value.shape[2] != 3:
            raise ValueError("image must be an HxWx3 uint8 array")
        if value.size == 0:
            raise ValueError("image must not be empty")
        return value

    @property
    def memory_bytes(self) -> int:
        return int(self.image.nbytes)


class CameraStatus(StrictSchema):
    camera_id: str = Field(min_length=1, max_length=128)
    source_type: str = Field(min_length=1, max_length=32)
    state: CameraState
    consecutive_failures: int = Field(default=0, ge=0)
    reconnect_attempts: int = Field(default=0, ge=0)
    frames_read: int = Field(default=0, ge=0)
    frames_sampled: int = Field(default=0, ge=0)
    last_frame_at: datetime | None = None
    last_error: str | None = Field(default=None, max_length=2000)
    sampling_mode: SamplingMode = SamplingMode.STATIC
    target_fps: float = Field(default=0, ge=0)
    current_fps: float = Field(default=0, ge=0)
    motion_score: float = Field(default=0, ge=0, le=255)
    inference_queue_length: int = Field(default=0, ge=0)
    event_queue_length: int = Field(default=0, ge=0)
    dropped_normal_frames: int = Field(default=0, ge=0)
    updated_at: datetime = Field(default_factory=utc_now)


class TrackedDetection(StrictSchema):
    track_id: str = Field(min_length=1, max_length=128)
    detection: Detection
    hits: int = Field(ge=1)
    age: int = Field(ge=0)
    confirmed: bool

    @property
    def bbox(self) -> BoundingBox:
        return self.detection.bounding_box


class ConfirmationResult(StrictSchema):
    event_type: str
    identity: str
    positives: int = Field(ge=0)
    window_size: int = Field(ge=0)
    required: int = Field(ge=1)
    confirmed: bool
    smoothed_confidence: float = Field(ge=0, le=1)
    suspected: bool = False
    evidence_score: float = Field(default=0, ge=0, le=1)
    positive_duration_seconds: float = Field(default=0, ge=0)
    decision_source: str = "m_of_n"


class EventCandidate(BaseModel):
    """Internal candidate retaining its evidence frame."""

    model_config = ConfigDict(arbitrary_types_allowed=True, extra="forbid")

    camera_id: str
    event_type: str
    track_id: str | None = None
    bbox: BoundingBox
    confidence: float = Field(ge=0, le=1)
    confirmed: bool
    frame: VideoFrame
    detections: list[TrackedDetection] = Field(default_factory=list)
    calibration_decision: str = "uncalibrated"


class RealtimeRiskEvent(StrictSchema):
    id: str = Field(default_factory=new_id)
    camera_id: str = Field(min_length=1, max_length=128)
    event_type: str = Field(min_length=1, max_length=128)
    track_id: str | None = Field(default=None, max_length=128)
    status: EventState
    severity: Severity
    started_at: datetime
    last_seen_at: datetime
    ended_at: datetime | None = None
    max_confidence: float = Field(ge=0, le=1)
    region: BoundingBox
    start_frame_path: Path | None = None
    max_confidence_frame_path: Path | None = None
    end_frame_path: Path | None = None
    clip_path: Path | None = None
    detection_history: list[dict[str, Any]] = Field(default_factory=list, max_length=500)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_dates(self) -> RealtimeRiskEvent:
        if self.last_seen_at < self.started_at:
            raise ValueError("last_seen_at must not precede started_at")
        if self.ended_at is not None and self.ended_at < self.started_at:
            raise ValueError("ended_at must not precede started_at")
        return self


class CameraActionInput(StrictSchema):
    camera_id: str = Field(min_length=1, max_length=128)


class CameraActionOutput(StrictSchema):
    status: CameraStatus


class QueryRecentEventsInput(StrictSchema):
    camera_id: str | None = Field(default=None, max_length=128)
    statuses: list[EventState] = Field(default_factory=list)
    limit: int = Field(default=20, ge=1, le=500)


class QueryRecentEventsOutput(StrictSchema):
    events: list[RealtimeRiskEvent] = Field(default_factory=list)


class EventActionInput(StrictSchema):
    event_id: str = Field(min_length=1, max_length=128)


class EventActionOutput(StrictSchema):
    event: RealtimeRiskEvent


class ListCameraStatusInput(StrictSchema):
    include_stopped: bool = True


class ListCameraStatusOutput(StrictSchema):
    cameras: list[CameraStatus] = Field(default_factory=list)
