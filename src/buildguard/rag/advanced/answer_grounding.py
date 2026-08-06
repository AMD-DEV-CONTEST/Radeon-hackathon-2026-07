"""Sentence-level removal of unsupported normative claims."""

from __future__ import annotations

import re

from pydantic import Field

from buildguard.config import AdvancedRagConfig
from buildguard.rag.embedding_backend import lexical_tokens
from buildguard.rag.retriever import STANDARD_PATTERN
from buildguard.rag.schemas import DocumentChunk
from buildguard.schemas.common import StrictSchema

SENTENCE_PATTERN = re.compile(r"[^。！？!?；;\n]+[。！？!?；;]?")
CITATION_ONLY_PATTERN = re.compile(
    r"^\s*[\[(][0-9a-fA-F]{32,64}[\])]\s*$"
)
ARTICLE_PATTERN = re.compile(r"第[一二三四五六七八九十百\d]+条")
PAGE_PATTERN = re.compile(r"(?:第\s*(\d+)\s*页|p\.?\s*(\d+))", re.IGNORECASE)
MANDATORY_TERMS = ("必须", "应当", "严禁", "不得", "禁止")
SUGGESTION_TERMS = ("建议", "推荐", "可考虑", "宜")


class GroundingResult(StrictSchema):
    supported_claims: list[str] = Field(default_factory=list)
    unsupported_claims: list[str] = Field(default_factory=list)
    final_safe_answer: str = Field(min_length=1)
    issues: dict[str, list[str]] = Field(default_factory=dict)


def _compact(value: str) -> str:
    return re.sub(r"\s+", "", value).upper()


class AnswerGrounder:
    def __init__(self, config: AdvancedRagConfig) -> None:
        self.config = config

    @staticmethod
    def _sentences(answer: str) -> list[str]:
        sentences: list[str] = []
        for match in SENTENCE_PATTERN.finditer(answer):
            sentence = match.group(0).strip()
            if not sentence:
                continue
            if CITATION_ONLY_PATTERN.fullmatch(sentence) and sentences:
                sentences[-1] = f"{sentences[-1]} {sentence}"
            else:
                sentences.append(sentence)
        return sentences

    def _lexical_support(
        self,
        sentence: str,
        chunks: list[DocumentChunk],
    ) -> tuple[float, list[str]]:
        tokens = {
            token
            for token in lexical_tokens(sentence)
            if len(token) >= 2
        }
        best_coverage = 0.0
        supporting: list[str] = []
        for chunk in chunks:
            content_tokens = set(
                lexical_tokens(
                    f"{chunk.document_name} {chunk.article or ''} {chunk.content}"
                )
            )
            coverage = (
                len(tokens & content_tokens) / len(tokens)
                if tokens
                else 1.0
            )
            if coverage > best_coverage:
                best_coverage = coverage
                supporting = [chunk.chunk_id]
            elif coverage == best_coverage and coverage > 0:
                supporting.append(chunk.chunk_id)
        return best_coverage, supporting

    def validate(
        self,
        answer: str,
        chunks: list[DocumentChunk],
    ) -> GroundingResult:
        if not answer.strip():
            raise ValueError("answer grounding input must not be empty")
        combined = "\n".join(
            f"{chunk.document_name}\n{chunk.article or ''}\n{chunk.content}"
            for chunk in chunks
        )
        compact_evidence = _compact(combined)
        evidence_articles = {
            article
            for chunk in chunks
            for article in (
                [chunk.article] if chunk.article is not None else []
            )
        }
        evidence_pages = {
            chunk.page for chunk in chunks if chunk.page is not None
        }
        supported: list[str] = []
        unsupported: list[str] = []
        issues: dict[str, list[str]] = {}
        for sentence in self._sentences(answer):
            reasons: list[str] = []
            standards = STANDARD_PATTERN.findall(sentence)
            for standard in standards:
                if _compact(standard) not in compact_evidence:
                    reasons.append(f"unretrieved_standard:{standard}")
            articles = ARTICLE_PATTERN.findall(sentence)
            for article in articles:
                if article not in evidence_articles and article not in combined:
                    reasons.append(f"nonexistent_article:{article}")
            page_matches = PAGE_PATTERN.findall(sentence)
            for first, second in page_matches:
                page = int(first or second)
                if page not in evidence_pages:
                    reasons.append(f"incorrect_page:{page}")
            if (
                any(term in sentence for term in SUGGESTION_TERMS)
                and any(term in sentence for term in MANDATORY_TERMS)
            ):
                reasons.append("suggestion_presented_as_mandatory")
            coverage, _ = self._lexical_support(sentence, chunks)
            if coverage < self.config.grounding_min_coverage:
                reasons.append("insufficient_lexical_support")
            if (
                any(term in sentence for term in MANDATORY_TERMS)
                and coverage < max(0.6, self.config.grounding_min_coverage)
            ):
                reasons.append("unsupported_mandatory_claim")
            if not chunks:
                reasons.append("no_retrieved_evidence")
            if reasons:
                unsupported.append(sentence)
                issues[sentence] = list(dict.fromkeys(reasons))
            else:
                supported.append(sentence)
        final = "".join(supported).strip()
        if not final:
            final = self.config.refusal_message
        return GroundingResult(
            supported_claims=supported,
            unsupported_claims=unsupported,
            final_safe_answer=final,
            issues=issues,
        )
