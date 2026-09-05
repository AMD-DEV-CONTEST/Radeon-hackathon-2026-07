"""Isolated E3/M2 contracts for timeline and critical-moment preparation."""

from __future__ import annotations

from typing import Annotated, Literal
from uuid import UUID

from pydantic import AwareDatetime, ConfigDict, Field, model_validator

from .enums import MilestoneState
from .models import ContractModel, NonEmptyText

M2ArtifactState = Literal[
    MilestoneState.NEEDS_INPUT,
    MilestoneState.REVIEW_READY,
    MilestoneState.CONFIRMED,
    MilestoneState.COMPLETE_WITH_GAPS,
    MilestoneState.INVALIDATED,
]
CriticalityStatus = Literal["AGENT_PROPOSED", "UNRESOLVED", "USER_CONFIRMED"]
UserCriticalityDecision = Literal["UNRESOLVED", "USER_CONFIRMED"]


class M2CreateRequestV1(ContractModel):
    expected_m1_version_id: UUID


class M2MomentEditV1(ContractModel):
    moment_id: UUID
    title: NonEmptyText
    criticality_status: UserCriticalityDecision | None = None


class M2EditRequestV1(ContractModel):
    expected_artifact_id: UUID
    moments: list[M2MomentEditV1] = Field(min_length=1)

    @model_validator(mode="after")
    def moment_ids_are_unique(self) -> M2EditRequestV1:
        ids = [moment.moment_id for moment in self.moments]
        if len(ids) != len(set(ids)):
            raise ValueError("moment edit IDs must be unique")
        return self


class M2ConfirmRequestV1(ContractModel):
    expected_artifact_id: UUID
    complete_with_gaps: bool = False


class CriticalMomentEntryBaseV1(ContractModel):
    """Common source-linked content; display order is not a claimed calendar date."""

    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={
            "allOf": [
                {
                    "if": {
                        "properties": {
                            "criticality_status": {"const": "USER_CONFIRMED"}
                        },
                        "required": ["criticality_status"],
                    },
                    "then": {
                        "properties": {
                            "criticality_confirmed_at": {
                                "format": "date-time",
                                "type": "string",
                            }
                        },
                        "required": ["criticality_confirmed_at"],
                    },
                    "else": {
                        "properties": {
                            "criticality_confirmed_at": {
                                "type": "null"
                            }
                        }
                    },
                }
            ]
        },
    )

    moment_id: UUID
    display_order: int = Field(ge=0)
    title: NonEmptyText
    description: NonEmptyText
    criticality_status: CriticalityStatus
    criticality_reason: NonEmptyText
    criticality_confirmed_at: AwareDatetime | None = None
    source_statement_ids: list[UUID] = Field(min_length=1, json_schema_extra={"uniqueItems": True})
    cue_statement_ids: list[UUID]
    change_statement_ids: list[UUID]
    surprise_statement_ids: list[UUID]

    @model_validator(mode="after")
    def detail_references_are_source_linked(self) -> CriticalMomentEntryBaseV1:
        if len(self.source_statement_ids) != len(set(self.source_statement_ids)):
            raise ValueError("moment source statement IDs must be unique")
        referenced = {
            *self.cue_statement_ids,
            *self.change_statement_ids,
            *self.surprise_statement_ids,
        }
        if not referenced.issubset(set(self.source_statement_ids)):
            raise ValueError("moment detail IDs must be included in source_statement_ids")
        if self.criticality_status == "USER_CONFIRMED":
            if self.criticality_confirmed_at is None:
                raise ValueError(
                    "USER_CONFIRMED criticality requires trusted confirmation provenance"
                )
        elif self.criticality_confirmed_at is not None:
            raise ValueError(
                "only USER_CONFIRMED criticality may carry confirmation provenance"
            )
        return self


class KnownTimeMomentV1(CriticalMomentEntryBaseV1):
    temporal_status: Literal["KNOWN"]
    time_label: NonEmptyText
    conflict_statement_ids: list[UUID] = Field(max_length=0)
    unresolved_reason: None


class MissingTimeMomentV1(CriticalMomentEntryBaseV1):
    temporal_status: Literal["MISSING"]
    time_label: None
    conflict_statement_ids: list[UUID] = Field(max_length=0)
    unresolved_reason: NonEmptyText


