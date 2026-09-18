"""LangGraph state and internal structured decisions."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Literal, TypedDict

from pydantic import Field

from buildguard.llm.token_metrics import TokenMetrics
from buildguard.rag.advanced.answer_grounding import GroundingResult
from buildguard.rag.schemas import DocumentChunk
from buildguard.schemas.agent import AgentMessage, TaskPlan
from buildguard.schemas.common import StrictSchema
from buildguard.schemas.rag import RetrievedEvidence
from buildguard.schemas.tools import ToolCallResult
from buildguard.schemas.vision import InspectionResult, RiskAssessment
from buildguard.vision.routing.schemas import RoutingDecision
from buildguard.vision.schemas import EvidenceRecord


class IntentResult(StrictSchema):
    category: Literal["query", "inspection", "history", "report", "unknown"]
    complexity: Literal["simple", "multi_step"]
    confidence: float = Field(ge=0, le=1)


class VerificationResult(StrictSchema):
    valid: bool
    recoverable: bool
    reason: str = Field(min_length=1, max_length=2000)


class InspectionAnalysisDecision(StrictSchema):
    """Bounded LLM decision made only after visual evidence is available."""

    search_standards: bool = True
    standards_query: str | None = Field(default=None, max_length=4000)
    query_history: bool = False
    history_limit: int = Field(default=20, ge=1, le=100)
    reason: str = Field(min_length=1, max_length=2000)


class AgentState(TypedDict):
    session_id: str
    task_id: str
    user_query: str
    requested_action: str | None
    action: str
    image_paths: list[Path]
    intent: IntentResult | None
    inspection_analysis: InspectionAnalysisDecision | None
    plan: TaskPlan | None
    plan_phase: Literal["general", "visual", "inspection_enrichment", "risk"]
    current_step: int
    retry_count: int
    tool_results: list[ToolCallResult]
    inspection_results: list[InspectionResult]
    retrieved_evidence: list[RetrievedEvidence]
    retrieved_chunks: list[DocumentChunk]
    visual_evidence: list[EvidenceRecord]
    routing_decisions: list[RoutingDecision]
    evidence_status: Literal["not_requested", "sufficient", "insufficient_evidence"]
    tool_chain: list[str]
    new_inference_count: int
    reused_inspection_count: int
    max_risk: str
    grounding_result: GroundingResult | None
    risk_results: list[RiskAssessment]
    pending_confirmation: dict[str, Any] | None
    confirmation_granted: bool
    confirmation_denied: bool
    errors: list[str]
    final_response: str | None
    report_path: str | None
    performance_trace: list[TokenMetrics]
    memory_messages: list[AgentMessage]
    status: str
