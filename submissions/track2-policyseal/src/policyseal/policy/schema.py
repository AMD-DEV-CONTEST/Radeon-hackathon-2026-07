from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from policyseal.domain.enums import (
    Action,
    Channel,
    Classification,
    ContentCategory,
    FileKind,
    OwnerRelation,
    Purpose,
    RecipientProfile,
)


class TransformKind(StrEnum):
    KEEP_NAME_WORK_EMAIL = "keep_name_work_email"
    MASK_LAST_FOUR = "mask_last_four"
    KEEP_AUDIT_AMOUNT = "keep_audit_amount"
    FILTER_OTHER_OWNERS = "filter_other_owners"
    GENERALIZE_APPROVAL_STATUS = "generalize_approval_status"
    GENERALIZE_SHORTLIST_STATUS = "generalize_shortlist_status"
    STABLE_ASSET_ALIAS = "stable_asset_alias"
    STABLE_PERSON_ALIAS = "stable_person_alias"
    PLACEHOLDER_BUYER = "placeholder_buyer"
    PLACEHOLDER_SUPPLIER = "placeholder_supplier"
    PLACEHOLDER_CORPORATE_ID = "placeholder_corporate_id"
    PLACEHOLDER_CONTACT = "placeholder_contact"
    PLACEHOLDER_CONTRACT_DATE = "placeholder_contract_date"
    PLACEHOLDER_HISTORICAL_PRICING = "placeholder_historical_pricing"


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class RuleConditions(StrictModel):
    file_kinds: tuple[FileKind, ...] = ()
    recipients: tuple[RecipientProfile, ...] = ()
    purposes: tuple[Purpose, ...] = ()
    channels: tuple[Channel, ...] = ()
    classifications: tuple[Classification, ...] = ()
    categories: tuple[ContentCategory, ...] = ()
    owner_relations: tuple[OwnerRelation, ...] = ()


class EvidenceRecord(StrictModel):
    id: str = Field(pattern=r"^EV-[A-Z0-9-]+$")
    path: str = Field(pattern=r"^evidence/[a-z0-9-]+\.md$")
    title: str = Field(min_length=3, max_length=120)
    tags: tuple[str, ...] = ()


class PolicyRule(StrictModel):
    id: str = Field(pattern=r"^PS-[A-Z0-9-]+$")
    reason_code: str = Field(pattern=r"^[a-z][a-z0-9_]+$")
    reason: str = Field(min_length=8, max_length=300)
    priority: int = Field(default=100, ge=0, le=1000)
    enabled: bool = True
    when: RuleConditions
    action: Action
    transform: TransformKind | None = None
    evidence_ids: tuple[str, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_transform(self) -> PolicyRule:
        transform_actions = {Action.MASK, Action.FILTER, Action.GENERALIZE}
        if self.action in transform_actions and self.transform is None:
            raise ValueError(f"{self.action.value} requires a deterministic transform")
        if self.action not in transform_actions and self.transform is not None:
            raise ValueError(f"{self.action.value} cannot declare a transform")
        return self


class PolicyDefinition(StrictModel):
    version: str = Field(pattern=r"^[0-9]+\.[0-9]+\.[0-9]+$")
    name: str = Field(min_length=3, max_length=120)
    synthetic_only: Literal[True]
    default_action: Action
    evidence: tuple[EvidenceRecord, ...]
    rules: tuple[PolicyRule, ...]

    @model_validator(mode="after")
    def validate_fail_closed_default(self) -> PolicyDefinition:
        if self.default_action not in {Action.REQUIRE_APPROVAL, Action.BLOCK}:
            raise ValueError("the policy default must fail closed")
        return self


@dataclass(frozen=True, slots=True)
class PolicyPack:
    definition: PolicyDefinition
    sha256: str
    root: Path

    @property
    def version(self) -> str:
        return self.definition.version

    @property
    def rules(self) -> tuple[PolicyRule, ...]:
        return self.definition.rules

    @property
    def evidence(self) -> tuple[EvidenceRecord, ...]:
        return self.definition.evidence

    @property
    def default_action(self) -> Action:
        return self.definition.default_action
