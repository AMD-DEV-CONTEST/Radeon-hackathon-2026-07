"""Shared graph state and node execution envelopes."""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any, TypedDict

from pydantic import BaseModel, ConfigDict, Field


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class NodeStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    BLOCKED = "blocked"
    NEEDS_HUMAN = "needs_human"
    SKIPPED = "skipped"


class NodeResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: NodeStatus
    started_at: str
    finished_at: str
    inputs_hash: str
    outputs: dict[str, Any] = Field(default_factory=dict)
    warnings: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
    retry_count: int = Field(default=0, ge=0, le=1)
    metrics: dict[str, float | int | str] = Field(default_factory=dict)


class CaseState(TypedDict, total=False):
    """LangGraph-compatible state; Evidence Graph fields stay in SQLite."""

    case_id: str
    thread_id: str
    current_node: str
    progress: float
    route: str
    approval_status: str
    document_status: str
    interrupt_after: str | None
    simulate_json_error_at: str | None
    simulate_failure_at: str | None
    node_results: dict[str, dict[str, Any]]
    legal_queries: list[str]
    legal_citations: list[dict[str, Any]]
    intake_assessment: dict[str, Any]
    blocking_issues: list[dict[str, Any]]
    missing_evidence: list[dict[str, Any]]
    evidence_summary: dict[str, Any]
    case_capsule: dict[str, Any]
    vehicle_classification: dict[str, Any]
    vehicle_nature_result: dict[str, Any]
    parameter_comparison: list[dict[str, Any]]
    violation_matrix: list[dict[str, Any]]
    causation_matrix: list[dict[str, Any]]
    liability_hypotheses: list[dict[str, Any]]
    liability_result: dict[str, Any]
    responsibility_probabilities: dict[str, float]
    accident_responsibility: dict[str, Any]
    civil_compensation_allocation: dict[str, Any]
    insurance_payment_estimate: dict[str, Any]
    counterfactual_analysis: list[dict[str, Any]]
    delivery_date_result: dict[str, Any]
    appraisal_delivery_date_result: dict[str, Any]
    deadlines: list[dict[str, Any]]
    rights_tasks: list[dict[str, Any]]
    evidence_collection_plan: list[dict[str, Any]]
    review_application_draft: dict[str, Any]
    approval_state: dict[str, Any]
    compensation_route_result: dict[str, Any]
    vehicle_rule_assessment: dict[str, Any]
    verifier_results: dict[str, Any]
    policy_gate: dict[str, Any]
    context_metrics: dict[str, int]
    protected_fields_valid: bool
    branch_reason: str
    rights_branch_reason: str
    human_action_required: bool
    warnings: list[str]
    errors: list[str]
