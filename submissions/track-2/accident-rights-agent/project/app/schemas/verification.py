"""Verifier component and final policy-gate contracts."""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, ConfigDict, Field


class StrictVerificationModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class VerificationSeverity(str, Enum):
    WARNING = "warning"
    BLOCKING = "blocking"


class VerificationIssue(StrictVerificationModel):
    code: str
    message: str
    severity: VerificationSeverity
    path: str = ""
    related_ids: list[str] = Field(default_factory=list)
    required_action: str


class ComponentVerifierResult(StrictVerificationModel):
    verifier: str
    passed: bool
    issues: list[VerificationIssue] = Field(default_factory=list)
    verified_ids: list[str] = Field(default_factory=list)
    audit_event_ids: list[str] = Field(default_factory=list)


class RiskAction(str, Enum):
    HARD_BLOCK = "hard_block"
    REWRITE_REQUIRED = "rewrite_required"


class RiskLanguageMatch(StrictVerificationModel):
    pattern_id: str
    matched_text: str
    action: RiskAction
    path: str
    suggested_rewrite: str | None = None


class RiskLanguageResult(StrictVerificationModel):
    passed: bool
    matches: list[RiskLanguageMatch] = Field(default_factory=list)
    rewritten_fields: dict[str, str] = Field(default_factory=dict)
    audit_event_ids: list[str] = Field(default_factory=list)


class PolicyGateDecision(str, Enum):
    PASS = "pass"
    PASS_WITH_WARNINGS = "pass_with_warnings"
    BLOCK = "block"


class PolicyGateResult(StrictVerificationModel):
    decision: PolicyGateDecision
    blocking_issues: list[VerificationIssue] = Field(default_factory=list)
    warnings: list[VerificationIssue] = Field(default_factory=list)
    required_actions: list[str] = Field(default_factory=list)
    verified_evidence_ids: list[str] = Field(default_factory=list)
    verified_law_ids: list[str] = Field(default_factory=list)
    approval_required: bool = True
    audit_event_ids: list[str] = Field(default_factory=list)
