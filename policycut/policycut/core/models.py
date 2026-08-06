"""Core Pydantic models (contract section 4).

Pure-python module: importable without torch/ffmpeg. Requires pydantic>=2.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

__all__ = [
    "ProjectStatus",
    "EventKind",
    "EventSource",
    "EventStatus",
    "JobType",
    "JobStatus",
    "MediaInfo",
    "Project",
    "BoxKeyframe",
    "RedactionEvent",
    "Job",
]

# ---------------------------------------------------------------------------
# Type aliases
# ---------------------------------------------------------------------------

ProjectStatus = Literal[
    "draft", "analyzing", "review_ready", "rendering", "complete", "error"
]

EventKind = Literal["visual", "audio"]
EventSource = Literal["auto", "manual"]
EventStatus = Literal["pending", "confirmed", "ignored"]

JobType = Literal["analysis", "render"]
JobStatus = Literal[
    "queued", "running", "done", "error", "cancelled", "server_restarted"
]


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------


class MediaInfo(BaseModel):
    """Probed properties of the uploaded source video."""

    filename: str
    duration_s: float
    width: int
    height: int
    fps: float
    codec: str
    has_audio: bool
    audio_codec: str | None = None
    size_bytes: int
    rotation: int = 0


class Project(BaseModel):
    """A redaction project (one source video + policy + events)."""

    id: str
    name: str
    status: ProjectStatus = "draft"
    created_at: str  # ISO 8601 UTC
    updated_at: str  # ISO 8601 UTC
    media: MediaInfo | None = None
    policy_text: str = ""
    revision: int = 0  # bumped on every event mutation
    exports_stale: bool = False
    error: str | None = None


class BoxKeyframe(BaseModel):
    """A normalized box at time ``t`` (seconds), coords 0..1 of output video."""

    t: float
    x: float
    y: float
    w: float
    h: float


class RedactionEvent(BaseModel):
    """One redaction span, visual (box/mask) or audio (time range)."""

    id: str
    kind: EventKind
    category: str  # VisualCategory | AudioCategory | "manual"
    status: EventStatus = "pending"
    source: EventSource = "auto"
    start_s: float
    end_s: float
    action: dict  # e.g. {"type": "pixelate", "strength": 65} or {"type": "beep"}
    confidence: float = 1.0
    track_id: str | None = None  # visual only; masks in analysis/masks/<track_id>.npz
    boxes: list[BoxKeyframe] = Field(default_factory=list)  # visual keyframes
    text_preview: str = ""  # audio only; REDACTED-safe label, never raw PII
    warnings: list[str] = Field(default_factory=list)
    manual_fixed_region: bool = False


class Job(BaseModel):
    """A background job (analysis or render) with progress + metrics."""

    id: str
    project_id: str
    type: JobType
    status: JobStatus
    stage: str = ""  # contract section 7 stage names
    progress: float = 0.0  # 0..1
    message: str = ""
    created_at: str
    started_at: str | None = None
    finished_at: str | None = None
    error: str | None = None
    metrics: dict = Field(default_factory=dict)  # stage -> metric dict
