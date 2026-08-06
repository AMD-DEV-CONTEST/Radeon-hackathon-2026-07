"""Meaning-preserving local retrieval query expansion."""

from __future__ import annotations

import logging
import re

from pydantic import Field, field_validator

from buildguard.config import AdvancedRagConfig
from buildguard.llm.base import ChatMessage, LocalLLMBackend
from buildguard.rag.embedding_backend import lexical_tokens
from buildguard.rag.retriever import STANDARD_PATTERN
from buildguard.schemas.common import StrictSchema

LOGGER = logging.getLogger(__name__)


class QueryRewriteProposal(StrictSchema):
    queries: list[str] = Field(default_factory=list, max_length=2)

    @field_validator("queries")
    @classmethod
    def non_empty_queries(cls, value: list[str]) -> list[str]:
        cleaned = [item.strip() for item in value]
        if any(not item for item in cleaned):
            raise ValueError("rewritten queries must not be empty")
        return cleaned


class QueryRewriteResult(StrictSchema):
    original_query: str = Field(min_length=1, max_length=4000)
    queries: list[str] = Field(min_length=1, max_length=3)
    used_llm: bool

    @field_validator("queries")
    @classmethod
    def unique_queries(cls, value: list[str]) -> list[str]:
        if len(value) != len(set(value)):
            raise ValueError("rewritten queries must be unique")
        return value


def _standard_ids(value: str) -> set[str]:
    return {
        item.replace(" ", "").upper()
        for item in STANDARD_PATTERN.findall(value)
    }


class QueryRewriter:
    def __init__(
        self,
        config: AdvancedRagConfig,
        backend: LocalLLMBackend | None = None,
    ) -> None:
        self.config = config
        self.backend = backend

    @staticmethod
    def _preserves_intent(original: str, candidate: str) -> bool:
        if not candidate or len(candidate) > 4000:
            return False
        required_standards = _standard_ids(original)
        candidate_standards = _standard_ids(candidate)
        candidate_compact = candidate.replace(" ", "").upper()
        if not all(identifier in candidate_compact for identifier in required_standards):
            return False
        if candidate_standards != required_standards:
            return False
        original_tokens = {
            token for token in lexical_tokens(original) if len(token) >= 2
        }
        candidate_tokens = set(lexical_tokens(candidate))
        if original in candidate or not original_tokens:
            return True
        return (
            len(original_tokens & candidate_tokens) / len(original_tokens)
            >= 0.5
        )

    def _professional_query(self, query: str) -> str:
        rewritten = query
        for source, professional in sorted(
            self.config.professional_term_mappings.items()
        ):
            if source in rewritten:
                rewritten = rewritten.replace(source, professional)
        return rewritten

    @staticmethod
    def _standard_query(query: str) -> str:
        standards = STANDARD_PATTERN.findall(query)
        articles = re.findall(r"第[一二三四五六七八九十百\d]+条", query)
        suffix = " ".join([*standards, *articles, "施工安全 规范 条款"])
        return f"{query} {suffix}".strip()

    def rewrite(self, query: str) -> QueryRewriteResult:
        original = query.strip()
        if not original:
            raise ValueError("query rewrite input must not be empty")
        candidates: list[str] = [original]
        used_llm = False
        if self.config.use_llm_rewriter and self.backend is not None:
            try:
                proposal = self.backend.structured_chat(
                    [
                        ChatMessage(
                            role="system",
                            content=(
                                "Return at most two local retrieval query rewrites. "
                                "Preserve every user constraint and standard identifier. "
                                "One rewrite should use professional terminology and one "
                                "should emphasize standard numbers or keywords. JSON only."
                            ),
                        ),
                        ChatMessage(role="user", content=original),
                    ],
                    QueryRewriteProposal,
                    thinking=False,
                )
                for candidate in proposal.queries:
                    if candidate not in candidates and self._preserves_intent(original, candidate):
                        candidates.append(candidate)
                used_llm = len(candidates) > 1
            except Exception as exc:
                LOGGER.warning(
                    "Local query rewrite failed; using deterministic rewrites: %s",
                    exc,
                )
        for candidate in (
            self._professional_query(original),
            self._standard_query(original),
        ):
            if (
                len(candidates) >= 3
                or candidate in candidates
                or not self._preserves_intent(original, candidate)
            ):
                continue
            candidates.append(candidate)
        return QueryRewriteResult(
            original_query=original,
            queries=candidates[:3],
            used_llm=used_llm,
        )
