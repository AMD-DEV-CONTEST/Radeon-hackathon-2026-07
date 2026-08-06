"""ILS v2.2 - Canonical IntentPacket model with validation."""
from __future__ import annotations
from enum import Enum
from typing import Any
from pydantic import BaseModel, Field, model_validator


class IntentType(str, Enum):
    CREATE = "create"
    MODIFY = "modify"
    DELETE = "delete"
    INVESTIGATE = "investigate"
    FIX = "fix"
    DEPLOY = "deploy"
    REVIEW = "review"
    OTHER = "other"


class IntentPacket(BaseModel):
    """Low-entropy intent envelope compiled from raw user input.
    Required by ILS-G001 (Target Object Gate): target_object must be
    populated or the intake hook will block the request.
    """
    task_id: str = Field(description="Unique intake identifier")
    raw_input: str = Field(description="Original user request verbatim")
    normalized_intent: str = Field(
        max_length=500, description="De-noised, concise intent statement",
    )
    target_object: str = Field(
        min_length=1,
        description="Entity to be modified (file, service, module). Must uniquely identify the target.",
    )
    intent_type: IntentType = Field(default=IntentType.OTHER)
    scope_boundary: str = Field(
        default="", description="Explicit boundary: what files/services/dirs are in scope",
    )
    non_goals: list[str] = Field(default_factory=list, description="Explicitly excluded outcomes")
    ambiguity_points: list[str] = Field(default_factory=list, description="Known ambiguities that need clarification")
    asr_noise_suspected: bool = Field(default=False, description="True if voice-input artefacts are detected")
    confidence: float = Field(default=0.8, ge=0.0, le=1.0, description="System confidence in the normalised intent (0-1)")
    required_confirmation: bool = Field(default=False, description="If True, human must confirm before dispatch")
    project: str = Field(default="default", description="Project namespace")
    metadata: dict[str, Any] = Field(default_factory=dict)
    participants: list[dict[str, Any]] = Field(
        default_factory=list,
        description="Participant list with roles",
    )

    @model_validator(mode="after")
    def _validate_gate_conditions(self) -> "IntentPacket":
        if not self.target_object.strip():
            raise ValueError("ILS-F001: target_object is empty. Every intent must name the entity to be modified.")
        if len(self.ambiguity_points) >= 3 and not self.required_confirmation:
            self.required_confirmation = True
        if self.confidence < 0.5 and not self.required_confirmation:
            self.required_confirmation = True
        return self

    def blocking_issues(self) -> list[str]:
        issues: list[str] = []
        if not self.target_object.strip():
            issues.append("ILS-F001: target_object is missing or ambiguous")
        if self.required_confirmation:
            issues.append(
                "ILS-F001: human confirmation required "
                f"(confidence={self.confidence}, ambiguities={len(self.ambiguity_points)})"
            )
        if self.asr_noise_suspected:
            issues.append("ASR noise suspected -- raw input may contain voice artefacts")
        return issues

    def to_hook_dict(self) -> dict[str, Any]:
        return self.model_dump()


class IntentValidationResult(BaseModel):
    valid: bool
    warnings: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
    gate_outcomes: dict[str, bool] = Field(default_factory=dict)


def validate_intent_packet(packet):
    if packet is None or (not packet.target_object):
        return IntentValidationResult(
            valid=False,
            errors=["intent_packet missing or empty"],
            gate_outcomes={"ILS-G001": False},
        )
    warnings = []
    if len(packet.raw_input) < 10:
        warnings.append("ILS-G001: raw_input is very short")
    if not packet.normalized_intent:
        warnings.append("ILS-G001: normalized_intent is empty")
    return IntentValidationResult(
        valid=len(warnings) == 0,
        warnings=warnings,
        gate_outcomes={"ILS-G001": len(warnings) == 0},
    )
