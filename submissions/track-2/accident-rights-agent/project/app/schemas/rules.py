"""Versioned deterministic-rule and compensation-routing contracts."""

from __future__ import annotations

import hashlib
import json
from datetime import date, datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.schemas.business import CompensationRegime
from app.schemas.legal import LegalCitation


class StrictRuleModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class RuleStatus(str, Enum):
    EFFECTIVE = "effective"
    EXPIRED = "expired"
    NOT_YET_EFFECTIVE = "not_yet_effective"
    PROPOSED = "proposed"


class RuleAuthority(StrictRuleModel):
    source_law_id: str
    source_article: str
    source_url: str = Field(pattern=r"^https://")
    retrieved_at: datetime
    effective_date: date
    note: str = ""


class RuleDefinition(StrictRuleModel):
    rule_id: str = Field(pattern=r"^RULE-[A-Z0-9._-]+$")
    title: str
    rule_type: str
    jurisdiction: str
    authority_level: str
    source_law_id: str
    source_article: str
    source_url: str = Field(pattern=r"^https://")
    retrieved_at: datetime
    version: str
    promulgation_date: date
    effective_date: date
    expiry_date: date | None = None
    status: RuleStatus
    conditions: dict[str, Any]
    decision_logic: dict[str, Any]
    outputs: dict[str, Any]
    exceptions: list[dict[str, Any]] = Field(default_factory=list)
    confidence_policy: dict[str, Any]
    supporting_authorities: list[RuleAuthority] = Field(default_factory=list)
    content_hash: str = Field(pattern=r"^[a-f0-9]{64}$")

    @model_validator(mode="after")
    def dates_are_ordered(self) -> "RuleDefinition":
        if self.expiry_date and self.expiry_date <= self.effective_date:
            raise ValueError("Rule expiry_date must be after effective_date.")
        return self

    def applies(self, *, as_of_date: date, jurisdiction: str) -> bool:
        jurisdiction_matches = (
            self.jurisdiction == jurisdiction
            or self.jurisdiction == "CN"
            or jurisdiction.startswith(f"{self.jurisdiction}/")
        )
        return (
            jurisdiction_matches
            and self.status is RuleStatus.EFFECTIVE
            and self.effective_date <= as_of_date
            and (self.expiry_date is None or as_of_date < self.expiry_date)
        )


def rule_content_hash(payload: dict[str, Any]) -> str:
    canonical = {key: value for key, value in payload.items() if key != "content_hash"}
    encoded = json.dumps(
        canonical, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


class RuleSelectionStatus(str, Enum):
    SELECTED = "selected"
    CONFLICT = "conflict"
    NOT_FOUND = "not_found"


class RuleSelectionResult(StrictRuleModel):
    status: RuleSelectionStatus
    selected_rule: RuleDefinition | None = None
    conflicting_rule_ids: list[str] = Field(default_factory=list)
    reason: str


class InsuranceLayerStatus(str, Enum):
    APPLICABLE = "applicable"
    PENDING = "pending"
    INSUFFICIENT_DATA = "insufficient_data"
    NOT_APPLICABLE = "not_applicable"


class InsuranceLayer(StrictRuleModel):
    status: InsuranceLayerStatus
    order: int = Field(ge=1)
    estimated_amount: float | None = Field(default=None, ge=0)
    required_inputs: list[str] = Field(default_factory=list)
    rule_ids: list[str] = Field(default_factory=list)
    law_ids: list[str] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def missing_data_has_no_amount(self) -> "InsuranceLayer":
        if self.status in {
            InsuranceLayerStatus.INSUFFICIENT_DATA,
            InsuranceLayerStatus.PENDING,
        } and self.estimated_amount is not None:
            raise ValueError("Pending or insufficient-data layers cannot estimate amounts.")
        return self


class CompensationRouteResult(StrictRuleModel):
    regime: CompensationRegime
    accident_responsibility: dict[str, Any]
    civil_compensation_allocation: dict[str, Any]
    compulsory_insurance_layer: InsuranceLayer
    commercial_insurance_layer: InsuranceLayer
    uninsured_or_uncovered_loss: InsuranceLayer
    insurance_payment_estimate: dict[str, Any]
    rule_ids: list[str]
    law_ids: list[str]
    legal_citations: list[LegalCitation]
    assumptions: list[str]
    uncertainty: list[str]
