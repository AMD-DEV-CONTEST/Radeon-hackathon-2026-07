"""Bounded, auditable XiangLens agent graph."""

from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass
from typing import Any, Literal, TypeVar

from langgraph.graph import END, START, StateGraph
from pydantic import BaseModel, ValidationError

from xianglens.agent.state import XiangLensState
from xianglens.inference.llama_client import (
    ModelClient,
    ModelRequestError,
    parse_json_object,
)
from xianglens.schemas import (
    CandidateComparison,
    MemoryProposalDraft,
    StructuredReportDraft,
    VisualObservation,
)
from xianglens.storage.knowledge_store import KnowledgeStore
from xianglens.storage.sqlite_store import SQLiteStore
from xianglens.tools.image_tools import ImageInspector


@dataclass(slots=True)
class GraphServices:
    model: ModelClient
    knowledge: KnowledgeStore
    database: SQLiteStore
    image_inspector: ImageInspector
    rag_top_k: int = 4


SENSITIVE_PATTERNS = (
    r"\binfer\s+(?:my|their|his|her)?\s*personality\b",
    r"\bguess\s+(?:my|their|his|her)?\s*(?:ethnicity|race|religion|politics)\b",
    r"\b(?:criminality|sexual orientation|medical diagnosis|intelligence score)\b",
    r"\bpredict\s+(?:my|their|his|her)?\s*(?:future|destiny|wealth|lifespan)\b",
)

EXPLICIT_MEMORY_PATTERNS = (
    r"\bremember\b",
    r"\bkeep (?:this|that|it) in mind\b",
    r"\bi prefer\b",
    r"\bmy\s+[a-z0-9 -]{1,50}\s+(?:is|are)\b",
    r"\bdo not treat\b",
    r"\bi (?:always|never)\b",
)

SENSITIVE_MEMORY_TERMS = (
    "medical",
    "disease",
    "diagnosis",
    "religion",
    "politics",
    "sexual orientation",
    "ethnicity",
    "criminal",
    "pregnancy",
)

ModelSchema = TypeVar("ModelSchema", bound=BaseModel)


def _trace(
    state: XiangLensState,
    *,
    node: str,
    tool: str,
    started: float,
    summary: str,
    status: str = "completed",
) -> list[dict[str, Any]]:
    return [
        *state.get("tool_trace", []),
        {
            "node": node,
            "tool": tool,
            "status": status,
            "duration_ms": round((time.perf_counter() - started) * 1000, 2),
            "summary": summary,
        },
    ]


def _explicit_memory_candidate(message: str) -> bool:
    lowered = message.lower()
    return any(re.search(pattern, lowered) for pattern in EXPLICIT_MEMORY_PATTERNS) and not any(
        term in lowered for term in SENSITIVE_MEMORY_TERMS
    )


def _render_bullets(items: list[str], fallback: str) -> str:
    values = [item.strip() for item in items if item.strip()]
    return "\n".join(f"- {item}" for item in values) if values else f"- {fallback}"


def _render_report(
    report: StructuredReportDraft,
    evidence: list[dict[str, Any]],
    comparison: dict[str, Any] | None,
    proposal: dict[str, Any] | None,
) -> str:
    known_cards = {card["card_id"]: card for card in evidence}
    cited = [known_cards[card_id] for card_id in report.cited_card_ids if card_id in known_cards]
    if not cited:
        cited = evidence

    sections = [
        "# XiangLens Review",
        report.summary.strip(),
        "## Observed",
        _render_bullets(report.observed, "No additional visible fact was asserted."),
    ]
    if comparison:
        comparison_lines = []
        for candidate in comparison["candidates"]:
            comparison_lines.append(
                f"- `{candidate['image_id']}` — crop {candidate['crop_resilience']}/5, "
                f"small-size clarity {candidate['small_size_clarity']}/5, privacy "
                f"{candidate['privacy_safety']}/5, intent {candidate['intent_alignment']}/5, "
                f"ambiguity {candidate['contextual_ambiguity']}/5. {candidate['rationale']}"
            )
        sections.extend(
            [
                "## Comparison",
                f"Recommended image: `{comparison['recommended_image_id']}`.",
                *comparison_lines,
                f"Decision rule: {comparison['decision_rule']}",
            ]
        )
        if comparison.get("caveat"):
            sections.append(f"Caveat: {comparison['caveat']}")

    sections.extend(
        [
            "## Privacy",
            _render_bullets(report.privacy, "No specific privacy risk was confirmed."),
            "## Context",
            _render_bullets(report.context, "No additional contextual claim was required."),
            "## Recommendation",
            _render_bullets(report.recommendations, "Review the image at the target avatar size."),
            "## Evidence",
        ]
    )
    if cited:
        sections.extend(
            f"- [{card['source_title']}]({card['source_url']}) — {card['text']} "
            f"(`{card['card_id']}`)"
            for card in cited
        )
    else:
        sections.append("- No knowledge card was available for this claim.")

    if proposal:
        sections.extend(
            [
                "## Memory Proposal",
                f"Pending approval: “{proposal['text']}”",
                f"Reason: {proposal['reason']}",
                "This proposal has not been added to long-term memory.",
            ]
        )
    sections.extend(
        [
            "## Limitations",
            _render_bullets(
                report.limitations,
                "This review evaluates the supplied goals, not identity or personality.",
            ),
        ]
    )
    return "\n\n".join(sections).strip()


