from __future__ import annotations

import hmac
from collections.abc import Mapping
from typing import Annotated, Any, Literal
from uuid import UUID

from pydantic import AwareDatetime, Field, field_validator, model_validator

from .models import StrictFrozenModel, stable_json_sha256


Sha256Digest = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
Identifier = Annotated[
    str,
    Field(min_length=1, max_length=160, pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:-]*$"),
]
CharacterReferenceViewName = Literal[
    "front",
    "three_quarter_left",
    "profile_left",
]
CharacterReferenceState = Literal[
    "draft",
    "generating",
    "qc_pending",
    "needs_manual_source_fix",
    "frozen",
]

CANONICAL_CHARACTER_REFERENCE_VIEWS: tuple[str, ...] = (
    "front",
    "three_quarter_left",
    "profile_left",
)


def character_reference_set_digest(value: Mapping[str, Any]) -> str:
    """Return the canonical SHA-256 identity for a reference-set payload."""

    return stable_json_sha256(dict(value))  # type: ignore[arg-type]


class CharacterReferenceSourceAssetV1(StrictFrozenModel):
    asset_id: UUID
    content_digest: Sha256Digest
    verified: bool
    historical: bool
    ai_derived: bool
    uploaded_by: Identifier
    uploaded_at: AwareDatetime


class CharacterReferenceModelRevisionV1(StrictFrozenModel):
    model_family: Literal["flux2-dev"]
    model_id: Literal["flux2-dev-fp8mixed.v1"]
    diffusion_model_sha256: Sha256Digest
    text_encoder_sha256: Sha256Digest
    vae_sha256: Sha256Digest
    workflow_sha256: Sha256Digest
    revision: Literal["flux2-dev-fp8mixed.v1"]


class CharacterReferenceViewV1(StrictFrozenModel):
    asset_id: UUID
    view_name: CharacterReferenceViewName
    attempt_ordinal: Annotated[int, Field(ge=0, le=1)]
    image_digest: Sha256Digest
    ai_derived: Literal[True]
    historical: Literal[False]
    identity_control: Literal[True]
    model_revision: CharacterReferenceModelRevisionV1
    single_view_qc_passed: bool
    generated_at: AwareDatetime


class CharacterReferenceCrossViewQCV1(StrictFrozenModel):
    identity_consistent: bool
    age_consistent: bool
    attire_consistent: bool
    angle_correct: bool
    no_artifact: bool
    qc_run_at: AwareDatetime

    def all_gates_passed(self) -> bool:
        return all(
            (
                self.identity_consistent,
                self.age_consistent,
                self.attire_consistent,
                self.angle_correct,
                self.no_artifact,
            )
        )


class CharacterReferenceSetV1(StrictFrozenModel):
    reference_set_id: UUID
    reference_set_revision_id: UUID
    character_id: Identifier
    age_stage: Identifier
    source_asset: CharacterReferenceSourceAssetV1
    model_revision: CharacterReferenceModelRevisionV1
    views: tuple[CharacterReferenceViewV1, ...] = Field(default=(), max_length=3)
    cross_view_qc: CharacterReferenceCrossViewQCV1 | None = None
    state: CharacterReferenceState
    reference_set_digest: Sha256Digest

    @field_validator("views")
    @classmethod
    def validate_view_shape(
        cls,
        views: tuple[CharacterReferenceViewV1, ...],
    ) -> tuple[CharacterReferenceViewV1, ...]:
        names = tuple(view.view_name for view in views)
        canonical_positions = tuple(
            CANONICAL_CHARACTER_REFERENCE_VIEWS.index(name) for name in names
        )
        if canonical_positions != tuple(sorted(canonical_positions)) or len(
            names
        ) != len(set(names)):
            raise ValueError("reference views must use the canonical view order")
        digests = tuple(view.image_digest for view in views)
        if len(digests) != len(set(digests)):
            raise ValueError("reference view image digests must be unique")
        asset_ids = tuple(view.asset_id for view in views)
        if len(asset_ids) != len(set(asset_ids)):
            raise ValueError("reference view asset ids must be unique")
        return views

    @model_validator(mode="after")
    def validate_reference_set(self) -> CharacterReferenceSetV1:
        if not self.source_asset.verified:
            raise ValueError("reference source asset must be verified")
        if not self.source_asset.historical:
            raise ValueError("reference source asset must be historical")
        if self.source_asset.ai_derived:
            raise ValueError("reference source asset cannot be AI-derived")
        if any(view.model_revision != self.model_revision for view in self.views):
            raise ValueError("reference view model revision must match the set")
        if self.state == "frozen":
            if tuple(view.view_name for view in self.views) != (
                CANONICAL_CHARACTER_REFERENCE_VIEWS
            ):
                raise ValueError(
                    "frozen reference set requires exactly three canonical views"
                )
            if not all(view.single_view_qc_passed for view in self.views):
                raise ValueError("frozen reference set requires every view qc gate")
            if self.cross_view_qc is None or not self.cross_view_qc.all_gates_passed():
                raise ValueError("frozen reference set requires every cross-view qc gate")
        identity = self.model_dump(mode="json", exclude={"reference_set_digest"})
        actual = character_reference_set_digest(identity)
        if not hmac.compare_digest(actual, self.reference_set_digest):
            raise ValueError("character reference set digest mismatch")
        return self
