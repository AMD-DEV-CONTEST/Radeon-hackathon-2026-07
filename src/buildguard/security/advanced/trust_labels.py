"""Trust labels and provenance carried by external data objects."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import Field

from buildguard.schemas.common import StrictSchema
from buildguard.utils.time import utc_now


class TrustLabel(StrEnum):
    TRUSTED_USER_INSTRUCTION = "TRUSTED_USER_INSTRUCTION"
    TRUSTED_POLICY = "TRUSTED_POLICY"
    TRUSTED_CONFIRMATION = "TRUSTED_CONFIRMATION"
    UNTRUSTED_DOCUMENT = "UNTRUSTED_DOCUMENT"
    UNTRUSTED_OCR = "UNTRUSTED_OCR"
    UNTRUSTED_TOOL_OUTPUT = "UNTRUSTED_TOOL_OUTPUT"
    UNTRUSTED_MODEL_OUTPUT = "UNTRUSTED_MODEL_OUTPUT"


TRUSTED_CONTROL_LABELS = frozenset(
    {
        TrustLabel.TRUSTED_USER_INSTRUCTION,
        TrustLabel.TRUSTED_POLICY,
        TrustLabel.TRUSTED_CONFIRMATION,
    }
)
UNTRUSTED_LABELS = frozenset(set(TrustLabel) - set(TRUSTED_CONTROL_LABELS))


class Provenance(StrictSchema):
    source_id: str = Field(min_length=1, max_length=512)
    source_kind: str = Field(min_length=1, max_length=128)
    checksum: str | None = Field(default=None, min_length=64, max_length=64)
    captured_at: datetime = Field(default_factory=utc_now)


class LabeledData(StrictSchema):
    """A value with mandatory trust and origin metadata."""

    value: Any
    label: TrustLabel
    provenance: Provenance
    sensitive: bool = False

    @property
    def trusted_for_control(self) -> bool:
        return self.label in TRUSTED_CONTROL_LABELS

