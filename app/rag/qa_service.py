"""QA Service — answer questions with evidence from project documents.

B-06 specification delivers:
- Answers that cite sources when evidence exists
- Explicit "no evidence" refusal when evidence is absent
- Benchmark recording of hit rate, citation correctness, and refusals
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from app.rag.retriever import Retriever
from app.schemas.models import Evidence

NO_EVIDENCE_MSG = "未在项目资料中找到相关证据，无法回答该问题。"

# ── QA result models ────────────────────────────────────────────────────────


@dataclass
class QAResult:
    """Single question-answer result with evidence tracking."""

    question: str
    answer: str
    evidence: list[Evidence] = field(default_factory=list)
    has_evidence: bool = False
    is_refused: bool = False
    sources_used: list[str] = field(default_factory=list)  # relative_path
    # Benchmark fields
    hit: bool = False          # True when any evidence was retrieved
    citation_correct: bool = False  # True when answer contains source references


@dataclass
class QABenchmark:
    """Benchmark recorder for 20-question test suite.

    Tracks hit rate, citation correctness, and refusal results
    across factual, cross-file, and no-answer question categories.
    """

    total: int = 0
    factual_total: int = 0
    factual_hits: int = 0
    factual_citation_correct: int = 0
    cross_file_total: int = 0
    cross_file_hits: int = 0
    cross_file_citation_correct: int = 0
    no_answer_total: int = 0
    no_answer_refused: int = 0
    results: list[QAResult] = field(default_factory=list)

    def record(self, result: QAResult, category: str) -> None:
        """Record a single QA result."""
        self.total += 1
        self.results.append(result)
        if category == "factual":
            self.factual_total += 1
            if result.hit:
                self.factual_hits += 1
            if result.citation_correct:
                self.factual_citation_correct += 1
        elif category == "cross_file":
            self.cross_file_total += 1
            if result.hit:
                self.cross_file_hits += 1
            if result.citation_correct:
                self.cross_file_citation_correct += 1
        elif category == "no_answer":
            self.no_answer_total += 1
            if result.is_refused:
                self.no_answer_refused += 1

    @property
    def hit_rate(self) -> float:
        """Overall hit rate (factual + cross-file)."""
        total_robust = self.factual_total + self.cross_file_total
        if total_robust == 0:
            return 0.0
        hits = self.factual_hits + self.cross_file_hits
        return hits / total_robust

    @property
    def citation_rate(self) -> float:
        """Overall citation correctness rate."""
        total_robust = self.factual_total + self.cross_file_total
        if total_robust == 0:
            return 0.0
        correct = self.factual_citation_correct + self.cross_file_citation_correct
        return correct / total_robust

    @property
    def refusal_rate(self) -> float:
        """Refusal rate for no-answer questions."""
        if self.no_answer_total == 0:
            return 0.0
        return self.no_answer_refused / self.no_answer_total

    def summary(self) -> str:
        """Human-readable benchmark summary."""
        lines = [
            "=" * 60,
            "QA Benchmark Results",
            "=" * 60,
            f"Total questions: {self.total}",
            f"  Factual ({self.factual_total}): "
            f"hits={self.factual_hits}/{self.factual_total}, "
            f"citation_correct={self.factual_citation_correct}/{self.factual_total}",
            f"  Cross-file ({self.cross_file_total}): "
            f"hits={self.cross_file_hits}/{self.cross_file_total}, "
            f"citation_correct={self.cross_file_citation_correct}/{self.cross_file_total}",
            f"  No-answer ({self.no_answer_total}): "
            f"refused={self.no_answer_refused}/{self.no_answer_total}",
            "-" * 60,
            f"Overall hit rate:       {self.hit_rate:.1%}",
            f"Overall citation rate:  {self.citation_rate:.1%}",
            f"No-answer refusal rate: {self.refusal_rate:.1%}",
            "=" * 60,
        ]
        return "\n".join(lines)


# ── QA Service ──────────────────────────────────────────────────────────────


class QAService:
    """Question-answering over project document index.

    Two modes:
    - ``use_llm=True`` — calls LLM API to generate answers with source citations
    - ``use_llm=False`` — mock mode, builds answer from evidence excerpts (for testing)
    """

    def __init__(
        self,
        retriever: Retriever,
        *,
        use_llm: bool = False,
        score_threshold: float = 0.35,
        bm25_only: bool = False,
    ):
        self._retriever = retriever
        self._use_llm = use_llm
        self._score_threshold = score_threshold
        self._bm25_only = bm25_only

    def ask(self, question: str) -> QAResult:
        """Answer a single question, returning a QAResult."""
        evidence = self._retriever.search(
            question, top_k=5, min_score=self._score_threshold, bm25_only=self._bm25_only
        )

        if not evidence:
            return QAResult(
                question=question,
                answer=NO_EVIDENCE_MSG,
                evidence=[],
                has_evidence=False,
                is_refused=True,
                sources_used=[],
                hit=False,
                citation_correct=True,  # Correctly refused
            )

        # Build answer
        sources = sorted({e.relative_path for e in evidence})
        if self._use_llm:
            answer = self._llm_answer(question, evidence)
        else:
            answer = self._mock_answer(question, evidence)

        # Detect LLM refusal even when evidence is present
        if self._is_refusal(answer):
            return QAResult(
                question=question,
                answer=answer,
                evidence=evidence,
                has_evidence=False,
                is_refused=True,
                sources_used=[],
                hit=False,
                citation_correct=True,
            )

        # Determine if answer cites sources
        citation_correct = self._check_citations(answer, sources)

        return QAResult(
            question=question,
            answer=answer,
            evidence=evidence,
            has_evidence=True,
            is_refused=False,
            sources_used=sources,
            hit=True,
            citation_correct=citation_correct,
        )

    def ask_batch(
        self,
        questions: list[dict],
        *,
        category: str = "factual",
    ) -> QABenchmark:
        """Ask a batch of questions and record benchmark results.

        Each dict should have ``"q"`` key.
        """
        benchmark = QABenchmark()
        for item in questions:
            result = self.ask(item["q"])
            benchmark.record(result, category)
        return benchmark

    # ── internal helpers ─────────────────────────────────────────────────

    def _mock_answer(self, question: str, evidence: list[Evidence]) -> str:
        """Build a deterministic answer from evidence excerpts (no LLM call).

        Produces an answer with explicit source citations.
        """
        lines = [f"问题: {question}", "", "根据项目资料："]
        seen_files: set[str] = set()
        source_idx = 1
        for i, e in enumerate(evidence):
            label = f"[来源{source_idx}]"
            if e.relative_path not in seen_files:
                seen_files.add(e.relative_path)
                lines.append(f"\n{label} {e.relative_path}")
            else:
                lines.append(f"\n{label} (同上)")
            lines.append(f"  位置: {e.locator}")
            lines.append(f"  内容: {e.excerpt}")
            source_idx += 1

        lines.append(f"\n以上信息来自 {len(seen_files)} 个项目文件。")
        return "\n".join(lines)

    def _llm_answer(self, question: str, evidence: list[Evidence]) -> str:
        """Call LLM API to generate answer with forced source citations."""
        prompt = self._build_qa_prompt(question, evidence)

        import httpx

        from app.config import Settings

        settings = Settings()
        resp = httpx.post(
            f"{settings.llm_base_url}/chat/completions",
            json={
                "model": settings.llm_model,
                "messages": [
                    {
                        "role": "system",
                        "content": (
                            "你是一个项目资料问答助手。请严格根据提供的证据回答问题。"
                            "每条回答必须引用来源文件。"
                            "如果证据不足以回答问题，请明确表示无法回答。"
                        ),
                    },
                    {"role": "user", "content": prompt},
                ],
                "temperature": 0.1,
            },
            timeout=60,
        )
        resp.raise_for_status()
        data = resp.json()
        return data["choices"][0]["message"]["content"]

    @staticmethod
    def _build_qa_prompt(question: str, evidence: list[Evidence]) -> str:
        """Build LLM prompt with evidence blocks and citation requirement."""
        parts = [
            f"问题：{question}",
            "",
            "请根据以下项目资料证据回答问题。每条回答必须明确标注来源文件的路径。",
            "",
        ]
        for i, e in enumerate(evidence, 1):
            parts.append(f"--- 证据 {i} ---")
            parts.append(f"文件: {e.relative_path}")
            parts.append(f"位置: {e.locator}")
            parts.append(f"内容: {e.excerpt}")
            parts.append("")

        parts.append("请回答上述问题，并在回答中引用具体的来源文件路径。")
        parts.append("如果证据不足以回答，请明确说「未在项目资料中找到相关证据」。")
        return "\n".join(parts)

    @staticmethod
    def _is_refusal(answer: str) -> bool:
        """Detect if the LLM answer is a refusal despite having evidence.

        检查回答前 30 字内是否包含拒绝语，容忍 LLM 开头的小幅措辞差异。
        """
        refusal_phrases = [
            "未在项目资料中找到相关证据",
            "未在项目资料中找到",
            "未找到相关证据",
            "未在项目资料中",
            "无法回答该问题",
            "无法提供相关信息",
            "资料中未包含相关",
            "资料中没有相关",
            "证据不足以",
        ]
        prefix = answer.strip()[:30]
        return any(phrase in prefix for phrase in refusal_phrases)

    @staticmethod
    def _check_citations(answer: str, sources: list[str]) -> bool:
        """Verify answer contains references to source files."""
        if not sources:
            return False
        # Check if any source filename or path appears in the answer
        for src in sources:
            # Check both full relative_path and just the filename
            if src in answer:
                return True
            # Extract filename and check
            fname = src.replace("\\", "/").split("/")[-1]
            if fname and fname in answer:
                return True
        return False
