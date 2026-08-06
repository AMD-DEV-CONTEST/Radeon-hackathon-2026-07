"""Optional offline-calibrated event decisions for the video temporal layer."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field, model_validator

CalibrationDecision = Literal["event", "no_event", "ambiguous", "uncalibrated"]


class EventCalibrationThreshold(BaseModel):
    negative_max: float = Field(ge=0, le=1)
    positive_min: float = Field(ge=0, le=1)
    sample_count: int = Field(ge=1)

    @model_validator(mode="after")
    def ordered_thresholds(self) -> EventCalibrationThreshold:
        if self.negative_max >= self.positive_min:
            raise ValueError("calibration thresholds must leave an ambiguity interval")
        return self


class EventCalibrationArtifact(BaseModel):
    version: str = Field(min_length=1, max_length=64)
    dataset_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    target_error_rate: float = Field(gt=0, lt=1)
    event_types: dict[str, EventCalibrationThreshold]


class ConformalEventCalibrator:
    """Three-way event decision loaded from a versioned local JSON artifact."""

    def __init__(self, artifact: EventCalibrationArtifact | None = None) -> None:
        self.artifact = artifact

    @classmethod
    def from_path(
        cls,
        path: Path | None,
        *,
        required: bool,
    ) -> ConformalEventCalibrator:
        if path is None:
            if required:
                raise ValueError("Realtime calibration artifact is required")
            return cls()
        resolved = path.resolve()
        if not resolved.is_file():
            if required:
                raise ValueError(f"Realtime calibration artifact is missing: {resolved}")
            return cls()
        raw = resolved.read_bytes()
        payload = json.loads(raw.decode("utf-8"))
        artifact = EventCalibrationArtifact.model_validate(payload)
        declared = payload.get("artifact_sha256")
        if declared is not None:
            normalized = dict(payload)
            normalized.pop("artifact_sha256", None)
            canonical = json.dumps(
                normalized,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
            actual = hashlib.sha256(canonical).hexdigest()
            if actual != declared:
                raise ValueError("Realtime calibration artifact checksum mismatch")
        return cls(artifact)

    def decide(self, event_type: str, score: float) -> CalibrationDecision:
        if not 0 <= score <= 1:
            raise ValueError("calibration score must be within 0..1")
        if self.artifact is None:
            return "uncalibrated"
        threshold = self.artifact.event_types.get(event_type)
        if threshold is None:
            return "uncalibrated"
        if score >= threshold.positive_min:
            return "event"
        if score <= threshold.negative_max:
            return "no_event"
        return "ambiguous"
