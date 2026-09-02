from __future__ import annotations

from typing import Annotated, Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, field_validator


Sha256Digest = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
ReferenceView = Literal["front", "three_quarter_left", "profile_left"]


class ReferenceManufacturingError(RuntimeError):
    """A reference view or reference set cannot be safely manufactured."""


class _StrictFrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ReferenceViewQCResult(_StrictFrozenModel):
    view: ReferenceView
    image_digest: Sha256Digest
    prompt_digest: Sha256Digest
    workflow_digest: Sha256Digest
    attempt: Annotated[int, Field(ge=0, le=1)]
    evaluator_provider: Literal["zhipu"]
    evaluator_model_id: Literal["glm-4.6v"]
    evaluator_response_digest: Sha256Digest
    angle_match: bool
    single_subject: bool
    artifact_free: bool
    source_fidelity: bool
    policy_snapshot_digest: Sha256Digest
    evaluated_at: AwareDatetime

    @property
    def passed(self) -> bool:
        return all(
            (
                self.angle_match,
                self.single_subject,
                self.artifact_free,
                self.source_fidelity,
            )
        )


class CrossViewQCResult(_StrictFrozenModel):
    view_image_digests: tuple[Sha256Digest, Sha256Digest, Sha256Digest]
    evaluator_provider: Literal["zhipu"]
    evaluator_model_id: Literal["glm-4.6v"]
    evaluator_response_digest: Sha256Digest
    identity_consistent: bool
    age_consistent: bool
    attire_consistent: bool
    angle_correct: bool
    artifact_free: bool
    policy_snapshot_digest: Sha256Digest
    evaluated_at: AwareDatetime

    @field_validator("view_image_digests")
    @classmethod
    def independent_images(cls, value: tuple[str, str, str]) -> tuple[str, str, str]:
        if len(set(value)) != 3:
            raise ValueError("cross-view QC requires three distinct images")
        return value

    @property
    def passed(self) -> bool:
        return all(
            (
                self.identity_consistent,
                self.age_consistent,
                self.attire_consistent,
                self.angle_correct,
                self.artifact_free,
            )
        )


def next_reference_attempt(
    current_attempt: int,
    qc: ReferenceViewQCResult,
) -> int:
    if current_attempt not in (0, 1) or qc.attempt != current_attempt:
        raise ReferenceManufacturingError(
            f"{qc.view} QC lineage does not match its generation attempt"
        )
    if qc.passed:
        return current_attempt
    if current_attempt == 0:
        return 1
    raise ReferenceManufacturingError(
        f"{qc.view} failed its single allowed view-specific retry"
    )


__all__ = [
    "CrossViewQCResult",
    "ReferenceManufacturingError",
    "ReferenceViewQCResult",
    "next_reference_attempt",
]