def build_graph(services: GraphServices):
    async def validated_model_json(
        messages: list[dict[str, Any]], schema: type[ModelSchema], max_tokens: int
    ) -> ModelSchema:
        raw = await services.model.chat(messages, temperature=0.1, max_tokens=max_tokens)
        last_error = "unknown validation error"
        for attempt in range(2):
            try:
                return schema.model_validate(parse_json_object(raw))
            except (ModelRequestError, ValidationError) as exc:
                last_error = str(exc)
                if attempt == 1:
                    break
                raw = await services.model.chat(
                    [
                        *messages,
                        {"role": "assistant", "content": raw},
                        {
                            "role": "user",
                            "content": (
                                "The response failed validation. Return only one valid JSON object "
                                f"for schema {schema.__name__}. Error: {last_error[:500]}"
                            ),
                        },
                    ],
                    temperature=0.0,
                    max_tokens=max_tokens,
                )
        raise ModelRequestError(f"Model JSON failed validation after one repair: {last_error}")

    async def intake(state: XiangLensState) -> dict[str, Any]:
        started = time.perf_counter()
        plan = [
            "Apply the sensitive-inference policy gate.",
            "Recall only user-approved preferences and prior thread context.",
            "Measure each image and scan local metadata and QR evidence.",
            "Observe visible, non-sensitive image facts with the self-hosted vision model.",
            "Retrieve up to four source-backed cards from enabled Lens Packs.",
            "Compare multiple candidates with one transparent five-dimension rubric.",
            "Propose reusable memory only from an explicit user statement.",
            "Render a structured goal-relative report with code-controlled citations.",
        ]
        return {
            "plan": plan,
            "tool_trace": _trace(
                state,
                node="intake",
                tool="bounded_planner",
                started=started,
                summary=(
                    f"Created a fixed eight-step plan for {len(state['image_paths'])} image(s)."
                ),
            ),
        }

    async def policy_gate(state: XiangLensState) -> dict[str, Any]:
        started = time.perf_counter()
        message = state["message"].lower()
        blocked = any(re.search(pattern, message) for pattern in SENSITIVE_PATTERNS)
        reason = None
        if blocked:
            reason = (
                "XiangLens cannot infer sensitive attributes, personality, intelligence, health, "
                "criminality, wealth, relationships, politics, religion, or destiny from an image."
            )
        return {
            "blocked_reason": reason,
            "tool_trace": _trace(
                state,
                node="policy_gate",
                tool="sensitive_inference_policy",
                started=started,
                summary=(
                    "Request blocked by policy." if blocked else "Request is within product scope."
                ),
                status="blocked" if blocked else "completed",
            ),
        }

    def route_policy(state: XiangLensState) -> Literal["blocked_report", "recall_context"]:
        return "blocked_report" if state.get("blocked_reason") else "recall_context"

    async def blocked_report(state: XiangLensState) -> dict[str, Any]:
        return {
            "measurements": [],
            "visual_observations": [],
            "privacy_findings": [],
            "evidence": [],
            "recalled_memories": [],
            "comparison": None,
            "memory_proposal_draft": None,
            "report_markdown": (
                "## Request not analyzed\n\n"
                f"{state['blocked_reason']}\n\n"
                "I can instead evaluate crop resilience, visible privacy risks, "
                "small-size clarity, platform requirements, or fit with goals you provide."
            ),
        }

    async def recall_context(state: XiangLensState) -> dict[str, Any]:
        started = time.perf_counter()
        memories = services.database.list_memories(state["user_id"], limit=8)
        history = services.database.list_messages(state["thread_id"], limit=8)
        return {
            "recalled_memories": memories,
            "history": history,
            "tool_trace": _trace(
                state,
                node="recall_context",
                tool="sqlite_memory",
                started=started,
                summary=f"Recalled {len(memories)} approved memories and {len(history)} messages.",
            ),
        }

    async def inspect_local(state: XiangLensState) -> dict[str, Any]:
        started = time.perf_counter()
        measurements: list[dict[str, Any]] = []
        findings: list[dict[str, Any]] = []
        for path in state["image_paths"]:
            measurement, image_findings = services.image_inspector.inspect(path)
            measurements.append(measurement)
            findings.extend({"image_id": path.stem, **finding} for finding in image_findings)
        return {
            "measurements": measurements,
            "privacy_findings": findings,
            "tool_trace": _trace(
                state,
                node="inspect_local",
                tool="image_measurement_and_privacy_scan",
                started=started,
                summary=(
                    f"Measured {len(measurements)} image(s) and produced "
                    f"{len(findings)} local finding(s)."
                ),
            ),
        }

    async def observe_visual(state: XiangLensState) -> dict[str, Any]:
        started = time.perf_counter()
        prompt = (
            "Return a JSON object with keys visible_elements, composition, text_candidates, "
            "privacy_candidates, and uncertainties. Every list value must contain short strings. "
            "Describe only directly visible evidence. "
            f"The user selected platform '{state['platform']}', audience '{state['audience']}', "
            f"and goals {state['intent_keywords']}. Do not identify a person or "
            "infer sensitive traits."
        )
        observations = []
        visual_findings = list(state.get("privacy_findings", []))
        for path in state["image_paths"]:
            raw = await services.model.inspect_image(path, prompt)
            observation = VisualObservation.model_validate(raw)
            observations.append({"image_id": path.stem, **observation.model_dump()})
            visual_findings.extend(
                {
                    "image_id": path.stem,
                    "type": "visual_privacy_candidate",
                    "severity": "medium",
                    "observable": True,
                    "summary": candidate,
                    "recommendation": "Confirm the visible detail before sharing the image.",
                }
                for candidate in observation.privacy_candidates
            )
        return {
            "visual_observations": observations,
            "privacy_findings": visual_findings,
            "tool_trace": _trace(
                state,
                node="observe_visual",
                tool="self_hosted_vlm",
                started=started,
                summary=(
                    f"Validated structured observations for {len(observations)} image(s) "
                    "with the configured Radeon endpoint."
                ),
            ),
        }

    async def retrieve_evidence(state: XiangLensState) -> dict[str, Any]:
        started = time.perf_counter()
        finding_types = [item.get("type", "") for item in state.get("privacy_findings", [])]
        visual_terms = [
            item
            for observation in state.get("visual_observations", [])
            for item in observation.get("visible_elements", [])[:5]
        ]
        query = " ".join(
            [
                state["message"],
                state["platform"],
                state["audience"],
                *state["intent_keywords"],
                *finding_types,
                *visual_terms,
            ]
        )
        cards = services.knowledge.search(query, state["enabled_packs"], limit=services.rag_top_k)
        evidence = [card.model_dump() for card in cards]
        return {
            "evidence": evidence,
            "tool_trace": _trace(
                state,
                node="retrieve_evidence",
                tool="milvus_lite",
                started=started,
                summary=f"Retrieved {len(evidence)} source-backed knowledge card(s).",
            ),
        }

    async def compare_candidates(state: XiangLensState) -> dict[str, Any]:
        started = time.perf_counter()
        if len(state["image_paths"]) < 2:
            return {
                "comparison": None,
                "tool_trace": _trace(
                    state,
                    node="compare_candidates",
                    tool="transparent_comparison_rubric",
                    started=started,
                    summary="Comparison skipped for a single image.",
                    status="skipped",
                ),
            }
        image_ids = [path.stem for path in state["image_paths"]]
        context = {
            "image_ids": image_ids,
            "platform": state["platform"],
            "audience": state["audience"],
            "goals": state["intent_keywords"],
            "measurements": state.get("measurements", []),
            "observations": state.get("visual_observations", []),
            "privacy_findings": state.get("privacy_findings", []),
        }
        comparison = await validated_model_json(
            [
                {
                    "role": "system",
                    "content": (
                        "Compare every supplied image with the same five dimensions, each scored "
                        "from 0 to 5: crop_resilience, small_size_clarity, privacy_safety, "
                        "intent_alignment, and contextual_ambiguity. A privacy risk overrides the "
                        "aggregate score. Higher contextual_ambiguity means more ambiguity. "
                        "Use only "
                        "the supplied image IDs. Return only JSON matching CandidateComparison."
                    ),
                },
                {"role": "user", "content": json.dumps(context, ensure_ascii=False)},
            ],
            CandidateComparison,
            1200,
        )
        candidate_ids = {candidate.image_id for candidate in comparison.candidates}
        if candidate_ids != set(image_ids) or comparison.recommended_image_id not in candidate_ids:
            raise ModelRequestError("The comparison did not cover exactly the supplied image IDs")
        return {
            "comparison": comparison.model_dump(),
            "tool_trace": _trace(
                state,
                node="compare_candidates",
                tool="transparent_comparison_rubric",
                started=started,
                summary=f"Compared {len(image_ids)} images with five visible dimensions.",
            ),
        }

    async def propose_memory(state: XiangLensState) -> dict[str, Any]:
        started = time.perf_counter()
        if not _explicit_memory_candidate(state["message"]):
            return {
                "memory_proposal_draft": None,
                "tool_trace": _trace(
                    state,
                    node="propose_memory",
                    tool="consent_first_memory",
                    started=started,
                    summary="No explicit reusable user statement was detected.",
                    status="skipped",
                ),
            }
        proposal = await validated_model_json(
            [
                {
                    "role": "system",
                    "content": (
                        "Extract one reusable fact stated explicitly by the user. Do not infer or "
                        "add details. Return JSON with text, memory_type, and reason. Use "
                        "memory_type preference, goal, correction, or outcome. This is only a "
                        "proposal; it will "
                        "require approval before storage."
                    ),
                },
                {"role": "user", "content": state["message"]},
            ],
            MemoryProposalDraft,
            350,
        )
        if any(term in proposal.text.lower() for term in SENSITIVE_MEMORY_TERMS):
            return {
                "memory_proposal_draft": None,
                "tool_trace": _trace(
                    state,
                    node="propose_memory",
                    tool="consent_first_memory",
                    started=started,
                    summary="A sensitive memory proposal was discarded.",
                    status="blocked",
                ),
            }
        return {
            "memory_proposal_draft": proposal.model_dump(),
            "tool_trace": _trace(
                state,
                node="propose_memory",
                tool="consent_first_memory",
                started=started,
                summary="Created one pending memory proposal without writing long-term memory.",
            ),
        }

    async def synthesize_report(state: XiangLensState) -> dict[str, Any]:
        started = time.perf_counter()
        context = {
            "request": state["message"],
            "platform": state["platform"],
            "audience": state["audience"],
            "goals": state["intent_keywords"],
            "recent_thread_messages": state.get("history", [])[-6:],
            "measurements": state.get("measurements", []),
            "visual_observations": state.get("visual_observations", []),
            "privacy_findings": state.get("privacy_findings", []),
            "approved_memories": [
                {"type": item["memory_type"], "text": item["text"]}
                for item in state.get("recalled_memories", [])
            ],
            "comparison": state.get("comparison"),
            "evidence": state.get("evidence", []),
        }
        report = await validated_model_json(
            [
                {
                    "role": "system",
                    "content": (
                        "Create a concise XiangLens report draft. Return only JSON matching "
                        "StructuredReportDraft with summary, observed, privacy, context, "
                        "recommendations, limitations, and cited_card_ids. Separate facts from "
                        "interpretation. Base recommendations only on user goals. Cite only "
                        "card IDs present in evidence. Never infer identity or sensitive traits. "
                        "Never treat a "
                        "cultural association as universal."
                    ),
                },
                {
                    "role": "user",
                    "content": "Synthesize this verified run context:\n"
                    + json.dumps(context, ensure_ascii=False),
                },
            ],
            StructuredReportDraft,
            1400,
        )
        known_ids = {card["card_id"] for card in state.get("evidence", [])}
        report = report.model_copy(
            update={
                "cited_card_ids": [
                    card_id for card_id in report.cited_card_ids if card_id in known_ids
                ]
            }
        )
        rendered = _render_report(
            report,
            state.get("evidence", []),
            state.get("comparison"),
            state.get("memory_proposal_draft"),
        )
        return {
            "structured_report": report.model_dump(),
            "report_markdown": rendered,
            "tool_trace": _trace(
                state,
                node="synthesize_report",
                tool="self_hosted_llm_and_safe_renderer",
                started=started,
                summary="Validated structured output and rendered code-controlled citations.",
            ),
        }

    builder = StateGraph(XiangLensState)
    builder.add_node("intake", intake)
    builder.add_node("policy_gate", policy_gate)
    builder.add_node("blocked_report", blocked_report)
    builder.add_node("recall_context", recall_context)
    builder.add_node("inspect_local", inspect_local)
    builder.add_node("observe_visual", observe_visual)
    builder.add_node("retrieve_evidence", retrieve_evidence)
    builder.add_node("compare_candidates", compare_candidates)
    builder.add_node("propose_memory", propose_memory)
    builder.add_node("synthesize_report", synthesize_report)

    builder.add_edge(START, "intake")
    builder.add_edge("intake", "policy_gate")
    builder.add_conditional_edges("policy_gate", route_policy)
    builder.add_edge("blocked_report", END)
    builder.add_edge("recall_context", "inspect_local")
    builder.add_edge("inspect_local", "observe_visual")
    builder.add_edge("observe_visual", "retrieve_evidence")
    builder.add_edge("retrieve_evidence", "compare_candidates")
    builder.add_edge("compare_candidates", "propose_memory")
    builder.add_edge("propose_memory", "synthesize_report")
    builder.add_edge("synthesize_report", END)
    return builder.compile()
