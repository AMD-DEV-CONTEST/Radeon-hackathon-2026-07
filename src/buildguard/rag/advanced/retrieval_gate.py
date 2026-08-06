"""Rule-first retrieval gate with optional local LLM structured judgement."""

from __future__ import annotations

import logging
from typing import Literal

from pydantic import Field

from buildguard.config import AdvancedRagConfig
from buildguard.llm.base import ChatMessage, LocalLLMBackend
from buildguard.schemas.common import StrictSchema

LOGGER = logging.getLogger(__name__)
QueryType = Literal["standard", "history", "risk", "general"]
RequestedSource = Literal[
    "construction_standards",
    "task_history",
    "inspection_results",
    "risk_events",
]


class RetrievalGateDecision(StrictSchema):
    need_retrieval: bool
    query_type: QueryType
    reason: str = Field(min_length=1, max_length=1000)
    requested_sources: list[RequestedSource] = Field(default_factory=list, max_length=4)


class RetrievalGate:
    """Mandatory rules cannot be overruled by the local language model."""

    def __init__(
        self,
        config: AdvancedRagConfig,
        backend: LocalLLMBackend | None = None,
    ) -> None:
        self.config = config
        self.backend = backend

    @staticmethod
    def _rule_type(query: str) -> QueryType:
        if "历史" in query:
            return "history"
        if "风险等级" in query:
            return "risk"
        if any(term in query for term in ("规范", "条款", "依据")):
            return "standard"
        return "general"

    @staticmethod
    def _sources(query_type: QueryType) -> list[RequestedSource]:
        if query_type == "history":
            return ["task_history"]
        if query_type == "risk":
            return ["inspection_results", "risk_events", "construction_standards"]
        if query_type == "standard":
            return ["construction_standards"]
        return []

    def decide(self, query: str) -> RetrievalGateDecision:
        normalized = query.strip()
        if not normalized:
            raise ValueError("retrieval gate query must not be empty")
        query_type = self._rule_type(normalized)
        matched = [
            term
            for term in self.config.required_retrieval_terms
            if term in normalized
        ]
        domain_matches = [
            term for term in self.config.entity_terms if term in normalized
        ]
        if matched or domain_matches:
            effective_type: QueryType = (
                query_type if query_type != "general" else "standard"
            )
            reason_terms = [*matched, *domain_matches]
            return RetrievalGateDecision(
                need_retrieval=True,
                query_type=effective_type,
                reason=(
                    "Mandatory or construction-domain local retrieval terms matched: "
                    f"{', '.join(dict.fromkeys(reason_terms))}"
                ),
                requested_sources=self._sources(effective_type),
            )
        if (
            not self.config.use_llm_gate
            or self.backend is None
        ):
            return RetrievalGateDecision(
                need_retrieval=False,
                query_type="general",
                reason="No mandatory retrieval rule matched.",
                requested_sources=[],
            )
        try:
            decision = self.backend.structured_chat(
                [
                    ChatMessage(
                        role="system",
                        content=(
                            "Decide whether this request needs local evidence retrieval. "
                            "Use only these sources: construction_standards, task_history, "
                            "inspection_results, risk_events. Return schema-valid JSON. "
                            "Do not include hidden reasoning."
                        ),
                    ),
                    ChatMessage(role="user", content=normalized),
                ],
                RetrievalGateDecision,
                thinking=False,
            )
            if decision.need_retrieval and not decision.requested_sources:
                return decision.model_copy(
                    update={
                        "requested_sources": self._sources(decision.query_type)
                        or ["construction_standards"]
                    }
                )
            return decision
        except Exception as exc:
            LOGGER.warning(
                "Local LLM retrieval gate failed; using deterministic no-rule fallback: %s",
                exc,
            )
            return RetrievalGateDecision(
                need_retrieval=False,
                query_type="general",
                reason="Local gate unavailable and no mandatory retrieval rule matched.",
                requested_sources=[],
            )