class ConflictingTimeMomentV1(CriticalMomentEntryBaseV1):
    temporal_status: Literal["CONFLICTING"]
    time_label: None
    conflict_statement_ids: list[UUID] = Field(
        min_length=2, json_schema_extra={"uniqueItems": True}
    )
    unresolved_reason: NonEmptyText

    @model_validator(mode="after")
    def conflict_sources_are_distinct_and_linked(self) -> ConflictingTimeMomentV1:
        conflicts = set(self.conflict_statement_ids)
        if len(conflicts) != len(self.conflict_statement_ids):
            raise ValueError("conflict statement IDs must be distinct")
        if not conflicts.issubset(set(self.source_statement_ids)):
            raise ValueError("conflict statement IDs must be included in source_statement_ids")
        return self


CriticalMomentEntryV1 = Annotated[
    KnownTimeMomentV1 | MissingTimeMomentV1 | ConflictingTimeMomentV1,
    Field(discriminator="temporal_status"),
]


class CriticalMomentMapV1(ContractModel):
    """M2 artifact bound to one accepted M1 version and its source statements."""

    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={
            "allOf": [
                {
                    "if": {
                        "properties": {"state": {"const": "INVALIDATED"}},
                        "required": ["state"],
                    },
                    "then": {
                        "properties": {
                            "invalidated_by_m1_version_id": {
                                "format": "uuid",
                                "type": "string",
                            },
                            "invalidation_reason": {
                                "minLength": 1,
                                "type": "string",
                            },
                        }
                    },
                    "else": {
                        "properties": {
                            "invalidated_by_m1_version_id": {"type": "null"},
                            "invalidation_reason": {"type": "null"},
                        }
                    },
                }
            ]
        },
    )

    schema_version: Literal["0.1.0"] = "0.1.0"
    artifact_id: UUID
    asset_id: UUID
    base_m1_version_id: UUID
    generated_by_run_id: UUID
    state: M2ArtifactState
    order_basis: Literal["SOURCE_ASSERTED", "NARRATIVE_SEQUENCE", "PARTIAL_ORDER"]
    moments: list[CriticalMomentEntryV1]
    dependency_statement_ids: list[UUID] = Field(
        min_length=1, json_schema_extra={"uniqueItems": True}
    )
    unresolved_question_ids: list[UUID]
    created_at: AwareDatetime
    updated_at: AwareDatetime
    invalidated_by_m1_version_id: UUID | None
    invalidation_reason: NonEmptyText | None

    @model_validator(mode="after")
    def map_invariants_hold(self) -> CriticalMomentMapV1:
        if len(self.dependency_statement_ids) != len(set(self.dependency_statement_ids)):
            raise ValueError("dependency statement IDs must be unique")

        moment_ids = [moment.moment_id for moment in self.moments]
        if len(moment_ids) != len(set(moment_ids)):
            raise ValueError("critical moment IDs must be unique")

        display_orders = [moment.display_order for moment in self.moments]
        if display_orders != sorted(display_orders) or len(display_orders) != len(
            set(display_orders)
        ):
            raise ValueError("critical moments must have unique ascending display_order values")

        dependencies = set(self.dependency_statement_ids)
        if any(
            not set(moment.source_statement_ids).issubset(dependencies) for moment in self.moments
        ):
            raise ValueError("moment source statements must be declared map dependencies")

        is_invalidated = self.state == MilestoneState.INVALIDATED
        if is_invalidated:
            if self.invalidated_by_m1_version_id is None or not self.invalidation_reason:
                raise ValueError("INVALIDATED state requires a version and non-empty reason")
            if self.invalidated_by_m1_version_id == self.base_m1_version_id:
                raise ValueError("invalidation must reference a new M1 version")
        elif self.invalidated_by_m1_version_id is not None or self.invalidation_reason is not None:
            raise ValueError("only INVALIDATED state may carry invalidation provenance")
        return self


class M2WorkspaceV1(ContractModel):
    artifact: CriticalMomentMapV1
    is_current: bool
    history_artifact_ids: list[UUID]
    allowed_actions: list[Literal["EDIT", "CONFIRM", "REGENERATE"]]
