"""Execute RAG questions through retrieval, generation, grounding, and refusal."""

from __future__ import annotations

import time
from pathlib import Path

import orjson
from pydantic import Field

from buildguard.config import Settings
from buildguard.llm.base import ChatMessage, LocalLLMBackend
from buildguard.rag.advanced.answer_grounding import AnswerGrounder
from buildguard.rag.schemas import RagSearchInput
from buildguard.rag.service import RagService
from buildguard.schemas.common import StrictSchema


class RagCaseInput(StrictSchema):
    case_id: str = Field(min_length=1, max_length=256)
    question: str = Field(min_length=1, max_length=4000)
    answerable: bool
    relevant_chunk_ids: list[str] = Field(default_factory=list)
    expected_standard: str = ""
    expected_article: str = ""
    forbidden_outdated_sources: list[str] = Field(default_factory=list)


class RagCaseResult(StrictSchema):
    case_id: str
    relevant_chunk_ids: list[str]
    retrieved_chunk_ids: list[str]
    reranked_chunk_ids: list[str]
    citation_supported: bool
    claim_supported: bool
    expected_refusal: bool
    actual_refusal: bool
    outdated_source_used: bool
    latency_ms: float = Field(ge=0)
    failure_reason: str | None = None


class RagHarnessSummary(StrictSchema):
    total_cases: int = Field(ge=0)
    executed_cases: int = Field(ge=0)
    resumed_cases: int = Field(ge=0)
    succeeded_cases: int = Field(ge=0)
    failed_cases: int = Field(ge=0)
    result_path: Path


def _records(path: Path, schema: type[StrictSchema]) -> list[StrictSchema]:
    result: list[StrictSchema] = []
    for line_number, line in enumerate(path.read_bytes().splitlines(), start=1):
        if not line.strip():
            continue
        try:
            result.append(schema.model_validate(orjson.loads(line)))
        except (orjson.JSONDecodeError, ValueError) as exc:
            raise ValueError(f"Invalid JSONL line {line_number}: {exc}") from exc
    return result


class RagEvaluationHarness:
    def __init__(
        self,
        settings: Settings,
        service: RagService,
        backend: LocalLLMBackend,
    ) -> None:
        self.settings = settings
        self.service = service
        self.backend = backend

    def _execute(self, case: RagCaseInput) -> RagCaseResult:
        started = time.perf_counter()
        search = self.service.search(
            RagSearchInput(query=case.question, top_k=self.settings.rag.final_top_k)
        )
        chunk_ids = [chunk.chunk_id for chunk in search.chunks]
        refusal = search.evidence_status == "insufficient_evidence"
        claim_supported = False
        if refusal:
            answer = self.settings.rag.advanced.refusal_message
        else:
            evidence = "\n".join(
                f"[{chunk.chunk_id}] {chunk.content}" for chunk in search.chunks
            )
            answer = self.backend.chat(
                [
                    ChatMessage(
                        role="user",
                        content=(
                            "Answer strictly from the supplied evidence. "
                            "Return exactly one concise answer sentence. "
                            "For a multiple-choice question, state only the "
                            "correct option text. Append one supporting "
                            "citation in the form [chunk_id] to that sentence. "
                            "Do not repeat the question or evidence. "
                            "Do not output headings or labels such as "
                            "Answer, Evidence, Reason, or Explanation. "
                            "Do not add any claim not explicitly supported "
                            "by the evidence.\n"
                            f"Question: {case.question}\n"
                            f"Evidence:\n{evidence}"
                        ),
                    )
                ],
                profile="normal_dialogue",
            ).content
            grounded = AnswerGrounder(self.settings.rag.advanced).validate(
                answer, search.chunks
            )
            answer = grounded.final_safe_answer
            claim_supported = bool(grounded.supported_claims) and not (
                grounded.unsupported_claims
            )
            refusal = answer == self.settings.rag.advanced.refusal_message
        citation_supported = all(
            citation.chunk_id in chunk_ids for citation in search.citations
        )
        forbidden = {item.casefold() for item in case.forbidden_outdated_sources}
        outdated = any(
            chunk.document_name.casefold() in forbidden
            or str(chunk.source_path).casefold() in forbidden
            for chunk in search.chunks
        )
        expected_refusal = not case.answerable
        failures: list[str] = []
        if refusal != expected_refusal:
            failures.append("refusal mismatch")
        if outdated:
            failures.append("forbidden outdated source used")
        if not citation_supported:
            failures.append("citation does not resolve to retrieved evidence")
        if not refusal and not claim_supported:
            failures.append("generated claims are not fully grounded")
        return RagCaseResult(
            case_id=case.case_id,
            relevant_chunk_ids=case.relevant_chunk_ids,
            retrieved_chunk_ids=search.retrieved_chunk_ids,
            reranked_chunk_ids=search.reranked_chunk_ids,
            citation_supported=citation_supported,
            claim_supported=claim_supported,
            expected_refusal=expected_refusal,
            actual_refusal=refusal,
            outdated_source_used=outdated,
            latency_ms=(time.perf_counter() - started) * 1000,
            failure_reason="; ".join(failures) if failures else None,
        )

    def run(
        self, cases_path: Path, result_path: Path, *, resume: bool = True
    ) -> RagHarnessSummary:
        cases = [
            RagCaseInput.model_validate(item)
            for item in _records(cases_path.resolve(), RagCaseInput)
        ]
        target = result_path.resolve()
        target.parent.mkdir(parents=True, exist_ok=True)
        existing = (
            [
                RagCaseResult.model_validate(item)
                for item in _records(target, RagCaseResult)
            ]
            if resume and target.is_file()
            else []
        )
        completed = {item.case_id for item in existing}
        executed: list[RagCaseResult] = []
        with target.open("ab") as stream:
            for case in cases:
                if case.case_id in completed:
                    continue
                try:
                    record = self._execute(case)
                except (OSError, RuntimeError, ValueError, KeyError) as exc:
                    record = RagCaseResult(
                        case_id=case.case_id,
                        relevant_chunk_ids=case.relevant_chunk_ids,
                        retrieved_chunk_ids=[],
                        reranked_chunk_ids=[],
                        citation_supported=False,
                        claim_supported=False,
                        expected_refusal=not case.answerable,
                        actual_refusal=False,
                        outdated_source_used=False,
                        latency_ms=0,
                        failure_reason=str(exc),
                    )
                stream.write(orjson.dumps(record.model_dump(mode="json")) + b"\n")
                stream.flush()
                executed.append(record)
        records = [*existing, *executed]
        succeeded = sum(item.failure_reason is None for item in records)
        return RagHarnessSummary(
            total_cases=len(cases),
            executed_cases=len(executed),
            resumed_cases=len(existing),
            succeeded_cases=succeeded,
            failed_cases=len(records) - succeeded,
            result_path=target,
        )
