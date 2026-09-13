"""
IncidentInvestigationState — the shared state object every LangGraph node
reads from and writes to. This is the "shared memory" agents coordinate
through, distinct from the long-term MemoryService (which persists across
incidents, not just within one investigation).
"""
from typing import Any, Optional, TypedDict


class Hypothesis(TypedDict):
    statement: str
    confidence: float
    supporting_evidence_ids: list[str]


class IncidentInvestigationState(TypedDict, total=False):
    incident_id: str
    title: str
    description: str
    service_hint: Optional[str]

    # Populated by the Planner
    investigation_plan: list[str]          # which specialist agents to invoke
    hypotheses_to_test: list[str]

    # Populated by specialist agents (accumulated, not overwritten, via reducer)
    evidence: list[dict[str, Any]]

    # Populated by the Synthesizer
    ranked_hypotheses: list[Hypothesis]
    root_cause_summary: Optional[str]
    root_cause_confidence: Optional[float]

    # Populated by the Remediation agent / human-approval interrupt
    proposed_action: Optional[dict[str, Any]]
    remediation_approved: Optional[bool]
    remediation_result: Optional[dict[str, Any]]

    # Bookkeeping
    agent_run_id: str
    step_sequence: int
