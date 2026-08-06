"""Visible response and safe-failure nodes."""

import json
import re

from pydantic import ValidationError

from buildguard.agent.nodes.prompts import load_prompt
from buildguard.agent.state import AgentState
from buildguard.llm.base import ChatMessage, LocalLLMBackend
from buildguard.rag.advanced.answer_grounding import AnswerGrounder, GroundingResult
from buildguard.rag.schemas import DocumentChunk

NORMATIVE_TERMS = ("必须", "应当", "严禁", "不得", "禁止", "规范", "标准")
MODEL_TERMS = ("yolo", "rt-detr", "rtdetr", "grounding", "mobileclip", "sam")


def _multisource_grounding(
    state: AgentState,
    answer: str,
    grounder: AnswerGrounder,
    evidence_chunks: list[DocumentChunk],
) -> GroundingResult:
    """Validate each claim against its authoritative source type."""

    inspections = state.get("inspection_results", [])
    risks = state.get("risk_results", [])
    if not inspections and not risks:
        return grounder.validate(answer, evidence_chunks)

    actual_models = {
        inspection.model_name.casefold()
        for inspection in inspections
    } | {
        detection.source_model.casefold()
        for inspection in inspections
        for detection in inspection.detections
    }
    confidences = [
        detection.confidence
        for inspection in state["inspection_results"]
        for detection in inspection.detections
    ]
    risk_scores = [item.score for item in risks]
    risk_levels = {item.severity.value for item in risks}
    supported: list[str] = []
    unsupported: list[str] = []
    issues: dict[str, list[str]] = {}
    for sentence in grounder._sentences(answer):
        reasons: list[str] = []
        normalized = sentence.casefold()
        is_normative = any(term in sentence for term in NORMATIVE_TERMS)
        has_chunk_citation = any(chunk.chunk_id in sentence for chunk in evidence_chunks)
        if is_normative or has_chunk_citation:
            rag_result = grounder.validate(sentence, evidence_chunks)
            if rag_result.unsupported_claims:
                reasons.extend(
                    reason
                    for values in rag_result.issues.values()
                    for reason in values
                    if not reason.startswith("insufficient_lexical_support")
                )

        mentioned_model_terms = [term for term in MODEL_TERMS if term in normalized]
        if mentioned_model_terms and not any(
            model in normalized or normalized_model in normalized
            for model in actual_models
            for normalized_model in (model.replace("_", "-"),)
        ):
            reasons.append("unverified_visual_model")

        for raw in re.findall(r"(?:置信度|confidence)\s*[:：]?\s*(0(?:\.\d+)?|1(?:\.0+)?)", normalized):
            value = float(raw)
            if not any(abs(value - expected) <= 0.005 for expected in confidences):
                reasons.append(f"unverified_confidence:{raw}")
        for raw in re.findall(r"(?:风险(?:分数)?|risk score)\s*[:：]?\s*(0(?:\.\d+)?|1(?:\.0+)?)", normalized):
            value = float(raw)
            if not any(abs(value - expected) <= 0.005 for expected in risk_scores):
                reasons.append(f"unverified_risk_score:{raw}")
        claimed_levels = {
            level
            for level, terms in {
                "critical": ("critical", "危急风险"),
                "high": ("high risk", "高风险"),
                "normal": ("normal risk", "一般风险"),
                "low": ("low risk", "低风险"),
            }.items()
            if any(term in normalized for term in terms)
        }
        if claimed_levels and not claimed_levels.issubset(risk_levels):
            reasons.append("risk_level_mismatch")

        if reasons:
            unsupported.append(sentence)
            issues[sentence] = list(dict.fromkeys(reasons))
        else:
            supported.append(sentence)
    final = "".join(supported).strip()
    if not final:
        final = grounder.config.refusal_message
    return GroundingResult(
        supported_claims=supported,
        unsupported_claims=unsupported,
        final_safe_answer=final,
        issues=issues,
    )


def _rag_evidence(state: AgentState) -> tuple[bool, list[DocumentChunk]]:
    """Return whether RAG participated and only fully validated source chunks."""
    rag_used = False
    chunks: list[DocumentChunk] = []
    seen: set[str] = set()
    for result in state["tool_results"]:
        output = result.output if result.success else None
        if not isinstance(output, dict):
            continue
        if "chunks" not in output and "evidence_status" not in output:
            continue
        rag_used = True
        for raw in output.get("chunks", []):
            if not isinstance(raw, dict):
                continue
            try:
                chunk = DocumentChunk.model_validate(raw)
            except ValidationError:
                continue
            if chunk.chunk_id not in seen:
                chunks.append(chunk)
                seen.add(chunk.chunk_id)
    return rag_used, chunks


def generate_response(
    state: AgentState,
    backend: LocalLLMBackend,
    grounder: AnswerGrounder | None = None,
) -> dict[str, object]:
    intent = state["intent"]
    thinking = bool(intent and intent.complexity == "multi_step")
    successful = [
        item.output for item in state["tool_results"] if item.success and item.output is not None
    ]
    result_context = json.dumps(
        successful,
        ensure_ascii=False,
        default=str,
        separators=(",", ":"),
    )[:6_000]
    memory_context = "\n".join(
        f"{item.role}: {item.content}" for item in state["memory_messages"][-8:]
    )[:2_000]
    prompt = (
        f"{load_prompt('response.txt')}\nUser query: {state['user_query']}\n"
        f"Successful tool results ({len(successful)}): {result_context}\n"
        f"Relevant conversation memory: {memory_context}\n"
        "Use only the supplied local tool evidence for factual claims. Preserve source "
        "and citation identifiers when present; state uncertainty explicitly. "
        "Detection labels, confidences, source models, review flags, risk levels and "
        "risk scores must be copied exactly and never inferred. Cite regulatory claims "
        "with the retrieved chunk_id. Do not name a vision model unless it appears in "
        "the tool facts."
    )
    response = backend.chat(
        [ChatMessage(role="user", content=prompt)],
        thinking=thinking,
        profile="normal_dialogue",
    )
    final_response = response.content
    grounding_result = None
    rag_used, evidence_chunks = _rag_evidence(state)
    if grounder is not None and (
        rag_used
        or state.get("inspection_results", [])
        or state.get("risk_results", [])
    ):
        grounding_result = _multisource_grounding(
            state,
            response.content,
            grounder,
            evidence_chunks,
        )
        final_response = grounding_result.final_safe_answer
    return {
        "final_response": final_response,
        "grounding_result": grounding_result,
        "status": "completed",
        "performance_trace": [*state["performance_trace"], response.metrics],
    }


def safe_failure(state: AgentState) -> dict[str, object]:
    reason = (
        state["errors"][-1] if state["errors"] else "The local task could not be completed safely."
    )
    return {
        "final_response": f"Safe failure: {reason}",
        "status": "safe_failure",
        "pending_confirmation": None,
    }


def wait_for_confirmation(state: AgentState) -> dict[str, object]:
    message = state["pending_confirmation"]
    return {
        "final_response": str(message["message"]) if message else "Confirmation required.",
        "status": "WAIT_FOR_CONFIRMATION",
    }
