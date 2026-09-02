"""PolicySpec Pydantic models.

Single source of truth: docs/CONTRACTS.md section 3, mirrored by
schemas/policy.schema.json. Pure python — importable without torch/ffmpeg.
"""

from typing import Literal

from pydantic import BaseModel, Field

VisualCategory = Literal["face", "license_plate", "id_document", "screen"]
AudioCategory = Literal["phone", "email", "address"]
VisualActionType = Literal["blur", "pixelate", "solid"]
AudioActionType = Literal["mute", "beep"]


class VisualAction(BaseModel):
    """How a visual target is redacted."""

    type: VisualActionType = "pixelate"
    strength: int = Field(65, ge=1, le=100)


class AudioAction(BaseModel):
    """How an audio target is redacted."""

    type: AudioActionType = "mute"


class VisualTarget(BaseModel):
    """A visual category to detect and redact."""

    category: VisualCategory
    prompts: list[str]  # detection phrases for GroundingDINO
    action: VisualAction


class AudioTarget(BaseModel):
    """An audio PII category to detect and redact."""

    category: AudioCategory
    action: AudioAction
    padding_before_ms: int = 150
    padding_after_ms: int = 250


class PolicySpec(BaseModel):
    """Full machine-readable redaction policy."""

    schema_version: str = "1.0"
    language: str = "en"
    visual_targets: list[VisualTarget]
    audio_targets: list[AudioTarget]
    unsupported_terms: list[str] = []
    review_required: bool = True


# Default GroundingDINO detection prompts per visual category
# (YuNet also always runs when "face" is targeted).
DEFAULT_PROMPTS: dict[str, list[str]] = {
    "face": ["human face"],
    "license_plate": ["license plate", "vehicle registration plate"],
    "id_document": ["identity card", "passport", "driver's license"],
    "screen": ["computer monitor", "laptop screen", "smartphone screen", "tablet screen"],
}
